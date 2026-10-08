"""Indicadores — painel de leitura, uma página por indicador (como o Indicador
Sustentabilidade). Só lê as tabelas que os CRUDs já gravam; o acesso por
filial é o mesmo do resto do app (acesso.listar).

Acidentes Internos: CATs (segtrabalho_cat) — quantos acidentes, com e sem
afastamento, dias perdidos e onde se concentram. Dias perdidos se dividem em
até o 15º dia (a empresa paga) e a partir do 16º (o INSS paga).

Treinamentos: listas de presença (segtrabalho_treinamento) — volume por mês e
ano, quando acontecem (dia da semana, semana do mês), pessoas por turma,
vencimentos e filiais sem treinamento. As cargas históricas de 2024/2025
foram gravadas no dia 1º do mês (a planilha só tinha o mês): entram nos
números por mês/ano, mas não no que depende do dia.

Acidentes × Viagens: acidentes do Relatório de Acidente (segtrabalho_acidente)
por 1.000 viagens. As viagens vêm de um parquet que o B.I gera no HANA e sobe
no MinIO (ARQUIVO_VIAGENS): uma linha por mês × filial × motorista.
"""

import io
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import acesso
import evidencia
import pagina_acidente
import pagina_cat
import pagina_treinamento
from comum import baixar_excel, so_digitos, texto
from estilo import barra_paginas_lateral, bloco_usuario_lateral, cabecalho_tela, linha_cartoes, titulo_secao

PAGINAS = {
    "acidentes_internos": "Acidentes Internos",
    "treinamentos": "Treinamentos",
    "acidentes_viagens": "Acidentes × Viagens",
}
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_NOME = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
              "Setembro", "Outubro", "Novembro", "Dezembro"]
DIAS_INSS = pagina_cat.DIAS_INSS
COR_EMPRESA, COR_INSS = "#E4610A", "#8C1D18"
COR_COM, COR_SEM, COR_NAO_INFORMADO = "#E4610A", "#D9CBBF", "#9A8E86"
CARGA_HISTORICA = "carga planilha"  # criado_por das cargas 2024/2025 (data = dia 1º do mês)
DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
SEMANAS_MES = ["1ª (dias 1–7)", "2ª (8–14)", "3ª (15–21)", "4ª (22–28)", "5ª (29–31)"]
VINCULOS = pagina_treinamento.VINCULOS + ["Não informado"]
CORES_VINCULO = ["#E4610A", "#8C1D18", "#F7A46B", "#5A4E46", "#D9CBBF"]
# parquet que a rotina do B.I gera no HANA e substitui no MinIO
BUCKET_VIAGENS, ARQUIVO_VIAGENS = "calculation-view", "dados_tratados/ViagensPorMotorista.parquet"
TIPOS_MOTORISTA = pagina_acidente.TIPOS_MOTORISTA  # Frota, Agregado, Terceiro
TIPO_VIAGEM = {"Frota": "Frota", "Agregado": "Agregado", "Terceiros/Dedicado": "Terceiro"}  # BP → app
CORES_TIPO = ["#8C1D18", "#E4610A", "#F7A46B"]
POR_MIL = 1000


