@echo off
setlocal
cd /d "%~dp0"
title TP DASH Agente - gerar executavel para Windows antigo (Server 2012 / Windows 8 / 7)
rem Gera o TPDashAgente.exe com Python 3.8 (ultima versao que roda no Windows Server 2012, Windows 8 e 7).
rem Usa um ambiente separado (.venv38) e nao mexe no .venv nem no gerar_exe.bat normal.
rem Precisa do Python 3.8.10 64 bits instalado neste PC (o lancador "py -3.8" deve funcionar).

py -3.8 -c "import sys" >nul 2>&1 || (echo [ERRO] Python 3.8 nao encontrado. Instale o Python 3.8.10 64 bits e tente de novo. & pause & exit /b 1)

if not exist ".venv38\Scripts\python.exe" (
  echo Criando o ambiente .venv38 com Python 3.8...
  py -3.8 -m venv .venv38 || (echo [ERRO] Falha ao criar o .venv38. & pause & exit /b 1)
)
".venv38\Scripts\python.exe" -m pip install --upgrade pip || (echo [ERRO] Falha ao atualizar o pip. & pause & exit /b 1)
".venv38\Scripts\python.exe" -m pip install "firebird-driver>=1.10,<2" "pyinstaller==6.10.0" || (echo [ERRO] Falha ao instalar as dependencias. & pause & exit /b 1)

set ICONE=
if exist "..\site\static\icone.ico" set ICONE=--icon "%~dp0..\site\static\icone.ico" --add-data "%~dp0..\site\static\icone.ico;."
".venv38\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name TPDashAgente %ICONE% ^
  --collect-submodules firebird --copy-metadata firebird-driver --copy-metadata firebird-base ^
  --workpath build38 --distpath dist38 --specpath build38 agente_app.py || (echo [ERRO] Falha ao gerar o executavel. & pause & exit /b 1)

set DEST=pacote\TPDashAgente_Win2012
if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"
copy /y "dist38\TPDashAgente.exe" "%DEST%\" >nul
copy /y LEIA-ME-AGENTE.txt "%DEST%\" >nul
certutil -hashfile "%DEST%\TPDashAgente.exe" SHA256 > "%DEST%\HASH-SHA256.txt"
echo.
echo Pronto: pasta %DEST% (versao para Windows Server 2012 / Windows 8 / 7).
pause
