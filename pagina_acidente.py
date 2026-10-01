"""Acidentes — Relatório de Acidente → segtrabalho_acidente.

Informações do acidente, do acidentado/motorista e do veículo. O plano de
ação saiu desta tela: cada acidente pode ter várias ações, cadastradas em
Plano de Ação e vinculadas pelo acidente_id.
"""

import re
from datetime import date

import pandas as pd
import streamlit as st

import banco
import pagina_plano_acao as plano
from comum import (
    garantir_colunas, campo_com_outro, campo_lista, campo_sim_nao, csv_excel, erro_cpf, fmt_cpf,
    guardar_msg, mostrar_erros, opcoes_existentes, para_data, para_hora, render_msg,
    so_digitos, texto,
)
from estilo import (
    barra_paginas_lateral, bloco_usuario_lateral, cabecalho_tela, linha_cartoes, titulo_secao,
)

PAGINAS = {
    "novo": "Novo relatório de acidente",
    "registros": "Registros",
}
# listas da planilha "Relatorio de Acidente"
TIPOS_PERDA = [
    "Evento com perda pessoal", "Evento com perda ambiental", "Evento com perda material",
    "Evento com comunidade", "Ocorrência operacional", "Evento sem perda",
]
TIPOS_MOTORISTA = ["Frota", "Agregado", "Terceiro"]
COLUNAS = [
    "id", "data_evento", "hora_evento", "localizacao", "tipo_perda", "descricao", "nome",
    "origem", "destino", "filial_origem", "cpf", "produto_perigoso", "data_nascimento",
    "tipo_motorista", "placa", "link_evidencia", "criado_em", "criado_por",
]
MSG_NOVO = "ac_msg_novo"
MSG_REG = "ac_msg_reg"


def tela(usuario: dict) -> None:
    cabecalho_tela(
        "🚛 ACIDENTES",
        "Relatório de Acidente: o que aconteceu, quem se envolveu e qual veículo.",
        "acidente",
    )
    pagina = barra_paginas_lateral("ac_pagina", PAGINAS, "ac")
    bloco_usuario_lateral(usuario)
    df = carregar()
    if pagina == "novo":
        novo(df, usuario)
    else:
        registros(df)


def carregar() -> pd.DataFrame:
    try:
        df = banco.listar(banco.ACIDENTE)
    except Exception as erro:
        st.error(f"Não foi possível ler {banco.ACIDENTE}: {erro}")
        df = pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=COLUNAS)
    df = garantir_colunas(df, COLUNAS)
    for coluna in ("data_evento", "data_nascimento"):
        df[coluna] = df[coluna].map(para_data)
    df["hora_evento"] = df["hora_evento"].map(para_hora)
    return df


def placa_limpa(valor) -> str:
    """'abc-1d23' -> 'ABC1D23'."""
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


# ---------------------------------------------------------------------
# Campos (os mesmos no cadastro e na edição)
# ---------------------------------------------------------------------

