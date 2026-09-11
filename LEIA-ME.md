# Gerador de Cartas de Cobrança – MedSênior

Gera, a partir da planilha enviada pela MedSênior, um PDF A4 individual por beneficiário
com 2 páginas (frente = AR dos Correios + envelope; verso = Notificação Extrajudicial),
no mesmo formato do modelo aprovado (página paisagem com o conteúdo rotacionado).

## Como usar

1. Coloque a planilha `.xlsx` na pasta `entrada/` (pode ser mais de uma).
2. Dê dois cliques em `GERAR_CARTAS.bat`
   (ou arraste a planilha para cima do `.bat`).
3. Os PDFs saem em `saida/<nome da planilha>_<data_hora>/`:
   - `0001_<matricula>_<nome>.pdf`, `0002_...` – uma carta por beneficiário
   - `LOTE_<nome da planilha>_<N>_cartas.pdf` – todas as cartas juntas, na ordem, para impressão

Linha de comando:

    python gerar_cartas.py                       (todas as planilhas de entrada/)
    python gerar_cartas.py "caminho\planilha.xlsx"
    python gerar_cartas.py planilha.xlsx --retrato    (páginas em pé, sem rotação)
    python gerar_cartas.py planilha.xlsx --sem-lote   (não gera o PDF consolidado)

## Regras aplicadas

- Uma linha da planilha = um boleto. As linhas são agrupadas por `MATRICULA`; cada
  matrícula vira uma carta com todos os seus boletos na tabela (ordenados por vencimento).
- Número de sequência (`0001`, `0002`...) = ordem da carta dentro da planilha.
- Código de barras do AR: Code 39 com a matrícula.
- CEP e CPF são completados com zeros à esquerda (8 e 11 dígitos) caso o Excel os tenha removido.
- `DT. PROCESSAMENTO` e a data da carta ("Vitória (ES), dd de mês de aaaa") = `Data Geracao Arquivo`.
- Valor total = `Div_Total_Calc` (se vazio, soma dos `Valor Boleto Att`), escrito também por extenso.
- Tabela: 8 linhas fixas como no modelo; boletos excedentes reduzem a altura das linhas para caber.
- Textos longos (nome, endereço, plano) reduzem a fonte automaticamente para não estourar o campo.

## Colunas obrigatórias na planilha

MATRICULA, NOME, ENDERECO, COMPLEMENTO, BAIRRO, CIDADE, CEP, UF, CPF, Plano Codigo ANS,
Plano Descricao, Nosso Número Boleto, Vencimento Boleto, Valor Boleto Att,
Dias de Atraso Boleto, Mes_competencia, Data Geracao Arquivo (e, opcional, Div_Total_Calc).

## Estrutura

    gerar_cartas.py     – programa
    GERAR_CARTAS.bat    – atalho para rodar
    modelos/            – moldes fixos (frente_retrato.jpg / verso_retrato.jpg, 350 DPI)
    entrada/            – planilhas recebidas
    saida/              – PDFs gerados
    testes/             – planilha de teste com casos extremos

## Requisitos

Python 3 com `pandas`, `openpyxl`, `reportlab`, `pypdf` (`pip install pandas openpyxl reportlab pypdf`)
e as fontes Arial e Calibri do Windows.

## Portal web (uso no dia a dia)

Versão web do gerador, com login, ordens de serviço, filtro, seleção por checkbox,
BAIXAR TUDO e retenção de 48 horas. Inicie com `INICIAR_SISTEMA_WEB.bat` e abra
`http://localhost:8000`. Instruções completas em `webapp/LEIA-ME_PORTAL.md`.
