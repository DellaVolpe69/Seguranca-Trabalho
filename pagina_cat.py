"""Acidentes internos — CAT (Comunicação de Acidente de Trabalho) → segtrabalho_cat.

A CAT é emitida no eSocial quando um EMPREGADO (CLT) sofre acidente típico,
de trajeto ou doença ocupacional — mesmo sem afastamento. Por isso aqui só
entram motoristas próprios e funcionários internos; agregado e terceiro
ficam no Relatório de Acidente (pagina_acidente.py).

Registros responde às perguntas do MD: quantos acidentes no período, com e
sem afastamento, quantos afastamentos passaram de 15 dias (a partir do 16º
dia quem paga é o INSS), dias perdidos e onde se concentram (agente
causador, filial, setor, cargo). Campo vazio não vira zero.
"""

from datetime import date

import pandas as pd
import streamlit as st

import acesso
import banco
import evidencia
from comum import (
    FUNCOES_RQ05, garantir_colunas, campo_com_outro, campo_lista, campo_sim_nao, csv_excel, erro_cpf,
    fmt_cpf, guardar_msg, mostrar_erros, opcoes_existentes, para_data, para_hora, render_msg,
    so_digitos, texto, vazio,
)
from estilo import (
    barra_paginas_lateral, bloco_usuario_lateral, cabecalho_tela, linha_cartoes, titulo_secao,
)

PAGINAS = {
    "nova": "Nova CAT",
    "registros": "Registros",
}
PUBLICOS = ["Motorista próprio", "Interno administrativo", "Interno operacional"]
SEXOS = ["Masculino", "Feminino"]
TIPOS = ["Típico", "Trajeto", "Doença ocupacional"]
LATERALIDADES = ["Direito", "Esquerdo", "Ambos", "Não se aplica"]
# listas-base (o campo aceita OUTRO e passa a oferecer o que já foi usado)
PARTES_CORPO = [
    "Cabeça", "Olhos", "Face", "Pescoço", "Ombro", "Braço", "Cotovelo", "Antebraço", "Punho", "Mão",
    "Dedos da mão", "Tórax", "Costas / coluna", "Abdômen", "Quadril", "Coxa", "Joelho", "Perna",
    "Tornozelo", "Pé", "Dedos do pé", "Múltiplas partes",
]
AGENTES = [
    "Veículo (colisão / tombamento)", "Atropelamento", "Empilhadeira", "Carga / volume em movimentação",
    "Queda de mesmo nível", "Queda de altura", "Escada / plataforma / carroceria", "Ferramenta manual",
    "Máquina / equipamento", "Objeto cortante ou perfurante", "Produto químico", "Esforço excessivo / postura",
    "Animal", "Agressão / violência",
]
DIAS_INSS = 15  # até o 15º dia a empresa paga; a partir do 16º, o INSS
COLUNAS = [
    "id", "numero_cat", "nome", "cpf", "sexo", "data_nascimento", "cargo", "filial", "cod_filial",
    "publico", "setor", "data_acidente", "hora_acidente", "horario_trabalho", "local_acidente",
    "tipo_acidente", "parte_corpo", "lateralidade", "agente_causador", "descricao", "medico_nome",
    "cid", "data_atestado", "houve_afastamento", "dias_afastamento", "link_evidencia",
    "criado_em", "criado_por",
]
MSG_NOVA = "cat_msg_nova"
MSG_REG = "cat_msg_reg"


def tela(usuario: dict) -> None:
    cabecalho_tela(
        "🩹 ACIDENTES INTERNOS (CAT)",
        "Comunicação de Acidente de Trabalho: motoristas próprios e funcionários internos (CLT).",
        "cat",
    )
    pagina = barra_paginas_lateral("cat_pagina", PAGINAS, "cat")
    bloco_usuario_lateral(usuario)
    df = carregar()
    if pagina == "nova":
        nova(df, usuario)
    else:
        registros(df)


def carregar() -> pd.DataFrame:
    try:
        df = acesso.listar(banco.CAT)
    except Exception as erro:
        st.error(f"Não foi possível ler {banco.CAT}: {erro}")
        df = pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=COLUNAS)
    df = garantir_colunas(df, COLUNAS)
    for coluna in ("data_acidente", "data_nascimento", "data_atestado"):
        df[coluna] = df[coluna].map(para_data)
    df["hora_acidente"] = df["hora_acidente"].map(para_hora)
    df["dias_afastamento"] = pd.to_numeric(df["dias_afastamento"], errors="coerce")
    # True / False / None de verdade (o pandas pode trazer numpy.bool_ ou NaN)
    df["houve_afastamento"] = df["houve_afastamento"].map(lambda a: None if vazio(a) else bool(a))
    return df