def campos_acidente(df: pd.DataFrame, k: str, atual: dict) -> dict:
    titulo_secao("1. Informações do acidente")
    c1, c2, c3 = st.columns([1, 0.8, 1.6])
    with c1:
        data_evento = st.date_input(
            "DATA DO EVENTO", value=atual.get("data_evento") or date.today(),
            max_value=date.today(), format="DD/MM/YYYY", key=f"{k}_data",
        )
    with c2:
        hora = st.time_input("HORA", value=atual.get("hora_evento"), step=300, key=f"{k}_hora")
    with c3:
        filial = campo_com_outro(
            "FILIAL DE ORIGEM", opcoes_existentes(df, "filial_origem"), f"{k}_filial",
            atual.get("filial_origem"),
        )

    c4, c5, c6 = st.columns([1.6, 1.4, 1])
    with c4:
        localizacao = st.text_input(
            "LOCALIZAÇÃO", value=texto(atual.get("localizacao")) or "", key=f"{k}_local",
            placeholder="Rodovia, km, cidade ou endereço",
        )
    with c5:
        tipo_perda = campo_lista(
            "EVENTO COM ALGUM TIPO DE PERDA?", TIPOS_PERDA, f"{k}_perda", atual.get("tipo_perda")
        )
    with c6:
        produto_perigoso = campo_sim_nao(
            "PRODUTO PERIGOSO?", f"{k}_perigoso", atual.get("produto_perigoso")
        )

    descricao = st.text_area(
        "BREVE DESCRIÇÃO DO ACIDENTE", value=texto(atual.get("descricao")) or "",
        key=f"{k}_descricao", height=90,
    )

    titulo_secao("2. Dados do acidentado / motorista", "Deixe em branco se não houve pessoa envolvida.")
    c7, c8, c9, c10 = st.columns([1.8, 1, 1, 1])
    with c7:
        nome = st.text_input("NOME", value=texto(atual.get("nome")) or "", key=f"{k}_nome")
    with c8:
        cpf = st.text_input(
            "CPF", value=fmt_cpf(atual.get("cpf")) if texto(atual.get("cpf")) else "",
            key=f"{k}_cpf", placeholder="000.000.000-00",
        )
    with c9:
        # sem min_value o Streamlit só deixa escolher os últimos 10 anos
        nascimento = st.date_input(
            "DATA DE NASCIMENTO", value=atual.get("data_nascimento"),
            min_value=date(1930, 1, 1), max_value=date.today(),
            format="DD/MM/YYYY", key=f"{k}_nasc",
        )
    with c10:
        tipo_motorista = campo_lista(
            "TIPO DE MOTORISTA", TIPOS_MOTORISTA, f"{k}_tipo_mot", atual.get("tipo_motorista")
        )

    titulo_secao("3. Veículo e viagem")
    c11, c12, c13 = st.columns([0.8, 1.6, 1.6])
    with c11:
        placa = st.text_input(
            "PLACA", value=texto(atual.get("placa")) or "", key=f"{k}_placa", placeholder="ABC1D23"
        )
    with c12:
        origem = st.text_input(
            "ORIGEM (ENDEREÇO)", value=texto(atual.get("origem")) or "", key=f"{k}_origem"
        )
    with c13:
        destino = st.text_input(
            "DESTINO (ENDEREÇO)", value=texto(atual.get("destino")) or "", key=f"{k}_destino"
        )

    link = st.text_input(
        "LINK DA EVIDÊNCIA", value=texto(atual.get("link_evidencia")) or "", key=f"{k}_link",
        placeholder="https://dellavolpe.sharepoint.com/...",
    )

    return {
        "data_evento": data_evento,
        "hora_evento": hora,
        "filial_origem": filial,
        "localizacao": texto(localizacao),
        "tipo_perda": tipo_perda,
        "produto_perigoso": produto_perigoso,
        "descricao": texto(descricao),
        "nome": texto(nome),
        "cpf": so_digitos(cpf) or None,
        "data_nascimento": nascimento,
        "tipo_motorista": tipo_motorista,
        "placa": placa_limpa(placa) or None,
        "origem": texto(origem),
        "destino": texto(destino),
        "link_evidencia": texto(link),
    }


def validar(d: dict) -> list:
    erros = []
    if not d["data_evento"]:
        erros.append("Informe a data do evento.")
    if not d["filial_origem"]:
        erros.append("Informe a filial de origem.")
    if not d["tipo_perda"]:
        erros.append("Informe o tipo de perda do evento.")
    if not d["descricao"]:
        erros.append("Descreva brevemente o acidente.")
    if d["cpf"] and erro_cpf(d["cpf"]):  # CPF é opcional, mas se vier tem que existir
        erros.append(erro_cpf(d["cpf"]))
    if d["placa"] and not re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", d["placa"]):
        erros.append(f"Placa inválida ({d['placa']}). Use o padrão ABC1234 ou ABC1D23.")
    if d["data_nascimento"] and d["data_evento"] and d["data_nascimento"] >= d["data_evento"]:
        erros.append("A data de nascimento precisa ser anterior à data do evento.")
    return erros


# ---------------------------------------------------------------------
# Novo relatório
# ---------------------------------------------------------------------

def novo(df: pd.DataFrame, usuario: dict) -> None:
    v = st.session_state.setdefault("ac_versao", 0)
    render_msg(MSG_NOVO)
    dados = campos_acidente(df, f"ac_novo_{v}", {})

    if st.button("💾 Salvar relatório de acidente", type="primary", key=f"ac_salvar_{v}"):
        erros = validar(dados)
        if erros:
            mostrar_erros(erros)
            return
        dados["criado_por"] = usuario["email"]
        ok, msg = banco.inserir(banco.ACIDENTE, [dados])
        if not ok:
            st.error(msg)
            return
        guardar_msg(
            MSG_NOVO, "success",
            "Acidente cadastrado. Para abrir as ações, vá em Menu › Plano de Ação e "
            "escolha este acidente em ACIDENTE VINCULADO.",
        )
        st.session_state["ac_versao"] += 1
        st.rerun()


