"""Treinamentos — RQ 10 (Lista de Presença) → segtrabalho_treinamento.

Uma lista de presença = um treinamento, numa data e filial, com N
participantes, lançados um a um em campos normais (sem grade). Cada
participante vira uma linha na tabela.

Nenhum formulário usa st.form: com clear_on_submit os campos seriam apagados
também quando o insert falhasse. As chaves dos campos levam um número de
versão, que só avança depois de gravar com sucesso — é isso que limpa a tela.
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import banco
from comum import (
    FUNCOES_RQ05, VAZIO, campo_com_outro, campo_lista, cpf_valido, csv_excel, fmt_cpf,
    guardar_msg, mostrar_erros, opcoes_existentes, para_data, para_numero,
    render_msg, so_digitos, texto,
)
from estilo import (
    barra_paginas_lateral, bloco_usuario_lateral, cabecalho_tela, linha_cartoes, titulo_secao,
)

PAGINAS = {
    "nova": "Nova lista de presença",
    "registros": "Registros",
}
VINCULOS = ["Frota", "Agregado", "Terceiro", "Interno"]
COLUNAS = [
    "id", "nome", "cpf", "data_treinamento", "filial", "funcao", "setor",
    "treinamento", "vinculo", "data_validade", "avaliacao_nota",
    "link_evidencia", "criado_em", "criado_por",
]
MSG_NOVA = "tr_msg_nova"
MSG_REG = "tr_msg_reg"


def tela(usuario: dict) -> None:
    cabecalho_tela(
        "🎓 TREINAMENTOS",
        "RQ 10 — Lista de Presença: treinamentos, integrações e reciclagens.",
        "treinamento",
    )
    pagina = barra_paginas_lateral("tr_pagina", PAGINAS, "tr")
    bloco_usuario_lateral(usuario)
    df = carregar()
    if pagina == "nova":
        nova_lista(df, usuario)
    else:
        registros(df)


def carregar() -> pd.DataFrame:
    try:
        df = banco.listar(banco.TREINAMENTO)
    except Exception as erro:
        st.error(f"Não foi possível ler {banco.TREINAMENTO}: {erro}")
        df = pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=COLUNAS)
    for coluna in ("data_treinamento", "data_validade"):
        df[coluna] = df[coluna].map(para_data)
    return df


def situacao_validade(validade, hoje: date) -> str:
    if validade is None:
        return "Sem validade"
    if validade < hoje:
        return "Vencido"
    if validade < hoje + timedelta(days=30):
        return "Vence em 30 dias"
    return "Válido"


# ---------------------------------------------------------------------
# Nova lista de presença
# ---------------------------------------------------------------------
# Cada participante é lançado em campos normais e entra numa lista com
# "➕ Adicionar participante" — mais simples para quem não está acostumado
# a editar célula por célula numa grade. A lista só vai para o banco no
# "Salvar", toda de uma vez.

def opcoes_funcao(df: pd.DataFrame) -> list:
    """Funções da RQ 05 + as que já foram usadas no banco."""
    return sorted(set(FUNCOES_RQ05) | set(opcoes_existentes(df, "funcao")), key=str.casefold)


def nova_lista(df: pd.DataFrame, usuario: dict) -> None:
    v = st.session_state.setdefault("tr_versao", 0)
    lista = st.session_state.setdefault(f"tr_lista_{v}", [])
    render_msg(MSG_NOVA)

    titulo_secao("1. Treinamento", "O que foi aplicado, quando e em qual filial.")
    c1, c2, c3 = st.columns([2, 1, 1.5])
    with c1:
        treinamento = campo_com_outro(
            "TREINAMENTO", opcoes_existentes(df, "treinamento"), f"tr_trein_{v}",
            ajuda="Ex.: NR-35 Trabalho em Altura, Integração de Agregados, Direção Defensiva",
        )
    with c2:
        data_tr = st.date_input(
            "DATA DO TREINAMENTO", value=date.today(), format="DD/MM/YYYY", key=f"tr_data_{v}"
        )
    with c3:
        filial = campo_com_outro("FILIAL", opcoes_existentes(df, "filial"), f"tr_filial_{v}")

    c4, c5 = st.columns([1, 2.5])
    with c4:
        validade = st.date_input(
            "VALIDADE DO TREINAMENTO", value=None, format="DD/MM/YYYY", key=f"tr_validade_{v}",
            help="Deixe em branco se o treinamento não vence (DDS, campanha).",
        )
    with c5:
        link = st.text_input(
            "LINK DA EVIDÊNCIA (RQ 10 assinada)", key=f"tr_link_{v}",
            placeholder="https://dellavolpe.sharepoint.com/...",
        )

    titulo_secao(
        "2. Participantes",
        "Preencha os dados de uma pessoa e clique em ➕ Adicionar participante. Repita para cada uma.",
    )
    rascunho = campos_participante(df, lista, v)
    lista_participantes(lista, v)

    total = len(lista)
    rotulo = f"💾 Salvar lista de presença ({total} participante{'' if total == 1 else 's'})"
    if st.button(rotulo, type="primary", key=f"tr_salvar_{v}"):
        salvar_lista(df, usuario, treinamento, data_tr, filial, validade, link, lista, rascunho)


def campos_participante(df: pd.DataFrame, lista: list, v: int) -> bool:
    """Campos de UM participante + botão Adicionar. Devolve True se sobrou algo digitado."""
    pv = st.session_state.setdefault("tr_pv", 0)  # avança a cada pessoa adicionada: limpa os campos
    k = f"tr_p_{v}_{pv}"

    c1, c2 = st.columns([2, 1])
    with c1:
        nome = st.text_input("NOME COMPLETO", key=f"{k}_nome")
    with c2:
        cpf = st.text_input("CPF", key=f"{k}_cpf", placeholder="000.000.000-00")

    c3, c4, c5, c6 = st.columns([1.6, 1.4, 1, 1])
    with c3:
        funcao = campo_com_outro("FUNÇÃO", opcoes_funcao(df), f"{k}_funcao")
    with c4:
        setor = campo_com_outro("SETOR", opcoes_existentes(df, "setor"), f"{k}_setor")
    with c5:
        vinculo = campo_lista("VÍNCULO", VINCULOS, f"{k}_vinculo")
    with c6:
        nota = st.number_input(
            "AVALIAÇÃO (0 a 10)", min_value=0.0, max_value=10.0, step=0.5, value=None,
            placeholder="—", key=f"{k}_nota",
            help="Nota da avaliação do treinamento. Deixe em branco se não houve avaliação.",
        )

    if st.button("➕ Adicionar participante", key=f"{k}_add"):
        cpf_limpo = so_digitos(cpf)
        erros = []
        if not texto(nome):
            erros.append("Informe o nome.")
        if not cpf_valido(cpf_limpo):
            erros.append(f"CPF inválido ({cpf or 'vazio'}). Confira os 11 números.")
        elif any(p["cpf"] == cpf_limpo for p in lista):
            erros.append("Essa pessoa já está na lista.")
        if erros:
            mostrar_erros(erros, "Corrija antes de adicionar:")
        else:
            lista.append({
                "nome": texto(nome), "cpf": cpf_limpo, "funcao": funcao, "setor": setor,
                "vinculo": vinculo, "avaliacao_nota": nota,
            })
            st.session_state["tr_pv"] += 1
            st.rerun()

    return bool(texto(nome) or so_digitos(cpf))


def lista_participantes(lista: list, v: int) -> None:
    if not lista:
        st.caption("Nenhum participante adicionado ainda.")
        return
    with st.container(border=True):
        for i, p in enumerate(lista):
            nota = VAZIO if p["avaliacao_nota"] is None else f"{p['avaliacao_nota']:.1f}".replace(".", ",")
            detalhes = " · ".join([
                fmt_cpf(p["cpf"]), p["funcao"] or VAZIO, p["setor"] or VAZIO,
                p["vinculo"] or VAZIO, f"avaliação {nota}",
            ])
            texto_col, botao_col = st.columns([9, 1])
            texto_col.markdown(f"**{i + 1}. {p['nome']}**  \n{detalhes}")
            # on_click roda antes do rerun: o índice ainda é o desta linha
            botao_col.button("🗑️", key=f"tr_rm_{v}_{i}", help="Remover da lista",
                             on_click=lista.pop, args=(i,))


def salvar_lista(df, usuario, treinamento, data_tr, filial, validade, link, lista, rascunho) -> None:
    erros = []
    if not treinamento:
        erros.append("Informe o treinamento.")
    if not data_tr:
        erros.append("Informe a data do treinamento.")
    if not filial:
        erros.append("Informe a filial.")
    if validade and data_tr and validade < data_tr:
        erros.append("A validade não pode ser anterior à data do treinamento.")
    if rascunho:
        erros.append("Há um participante preenchido que não entrou na lista: clique em "
                     "➕ Adicionar participante (ou apague os campos) antes de salvar.")
    if not lista:
        erros.append("Adicione pelo menos um participante.")

    # quem já está lançado neste treinamento nesta data (evita gravar a lista duas vezes)
    if not df.empty and treinamento and data_tr:
        mesmo = df[(df["treinamento"] == treinamento) & (df["data_treinamento"] == data_tr)]
        ja_lancados = set(mesmo["cpf"].map(so_digitos))
        for p in lista:
            if p["cpf"] in ja_lancados:
                erros.append(f"{p['nome']} já está lançado(a) neste treinamento nesta data.")

    if erros:
        mostrar_erros(erros)
        return

    linhas = [{
        **p,
        "data_treinamento": data_tr,
        "filial": filial,
        "treinamento": treinamento,
        "data_validade": validade,
        "link_evidencia": texto(link),
        "criado_por": usuario["email"],
    } for p in lista]

    ok, msg = banco.inserir(banco.TREINAMENTO, linhas)
    if not ok:
        st.error(msg)  # nada foi limpo: a lista continua na tela
        return
    guardar_msg(MSG_NOVA, "success", f"Lista de presença salva — {msg}")
    st.session_state.pop(f"tr_lista_{st.session_state['tr_versao']}", None)
    st.session_state["tr_versao"] += 1
    st.session_state["tr_pv"] += 1
    st.rerun()


# ---------------------------------------------------------------------
# Registros: consulta, edição e exclusão
# ---------------------------------------------------------------------

def registros(df: pd.DataFrame) -> None:
    render_msg(MSG_REG)
    if df.empty:
        st.info("Nenhum treinamento lançado ainda.")
        return

    hoje = date.today()
    df = df.copy()
    df["situacao"] = df["data_validade"].map(lambda d: situacao_validade(d, hoje))

    f1, f2, f3, f4, f5 = st.columns([1.3, 1.6, 1, 0.9, 0.9])
    with f1:
        filiais = st.multiselect("FILIAL", opcoes_existentes(df, "filial"), key="tr_f_filial")
    with f2:
        treinos = st.multiselect("TREINAMENTO", opcoes_existentes(df, "treinamento"), key="tr_f_trein")
    with f3:
        vinculos = st.multiselect("VÍNCULO", VINCULOS, key="tr_f_vinculo")
    with f4:
        de = st.date_input("DE", value=None, format="DD/MM/YYYY", key="tr_f_de")
    with f5:
        ate = st.date_input("ATÉ", value=None, format="DD/MM/YYYY", key="tr_f_ate")
    busca = st.text_input("BUSCAR NOME OU CPF", key="tr_f_busca")

    f = df
    if filiais:
        f = f[f["filial"].isin(filiais)]
    if treinos:
        f = f[f["treinamento"].isin(treinos)]
    if vinculos:
        f = f[f["vinculo"].isin(vinculos)]
    if de:
        f = f[f["data_treinamento"] >= de]
    if ate:
        f = f[f["data_treinamento"] <= ate]
    if texto(busca):
        termo, digitos = texto(busca).lower(), so_digitos(busca)
        achou = f["nome"].str.lower().str.contains(termo, regex=False, na=False)
        if digitos:
            achou |= f["cpf"].astype(str).str.contains(digitos, regex=False, na=False)
        f = f[achou]

    notas = f["avaliacao_nota"].dropna()
    vencidos = int((f["situacao"] == "Vencido").sum())
    vencendo = int((f["situacao"] == "Vence em 30 dias").sum())
    linha_cartoes([
        ("Participações", f"{len(f)}", "neutro", "linhas no filtro"),
        ("Pessoas treinadas", f"{f['cpf'].nunique()}", "verde", "CPFs distintos"),
        ("Treinamentos", f"{f['treinamento'].nunique()}", "neutro", "tipos distintos"),
        ("Avaliação média", f"{notas.mean():.1f}".replace(".", ",") if len(notas) else VAZIO,
         "neutro", f"{len(notas)} avaliações"),
        ("Vencem em 30 dias", f"{vencendo}", "laranja" if vencendo else "neutro", ""),
        ("Vencidos", f"{vencidos}", "vermelho" if vencidos else "neutro", ""),
    ])
    st.write("")

    tabela = f[[
        "id", "data_treinamento", "treinamento", "filial", "nome", "cpf", "funcao",
        "setor", "vinculo", "avaliacao_nota", "data_validade", "situacao",
    ]].copy()
    tabela["cpf"] = tabela["cpf"].map(fmt_cpf)
    textos = ["treinamento", "filial", "nome", "funcao", "setor", "vinculo"]
    tabela[textos] = tabela[textos].fillna("")  # vazio em vez de "None" na tela

    versao_tabela = st.session_state.setdefault("tr_tabela_v", 0)
    evento = st.dataframe(
        tabela,
        key=f"tr_tabela_{versao_tabela}",
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.NumberColumn("ID", format="%d", width="small"),
            "data_treinamento": st.column_config.DateColumn("DATA", format="DD/MM/YYYY"),
            "treinamento": "TREINAMENTO",
            "filial": "FILIAL",
            "nome": "NOME",
            "cpf": "CPF",
            "funcao": "FUNÇÃO",
            "setor": "SETOR",
            "vinculo": "VÍNCULO",
            "avaliacao_nota": st.column_config.NumberColumn("AVALIAÇÃO", format="%.1f"),
            "data_validade": st.column_config.DateColumn("VALIDADE", format="DD/MM/YYYY"),
            "situacao": "SITUAÇÃO",
        },
    )
    st.download_button(
        "⬇️ Baixar CSV", csv_excel(tabela), file_name="treinamentos.csv",
        mime="text/csv", key="tr_csv",
    )

    linhas = evento.selection.rows
    if not linhas:
        st.caption("Selecione uma linha na tabela para editar ou excluir.")
        return
    registro = f.iloc[linhas[0]]
    st.divider()
    editar(registro, df)


def editar(reg: pd.Series, df: pd.DataFrame) -> None:
    rid = int(reg["id"])
    k = f"tr_ed_{rid}_{st.session_state['tr_tabela_v']}"
    titulo_secao(f"Editar registro #{rid}")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        nome = st.text_input("NOME", value=texto(reg["nome"]) or "", key=f"{k}_nome")
    with c2:
        cpf = st.text_input("CPF", value=fmt_cpf(reg["cpf"]), key=f"{k}_cpf")
    with c3:
        data_tr = st.date_input(
            "DATA DO TREINAMENTO", value=reg["data_treinamento"], format="DD/MM/YYYY", key=f"{k}_data"
        )

    c4, c5, c6 = st.columns([2, 1.5, 1])
    with c4:
        treinamento = campo_com_outro(
            "TREINAMENTO", opcoes_existentes(df, "treinamento"), f"{k}_trein", reg["treinamento"]
        )
    with c5:
        filial = campo_com_outro("FILIAL", opcoes_existentes(df, "filial"), f"{k}_filial", reg["filial"])
    with c6:
        vinculo = campo_lista("VÍNCULO", VINCULOS, f"{k}_vinculo", reg["vinculo"])

    c7, c8, c9, c10 = st.columns(4)
    with c7:
        funcao = campo_com_outro("FUNÇÃO", opcoes_funcao(df), f"{k}_funcao", reg["funcao"])
    with c8:
        setor = campo_com_outro("SETOR", opcoes_existentes(df, "setor"), f"{k}_setor", reg["setor"])
    with c9:
        nota = st.number_input(
            "AVALIAÇÃO (0–10)", min_value=0.0, max_value=10.0, step=0.5,
            value=para_numero(reg["avaliacao_nota"]), key=f"{k}_nota",
        )
    with c10:
        validade = st.date_input(
            "VALIDADE", value=reg["data_validade"], format="DD/MM/YYYY", key=f"{k}_validade"
        )
    link = st.text_input("LINK DA EVIDÊNCIA", value=texto(reg["link_evidencia"]) or "", key=f"{k}_link")

    confirmar = st.checkbox("Quero excluir este registro", key=f"{k}_confirma")
    b1, b2, _ = st.columns([1.4, 1, 4])
    salvar = b1.button("💾 Salvar alterações", type="primary", key=f"{k}_salvar")
    apagar = b2.button("🗑️ Excluir", key=f"{k}_excluir", disabled=not confirmar)

    if salvar:
        cpf_limpo = so_digitos(cpf)
        erros = []
        if not texto(nome):
            erros.append("Nome em branco.")
        if not cpf_valido(cpf_limpo):
            erros.append("CPF inválido.")
        if not treinamento:
            erros.append("Informe o treinamento.")
        if not filial:
            erros.append("Informe a filial.")
        if not data_tr:
            erros.append("Informe a data do treinamento.")
        if validade and data_tr and validade < data_tr:
            erros.append("A validade não pode ser anterior à data do treinamento.")
        if erros:
            mostrar_erros(erros)
            return
        dados = {
            "nome": texto(nome), "cpf": cpf_limpo, "data_treinamento": data_tr,
            "filial": filial, "funcao": texto(funcao), "setor": texto(setor),
            "treinamento": treinamento, "vinculo": vinculo, "data_validade": validade,
            "avaliacao_nota": nota, "link_evidencia": texto(link),
        }
        concluir(banco.atualizar(banco.TREINAMENTO, rid, dados))

    if apagar:
        concluir(banco.excluir(banco.TREINAMENTO, rid))


def concluir(resultado: tuple) -> None:
    ok, msg = resultado
    if not ok:
        st.error(msg)
        return
    guardar_msg(MSG_REG, "success", msg)
    st.session_state["tr_tabela_v"] += 1  # limpa a seleção da tabela
    st.rerun()
