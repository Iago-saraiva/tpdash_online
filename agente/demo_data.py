"""Cria um banco SQLite de demonstração com as mesmas tabelas/colunas usadas do Puma e dados fictícios."""
import datetime as dt
import os
import random
import sqlite3

TABELAS = """
CREATE TABLE TTIPOMOV (CODEMPRESA INTEGER, CODTIPOMOV TEXT, NOME TEXT);
CREATE TABLE TVENDEDOR (CODEMPRESA INTEGER, CODVEN TEXT, NOME TEXT);
CREATE TABLE TLOCALEST (CODEMPRESA INTEGER, CODLOC TEXT, NOME TEXT);
CREATE TABLE TGRUPO (CODEMPRESA INTEGER, CODGRUPO TEXT, DESCRICAO TEXT);
CREATE TABLE GFILIAL (CODEMPRESA INTEGER, CODFILIAL INTEGER, NOMEFANTASIA TEXT);
CREATE TABLE TSTRIBUTARIA (CODEMPRESA INTEGER, CODSIT TEXT, DESCRICAO TEXT);
CREATE TABLE FTIPODOC (CODEMPRESA INTEGER, CODTIPODOC TEXT, DESCRICAO TEXT);
CREATE TABLE FCFO (CODEMPRESA INTEGER, CODCFO TEXT, NOME TEXT, NOMEFANTASIA TEXT, TIPO TEXT, PESSOAFISJUR TEXT,
  CGCCFO TEXT, CIDADE TEXT, CODETD TEXT, TELEFONE TEXT, EMAIL TEXT, ATIVO TEXT, DATACRIACAO TEXT, DATAULTVENDA TEXT,
  LIMITECREDITO REAL);
CREATE TABLE TPRODUTO (CODEMPRESA INTEGER, CODPRD TEXT, NUMNOFABRIC TEXT, NOMEFANTASIA TEXT, CODUNDVENDA TEXT, CODGRUPO TEXT, PRECO1 REAL,
  CUSTOMEDIO REAL, SALDOGERALFISICO REAL, CODCLASSFISCAL TEXT, CODCEST TEXT, CODSIT TEXT, CODSIT2 TEXT,
  CST_PISCOFINS TEXT, INATIVO TEXT);
CREATE TABLE TPRODSALDO (CODEMPRESA INTEGER, CODPRD TEXT, CODLOC TEXT, SALDOFISICO1 REAL, CUSTOMEDIO REAL);
CREATE TABLE TMOV (CODEMPRESA INTEGER, IDMOV INTEGER, NUMEROMOV TEXT, CODTMV TEXT, DATAEMISSAO TEXT, STATUS TEXT,
  CODCFO TEXT, CODVEN1 TEXT, CODVEN2 TEXT, CODFILIAL INTEGER, VALORLIQUIDO REAL, VALORBRUTO REAL);
CREATE TABLE TMOVITENS (CODEMPRESA INTEGER, IDMOV INTEGER, NSEQ INTEGER, CODPRD TEXT, CODUND TEXT, QUANTIDADE REAL,
  PRECOUNITARIO REAL, VALORTOTALITEM REAL, FLAGEFEITOSALDO TEXT);
CREATE TABLE FLAN (CODEMPRESA INTEGER, IDLAN INTEGER, PAGREC TEXT, STATUSLAN TEXT, NUMERODOCUMENTO TEXT, PARCELA INTEGER,
  CODCFO TEXT, CODTDO TEXT, DATAEMISSAO TEXT, DATAVENCIMENTO TEXT, DATABAIXA TEXT, VALORORIGINAL REAL,
  VALORBAIXADO REAL, HISTORICO TEXT);
CREATE TABLE FCCUSTO (CODEMPRESA INTEGER, COD TEXT, DESCRICAO TEXT);
CREATE TABLE GDEPARTAMENTO (CODEMPRESA INTEGER, CODFILIAL INTEGER, CODDEPARTAMENTO TEXT, NOME TEXT);
CREATE TABLE FLANRATCCUSTO (CODEMPRESA INTEGER, IDLAN INTEGER, CCUSTO TEXT, ORIGEM TEXT, VALOR REAL, CODDEPARTAMENTO TEXT, CODFILIAL INTEGER);
CREATE TABLE AMAQUINASGRUPO (CODEMPRESA INTEGER, CODIGO TEXT, NOME TEXT);
CREATE TABLE AMAQUINAS (CODIGO TEXT, CODEMPRESA INTEGER, NOME TEXT, NUMSERIE TEXT, ANO TEXT, MODELO TEXT, CHASSI TEXT, NUMMOTOR TEXT,
  OBSERVACAO TEXT, TIPOCONTROLE TEXT, MARCA TEXT, KM REAL, TIPOVERIFICACAO TEXT, INATIVO TEXT, TIPO TEXT, CODFILIAL INTEGER,
  CODGRUPO TEXT, PLACA TEXT);
CREATE INDEX IX_MOV ON TMOV (DATAEMISSAO);
CREATE INDEX IX_ITENS ON TMOVITENS (IDMOV);
CREATE INDEX IX_LAN ON FLAN (DATAVENCIMENTO);
"""

