"""Indicadores — painel de leitura, uma página por indicador (como o Indicador
Sustentabilidade). Só lê as tabelas que os CRUDs já gravam; o acesso por
filial é o mesmo do resto do app (acesso.listar).

Acidentes Internos: CATs (segtrabalho_cat) — quantos acidentes, com e sem
afastamento, dias perdidos e onde se concentram. Dias perdidos se dividem em
até o 15º dia (a empresa paga) e a partir do 16º (o INSS paga).
"""

import altair as alt
import pandas as pd
import streamlit as st

import pagina_cat
from comum import csv_excel, texto
from estilo import barra_paginas_lateral, bloco_usuario_lateral, cabecalho_tela, linha_cartoes, titulo_secao

PAGINAS = {
    "acidentes_internos": "Acidentes Internos",
}
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_NOME = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
              "Setembro", "Outubro", "Novembro", "Dezembro"]
DIAS_INSS = pagina_cat.DIAS_INSS
COR_EMPRESA, COR_INSS = "#E4610A", "#8C1D18"
COR_COM, COR_SEM, COR_NAO_INFORMADO = "#E4610A", "#D9CBBF", "#9A8E86"


def tela(usuario: dict) -> None:
    cabecalho_tela("📊 INDICADORES", "Indicadores de Segurança do Trabalho a partir dos lançamentos do app.",
                   "indicadores")
    barra_paginas_lateral("ind_pagina", PAGINAS, "ind")
    bloco_usuario_lateral(usuario)
    acidentes_internos()


# ---------------------------------------------------------------------
# Acidentes Internos (CAT)
# ---------------------------------------------------------------------

def acidentes_internos() -> None:
    st.markdown("### Acidentes Internos")
    df = pagina_cat.carregar()
    df = df[df["data_acidente"].notna()].copy()
    if df.empty:
        st.info("Nenhuma CAT lançada ainda.")
        return
    df["ano"] = df["data_acidente"].map(lambda d: d.year)
    df["mes"] = df["data_acidente"].map(lambda d: d.month)
    df["afastamento"] = df["houve_afastamento"].map(
        lambda a: "Com afastamento" if a is True else "Sem afastamento" if a is False else "Não informado")
    df["dias_empresa"] = df["dias_afastamento"].clip(upper=DIAS_INSS)
    df["dias_inss"] = (df["dias_afastamento"] - DIAS_INSS).clip(lower=0)

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        filiais = st.multiselect("FILIAL", sorted(df["filial"].dropna().unique()), key="ind_ai_filial")
    with f2:
        anos = st.multiselect("ANO", sorted(df["ano"].unique(), reverse=True), key="ind_ai_ano")
    with f3:
        meses = st.multiselect("MÊS", list(range(1, 13)), format_func=lambda m: MESES_NOME[m - 1],
                               key="ind_ai_mes")
    with f4:
        publicos = st.multiselect("PÚBLICO", pagina_cat.PUBLICOS, key="ind_ai_publico")

    f = df
    if filiais:
        f = f[f["filial"].isin(filiais)]
    if anos:
        f = f[f["ano"].isin(anos)]
    if meses:
        f = f[f["mes"].isin(meses)]
    if publicos:
        f = f[f["publico"].isin(publicos)]

    cartoes_acidentes(f)
    st.write("")
    analise, relatorio = st.tabs(["📊 Análise", "📄 Relatório"])
    with analise:
        if f.empty:
            st.info("Nenhuma CAT no filtro.")
        else:
            comparacao_mes(df, filiais, publicos)
            graficos_acidentes(f)
    with relatorio:
        relatorio_acidentes(f)


def cartoes_acidentes(f: pd.DataFrame) -> None:
    total = len(f)
    com = int((f["afastamento"] == "Com afastamento").sum())
    sem = int((f["afastamento"] == "Sem afastamento").sum())
    dias = f["dias_afastamento"].dropna()
    com_sem_dias = int(((f["afastamento"] == "Com afastamento") & f["dias_afastamento"].isna()).sum())
    acima = int((f["dias_afastamento"] > DIAS_INSS).sum())
    nota_dias = (f"empresa {int(f['dias_empresa'].sum())} · INSS {int(f['dias_inss'].sum())}"
                 + (f" · {com_sem_dias} sem dias informados" if com_sem_dias else ""))
    linha_cartoes([
        ("Acidentes", f"{total}", "neutro", "CATs no filtro"),
        ("Com afastamento", f"{com}", "laranja" if com else "neutro",
         f"{com / total:.0%} do total · {sem} sem afastamento" if total else ""),
        ("Dias perdidos", f"{int(dias.sum())}", "vermelho" if dias.sum() else "neutro", nota_dias),
        ("Média por afastamento", f"{dias.mean():.1f} dias".replace(".", ",") if len(dias) else "—", "neutro",
         f"em {len(dias)} afastamento(s) com dias informados" if len(dias) else ""),
        (f"Acima de {DIAS_INSS} dias", f"{acima}", "vermelho" if acima else "neutro",
         f"a partir do {DIAS_INSS + 1}º dia quem paga é o INSS"),
    ])


