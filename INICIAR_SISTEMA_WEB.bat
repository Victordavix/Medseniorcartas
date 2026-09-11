@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================================
echo   Portal de Cartas de Cobranca - MedSenior
echo   Abra no navegador: http://localhost:8000
echo   (na rede: http://IP-DESTA-MAQUINA:8000)
echo   Feche esta janela para parar o servidor.
echo ==========================================================
python webapp\app.py
pause
