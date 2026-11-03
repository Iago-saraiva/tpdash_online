@echo off
setlocal
cd /d "%~dp0"
title TP DASH Agente - gerar executavel
rem Gera o TPDashAgente.exe (aplicativo com janela) e monta a pasta "distribuir\TPDashAgente".
rem Precisa do ambiente .venv criado pelo instalar_agente.bat (versao com Python).
if not exist ".venv\Scripts\python.exe" (echo [ERRO] Rode antes o instalar_agente.bat para criar o .venv. & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller || (echo [ERRO] Falha ao instalar o PyInstaller. & pause & exit /b 1)
set ICONE=
if exist "..\site\static\icone.ico" set ICONE=--icon "%~dp0..\site\static\icone.ico" --add-data "%~dp0..\site\static\icone.ico;."
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name TPDashAgente %ICONE% ^
  --collect-submodules firebird --copy-metadata firebird-driver --copy-metadata firebird-base ^
  --workpath build --distpath dist --specpath build agente_app.py || (echo [ERRO] Falha ao gerar o executavel. & pause & exit /b 1)
set DEST=pacote\TPDashAgente
if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"
copy /y "dist\TPDashAgente.exe" "%DEST%\" >nul
copy /y LEIA-ME-AGENTE.txt "%DEST%\" >nul
certutil -hashfile "%DEST%\TPDashAgente.exe" SHA256 > "%DEST%\HASH-SHA256.txt"
echo.
echo Pronto: pasta %DEST% (sem configuracao: cada servidor faz a sua pela janela do agente).
pause