def opcoes(df: pd.DataFrame, coluna: str, base: list) -> list:
    return sorted(set(base) | set(opcoes_existentes(df, coluna)), key=str.casefold)


# ---------------------------------------------------------------------
# Campos (os mesmos no cadastro e na edição) — na ordem do modelo da CAT
# ---------------------------------------------------------------------

def campos_cat(df: pd.DataFrame, k: str, atual: dict) -> dict:
    titulo_secao("1. Colaborador acidentado")
    c1, c2, c3, c4 = st.columns([2, 1.1, 0.9, 1])
    with c1:
        nome = st.text_input("NOME COMPLETO", value=texto(atual.get("nome")) or "", key=f"{k}_nome")
    with c2:
        cpf = st.text_input("CPF", value=fmt_cpf(atual.get("cpf")) if texto(atual.get("cpf")) else "",
                            key=f"{k}_cpf", placeholder="000.000.000-00")
    with c3:
        sexo = campo_lista("SEXO", SEXOS, f"{k}_sexo", atual.get("sexo"))
    with c4:
        # sem min_value o Streamlit só deixa escolher os últimos 10 anos
        nascimento = st.date_input("DATA DE NASCIMENTO", value=atual.get("data_nascimento"),
                                   min_value=date(1930, 1, 1), max_value=date.today(),
                                   format="DD/MM/YYYY", key=f"{k}_nasc")
    c5, c6, c7, c8 = st.columns([1.4, 1.2, 1.4, 1.2])
    with c5:
        cargo = campo_com_outro("CARGO / FUNÇÃO", opcoes(df, "cargo", FUNCOES_RQ05), f"{k}_cargo",
                                atual.get("cargo"))
    with c6:
        setor = campo_com_outro("SETOR", opcoes_existentes(df, "setor"), f"{k}_setor", atual.get("setor"))
    with c7:
        cod_filial, filial = acesso.campo_filial("FILIAL", f"{k}_filial", atual.get("cod_filial"))
    with c8:
        publico = campo_lista("PÚBLICO", PUBLICOS, f"{k}_publico", atual.get("publico"))

    titulo_secao("2. Acidente")
    c9, c10, c11, c12, c13 = st.columns([1.1, 1, 0.8, 1.2, 1.2])
    with c9:
        numero_cat = st.text_input("Nº DA CAT (eSocial)", value=texto(atual.get("numero_cat")) or "",
                                   key=f"{k}_numero", help="Número da CAT ou do recibo no eSocial.")
    with c10:
        data_acidente = st.date_input("DATA DO ACIDENTE", value=atual.get("data_acidente") or date.today(),
                                      max_value=date.today(), format="DD/MM/YYYY", key=f"{k}_data")
    with c11:
        hora = st.time_input("HORA", value=atual.get("hora_acidente"), step=300, key=f"{k}_hora")
    with c12:
        horario_trabalho = st.text_input("HORÁRIO DE TRABALHO", value=texto(atual.get("horario_trabalho")) or "",
                                         key=f"{k}_horario", placeholder="Ex.: 08:00 às 17:48")
    with c13:
        tipo = campo_lista("TIPO DE ACIDENTE", TIPOS, f"{k}_tipo", atual.get("tipo_acidente"))
    local = st.text_input("LOCAL DO ACIDENTE (completo e com CEP)", value=texto(atual.get("local_acidente")) or "",
                          key=f"{k}_local")
    c14, c15, c16 = st.columns([1.4, 1, 1.8])
    with c14:
        parte = campo_com_outro("PARTE DO CORPO ATINGIDA", opcoes(df, "parte_corpo", PARTES_CORPO),
                                f"{k}_parte", atual.get("parte_corpo"))
    with c15:
        lateralidade = campo_lista("LATERALIDADE", LATERALIDADES, f"{k}_lado", atual.get("lateralidade"))
    with c16:
        agente = campo_com_outro("AGENTE CAUSADOR", opcoes(df, "agente_causador", AGENTES), f"{k}_agente",
                                 atual.get("agente_causador"))
    descricao = st.text_area("DESCRIÇÃO DA SITUAÇÃO GERADORA DO ACIDENTE",
                             value=texto(atual.get("descricao")) or "", key=f"{k}_descricao", height=90)

    titulo_secao("3. Atestado e afastamento",
                 f"Afastamento acima de {DIAS_INSS} dias passa a ser pago pelo INSS.")
    c17, c18, c19, c20, c21 = st.columns([1.8, 0.8, 1, 1, 1])
    with c17:
        medico = st.text_input("MÉDICO (nome, CRM e UF)", value=texto(atual.get("medico_nome")) or "",
                               key=f"{k}_medico")
    with c18:
        cid = st.text_input("CID", value=texto(atual.get("cid")) or "", key=f"{k}_cid", placeholder="S62.6")
    with c19:
        data_atestado = st.date_input("DATA DO ATESTADO", value=atual.get("data_atestado"),
                                      format="DD/MM/YYYY", key=f"{k}_atestado")
    with c20:
        afastamento = campo_sim_nao("HOUVE AFASTAMENTO?", f"{k}_afast", atual.get("houve_afastamento"))
    with c21:
        dias_atual = atual.get("dias_afastamento")
        dias = st.number_input(
            "DIAS DE AFASTAMENTO", min_value=0, step=1, key=f"{k}_dias",
            value=None if dias_atual is None or pd.isna(dias_atual) else int(dias_atual),
            disabled=afastamento is not True,
            help="Só com afastamento = Sim. Em branco = ainda não se sabe (não conta como zero).",
        )

    titulo_secao("4. Evidência")
    link_atual = texto(atual.get("link_evidencia"))
    if link_atual:
        evidencia.mostrar(link_atual)
    arquivo = evidencia.campo("SUBSTITUIR CAT" if link_atual else "ANEXAR A CAT (PDF ou foto)", f"{k}_arquivo")

    return {
        "numero_cat": texto(numero_cat),
        "nome": texto(nome),
        "cpf": so_digitos(cpf),
        "sexo": sexo,
        "data_nascimento": nascimento,
        "cargo": cargo,
        "setor": setor,
        "filial": filial,
        "cod_filial": cod_filial,
        "publico": publico,
        "data_acidente": data_acidente,
        "hora_acidente": hora,
        "horario_trabalho": texto(horario_trabalho),
        "local_acidente": texto(local),
        "tipo_acidente": tipo,
        "parte_corpo": parte,
        "lateralidade": lateralidade,
        "agente_causador": agente,
        "descricao": texto(descricao),
        "medico_nome": texto(medico),
        "cid": (texto(cid) or "").upper() or None,
        "data_atestado": data_atestado,
        "houve_afastamento": afastamento,
        "dias_afastamento": int(dias) if afastamento is True and dias is not None else None,
        "link_evidencia": link_atual,
        "_arquivo": arquivo,  # não é coluna: sai antes de gravar
    }


