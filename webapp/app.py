# -*- coding: utf-8 -*-
"""
Portal web de Cartas de Cobrança MedSênior.

- Login com perfis: operador e superadmin
- Upload da planilha -> Ordem de Serviço (OS) com solicitante, data e hora
- Geração dos PDFs individuais em segundo plano, download unitário, selecionado ou "BAIXAR TUDO" (ZIP)
- PDFs ficam disponíveis por 48 h; depois só a planilha original e o registro da OS permanecem
- OS só pode ser excluída por superadmin

Executar:  python webapp/app.py   (ou INICIAR_SISTEMA_WEB.bat)
"""
import os
import re
import secrets
import sys
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
import processamento as proc  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
PORTA = int(os.environ.get("PORT") or os.environ.get("PORTA") or "8000")  # Railway injeta PORT
TAM_MAX_UPLOAD_MB = 30

app = Flask(__name__, template_folder=os.path.join(BASE, "templates"), static_folder=os.path.join(BASE, "static"))
app.config["MAX_CONTENT_LENGTH"] = TAM_MAX_UPLOAD_MB * 1024 * 1024


def _chave_secreta():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    os.makedirs(db.DIR_DADOS, exist_ok=True)
    caminho = os.path.join(db.DIR_DADOS, "chave_secreta.txt")
    if not os.path.exists(caminho):
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(caminho, encoding="utf-8") as f:
        return f.read().strip()


app.secret_key = _chave_secreta()


# ----------------------------------------------------------------------------
# Infra: conexão por requisição, usuário logado, decorators
# ----------------------------------------------------------------------------
@app.before_request
def _abrir():
    g.con = db.conectar()
    g.usuario = None
    uid = session.get("uid")
    if uid:
        u = g.con.execute("SELECT * FROM usuarios WHERE id = ? AND ativo = 1", (uid,)).fetchone()
        g.usuario = dict(u) if u else None
        if not g.usuario:
            session.clear()


@app.teardown_request
def _fechar(exc):
    con = getattr(g, "con", None)
    if con:
        con.close()


def exige_login(f):
    @wraps(f)
    def w(*a, **k):
        if not g.usuario:
            return redirect(url_for("login", proximo=request.path))
        return f(*a, **k)
    return w


def exige_superadmin(f):
    @wraps(f)
    def w(*a, **k):
        if not g.usuario:
            return redirect(url_for("login", proximo=request.path))
        if g.usuario["papel"] != "superadmin":
            return render_template("erro.html", titulo="Acesso restrito",
                                   mensagem="Esta ação é permitida apenas ao super admin."), 403
        return f(*a, **k)
    return w


@app.template_filter("dt")
def _fmt_dt(v):
    if not v:
        return ""
    try:
        return datetime.strptime(v, proc.FMT).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return v


@app.template_filter("moeda")
def _fmt_moeda(v):
    s = f"{float(v or 0):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("cpf")
def _fmt_cpf(v):
    v = re.sub(r"\D", "", str(v or ""))
    return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}" if len(v) == 11 else v


