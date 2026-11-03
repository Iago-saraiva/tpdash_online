@echo off
title TP DASH online - AGENTE (teste local)
cd /d "%~dp0agente"
set PY=%~dp0..\painel_puma\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo [ERRO] Nao encontrei o Python do painel em %PY%
  pause
  exit /b 1
)
echo ==============================================================
echo  Agente TP DASH: le o banco do Puma e responde ao site.
echo  Se aparecer erro de permissao no config.ini do painel,
echo  feche e rode este arquivo com "Executar como administrador".
echo  Para parar, feche esta janela.
echo ==============================================================
"%PY%" agente.py
pause