def validar(d: dict, df: pd.DataFrame, rid=None) -> list:
    erros = []
    if not d["nome"]:
        erros.append("Informe o nome do colaborador.")
    if erro_cpf(d["cpf"]):
        erros.append(erro_cpf(d["cpf"]))
    if not d["filial"]:
        erros.append("Informe a filial.")
    if not d["publico"]:
        erros.append("Informe o público (motorista próprio ou interno).")
    if not d["data_acidente"]:
        erros.append("Informe a data do acidente.")
    if not d["tipo_acidente"]:
        erros.append("Informe o tipo de acidente.")
    if not d["descricao"]:
        erros.append("Descreva a situação que gerou o acidente.")
    if d["data_nascimento"] and d["data_acidente"] and d["data_nascimento"] >= d["data_acidente"]:
        erros.append("A data de nascimento precisa ser anterior à data do acidente.")
    if d["data_atestado"] and d["data_acidente"] and d["data_atestado"] < d["data_acidente"]:
        erros.append("A data do atestado não pode ser anterior à data do acidente.")
    if d["numero_cat"] and not df.empty:
        outros = df if rid is None else df[df["id"] != rid]
        if (outros["numero_cat"].map(texto) == d["numero_cat"]).any():
            erros.append(f"A CAT nº {d['numero_cat']} já está lançada.")
    return erros