def _restante(ordem):
    """Texto de disponibilidade dos PDFs."""
    if ordem["status"] != "concluida":
        return None
    if ordem["pdfs_removidos_em"] or not ordem["expira_em"]:
        return "expirado"
    delta = datetime.strptime(ordem["expira_em"], proc.FMT) - datetime.now()
    seg = int(delta.total_seconds())
    if seg <= 0:
        return "expirado"
    h, m = divmod(seg // 60, 60)
    return f"{h} h {m:02d} min"


app.jinja_env.globals["restante"] = _restante


# ----------------------------------------------------------------------------
# Autenticação
# ----------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario:
        return redirect(url_for("painel"))
    erro = None
    if request.method == "POST":
        login_ = request.form.get("login", "").strip().lower()
        senha = request.form.get("senha", "")
        u = g.con.execute("SELECT * FROM usuarios WHERE lower(login) = ?", (login_,)).fetchone()
        if u and u["ativo"] and check_password_hash(u["senha_hash"], senha):
            session.clear()
            session["uid"] = u["id"]
            session.permanent = False
            g.con.execute("UPDATE usuarios SET ultimo_acesso = ? WHERE id = ?", (db.agora(), u["id"]))
            db.registrar_evento(g.con, "login", dict(u))
            destino = request.args.get("proximo") or url_for("painel")
            if not destino.startswith("/"):
                destino = url_for("painel")
            return redirect(destino)
        erro = "Login ou senha incorretos, ou usuário desativado."
        db.registrar_evento(g.con, "login_falhou", None, detalhe=login_)
    return render_template("login.html", erro=erro)


@app.route("/sair")
def sair():
    if g.usuario:
        db.registrar_evento(g.con, "logout", g.usuario)
    session.clear()
    return redirect(url_for("login"))


@app.route("/minha-senha", methods=["GET", "POST"])
@exige_login
def minha_senha():
    erro = None
    if request.method == "POST":
        atual = request.form.get("atual", "")
        nova = request.form.get("nova", "")
        conf = request.form.get("confirmar", "")
        u = g.con.execute("SELECT * FROM usuarios WHERE id = ?", (g.usuario["id"],)).fetchone()
        if not check_password_hash(u["senha_hash"], atual):
            erro = "A senha atual não confere."
        elif len(nova) < 6:
            erro = "A nova senha precisa ter pelo menos 6 caracteres."
        elif nova != conf:
            erro = "A confirmação não é igual à nova senha."
        else:
            g.con.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (generate_password_hash(nova), u["id"]))
            db.registrar_evento(g.con, "senha_alterada", g.usuario)
            flash("Senha alterada.", "ok")
            return redirect(url_for("painel"))
    return render_template("minha_senha.html", erro=erro)


# ----------------------------------------------------------------------------
# Painel: upload + lista de ordens de serviço
# ----------------------------------------------------------------------------
@app.route("/")
@exige_login
def painel():
    busca = request.args.get("q", "").strip()
    sql = "SELECT * FROM ordens_servico"
    params = ()
    if busca:
        sql += " WHERE numero LIKE ? OR arquivo_original LIKE ? OR solicitante_nome LIKE ?"
        params = (f"%{busca}%",) * 3
    sql += " ORDER BY id DESC LIMIT 300"
    ordens = [dict(r) for r in g.con.execute(sql, params).fetchall()]
    total_os = g.con.execute("SELECT COUNT(*) FROM ordens_servico").fetchone()[0]
    return render_template("painel.html", ordens=ordens, busca=busca, total_os=total_os,
                           tam_max=TAM_MAX_UPLOAD_MB, horas=proc.HORAS_RETENCAO)


@app.route("/os/nova", methods=["POST"])
@exige_login
def os_nova():
    arq = request.files.get("planilha")
    if not arq or not arq.filename:
        flash("Selecione a planilha (.xlsx) antes de enviar.", "erro")
        return redirect(url_for("painel"))
    nome = secure_filename(arq.filename) or "planilha.xlsx"
    if not nome.lower().endswith((".xlsx", ".xlsm")):
        flash("Formato não aceito. Envie a planilha em .xlsx.", "erro")
        return redirect(url_for("painel"))
    os_id = _criar_os(nome, arq.save)
    return redirect(url_for("os_detalhe", os_id=os_id))


def _criar_os(nome_original, salvar, reprocessada_de=None):
    """Cria a OS, grava o original com a função `salvar(caminho)` e dispara a geração."""
    numero = db.proximo_numero_os(g.con)
    cur = g.con.execute(
        "INSERT INTO ordens_servico (numero, solicitante_id, solicitante_nome, solicitante_login, criado_em, "
        "status, arquivo_original, reprocessada_de) VALUES (?, ?, ?, ?, ?, 'processando', ?, ?)",
        (numero, g.usuario["id"], g.usuario["nome"], g.usuario["login"], db.agora(), nome_original, reprocessada_de),
    )
    os_id = cur.lastrowid
    g.con.commit()
    os.makedirs(proc.pasta_os(os_id), exist_ok=True)
    salvar(proc.caminho_original(os_id, nome_original))
    db.registrar_evento(g.con, "upload", g.usuario, os_id, nome_original)
    proc.iniciar_processamento(os_id)
    return os_id


