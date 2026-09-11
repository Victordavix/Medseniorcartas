# -*- coding: utf-8 -*-
"""
Gerador de cartas de cobrança MedSênior (Notificação Extrajudicial com AR).

Lê a planilha enviada pelo cliente (uma linha por boleto), agrupa por MATRICULA
e gera, para cada beneficiário, um PDF A4 de 2 páginas:
  - Página 1 (frente): formulário AR dos Correios + envelope (destinatário/remetente)
  - Página 2 (verso) : carta "Ref.: NOTIFICAÇÃO EXTRAJUDICIAL" com a tabela de boletos

Os moldes fixos ficam em modelos/ (frente_retrato.jpg e verso_retrato.jpg) e os
dados variáveis são sobrepostos em posições medidas no exemplo aprovado.

Uso:
    python gerar_cartas.py                      -> processa todos os .xlsx de entrada/
    python gerar_cartas.py "caminho\\arquivo.xlsx"
    python gerar_cartas.py arquivo.xlsx --retrato   (páginas em pé, sem rotação)
    python gerar_cartas.py arquivo.xlsx --sem-lote  (não gera o PDF consolidado)
"""
import os
import re
import sys
import glob
import unicodedata
from datetime import datetime, date

import pandas as pd
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code39

BASE = os.path.dirname(os.path.abspath(__file__))
DIR_MODELOS = os.path.join(BASE, "modelos")
DIR_ENTRADA = os.path.join(BASE, "entrada")
DIR_SAIDA = os.path.join(BASE, "saida")
MOLDE_FRENTE = os.path.join(DIR_MODELOS, "frente_retrato.jpg")
MOLDE_VERSO = os.path.join(DIR_MODELOS, "verso_retrato.jpg")

PAGE_W, PAGE_H = A4  # retrato: 210 x 297 mm (todas as coordenadas abaixo são em mm, medidas do topo)

# ----------------------------------------------------------------------------
# Fontes (Windows). Calibri no corpo da carta, Arial no formulário AR/envelope.
# ----------------------------------------------------------------------------
FONTES = {  # nome usado no PDF -> (arquivo no Windows, arquivo embutido em fontes/ com as mesmas métricas)
    "Arial": ("arial.ttf", "LiberationSans-Regular.ttf"),
    "Arial-Bold": ("arialbd.ttf", "LiberationSans-Bold.ttf"),
    "Calibri": ("calibri.ttf", "Carlito-Regular.ttf"),
    "Calibri-Bold": ("calibrib.ttf", "Carlito-Bold.ttf"),
}
DIR_FONTES_EMBUTIDAS = os.path.join(BASE, "fontes")
_fontes_registradas = False


def registrar_fontes():
    """
    Registra as fontes no reportlab. Ordem de busca:
      1. pasta indicada em FONTES_DIR (se definida)
      2. fontes do Windows (Arial/Calibri originais)
      3. fontes embutidas em fontes/ (Liberation Sans = métricas da Arial; Carlito = métricas da Calibri),
         usadas em Linux/Railway. FONTES_EMBUTIDAS=1 força esta opção.
    """
    global _fontes_registradas
    if _fontes_registradas:
        return
    pastas = []
    if os.environ.get("FONTES_DIR"):
        pastas.append(os.environ["FONTES_DIR"])
    if os.environ.get("FONTES_EMBUTIDAS") != "1" and os.environ.get("WINDIR"):
        pastas.append(os.path.join(os.environ["WINDIR"], "Fonts"))
    pastas.append(DIR_FONTES_EMBUTIDAS)
    for nome, (arq_win, arq_emb) in FONTES.items():
        for pasta in pastas:
            for arq in (arq_win, arq_emb):
                caminho = os.path.join(pasta, arq)
                if os.path.exists(caminho):
                    pdfmetrics.registerFont(TTFont(nome, caminho))
                    break
            else:
                continue
            break
        else:
            raise FileNotFoundError(f"Fonte '{nome}' não encontrada em: {pastas}")
    _fontes_registradas = True


# ----------------------------------------------------------------------------
# Utilidades de texto / formatação
# ----------------------------------------------------------------------------
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def normaliza_coluna(s):
    s = sem_acento(s).upper().strip()
    s = re.sub(r"[^A-Z0-9_ ]", "?", s)   # caracteres quebrados (ex.: 'N�MERO') viram '?'
    return re.sub(r"\s+", " ", s)


