# Portal web de Cartas de Cobrança – MedSênior

Versão web do gerador (`gerar_cartas.py`). O cliente envia a planilha, o portal gera um PDF
por beneficiário e disponibiliza para download por 48 horas. Cada envio vira uma **ordem de
serviço (OS)** com solicitante, data e hora, que só o super admin pode excluir.

## Iniciar

Dois cliques em `INICIAR_SISTEMA_WEB.bat` (na pasta principal) ou:

    python webapp/app.py

Abre em `http://localhost:8000`. Na rede local, use `http://IP-DA-MAQUINA:8000`.
Porta alternativa: defina a variável de ambiente `PORTA` antes de iniciar.

**Primeiro acesso:** login `admin`, senha `admin`. Troque a senha imediatamente em "Senha".
Depois crie os usuários da equipe em "Usuários" (perfil operador).

## Perfis

| Ação | Operador | Super admin |
|---|---|---|
| Enviar planilha e gerar PDFs | sim | sim |
| Ver todas as OS, filtrar, baixar PDFs (unitário, selecionados, BAIXAR TUDO, lote) | sim | sim |
| Baixar a planilha original de qualquer OS | sim | sim |
| "Gerar novamente" a partir da planilha original (após os 48 h ou erro) | sim | sim |
| Excluir uma OS (planilha, PDFs e registro) | não | sim |
| Criar, desativar e redefinir senha de usuários | não | sim |
| Ver a auditoria (logins, uploads, downloads, exclusões) | não | sim |

## Regras de retenção

- Os PDFs de uma OS ficam disponíveis por **48 horas** após a conclusão. Um processo interno
  verifica a cada 10 minutos e apaga os PDFs vencidos.
- A **planilha original**, o registro da OS (número, solicitante, data e hora, lista de
  beneficiários gerados) e a auditoria **permanecem**. Só o super admin exclui uma OS.
- Após a expiração, "Gerar novamente" abre uma nova OS a partir da mesma planilha, com
  referência à OS de origem.

## Tela da OS

- **Filtro** por nome, matrícula, CPF ou cidade (aceita várias palavras; `/` foca o campo,
  `Esc` limpa).
- **Checkbox** por beneficiário e "marcar todos os visíveis" no cabeçalho. O botão
  "Baixar selecionados (N)" entrega um ZIP com os PDFs marcados.
- **BAIXAR TUDO**: ZIP com todos os PDFs individuais mais o PDF de lote.
- **Lote para impressão**: um único PDF com todas as cartas em sequência (0001, 0002, …).
- **PDF** na linha: baixa a carta daquele beneficiário.

## Onde ficam os dados

    webapp/dados/portal.db              banco SQLite (usuários, OS, cartas, auditoria)
    webapp/dados/ordens/000001/         uma pasta por OS
        original_<planilha>.xlsx        planilha enviada (permanente)
        pdfs/                           PDFs gerados (apagados após 48 h)
    webapp/dados/chave_secreta.txt      chave das sessões (gerada no primeiro início)

Faça backup da pasta `webapp/dados/`.

## Requisitos

Python 3 com `flask`, `waitress`, `pandas`, `openpyxl`, `reportlab`:

    pip install flask waitress pandas openpyxl reportlab

Fontes Arial e Calibri do Windows (já presentes) e os moldes em `modelos/`.

## Segurança e rede

- Sessão por cookie assinado; senhas com hash (PBKDF2). Upload limitado a 30 MB e a `.xlsx`.
- O servidor escuta em todas as interfaces (0.0.0.0). Para acesso fora da rede local,
  coloque atrás de um proxy HTTPS (IIS, nginx ou Caddy) e libere só a porta do proxy.
