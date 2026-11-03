@echo off
setlocal
cd /d "%~dp0"
title TP DASH Agente - Instalacao
echo ==============================================================
echo   TP DASH Agente - instalacao (rode como Administrador)
echo ==============================================================
set RODAR="%~dp0TPDashAgente.exe"
if exist "%~dp0TPDashAgente.exe" goto configurar
set RODAR=".venv\Scripts\python.exe" agente.py
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (echo [ERRO] Python nao encontrado. Instale o Python 3.11+ em https://www.python.org/downloads/ & pause & exit /b 1)
echo Criando ambiente Python em .venv ...
%PY% -m venv .venv || (echo [ERRO] Falha ao criar o ambiente. & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo [ERRO] Falha ao instalar bibliotecas. & pause & exit /b 1)
:configurar
if not exist config.ini (
  copy /y config.ini.exemplo config.ini >nul
  echo Preencha o banco do Puma e a chave do site no config.ini que vai abrir, salve e feche.
  notepad config.ini
)
echo Testando banco e site ...
%RODAR% --testar || (echo [ERRO] Confira o config.ini e rode de novo. & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0criar_tarefa_agente.ps1" -Pasta "%~dp0." || (echo [ERRO] Rode como Administrador. & pause & exit /b 1)
echo ==============================================================
echo  Agente instalado. Ele inicia com o Windows e nao precisa de porta aberta.
echo  Registro de funcionamento: dados\agente.log
echo ==============================================================
pause
