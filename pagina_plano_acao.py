"""Plano de Ação → segtrabalho_plano_acao.

Consolida "ações concluídas no prazo" e "ações críticas vencidas" numa base
só (pedido do MD): a situação não é digitada, é calculada a partir de
status, prazo_final e data_conclusao.
"""

from datetime import date

import pandas as pd
import streamlit as st

import banco
from comum import (
    VAZIO, campo_com_outro, campo_lista, campo_sim_nao, csv_excel, fmt_data,
    guardar_msg, mostrar_erros, opcoes_existentes, para_data, render_msg, texto,
)
from estilo import (
    barra_paginas_lateral, bloco_usuario_lateral, cabecalho_tela, linha_cartoes, titulo_secao,
)

PAGINAS = {
    "nova": "Nova ação",
    "acompanhamento": "Acompanhamento",
}
STATUS = ["Em andamento", "Finalizado"]
CRITICIDADES = ["Baixa", "Média", "Alta", "Crítica"]
SEM_ACIDENTE = "Sem acidente vinculado"
COLUNAS = [
    "id", "acidente_id", "filial", "area", "plano_acao", "criticidade",
    "responsavel", "data_abertura", "prazo_final", "data_conclusao", "status",
    "eficaz", "houve_reincidencia", "link_evidencia", "criado_em", "criado_por",
]
MSG_NOVA = "pa_msg_nova"
MSG_REG = "pa_msg_reg"


def tela(usuario: dict) -> None:
    cabecalho_tela(
        "✅ PLANO DE AÇÃO",
        "Ações de acidentes, inspeções e PGR: prazo, conclusão e eficácia.",
        "plano_acao",
    )
    pagina = barra_paginas_lateral("pa_pagina", PAGINAS, "pa")
    bloco_usuario_lateral(usuario)
    df = carregar()
    acidentes = carregar_acidentes()
    if pagina == "nova":
        nova_acao(df, acidentes, usuario)
    else:
        acompanhamento(df, acidentes)


def carregar() -> pd.DataFrame:
    try:
        df = banco.listar(banco.PLANO_ACAO)
    except Exception as erro:
        st.error(f"Não foi possível ler {banco.PLANO_ACAO}: {erro}")
        df = pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=COLUNAS)
    for coluna in ("data_abertura", "prazo_final", "data_conclusao"):
        df[coluna] = df[coluna].map(para_data)
    return df


def carregar_acidentes() -> dict:
    """{id: rótulo} para vincular a ação a um acidente. Vazio se a tabela não responder."""
    try:
        df = banco.listar(banco.ACIDENTE)
    except Exception:
        return {}
    if df.empty:
        return {}
    rotulos = {}
    for _, a in df.iterrows():
        descricao = (texto(a.get("descricao")) or "")[:50]
        rotulos[int(a["id"])] = (
            f"#{int(a['id'])} · {fmt_data(a.get('data_evento'))} · "
            f"{texto(a.get('filial_origem')) or ''} · {descricao}"
        )
    return rotulos


# ---------------------------------------------------------------------
# Situação de prazo (calculada, nunca digitada)
# ---------------------------------------------------------------------

def situacao(acao: pd.Series, hoje: date) -> str:
    prazo, conclusao = acao["prazo_final"], acao["data_conclusao"]
    if acao["status"] == "Finalizado":
        if prazo is None or conclusao is None:
            return "Concluída (sem data)"
        return "Concluída no prazo" if conclusao <= prazo else "Concluída com atraso"
    if prazo is not None and prazo < hoje:
        return "Vencida"
    return "No prazo"


def dias_atraso(acao: pd.Series, hoje: date):
    prazo, conclusao = acao["prazo_final"], acao["data_conclusao"]
    if prazo is None:
        return None
    fim = conclusao if acao["status"] == "Finalizado" else hoje
    if fim is None:
        return None
    return max((fim - prazo).days, 0)


