"""TP DASH Agente - aplicativo com janela.

TPDashAgente.exe             abre a janela (pede login; no primeiro uso cria o login)
TPDashAgente.exe --servico   roda o agente em segundo plano (é assim que o Windows o inicia)

A configuração (site, chaves e bancos) fica em dados\\agente.dat, cifrada pelo Windows. Não há config.ini.
"""
import os
import re
import queue
import subprocess
import sys
import threading
import time

import cofre
import config

TAREFA = "TP DASH Agente"
TITULO = "TP DASH Agente"


# ====================================================================== Windows: admin e tarefa
def _sem_janela():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW


def eh_admin():
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def pedir_admin():
    """Abre de novo como administrador (o Windows mostra a pergunta de permissão). True se reabriu."""
    import ctypes
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, ""
    else:
        exe, args = sys.executable, f'"{os.path.abspath(__file__)}"'
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, config.BASE_DIR, 1)
    return r > 32


def _comando_servico():
    if getattr(sys, "frozen", False):
        return sys.executable, "--servico"
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return (pyw if os.path.exists(pyw) else sys.executable), f'"{os.path.abspath(__file__)}" --servico'


def _powershell(script, timeout=60):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=timeout, **_sem_janela())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "erro no PowerShell").strip().splitlines()[-1])
    return (r.stdout or "").strip()


def _ps_texto(t):
    return "'" + str(t).replace("'", "''") + "'"


def instalar_servico():
    """Cria/atualiza a tarefa do Windows que roda o agente com o Windows (como LOCAL SERVICE, sem janela)
    e deixa a pasta legível só por administradores, SYSTEM e o serviço."""
    if sys.platform != "win32":
        raise RuntimeError("Só no Windows.")
    exe, args = _comando_servico()
    pasta = config.BASE_DIR
    script = f"""
$ErrorActionPreference = 'Stop'
$acao = New-ScheduledTaskAction -Execute {_ps_texto(exe)} -Argument {_ps_texto(args)} -WorkingDirectory {_ps_texto(pasta)}
$gatilhos = @(New-ScheduledTaskTrigger -AtStartup)
try {{ $gatilhos += New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) }} catch {{ }}
$principal = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\\LOCALSERVICE' -LogonType ServiceAccount -RunLevel Limited
$cfg = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName {_ps_texto(TAREFA)} -Action $acao -Trigger $gatilhos -Principal $principal -Settings $cfg -Force | Out-Null
icacls {_ps_texto(pasta)} /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-19:(OI)(CI)M' | Out-Null
"""
    _powershell(script, timeout=120)


def estado_servico():
    """'Running', 'Ready', 'Disabled' ou '' (não instalado)."""
    if sys.platform != "win32":
        return ""
    try:
        return _powershell(f"(Get-ScheduledTask -TaskName {_ps_texto(TAREFA)} -ErrorAction SilentlyContinue).State", 30)
    except Exception:  # noqa: BLE001
        return ""


# O .exe de arquivo único roda em dois processos (o que abre e o que trabalha). Parar a tarefa encerra só o
# primeiro; o segundo continuava sincronizando e, ao iniciar de novo, ficavam dois. Encerra também os que sobraram.
_ENCERRAR_SOBRAS = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--servico*' -and "
                    "($_.Name -like 'TPDashAgente*' -or $_.Name -like 'python*') } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")


def parar_servico():
    if sys.platform == "win32":
        _powershell(f"Stop-ScheduledTask -TaskName {_ps_texto(TAREFA)} -ErrorAction SilentlyContinue; "
                    f"Start-Sleep -Seconds 1; {_ENCERRAR_SOBRAS}")


def iniciar_servico():
    if sys.platform == "win32":
        _powershell(f"Stop-ScheduledTask -TaskName {_ps_texto(TAREFA)} -ErrorAction SilentlyContinue; "
                    f"Start-Sleep -Seconds 1; {_ENCERRAR_SOBRAS}; Start-Sleep -Seconds 1; "
                    f"Start-ScheduledTask -TaskName {_ps_texto(TAREFA)}")


ESTADOS = {"Running": "Rodando", "Ready": "Parado (pronto para iniciar)", "Disabled": "Desativado",
           "Queued": "Iniciando", "": "Não instalado"}


