# -*- coding: utf-8 -*-
"""
Processamento das ordens de serviço: gera os PDFs (reaproveitando gerar_cartas.py),
monta ZIPs para download e apaga os PDFs vencidos (48 h), preservando a planilha original.
"""
import io
import os
import shutil
import sys
import threading
import time
import zipfile
from datetime import datetime, timedelta

from db import DIR_DADOS, DIR_OS, agora, conectar

DIR_TMP = os.path.join(DIR_DADOS, "tmp")  # ZIPs de download em trânsito

# gerar_cartas.py fica na pasta acima de webapp/
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
import gerar_cartas  # noqa: E402

HORAS_RETENCAO = 48
FMT = "%Y-%m-%d %H:%M:%S"


def pasta_os(os_id):
    return os.path.join(DIR_OS, f"{os_id:06d}")


def pasta_pdfs(os_id):
    return os.path.join(pasta_os(os_id), "pdfs")


def caminho_original(os_id, nome_arquivo):
    return os.path.join(pasta_os(os_id), "original_" + nome_arquivo)


def processar_os(os_id):
    """Roda em thread: lê a planilha da OS, gera os PDFs e grava as cartas no banco."""
    con = conectar()
    try:
        ordem = con.execute("SELECT * FROM ordens_servico WHERE id = ?", (os_id,)).fetchone()
        origem = caminho_original(os_id, ordem["arquivo_original"])
        destino = pasta_pdfs(os_id)
        if os.path.isdir(destino):
            shutil.rmtree(destino)
        os.makedirs(destino, exist_ok=True)

        gerar_cartas.registrar_fontes()
        cartas = gerar_cartas.ler_planilha(origem)
        if not cartas:
            raise ValueError("A planilha não tem nenhuma linha válida com MATRICULA.")

        gerados = gerar_cartas.gerar(origem, pasta_saida=destino, retrato=False, lote=True,
                                     nome_base=ordem["numero"])  # LOTE_OS-2026-0001_27_cartas.pdf
        con.execute("DELETE FROM cartas WHERE os_id = ?", (os_id,))
        for seq, (carta, arq) in enumerate(zip(cartas, gerados), start=1):
            con.execute(
                "INSERT INTO cartas (os_id, seq, matricula, nome, cpf, cidade, uf, qtd_boletos, total, arquivo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (os_id, seq, carta["matricula"], carta["nome"], carta["cpf"], carta["cidade"], carta["uf"],
                 len(carta["boletos"]), float(carta["total"]), os.path.basename(arq)),
            )
        qtd_linhas = sum(len(c["boletos"]) for c in cartas)
        expira = (datetime.now() + timedelta(hours=HORAS_RETENCAO)).strftime(FMT)
        con.execute(
            "UPDATE ordens_servico SET status = 'concluida', concluido_em = ?, qtd_cartas = ?, qtd_linhas = ?, "
            "expira_em = ?, erro = NULL WHERE id = ?",
            (agora(), len(cartas), qtd_linhas, expira, os_id),
        )
        con.commit()
    except Exception as e:  # noqa: BLE001
        con.execute("UPDATE ordens_servico SET status = 'erro', erro = ?, concluido_em = ? WHERE id = ?",
                    (str(e)[:1000], agora(), os_id))
        con.commit()
    finally:
        con.close()


def iniciar_processamento(os_id):
    t = threading.Thread(target=processar_os, args=(os_id,), daemon=True, name=f"os-{os_id}")
    t.start()
    return t


def arquivo_lote(os_id):
    pasta = pasta_pdfs(os_id)
    if not os.path.isdir(pasta):
        return None
    for n in os.listdir(pasta):
        if n.startswith("LOTE_") and n.lower().endswith(".pdf"):
            return os.path.join(pasta, n)
    return None


def montar_zip(os_id, arquivos, incluir_lote=False):
    """Monta um ZIP em arquivo temporário (não em memória) com os PDFs escolhidos e devolve o caminho."""
    import tempfile
    pasta = pasta_pdfs(os_id)
    os.makedirs(DIR_TMP, exist_ok=True)
    fd, caminho_zip = tempfile.mkstemp(prefix=f"os{os_id}_", suffix=".zip", dir=DIR_TMP)
    os.close(fd)
    with zipfile.ZipFile(caminho_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for nome in arquivos:
            caminho = os.path.join(pasta, os.path.basename(nome))
            if os.path.isfile(caminho):
                z.write(caminho, arcname=os.path.basename(nome))
        if incluir_lote:
            lote = arquivo_lote(os_id)
            if lote:
                z.write(lote, arcname=os.path.basename(lote))
    return caminho_zip


# ----------------------------------------------------------------------------
# Limpeza: PDFs vencem em 48 h. A planilha original e o registro da OS ficam.
# ----------------------------------------------------------------------------
def limpar_vencidos():
    con = conectar()
    try:
        agora_s = datetime.now().strftime(FMT)
        vencidas = con.execute(
            "SELECT id FROM ordens_servico WHERE status = 'concluida' AND pdfs_removidos_em IS NULL "
            "AND expira_em IS NOT NULL AND expira_em <= ?", (agora_s,)
        ).fetchall()
        for r in vencidas:
            pasta = pasta_pdfs(r["id"])
            if os.path.isdir(pasta):
                shutil.rmtree(pasta, ignore_errors=True)
            con.execute("UPDATE ordens_servico SET pdfs_removidos_em = ? WHERE id = ?", (agora(), r["id"]))
        if vencidas:
            con.commit()
        return len(vencidas)
    finally:
        con.close()


def retomar_interrompidas():
    """OS que ficaram 'processando' quando o servidor caiu são marcadas como erro (o usuário pode reprocessar)."""
    con = conectar()
    try:
        con.execute(
            "UPDATE ordens_servico SET status = 'erro', erro = 'Processamento interrompido (servidor reiniciado). "
            "Use Gerar novamente.' WHERE status = 'processando'"
        )
        con.commit()
    finally:
        con.close()


def limpar_zips_temporarios(idade_min_seg=900):
    """Apaga ZIPs de download já entregues (o Windows segura o arquivo até o envio terminar)."""
    import glob
    limite = time.time() - idade_min_seg
    for z in glob.glob(os.path.join(DIR_TMP, "os*_*.zip")):
        try:
            if os.path.getmtime(z) < limite:
                os.remove(z)
        except OSError:
            pass


def iniciar_limpeza_periodica(intervalo_seg=600):
    def loop():
        while True:
            try:
                limpar_vencidos()
                limpar_zips_temporarios()
            except Exception as e:  # noqa: BLE001
                print("[limpeza] erro:", e)
            time.sleep(intervalo_seg)
    threading.Thread(target=loop, daemon=True, name="limpeza-48h").start()