def enriquecer(df: pd.DataFrame) -> pd.DataFrame:
    hoje = date.today()
    df = df.copy()
    df["situacao"] = df.apply(lambda a: situacao(a, hoje), axis=1)
    df["dias_atraso"] = pd.to_numeric(df.apply(lambda a: dias_atraso(a, hoje), axis=1), errors="coerce")
    df["critica_vencida"] = (df["criticidade"] == "Crítica") & (df["situacao"] == "Vencida")
    df["dias_para_concluir"] = pd.to_numeric(
        df.apply(
            lambda a: (a["data_conclusao"] - a["data_abertura"]).days
            if a["data_conclusao"] is not None and a["data_abertura"] is not None else None,
            axis=1,
        ),
        errors="coerce",
    )
    return df


# ---------------------------------------------------------------------
# Campos (os mesmos na criação e na edição)
# ---------------------------------------------------------------------

def campos_acao(df: pd.DataFrame, acidentes: dict, k: str, atual: dict) -> dict:
    """Desenha o formulário e devolve os valores digitados."""
    opcoes_acidente = [SEM_ACIDENTE] + list(acidentes)
    atual_acidente = atual.get("acidente_id")
    indice = opcoes_acidente.index(int(atual_acidente)) if (
        atual_acidente is not None and not pd.isna(atual_acidente)
        and int(atual_acidente) in acidentes
    ) else 0
    acidente = st.selectbox(
        "ACIDENTE VINCULADO", opcoes_acidente, index=indice, key=f"{k}_acidente",
        format_func=lambda o: o if o == SEM_ACIDENTE else acidentes[o],
        help="Deixe sem vínculo para ações de inspeção, PGR ou auditoria.",
    )

    c1, c2, c3 = st.columns([1.4, 1.4, 1])
    with c1:
        filial = campo_com_outro("FILIAL", opcoes_existentes(df, "filial"), f"{k}_filial", atual.get("filial"))
    with c2:
        area = campo_com_outro("ÁREA", opcoes_existentes(df, "area"), f"{k}_area", atual.get("area"))
    with c3:
        criticidade = campo_lista("CRITICIDADE", CRITICIDADES, f"{k}_crit", atual.get("criticidade"))

    plano = st.text_area(
        "PLANO DE AÇÃO", value=texto(atual.get("plano_acao")) or "", key=f"{k}_plano", height=90
    )

    c4, c5, c6 = st.columns([1.6, 1, 1])
    with c4:
        responsavel = campo_com_outro(
            "RESPONSÁVEL", opcoes_existentes(df, "responsavel"), f"{k}_resp", atual.get("responsavel")
        )
    with c5:
        abertura = st.date_input(
            "DATA DE ABERTURA", value=atual.get("data_abertura") or date.today(),
            format="DD/MM/YYYY", key=f"{k}_abertura",
        )
    with c6:
        prazo = st.date_input(
            "PRAZO FINAL", value=atual.get("prazo_final"), format="DD/MM/YYYY", key=f"{k}_prazo"
        )

    c7, c8, c9, c10 = st.columns(4)
    with c7:
        status_atual = atual.get("status") if atual.get("status") in STATUS else STATUS[0]
        status = st.selectbox("STATUS", STATUS, index=STATUS.index(status_atual), key=f"{k}_status")
    conclusao, eficaz, reincidencia = None, None, None
    if status == "Finalizado":
        with c8:
            conclusao = st.date_input(
                "DATA DE CONCLUSÃO", value=atual.get("data_conclusao") or date.today(),
                format="DD/MM/YYYY", key=f"{k}_conclusao",
            )
        with c9:
            eficaz = campo_sim_nao("AÇÃO EFICAZ?", f"{k}_eficaz", atual.get("eficaz"))
        with c10:
            reincidencia = campo_sim_nao(
                "HOUVE REINCIDÊNCIA?", f"{k}_reinc", atual.get("houve_reincidencia")
            )

    link = st.text_input(
        "LINK DA EVIDÊNCIA", value=texto(atual.get("link_evidencia")) or "", key=f"{k}_link",
        placeholder="https://dellavolpe.sharepoint.com/...",
    )

    return {
        "acidente_id": None if acidente == SEM_ACIDENTE else int(acidente),
        "filial": filial,
        "area": area,
        "plano_acao": texto(plano),
        "criticidade": criticidade,
        "responsavel": responsavel,
        "data_abertura": abertura,
        "prazo_final": prazo,
        "data_conclusao": conclusao,
        "status": status,
        "eficaz": eficaz,
        "houve_reincidencia": reincidencia,
        "link_evidencia": texto(link),
    }