# ---------------------------------------------------------------------
# Registros: consulta, edição e exclusão
# ---------------------------------------------------------------------

def acoes_por_acidente() -> dict:
    """{acidente_id: quantidade de ações} — para mostrar na tabela e travar exclusão."""
    try:
        acoes = banco.listar(banco.PLANO_ACAO)
    except Exception:
        return {}
    if acoes.empty or "acidente_id" not in acoes:
        return {}
    return acoes["acidente_id"].dropna().astype(int).value_counts().to_dict()


def registros(df: pd.DataFrame) -> None:
    render_msg(MSG_REG)
    if df.empty:
        st.info("Nenhum acidente cadastrado ainda.")
        return

    acoes = acoes_por_acidente()
    df = df.copy()
    df["acoes"] = df["id"].map(lambda i: acoes.get(int(i), 0))

    f1, f2, f3, f4, f5 = st.columns([1.3, 1.6, 1, 0.9, 0.9])
    with f1:
        filiais = st.multiselect("FILIAL", opcoes_existentes(df, "filial_origem"), key="ac_f_filial")
    with f2:
        perdas = st.multiselect("TIPO DE PERDA", TIPOS_PERDA, key="ac_f_perda")
    with f3:
        motoristas = st.multiselect("TIPO DE MOTORISTA", TIPOS_MOTORISTA, key="ac_f_mot")
    with f4:
        de = st.date_input("DE", value=None, format="DD/MM/YYYY", key="ac_f_de")
    with f5:
        ate = st.date_input("ATÉ", value=None, format="DD/MM/YYYY", key="ac_f_ate")

    f = df
    if filiais:
        f = f[f["filial_origem"].isin(filiais)]
    if perdas:
        f = f[f["tipo_perda"].isin(perdas)]
    if motoristas:
        f = f[f["tipo_motorista"].isin(motoristas)]
    if de:
        f = f[f["data_evento"] >= de]
    if ate:
        f = f[f["data_evento"] <= ate]

    perda_pessoal = int((f["tipo_perda"] == "Evento com perda pessoal").sum())
    perigoso = int((f["produto_perigoso"] == True).sum())  # noqa: E712 (None não conta)
    sem_acao = int((f["acoes"] == 0).sum())
    por_tipo = f["tipo_motorista"].value_counts()
    linha_cartoes([
        ("Acidentes", f"{len(f)}", "neutro", "no filtro"),
        ("Com perda pessoal", f"{perda_pessoal}", "vermelho" if perda_pessoal else "neutro", ""),
        ("Produto perigoso", f"{perigoso}", "laranja" if perigoso else "neutro", ""),
        ("Frota / Agregado / Terceiro",
         f"{por_tipo.get('Frota', 0)} / {por_tipo.get('Agregado', 0)} / {por_tipo.get('Terceiro', 0)}",
         "neutro", "tipo de motorista"),
        ("Sem plano de ação", f"{sem_acao}", "laranja" if sem_acao else "verde", "nenhuma ação vinculada"),
    ])
    st.write("")

    tabela = f[[
        "id", "data_evento", "hora_evento", "filial_origem", "tipo_perda", "descricao", "nome",
        "cpf", "tipo_motorista", "placa", "produto_perigoso", "localizacao", "acoes",
    ]].copy()
    tabela["cpf"] = tabela["cpf"].map(lambda c: fmt_cpf(c) if texto(c) else "")
    tabela["hora_evento"] = tabela["hora_evento"].map(lambda h: h.strftime("%H:%M") if h else "")
    textos = ["filial_origem", "tipo_perda", "descricao", "nome", "tipo_motorista", "placa", "localizacao"]
    tabela[textos] = tabela[textos].fillna("")

    versao_tabela = st.session_state.setdefault("ac_tabela_v", 0)
    evento = st.dataframe(
        tabela,
        key=f"ac_tabela_{versao_tabela}",
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.NumberColumn("ID", format="%d", width="small"),
            "data_evento": st.column_config.DateColumn("DATA", format="DD/MM/YYYY"),
            "hora_evento": "HORA",
            "filial_origem": "FILIAL",
            "tipo_perda": "TIPO DE PERDA",
            "descricao": st.column_config.TextColumn("DESCRIÇÃO", width="large"),
            "nome": "ACIDENTADO",
            "cpf": "CPF",
            "tipo_motorista": "MOTORISTA",
            "placa": "PLACA",
            "produto_perigoso": st.column_config.CheckboxColumn("PROD. PERIGOSO"),
            "localizacao": "LOCALIZAÇÃO",
            "acoes": st.column_config.NumberColumn("AÇÕES", format="%d", help="Ações vinculadas no Plano de Ação"),
        },
    )
    st.download_button(
        "⬇️ Baixar CSV", csv_excel(tabela), file_name="acidentes.csv", mime="text/csv", key="ac_csv",
    )

    linhas = evento.selection.rows
    if not linhas:
        st.caption("Selecione uma linha na tabela para editar ou excluir.")
        return
    st.divider()
    editar(f.iloc[linhas[0]], df)


