"""Treinamentos — RQ 10 (Lista de Presença) → segtrabalho_treinamento.

Uma lista de presença = um treinamento, numa data e filial, com N
participantes, lançados um a um em campos normais (sem grade). Cada
participante vira uma linha na tabela.

Nenhum formulário usa st.form: com clear_on_submit os campos seriam apagados
também quando o insert falhasse. As chaves dos campos levam um número de
versão, que só avança depois de gravar com sucesso — é isso que limpa a tela.
"""

import io
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone

import openpyxl
import pandas as pd
import qrcode
import streamlit as st
from openpyxl.worksheet.datavalidation import DataValidation

import acesso
import banco
import evidencia
from comum import (
    garantir_colunas, FUNCOES_RQ05, VAZIO, campo_com_outro, campo_lista, csv_excel, erro_cpf, fmt_cpf,
    fmt_data, guardar_msg, mostrar_erros, opcoes_existentes, para_data,
    render_msg, so_digitos, texto,
)
from estilo import (
    barra_paginas_lateral, bloco_usuario_lateral, cabecalho_tela, linha_cartoes, titulo_secao,
)

PAGINAS = {
    "nova": "Nova lista de presença",
    "qr": "Presença por QR Code",
    "registros": "Registros",
}
VINCULOS = ["Frota", "Agregado", "Terceiro", "Interno"]
# "Avaliação do treinamento" da RQ 10: as 3 carinhas 😊 😐 ☹️ (não é nota)
AVALIACOES = ["Satisfeito", "Normal", "Insatisfeito"]
COLUNAS = [
    "id", "nome", "cpf", "data_treinamento", "filial", "funcao", "setor",
    "treinamento", "instrutor", "vinculo", "data_validade", "avaliacao",
    "link_evidencia", "link_assinatura", "cod_filial", "sessao_id", "criado_em", "criado_por",
]
# Planilha de participantes (paliativo enquanto a leitura da RQ 10 escaneada está em stand-by)
COLUNAS_PLANILHA = ["NOME", "CPF", "FUNÇÃO", "SETOR", "VÍNCULO", "AVALIAÇÃO"]
MSG_NOVA = "tr_msg_nova"
MSG_REG = "tr_msg_reg"
MSG_QR = "tr_msg_qr"


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
    elif pagina == "qr":
        lista_qr(df, usuario)
    else:
        registros(df)


def carregar() -> pd.DataFrame:
    try:
        df = acesso.listar(banco.TREINAMENTO)
    except Exception as erro:
        st.error(f"Não foi possível ler {banco.TREINAMENTO}: {erro}")
        df = pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=COLUNAS)
    df = garantir_colunas(df, COLUNAS)
    for coluna in ("data_treinamento", "data_validade"):
        df[coluna] = df[coluna].map(para_data)
    return df


def situacao_validade(validade, hoje: date) -> str:
    if validade is None:
        return "Sem validade"
    if validade < hoje:
        return "Vencido"
    if validade < hoje + timedelta(days=7):
        return "Vence em 7 dias"
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
    treinamento, data_tr, cod_filial, filial = campos_treinamento(df, f"tr_{v}")

    c4, c5, c6 = st.columns([1, 1.5, 2])
    with c4:
        validade = campo_validade(f"tr_validade_{v}")
    with c5:
        instrutor = campo_instrutor(df, f"tr_instrutor_{v}")
    with c6:
        arquivo = evidencia.campo("RQ 10 ASSINADA (PDF ou foto)", f"tr_arquivo_{v}")

    titulo_secao(
        "2. Participantes",
        "Importe uma planilha Excel com todos de uma vez, ou preencha os dados de uma pessoa "
        "e clique em ➕ Adicionar participante.",
    )
    if treinamento and data_tr and filial:
        importar_planilha(df, lista, v)
    else:
        st.caption("📥 Para importar os participantes de uma planilha Excel, "
                   "preencha antes o treinamento, a data e a filial.")
    rascunho = campos_participante(df, lista, v)
    lista_participantes(lista, v)

    total = len(lista)
    rotulo = f"💾 Salvar lista de presença ({total} participante{'' if total == 1 else 's'})"
    if st.button(rotulo, type="primary", key=f"tr_salvar_{v}"):
        salvar_lista(df, usuario, treinamento, data_tr, cod_filial, filial, validade, instrutor,
                     arquivo, lista, rascunho)


