@echo off
title TP DASH ADMIN
cd /d "%~dp0admin"
set PY=%~dp0..\painel_puma\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo [ERRO] Nao encontrei o Python do painel em %PY%
  echo Coloque a pasta tpdash_online ao lado da pasta painel_puma.
  pause
  exit /b 1
)
echo ==============================================================
echo  TP DASH ADMIN (so Tecnoplan) em http://localhost:8071
echo  Entre com o usuario administrador da Tecnoplan do TP DASH online.
echo  O site (1_iniciar_site.bat) precisa estar rodando para os
echo  agentes aparecerem conectados.
echo  Para parar, feche esta janela.
echo ==============================================================
start "" http://localhost:8071
"%PY%" admin_app.py
pause