def _carregar_os(os_id):
    o = g.con.execute("SELECT * FROM ordens_servico WHERE id = ?", (os_id,)).fetchone()
    if not o:
        abort(404)
    return dict(o)


@app.route("/os/<int:os_id>")
@exige_login
def os_detalhe(os_id):
    ordem = _carregar_os(os_id)
    cartas = [dict(r) for r in g.con.execute(
        "SELECT * FROM cartas WHERE os_id = ? ORDER BY seq", (os_id,)).fetchall()]
    total = sum(c["total"] for c in cartas)
    disponivel = ordem["status"] == "concluida" and not ordem["pdfs_removidos_em"] and _restante(ordem) != "expirado"
    origem = None
    if ordem["reprocessada_de"]:
        origem = g.con.execute("SELECT numero FROM ordens_servico WHERE id = ?", (ordem["reprocessada_de"],)).fetchone()
    return render_template("os_detalhe.html", ordem=ordem, cartas=cartas, total=total,
                           disponivel=disponivel, origem=origem["numero"] if origem else None,
                           tem_lote=bool(proc.arquivo_lote(os_id)) if disponivel else False)


@app.route("/os/<int:os_id>/status")
@exige_login
def os_status(os_id):
    ordem = _carregar_os(os_id)
    return jsonify(status=ordem["status"], erro=ordem["erro"], qtd_cartas=ordem["qtd_cartas"])


def _exigir_disponivel(ordem):
    if ordem["status"] != "concluida" or ordem["pdfs_removidos_em"] or _restante(ordem) == "expirado":
        return render_template("erro.html", titulo="PDFs não disponíveis",
                               mensagem="Os PDFs desta ordem de serviço expiraram ou ainda não foram gerados. "
                                        "A planilha original continua disponível; use “Gerar novamente”."), 410
    return None


@app.route("/os/<int:os_id>/carta/<int:carta_id>")
@exige_login
def baixar_carta(os_id, carta_id):
    ordem = _carregar_os(os_id)
    r = _exigir_disponivel(ordem)
    if r:
        return r
    c = g.con.execute("SELECT * FROM cartas WHERE id = ? AND os_id = ?", (carta_id, os_id)).fetchone()
    if not c:
        abort(404)
    caminho = os.path.join(proc.pasta_pdfs(os_id), c["arquivo"])
    if not os.path.isfile(caminho):
        abort(404)
    db.registrar_evento(g.con, "download", g.usuario, os_id, c["arquivo"])
    return send_file(caminho, as_attachment=True, download_name=c["arquivo"])


def _enviar_temporario(caminho, nome_download):
    """Envia um ZIP temporário e o apaga quando a resposta termina de ser transmitida."""
    resp = send_file(caminho, as_attachment=True, download_name=nome_download, mimetype="application/zip")

    def _apagar():
        # O servidor (waitress) ainda pode estar com o arquivo aberto quando a resposta fecha;
        # no Windows isso impede a remoção imediata, então tentamos por até 2 minutos em segundo plano.
        import threading
        import time

        def tentar():
            for _ in range(60):
                try:
                    os.remove(caminho)
                    return
                except FileNotFoundError:
                    return
                except OSError:
                    time.sleep(2)
        threading.Thread(target=tentar, daemon=True).start()
    resp.call_on_close(_apagar)
    return resp


@app.route("/os/<int:os_id>/baixar", methods=["POST"])
@exige_login
def baixar_selecionados(os_id):
    ordem = _carregar_os(os_id)
    r = _exigir_disponivel(ordem)
    if r:
        return r
    ids = [int(i) for i in request.form.getlist("carta") if i.isdigit()]
    if not ids:
        flash("Marque pelo menos um beneficiário para baixar.", "erro")
        return redirect(url_for("os_detalhe", os_id=os_id))
    q = ",".join("?" * len(ids))
    rows = g.con.execute(f"SELECT arquivo FROM cartas WHERE os_id = ? AND id IN ({q}) ORDER BY seq",
                         (os_id, *ids)).fetchall()
    caminho_zip = proc.montar_zip(os_id, [x["arquivo"] for x in rows])
    db.registrar_evento(g.con, "download_selecionados", g.usuario, os_id, f"{len(rows)} carta(s)")
    return _enviar_temporario(caminho_zip, f"{ordem['numero']}_selecionadas_{len(rows)}.zip")


