@echo off
title TP DASH online - SITE (teste local)
cd /d "%~dp0site"
set PY=%~dp0..\painel_puma\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo [ERRO] Nao encontrei o Python do painel em %PY%
  echo Coloque a pasta tpdash_online ao lado da pasta painel_puma.
  pause
  exit /b 1
)
rem imagens (logos e icones): copiadas do painel atual, que ja tem as versoes certas
if not exist "%~dp0site\static\logo-tpdash.svg" (
  xcopy /Y /Q "%~dp0..\painel_puma\static\*.png" "%~dp0site\static\" >nul
  xcopy /Y /Q "%~dp0..\painel_puma\static\*.svg" "%~dp0site\static\" >nul
  xcopy /Y /Q "%~dp0..\painel_puma\static\*.ico" "%~dp0site\static\" >nul
)
echo ==============================================================
echo  Site TP DASH online (teste)
echo.
echo  Neste computador:  http://localhost:8070
echo  No celular ou em outro computador da mesma rede, use um destes:
echo    http://%COMPUTERNAME%:8070
echo    http://%COMPUTERNAME%.local:8070
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { '   http://' + $_.IPAddress + ':8070' }"
echo  (se nao abrir de fora, rode o 3_liberar_rede.bat como administrador)
echo.
echo  Primeiro acesso: usuario admin / senha admin
echo  Para parar, feche esta janela.
echo ==============================================================
start "" http://localhost:8070
"%PY%" app.py
pause