def gravar(dados: dict, salvar) -> tuple:
    """Sobe a CAT anexada (nome legível: NOME-DD-MM-AAAA) e chama salvar(caminho)."""
    arquivo = dados.pop("_arquivo")
    nome = f"{evidencia.nome_legivel(dados['nome'])}-{dados['data_acidente']:%d-%m-%Y}"
    return evidencia.gravar(arquivo, "cat", lambda caminho: salvar(
        {**dados, "link_evidencia": caminho or dados["link_evidencia"]}), nome)


# ---------------------------------------------------------------------
# Nova CAT
# ---------------------------------------------------------------------

def nova(df: pd.DataFrame, usuario: dict) -> None:
    v = st.session_state.setdefault("cat_versao", 0)
    render_msg(MSG_NOVA)
    dados = campos_cat(df, f"cat_nova_{v}", {})

    if st.button("💾 Salvar CAT", type="primary", key=f"cat_salvar_{v}"):
        erros = validar(dados, df)
        if erros:
            mostrar_erros(erros)
            return
        dados["criado_por"] = usuario["email"]
        ok, msg = gravar(dados, lambda linha: banco.inserir(banco.CAT, [linha]))
        if not ok:
            st.error(msg)
            return
        guardar_msg(MSG_NOVA, "success", f"CAT de {dados['nome']} salva.")
        st.session_state["cat_versao"] += 1
        st.rerun()


# ---------------------------------------------------------------------
# Registros: indicadores, consulta, edição e exclusão
# ---------------------------------------------------------------------

def registros(df: pd.DataFrame) -> None:
    render_msg(MSG_REG)
    if df.empty:
        st.info("Nenhuma CAT lançada ainda.")
        return

    f1, f2, f3, f4, f5, f6 = st.columns([1.3, 1.3, 1.1, 1, 0.9, 0.9])
    with f1:
        filiais = st.multiselect("FILIAL", opcoes_existentes(df, "filial"), key="cat_f_filial")
    with f2:
        publicos = st.multiselect("PÚBLICO", PUBLICOS, key="cat_f_publico")
    with f3:
        tipos = st.multiselect("TIPO", TIPOS, key="cat_f_tipo")
    with f4:
        afast = st.multiselect("AFASTAMENTO", ["Com afastamento", "Sem afastamento", "Não informado"],
                               key="cat_f_afast")
    with f5:
        de = st.date_input("DE", value=None, format="DD/MM/YYYY", key="cat_f_de")
    with f6:
        ate = st.date_input("ATÉ", value=None, format="DD/MM/YYYY", key="cat_f_ate")
    busca = st.text_input("BUSCAR NOME, CPF OU Nº DA CAT", key="cat_f_busca")

    f = df.copy()
    f["afastamento"] = f["houve_afastamento"].map(
        lambda a: "Com afastamento" if a is True else "Sem afastamento" if a is False else "Não informado")
    if filiais:
        f = f[f["filial"].isin(filiais)]
    if publicos:
        f = f[f["publico"].isin(publicos)]
    if tipos:
        f = f[f["tipo_acidente"].isin(tipos)]
    if afast:
        f = f[f["afastamento"].isin(afast)]
    if de:
        f = f[f["data_acidente"] >= de]
    if ate:
        f = f[f["data_acidente"] <= ate]
    if texto(busca):
        termo, digitos = texto(busca).lower(), so_digitos(busca)
        achou = f["nome"].str.lower().str.contains(termo, regex=False, na=False)
        achou |= f["numero_cat"].astype(str).str.lower().str.contains(termo, regex=False, na=False)
        if digitos:
            achou |= f["cpf"].astype(str).str.contains(digitos, regex=False, na=False)
        f = f[achou]

    total = len(f)
    com = int((f["afastamento"] == "Com afastamento").sum())
    sem = int((f["afastamento"] == "Sem afastamento").sum())
    acima = int((f["dias_afastamento"] > DIAS_INSS).sum())
    dias = f["dias_afastamento"].dropna()
    com_sem_dias = int(((f["afastamento"] == "Com afastamento") & f["dias_afastamento"].isna()).sum())
    linha_cartoes([
        ("Acidentes", f"{total}", "neutro", "CATs no filtro"),
        ("Com afastamento", f"{com}", "laranja" if com else "neutro",
         f"{com / total:.0%} do total" if total else ""),
        ("Sem afastamento", f"{sem}", "verde" if sem else "neutro", ""),
        (f"Acima de {DIAS_INSS} dias", f"{acima}", "vermelho" if acima else "neutro", "pagos pelo INSS"),
        ("Dias perdidos", f"{int(dias.sum())}", "vermelho" if dias.sum() else "neutro",
         f"{com_sem_dias} afastamento(s) sem dias informados" if com_sem_dias else "soma dos afastamentos"),
    ])
    concentracao(f)

    tabela = f[[
        "id", "data_acidente", "numero_cat", "nome", "cpf", "publico", "filial", "setor", "cargo",
        "tipo_acidente", "agente_causador", "parte_corpo", "afastamento", "dias_afastamento", "cid",
    ]].copy()
    tabela["cpf"] = tabela["cpf"].map(fmt_cpf)
    textos = ["numero_cat", "nome", "publico", "filial", "setor", "cargo", "tipo_acidente",
              "agente_causador", "parte_corpo", "cid"]
    tabela[textos] = tabela[textos].fillna("")

    versao_tabela = st.session_state.setdefault("cat_tabela_v", 0)
    evento = st.dataframe(
        tabela,
        key=f"cat_tabela_{versao_tabela}",
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        column_config={
            "id": st.column_config.NumberColumn("ID", format="%d", width="small"),
            "data_acidente": st.column_config.DateColumn("DATA", format="DD/MM/YYYY"),
            "numero_cat": "Nº CAT",
            "nome": "COLABORADOR",
            "cpf": "CPF",
            "publico": "PÚBLICO",
            "filial": "FILIAL",
            "setor": "SETOR",
            "cargo": "CARGO",
            "tipo_acidente": "TIPO",
            "agente_causador": "AGENTE CAUSADOR",
            "parte_corpo": "PARTE DO CORPO",
            "afastamento": "AFASTAMENTO",
            "dias_afastamento": st.column_config.NumberColumn("DIAS", format="%d"),
            "cid": "CID",
        },
    )
    st.download_button("⬇️ Baixar CSV", csv_excel(tabela), file_name="cat_acidentes_internos.csv",
                       mime="text/csv", key="cat_csv")

    linhas = evento.selection.rows
    if not linhas:
        st.caption("Selecione uma linha na tabela para editar ou excluir.")
        return
    st.divider()
    editar(f.iloc[linhas[0]], df)


