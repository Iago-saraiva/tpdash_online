# TP DASH online: como colocar o site no ar

## 1. Servidor (VPS Ubuntu 24.04, 2 núcleos, 4 GB)
```
sudo adduser --system --group --home /opt/tpdash tpdash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx
sudo -u tpdash mkdir -p /opt/tpdash/site      # copie (ou git clone) a pasta site/ para cá
cd /opt/tpdash/site
sudo -u tpdash python3 -m venv .venv
sudo -u tpdash .venv/bin/pip install -r requirements.txt
sudo -u tpdash cp implantacao/config.ini.site config.ini
```

## 2. Serviço e HTTPS
```
sudo cp implantacao/tpdash.service /etc/systemd/system/ && sudo systemctl enable --now tpdash
sudo cp implantacao/nginx-tpdash.conf /etc/nginx/sites-available/tpdash   # troque o domínio
sudo ln -s /etc/nginx/sites-available/tpdash /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d painel.exemplo.com.br
```
O domínio precisa apontar (registro A) para o IP do servidor antes do certbot.

## 3. Primeiro acesso
- Entre com **admin / admin**: é o super administrador (Tecnoplan). Troque a senha.
- Em **Empresas**: cadastre a empresa, clique **Gerar chave** e copie a chave (aparece uma vez só).
- Crie o administrador da empresa no mesmo lugar.

## 4. No servidor do cliente
- Copie a pasta `agente/`, rode `instalar_agente.bat` como Administrador.
- No `config.ini` que abrir: dados do banco do Puma e, em `[nuvem]`, o endereço do site e a chave.
- O agente só faz conexões de saída (HTTPS). Não precisa abrir porta nem VPN.

## Observações
- O site roda em **um processo** (os pedidos aos agentes ficam na memória). Não use vários workers.
- Faça backup do arquivo `dados/painel.sqlite` (empresas, usuários, consultas salvas e layouts).
- A sincronização automática do ReportBuilder fica desligada no site; use o botão em Administração.