def txt(v):
    """Converte célula em texto limpo (sem 'nan', sem '.0' em inteiros)."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == ""):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def digitos(v, largura=None):
    s = re.sub(r"\D", "", txt(v))
    if largura and s:
        s = s.zfill(largura)
    return s


def para_data(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return v if isinstance(v, date) else v.to_pydatetime()
    s = txt(v)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def para_float(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = txt(v).replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def fmt_moeda(v):
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def data_extenso(d):
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def competencia(v):
    """Mes_competencia -> 'MM-AAAA'."""
    d = para_data(v)
    if d:
        return f"{d.month:02d}-{d.year}"
    s = txt(v)
    m = re.match(r"(\d{4})[-/](\d{1,2})", s)
    if m:
        return f"{int(m.group(2)):02d}-{m.group(1)}"
    m = re.match(r"(\d{1,2})[-/](\d{4})", s)
    if m:
        return f"{int(m.group(1)):02d}-{m.group(2)}"
    return s


# ----------------------------------------------------------------------------
# Valor por extenso (formato do modelo: "Dois Mil Setecentos e Noventa e Nove
# Reais e Setenta e Oito Centavos")
# ----------------------------------------------------------------------------
_UNID = ["", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez",
         "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZ = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_CEN = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos",
        "setecentos", "oitocentos", "novecentos"]


def _ate_999(n):
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    partes = []
    c, r = divmod(n, 100)
    if c:
        partes.append(_CEN[c])
    if r:
        if r < 20:
            partes.append(_UNID[r])
        else:
            d, u = divmod(r, 10)
            partes.append(_DEZ[d] + (" e " + _UNID[u] if u else ""))
    return " e ".join(partes)


def _inteiro_extenso(n):
    if n == 0:
        return "zero"
    grupos = []  # (valor, singular, plural)
    escalas = [("", ""), ("mil", "mil"), ("milhão", "milhões"), ("bilhão", "bilhões")]
    i = 0
    while n > 0:
        n, g = divmod(n, 1000)
        if g:
            if i == 0:
                s = _ate_999(g)
            elif i == 1:
                s = ("mil" if g == 1 else _ate_999(g) + " mil")
            else:
                s = ("um " + escalas[i][0]) if g == 1 else _ate_999(g) + " " + escalas[i][1]
            grupos.append((g, s))
        i += 1
    grupos.reverse()
    # "e" só antes do último grupo quando ele é < 100 ou centena redonda
    out = grupos[0][1]
    for k in range(1, len(grupos)):
        g, s = grupos[k]
        ultimo = (k == len(grupos) - 1)
        if ultimo and (g < 100 or g % 100 == 0):
            out += " e " + s
        else:
            out += " " + s
    return out


def valor_extenso(valor):
    valor = round(valor + 1e-9, 2)
    reais = int(valor)
    cent = int(round((valor - reais) * 100))
    partes = []
    if reais:
        conector = " de" if reais >= 1_000_000 and reais % 1_000_000 == 0 else ""
        partes.append(_inteiro_extenso(reais) + conector + (" real" if reais == 1 else " reais"))
    if cent:
        partes.append(_inteiro_extenso(cent) + (" centavo" if cent == 1 else " centavos"))
    if not partes:
        partes.append("zero reais")
    texto = " e ".join(partes)
    # Title Case, mantendo o conectivo "e" minúsculo
    return " ".join(w if w in ("e", "de") else w[:1].upper() + w[1:] for w in texto.split(" "))


# ----------------------------------------------------------------------------
# Leitura da planilha
# ----------------------------------------------------------------------------
COLUNAS = {  # chave interna -> regex sobre o nome normalizado
    "matricula": r"^MATRICULA$",
    "nome": r"^NOME$",
    "endereco": r"^ENDERECO$",
    "complemento": r"^COMPLEMENTO$",
    "bairro": r"^BAIRRO$",
    "cidade": r"^CIDADE$",
    "cep": r"^CEP$",
    "uf": r"^UF$",
    "cpf": r"^CPF$",
    "plano_codigo": r"^PLANO CODIGO ANS$",
    "plano_desc": r"^PLANO DESCRICAO$",
    "boleto": r"^NOSSO N.?MERO BOLETO$",
    "vencimento": r"^VENCIMENTO BOLETO$",
    "valor_boleto": r"^VALOR BOLETO ATT$",
    "dias_atraso": r"^DIAS DE ATRASO BOLETO$",
    "mes_comp": r"^MES_COMPETENCIA$",
    "data_geracao": r"^DATA GERACAO ARQUIVO$",
    "numero_carta": r"^N.?MERO DA CARTA$",
    "div_total": r"^DIV_TOTAL_CALC$",
}
OBRIGATORIAS = ["matricula", "nome", "endereco", "cidade", "cep", "uf", "cpf",
                "plano_codigo", "plano_desc", "boleto", "vencimento", "valor_boleto",
                "dias_atraso", "mes_comp", "data_geracao"]


def ler_planilha(caminho):
    df = pd.read_excel(caminho, dtype=object)
    df = df.dropna(how="all")
    mapa = {}
    for col in df.columns:
        n = normaliza_coluna(col)
        for chave, rx in COLUNAS.items():
            if chave not in mapa and re.match(rx, n):
                mapa[chave] = col
    faltando = [c for c in OBRIGATORIAS if c not in mapa]
    if faltando:
        raise ValueError(f"Colunas não encontradas na planilha: {faltando}\nColunas lidas: {list(df.columns)}")

    cartas = []      # ordem de aparição
    por_matricula = {}
    for _, r in df.iterrows():
        g = lambda k: r[mapa[k]] if k in mapa else None
        matricula = digitos(g("matricula")) or txt(g("matricula"))
        if not matricula:
            continue
        venc = para_data(g("vencimento"))
        comp = competencia(g("mes_comp"))
        if not comp and venc:  # competência vazia na planilha: usa mês/ano do vencimento
            comp = f"{venc.month:02d}-{venc.year}"
        boleto = {
            "numero": txt(g("boleto")),
            "competencia": comp,
            "vencimento": venc,
            "dias": digitos(g("dias_atraso")) or txt(g("dias_atraso")),
            "valor": para_float(g("valor_boleto")),
        }
        if matricula not in por_matricula:
            carta = {
                "matricula": matricula,
                "nome": txt(g("nome")).upper(),
                "endereco": txt(g("endereco")).upper(),
                "complemento": "" if txt(g("complemento")).strip("0-. ") == "" else txt(g("complemento")).upper(),
                "bairro": txt(g("bairro")).upper(),
                "cidade": txt(g("cidade")).upper(),
                "cep": digitos(g("cep"), 8),
                "uf": txt(g("uf")).upper(),
                "cpf": digitos(g("cpf"), 11),
                "plano_codigo": digitos(g("plano_codigo")) or txt(g("plano_codigo")),
                "plano_desc": txt(g("plano_desc")),
                "data_geracao": para_data(g("data_geracao")) or datetime.today(),
                "numero_carta": txt(g("numero_carta")),
                "div_total": para_float(g("div_total")) if "div_total" in mapa else None,
                "boletos": [],
            }
            por_matricula[matricula] = carta
            cartas.append(carta)
        por_matricula[matricula]["boletos"].append(boleto)

    for c in cartas:
        soma = round(sum(b["valor"] for b in c["boletos"]), 2)
        c["total"] = c["div_total"] if c["div_total"] else soma
        c["boletos"].sort(key=lambda b: b["vencimento"] or datetime.max)
    return cartas


# ----------------------------------------------------------------------------
# Desenho
# ----------------------------------------------------------------------------
class Desenho:
    """Helper com coordenadas em mm medidas a partir do canto superior esquerdo (retrato)."""

    def __init__(self, c):
        self.c = c

    def texto(self, x, y, s, fonte="Arial", tam=8.5, max_larg=None, alinh="esq"):
        """Escreve s com linha-base em (x,y) mm. Reduz a fonte se ultrapassar max_larg (mm)."""
        if max_larg:
            while tam > 4 and pdfmetrics.stringWidth(s, fonte, tam) > max_larg * mm:
                tam -= 0.25
        self.c.setFont(fonte, tam)
        X, Y = x * mm, (297 - y) * mm
        if alinh == "dir":
            self.c.drawRightString(X, Y, s)
        elif alinh == "centro":
            self.c.drawCentredString(X, Y, s)
        else:
            self.c.drawString(X, Y, s)
        return pdfmetrics.stringWidth(s, fonte, tam) / mm

    def paragrafo(self, x, y_topo, largura, texto, fonte="Calibri", tam=9.0, entrelinha=4.0,
                  max_linhas=None, justificar=True, negrito_trechos=()):
        """
        Parágrafo justificado dentro de `largura` mm a partir de x. A primeira linha-base fica
        em y_topo + 0.75*entrelinha. Se exceder max_linhas, reduz fonte/entrelinha até caber.
        """
        c = self.c
        palavras = texto.split()
        while True:
            linhas, atual = [], []
            for p in palavras:
                teste = " ".join(atual + [p])
                if atual and pdfmetrics.stringWidth(teste, fonte, tam) > largura * mm:
                    linhas.append(atual)
                    atual = [p]
                else:
                    atual.append(p)
            if atual:
                linhas.append(atual)
            if not max_linhas or len(linhas) <= max_linhas or tam <= 5:
                break
            tam -= 0.25
            entrelinha *= (tam / (tam + 0.25))

        c.setFont(fonte, tam)
        y = y_topo + entrelinha * 0.75
        for i, ln in enumerate(linhas):
            Y = (297 - y) * mm
            ultima = (i == len(linhas) - 1)
            if justificar and not ultima and len(ln) > 1:
                larg_palavras = sum(pdfmetrics.stringWidth(p, fonte, tam) for p in ln)
                espaco = (largura * mm - larg_palavras) / (len(ln) - 1)
                X = x * mm
                for p in ln:
                    c.drawString(X, Y, p)
                    X += pdfmetrics.stringWidth(p, fonte, tam) + espaco
            else:
                c.drawString(x * mm, Y, " ".join(ln))
            y += entrelinha
        return len(linhas), y - entrelinha  # (n linhas, y da última linha-base)

    def retangulo_branco(self, x0, y0, x1, y1):
        c = self.c
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(1, 1, 1)
        c.rect(x0 * mm, (297 - y1) * mm, (x1 - x0) * mm, (y1 - y0) * mm, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setStrokeColorRGB(0, 0, 0)


def desenhar_frente(c, carta, seq):
    d = Desenho(c)
    c.drawImage(MOLDE_FRENTE, 0, 0, width=PAGE_W, height=PAGE_H)

    nome_mat = f"{carta['matricula']} - {carta['nome']}"
    end_completo = " ".join(p for p in [carta["endereco"], carta["complemento"], carta["bairro"]] if p)
    end_curto = " ".join(p for p in [carta["endereco"], carta["complemento"]] if p)
    cidade_uf = f"{carta['cidade']} - {carta['uf']}"
    data_proc = carta["data_geracao"].strftime("%d/%m/%Y")

    # --- Formulário AR: DESTINATÁRIO DO OBJETO ---
    d.texto(52.5, 11.4, nome_mat, "Arial-Bold", 8.5, max_larg=86)
    d.texto(53.0, 17.5, end_completo, "Arial", 8.5, max_larg=86)
    d.texto(53.0, 23.6, carta["cep"], "Arial", 8.5)
    d.texto(91.0, 23.6, cidade_uf, "Arial", 8.5, max_larg=60)
    d.texto(188.5, 23.6, data_proc, "Arial", 8.5, alinh="dir")

    # --- Código de barras Code 39 com a matrícula (canto superior direito do AR) ---
    bx0, bx1, by_topo, alt = 142.0, 185.0, 7.0, 7.5
    # quiet=0: sem zona quieta interna, para as barras ocuparem exatamente bx0..bx1
    opts = dict(barHeight=alt * mm, checksum=0, stop=1, humanReadable=False, quiet=0)
    bc = code39.Standard39(carta["matricula"], barWidth=1, **opts)
    escala = (bx1 - bx0) * mm / bc.width
    bc = code39.Standard39(carta["matricula"], barWidth=escala, **opts)
    bc.drawOn(c, bx0 * mm, (297 - by_topo - alt) * mm)
    # Leitura humana: mesma largura e mesmo centro das barras
    legenda = f"*{carta['matricula']}*"
    c.setFont("Arial", 7)
    larg = pdfmetrics.stringWidth(legenda, "Arial", 7)
    espaco = min(((bx1 - bx0) * mm - larg) / max(len(legenda) - 1, 1), 1.2 * mm)  # limita para matrículas curtas
    larg_total = larg + espaco * (len(legenda) - 1)
    centro = (bx0 + bx1) / 2 * mm
    x_leg = centro - larg_total / 2
    t = c.beginText(x_leg, (297 - by_topo - alt - 2.6) * mm)
    t.setFont("Arial", 7)
    t.setCharSpace(espaco)
    t.textOut(legenda)
    t.setCharSpace(0)  # o operador Tc persiste no PDF; zera para os demais textos
    c.drawText(t)

    # --- Envelope: DESTINATÁRIO ---
    d.texto(146.0, 163.5, f"{seq:04d}", "Arial", 6.5)
    d.texto(23.0, 168.6, nome_mat, "Arial-Bold", 8.6, max_larg=120)
    d.texto(23.0, 172.7, end_curto, "Arial", 8.6, max_larg=120)
    d.texto(23.0, 176.7, carta["bairro"], "Arial", 8.6, max_larg=120)
    d.texto(23.0, 180.7, f"{carta['cep']} - {cidade_uf}", "Arial", 8.6, max_larg=120)

    # --- Sequência do lote (canto inferior direito) ---
    d.texto(200.0, 291.5, f"{seq:04d}", "Arial", 7.7)


def desenhar_verso(c, carta, seq):
    d = Desenho(c)
    c.drawImage(MOLDE_VERSO, 0, 0, width=PAGE_W, height=PAGE_H)

    end_completo = " ".join(p for p in [carta["endereco"], carta["complemento"], carta["bairro"]] if p)

    # --- Cabeçalho da carta ---
    d.texto(17.0, 106.0, f"Vitória (ES),{data_extenso(carta['data_geracao'])}.", "Calibri-Bold", 9.2)
    d.texto(16.5, 113.0, f"Ao(À) Sr(a).  {carta['nome']}", "Calibri", 9.1, max_larg=98)
    d.texto(16.5, 117.3, f"CPF:  {carta['cpf']}", "Calibri", 9.1)
    rotulo = "Endereço:  "
    d.texto(16.5, 121.5, rotulo + end_completo, "Calibri", 9.1, max_larg=100)
    x2 = 16.5 + pdfmetrics.stringWidth(rotulo, "Calibri", 9.1) / mm
    d.texto(x2, 125.7, f"{carta['cidade']} - {carta['uf']} - {carta['cep']}", "Calibri", 9.1)

    # --- Parágrafo do produto (variável) ---
    prod = (f"V.S.a. ingressou no plano de saúde individual da MedSênior, produto: {carta['plano_desc']}, "
            f"registro ANS nº. {carta['plano_codigo']}. Verificamos que se encontra em aberto o pagamento "
            f"referente aos meses indicados no quadro abaixo:")
    d.paragrafo(16.5, 145.4, 175.5, prod, "Calibri", 9.0, 4.0, max_linhas=3)

    # --- Tabela de boletos (redesenhada em vetor sobre o molde) ---
    tx0, tx1, ty0, ty1 = 16.75, 190.7, 158.8, 193.2
    cab_alt = 3.9
    d.retangulo_branco(15.6, 158.0, 191.7, 193.7)
    n_linhas = max(8, len(carta["boletos"]))
    lin_alt = (ty1 - ty0 - cab_alt) / n_linhas
    ncol = 5
    col_larg = (tx1 - tx0) / ncol
    xs = [tx0 + i * col_larg for i in range(ncol + 1)]

    # cabeçalho cinza
    c.setFillColorRGB(0.80, 0.80, 0.80)
    c.rect(tx0 * mm, (297 - ty0 - cab_alt) * mm, (tx1 - tx0) * mm, cab_alt * mm, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    # linhas
    c.setLineWidth(0.25)
    for i in range(n_linhas + 1):
        y = ty0 + cab_alt + i * lin_alt
        c.line(tx0 * mm, (297 - y) * mm, tx1 * mm, (297 - y) * mm)
    for x in xs:
        c.line(x * mm, (297 - ty0) * mm, x * mm, (297 - ty1) * mm)
    c.setLineWidth(0.9)
    c.rect(tx0 * mm, (297 - ty1) * mm, (tx1 - tx0) * mm, (ty1 - ty0) * mm, stroke=1, fill=0)
    c.setLineWidth(0.25)

    cabecalhos = ["Número da boleta", "Competência (Mês de vencimento)", "Data de Vencimento",
                  "Tempo de inadimplência*", "Valor do boleto atualizado"]
    for i, h in enumerate(cabecalhos):
        d.texto((xs[i] + xs[i + 1]) / 2, ty0 + cab_alt - 1.1, h, "Arial-Bold", 7.6,
                max_larg=col_larg - 1.0, alinh="centro")

    tam_cel = min(8.0, lin_alt * 2.0)
    for i in range(n_linhas):
        yb = ty0 + cab_alt + (i + 1) * lin_alt - (lin_alt - tam_cel * 0.26) / 2  # ~centralizado
        if i < len(carta["boletos"]):
            b = carta["boletos"][i]
            venc = b["vencimento"].strftime("%Y-%m-%d") if b["vencimento"] else "-"
            vals = [b["numero"] or "-", b["competencia"] or "-", venc, b["dias"] or "-", fmt_moeda(b["valor"])]
        else:
            vals = ["-"] * 5
        for j, v in enumerate(vals):
            d.texto((xs[j] + xs[j + 1]) / 2, yb, v, "Calibri", tam_cel, max_larg=col_larg - 1.0, alinh="centro")

    # --- Parágrafo do valor total (variável) ---
    total = carta["total"]
    valor_txt = (f"O valor exato e atualizado do seu débito é de R$ {fmt_moeda(total)} ({valor_extenso(total)}) , "
                 f"até a data de emissão desta notificação.")
    d.paragrafo(16.5, 200.4, 175.5, valor_txt, "Calibri", 9.0, 4.0, max_linhas=2)

    # --- Sequência do lote (canto inferior esquerdo) ---
    d.texto(5.0, 291.0, f"{seq:04d}", "Arial", 7.7)


def desenhar_carta(c, carta, seq, retrato=False):
    """Desenha as 2 páginas da carta no canvas. Por padrão replica o modelo: página A4
    paisagem com o conteúdo rotacionado 90° (texto corre de baixo para cima)."""
    for pagina in (desenhar_frente, desenhar_verso):
        if retrato:
            c.setPageSize(A4)
            pagina(c, carta, seq)
        else:
            c.setPageSize(landscape(A4))
            c.saveState()
            c.translate(landscape(A4)[0], 0)
            c.rotate(90)
            pagina(c, carta, seq)
            c.restoreState()
        c.showPage()


# ----------------------------------------------------------------------------
# Geração
# ----------------------------------------------------------------------------
def nome_arquivo(carta, seq):
    nome = sem_acento(carta["nome"]).upper()
    nome = re.sub(r"[^A-Z0-9]+", "_", nome).strip("_")[:40]
    return f"{seq:04d}_{carta['matricula']}_{nome}.pdf"


def gerar(caminho_xlsx, pasta_saida=None, retrato=False, lote=True, nome_base=None):
    registrar_fontes()
    cartas = ler_planilha(caminho_xlsx)
    if not cartas:
        print("Nenhuma carta encontrada na planilha.")
        return []

    nome_base = nome_base or os.path.splitext(os.path.basename(caminho_xlsx))[0]
    pasta = pasta_saida or os.path.join(DIR_SAIDA, f"{nome_base}_{datetime.now():%Y-%m-%d_%H%M}")
    os.makedirs(pasta, exist_ok=True)

    gerados = []
    for seq, carta in enumerate(cartas, start=1):
        arq = os.path.join(pasta, nome_arquivo(carta, seq))
        c = canvas.Canvas(arq, pagesize=A4 if retrato else landscape(A4))
        c.setTitle(f"Notificação Extrajudicial - {carta['matricula']} - {carta['nome']}")
        c.setAuthor("MedSênior")
        desenhar_carta(c, carta, seq, retrato)
        c.save()
        gerados.append(arq)
        print(f"[{seq:04d}] {carta['matricula']} - {carta['nome']}  ({len(carta['boletos'])} boleto(s), "
              f"R$ {fmt_moeda(carta['total'])}) -> {os.path.basename(arq)}")

    if lote:
        # Lote gerado num único documento: as imagens do molde entram uma vez só (arquivo pequeno)
        arq_lote = os.path.join(pasta, f"LOTE_{nome_base}_{len(cartas)}_cartas.pdf")
        cl = canvas.Canvas(arq_lote, pagesize=A4 if retrato else landscape(A4))
        cl.setTitle(f"Lote de notificações - {nome_base} - {len(cartas)} cartas")
        cl.setAuthor("MedSênior")
        for seq, carta in enumerate(cartas, start=1):
            desenhar_carta(cl, carta, seq, retrato)
        cl.save()
        print(f"\nLote consolidado: {arq_lote}")

    print(f"\n{len(gerados)} carta(s) gerada(s) em: {pasta}")
    return gerados


def main(argv):
    retrato = "--retrato" in argv
    lote = "--sem-lote" not in argv
    arquivos = [a for a in argv[1:] if not a.startswith("--")]
    if not arquivos:
        arquivos = sorted(glob.glob(os.path.join(DIR_ENTRADA, "*.xlsx")))
        arquivos = [a for a in arquivos if not os.path.basename(a).startswith("~$")]
    if not arquivos:
        print(f"Nenhum .xlsx informado nem encontrado em {DIR_ENTRADA}")
        return 1
    for a in arquivos:
        print(f"\n=== Processando: {a}")
        gerar(a, retrato=retrato, lote=lote)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