def campos_treinamento(df: pd.DataFrame, k: str) -> tuple:
    """Treinamento, data e filial — os mesmos na lista lançada e na lista por QR Code."""
    c1, c2, c3 = st.columns([2, 1, 1.5])
    with c1:
        treinamento = campo_com_outro(
            "TREINAMENTO", opcoes_existentes(df, "treinamento"), f"{k}_trein",
            ajuda="Ex.: NR-35 Trabalho em Altura, Integração de Agregados, Direção Defensiva",
        )
    with c2:
        data_tr = st.date_input("DATA DO TREINAMENTO", value=date.today(), format="DD/MM/YYYY", key=f"{k}_data")
    with c3:
        cod_filial, filial = acesso.campo_filial("FILIAL", f"{k}_filial")
    return treinamento, data_tr, cod_filial, filial


def campo_instrutor(df: pd.DataFrame, key: str, valor_atual=None):
    """Lista com os instrutores já usados: o mesmo nome sempre igual, para medir quem mais treina."""
    return campo_com_outro(
        "INSTRUTOR", opcoes_existentes(df, "instrutor"), key, valor_atual,
        ajuda="Quem aplicou o treinamento. Se não estiver na lista, escolha OUTRO e digite o nome.",
    )


def campo_validade(key: str):
    return st.date_input(
        "VALIDADE DO TREINAMENTO", value=None, format="DD/MM/YYYY", key=key,
        help="Deixe em branco se o treinamento não vence (DDS, campanha).",
    )


def erros_treinamento(treinamento, data_tr, filial, validade) -> list:
    erros = []
    if not treinamento:
        erros.append("Informe o treinamento.")
    if not data_tr:
        erros.append("Informe a data do treinamento.")
    if not filial:
        erros.append("Informe a filial.")
    if validade and data_tr and validade < data_tr:
        erros.append("A validade não pode ser anterior à data do treinamento.")
    return erros


def importar_planilha(df: pd.DataFrame, lista: list, v: int) -> None:
    """Upload do xlsx: quem passa na validação entra na lista abaixo (dá para conferir e remover)."""
    iv = st.session_state.setdefault("tr_iv", 0)  # avança a cada importação: limpa o campo do arquivo
    with st.container(border=True):
        st.markdown("**📥 Importar participantes de uma planilha Excel**")
        c1, c2 = st.columns([3, 1])
        with c1:
            arquivo = st.file_uploader("PLANILHA (.xlsx)", type=["xlsx"], key=f"tr_xlsx_{v}_{iv}")
        with c2:
            st.write("")
            st.download_button(
                "⬇️ Baixar modelo", modelo_planilha(), file_name="modelo_participantes_rq10.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"tr_modelo_{v}",
            )
        if arquivo:
            novos, erros = ler_planilha(arquivo, df, lista)
            lista.extend(novos)
            st.session_state[f"tr_imp_{v}"] = (len(novos), erros)
            st.session_state["tr_iv"] += 1
            st.rerun()

        importados, erros = st.session_state.get(f"tr_imp_{v}", (0, []))
        if importados:
            st.success(f"{importados} participante{'' if importados == 1 else 's'} da planilha "
                       "entraram na lista abaixo. Confira antes de salvar.")
        if erros:
            st.warning(f"{len(erros)} linha{'' if len(erros) == 1 else 's'} da planilha não "
                       "entraram — corrija e importe de novo, ou lance à mão:\n\n"
                       + "\n".join(f"- {e}" for e in erros))