def validar(d: dict) -> list:
    erros = []
    if not d["filial"]:
        erros.append("Informe a filial.")
    if not d["plano_acao"]:
        erros.append("Descreva o plano de ação.")
    if not d["criticidade"]:
        erros.append("Informe a criticidade.")
    if not d["responsavel"]:
        erros.append("Informe o responsável.")
    if not d["data_abertura"]:
        erros.append("Informe a data de abertura.")
    if not d["prazo_final"]:
        erros.append("Informe o prazo final.")
    elif d["data_abertura"] and d["prazo_final"] < d["data_abertura"]:
        erros.append("O prazo final não pode ser anterior à abertura.")
    if d["status"] == "Finalizado":
        if not d["data_conclusao"]:
            erros.append("Ação finalizada precisa da data de conclusão.")
        elif d["data_abertura"] and d["data_conclusao"] < d["data_abertura"]:
            erros.append("A conclusão não pode ser anterior à abertura.")
        elif d["data_conclusao"] > date.today():
            erros.append("A data de conclusão não pode estar no futuro.")
    return erros


# ---------------------------------------------------------------------
# Nova ação
# ---------------------------------------------------------------------

def nova_acao(df: pd.DataFrame, acidentes: dict, usuario: dict) -> None:
    v = st.session_state.setdefault("pa_versao", 0)
    render_msg(MSG_NOVA)
    dados = campos_acao(df, acidentes, f"pa_nova_{v}", {})

    if st.button("💾 Salvar ação", type="primary", key=f"pa_salvar_{v}"):
        erros = validar(dados)
        if erros:
            mostrar_erros(erros)
            return
        dados["criado_por"] = usuario["email"]
        ok, msg = banco.inserir(banco.PLANO_ACAO, [dados])
        if not ok:
            st.error(msg)
            return
        guardar_msg(MSG_NOVA, "success", "Ação cadastrada.")
        st.session_state["pa_versao"] += 1
        st.rerun()


# ---------------------------------------------------------------------
# Acompanhamento: indicadores, consulta, edição e exclusão
# ---------------------------------------------------------------------