def comparacao_mes(df: pd.DataFrame, filiais: list, publicos: list) -> None:
    """Último mês fechado contra o anterior (o mês corrente fica de fora: ainda está aberto).
    Respeita filial e público, mas não ano/mês — a comparação tem o próprio período."""
    base = df
    if filiais:
        base = base[base["filial"].isin(filiais)]
    if publicos:
        base = base[base["publico"].isin(publicos)]
    hoje = pd.Timestamp.today()
    fechado = (hoje.to_period("M") - 1)
    anterior = fechado - 1

    def do_mes(p):
        m = base[(base["ano"] == p.year) & (base["mes"] == p.month)]
        return len(m), int(m["dias_afastamento"].sum())

    (ac, di), (ac_ant, di_ant) = do_mes(fechado), do_mes(anterior)
    nome = f"{MESES_NOME[fechado.month - 1]}/{fechado.year}"
    nome_ant = f"{MESES_NOME[anterior.month - 1]}/{anterior.year}"

    def seta(atual, antes, unidade):
        if atual == antes:
            return "= igual", "neutro"
        dif = atual - antes
        # para acidente, subir é ruim: vermelho; cair é bom: verde
        return f"{'▲' if dif > 0 else '▼'} {abs(dif)} {unidade}", "vermelho" if dif > 0 else "verde"

    texto_ac, cor_ac = seta(ac, ac_ant, "acidente(s)")
    texto_di, cor_di = seta(di, di_ant, "dia(s)")
    titulo_secao(f"{nome} vs. mês anterior",
                 "Último mês fechado — o mês corrente fica de fora porque ainda está aberto. "
                 "Usa os filtros de filial e público.")
    linha_cartoes([
        (f"Acidentes · {nome}", f"{ac}", "neutro", f"{nome_ant}: {ac_ant}"),
        ("Acidentes vs. anterior", texto_ac, cor_ac, ""),
        (f"Dias perdidos · {nome}", f"{di}", "neutro", f"{nome_ant}: {di_ant}"),
        ("Dias perdidos vs. anterior", texto_di, cor_di, ""),
    ])


