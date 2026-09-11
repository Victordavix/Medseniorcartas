# -*- coding: utf-8 -*-
"""Banco de dados SQLite do portal (usuários, ordens de serviço, cartas, eventos)."""
import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DIR_DADOS = os.environ.get("DADOS_DIR") or os.path.join(BASE, "dados")  # Railway: DADOS_DIR=/data
DIR_OS = os.path.join(DIR_DADOS, "ordens")
CAMINHO_DB = os.path.join(DIR_DADOS, "portal.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL,
    login       TEXT NOT NULL UNIQUE,
    senha_hash  TEXT NOT NULL,
    papel       TEXT NOT NULL CHECK (papel IN ('operador', 'superadmin')),
    ativo       INTEGER NOT NULL DEFAULT 1,
    criado_em   TEXT NOT NULL,
    ultimo_acesso TEXT
);

CREATE TABLE IF NOT EXISTS ordens_servico (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero          TEXT NOT NULL UNIQUE,          -- OS-2026-0001
    solicitante_id  INTEGER NOT NULL,
    solicitante_nome TEXT NOT NULL,                -- congelado: não muda se o usuário for renomeado
    solicitante_login TEXT NOT NULL,
    criado_em       TEXT NOT NULL,
    concluido_em    TEXT,
    status          TEXT NOT NULL DEFAULT 'processando',  -- processando | concluida | erro
    erro            TEXT,
    arquivo_original TEXT NOT NULL,                -- nome como o cliente enviou
    qtd_linhas      INTEGER DEFAULT 0,
    qtd_cartas      INTEGER DEFAULT 0,
    expira_em       TEXT,                          -- PDFs disponíveis até aqui (48 h)
    pdfs_removidos_em TEXT,
    reprocessada_de INTEGER,                       -- id da OS de origem, quando gerada de novo
    FOREIGN KEY (solicitante_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS cartas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    os_id       INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    matricula   TEXT NOT NULL,
    nome        TEXT NOT NULL,
    cpf         TEXT,
    cidade      TEXT,
    uf          TEXT,
    qtd_boletos INTEGER NOT NULL,
    total       REAL NOT NULL,
    arquivo     TEXT NOT NULL,                     -- nome do PDF dentro da pasta da OS
    FOREIGN KEY (os_id) REFERENCES ordens_servico(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cartas_os ON cartas(os_id);

CREATE TABLE IF NOT EXISTS eventos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quando      TEXT NOT NULL,
    usuario_id  INTEGER,
    usuario_login TEXT,
    acao        TEXT NOT NULL,     -- login | upload | download | download_tudo | excluir_os | usuario_criado ...
    os_id       INTEGER,
    detalhe     TEXT
);
"""


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar():
    os.makedirs(DIR_OS, exist_ok=True)
    con = sqlite3.connect(CAMINHO_DB, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def inicializar(admin_login="admin", admin_senha="admin"):
    """Cria as tabelas e o super admin inicial (se não existir nenhum)."""
    con = conectar()
    con.executescript(SCHEMA)
    existe = con.execute("SELECT COUNT(*) FROM usuarios WHERE papel = 'superadmin'").fetchone()[0]
    if not existe:
        con.execute(
            "INSERT INTO usuarios (nome, login, senha_hash, papel, ativo, criado_em) VALUES (?, ?, ?, 'superadmin', 1, ?)",
            ("Super Admin", admin_login, generate_password_hash(admin_senha), agora()),
        )
        con.commit()
        print(f"[portal] Super admin inicial criado: login '{admin_login}' / senha '{admin_senha}'. Troque a senha no primeiro acesso.")
    con.close()


def registrar_evento(con, acao, usuario=None, os_id=None, detalhe=None):
    con.execute(
        "INSERT INTO eventos (quando, usuario_id, usuario_login, acao, os_id, detalhe) VALUES (?, ?, ?, ?, ?, ?)",
        (agora(), usuario["id"] if usuario else None, usuario["login"] if usuario else None, acao, os_id, detalhe),
    )
    con.commit()


def proximo_numero_os(con):
    ano = datetime.now().year
    ultimo = con.execute(
        "SELECT numero FROM ordens_servico WHERE numero LIKE ? ORDER BY id DESC LIMIT 1", (f"OS-{ano}-%",)
    ).fetchone()
    n = int(ultimo["numero"].split("-")[-1]) + 1 if ultimo else 1
    return f"OS-{ano}-{n:04d}"
