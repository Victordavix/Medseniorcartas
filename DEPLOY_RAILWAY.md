# Publicar o portal no Railway

O projeto já está preparado: `Procfile`, `railway.json`, `requirements.txt`, `.python-version`,
fontes embutidas em `fontes/` e pastas configuráveis por variável de ambiente.

## O que muda em relação ao uso local

| Item | Local (Windows) | Railway (Linux) |
|---|---|---|
| Fontes | Arial e Calibri do Windows | Liberation Sans e Carlito (embutidas, mesmas métricas: o layout não muda) |
| Banco e arquivos | `webapp/dados/` | Volume persistente montado em `/data` (`DADOS_DIR=/data`) |
| Porta | 8000 | `PORT` injetada pelo Railway |
| HTTPS | não | sim, automático no domínio do Railway |
| Chave de sessão | arquivo em `dados/` | variável `SECRET_KEY` |

O banco é SQLite dentro do volume. Para o volume de uso desta equipe (poucas dezenas de OS
por dia, PDFs apagados em 48 h) isso é suficiente. Se um dia quiser Postgres, a camada de
banco está isolada em `webapp/db.py`.

## Passo a passo

1. **Repositório Git.** Na pasta do projeto:

       git init
       git add .
       git commit -m "Portal de cartas de cobrança MedSênior"

   Suba para um repositório privado no GitHub (`webapp/dados/` e `saida/` já estão no `.gitignore`).

2. **Projeto no Railway.** New Project → Deploy from GitHub repo → escolha o repositório.
   O Railway detecta Python, instala `requirements.txt` e usa o comando do `Procfile`.

3. **Volume.** No serviço: Settings → Volumes → Add Volume, mount path `/data`.
   Sem o volume, banco e planilhas somem a cada deploy.

4. **Variáveis** (Settings → Variables):

       DADOS_DIR=/data
       SECRET_KEY=<texto aleatório longo>
       ADMIN_LOGIN=admin
       ADMIN_SENHA=<senha forte do primeiro super admin>

   `ADMIN_LOGIN`/`ADMIN_SENHA` só valem na primeira inicialização (quando ainda não existe
   super admin). Depois, gerencie pelo portal.

5. **Domínio.** Settings → Networking → Generate Domain. O acesso é `https://...up.railway.app`.
   Se quiser um domínio próprio (ex.: `cartas.suaempresa.com.br`), adicione em Custom Domain
   e aponte o CNAME no seu DNS.

6. **Primeiro acesso.** Entre com o super admin, troque a senha e cadastre os operadores.

## Esqueci a senha do super admin

1. No Railway: serviço **web** → **Variables** → adicione `ADMIN_RESET_SENHA` com a nova senha.
2. O Railway faz um novo deploy sozinho. Na inicialização, a senha do login `ADMIN_LOGIN`
   (padrão `admin`) é redefinida, o usuário é reativado e a auditoria registra o evento.
3. Entre no portal com a nova senha e **remova a variável** `ADMIN_RESET_SENHA` (senão a senha
   volta a ser redefinida a cada deploy).

As senhas dos demais usuários são redefinidas pelo super admin em **Usuários → Ações**.

## Limites a observar

- Upload de planilha limitado a 30 MB (ajustável em `TAM_MAX_UPLOAD_MB` no `app.py`).
- O ZIP de "BAIXAR TUDO" tem cerca de 1 MB por carta. Para lotes muito grandes (mil cartas),
  o download passa de 1 GB; nesse caso prefira o "Lote para impressão" (PDF único, bem menor)
  ou baixe por seleção.
- Mantenha **1 réplica** (já configurado em `railway.json`). O SQLite e a geração em
  segundo plano não devem rodar em mais de uma instância.
- O plano do Railway precisa de espaço no volume para 48 h de PDFs (estime 1 MB por carta
  gerada nas últimas 48 h) mais as planilhas originais, que ficam para sempre.

## Rodar localmente simulando o Railway

    set DADOS_DIR=C:\temp\dados_teste
    set FONTES_EMBUTIDAS=1
    set PORT=8123
    python webapp\app.py
