# TP DASH online

Painel web do Puma para várias empresas clientes. Cada empresa instala o **TP DASH Agente** no servidor dela;
o agente se conecta ao site (de dentro para fora) e executa as consultas no banco Firebird da empresa.
O site nunca acessa o banco diretamente e nenhum dado das empresas fica guardado nele.

| Pasta | O que é |
|---|---|
| `site/` | Site TP DASH online (Flask). Telas, usuários, permissões e a ponte com os agentes. |
| `admin/` | TP DASH ADMIN (só Tecnoplan): empresas, chaves dos agentes, filiais e usuários. |
| `agente/` | TP DASH Agente (programa instalado no servidor de cada cliente). |
| `servidor_nuvem.py` | Inicia o site e o ADMIN juntos na hospedagem (Render). |
| `render.yaml` | Configuração do serviço no Render. |

**Nunca vão para o GitHub** (ver `.gitignore`): `config.ini`, `admin.ini`, pastas `dados/`, bancos `.sqlite`,
`agente.dat`, executáveis, backups e logs. Mantenha o repositório **privado**.

## Publicar no Render

1. No Render: **New > Blueprint**, escolha este repositório. Ele lê o `render.yaml`.
2. Preencha as variáveis pedidas:
   - `TPDASH_ADMIN_CAMINHO`: caminho do ADMIN enquanto não houver domínio próprio, difícil de adivinhar
     (ex.: `/adm-` seguido de 10 letras e números). O ADMIN fica em `https://<serviço>.onrender.com/<caminho>`.
   - `TPDASH_ADMIN_HOST`: deixe vazio até ter domínio (veja abaixo).
   - `TPDASH_ADMIN_PERMITIR` (opcional): IP fixo da Tecnoplan, para só ela abrir o ADMIN.
3. Confirme o plano **Starter** com o disco de 1 GB (o plano grátis não tem disco e apaga os dados).
4. Primeiro acesso no ADMIN: usuário `admin`, senha `admin`. **Troque a senha na hora.**
5. No ADMIN, cadastre as empresas, gere as chaves e os usuários. No TP DASH Agente de cada cliente,
   coloque o endereço `https://<serviço>.onrender.com` e a chave da empresa.

Atualizar: envie as mudanças para o GitHub (commit + push). O Render publica sozinho e os dados do disco continuam.

### Com domínio próprio (recomendado)

No Render, em **Settings > Custom Domains**, adicione por exemplo `tpdash.seudominio.com.br` e
`admin.seudominio.com.br` (e crie os registros CNAME pedidos no seu provedor de domínio).
Depois coloque `TPDASH_ADMIN_HOST=admin.seudominio.com.br` e apague `TPDASH_ADMIN_CAMINHO`.

## Variáveis de ambiente

| Variável | Para que serve |
|---|---|
| `TPDASH_NUVEM=1` | Modo hospedado: sem `config.ini`/`admin.ini`. |
| `TPDASH_DADOS` | Pasta do disco persistente (padrão no Render: `/var/data`). |
| `TPDASH_CHAVE_SECRETA` / `TPDASH_ADMIN_CHAVE_SECRETA` | Assinam os logins do site e do ADMIN (geradas pelo Render). |
| `TPDASH_ADMIN_HOST` / `TPDASH_ADMIN_CAMINHO` | Endereço do ADMIN (um dos dois; sem nenhum, o ADMIN fica desligado). |
| `TPDASH_ADMIN_PERMITIR`, `TPDASH_PERMITIR` | IPs que podem abrir o ADMIN / o site (vazio = todos). |
| `TPDASH_NOME` | Nome no login do site. |

## Rodar localmente (teste)

`1_iniciar_site.bat` (site, porta 8070) e `4_iniciar_admin.bat` (ADMIN, porta 8071), usando o Python do painel.