def acompanhamento(df: pd.DataFrame, acidentes: dict) -> None:
    render_msg(MSG_REG)
    if df.empty:
        st.info("Nenhuma ação cadastrada ainda.")
        return
    df = enriquecer(df)

    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        filiais = st.multiselect("FILIAL", opcoes_existentes(df, "filial"), key="pa_f_filial")
    with f2:
        areas = st.multiselect("ÁREA", opcoes_existentes(df, "area"), key="pa_f_area")
    with f3:
        responsaveis = st.multiselect("RESPONSÁVEL", opcoes_existentes(df, "responsavel"), key="pa_f_resp")
    with f4:
        situacoes = st.multiselect("SITUAÇÃO", opcoes_existentes(df, "situacao"), key="pa_f_sit")
    with f5:
        criticidades = st.multiselect("CRITICIDADE", CRITICIDADES, key="pa_f_crit")

    f = df
    if filiais:
        f = f[f["filial"].isin(filiais)]
    if areas:
        f = f[f["area"].isin(areas)]
    if responsaveis:
        f = f[f["responsavel"].isin(responsaveis)]
    if situacoes:
        f = f[f["situacao"].isin(situacoes)]
    if criticidades:
        f = f[f["criticidade"].isin(criticidades)]

    abertas = int((f["status"] == "Em andamento").sum())
    vencidas = int((f["situacao"] == "Vencida").sum())
    criticas_vencidas = int(f["critica_vencida"].sum())
    concluidas = f[f["status"] == "Finalizado"]
    no_prazo = int((concluidas["situacao"] == "Concluída no prazo").sum())
    pct_no_prazo = f"{no_prazo / len(concluidas):.0%}" if len(concluidas) else VAZIO
    tempos = concluidas["dias_para_concluir"].dropna()
    tempo_medio = f"{tempos.mean():.0f} dias" if len(tempos) else VAZIO

    linha_cartoes([
        ("Ações abertas", f"{abertas}", "neutro", f"de {len(f)} no filtro"),
        ("Vencidas", f"{vencidas}", "vermelho" if vencidas else "neutro", "abertas fora do prazo"),
        ("Críticas vencidas", f"{criticas_vencidas}", "vermelho" if criticas_vencidas else "neutro", ""),
        ("Concluídas no prazo", pct_no_prazo, "verde", f"{no_prazo} de {len(concluidas)} concluídas"),
        ("Tempo médio", tempo_medio, "neutro", "abertura → conclusão"),
    ])
    st.write("")

    tabela = f[[
        "id", "situacao", "criticidade", "filial", "area", "plano_acao", "responsavel",
        "data_abertura", "prazo_final", "data_conclusao", "dias_atraso", "status",
        "eficaz", "houve_reincidencia", "acidente_id",
    ]].copy()
    textos = ["criticidade", "filial", "area", "plano_acao", "responsavel"]
    tabela[textos] = tabela[textos].fillna("")  # vazio em vez de "None" na tela

    versao_tabela = st.session_state.setdefault("pa_tabela_v", 0)
    evento = st.dataframe(
        tabela,
        key=f"pa_tabela_{versao_tabela}",
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.NumberColumn("ID", format="%d", width="small"),
            "situacao": "SITUAÇÃO",
            "criticidade": "CRITICIDADE",
            "filial": "FILIAL",
            "area": "ÁREA",
            "plano_acao": st.column_config.TextColumn("PLANO DE AÇÃO", width="large"),
            "responsavel": "RESPONSÁVEL",
            "data_abertura": st.column_config.DateColumn("ABERTURA", format="DD/MM/YYYY"),
            "prazo_final": st.column_config.DateColumn("PRAZO", format="DD/MM/YYYY"),
            "data_conclusao": st.column_config.DateColumn("CONCLUSÃO", format="DD/MM/YYYY"),
            "dias_atraso": st.column_config.NumberColumn("DIAS DE ATRASO", format="%d"),
            "status": "STATUS",
            "eficaz": st.column_config.CheckboxColumn("EFICAZ"),
            "houve_reincidencia": st.column_config.CheckboxColumn("REINCIDÊNCIA"),
            "acidente_id": st.column_config.NumberColumn("ACIDENTE", format="%d"),
        },
    )
    st.download_button(
        "⬇️ Baixar CSV", csv_excel(tabela), file_name="plano_de_acao.csv",
        mime="text/csv", key="pa_csv",
    )

    linhas = evento.selection.rows
    if not linhas:
        st.caption("Selecione uma linha na tabela para editar, concluir ou excluir.")
        return
    st.divider()
    editar(f.iloc[linhas[0]], df, acidentes)


def editar(reg: pd.Series, df: pd.DataFrame, acidentes: dict) -> None:
    rid = int(reg["id"])
    k = f"pa_ed_{rid}_{st.session_state['pa_tabela_v']}"
    titulo_secao(f"Editar ação #{rid}", f"Situação atual: {reg['situacao']}")
    dados = campos_acao(df, acidentes, k, reg.to_dict())

    confirmar = st.checkbox("Quero excluir esta ação", key=f"{k}_confirma")
    b1, b2, _ = st.columns([1.4, 1, 4])
    salvar = b1.button("💾 Salvar alterações", type="primary", key=f"{k}_salvar")
    apagar = b2.button("🗑️ Excluir", key=f"{k}_excluir", disabled=not confirmar)

    if salvar:
        erros = validar(dados)
        if erros:
            mostrar_erros(erros)
            return
        concluir(banco.atualizar(banco.PLANO_ACAO, rid, dados))
    if apagar:
        concluir(banco.excluir(banco.PLANO_ACAO, rid))


def concluir(resultado: tuple) -> None:
    ok, msg = resultado
    if not ok:
        st.error(msg)
        return
    guardar_msg(MSG_REG, "success", msg)
    st.session_state["pa_tabela_v"] += 1  # limpa a seleção da tabela
    st.rerun()