TIPOS = [("1.1.01", "Pedido de Compra"), ("1.2.01", "Entrada NF Compra"), ("2.1.05", "Entrega de Materiais Estoque"),
         ("2.1.07", "Empenho Material p/ NS"), ("2.2.08", "Material Aplicado conforme orçado"),
         ("2.2.10", "Material Aplicado Sem Orçamento"), ("2.2.21", "Empréstimo de Material (Saída)"),
         ("2.3.07", "Devolução de Empréstimo (Entrada)"), ("3.1.01", "Venda de Mercadoria"), ("3.2.01", "Prestação de Serviço")]
# efeito de cada tipo no saldo (como TMOVITENS.FLAGEFEITOSALDO do Puma): A = entrada, D = saída, N = não mexe
EFEITO = {"1.1.01": "NNANNNNNNN", "1.2.01": "AANNNNNNNN", "2.1.05": "DDNNNNNNNN", "2.1.07": "NNNANNNNNN",
          "2.2.08": "DDNNNNNNNN", "2.2.10": "DDNNNNNNNN", "2.2.21": "DDNNNNNNNN", "2.3.07": "AANNNNNNNN",
          "3.1.01": "DDNNNNNNNN", "3.2.01": "NNNNNNNNNN"}
GRUPOS_TIPO = [("1", "Entradas/Compras"), ("1.1", "Pedidos de Compra"), ("1.2", "Movimentos de Compra"), ("2", "Vendas/Saídas"),
               ("2.1", "Pedidos de Venda"), ("2.2", "Movimentos de Venda"), ("2.3", "Devoluções de Venda"),
               ("3", "Faturamento"), ("3.1", "Vendas"), ("3.2", "Serviços")]
VEND = [("011", "ANA PAULA REZENDE"), ("015", "FERNANDO OLIVEIRA"), ("021", "CARLOS SOUZA LIMA"), ("033", "MARCOS VIEIRA"),
        ("047", "JULIANA MARTINS"), ("052", "RAFAEL COSTA"), ("060", "ALMOXARIFADO CENTRAL")]
LOCAIS = [("001", "MATERIAL ELÉTRICO"), ("002", "EPI'S E FERRAMENTAS"), ("005", "MANUTENÇÃO FROTA"), ("011", "ALMOXARIFADO"),
          ("012", "MATERIAL ELÉTRICO NOVO"), ("014", "LUMINÁRIAS MANUTENIDAS")]
GRUPOS = [("01", "CABOS E CONDUTORES"), ("02", "CONECTORES"), ("03", "FERRAGENS"), ("04", "ISOLADORES"), ("05", "ILUMINAÇÃO"),
          ("06", "EPI"), ("07", "PEÇAS DE FROTA"), ("08", "ESCRITÓRIO")]