def editar(reg: pd.Series, df: pd.DataFrame) -> None:
    rid = int(reg["id"])
    n_acoes = int(reg["acoes"])
    k = f"ac_ed_{rid}_{st.session_state['ac_tabela_v']}"
    titulo_secao(f"Acidente #{rid}")
    acoes_do_acidente(rid, reg["filial_origem"], k)

    titulo_secao("Editar dados do acidente")
    dados = campos_acidente(df, k, reg.to_dict())

    confirmar = st.checkbox("Quero excluir este acidente", key=f"{k}_confirma")
    b1, b2, _ = st.columns([1.4, 1, 4])
    salvar = b1.button("💾 Salvar alterações", type="primary", key=f"{k}_salvar")
    apagar = b2.button("🗑️ Excluir", key=f"{k}_excluir", disabled=not confirmar)

    if salvar:
        erros = validar(dados)
        if erros:
            mostrar_erros(erros)
            return
        concluir(banco.atualizar(banco.ACIDENTE, rid, dados))
    if apagar:
        if n_acoes:
            # a FK do plano de ação barraria no banco com uma mensagem técnica
            st.error(f"Este acidente tem {n_acoes} ação(ões) vinculada(s). Exclua ou desvincule "
                     "as ações no Plano de Ação antes de excluir o acidente.")
            return
        concluir(banco.excluir(banco.ACIDENTE, rid))


def nova_acao_para(rid: int, filial) -> None:
    """Abre o Plano de Ação › Nova ação já com este acidente (e a filial) preenchidos."""
    st.session_state["tela"] = "plano_acao"
    st.session_state["pa_pagina"] = "nova"
    st.session_state["pa_versao"] = st.session_state.get("pa_versao", 0) + 1  # campos novos, sem rascunho
    st.session_state["pa_prefill"] = {"acidente_id": rid, "filial": filial}


def acoes_do_acidente(rid: int, filial, k: str) -> None:
    """As ações do Plano de Ação vinculadas a este acidente (1 acidente → N ações)."""
    acoes = plano.carregar()
    if not acoes.empty:
        acoes = acoes[acoes["acidente_id"] == rid]

    if acoes.empty:
        st.caption("Nenhuma ação vinculada a este acidente ainda.")
    else:
        acoes = plano.enriquecer(acoes)
        tabela = acoes[["id", "situacao", "criticidade", "plano_acao", "responsavel", "prazo_final",
                        "data_conclusao", "status"]].copy()
        textos = ["criticidade", "plano_acao", "responsavel"]
        tabela[textos] = tabela[textos].fillna("")
        st.dataframe(
            tabela,
            hide_index=True,
            width="stretch",
            column_config={
                "id": st.column_config.NumberColumn("AÇÃO", format="%d", width="small"),
                "situacao": "SITUAÇÃO",
                "criticidade": "CRITICIDADE",
                "plano_acao": st.column_config.TextColumn("PLANO DE AÇÃO", width="large"),
                "responsavel": "RESPONSÁVEL",
                "prazo_final": st.column_config.DateColumn("PRAZO", format="DD/MM/YYYY"),
                "data_conclusao": st.column_config.DateColumn("CONCLUSÃO", format="DD/MM/YYYY"),
                "status": "STATUS",
            },
        )
    st.button("➕ Nova ação para este acidente", key=f"{k}_nova_acao",
              on_click=nova_acao_para, args=(rid, filial))


def concluir(resultado: tuple) -> None:
    ok, msg = resultado
    if not ok:
        st.error(msg)
        return
    guardar_msg(MSG_REG, "success", msg)
    st.session_state["ac_tabela_v"] += 1  # limpa a seleção da tabela
    st.rerun()