@app.route("/os/<int:os_id>/baixar-tudo")
@exige_login
def baixar_tudo(os_id):
    ordem = _carregar_os(os_id)
    r = _exigir_disponivel(ordem)
    if r:
        return r
    rows = g.con.execute("SELECT arquivo FROM cartas WHERE os_id = ? ORDER BY seq", (os_id,)).fetchall()
    caminho_zip = proc.montar_zip(os_id, [x["arquivo"] for x in rows], incluir_lote=True)
    db.registrar_evento(g.con, "download_tudo", g.usuario, os_id, f"{len(rows)} carta(s) + lote")
    return _enviar_temporario(caminho_zip, f"{ordem['numero']}_todas_{len(rows)}_cartas.zip")


@app.route("/os/<int:os_id>/lote")
@exige_login
def baixar_lote(os_id):
    ordem = _carregar_os(os_id)
    r = _exigir_disponivel(ordem)
    if r:
        return r
    lote = proc.arquivo_lote(os_id)
    if not lote:
        abort(404)
    db.registrar_evento(g.con, "download_lote", g.usuario, os_id)
    return send_file(lote, as_attachment=True, download_name=os.path.basename(lote))


@app.route("/os/<int:os_id>/original")
@exige_login
def baixar_original(os_id):
    ordem = _carregar_os(os_id)
    caminho = proc.caminho_original(os_id, ordem["arquivo_original"])
    if not os.path.isfile(caminho):
        abort(404)
    db.registrar_evento(g.con, "download_original", g.usuario, os_id)
    return send_file(caminho, as_attachment=True, download_name=ordem["arquivo_original"])


@app.route("/os/<int:os_id>/reprocessar", methods=["POST"])
@exige_login
def reprocessar(os_id):
    """Gera uma nova OS a partir da planilha original desta (usado após os 48 h ou após erro)."""
    ordem = _carregar_os(os_id)
    origem = proc.caminho_original(os_id, ordem["arquivo_original"])
    if not os.path.isfile(origem):
        abort(404)
    import shutil
    novo = _criar_os(ordem["arquivo_original"], lambda destino: shutil.copyfile(origem, destino), reprocessada_de=os_id)
    flash(f"Nova ordem de serviço criada a partir da {ordem['numero']}.", "ok")
    return redirect(url_for("os_detalhe", os_id=novo))


@app.route("/os/<int:os_id>/excluir", methods=["POST"])
@exige_superadmin
def excluir_os(os_id):
    ordem = _carregar_os(os_id)
    import shutil
    shutil.rmtree(proc.pasta_os(os_id), ignore_errors=True)
    g.con.execute("DELETE FROM cartas WHERE os_id = ?", (os_id,))
    g.con.execute("DELETE FROM ordens_servico WHERE id = ?", (os_id,))
    db.registrar_evento(g.con, "excluir_os", g.usuario, os_id, f"{ordem['numero']} ({ordem['arquivo_original']})")
    flash(f"Ordem de serviço {ordem['numero']} excluída.", "ok")
    return redirect(url_for("painel"))


# ----------------------------------------------------------------------------
# Administração: usuários e auditoria (superadmin)
# ----------------------------------------------------------------------------
@app.route("/usuarios")
@exige_superadmin
def usuarios():
    lista = [dict(r) for r in g.con.execute("SELECT * FROM usuarios ORDER BY ativo DESC, nome").fetchall()]
    return render_template("usuarios.html", usuarios=lista)