# ====================================================================== janela
def abrir_janela():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import agente

    raiz = tk.Tk()
    raiz.title(TITULO)
    raiz.minsize(720, 480)
    try:
        ico = os.path.join(getattr(sys, "_MEIPASS", config.BASE_DIR), "icone.ico")
        if os.path.exists(ico):
            raiz.iconbitmap(ico)
    except Exception:  # noqa: BLE001
        pass
    estilo = ttk.Style(raiz)
    if "vista" in estilo.theme_names():
        estilo.theme_use("vista")
    estilo.configure("Titulo.TLabel", font=("Segoe UI", 14, "bold"))
    estilo.configure("Aviso.TLabel", foreground="#b42318")
    estilo.configure("Ok.TLabel", foreground="#067647")

    estado = {"dados": None, "falhas": 0, "bloqueio": 0.0}
    tarefas = queue.Queue()

    def em_segundo_plano(fn, ao_terminar):
        """Roda fn sem travar a janela e chama ao_terminar(resultado, erro) depois."""
        def rodar():
            try:
                tarefas.put((ao_terminar, fn(), None))
            except Exception as e:  # noqa: BLE001
                tarefas.put((ao_terminar, None, e))
        threading.Thread(target=rodar, daemon=True).start()

    def conferir_tarefas():
        try:
            while True:
                cb, r, e = tarefas.get_nowait()
                cb(r, e)
        except queue.Empty:
            pass
        raiz.after(150, conferir_tarefas)

    raiz.after(150, conferir_tarefas)

    corpo = ttk.Frame(raiz, padding=16)
    corpo.pack(fill="both", expand=True)

    def limpar():
        for w in corpo.winfo_children():
            w.destroy()

    def campo(pai, rotulo, linha, segredo=False, largura=40, valor=""):
        ttk.Label(pai, text=rotulo).grid(row=linha, column=0, sticky="w", pady=4, padx=(0, 10))
        v = tk.StringVar(value=valor)
        e = ttk.Entry(pai, textvariable=v, width=largura, show="•" if segredo else "")
        e.grid(row=linha, column=1, sticky="we", pady=4)
        return v, e

    # ------------------------------------------------------------------ primeiro acesso
    def tela_primeiro_acesso():
        limpar()
        raiz.title(TITULO + " - primeiro acesso")
        ttk.Label(corpo, text="Bem-vindo ao TP DASH Agente", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(corpo, wraplength=640, text="Crie o login que vai proteger esta tela. Ele vale só neste "
                  "servidor e não é o login do site.").pack(anchor="w", pady=(4, 12))
        f = ttk.Frame(corpo)
        f.pack(anchor="w")
        login, e1 = campo(f, "Login", 0, valor="admin")
        senha, _ = campo(f, "Senha", 1, segredo=True)
        confirma, _ = campo(f, "Confirmar senha", 2, segredo=True)
        importar = tk.BooleanVar(value=os.path.exists(config.CONFIG_PATH))
        if os.path.exists(config.CONFIG_PATH):
            ttk.Checkbutton(corpo, variable=importar, text="Trazer as empresas do config.ini atual (e depois "
                            "apagar o config.ini)").pack(anchor="w", pady=(10, 0))
        msg = ttk.Label(corpo, text="", style="Aviso.TLabel")
        msg.pack(anchor="w", pady=6)

        def criar():
            if not login.get().strip():
                msg.config(text="Informe o login.")
                return
            erro = cofre.senha_fraca(senha.get())
            if erro:
                msg.config(text=erro)
                return
            if senha.get() != confirma.get():
                msg.config(text="As senhas não conferem.")
                return
            d = cofre.novo()
            cofre.definir_usuario(d, login.get(), senha.get())
            apagar_ini = False
            if importar.get():
                try:
                    d["site"], d["empresas"] = agente.importar_config_ini()
                    apagar_ini = True
                except BaseException as e:  # noqa: BLE001 - SystemExit do leitor antigo vira aviso
                    messagebox.showwarning(TITULO, f"Não consegui trazer o config.ini: {e}\n"
                                           "Cadastre as empresas na próxima tela.")
            cofre.salvar(d)
            if apagar_ini:
                try:
                    os.remove(config.CONFIG_PATH)
                except OSError as e:
                    messagebox.showwarning(TITULO, f"Empresas importadas, mas não consegui apagar o config.ini: {e}")
            estado["dados"] = d
            tela_principal()

        ttk.Button(corpo, text="Criar acesso", command=criar).pack(anchor="w")
        e1.focus_set()
        raiz.bind("<Return>", lambda _e: criar())

    # ------------------------------------------------------------------ login
    def tela_login():
        limpar()
        raiz.title(TITULO + " - entrar")
        ttk.Label(corpo, text="TP DASH Agente", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(corpo, text="Entre com o login deste agente.").pack(anchor="w", pady=(4, 12))
        f = ttk.Frame(corpo)
        f.pack(anchor="w")
        login, e1 = campo(f, "Login", 0)
        senha, _ = campo(f, "Senha", 1, segredo=True)
        msg = ttk.Label(corpo, text="", style="Aviso.TLabel")
        msg.pack(anchor="w", pady=6)

        def entrar():
            if time.time() < estado["bloqueio"]:
                msg.config(text=f"Muitas tentativas. Aguarde {int(estado['bloqueio'] - time.time()) + 1} s.")
                return
            try:
                d = cofre.carregar()
            except cofre.ErroCofre as e:
                msg.config(text=str(e))
                return
            if cofre.conferir(d, login.get(), senha.get()):
                estado["dados"], estado["falhas"] = d, 0
                tela_principal()
                return
            estado["falhas"] += 1
            senha.set("")
            if estado["falhas"] >= 5:
                estado["bloqueio"], estado["falhas"] = time.time() + 60, 0
                msg.config(text="Muitas tentativas erradas. Aguarde 1 minuto.")
            else:
                msg.config(text="Login ou senha incorretos.")

        ttk.Button(corpo, text="Entrar", command=entrar).pack(anchor="w")
        ttk.Label(corpo, wraplength=640, foreground="#667085", text="Esqueceu a senha? Um administrador do Windows "
                  "pode apagar o arquivo dados\\agente.dat e configurar de novo (será preciso informar as "
                  "chaves e os bancos outra vez).").pack(anchor="w", pady=(18, 0))
        e1.focus_set()
        raiz.bind("<Return>", lambda _e: entrar())

    # ------------------------------------------------------------------ empresa (cadastro/edição)
    def dialogo_empresa(emp=None, ao_salvar=None):
        emp = dict(emp or {})
        b = cofre.banco_completo(emp.get("banco"))
        dlg = tk.Toplevel(raiz)
        dlg.title("Empresa")
        dlg.transient(raiz)
        dlg.grab_set()
        dlg.resizable(False, False)
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Chave gerada no site (Empresas > Gerar chave)").grid(row=0, column=0, columnspan=3, sticky="w")
        chave, e_chave = campo(f, "Chave", 1, segredo=True, largura=52, valor=emp.get("chave", ""))
        mostrar = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="mostrar", variable=mostrar,
                        command=lambda: e_chave.config(show="" if mostrar.get() else "•")).grid(row=1, column=2, padx=6)
        nome, _ = campo(f, "Nome (opcional)", 2, largura=52, valor=emp.get("nome", ""))
        ttk.Separator(f).grid(row=3, column=0, columnspan=3, sticky="we", pady=10)
        ttk.Label(f, text="Banco do Puma (Firebird) desta empresa").grid(row=4, column=0, columnspan=3, sticky="w")
        host, _ = campo(f, "Servidor", 5, largura=52, valor=b["host"])
        porta, _ = campo(f, "Porta", 6, largura=10, valor=str(b["porta"]))
        arquivo, _ = campo(f, "Arquivo do banco", 7, largura=52, valor=b["arquivo"])

        def procurar():
            p = filedialog.askopenfilename(parent=dlg, title="Banco do Puma",
                                           filetypes=[("Banco Firebird", "*.fdb *.FDB"), ("Todos", "*.*")])
            if p:
                arquivo.set(os.path.normpath(p))

        ttk.Button(f, text="Procurar...", command=procurar).grid(row=7, column=2, padx=6)
        usuario, _ = campo(f, "Usuário", 8, largura=30, valor=b["usuario"])
        senha, _ = campo(f, "Senha", 9, segredo=True, largura=30, valor=b["senha"])
        codigo, _ = campo(f, "Código da empresa no Puma", 10, largura=10, valor=str(b["empresa"]))
        charset, _ = campo(f, "Charset", 11, largura=14, valor=b["charset"])
        fbclient, _ = campo(f, "fbclient.dll (opcional)", 12, largura=52, valor=b["fbclient"])
        msg = ttk.Label(f, text="", wraplength=560)
        msg.grid(row=13, column=0, columnspan=3, sticky="w", pady=8)

        def montar():
            ch = chave.get().strip()
            if "." not in ch:
                raise ValueError("Cole a chave inteira gerada no site (formato empresa.código).")
            try:
                p, c = int(porta.get()), int(codigo.get())
            except ValueError:
                raise ValueError("Porta e código da empresa precisam ser números.") from None
            if not arquivo.get().strip():
                raise ValueError("Informe o arquivo do banco.")
            return {"id": cofre.id_empresa(ch), "nome": nome.get().strip() or emp.get("nome") or cofre.id_empresa(ch),
                    "chave": ch, "ativa": emp.get("ativa", True),
                    "banco": {"modo": b.get("modo", "firebird"), "host": host.get().strip() or "localhost", "porta": p,
                              "arquivo": arquivo.get().strip(), "usuario": usuario.get().strip(),
                              "senha": senha.get(), "charset": charset.get().strip() or "WIN1252",
                              "fbclient": fbclient.get().strip(), "empresa": c}}

        def testar():
            try:
                e = montar()
            except ValueError as ex:
                msg.config(text=str(ex), style="Aviso.TLabel")
                return
            msg.config(text="Testando banco e site...", style="TLabel")
            site = var_site.get() if var_site else (estado["dados"] or {}).get("site", "")

            def fim(r, erro):
                if not dlg.winfo_exists():
                    return
                if erro:
                    msg.config(text=f"Erro: {erro}", style="Aviso.TLabel")
                    return
                ok, texto = r
                msg.config(text=texto, style="Ok.TLabel" if ok else "Aviso.TLabel")
                if ok and not nome.get().strip():
                    nome.set(texto.split("conectado como ", 1)[-1].rstrip("."))
            em_segundo_plano(lambda: agente.testar_empresa(site, e), fim)

        def salvar():
            try:
                e = montar()
            except ValueError as ex:
                msg.config(text=str(ex), style="Aviso.TLabel")
                return
            if ao_salvar(e, emp.get("id")):
                dlg.destroy()

        bts = ttk.Frame(f)
        bts.grid(row=14, column=0, columnspan=3, sticky="e")
        ttk.Button(bts, text="Testar", command=testar).pack(side="left", padx=4)
        ttk.Button(bts, text="Salvar", command=salvar).pack(side="left", padx=4)
        ttk.Button(bts, text="Cancelar", command=dlg.destroy).pack(side="left", padx=4)
        e_chave.focus_set()

    var_site = None

    # ------------------------------------------------------------------ principal
    def tela_principal():
        nonlocal var_site
        limpar()
        raiz.unbind("<Return>")
        raiz.title(TITULO)
        d = estado["dados"]
        topo = ttk.Frame(corpo)
        topo.pack(fill="x")
        ttk.Label(topo, text="TP DASH Agente", style="Titulo.TLabel").pack(side="left")
        ttk.Label(topo, text=f"versão {agente.VERSAO}", foreground="#667085").pack(side="left", padx=8, pady=(6, 0))
        ttk.Button(topo, text="Sair", command=lambda: (estado.update(dados=None), tela_login())).pack(side="right")
        ttk.Button(topo, text="Trocar senha", command=trocar_senha).pack(side="right", padx=6)

        abas = ttk.Notebook(corpo)
        abas.pack(fill="both", expand=True, pady=(10, 0))
        aba_emp = ttk.Frame(abas, padding=8)
        aba_sinc = ttk.Frame(abas, padding=8)
        abas.add(aba_emp, text="Empresas")
        abas.add(aba_sinc, text="Sincronização")

        fs = ttk.LabelFrame(aba_emp, text="Site TP DASH", padding=10)
        fs.pack(fill="x", pady=(4, 8))
        fs.columnconfigure(1, weight=1)
        var_site, _ = campo(fs, "Endereço", 0, largura=60, valor=d.get("site", ""))
        ttk.Label(fs, text="ex.: https://dash.suaempresa.com.br  (teste: http://localhost:8070 ou http://NOME-OU-IP-DO-SITE:8070)",
                  foreground="#667085").grid(row=1, column=1, sticky="w")

        fe = ttk.LabelFrame(aba_emp, text="Empresas atendidas por este agente", padding=10)
        fe.pack(fill="both", expand=True)
        arv = ttk.Treeview(fe, columns=("nome", "banco", "situacao"), show="headings", height=6)
        for c, t, w in (("nome", "Empresa", 200), ("banco", "Banco", 300), ("situacao", "Último teste", 220)):
            arv.heading(c, text=t)
            arv.column(c, width=w, anchor="w")
        arv.pack(fill="both", expand=True, side="left")
        bt = ttk.Frame(fe)
        bt.pack(side="left", fill="y", padx=(10, 0))
        situacoes = {}

        def recarregar():
            arv.delete(*arv.get_children())
            for e in d["empresas"]:
                b = cofre.banco_completo(e.get("banco"))
                arv.insert("", "end", iid=e["id"], values=(e.get("nome") or e["id"], f"{b['host']}:{b['arquivo']}",
                                                          situacoes.get(e["id"], "")))

        def selecionada():
            s = arv.selection()
            return next((e for e in d["empresas"] if s and e["id"] == s[0]), None)

        def gravar_empresa(nova, id_antigo):
            outros = [e for e in d["empresas"] if e["id"] != id_antigo]
            if any(e["id"] == nova["id"] for e in outros):
                messagebox.showerror(TITULO, "Essa empresa já está cadastrada neste agente.")
                return False
            d["empresas"] = outros + [nova]
            gravar()
            recarregar()
            return True

        def remover():
            e = selecionada()
            if e and messagebox.askyesno(TITULO, f"Remover {e.get('nome') or e['id']} deste agente?"):
                d["empresas"] = [x for x in d["empresas"] if x["id"] != e["id"]]
                gravar()
                recarregar()

        def testar_todas():
            site = var_site.get().strip()
            for e in d["empresas"]:
                situacoes[e["id"]] = "testando..."
            recarregar()
            for e in list(d["empresas"]):
                def fim(r, erro, eid=e["id"]):
                    ok, texto = r if r else (False, str(erro))
                    situacoes[eid] = ("OK" if ok else "ERRO: ") + ("" if ok else texto)
                    recarregar()
                    if not ok:
                        messagebox.showwarning(TITULO, f"{eid}: {texto}")
                em_segundo_plano(lambda e=e: agente.testar_empresa(site, e), fim)

        ttk.Button(bt, text="Adicionar", command=lambda: dialogo_empresa(None, gravar_empresa)).pack(fill="x", pady=2)
        ttk.Button(bt, text="Editar", command=lambda: selecionada() and dialogo_empresa(selecionada(), gravar_empresa)).pack(fill="x", pady=2)
        ttk.Button(bt, text="Remover", command=remover).pack(fill="x", pady=2)
        ttk.Button(bt, text="Testar todas", command=testar_todas).pack(fill="x", pady=(12, 2))
        arv.bind("<Double-1>", lambda _e: selecionada() and dialogo_empresa(selecionada(), gravar_empresa))

        montar_sincronizacao(aba_sinc, d)

        fv = ttk.LabelFrame(corpo, text="Funcionamento", padding=10)
        fv.pack(fill="x", pady=(8, 0))
        lb_estado = ttk.Label(fv, text="Situação: verificando...")
        lb_estado.pack(side="left")

        def atualizar_estado():
            em_segundo_plano(estado_servico, lambda r, e: lb_estado.winfo_exists() and lb_estado.config(
                text="Situação: " + ESTADOS.get(r or "", r or "Não instalado")))

        def salvar_e_iniciar():
            erro = agente.erro_endereco(var_site.get())
            if erro:
                messagebox.showerror(TITULO, erro)
                return
            if not d["empresas"]:
                messagebox.showerror(TITULO, "Cadastre pelo menos uma empresa.")
                return
            gravar()
            lb_estado.config(text="Situação: instalando e iniciando...")

            def fazer():
                instalar_servico()
                iniciar_servico()
                time.sleep(2)
                return estado_servico()

            def fim(r, e):
                if e:
                    messagebox.showerror(TITULO, f"Não consegui iniciar o agente: {e}")
                atualizar_estado()
            em_segundo_plano(fazer, fim)

        def parar():
            em_segundo_plano(parar_servico, lambda r, e: atualizar_estado())

        ttk.Button(fv, text="Ver registro", command=ver_registro).pack(side="right")
        ttk.Button(fv, text="Parar", command=parar).pack(side="right", padx=6)
        ttk.Button(fv, text="Salvar e iniciar", command=salvar_e_iniciar).pack(side="right")
        recarregar()
        atualizar_estado()

    # ------------------------------------------------------------------ aba Sincronização
    def montar_sincronizacao(pai, d):
        import sincronizar
        cfg = sincronizar._validar({**sincronizar.PADRAO, **(d.get("sincronizacao") or {})})
        fc = ttk.LabelFrame(pai, text="Consultas ao banco para atualizar o site", padding=10)
        fc.pack(fill="x")
        v_ativa = tk.BooleanVar(value=cfg["ativa"])
        ttk.Checkbutton(fc, text="Manter uma cópia dos dados no site (respostas mais rápidas no TP DASH)",
                        variable=v_ativa).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(fc, text="Consultar o banco a cada").grid(row=1, column=0, sticky="w", pady=(8, 4))
        opcoes = [f"{m} minutos" if m < 60 else (f"{m // 60} hora" if m == 60 else f"{m // 60} horas")
                  for m in sincronizar.INTERVALOS]
        v_int = tk.StringVar(value=opcoes[sincronizar.INTERVALOS.index(cfg["intervalo_min"])]
                             if cfg["intervalo_min"] in sincronizar.INTERVALOS else f"{cfg['intervalo_min']} minutos")
        ttk.Combobox(fc, textvariable=v_int, values=opcoes, state="readonly", width=14).grid(row=1, column=1, sticky="w", pady=(8, 4))
        ttk.Label(fc, text="Não consultar entre").grid(row=2, column=0, sticky="w", pady=4)
        v_ini = tk.StringVar(value=cfg["pausa_inicio"])
        v_fim = tk.StringVar(value=cfg["pausa_fim"])
        lp = ttk.Frame(fc)
        lp.grid(row=2, column=1, columnspan=3, sticky="w")
        ttk.Entry(lp, textvariable=v_ini, width=7).pack(side="left")
        ttk.Label(lp, text=" e ").pack(side="left")
        ttk.Entry(lp, textvariable=v_fim, width=7).pack(side="left")
        ttk.Label(lp, text="  (ex.: 23:00 e 06:00, horário do backup; vazio = sempre)", foreground="#667085").pack(side="left")
        ttk.Label(fc, text="Na primeira vez o agente envia todas as tabelas usadas pelo TP DASH (pode levar alguns minutos). "
                           "Depois envia só o que foi incluído, alterado ou apagado.", foreground="#667085",
                  wraplength=640).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        def salvar_sinc():
            ini, fim = v_ini.get().strip(), v_fim.get().strip()
            for v in (ini, fim):
                if v and not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", v):
                    messagebox.showerror(TITULO, f"Horário inválido: {v}. Use HH:MM, por exemplo 23:00.")
                    return
            if bool(ini) != bool(fim):
                messagebox.showerror(TITULO, "Preencha os dois horários da pausa, ou deixe os dois vazios.")
                return
            m = sincronizar.INTERVALOS[opcoes.index(v_int.get())] if v_int.get() in opcoes else cfg["intervalo_min"]
            d["sincronizacao"] = {"ativa": bool(v_ativa.get()), "intervalo_min": m, "pausa_inicio": ini, "pausa_fim": fim}
            gravar()
            messagebox.showinfo(TITULO, "Sincronização salva. O agente em funcionamento usa a nova configuração em até 1 minuto.")

        ttk.Button(fc, text="Salvar", command=salvar_sinc).grid(row=1, column=3, sticky="e", padx=(20, 0))
        fc.columnconfigure(2, weight=1)

        fl = ttk.LabelFrame(pai, text="Situação por empresa", padding=10)
        fl.pack(fill="both", expand=True, pady=(8, 0))
        cols = (("nome", "Empresa", 150), ("carga", "Carga inicial", 170), ("ultima", "Última rodada", 190),
                ("mud", "Mudanças", 170), ("prox", "Próxima", 110))
        arv = ttk.Treeview(fl, columns=[c[0] for c in cols], show="headings", height=5)
        for c, t, w in cols:
            arv.heading(c, text=t)
            arv.column(c, width=w, anchor="w")
        arv.pack(fill="both", expand=True, side="left")
        lb_erro = ttk.Label(pai, text="", style="Aviso.TLabel", wraplength=680)
        lb_erro.pack(fill="x", pady=(4, 0))
        bt = ttk.Frame(fl)
        bt.pack(side="left", fill="y", padx=(10, 0))

        def atualizar(agendar=False):
            if not arv.winfo_exists():
                return
            sel = arv.selection()
            arv.delete(*arv.get_children())
            erros = []
            for e in d["empresas"]:
                est = sincronizar.ler_estado(e["id"])
                ult = f"{est['ultima']} ({est.get('duracao_s', 0):.0f} s)" if est.get("ultima") else "ainda não rodou"
                mud = (f"{est.get('inseridas', 0)} novas, {est.get('alteradas', 0)} alt., {est.get('apagadas', 0)} apag."
                       if est.get("ultima") else "")
                carga = "refazer na próxima" if est.get("refazer") else (est.get("carga_inicial") or "pendente")
                arv.insert("", "end", iid=e["id"], values=(e.get("nome") or e["id"], carga, ult, mud, est.get("proxima") or ""))
                if est.get("erro"):
                    erros.append(f"{e.get('nome') or e['id']}: {est['erro']}")
            if sel and arv.exists(sel[0]):
                arv.selection_set(sel[0])
            lb_erro.config(text="\n".join(erros))
            if agendar:
                pai.after(10000, lambda: atualizar(True))

        def refazer():
            s_ = arv.selection()
            if not s_:
                messagebox.showinfo(TITULO, "Escolha a empresa na lista.")
                return
            if messagebox.askyesno(TITULO, "Enviar de novo todas as tabelas desta empresa para o site na próxima rodada?"):
                sincronizar.pedir_carga_completa(s_[0])
                atualizar()

        ttk.Button(bt, text="Atualizar", command=atualizar).pack(fill="x", pady=2)
        ttk.Button(bt, text="Refazer carga", command=refazer).pack(fill="x", pady=2)
        atualizar(True)

    def gravar():
        d = estado["dados"]
        if var_site is not None:
            d["site"] = var_site.get().strip().rstrip("/")
        cofre.salvar(d)

    def trocar_senha():
        dlg = tk.Toplevel(raiz)
        dlg.title("Trocar senha")
        dlg.transient(raiz)
        dlg.grab_set()
        f = ttk.Frame(dlg, padding=16)
        f.pack()
        atual, _ = campo(f, "Senha atual", 0, segredo=True, largura=28)
        nova, _ = campo(f, "Nova senha", 1, segredo=True, largura=28)
        conf, _ = campo(f, "Confirmar", 2, segredo=True, largura=28)
        msg = ttk.Label(f, text="", style="Aviso.TLabel")
        msg.grid(row=3, column=0, columnspan=2, sticky="w", pady=6)

        def ok():
            d = estado["dados"]
            if not cofre.conferir(d, d["usuario"]["login"], atual.get()):
                msg.config(text="Senha atual incorreta.")
                return
            erro = cofre.senha_fraca(nova.get()) or (None if nova.get() == conf.get() else "As senhas não conferem.")
            if erro:
                msg.config(text=erro)
                return
            cofre.definir_usuario(d, d["usuario"]["login"], nova.get())
            gravar()
            dlg.destroy()
            messagebox.showinfo(TITULO, "Senha trocada.")

        ttk.Button(f, text="Trocar", command=ok).grid(row=4, column=1, sticky="e")

    def ver_registro():
        dlg = tk.Toplevel(raiz)
        dlg.title("Registro do agente")
        dlg.geometry("900x420")
        txt = tk.Text(dlg, wrap="none", font=("Consolas", 9))
        txt.pack(fill="both", expand=True)

        def carregar():
            try:
                with open(agente.LOG, encoding="utf-8", errors="replace") as f:
                    linhas = f.readlines()[-300:]
            except OSError:
                linhas = ["(ainda não há registro)"]
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", "".join(linhas))
            txt.see("end")
            txt.config(state="disabled")

        ttk.Button(dlg, text="Atualizar", command=carregar).pack(anchor="e", padx=8, pady=6)
        carregar()

    try:
        tela_login() if cofre.existe() else tela_primeiro_acesso()
    except cofre.ErroCofre as e:
        messagebox.showerror(TITULO, str(e))
        raiz.destroy()
        return
    raiz.mainloop()


def main():
    if "--servico" in sys.argv or "--testar" in sys.argv:
        import agente
        agente.main()
        return
    if not eh_admin():
        try:
            if pedir_admin():
                return
        except Exception:  # noqa: BLE001
            pass
        import tkinter as tk
        from tkinter import messagebox
        tk.Tk().withdraw()
        messagebox.showerror(TITULO, "Abra o TP DASH Agente como administrador.")
        return
    abrir_janela()


if __name__ == "__main__":
    main()
