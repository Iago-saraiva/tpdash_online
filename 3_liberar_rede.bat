@echo off
title TP DASH online - liberar acesso pela rede (teste)
echo ==============================================================
echo  Libera a porta 8070 no Firewall do Windows SO para a rede local
echo  (celulares no Wi-Fi da empresa e outros computadores).
echo  Rode como Administrador. Depois reinicie o 1_iniciar_site.bat.
echo ==============================================================
netsh advfirewall firewall delete rule name="TP DASH online (teste)" >nul 2>nul
netsh advfirewall firewall add rule name="TP DASH online (teste)" dir=in action=allow protocol=TCP localport=8070 remoteip=localsubnet
if errorlevel 1 (
  echo [ERRO] Nao consegui criar a regra. Clique com o botao direito e use "Executar como administrador".
  pause
  exit /b 1
)
echo.
echo Pronto. Nos outros aparelhos use: http://IP-DO-SERVIDOR:8070
echo Enderecos deste servidor:
ipconfig | findstr /i "IPv4"
echo.
echo Para remover a liberacao depois do teste:
echo   netsh advfirewall firewall delete rule name="TP DASH online (teste)"
pause