PRODUTOS = {
    "01": ["CABO TRIPLEX CA 2X1X16+16 1KV", "CABO AL 1X50MM² 15KV", "CABO DE AÇO SM 1/4P 7 FIOS", "CABO FLEX 750V 6MM AZUL", "CABO QUADRUPLEX 3X1X35+35"],
    "02": ["CONECTOR CUNHA CU ITEM 7", "CONECTOR FORMATO H ITEM 2", "CONECTOR PERFURANTE 10-95MM", "TERMINAL COMPRESSÃO 50MM", "LUVA EMENDA COMPRESSÃO CA 50MM"],
    "03": ["BRAÇO SUPORTE L", "CINTA DE AÇO D 280MM", "PARAFUSO CAB. SEXTAVADA M12X40", "ARRUELA QUADRADA 38X18X3", "SELA PARA CRUZETA", "HASTE ATERRAMENTO 2400MM"],
    "04": ["ISOLADOR PINO POLIMÉRICO 15KV", "ISOLADOR ANCORAGEM POLIMÉRICO", "ISOLADOR ROLDANA PORCELANA"],
    "05": ["LUMINÁRIA LED 52W", "LUMINÁRIA LED 100W", "RELÉ FOTOELETRÔNICO 105-305V", "REATOR VAPOR SÓDIO 150W"],
    "06": ["LUVA ISOLANTE CLASSE 2", "CAPACETE COM JUGULAR", "BOTINA DE SEGURANÇA 42", "ÓCULOS DE PROTEÇÃO", "BALACLAVA MALHA CINZA"],
    "07": ["FILTRO DE COMBUSTÍVEL", "ÓLEO MOTOR 5W30", "PASTILHA DE FREIO DIANT.", "BATERIA 60AH"],
    "08": ["CANETA MARCA TEXTO AMARELA", "BLOCO POST-IT 76X102", "PAPEL A4 500 FOLHAS"],
}
CIDADES = [("ARAXA", "MG"), ("PATOS DE MINAS", "MG"), ("UBERLANDIA", "MG"), ("BELO HORIZONTE", "MG"), ("SAO PAULO", "SP"),
           ("ALFENAS", "MG"), ("MONTE CARMELO", "MG"), ("ARAXA", None), ("GOIANIA", "GO"), ("CURITIBA", "PR")]
NOMES_CLI = ["CONSTRUTORA HORIZONTE", "PREFEITURA MUNICIPAL DE {c}", "HOTEL CENTRAL", "AUTO PEÇAS {c}", "ENGENHARIA ELÉTRICA ALFA",
             "CONDOMÍNIO RESIDENCIAL IPÊ", "MERCADO BOM PREÇO", "TRANSPORTADORA RODOMINAS", "COOPERATIVA AGRÍCOLA", "CONCESSIONÁRIA ENERGIA",
             "MADEIREIRA SÃO JOSÉ", "POSTO CONFIANÇA", "CLÍNICA VIDA", "SINDICATO RURAL", "INDÚSTRIA METALÚRGICA BETA"]