def concentracao(f: pd.DataFrame) -> None:
    """Onde os acidentes se concentram: os 3 mais frequentes de cada recorte."""
    if f.empty:
        return
    titulo_secao("Onde mais acontece", "Os 3 mais frequentes no filtro.")
    recortes = [("Agente causador", "agente_causador"), ("Filial", "filial"),
                ("Setor", "setor"), ("Cargo", "cargo")]
    colunas = st.columns(len(recortes))
    for coluna_tela, (rotulo, coluna) in zip(colunas, recortes):
        contagem = f[coluna].map(texto).dropna().value_counts().head(3)
        linhas = "  \n".join(f"{n}× {valor}" for valor, n in contagem.items()) or "—"
        coluna_tela.caption(f"**{rotulo.upper()}**  \n{linhas}")
    st.write("")


def editar(reg: pd.Series, df: pd.DataFrame) -> None:
    rid = int(reg["id"])
    k = f"cat_ed_{rid}_{st.session_state['cat_tabela_v']}"
    titulo_secao(f"Editar CAT #{rid}")
    dados = campos_cat(df, k, reg.to_dict())

    confirmar = st.checkbox("Quero excluir esta CAT", key=f"{k}_confirma")
    b1, b2, _ = st.columns([1.4, 1, 4])
    salvar = b1.button("💾 Salvar alterações", type="primary", key=f"{k}_salvar")
    apagar = b2.button("🗑️ Excluir", key=f"{k}_excluir", disabled=not confirmar)

    if salvar:
        erros = validar(dados, df, rid)
        if erros:
            mostrar_erros(erros)
            return
        concluir(gravar(dados, lambda linha: banco.atualizar(banco.CAT, rid, linha)))
    if apagar:
        concluir(banco.excluir(banco.CAT, rid))


def concluir(resultado: tuple) -> None:
    ok, msg = resultado
    if not ok:
        st.error(msg)
        return
    guardar_msg(MSG_REG, "success", msg)
    st.session_state["cat_tabela_v"] += 1  # limpa a seleção da tabela
    st.rerun()