def tela(usuario: dict) -> None:
    cabecalho_tela("📊 INDICADORES", "Indicadores de Segurança do Trabalho a partir dos lançamentos do app.",
                   "indicadores")
    pagina = barra_paginas_lateral("ind_pagina", PAGINAS, "ind")
    bloco_usuario_lateral(usuario)
    if pagina == "treinamentos":
        treinamentos()
    elif pagina == "acidentes_viagens":
        acidentes_viagens()
    else:
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
            x=alt.X("mes:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0 if len(ordem) <= 14 else -45)),
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


def contar(f: pd.DataFrame, coluna: str, n: int = 5) -> pd.Series:
    return f[coluna].map(texto).dropna().value_counts().head(n)


def ranking(contagem: pd.Series, titulo: str, rotulo_valor: str = "ACIDENTES") -> None:
    """Os mais frequentes, em tabela com barra (rótulo longo não é cortado como no eixo do gráfico)."""
    if contagem.empty:
        st.markdown(f"**{titulo}**")
        st.caption("Sem informação no filtro.")
        return
    st.dataframe(
        contagem.rename_axis("item").reset_index(name="valor"), hide_index=True, width="stretch",
        column_config={
            "item": st.column_config.TextColumn(titulo.upper(), width="medium"),
            "valor": st.column_config.ProgressColumn(
                rotulo_valor, format="%d", min_value=0, max_value=int(contagem.max())),
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
        ranking(contar(f, "agente_causador"), "Agente causador")
    with r2:
        ranking(contar(f, "parte_corpo"), "Parte do corpo")
    with r3:
        ranking(contar(f, "cargo"), "Função")


def relatorio_acidentes(f: pd.DataFrame) -> None:
    if f.empty:
        st.info("Nenhuma CAT no filtro.")
        return
    tabela = f.sort_values("data_acidente", ascending=False)[[
        "data_acidente", "numero_cat", "nome", "filial", "publico", "cargo", "tipo_acidente",
        "agente_causador", "parte_corpo", "afastamento", "dias_afastamento", "dias_empresa", "dias_inss",
    ]]
    colunas = {
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
    }
    st.dataframe(tabela, hide_index=True, width="stretch", column_config=colunas)
    baixar_excel(tabela, colunas, "indicador_acidentes_internos", "ind_ai_xlsx", "Acidentes internos")


# ---------------------------------------------------------------------
# Treinamentos
# ---------------------------------------------------------------------

def variacao(atual: float, antes: float, sobe_bom: bool = True) -> tuple:
    """('▲ 12,5%', cor) — sem base de comparação, mostra só a diferença."""
    if atual == antes:
        return "= igual", "neutro"
    texto_var = (f"{abs(atual - antes) / antes:.1%}".replace(".", ",") if antes
                 else f"+{atual - antes:g}")
    bom = (atual > antes) == sobe_bom
    return f"{'▲' if atual > antes else '▼'} {texto_var}", "verde" if bom else "vermelho"


def treinamentos() -> None:
    st.markdown("### Treinamentos")
    df = pagina_treinamento.carregar()
    df = df[df["data_treinamento"].notna()].copy()
    if df.empty:
        st.info("Nenhum treinamento lançado ainda.")
        return
    hoje = date.today()
    df["filial_nome"] = [acesso.FILIAIS.get(str(c), texto(f) or "Sem filial")
                         for c, f in zip(df["cod_filial"], df["filial"])]
    df["ano"] = df["data_treinamento"].map(lambda d: d.year)
    df["mes"] = df["data_treinamento"].map(lambda d: d.month)
    df["vinculo_"] = df["vinculo"].map(lambda v: texto(v) or "Não informado")
    df["data_real"] = ~df["criado_por"].fillna("").astype(str).str.startswith(CARGA_HISTORICA)
    df["pessoa"] = [texto(c) or (texto(n) or "").upper() for c, n in zip(df["cpf"], df["nome"])]
    df = pagina_treinamento.chaves_de_lista(df)
    # turma = uma lista de presença (na carga histórica: treinamento × mês × filial)
    df["turma"] = df[["treinamento", "data_treinamento", "filial_nome", "instrutor_chave", "lista_chave"]] \
        .astype(str).agg("|".join, axis=1)

    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        filiais = st.multiselect("FILIAL", sorted(df["filial_nome"].unique()), key="ind_tr_filial")
    with f2:
        anos = st.multiselect("ANO", sorted(df["ano"].unique(), reverse=True), key="ind_tr_ano")
    with f3:
        meses = st.multiselect("MÊS", list(range(1, 13)), format_func=lambda m: MESES_NOME[m - 1],
                               key="ind_tr_mes")
    with f4:
        nomes = st.multiselect("TREINAMENTO", sorted(df["treinamento"].dropna().unique(), key=str.casefold),
                               key="ind_tr_treinamento")
    with f5:
        vinculos = st.multiselect("VÍNCULO", VINCULOS, key="ind_tr_vinculo")

    # base = sem o recorte de período (comparação anual, vencimentos e filiais têm o próprio período)
    base = df
    if filiais:
        base = base[base["filial_nome"].isin(filiais)]
    if nomes:
        base = base[base["treinamento"].isin(nomes)]
    if vinculos:
        base = base[base["vinculo_"].isin(vinculos)]
    f = base
    if anos:
        f = f[f["ano"].isin(anos)]
    if meses:
        f = f[f["mes"].isin(meses)]

    situacao = situacao_atual(base, hoje)
    cartoes_treinamentos(f, situacao)
    st.write("")
    analise, vencimentos, aba_filiais, relatorio = st.tabs(
        ["📊 Análise", "⏰ Vencimentos", "🏢 Filiais", "📄 Relatório"])
    with analise:
        comparacao_anual(base, hoje)
        if f.empty:
            st.info("Nenhum treinamento no filtro.")
        else:
            graficos_treinamentos(f)
    with vencimentos:
        tabela_vencimentos(situacao)
    with aba_filiais:
        filiais_sem_treinamento(f, base, filiais, hoje)
    with relatorio:
        relatorio_treinamentos(f)


def situacao_atual(base: pd.DataFrame, hoje: date) -> pd.DataFrame:
    """Última participação de cada pessoa em cada treinamento, com a situação da validade.
    Quem já refez o treinamento não conta como vencido pela participação antiga."""
    ultima = base.sort_values("data_treinamento").drop_duplicates(["pessoa", "treinamento"], keep="last")
    ultima = ultima[ultima["pessoa"] != ""].copy()
    ultima["situacao"] = ultima["data_validade"].map(lambda v: pagina_treinamento.situacao_validade(v, hoje))
    ultima["dias"] = ultima["data_validade"].map(lambda v: (v - hoje).days if v else None)
    return ultima


def cartoes_treinamentos(f: pd.DataFrame, situacao: pd.DataFrame) -> None:
    reais = f[f["data_real"]]
    media = reais.groupby("turma").size().mean() if not reais.empty else None
    avaliacoes = f["avaliacao"].map(texto).dropna()
    satisfeitos = (avaliacoes == "Satisfeito").mean() if len(avaliacoes) else None
    em_7 = int((situacao["situacao"] == "Vence em 7 dias").sum())
    em_30 = em_7 + int((situacao["situacao"] == "Vence em 30 dias").sum())
    vencidos = int((situacao["situacao"] == "Vencido").sum())
    pessoas = f.loc[f["pessoa"] != "", "pessoa"].nunique()
    linha_cartoes([
        ("Participações", milhar(len(f)), "neutro", f"{milhar(pessoas)} pessoas diferentes"),
        ("Turmas", milhar(f["turma"].nunique()), "neutro",
         f"média de {media:.1f} pessoas por turma".replace(".", ",") if media else ""),
        ("Satisfação", f"{satisfeitos:.0%}" if satisfeitos is not None else "—",
         "verde" if satisfeitos and satisfeitos >= 0.8 else "laranja" if satisfeitos is not None else "neutro",
         f"satisfeitos em {milhar(len(avaliacoes))} avaliações" if len(avaliacoes) else "sem avaliação no filtro"),
        ("Vencem em 30 dias", f"{em_30}", "laranja" if em_30 else "neutro",
         f"{em_7} em até 7 dias" if em_7 else "nenhum em até 7 dias"),
        ("Vencidos", milhar(vencidos), "vermelho" if vencidos else "verde", "sem renovação (situação de hoje)"),
    ])


def milhar(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def comparacao_anual(base: pd.DataFrame, hoje: date) -> None:
    """Mesmos meses fechados nos dois anos (o mês corrente fica de fora: ainda está aberto)."""
    fechados = hoje.month - 1
    if not fechados:
        return
    ano, ano_ant = hoje.year, hoje.year - 1
    periodo = f"{MESES[0]}–{MESES[fechados - 1]}" if fechados > 1 else MESES[0]

    def no_periodo(a):
        return base[(base["ano"] == a) & (base["mes"] <= fechados)]

    atual, anterior = no_periodo(ano), no_periodo(ano_ant)
    mes = base[(base["ano"] == ano) & (base["mes"] == fechados)]
    mes_ant_p = pd.Period(date(ano, fechados, 1), "M") - 1
    mes_ant = base[(base["ano"] == mes_ant_p.year) & (base["mes"] == mes_ant_p.month)]
    texto_ano, cor_ano = variacao(len(atual), len(anterior))
    texto_mes, cor_mes = variacao(len(mes), len(mes_ant))
    titulo_secao(f"Participações {periodo}/{ano} vs. {ano_ant}",
                 "Mesmos meses nos dois anos, só meses fechados. Usa os filtros de filial, treinamento e vínculo.")
    linha_cartoes([
        (f"{periodo}/{ano}", milhar(len(atual)), "neutro", f"{milhar(atual['turma'].nunique())} turmas"),
        (f"Mesmo período {ano_ant}", milhar(len(anterior)), "neutro", f"{milhar(anterior['turma'].nunique())} turmas"),
        (f"{ano} vs. {ano_ant}", texto_ano, cor_ano, f"{len(atual) - len(anterior):+d} participações"),
        (f"{MESES_NOME[fechados - 1]} vs. mês anterior", texto_mes, cor_mes,
         f"{len(mes)} contra {len(mes_ant)} em {MESES_NOME[mes_ant_p.month - 1]}"),
    ])


def contagem_mensal(f: pd.DataFrame, coluna: str, series: list) -> pd.DataFrame:
    """Participações por mês × série, do primeiro ao último mês do filtro (mês vazio = zero)."""
    periodos = f["data_treinamento"].map(lambda d: pd.Period(d, "M"))
    meses = pd.period_range(periodos.min(), periodos.max(), freq="M")
    tabela = pd.crosstab(periodos, f[coluna]).reindex(index=meses, columns=series, fill_value=0)
    tabela["mes"] = [f"{MESES[p.month - 1]}/{str(p.year)[2:]}" for p in tabela.index]
    return tabela.reset_index(drop=True)


def barras_destaque(dados: pd.DataFrame, categoria: str, ordem: list, titulo_y: str) -> alt.Chart:
    """Barras de turmas por categoria; a maior fica em laranja escuro."""
    maior = dados["turmas"].max()
    return (
        alt.Chart(dados.assign(destaque=dados["turmas"] == maior))
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(f"{categoria}:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("turmas:Q", title=titulo_y, axis=alt.Axis(tickMinStep=1)),
            color=alt.condition("datum.destaque", alt.value("#B84E08"), alt.value("#F7A46B")),
            tooltip=[alt.Tooltip(f"{categoria}:N", title=" "), alt.Tooltip("turmas:Q", title="Turmas"),
                     alt.Tooltip("participacoes:Q", title="Participações")],
        )
        .properties(height=230)
    )


def quando_acontecem(reais: pd.DataFrame) -> None:
    titulo_secao("Quando acontecem",
                 "Turmas por dia da semana e por semana do mês. Só lançamentos do app (QR Code, lista e Excel): "
                 "as cargas de 2024/2025 têm só o mês.")
    if reais.empty:
        st.caption("Nenhum lançamento com data completa no filtro.")
        return
    pessoas = reais.groupby("turma").size().rename("participacoes")
    turmas = reais.drop_duplicates("turma").join(pessoas, on="turma").assign(n=1)
    turmas["dia"] = turmas["data_treinamento"].map(lambda d: DIAS_SEMANA[d.weekday()])
    turmas["semana"] = turmas["data_treinamento"].map(lambda d: SEMANAS_MES[(d.day - 1) // 7])
    c1, c2 = st.columns(2)
    for coluna_tela, campo, ordem, titulo in ((c1, "dia", DIAS_SEMANA, "Dia da semana"),
                                              (c2, "semana", SEMANAS_MES, "Semana do mês")):
        dados = (turmas.groupby(campo).agg(turmas=("n", "sum"), participacoes=("participacoes", "sum"))
                 .reindex(ordem, fill_value=0).rename_axis(campo).reset_index())
        top = dados.loc[dados["turmas"].idxmax()]
        with coluna_tela:
            st.markdown(f"**{titulo}** · mais turmas: **{top[campo]}** ({int(top['turmas'])})")
            st.altair_chart(barras_destaque(dados, campo, ordem, "Turmas"))


def pessoas_por_turma(reais: pd.DataFrame) -> None:
    titulo_secao("Pessoas por turma", "Participantes por lista, por treinamento. Só lançamentos do app.")
    if reais.empty:
        st.caption("Nenhum lançamento com data completa no filtro.")
        return
    por_turma = reais.groupby(["treinamento", "turma"]).size().rename("pessoas").reset_index()
    tabela = (por_turma.groupby("treinamento")
              .agg(turmas=("turma", "size"), participacoes=("pessoas", "sum"), media=("pessoas", "mean"),
                   menor=("pessoas", "min"), maior=("pessoas", "max"))
              .sort_values("turmas", ascending=False).reset_index())
    st.dataframe(
        tabela, hide_index=True, width="stretch",
        column_config={
            "treinamento": st.column_config.TextColumn("TREINAMENTO", width="large"),
            "turmas": st.column_config.NumberColumn("TURMAS", format="%d"),
            "participacoes": st.column_config.NumberColumn("PARTICIPAÇÕES", format="%d"),
            "media": st.column_config.ProgressColumn("MÉDIA POR TURMA", format="%.1f", min_value=0,
                                                     max_value=float(tabela["media"].max())),
            "menor": st.column_config.NumberColumn("MENOR TURMA", format="%d"),
            "maior": st.column_config.NumberColumn("MAIOR TURMA", format="%d"),
        },
    )


def graficos_treinamentos(f: pd.DataFrame) -> None:
    titulo_secao("Participações por mês", legenda_html(VINCULOS, CORES_VINCULO))
    st.altair_chart(barras_empilhadas(contagem_mensal(f, "vinculo_", VINCULOS), VINCULOS, CORES_VINCULO,
                                      "Participações"))
    reais = f[f["data_real"]]
    quando_acontecem(reais)
    pessoas_por_turma(reais)

    titulo_secao("Rankings", "Os 5 maiores no filtro.")
    r1, r2, r3 = st.columns(3)
    with r1:
        ranking(contar(f, "treinamento"), "Treinamento", "PARTICIPAÇÕES")
    with r2:
        # a carga histórica não tem instrutor: o ranking só pega o que foi lançado com ele
        ranking(contar(f.drop_duplicates("turma"), "instrutor"), "Instrutor", "TURMAS")
    with r3:
        respostas = f["avaliacao"].map(texto).dropna().value_counts()
        ranking(respostas.reindex(pagina_treinamento.AVALIACOES).dropna().astype(int), "Avaliação", "RESPOSTAS")


def tabela_vencimentos(situacao: pd.DataFrame) -> None:
    titulo_secao("Vencimentos",
                 "Última participação de cada pessoa em cada treinamento: quem já refez não aparece como vencido. "
                 "Usa os filtros de filial, treinamento e vínculo.")
    escolha = st.multiselect("SITUAÇÃO", ["Vencido", "Vence em 7 dias", "Vence em 30 dias"],
                             default=["Vence em 7 dias", "Vence em 30 dias"], key="ind_tr_situacao")
    lista = situacao[situacao["situacao"].isin(escolha)].sort_values("data_validade")
    if lista.empty:
        st.success("Nenhum treinamento nessa situação.")
        return
    tabela = lista[["data_validade", "dias", "situacao", "nome", "treinamento", "filial_nome", "vinculo_",
                    "funcao", "data_treinamento"]]
    colunas = {
        "data_validade": st.column_config.DateColumn("VALIDADE", format="DD/MM/YYYY"),
        "dias": st.column_config.NumberColumn("DIAS", format="%d", help="Dias até vencer (negativo = já venceu)"),
        "situacao": "SITUAÇÃO",
        "nome": "NOME",
        "treinamento": "TREINAMENTO",
        "filial_nome": "FILIAL",
        "vinculo_": "VÍNCULO",
        "funcao": "FUNÇÃO",
        "data_treinamento": st.column_config.DateColumn("FEITO EM", format="DD/MM/YYYY"),
    }
    st.dataframe(tabela, hide_index=True, width="stretch", column_config=colunas)
    baixar_excel(tabela, colunas, "treinamentos_vencimentos", "ind_tr_xlsx_venc", "Vencimentos")


def filiais_sem_treinamento(f: pd.DataFrame, base: pd.DataFrame, filiais: list, hoje: date) -> None:
    titulo_secao("Filiais", "Todas as filiais do seu acesso, inclusive as que nunca lançaram treinamento. "
                            "Usa os filtros de treinamento e vínculo.")
    limite = st.select_slider("SEM TREINAMENTO HÁ MAIS DE", [30, 60, 90, 180, 365], value=90,
                              format_func=lambda d: f"{d} dias", key="ind_tr_limite")
    nomes = sorted({acesso.FILIAIS.get(c, c) for c in acesso.perfil()["codigos"]} | set(base["filial_nome"]))
    if filiais:
        nomes = [n for n in nomes if n in filiais]
    ultimo = base.groupby("filial_nome")["data_treinamento"].max()
    no_filtro = f.groupby("filial_nome").agg(turmas=("turma", "nunique"), participacoes=("id", "size"))
    tabela = pd.DataFrame({"filial": nomes})
    tabela["ultimo"] = pd.to_datetime(tabela["filial"].map(ultimo))  # NaT (célula vazia) para quem nunca lançou
    tabela["dias"] = (pd.Timestamp(hoje) - tabela["ultimo"]).dt.days.astype("Int64")
    tabela["turmas"] = tabela["filial"].map(no_filtro["turmas"]).fillna(0).astype(int)
    tabela["participacoes"] = tabela["filial"].map(no_filtro["participacoes"]).fillna(0).astype(int)
    parada = f"Há mais de {limite} dias"
    tabela["situacao"] = tabela["dias"].map(
        lambda d: "Nunca lançou" if pd.isna(d) else parada if d > limite else "Em dia")
    nunca = int((tabela["situacao"] == "Nunca lançou").sum())
    paradas = int((tabela["situacao"] == parada).sum())
    linha_cartoes([
        ("Filiais", f"{len(tabela)}", "neutro", "no seu acesso"),
        (f"Sem treinamento há + de {limite} dias", f"{paradas}", "vermelho" if paradas else "verde",
         "último treinamento antes disso"),
        ("Nunca lançaram", f"{nunca}", "laranja" if nunca else "verde", "nenhum treinamento no app"),
        ("Com turma no filtro", f"{int((tabela['turmas'] > 0).sum())}", "neutro", "período dos filtros de ano e mês"),
    ])
    ordem = {parada: 0, "Nunca lançou": 1, "Em dia": 2}
    tabela = (tabela.assign(_ordem=tabela["situacao"].map(ordem), _dias=-tabela["dias"].fillna(0))
              .sort_values(["_ordem", "_dias", "filial"]).drop(columns=["_ordem", "_dias"]))
    # célula vazia vira "None" no st.dataframe: quem nunca lançou mostra "—"
    tabela["ultimo"] = tabela["ultimo"].map(lambda d: "—" if pd.isna(d) else f"{d:%d/%m/%Y}")
    tabela["dias"] = tabela["dias"].map(lambda d: "—" if pd.isna(d) else str(int(d)))
    st.dataframe(
        tabela, hide_index=True, width="stretch",
        column_config={
            "filial": "FILIAL",
            "ultimo": "ÚLTIMO TREINAMENTO",
            "dias": "DIAS DESDE O ÚLTIMO",
            "turmas": st.column_config.NumberColumn("TURMAS NO FILTRO", format="%d"),
            "participacoes": st.column_config.NumberColumn("PARTICIPAÇÕES NO FILTRO", format="%d"),
            "situacao": "SITUAÇÃO",
        },
    )


def relatorio_treinamentos(f: pd.DataFrame) -> None:
    if f.empty:
        st.info("Nenhum treinamento no filtro.")
        return
    tabela = f.sort_values("data_treinamento", ascending=False)[[
        "data_treinamento", "treinamento", "filial_nome", "instrutor", "nome", "funcao", "setor", "vinculo_",
        "avaliacao", "data_validade",
    ]]
    colunas = {
        "data_treinamento": st.column_config.DateColumn("DATA", format="DD/MM/YYYY"),
        "treinamento": "TREINAMENTO",
        "filial_nome": "FILIAL",
        "instrutor": "INSTRUTOR",
        "nome": "NOME",
        "funcao": "FUNÇÃO",
        "setor": "SETOR",
        "vinculo_": "VÍNCULO",
        "avaliacao": "AVALIAÇÃO",
        "data_validade": st.column_config.DateColumn("VALIDADE", format="DD/MM/YYYY"),
    }
    st.dataframe(tabela, hide_index=True, width="stretch", column_config=colunas)
    baixar_excel(tabela, colunas, "indicador_treinamentos", "ind_tr_xlsx", "Treinamentos")


# ---------------------------------------------------------------------
# Acidentes × Viagens
# ---------------------------------------------------------------------
# Viagens: parquet gerado no HANA (vale-frete emitido → OF → placa → motorista
# do veículo → BP), uma linha por mês × filial × motorista. Fica no MinIO e é
# substituído pela rotina do B.I. Acidentes: Relatório de Acidente.

def _rotulo_mes(p: pd.Period) -> str:
    return f"{MESES[p.month - 1]}/{str(p.year)[2:]}"


@st.cache_data(ttl=3600, show_spinner="Lendo a base de viagens…")
def _viagens_minio() -> pd.DataFrame:
    df = pd.read_parquet(io.BytesIO(evidencia.baixar(ARQUIVO_VIAGENS, BUCKET_VIAGENS)))
    df.columns = [c.upper() for c in df.columns]
    return pd.DataFrame({
        "periodo": [pd.Period(year=int(a), month=int(m), freq="M") for a, m in zip(df["ANO"], df["MES"])],
        "cod_filial": df["COD_FILIAL"].astype(str).str.strip().str.zfill(4),
        "tipo": df["TIPO_PARCEIRO"].map(lambda t: TIPO_VIAGEM.get(texto(t), texto(t))),
        "cod_parceiro": df["COD_PARCEIRO"].astype(str),
        "nome": df["NOME_PARCEIRO"],
        "cpf": df["CPF_CNPJ"].map(so_digitos),
        "viagens": df["QTD_VIAGENS"].astype(int),
    })


def carregar_viagens():
    """Base de viagens recortada pelas filiais do usuário; None se não deu para ler."""
    try:
        df = _viagens_minio()
    except Exception as erro:
        st.warning(f"Não foi possível ler a base de viagens (`{BUCKET_VIAGENS}/{ARQUIVO_VIAGENS}` no MinIO): {erro}")
        return None
    if not acesso.perfil()["admin"]:
        df = df[df["cod_filial"].isin(acesso.perfil()["codigos"])]
    return df.assign(filial=df["cod_filial"].map(lambda c: acesso.FILIAIS.get(c, c)))


def taxa(acidentes: float, viagens: float):
    return acidentes / viagens * POR_MIL if viagens else None


def fmt_taxa(valor) -> str:
    return "—" if valor is None or pd.isna(valor) else f"{valor:.2f}".replace(".", ",")


def acidentes_viagens() -> None:
    st.markdown("### Acidentes × Viagens")
    viagens = carregar_viagens()
    if viagens is None:
        return
    if viagens.empty:
        st.info("Nenhuma viagem na base para as suas filiais.")
        return
    acid = pagina_acidente.carregar()
    acid = acid[acid["data_evento"].notna()].copy()
    acid["periodo"] = acid["data_evento"].map(lambda d: pd.Period(d, "M"))
    acid["cod_filial"] = acid["cod_filial"].map(lambda c: texto(c))
    acid["filial"] = [acesso.FILIAIS.get(c, texto(f) or "Sem filial") for c, f in zip(acid["cod_filial"], acid["filial_origem"])]
    acid["tipo"] = acid["tipo_motorista"].map(lambda t: texto(t) or "Não informado")
    acid["cpf_limpo"] = acid["cpf"].map(so_digitos)
    # a taxa só vale nos meses que a base de viagens cobre
    inicio, fim = viagens["periodo"].min(), viagens["periodo"].max()
    acid = acid[(acid["periodo"] >= inicio) & (acid["periodo"] <= fim)]

    f1, f2, f3, f4, f5 = st.columns([1.2, 1.1, 1.1, 1.1, 1.3])
    with f1:
        filiais = st.multiselect("FILIAL", sorted(set(viagens["filial"]) | set(acid["filial"])), key="ind_av_filial")
    with f2:
        anos = st.multiselect("ANO", sorted({p.year for p in viagens["periodo"]}, reverse=True), key="ind_av_ano")
    with f3:
        meses = st.multiselect("MÊS", list(range(1, 13)), format_func=lambda m: MESES_NOME[m - 1], key="ind_av_mes")
    with f4:
        tipos = st.multiselect("TIPO DE MOTORISTA", TIPOS_MOTORISTA, key="ind_av_tipo")
    with f5:
        perdas = st.multiselect("TIPO DE PERDA (acidentes)", pagina_acidente.TIPOS_PERDA, key="ind_av_perda")

    def recorta(df):
        if filiais:
            df = df[df["filial"].isin(filiais)]
        if anos:
            df = df[df["periodo"].map(lambda p: p.year).isin(anos)]
        if meses:
            df = df[df["periodo"].map(lambda p: p.month).isin(meses)]
        if tipos:
            df = df[df["tipo"].isin(tipos)]
        return df

    v, a = recorta(viagens), recorta(acid)
    if perdas:
        a = a[a["tipo_perda"].isin(perdas)]
    st.caption(f"Base de viagens: {_rotulo_mes(inicio)} a {_rotulo_mes(fim)} (o último mês pode estar em andamento). "
               "Viagem = OF com vale-frete emitido.")

    total_v, total_a = int(v["viagens"].sum()), len(a)
    sem_tipo = int((a["tipo"] == "Não informado").sum())
    linha_cartoes([
        ("Acidentes", f"{total_a}", "laranja" if total_a else "verde",
         f"{sem_tipo} sem tipo de motorista" if sem_tipo else "Relatório de Acidente"),
        ("Viagens", milhar(total_v), "neutro", f"{milhar(v['cpf'].nunique())} motoristas"),
        (f"Acidentes por {milhar(POR_MIL)} viagens", fmt_taxa(taxa(total_a, total_v)),
         "vermelho" if total_a else "verde", "acidentes ÷ viagens × 1.000"),
        ("Viagens por acidente", milhar(total_v / total_a) if total_a else "—", "neutro",
         "uma ocorrência a cada N viagens"),
    ])
    st.write("")
    analise, acidentados, relatorio = st.tabs(["📊 Análise", "🧑 Acidentados", "📄 Relatório"])
    with analise:
        graficos_viagens(v, a)
    with acidentados:
        tabela_acidentados(a, viagens)
    with relatorio:
        relatorio_viagens(v, a)


def resumo(v: pd.DataFrame, a: pd.DataFrame, chave: list) -> pd.DataFrame:
    """Viagens, motoristas, acidentes e taxa por `chave`."""
    vv = v.groupby(chave).agg(viagens=("viagens", "sum"), motoristas=("cpf", "nunique"))
    aa = a.groupby(chave).size().rename("acidentes")
    tabela = vv.join(aa, how="outer").fillna(0)
    tabela[["viagens", "motoristas", "acidentes"]] = tabela[["viagens", "motoristas", "acidentes"]].astype(int)
    tabela["taxa"] = [taxa(x, y) for x, y in zip(tabela["acidentes"], tabela["viagens"])]
    return tabela.reset_index()


def graficos_viagens(v: pd.DataFrame, a: pd.DataFrame) -> None:
    mensal = resumo(v, a, ["periodo"]).sort_values("periodo")
    if mensal.empty:
        st.info("Nenhuma viagem no filtro.")
        return
    meses = pd.period_range(mensal["periodo"].min(), mensal["periodo"].max(), freq="M")
    mensal = mensal.set_index("periodo").reindex(meses).fillna({"viagens": 0, "acidentes": 0}).reset_index(names="periodo")
    mensal["mes"] = mensal["periodo"].map(_rotulo_mes)

    por_tipo = v.groupby(["periodo", "tipo"])["viagens"].sum().unstack(fill_value=0) \
        .reindex(index=meses, columns=TIPOS_MOTORISTA, fill_value=0)
    por_tipo["mes"] = [_rotulo_mes(p) for p in por_tipo.index]
    c1, c2 = st.columns(2)
    with c1:
        titulo_secao("Viagens por mês", legenda_html(TIPOS_MOTORISTA, CORES_TIPO))
        st.altair_chart(barras_empilhadas(por_tipo.reset_index(drop=True), TIPOS_MOTORISTA, CORES_TIPO, "Viagens"))
    with c2:
        titulo_secao(f"Acidentes por {milhar(POR_MIL)} viagens, por mês",
                     "A barra é a taxa do mês; passe o mouse para ver acidentes e viagens.")
        ordem = list(mensal["mes"])
        grafico = (
            alt.Chart(mensal.assign(taxa=mensal["taxa"].fillna(0)))
            .mark_bar(color=COR_INSS, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("mes:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0 if len(ordem) <= 14 else -45)),
                y=alt.Y("taxa:Q", title=f"Acidentes / {milhar(POR_MIL)} viagens"),
                tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("taxa:Q", title="Taxa", format=".2f"),
                         alt.Tooltip("acidentes:Q", title="Acidentes"), alt.Tooltip("viagens:Q", title="Viagens", format=",")],
            )
            .properties(height=260)
        )
        st.altair_chart(grafico)

    colunas_resumo = {
        "viagens": st.column_config.NumberColumn("VIAGENS", format="%d"),
        "motoristas": st.column_config.NumberColumn("MOTORISTAS", format="%d"),
        "acidentes": st.column_config.NumberColumn("ACIDENTES", format="%d"),
        "taxa": st.column_config.NumberColumn(f"POR {milhar(POR_MIL)} VIAGENS", format="%.2f"),
    }
    titulo_secao("Por tipo de motorista")
    por_tipo_tab = resumo(v, a, ["tipo"])
    # média mensal: viagens ÷ (motorista × mês em que ele viajou)
    motorista_mes = v.groupby("tipo").apply(lambda x: len(x[["cpf", "periodo"]].drop_duplicates()), include_groups=False)
    por_tipo_tab["por_motorista"] = por_tipo_tab["viagens"] / por_tipo_tab["tipo"].map(motorista_mes)
    st.dataframe(por_tipo_tab, hide_index=True, width="stretch", column_config={
        "tipo": "TIPO", **colunas_resumo,
        "por_motorista": st.column_config.NumberColumn("VIAGENS POR MOTORISTA/MÊS", format="%.1f",
                                                       help="Média dos meses em que o motorista viajou"),
    })

    titulo_secao("Por filial", "Ordenado pela taxa. Em filial com poucas viagens, um único acidente pesa muito na taxa: "
                               "olhe junto o número de viagens. Filial com acidente e sem viagem na base aparece sem taxa.")
    por_filial = resumo(v, a, ["filial"]).sort_values(["taxa", "acidentes"], ascending=False, na_position="first")
    maior = por_filial["taxa"].max()
    st.dataframe(por_filial, hide_index=True, width="stretch", column_config={
        "filial": "FILIAL", **colunas_resumo,
        "taxa": st.column_config.ProgressColumn(f"POR {milhar(POR_MIL)} VIAGENS", format="%.2f", min_value=0,
                                                max_value=float(maior) if pd.notna(maior) and maior else 1.0),
    })


def tabela_acidentados(a: pd.DataFrame, viagens: pd.DataFrame) -> None:
    titulo_secao("Acidentados × viagens",
                 "Cada acidente do filtro com as viagens do motorista (pelo CPF): no mês do acidente e nos 12 meses "
                 "anteriores. Agregado: o código é do motorista do veículo.")
    if a.empty:
        st.success("Nenhum acidente no filtro.")
        return
    por_cpf_mes = viagens.groupby(["cpf", "periodo"])["viagens"].sum()
    cpfs = set(por_cpf_mes.index.get_level_values(0)) - {""}

    def no_mes(cpf, p):
        return int(por_cpf_mes.get((cpf, p), 0)) if cpf in cpfs else None

    def em_12(cpf, p):
        if cpf not in cpfs:
            return None
        serie = por_cpf_mes.loc[cpf]
        return int(serie[(serie.index >= p - 12) & (serie.index < p)].sum())

    tabela = a.sort_values("data_evento", ascending=False)[
        ["data_evento", "nome", "filial", "tipo", "tipo_perda", "placa", "cpf_limpo", "periodo"]].copy()
    tabela["na_base"] = tabela["cpf_limpo"].isin(cpfs)
    tabela["viagens_mes"] = [no_mes(c, p) for c, p in zip(tabela["cpf_limpo"], tabela["periodo"])]
    tabela["viagens_12m"] = [em_12(c, p) for c, p in zip(tabela["cpf_limpo"], tabela["periodo"])]
    tabela = tabela.drop(columns=["cpf_limpo", "periodo"])
    # célula vazia vira "None" no st.dataframe: na tela, "—"; no Excel fica vazia e numérica
    tela = tabela.copy()
    tela[["nome", "tipo_perda", "placa"]] = tela[["nome", "tipo_perda", "placa"]].fillna("")
    for coluna in ("viagens_mes", "viagens_12m"):
        tela[coluna] = tela[coluna].map(lambda n: "—" if n is None or pd.isna(n) else str(int(n)))
    achados = int(tabela["na_base"].sum())
    st.caption(f"{achados} de {len(tabela)} acidentado(s) encontrados na base de viagens pelo CPF.")
    colunas = {
        "data_evento": st.column_config.DateColumn("DATA", format="DD/MM/YYYY"),
        "nome": "ACIDENTADO",
        "filial": "FILIAL",
        "tipo": "TIPO",
        "tipo_perda": "TIPO DE PERDA",
        "placa": "PLACA",
        "na_base": st.column_config.CheckboxColumn("NA BASE DE VIAGENS"),
        "viagens_mes": "VIAGENS NO MÊS",
        "viagens_12m": st.column_config.TextColumn("12 MESES ANTES", help="Viagens nos 12 meses antes do mês do acidente"),
    }
    st.dataframe(tela, hide_index=True, width="stretch", column_config=colunas)
    baixar_excel(tabela, colunas, "acidentados_x_viagens", "ind_av_xlsx_acid", "Acidentados")


def relatorio_viagens(v: pd.DataFrame, a: pd.DataFrame) -> None:
    tabela = resumo(v, a, ["periodo", "filial", "tipo"]).sort_values(["periodo", "filial", "tipo"], ascending=[False, True, True])
    if tabela.empty:
        st.info("Nenhuma viagem no filtro.")
        return
    tabela["periodo"] = tabela["periodo"].map(_rotulo_mes)
    colunas = {
        "periodo": "MÊS",
        "filial": "FILIAL",
        "tipo": "TIPO",
        "viagens": st.column_config.NumberColumn("VIAGENS", format="%d"),
        "motoristas": st.column_config.NumberColumn("MOTORISTAS", format="%d"),
        "acidentes": st.column_config.NumberColumn("ACIDENTES", format="%d"),
        "taxa": st.column_config.NumberColumn(f"POR {milhar(POR_MIL)} VIAGENS", format="%.2f"),
    }
    st.dataframe(tabela, hide_index=True, width="stretch", column_config=colunas)
    baixar_excel(tabela, colunas, "acidentes_x_viagens", "ind_av_xlsx", "Acidentes x Viagens")