def modelo_planilha() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Participantes"
    ws.append(COLUNAS_PLANILHA)
    for coluna, largura in zip("ABCDEF", (40, 16, 28, 20, 14, 16)):
        ws.column_dimensions[coluna].width = largura
    for linha in range(2, 202):
        ws.cell(linha, 2).number_format = "@"  # CPF como texto: o Excel não come o zero da frente
    for coluna, opcoes in (("E", VINCULOS), ("F", AVALIACOES)):
        lista_suspensa = DataValidation(type="list", formula1=f'"{",".join(opcoes)}"', allow_blank=True)
        lista_suspensa.add(f"{coluna}2:{coluna}201")
        ws.add_data_validation(lista_suspensa)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def chave(valor) -> str:
    """'Função ' -> 'FUNCAO': compara sem acento, caixa e espaços."""
    s = unicodedata.normalize("NFD", texto(valor) or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def casar(valor, opcoes: list):
    """Valor como já existe nas opções ('motorista' -> 'Motorista'); senão, como veio."""
    por_chave = {chave(o): o for o in opcoes}
    return por_chave.get(chave(valor), texto(valor))


def ler_planilha(arquivo, df: pd.DataFrame, lista: list) -> tuple:
    """(participantes válidos, erros por linha). Primeira linha = cabeçalho do modelo."""
    try:
        bruto = pd.read_excel(arquivo, dtype=str)  # texto: CPF não perde o zero da frente
    except Exception as erro:
        return [], [f"Não foi possível ler a planilha: {erro}"]
    bruto.columns = ["NOME" if chave(c).startswith("NOME") else chave(c) for c in bruto.columns]
    faltando = [c for c in ("NOME", "CPF") if c not in bruto]
    if faltando:
        return [], [f"A primeira linha precisa ter a coluna {' e '.join(faltando)}. Use o modelo."]

    ja_na_lista = {p["cpf"] for p in lista}
    funcoes, setores = opcoes_funcao(df), opcoes_existentes(df, "setor")
    novos, erros = [], []
    for n, linha in enumerate(bruto.to_dict("records"), start=2):  # n = linha no Excel
        nome = texto(linha.get("NOME"))
        cpf_bruto = re.sub(r"\.0$", "", texto(linha.get("CPF")) or "")
        if not nome and not cpf_bruto:
            continue  # linha em branco
        cpf = so_digitos(cpf_bruto)
        if cpf_bruto.isdigit() and 9 <= len(cpf) < 11:
            cpf = cpf.zfill(11)  # CPF digitado como número: o Excel tirou o zero da frente

        problemas = []
        if not nome:
            problemas.append("sem nome")
        if erro_cpf(cpf):
            problemas.append(erro_cpf(cpf))
        elif cpf in ja_na_lista:
            problemas.append("pessoa repetida (já está na lista)")
        vinculo, avaliacao = casar(linha.get("VINCULO"), VINCULOS), casar(linha.get("AVALIACAO"), AVALIACOES)
        if vinculo and vinculo not in VINCULOS:
            problemas.append(f"vínculo “{vinculo}” não é da lista ({', '.join(VINCULOS)})")
        if avaliacao and avaliacao not in AVALIACOES:
            problemas.append(f"avaliação “{avaliacao}” não é da lista ({', '.join(AVALIACOES)})")

        if problemas:
            erros.append(f"Linha {n} ({nome or 'sem nome'}): {'; '.join(problemas)}")
            continue
        ja_na_lista.add(cpf)
        novos.append({
            "nome": nome, "cpf": cpf,
            "funcao": casar(linha.get("FUNCAO"), funcoes), "setor": casar(linha.get("SETOR"), setores),
            "vinculo": vinculo, "avaliacao": avaliacao,
        })
    if not novos and not erros:
        erros.append("A planilha não tem nenhum participante preenchido.")
    return novos, erros


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
        avaliacao = campo_lista("AVALIAÇÃO DO TREINAMENTO", AVALIACOES, f"{k}_aval")

    if st.button("➕ Adicionar participante", key=f"{k}_add"):
        cpf_limpo = so_digitos(cpf)
        erros = []
        if not texto(nome):
            erros.append("Informe o nome.")
        if erro_cpf(cpf_limpo):
            erros.append(erro_cpf(cpf_limpo))
        elif any(p["cpf"] == cpf_limpo for p in lista):
            erros.append("Essa pessoa já está na lista.")
        if erros:
            mostrar_erros(erros, "Corrija antes de adicionar:")
        else:
            lista.append({
                "nome": texto(nome), "cpf": cpf_limpo, "funcao": funcao, "setor": setor,
                "vinculo": vinculo, "avaliacao": avaliacao,
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
            detalhes = " · ".join([
                fmt_cpf(p["cpf"]), p["funcao"] or VAZIO, p["setor"] or VAZIO,
                p["vinculo"] or VAZIO, f"avaliação: {p['avaliacao'] or VAZIO}",
            ])
            texto_col, botao_col = st.columns([9, 1])
            texto_col.markdown(f"**{i + 1}. {p['nome']}**  \n{detalhes}")
            # on_click roda antes do rerun: o índice ainda é o desta linha
            botao_col.button("🗑️", key=f"tr_rm_{v}_{i}", help="Remover da lista",
                             on_click=lista.pop, args=(i,))


def salvar_lista(df, usuario, treinamento, data_tr, cod_filial, filial, validade, instrutor,
                 arquivo, lista, rascunho) -> None:
    erros = erros_treinamento(treinamento, data_tr, filial, validade)
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
        "cod_filial": cod_filial,
        "treinamento": treinamento,
        "instrutor": instrutor,
        "data_validade": validade,
        "link_evidencia": None,
        "criado_por": usuario["email"],
    } for p in lista]

    def salvar(caminho):
        for linha in linhas:  # o mesmo arquivo vale para todos os participantes
            linha["link_evidencia"] = caminho
        return banco.inserir(banco.TREINAMENTO, linhas)

    ok, msg = evidencia.gravar(arquivo, "treinamento", salvar)
    if not ok:
        st.error(msg)  # nada foi limpo: a lista continua na tela
        return
    guardar_msg(MSG_NOVA, "success", f"Lista de presença salva — {msg}")
    st.session_state.pop(f"tr_lista_{st.session_state['tr_versao']}", None)
    st.session_state["tr_versao"] += 1
    st.session_state["tr_pv"] += 1
    st.rerun()


# ---------------------------------------------------------------------
# Presença por QR Code
# ---------------------------------------------------------------------
# O TST abre a lista (treinamento, data, filial, validade) e mostra o QR.
# Cada participante se registra no próprio celular (pagina_presenca.py, sem
# login) e já grava no banco. O QR funciona até o TST encerrar a lista.

def lista_qr(df: pd.DataFrame, usuario: dict) -> None:
    render_msg(MSG_QR)
    try:
        abertas = listas_abertas()
    except Exception as erro:
        st.error(f"Não foi possível ler {banco.SESSAO}: {erro}")
        return
    acompanhando = next((s for s in abertas if s["id"] == st.session_state.get("tr_qr_sessao")), None)
    if acompanhando:
        acompanhar(acompanhando)
    else:
        abrir_lista(df, usuario)
        mostrar_abertas(abertas)


def listas_abertas() -> list:
    """Listas ainda não encerradas, das filiais do usuário."""
    abertas = banco.buscar(banco.SESSAO, encerrada_em=None)
    if acesso.perfil()["admin"]:
        return abertas
    return [s for s in abertas if s["cod_filial"] in acesso.perfil()["codigos"]]


def abrir_lista(df: pd.DataFrame, usuario: dict) -> None:
    v = st.session_state.setdefault("tr_qr_v", 0)
    titulo_secao("1. Treinamento", "Preencha e gere o QR Code. Os participantes escaneiam e "
                                   "se registram no próprio celular.")
    treinamento, data_tr, cod_filial, filial = campos_treinamento(df, f"tr_qr_{v}")
    c1, c2, _ = st.columns([1, 1.5, 2])
    with c1:
        validade = campo_validade(f"tr_qr_{v}_validade")
    with c2:
        instrutor = campo_instrutor(df, f"tr_qr_{v}_instrutor")

    if not st.button("📱 Gerar QR Code da lista", type="primary", key=f"tr_qr_{v}_gerar"):
        return
    erros = erros_treinamento(treinamento, data_tr, filial, validade)
    if erros:
        mostrar_erros(erros)
        return
    codigo = secrets.token_urlsafe(16)  # vai no link: aleatório, impossível de adivinhar
    ok, msg = banco.inserir(banco.SESSAO, [{
        "codigo": codigo, "treinamento": treinamento, "data_treinamento": data_tr,
        "filial": filial, "cod_filial": cod_filial, "data_validade": validade,
        "instrutor": instrutor, "criado_por": usuario["email"],
    }])
    if not ok:
        st.error(msg)
        return
    st.session_state["tr_qr_sessao"] = banco.buscar(banco.SESSAO, codigo=codigo)[0]["id"]
    st.session_state["tr_qr_v"] += 1
    st.rerun()


def mostrar_abertas(abertas: list) -> None:
    if not abertas:
        return
    titulo_secao("Listas abertas", "O QR Code delas ainda funciona. Acompanhe ou encerre.")
    with st.container(border=True):
        for s in abertas:
            texto_col, botao_col = st.columns([6, 1.4])
            texto_col.markdown(
                f"**{s['treinamento']}**  \n{fmt_data(s['data_treinamento'])} · {s['filial']} · "
                f"aberta por {s['criado_por']}"
            )
            botao_col.button("Acompanhar", key=f"tr_qr_abrir_{s['id']}",
                             on_click=st.session_state.__setitem__, args=("tr_qr_sessao", s["id"]))


def link_presenca(codigo: str) -> str:
    # APP_URL nos secrets; se não houver, o endereço de volta do login Azure é o do app
    base = banco.secret("APP_URL") or banco.secret("AZURE_REDIRECT_URI") or ""
    return f"{str(base).rstrip('/')}/?presenca={codigo}"


def imagem_qr(link: str) -> bytes:
    buffer = io.BytesIO()
    qrcode.make(link, box_size=10, border=2).save(buffer, format="PNG")
    return buffer.getvalue()


def acompanhar(sessao: dict) -> None:
    titulo_secao(
        f"📱 {sessao['treinamento']}",
        f"{fmt_data(sessao['data_treinamento'])} · {sessao['filial']} · validade: "
        f"{fmt_data(sessao['data_validade']) or 'sem validade'} · instrutor: "
        f"{sessao.get('instrutor') or VAZIO} · aberta por {sessao['criado_por']}",
    )
    link = link_presenca(sessao["codigo"])
    c1, c2 = st.columns([1, 1.6])
    with c1:
        st.image(imagem_qr(link), width=320)
        st.caption("Mostre na tela ou projete. Quem não conseguir escanear pode abrir o link:")
        st.code(link, language=None, wrap_lines=True)
    with c2:
        participantes_ao_vivo(sessao["id"])

    titulo_secao("Encerrar a lista", "Depois de encerrar, o QR Code para de funcionar e a lista "
                                     "vai para Registros.")
    k = f"tr_qr_fim_{sessao['id']}"
    arquivo = evidencia.campo("RQ 10 ASSINADA (PDF ou foto)", f"{k}_arquivo",
                              ajuda="A folha assinada continua sendo a evidência da presença.")
    confirmar = st.checkbox("Todos já se registraram — quero encerrar a lista", key=f"{k}_confirma")
    b1, b2, _ = st.columns([1.3, 1.6, 3])
    if b1.button("🔒 Encerrar lista", type="primary", key=f"{k}_encerrar", disabled=not confirmar):
        encerrar(sessao, arquivo)
    b2.button("⬅️ Voltar (a lista continua aberta)", key=f"{k}_voltar",
              on_click=st.session_state.pop, args=("tr_qr_sessao", None))


@st.fragment(run_every=5)
def participantes_ao_vivo(sessao_id: int) -> None:
    """Quem já se registrou. Roda de novo sozinho a cada 5 s (só este bloco, não a tela)."""
    try:
        linhas = banco.buscar(banco.TREINAMENTO, sessao_id=sessao_id)
    except Exception as erro:
        st.error(f"Não foi possível ler os participantes: {erro}")
        return
    st.markdown(f"**{len(linhas)} participante{'' if len(linhas) == 1 else 's'} registrado"
                f"{'' if len(linhas) == 1 else 's'}** · atualiza sozinho a cada 5 segundos")
    if not linhas:
        st.caption("Ninguém se registrou ainda.")
        return
    tabela = garantir_colunas(pd.DataFrame(linhas), ["link_assinatura"])
    tabela["assinou"] = tabela["link_assinatura"].map(lambda l: "✍️ Sim" if texto(l) else "—")
    tabela = tabela[["nome", "cpf", "funcao", "vinculo", "avaliacao", "assinou"]]
    tabela["cpf"] = tabela["cpf"].map(fmt_cpf)
    st.dataframe(tabela.fillna(""), hide_index=True, width="stretch", column_config={
        "nome": "NOME", "cpf": "CPF", "funcao": "FUNÇÃO", "vinculo": "VÍNCULO", "avaliacao": "AVALIAÇÃO",
        "assinou": "ASSINOU",
    })

    rv = st.session_state.setdefault("tr_qr_rm_v", 0)  # avança a cada remoção: limpa a escolha
    por_id = {l["id"]: f"{l['nome']} · {fmt_cpf(l['cpf'])}" for l in linhas}
    c1, c2 = st.columns([3, 1])
    with c1:
        escolhido = st.selectbox("REMOVER ALGUÉM QUE NÃO PARTICIPOU", [None] + list(por_id),
                                 format_func=lambda i: VAZIO if i is None else por_id[i],
                                 key=f"tr_qr_rm_{sessao_id}_{rv}")
    with c2:
        st.write("")
        remover = st.button("🗑️ Remover", key=f"tr_qr_rm_btn_{sessao_id}_{rv}", disabled=escolhido is None)
    if remover:
        ok, msg = banco.excluir(banco.TREINAMENTO, escolhido)
        if not ok:
            st.error(msg)
            return
        st.session_state["tr_qr_rm_v"] += 1
        st.rerun(scope="fragment")


def encerrar(sessao: dict, arquivo) -> None:
    # 1º a evidência nos participantes; se falhar, nada muda e a lista segue aberta
    ok, msg = evidencia.gravar(arquivo, "treinamento", lambda caminho: banco.atualizar_onde(
        banco.TREINAMENTO, "sessao_id", sessao["id"], {"link_evidencia": caminho}) if caminho else (True, ""))
    if not ok:
        st.error(msg)
        return
    ok, msg = banco.atualizar(banco.SESSAO, sessao["id"], {"encerrada_em": datetime.now(timezone.utc)})
    if not ok:
        st.error(f"A lista continua aberta — tente encerrar de novo. ({msg})")
        return
    total = len(banco.buscar(banco.TREINAMENTO, sessao_id=sessao["id"]))
    guardar_msg(MSG_QR, "success", f"Lista “{sessao['treinamento']}” encerrada com {total} participante"
                                   f"{'' if total == 1 else 's'}. Eles já aparecem em Registros.")
    st.session_state.pop("tr_qr_sessao", None)
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
    # o filtro de treinamento só oferece o que as filiais escolhidas realizaram
    da_filial = df[df["filial"].isin(filiais)] if filiais else df
    opcoes_trein = opcoes_existentes(da_filial, "treinamento")
    # tira da seleção o treinamento que deixou de existir ao trocar de filial
    st.session_state["tr_f_trein"] = [t for t in st.session_state.get("tr_f_trein", []) if t in opcoes_trein]
    with f2:
        treinos = st.multiselect("TREINAMENTO", opcoes_trein, key="tr_f_trein")
    with f3:
        vinculos = st.multiselect("VÍNCULO", VINCULOS, key="tr_f_vinculo")
    with f4:
        de = st.date_input("DE", value=None, format="DD/MM/YYYY", key="tr_f_de")
    with f5:
        ate = st.date_input("ATÉ", value=None, format="DD/MM/YYYY", key="tr_f_ate")
    f6, f7 = st.columns([1.3, 4.4])
    with f6:
        instrutores = st.multiselect("INSTRUTOR", opcoes_existentes(df, "instrutor"), key="tr_f_instrutor")
    with f7:
        busca = st.text_input("BUSCAR NOME OU CPF", key="tr_f_busca")

    f = df
    if filiais:
        f = f[f["filial"].isin(filiais)]
    if treinos:
        f = f[f["treinamento"].isin(treinos)]
    if vinculos:
        f = f[f["vinculo"].isin(vinculos)]
    if instrutores:
        f = f[f["instrutor"].isin(instrutores)]
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

    avaliadas = f["avaliacao"].dropna()
    contagem = avaliadas.value_counts()
    satisfeitos = int(contagem.get("Satisfeito", 0))
    vencidos = int((f["situacao"] == "Vencido").sum())
    vence_7 = int((f["situacao"] == "Vence em 7 dias").sum())
    vencendo = int((f["situacao"] == "Vence em 30 dias").sum())
    linha_cartoes([
        ("Participações", f"{len(f)}", "neutro", "linhas no filtro"),
        ("Pessoas treinadas", f"{f['cpf'].nunique()}", "verde", "CPFs distintos"),
        ("Treinamentos", f"{f['treinamento'].nunique()}", "neutro", "tipos distintos"),
        ("Satisfeitos", f"{satisfeitos / len(avaliadas):.0%}" if len(avaliadas) else VAZIO, "verde",
         " · ".join(f"{int(contagem.get(a, 0))} {a}" for a in AVALIACOES) if len(avaliadas)
         else "sem avaliações"),
        ("Vencem em 30 dias", f"{vencendo}", "laranja" if vencendo else "neutro", "de 7 a 29 dias"),
        ("Vencem em 7 dias", f"{vence_7}", "vermelho" if vence_7 else "neutro", "atenção imediata"),
        ("Vencidos", f"{vencidos}", "vermelho" if vencidos else "neutro", ""),
    ])
    st.write("")

    tabela = f[[
        "id", "data_treinamento", "treinamento", "instrutor", "filial", "nome", "cpf", "funcao",
        "setor", "vinculo", "avaliacao", "data_validade", "situacao", "link_assinatura",
    ]].copy()
    tabela["cpf"] = tabela["cpf"].map(fmt_cpf)
    tabela["link_assinatura"] = tabela["link_assinatura"].map(lambda l: texto(l).rsplit("/", 1)[-1] if texto(l) else "")
    textos = ["treinamento", "instrutor", "filial", "nome", "funcao", "setor", "vinculo", "avaliacao"]
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
            "instrutor": "INSTRUTOR",
            "filial": "FILIAL",
            "nome": "NOME",
            "cpf": "CPF",
            "funcao": "FUNÇÃO",
            "setor": "SETOR",
            "vinculo": "VÍNCULO",
            "avaliacao": "AVALIAÇÃO",
            "data_validade": st.column_config.DateColumn("VALIDADE", format="DD/MM/YYYY"),
            "situacao": "SITUAÇÃO",
            "link_assinatura": "ASSINATURA (arquivo no MinIO)",
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

    c4, c5, c6 = st.columns([2, 1.5, 1.5])
    with c4:
        treinamento = campo_com_outro(
            "TREINAMENTO", opcoes_existentes(df, "treinamento"), f"{k}_trein", reg["treinamento"]
        )
    with c5:
        instrutor = campo_instrutor(df, f"{k}_instrutor", reg["instrutor"])
    with c6:
        cod_filial, filial = acesso.campo_filial("FILIAL", f"{k}_filial", reg["cod_filial"])

    c7, c8, c11, c9, c10 = st.columns(5)
    with c11:
        vinculo = campo_lista("VÍNCULO", VINCULOS, f"{k}_vinculo", reg["vinculo"])
    with c7:
        funcao = campo_com_outro("FUNÇÃO", opcoes_funcao(df), f"{k}_funcao", reg["funcao"])
    with c8:
        setor = campo_com_outro("SETOR", opcoes_existentes(df, "setor"), f"{k}_setor", reg["setor"])
    with c9:
        avaliacao = campo_lista("AVALIAÇÃO", AVALIACOES, f"{k}_aval", reg["avaliacao"])
    with c10:
        validade = st.date_input(
            "VALIDADE", value=reg["data_validade"], format="DD/MM/YYYY", key=f"{k}_validade"
        )
    if texto(reg["link_assinatura"]):
        evidencia.mostrar(reg["link_assinatura"], "✍️ Ver assinatura")
    link_atual = texto(reg["link_evidencia"])
    if link_atual:
        evidencia.mostrar(link_atual)
    arquivo = evidencia.campo(
        "SUBSTITUIR EVIDÊNCIA (só deste participante)" if link_atual else "ANEXAR RQ 10 ASSINADA",
        f"{k}_arquivo",
    )

    confirmar = st.checkbox("Quero excluir este registro", key=f"{k}_confirma")
    b1, b2, _ = st.columns([1.4, 1, 4])
    salvar = b1.button("💾 Salvar alterações", type="primary", key=f"{k}_salvar")
    apagar = b2.button("🗑️ Excluir", key=f"{k}_excluir", disabled=not confirmar)

    if salvar:
        cpf_limpo = so_digitos(cpf)
        erros = []
        if not texto(nome):
            erros.append("Nome em branco.")
        if erro_cpf(cpf_limpo):
            erros.append(erro_cpf(cpf_limpo))
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
            "filial": filial, "cod_filial": cod_filial, "funcao": texto(funcao), "setor": texto(setor),
            "treinamento": treinamento, "instrutor": instrutor, "vinculo": vinculo, "data_validade": validade,
            "avaliacao": avaliacao, "link_evidencia": link_atual,
        }
        concluir(evidencia.gravar(arquivo, "treinamento", lambda caminho: banco.atualizar(
            banco.TREINAMENTO, rid, {**dados, "link_evidencia": caminho or dados["link_evidencia"]})))

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