@app.route("/usuarios/novo", methods=["POST"])
@exige_superadmin
def usuario_novo():
    nome = request.form.get("nome", "").strip()
    login_ = request.form.get("login", "").strip().lower()
    senha = request.form.get("senha", "")
    papel = request.form.get("papel", "operador")
    if not nome or not re.fullmatch(r"[a-z0-9._-]{3,40}", login_) or len(senha) < 6 or papel not in ("operador", "superadmin"):
        flash("Preencha nome, login (letras/números, mínimo 3) e senha (mínimo 6).", "erro")
        return redirect(url_for("usuarios"))
    if g.con.execute("SELECT 1 FROM usuarios WHERE login = ?", (login_,)).fetchone():
        flash("Já existe um usuário com esse login.", "erro")
        return redirect(url_for("usuarios"))
    g.con.execute("INSERT INTO usuarios (nome, login, senha_hash, papel, ativo, criado_em) VALUES (?, ?, ?, ?, 1, ?)",
                  (nome, login_, generate_password_hash(senha), papel, db.agora()))
    db.registrar_evento(g.con, "usuario_criado", g.usuario, detalhe=f"{login_} ({papel})")
    flash(f"Usuário {login_} criado.", "ok")
    return redirect(url_for("usuarios"))


@app.route("/usuarios/<int:uid>/alternar", methods=["POST"])
@exige_superadmin
def usuario_alternar(uid):
    if uid == g.usuario["id"]:
        flash("Você não pode desativar o próprio usuário.", "erro")
        return redirect(url_for("usuarios"))
    u = g.con.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    if not u:
        abort(404)
    novo = 0 if u["ativo"] else 1
    g.con.execute("UPDATE usuarios SET ativo = ? WHERE id = ?", (novo, uid))
    db.registrar_evento(g.con, "usuario_ativado" if novo else "usuario_desativado", g.usuario, detalhe=u["login"])
    flash(f"Usuário {u['login']} {'ativado' if novo else 'desativado'}.", "ok")
    return redirect(url_for("usuarios"))


@app.route("/usuarios/<int:uid>/senha", methods=["POST"])
@exige_superadmin
def usuario_senha(uid):
    u = g.con.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    if not u:
        abort(404)
    senha = request.form.get("senha", "")
    if len(senha) < 6:
        flash("A senha precisa ter pelo menos 6 caracteres.", "erro")
        return redirect(url_for("usuarios"))
    g.con.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (generate_password_hash(senha), uid))
    db.registrar_evento(g.con, "senha_redefinida", g.usuario, detalhe=u["login"])
    flash(f"Senha de {u['login']} redefinida.", "ok")
    return redirect(url_for("usuarios"))


@app.route("/auditoria")
@exige_superadmin
def auditoria():
    eventos = [dict(r) for r in g.con.execute(
        "SELECT e.*, o.numero AS os_numero FROM eventos e LEFT JOIN ordens_servico o ON o.id = e.os_id "
        "ORDER BY e.id DESC LIMIT 500").fetchall()]
    return render_template("auditoria.html", eventos=eventos)


@app.errorhandler(404)
def _404(e):
    return render_template("erro.html", titulo="Não encontrado", mensagem="A página ou arquivo não existe."), 404


@app.errorhandler(413)
def _413(e):
    return render_template("erro.html", titulo="Arquivo muito grande",
                           mensagem=f"O limite de envio é {TAM_MAX_UPLOAD_MB} MB."), 413


# ----------------------------------------------------------------------------
def preparar():
    db.inicializar(os.environ.get("ADMIN_LOGIN", "admin"), os.environ.get("ADMIN_SENHA", "admin"))
    proc.retomar_interrompidas()
    proc.limpar_vencidos()
    proc.iniciar_limpeza_periodica()


preparar()

# ----------------------------------------------------------------------------
# Ícones (Lucide, 24x24, traço 2) disponíveis nos templates como {{ icone('nome') }}
# ----------------------------------------------------------------------------
_ICONES = {
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    "busca": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "play": '<polygon points="6 3 20 12 6 21 6 3"/>',
    "sol": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "seta-esq": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "refazer": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "lixeira": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
}


@app.template_global("icone")
def _icone(nome):
    from markupsafe import Markup
    corpo = _ICONES.get(nome, "")
    return Markup(f'<svg class="icone" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                  f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{corpo}</svg>')


if __name__ == "__main__":
    print(f"Portal de Cartas de Cobrança rodando em http://localhost:{PORTA}  (Ctrl+C para parar)")
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORTA, threads=8, max_request_body_size=TAM_MAX_UPLOAD_MB * 1024 * 1024 + 1024)
    except ImportError:
        app.run(host="0.0.0.0", port=PORTA, debug=False)