def criar(caminho):
    rnd = random.Random(42)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if os.path.exists(caminho):
        os.remove(caminho)
    con = sqlite3.connect(caminho)
    con.executescript(TABELAS)
    E = 1
    con.executemany("INSERT INTO TTIPOMOV VALUES (?,?,?)", [(E, c, n) for c, n in TIPOS + GRUPOS_TIPO])
    con.executemany("INSERT INTO TVENDEDOR VALUES (?,?,?)", [(E, c, n) for c, n in VEND])
    con.executemany("INSERT INTO TLOCALEST VALUES (?,?,?)", [(E, c, n) for c, n in LOCAIS])
    con.executemany("INSERT INTO TGRUPO VALUES (?,?,?)", [(E, c, n) for c, n in GRUPOS])
    con.executemany("INSERT INTO GFILIAL VALUES (?,?,?)", [(E, 1, "MATRIZ"), (E, 2, "FILIAL TORRES")])
    con.executemany("INSERT INTO TSTRIBUTARIA VALUES (?,?,?)", [(E, "000", "TRIBUTADO"), (E, "FF", "SUBST. TRIBUTARIA"), (E, "II", "ISENTO")])
    con.executemany("INSERT INTO FTIPODOC VALUES (?,?,?)", [(E, "NF", "NOTA FISCAL"), (E, "BOL", "BOLETO"), (E, "DUP", "DUPLICATA"), (E, "PIX", "PIX")])

    hoje = dt.date.today()
    # clientes / fornecedores
    clientes = []
    for i in range(1, 181):
        cidade, uf = rnd.choice(CIDADES)
        base = rnd.choice(NOMES_CLI).format(c=cidade)
        nome = f"{base} {rnd.choice(['LTDA', 'ME', 'S/A', 'EIRELI', ''])}".strip()
        tipo = rnd.choices(["A", "C", "F"], [80, 12, 8])[0]
        pj = rnd.random() < .8
        cod = f"C{i:06d}"
        doc = (f"{rnd.randint(10, 99)}.{rnd.randint(100, 999)}.{rnd.randint(100, 999)}/0001-{rnd.randint(10, 99)}" if pj
               else f"{rnd.randint(100, 999)}.{rnd.randint(100, 999)}.{rnd.randint(100, 999)}-{rnd.randint(10, 99)}")
        email = rnd.choice(["NAOTEM@NAOTEM.COM", f"contato{i}@empresa.com.br", f"financeiro{i}@cliente.com.br"])
        criado = hoje - dt.timedelta(days=rnd.randint(10, 1500))
        clientes.append((E, cod, nome, nome, tipo, "J" if pj else "F", doc, cidade, uf, f"34{rnd.randint(30000000, 99999999)}",
                         email, "T" if rnd.random() < .97 else "F", criado.isoformat() + " 10:00:00", None, rnd.choice([0, 5000, 20000])))
    con.executemany("INSERT INTO FCFO VALUES (" + ",".join("?" * 15) + ")", clientes)
    cods_cli = [c[1] for c in clientes if c[4] in ("A", "C")]
    cods_forn = [c[1] for c in clientes if c[4] in ("A", "F")]

    # produtos
    produtos = []
    seq = 400
    for g, nomes in PRODUTOS.items():
        for n in nomes:
            seq += 1
            und = "M" if "CABO" in n else "PC" if g in ("02", "03", "04", "05") else "UN"
            custo = round(rnd.uniform(2, 400), 2)
            st = rnd.choices(["FF", "000", "II", None], [65, 30, 3, 2])[0]
            cest = None if (st == "FF" and rnd.random() < .12) else f"{rnd.randint(100000, 2800000):07d}"
            preco = 0.0 if rnd.random() < .08 else round(custo * rnd.uniform(1.2, 1.8), 2)
            produtos.append([E, f"{seq:06d}", str(rnd.randint(1000, 240000)), n, und, g, preco, custo, 0.0, f"{rnd.randint(27000000, 96999999)}", cest, st, st, "", "F"])
    con.executemany("INSERT INTO TPRODUTO VALUES (" + ",".join("?" * 15) + ")", produtos)
    con.execute("ALTER TABLE TPRODUTO ADD COLUMN ORIGEMMERCADORIA INTEGER")
    con.executemany("UPDATE TPRODUTO SET ORIGEMMERCADORIA = ? WHERE CODPRD = ?",
                    [(rnd.choices([0, 1, 2, 5], [80, 6, 10, 4])[0], p[1]) for p in produtos])
    saldos = []
    for p in produtos:
        for loc, _ in rnd.sample(LOCAIS, rnd.randint(1, 3)):
            s = round(rnd.choice([rnd.uniform(1, 300), rnd.uniform(1, 40)]), 0)
            if rnd.random() < .04:
                s = -rnd.randint(1, 5)
            saldos.append((E, p[1], loc, s, p[7]))
            p[8] += s
    con.executemany("INSERT INTO TPRODSALDO VALUES (?,?,?,?,?)", saldos)
    con.executemany("UPDATE TPRODUTO SET SALDOGERALFISICO=? WHERE CODPRD=?", [(p[8], p[1]) for p in produtos])
    con.execute("ALTER TABLE TPRODSALDO ADD COLUMN CODFILIAL INTEGER")
    con.execute("UPDATE TPRODSALDO SET CODFILIAL = CASE WHEN CODLOC = ? THEN 2 ELSE 1 END", (LOCAIS[-1][0],))

    # movimentos (2 anos)
    movs, itens = [], []
    idmov = 20000
    numeros = {}
    for d in range(730, -1, -1):
        dia = hoje - dt.timedelta(days=d)
        if dia.weekday() >= 5:
            continue
        for _ in range(rnd.randint(1, 6)):
            idmov += 1
            tmv = rnd.choices([t[0] for t in TIPOS], [5, 6, 18, 12, 14, 6, 10, 6, 15, 8])[0]
            numeros[tmv] = numeros.get(tmv, 0) + 1
            cli = rnd.choice(cods_forn if tmv.startswith("1") else cods_cli)
            ven = rnd.choice(VEND)[0]
            status = rnd.choices(["N", "F", "Q", "C"], [60, 20, 15, 5])[0]
            n_it = rnd.randint(1, 6)
            total = 0.0
            for s in range(1, n_it + 1):
                p = rnd.choice(produtos)
                q = float(rnd.randint(1, 60))
                pu = 0.0 if tmv.startswith("2") and rnd.random() < .4 else p[7]
                vt = round(q * pu, 2)
                total += vt
                itens.append((E, idmov, s, p[1], p[4], q, pu, vt, EFEITO.get(tmv, "NNNNNNNNNN")))
            movs.append((E, idmov, f"{numeros[tmv]:09d}", tmv, dia.isoformat(), status, cli, ven, None, rnd.choice([1, 1, 1, 2]), round(total, 2), round(total * rnd.choice([1, 1, 1.03, 1.05]), 2)))
    con.executemany("INSERT INTO TMOV VALUES (" + ",".join("?" * 12) + ")", movs)
    con.executemany("INSERT INTO TMOVITENS VALUES (?,?,?,?,?,?,?,?,?)", itens)

    # máquinas e veículos
    con.executemany("INSERT INTO AMAQUINASGRUPO VALUES (?,?,?)",
                    [(E, "1", "VEICULOS LEVES"), (E, "2", "EQUIPAMENTOS"), (E, "3", "CAMINHOES"), (E, "4", "MOTOS")])
    modelos = {"1": ["FIAT/STRADA HD WK CD", "VW/SAVEIRO CS", "TOYOTA/HILUX CD SRV", "RENAULT/OROCH"],
               "2": ["GERADOR BRANCO 8KVA", "MUNCK MADAL 13T", "CESTO AÉREO 13M", "ROMPEDOR MAKITA"],
               "3": ["VW/17.230 WORKER 4X2", "IVECO/TECTOR 170E21", "M BENZ/ACCELO 1016 CE", "FORD/CARGO 816 S"],
               "4": ["HONDA/CG 160 FAN", "YAMAHA/FACTOR 150"]}
    maq = []
    for i in range(1, 29):
        g = rnd.choices(["1", "2", "3", "4"], [10, 5, 9, 3])[0]
        nome = rnd.choice(modelos[g])
        ano = rnd.randint(2008, 2024)
        letras = "".join(rnd.choice("ABCDEFGHJKLMNOPQRSTUVWXYZ") for _ in range(3))
        placa = None if g == "2" else f"{letras}-{rnd.randint(1, 9)}{rnd.choice('ABCDEFGHIJ')}{rnd.randint(10, 99)}"
        cod = (placa or f"EQ{i:03d}").replace("-", "")
        maq.append((cod, E, ("CAMINHÃO " if g == "3" else "") + nome, f"S{rnd.randint(10000, 99999)}" if g == "2" else None,
                    str(ano), str(ano + rnd.choice([0, 1])), "9" + "".join(rnd.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(16)),
                    f"M{rnd.randint(1000000, 9999999)}", rnd.choice([None, None, "REVISÃO A CADA 10.000 KM", "USO EXCLUSIVO DA EQUIPE DE MANUTENÇÃO"]),
                    "H" if g == "2" else rnd.choice(["O", "O", "K"]), nome.split("/")[0].split(" ")[0], float(rnd.randint(0, 900000)),
                    "M", "T" if rnd.random() < .1 else "F", "C" if g != "2" else None, rnd.choice([1, 1, 2]), g, placa))
    con.executemany("INSERT INTO AMAQUINAS VALUES (" + ",".join("?" * 18) + ")", maq)

    # financeiro
    lans = []
    idlan = 1
    for d in range(540, -120, -3):
        emissao = hoje - dt.timedelta(days=d)
        for pagrec in ("R", "P", "P"):
            parcelas = rnd.randint(1, 3)
            valor_total = round(rnd.uniform(300, 45000), 2)
            cfo = rnd.choice(cods_cli if pagrec == "R" else cods_forn)
            doc = str(rnd.randint(1000, 99999))
            for parc in range(1, parcelas + 1):
                venc = emissao + dt.timedelta(days=30 * parc)
                v = round(valor_total / parcelas, 2)
                if venc < hoje - dt.timedelta(days=15) and rnd.random() < .88:
                    st, baixa, vb = "B", (venc + dt.timedelta(days=rnd.randint(-3, 10))).isoformat(), v
                elif rnd.random() < .03:
                    st, baixa, vb = "C", None, 0.0
                else:
                    st, baixa, vb = "A", None, 0.0
                lans.append((E, idlan, pagrec, st, doc, parc, cfo, rnd.choice(["NF", "BOL", "DUP", "PIX"]), emissao.isoformat(),
                             venc.isoformat(), baixa, v, vb, f"REF. DOC {doc} PARC {parc}/{parcelas}"))
                idlan += 1
    con.executemany("INSERT INTO FLAN VALUES (" + ",".join("?" * 14) + ")", lans)
    con.execute("ALTER TABLE FLAN ADD COLUMN CODFILIAL INTEGER")
    con.execute("UPDATE FLAN SET CODFILIAL = CASE WHEN IDLAN % 4 = 0 THEN 2 ELSE 1 END")
    # centros de custo e departamentos (com alguns títulos rateados entre dois centros)
    ccs = [("1", "RECEITAS"), ("1.01", "RECEITAS OPERACIONAIS"), ("1.01.001", "VENDAS DE SERVIÇOS"), ("1.01.002", "VENDA DE MATERIAIS ELÉTRICOS"),
           ("2", "DESPESAS OPERACIONAIS"), ("2.01", "CUSTO DE MERCADORIAS VENDIDAS"), ("2.01.001", "CUSTO DE MERCADORIAS VENDIDAS"),
           ("2.02", "DESPESAS COM VEÍCULOS"), ("2.02.001", "MANUTENÇÃO E REPARO"), ("2.02.002", "COMBUSTÍVEIS E LUBRIFICANTES"),
           ("2.03", "DESPESAS ADMINISTRATIVAS"), ("2.03.001", "ALUGUEL"), ("2.03.002", "ENERGIA E TELEFONE"), ("2.04", "PESSOAL"),
           ("2.04.001", "SALÁRIOS"), ("2.04.002", "ENCARGOS")]
    con.executemany("INSERT INTO FCCUSTO VALUES (?,?,?)", [(E, c, n) for c, n in ccs])
    deps = [("001", "ADMINISTRATIVO"), ("002", "OBRAS PARTICULARES"), ("003", "PATOS DE MINAS"), ("004", "TURMA MANUTENÇÃO")]
    con.executemany("INSERT INTO GDEPARTAMENTO VALUES (?,?,?,?)", [(E, 1, c, n) for c, n in deps])
    con.execute("ALTER TABLE FLAN ADD COLUMN CCUSTO TEXT")
    con.execute("ALTER TABLE FLAN ADD COLUMN CODDEPARTAMENTO TEXT")
    rec = [c for c, _ in ccs if c.startswith("1.01.")]
    desp = [c for c, _ in ccs if c.startswith("2.") and c.count(".") == 2]
    upd, rat = [], []
    for idl, pr, v in con.execute("SELECT IDLAN, PAGREC, VALORORIGINAL FROM FLAN").fetchall():
        cc = rnd.choice(rec if pr == "R" else desp) if rnd.random() < .95 else None
        dp = rnd.choices([d[0] for d in deps], [50, 35, 10, 5])[0] if rnd.random() < .85 else None
        upd.append((cc, dp, idl))
        if cc:
            if pr == "P" and rnd.random() < .08:          # rateado entre dois centros
                outro = rnd.choice([c for c in desp if c != cc])
                rat += [(E, idl, cc, "L", round(v * .6, 2), dp, 1), (E, idl, outro, "L", round(v * .4, 2), dp, 1)]
            else:
                rat.append((E, idl, cc, "L", v, dp, 1))
    con.executemany("UPDATE FLAN SET CCUSTO = ?, CODDEPARTAMENTO = ? WHERE IDLAN = ?", upd)
    con.execute("ALTER TABLE TMOV ADD COLUMN CODCCUSTO TEXT")
    con.execute("ALTER TABLE TMOV ADD COLUMN CODDEPARTAMENTO TEXT")
    upd_m = []
    for idm, tmv in con.execute("SELECT IDMOV, CODTMV FROM TMOV").fetchall():
        cc = rnd.choice(desp if tmv.startswith("1") else rec + desp) if rnd.random() < .7 else None
        dp = rnd.choices([d[0] for d in deps], [50, 35, 10, 5])[0] if rnd.random() < .65 else None
        upd_m.append((cc, dp, idm))
    con.executemany("UPDATE TMOV SET CODCCUSTO = ?, CODDEPARTAMENTO = ? WHERE IDMOV = ?", upd_m)
    con.executemany("INSERT INTO FLANRATCCUSTO VALUES (?,?,?,?,?,?,?)", rat)
    # frotas: abastecimentos (1.2.40) e manutenções (1.2.39) ligados às máquinas
    con.executemany("INSERT INTO TTIPOMOV VALUES (?,?,?)", [(E, "1.2.39", "RATEIO MANUTENÇÃO DE VEÍCULOS E MÁQUINAS"),
                                                           (E, "1.2.40", "RATEIO COMBUSTÍVEL/LUBRIFICANTE")])
    con.execute("ALTER TABLE TMOV ADD COLUMN CODMAQUINA TEXT")
    con.execute("ALTER TABLE TMOV ADD COLUMN KM REAL")
    comb = [("900001", "DIESEL S10", "LT", 6.15), ("900002", "GASOLINA", "L", 6.39), ("900003", "ARLA 32", "L", 3.90)]
    pecas = [("900010", "FILTRO DE OLEO", "UN", 58.0), ("900011", "OLEO MOTOR 15W40", "L", 32.0), ("900012", "PNEU 275/80 R22.5", "UN", 2350.0),
             ("900013", "PASTILHA DE FREIO", "JG", 189.0), ("900014", "MAO DE OBRA MECANICA", "H", 120.0), ("900015", "BATERIA 150AH", "UN", 980.0)]
    con.execute("INSERT INTO TGRUPO VALUES (?,?,?)", (E, "99", "FROTA - COMBUSTÍVEIS E PEÇAS"))
    con.executemany("INSERT INTO TPRODUTO (CODEMPRESA, CODPRD, NOMEFANTASIA, CODUNDVENDA, CODGRUPO, PRECO1, CUSTOMEDIO, SALDOGERALFISICO, INATIVO)"
                    " VALUES (?,?,?,?,?,?,?,0,'F')", [(E, c, n, u, "99", v, v) for c, n, u, v in comb + pecas])
    fm, fi = [], []
    n_ab = n_mt = 0
    postos = cods_forn[:4]
    for m in maq:
        cod, grupo = m[0], m[16]
        km = float(rnd.randint(20000, 300000))
        diesel = grupo in ("2", "3") or "HILUX" in m[2]
        consumo = {"1": 9.5, "2": 2.0, "3": 3.2, "4": 32.0}[grupo]
        tanque = {"1": 45, "2": 60, "3": 180, "4": 12}[grupo]
        d = 400
        while d > 0:
            d -= rnd.randint(4, 12) if grupo != "4" else rnd.randint(8, 20)
            dia = hoje - dt.timedelta(days=max(d, 0))
            idmov += 1
            n_ab += 1
            lit = round(tanque * rnd.uniform(.5, .95), 2)
            km += round(lit * consumo * rnd.uniform(.85, 1.15))
            prd, nome, und, pu = comb[0] if diesel else comb[1]
            pu = round(pu * rnd.uniform(.95, 1.05), 3)
            tot = round(lit * pu, 2)
            fi.append((E, idmov, 1, prd, und, lit, pu, tot, "NNNNNNNNNN"))
            if diesel and grupo == "3" and rnd.random() < .3:
                q = float(rnd.randint(10, 20))
                fi.append((E, idmov, 2, comb[2][0], "L", q, comb[2][3], round(q * comb[2][3], 2), "NNNNNNNNNN"))
                tot += round(q * comb[2][3], 2)
            fm.append((E, idmov, f"{n_ab:09d}", "1.2.40", dia.isoformat(), "N", rnd.choice(postos), None, None, m[15], round(tot, 2), round(tot, 2),
                       "2.02.002", "004", cod, km))
        for _ in range(rnd.randint(0, 4)):
            dia = hoje - dt.timedelta(days=rnd.randint(1, 390))
            idmov += 1
            n_mt += 1
            tot = 0.0
            for s, (prd, nome, und, pu) in enumerate(rnd.sample(pecas, rnd.randint(1, 3)), 1):
                q = float(rnd.randint(1, 6))
                tot += round(q * pu, 2)
                fi.append((E, idmov, s, prd, und, q, pu, round(q * pu, 2), "NNNNNNNNNN"))
            fm.append((E, idmov, f"{n_mt:09d}", "1.2.39", dia.isoformat(), "C" if rnd.random() < .05 else "N", rnd.choice(cods_forn), None, None,
                       m[15], round(tot, 2), round(tot, 2), "2.02.001", "004", cod, None))
    con.executemany("INSERT INTO TMOV (CODEMPRESA, IDMOV, NUMEROMOV, CODTMV, DATAEMISSAO, STATUS, CODCFO, CODVEN1, CODVEN2, CODFILIAL,"
                    " VALORLIQUIDO, VALORBRUTO, CODCCUSTO, CODDEPARTAMENTO, CODMAQUINA, KM) VALUES (" + ",".join("?" * 16) + ")", fm)
    con.executemany("INSERT INTO TMOVITENS VALUES (?,?,?,?,?,?,?,?,?)", fi)
    con.commit()
    con.close()


if __name__ == "__main__":
    from config import BASE_DIR

    destino = os.path.join(BASE_DIR, "dados", "demo.sqlite")
    criar(destino)
    print("Banco de demonstração criado em", destino)
