"""Vários bancos (uma empresa/Puma por banco): qual está em uso e onde ficam os arquivos de cada um."""
import os

from config import BASE_DIR, DADOS_DIR

PRINCIPAL = "principal"
DADOS = DADOS_DIR


def pasta(bid):
    """Pasta dos arquivos próprios do banco (catálogo do ReportBuilder, testes...).
    O principal usa dados\\ (como sempre foi); os outros, dados\\bancos\\<id>."""
    if not bid or bid == PRINCIPAL:
        return DADOS
    p = os.path.join(DADOS, "bancos", bid)
    os.makedirs(p, exist_ok=True)
    return p


def _padrao():
    return PRINCIPAL


# o app.py troca por uma função que devolve o banco escolhido pelo usuário na sessão
atual = _padrao
