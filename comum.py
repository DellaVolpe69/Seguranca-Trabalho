"""Utilitários de tela compartilhados pelas páginas."""

import re
from datetime import date, datetime

import pandas as pd
import streamlit as st

OUTRO = "OUTRO — digitar"
VAZIO = "—"
# Sim/Não com terceira opção: "não informado" fica NULL, não vira "Não".
SIM_NAO = {VAZIO: None, "Sim": True, "Não": False}


# ---------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------

def vazio(valor) -> bool:
    if valor is None:
        return True
    if isinstance(valor, str):
        return not valor.strip()
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def texto(valor):
    """Texto limpo, ou None se vazio."""
    if vazio(valor):
        return None
    return re.sub(r"\s+", " ", str(valor)).strip()


def para_data(valor):
    if vazio(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return pd.to_datetime(valor).date()


def para_numero(valor):
    return None if vazio(valor) else float(valor)


def rotulo_sim_nao(valor) -> str:
    if vazio(valor):
        return VAZIO
    return "Sim" if bool(valor) else "Não"


def fmt_data(valor) -> str:
    d = para_data(valor)
    return d.strftime("%d/%m/%Y") if d else ""


# ---------------------------------------------------------------------
# CPF
# ---------------------------------------------------------------------

def so_digitos(valor) -> str:
    return re.sub(r"\D", "", "" if vazio(valor) else str(valor))


def cpf_valido(cpf: str) -> bool:
    if not re.fullmatch(r"\d{11}", cpf or "") or cpf == cpf[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = soma * 10 % 11 % 10
        if digito != int(cpf[tamanho]):
            return False
    return True


def fmt_cpf(cpf) -> str:
    d = so_digitos(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else d


# ---------------------------------------------------------------------
# Mensagens que sobrevivem ao st.rerun()
# ---------------------------------------------------------------------

def guardar_msg(chave: str, tipo: str, texto_msg: str) -> None:
    st.session_state[chave] = (tipo, texto_msg)


def render_msg(chave: str) -> None:
    tipo, texto_msg = st.session_state.pop(chave, (None, None))
    if tipo == "success":
        st.success(texto_msg)
    elif tipo == "warning":
        st.warning(texto_msg)
    elif tipo == "error":
        st.error(texto_msg)


def mostrar_erros(erros: list) -> None:
    st.error("Corrija antes de salvar:\n\n" + "\n".join(f"- {e}" for e in erros))


# ---------------------------------------------------------------------
# Campos
# ---------------------------------------------------------------------

def opcoes_existentes(df: pd.DataFrame, coluna: str) -> list:
    """Valores já usados na coluna — viram as opções do selectbox."""
    if df.empty or coluna not in df:
        return []
    valores = {texto(v) for v in df[coluna]}
    return sorted(v for v in valores if v)


def campo_com_outro(rotulo: str, opcoes: list, key: str, valor_atual=None, ajuda=None):
    """Selectbox com os valores já usados + "OUTRO — digitar".

    Evita que "Filial SP", "filial sp" e "SP" virem três filiais no Power BI.
    """
    valor_atual = texto(valor_atual)
    lista = [VAZIO] + list(opcoes) + [OUTRO]
    if valor_atual is None:
        indice = 0
    elif valor_atual in opcoes:
        indice = lista.index(valor_atual)
    else:
        indice = len(lista) - 1

    escolha = st.selectbox(rotulo, lista, index=indice, key=key, help=ajuda)
    if escolha == OUTRO:
        inicial = valor_atual if valor_atual not in opcoes else ""
        return texto(st.text_input(f"{rotulo} (novo)", value=inicial or "", key=f"{key}_txt"))
    return None if escolha == VAZIO else escolha


def campo_sim_nao(rotulo: str, key: str, valor_atual=None):
    lista = list(SIM_NAO)
    escolha = st.selectbox(rotulo, lista, index=lista.index(rotulo_sim_nao(valor_atual)), key=key)
    return SIM_NAO[escolha]


def campo_lista(rotulo: str, opcoes: list, key: str, valor_atual=None):
    """Selectbox de lista fixa com opção vazia."""
    lista = [VAZIO] + list(opcoes)
    valor_atual = texto(valor_atual)
    indice = lista.index(valor_atual) if valor_atual in opcoes else 0
    escolha = st.selectbox(rotulo, lista, index=indice, key=key)
    return None if escolha == VAZIO else escolha


def csv_excel(df: pd.DataFrame) -> bytes:
    """CSV que o Excel em pt-BR abre certo (ponto e vírgula + BOM)."""
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
