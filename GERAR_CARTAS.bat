@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================================
echo   Gerador de Cartas de Cobranca - MedSenior
echo ==========================================================
if "%~1"=="" (
    echo Processando todas as planilhas .xlsx da pasta "entrada"...
    python gerar_cartas.py
) else (
    echo Processando: %*
    python gerar_cartas.py %*
)
echo.
echo Concluido. Os PDFs estao na pasta "saida".
pause