def serie_mensal(f: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por mês, do primeiro ao último do filtro — mês sem CAT aparece com zero."""
    periodos = f["data_acidente"].map(lambda d: pd.Period(d, "M"))
    meses = pd.period_range(periodos.min(), periodos.max(), freq="M")
    g = f.assign(periodo=periodos).groupby("periodo")
    tabela = pd.DataFrame({
        "Com afastamento": g.apply(lambda x: (x["afastamento"] == "Com afastamento").sum(), include_groups=False),
        "Sem afastamento": g.apply(lambda x: (x["afastamento"] == "Sem afastamento").sum(), include_groups=False),
        "Não informado": g.apply(lambda x: (x["afastamento"] == "Não informado").sum(), include_groups=False),
        f"Até {DIAS_INSS} dias (empresa)": g["dias_empresa"].sum(),
        f"Acima de {DIAS_INSS} dias (INSS)": g["dias_inss"].sum(),
    }).reindex(meses, fill_value=0)
    tabela["mes"] = [f"{MESES[p.month - 1]}/{str(p.year)[2:]}" for p in tabela.index]
    return tabela.reset_index(drop=True)


def barras_empilhadas(tabela: pd.DataFrame, series: list, cores: list, titulo_y: str) -> alt.Chart:
    longa = tabela.melt("mes", series, var_name="Série", value_name="valor")
    ordem = list(tabela["mes"])
    return (
        alt.Chart(longa)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("mes:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("sum(valor):Q", title=titulo_y, axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("Série:N", scale=alt.Scale(domain=series, range=cores),
                            legend=None),  # a legenda vai no título (legenda_html): a do tema do Streamlit sobrepõe rótulos
            order=alt.Order("ordem:Q"),
            tooltip=["mes:N", "Série:N", alt.Tooltip("valor:Q", title=titulo_y)],
        )
        .transform_calculate(ordem=f"indexof({series}, datum['Série'])")
        .properties(height=260)
    )


def legenda_html(series: list, cores: list) -> str:
    return " &nbsp; ".join(f'<span style="color:{c}">■</span> {s}' for s, c in zip(series, cores))


def ranking(f: pd.DataFrame, coluna: str, titulo: str, n: int = 5) -> None:
    """Os n mais frequentes, em tabela com barra (rótulo longo não é cortado como no eixo do gráfico)."""
    contagem = f[coluna].map(texto).dropna().value_counts().head(n)
    if contagem.empty:
        st.markdown(f"**{titulo}**")
        st.caption("Sem informação no filtro.")
        return
    st.dataframe(
        contagem.rename_axis("item").reset_index(name="acidentes"), hide_index=True, width="stretch",
        column_config={
            "item": st.column_config.TextColumn(titulo.upper(), width="medium"),
            "acidentes": st.column_config.ProgressColumn(
                "ACIDENTES", format="%d", min_value=0, max_value=int(contagem.max())),
        },
    )


def graficos_acidentes(f: pd.DataFrame) -> None:
    mensal = serie_mensal(f)
    c1, c2 = st.columns(2)
    with c1:
        series = ["Com afastamento", "Sem afastamento", "Não informado"]
        cores = [COR_COM, COR_SEM, COR_NAO_INFORMADO]
        titulo_secao("Acidentes por mês", legenda_html(series, cores))
        st.altair_chart(barras_empilhadas(mensal, series, cores, "Acidentes"))
    with c2:
        series = [f"Até {DIAS_INSS} dias (empresa)", f"Acima de {DIAS_INSS} dias (INSS)"]
        cores = [COR_EMPRESA, COR_INSS]
        titulo_secao("Dias perdidos por mês", legenda_html(series, cores)
                     + f" — até o {DIAS_INSS}º dia a empresa paga; a partir do {DIAS_INSS + 1}º, o INSS.")
        st.altair_chart(barras_empilhadas(mensal, series, cores, "Dias perdidos"))

    titulo_secao("Por filial")
    por_filial = (
        f.groupby(f["filial"].fillna("Sem filial"))
        .agg(acidentes=("id", "size"),
             com_afastamento=("afastamento", lambda s: int((s == "Com afastamento").sum())),
             dias_perdidos=("dias_afastamento", "sum"),
             acima_15=("dias_afastamento", lambda s: int((s > DIAS_INSS).sum())))
        .sort_values(["dias_perdidos", "acidentes"], ascending=False)
        .reset_index()
    )
    por_filial["dias_perdidos"] = por_filial["dias_perdidos"].astype(int)
    st.dataframe(
        por_filial, hide_index=True, width="stretch",
        column_config={
            "filial": "FILIAL",
            "acidentes": st.column_config.NumberColumn("ACIDENTES", format="%d"),
            "com_afastamento": st.column_config.NumberColumn("COM AFASTAMENTO", format="%d"),
            "dias_perdidos": st.column_config.ProgressColumn(
                "DIAS PERDIDOS", format="%d", min_value=0, max_value=max(int(por_filial["dias_perdidos"].max()), 1)),
            "acima_15": st.column_config.NumberColumn(f"ACIMA DE {DIAS_INSS} DIAS", format="%d"),
        },
    )

    titulo_secao("Onde mais acontece", "Os 5 mais frequentes no filtro.")
    r1, r2, r3 = st.columns(3)
    with r1:
        ranking(f, "agente_causador", "Agente causador")
    with r2:
        ranking(f, "parte_corpo", "Parte do corpo")
    with r3:
        ranking(f, "cargo", "Função")


def relatorio_acidentes(f: pd.DataFrame) -> None:
    if f.empty:
        st.info("Nenhuma CAT no filtro.")
        return
    tabela = f.sort_values("data_acidente", ascending=False)[[
        "data_acidente", "numero_cat", "nome", "filial", "publico", "cargo", "tipo_acidente",
        "agente_causador", "parte_corpo", "afastamento", "dias_afastamento", "dias_empresa", "dias_inss",
    ]]
    st.dataframe(
        tabela, hide_index=True, width="stretch",
        column_config={
            "data_acidente": st.column_config.DateColumn("DATA", format="DD/MM/YYYY"),
            "numero_cat": "Nº CAT",
            "nome": "COLABORADOR",
            "filial": "FILIAL",
            "publico": "PÚBLICO",
            "cargo": "FUNÇÃO",
            "tipo_acidente": "TIPO",
            "agente_causador": "AGENTE CAUSADOR",
            "parte_corpo": "PARTE DO CORPO",
            "afastamento": "AFASTAMENTO",
            "dias_afastamento": st.column_config.NumberColumn("DIAS", format="%d"),
            "dias_empresa": st.column_config.NumberColumn("DIAS EMPRESA", format="%d"),
            "dias_inss": st.column_config.NumberColumn("DIAS INSS", format="%d"),
        },
    )
    st.download_button("⬇️ Baixar CSV", csv_excel(tabela), file_name="indicador_acidentes_internos.csv",
                       mime="text/csv", key="ind_ai_csv")
