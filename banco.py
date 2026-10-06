"""Acesso ao Supabase. Toda leitura e gravação do app passa por aqui.

As páginas chamam banco.listar / banco.inserir / ... (e não importam as
funções soltas), para que tudo que toca o banco fique num lugar só.

A conexão usa o ConectionSupaBase do repositório Modulos, como os outros
apps da equipe.
"""

import os
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
import streamlit as st

TREINAMENTO = "segtrabalho_treinamento"
PLANO_ACAO = "segtrabalho_plano_acao"
ACIDENTE = "segtrabalho_acidente"
USUARIO = "segtrabalho_usuario"
CAT = "segtrabalho_cat"  # acidentes internos (Comunicação de Acidente de Trabalho)
SESSAO = "segtrabalho_treinamento_sessao"  # lista de presença aberta por QR Code

# O PostgREST devolve no máximo 1000 linhas por requisição; acima disso a
# lista vinha cortada sem aviso. listar() pagina até acabar.
TAMANHO_PAGINA = 1000


def secret(*nomes):
    """Primeiro secret existente entre os nomes aceitos."""
    for nome in nomes:
        try:
            if nome in st.secrets:
                return st.secrets[nome]
        except Exception:  # sem secrets.toml
            pass
    return None


def credenciais():
    """(url, key) — mesmos nomes aceitos pelo Painel de Sustentabilidade."""
    url = secret("SUPABASE_URL", "supabase_url") or os.getenv("SUPABASE_URL")
    key = secret(
        "SUPABASE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY", "supabase_key",
    ) or os.getenv("SUPABASE_KEY")
    return url, key


# ------------------------------------------------
# REPOSITÓRIO MODULOS (ConectionSupaBase)
# ------------------------------------------------
# Mesmo bloco do Metas TDV / Sustentabilidade: clona o Modulos na primeira
# execução e o coloca no caminho de importação.
MODULOS_DIR = Path(__file__).parent / "Modulos"
if not MODULOS_DIR.exists():
    # sem emoji: o console do Windows (cp1252) quebra com UnicodeEncodeError
    print("Clonando repositorio Modulos do GitHub...")
    subprocess.run(
        ["git", "clone", "https://github.com/DellaVolpe69/Modulos.git", str(MODULOS_DIR)],
        check=True,
    )
if str(MODULOS_DIR) not in sys.path:
    sys.path.insert(0, str(MODULOS_DIR))

# ConectionSupaBase lê SUPABASE_URL / SUPABASE_KEY de os.getenv() no nível
# do módulo, ou seja, NO MOMENTO DO IMPORT — e st.secrets não popula o
# ambiente. Por isso os secrets são publicados no ambiente ANTES do import.
_url, _key = credenciais()
if _url:
    os.environ["SUPABASE_URL"] = str(_url)
if _key:
    os.environ["SUPABASE_KEY"] = str(_key)

from Modulos import ConectionSupaBase  # noqa: E402


@st.cache_resource(show_spinner=False)
def conectar():
    """Um cliente por processo — conectar a cada rerun é desperdício."""
    return ConectionSupaBase.conexao()


def json_seguro(dados: dict) -> dict:
    """date/NaN/numpy não serializam em JSON; vazio vai como null, nunca 0."""
    saida = {}
    for chave, valor in dados.items():
        if valor is None or (not isinstance(valor, (str, list, dict)) and pd.isna(valor)):
            saida[chave] = None
        elif isinstance(valor, pd.Timestamp):
            saida[chave] = valor.date().isoformat()
        elif isinstance(valor, (datetime, date, time)):
            saida[chave] = valor.isoformat()
        elif hasattr(valor, "item"):  # escalares numpy/pandas
            saida[chave] = valor.item()
        else:
            saida[chave] = valor
    return saida


@st.cache_data(ttl=300, show_spinner=False)
def listar(tabela: str) -> pd.DataFrame:
    """Todas as linhas da tabela, mais recentes primeiro."""
    cliente = conectar()
    linhas, inicio = [], 0
    while True:
        resposta = (
            cliente.table(tabela)
            .select("*")
            .order("id", desc=True)
            .range(inicio, inicio + TAMANHO_PAGINA - 1)
            .execute()
        )
        lote = resposta.data or []
        linhas.extend(lote)
        if len(lote) < TAMANHO_PAGINA:
            break
        inicio += TAMANHO_PAGINA
    return pd.DataFrame(linhas)


def buscar(tabela: str, **filtros) -> list:
    """Linhas com coluna = valor (None = vazio), direto do banco, sem cache.

    Para o que muda a cada segundo — a lista de presença aberta por QR Code —
    e para não ler a tabela inteira só para achar uma linha.
    """
    consulta = conectar().table(tabela).select("*")
    for coluna, valor in filtros.items():
        consulta = consulta.is_(coluna, "null") if valor is None else consulta.eq(coluna, valor)
    return consulta.order("id").execute().data or []


def inserir(tabela: str, linhas: list) -> tuple:
    """Insere todas as linhas num único comando: ou grava tudo, ou nada."""
    try:
        conectar().table(tabela).insert([json_seguro(l) for l in linhas]).execute()
    except Exception as erro:
        return False, f"Não gravou: {erro}"
    listar.clear()
    return True, f"{len(linhas)} registro(s) gravado(s)."


def atualizar(tabela: str, id_registro, dados: dict) -> tuple:
    try:
        resposta = (
            conectar().table(tabela).update(json_seguro(dados)).eq("id", int(id_registro)).execute()
        )
    except Exception as erro:
        return False, f"Não alterou: {erro}"
    listar.clear()
    if not resposta.data:
        return False, f"Nenhuma linha alterada (registro #{id_registro} não encontrado)."
    return True, f"Registro #{id_registro} alterado."


def atualizar_onde(tabela: str, coluna: str, valor, dados: dict) -> tuple:
    """Altera todas as linhas com coluna = valor (ex.: a evidência de uma lista inteira)."""
    try:
        resposta = conectar().table(tabela).update(json_seguro(dados)).eq(coluna, valor).execute()
    except Exception as erro:
        return False, f"Não alterou: {erro}"
    listar.clear()
    return True, f"{len(resposta.data or [])} registro(s) alterado(s)."


def excluir_onde(tabela: str, coluna: str, valor) -> tuple:
    """Apaga todas as linhas com coluna = valor (ex.: os participantes de uma lista cancelada)."""
    try:
        resposta = conectar().table(tabela).delete().eq(coluna, valor).execute()
    except Exception as erro:
        return False, f"Não excluiu: {erro}"
    listar.clear()
    return True, f"{len(resposta.data or [])} registro(s) excluído(s)."


def excluir(tabela: str, id_registro) -> tuple:
    try:
        resposta = conectar().table(tabela).delete().eq("id", int(id_registro)).execute()
    except Exception as erro:
        return False, f"Não excluiu: {erro}"
    listar.clear()
    if not resposta.data:
        return False, f"Nada excluído (registro #{id_registro} não encontrado)."
    return True, f"Registro #{id_registro} excluído."
