"""Presença por QR Code — a ÚNICA tela do app sem login.

Motorista agregado e terceiro não têm conta da empresa, então não passam
pelo login Microsoft. Quem escaneia o QR da lista aberta pelo TST
(Treinamentos › Presença por QR Code) cai aqui com ?presenca=<código>.

A tela só faz uma coisa: incluir a própria pessoa naquele treinamento.
Não mostra nada do banco — nem os outros participantes. O código é
aleatório e deixa de valer quando o TST encerra a lista.

A assinatura (assinatura.py) é obrigatória e vai para o MinIO como
treinamento/assinaturas/NOME-TREINAMENTO-DD-MM-AAAA.png; o caminho fica em
link_assinatura. Se o quadro não carregar no celular, a presença é aceita
sem assinatura (melhor do que perder o registro).
"""

import streamlit as st

import banco
import evidencia
from comum import (
    FUNCOES_RQ05, campo_com_outro, campo_lista, erro_cpf, fmt_data, mostrar_erros, so_digitos, texto,
)
from estilo import CSS_INTERNO, titulo_secao
from pagina_treinamento import AVALIACOES, VINCULOS

CARINHAS = {"Satisfeito": "😊 Satisfeito", "Normal": "😐 Normal", "Insatisfeito": "☹️ Insatisfeito"}


def sessao_do_codigo(codigo: str):
    linhas = banco.buscar(banco.SESSAO, codigo=codigo)
    return linhas[0] if linhas else None


def tela(codigo: str) -> None:
    st.markdown(CSS_INTERNO, unsafe_allow_html=True)
    try:
        sessao = sessao_do_codigo(codigo)
    except Exception as erro:
        st.error(f"Não foi possível abrir a lista de presença: {erro}")
        return
    if not sessao:
        st.error("Link de presença inválido. Peça ao instrutor para mostrar o QR Code de novo.")
        return

    st.markdown(f"## 🎓 {sessao['treinamento']}")
    instrutor = f" · Instrutor: {sessao['instrutor']}" if sessao.get("instrutor") else ""
    st.caption(f"Lista de presença · {fmt_data(sessao['data_treinamento'])} · {sessao['filial']}{instrutor}")
    if sessao.get("encerrada_em"):
        st.warning("Esta lista de presença já foi encerrada pelo instrutor.")
        return

    v = st.session_state.setdefault("pr_v", 0)  # avança a cada registro: limpa os campos
    feito = st.session_state.get("pr_feito")
    if feito:
        st.success(f"✅ Presença registrada: **{feito}**. Pode fechar esta página.")
        st.button("Registrar outra pessoa neste celular", on_click=st.session_state.pop, args=("pr_feito",))
        return

    titulo_secao("Seus dados", "Preencha e toque em ✅ Registrar minha presença.")
    nome = st.text_input("NOME COMPLETO", key=f"pr_nome_{v}")
    cpf = st.text_input("CPF", key=f"pr_cpf_{v}", placeholder="000.000.000-00")
    funcao = campo_com_outro("FUNÇÃO", sorted(FUNCOES_RQ05, key=str.casefold), f"pr_funcao_{v}")
    setor = st.text_input("SETOR (se souber)", key=f"pr_setor_{v}")
    vinculo = campo_lista("VÍNCULO", VINCULOS, f"pr_vinculo_{v}")
    avaliacao = st.radio(
        "O QUE ACHOU DO TREINAMENTO?", AVALIACOES, index=None, horizontal=True,
        format_func=CARINHAS.get, key=f"pr_aval_{v}",
    )
    quadro_ok, png = campo_assinatura(v)
    st.caption("Nome e CPF são usados só para o registro deste treinamento pelo SESMT da Della Volpe.")

    if st.button("✅ Registrar minha presença", type="primary", key=f"pr_ok_{v}", width="stretch"):
        registrar(codigo, nome, cpf, funcao, setor, vinculo, avaliacao, png, quadro_ok)


def campo_assinatura(v: int) -> tuple:
    """(quadro carregou?, PNG da assinatura ou None).

    O import fica aqui dentro: se o componente falhar, só o quadro some — a
    tela de presença continua funcionando.
    """
    try:
        from assinatura import campo_assinatura as quadro
        st.markdown("**ASSINATURA**")
        png = quadro(f"pr_assinatura_{v}")
    except Exception as erro:
        st.warning(f"Quadro de assinatura indisponível: {erro}")
        return False, None
    if png:
        st.image(png, caption="Sua assinatura", width=220)
    return True, png


def registrar(codigo, nome, cpf, funcao, setor, vinculo, avaliacao, png, quadro_ok) -> None:
    cpf = so_digitos(cpf)
    erros = []
    if not texto(nome):
        erros.append("Informe o seu nome completo.")
    if erro_cpf(cpf):
        erros.append(erro_cpf(cpf))
    if quadro_ok and not png:
        erros.append("Assine no quadro: toque em ✍️ Toque para assinar.")
    if erros:
        mostrar_erros(erros, "Confira antes de registrar:")
        return

    sessao = sessao_do_codigo(codigo)  # lê de novo: o instrutor pode ter encerrado agora
    if not sessao or sessao.get("encerrada_em"):
        st.warning("Esta lista de presença já foi encerrada pelo instrutor.")
        return
    if banco.buscar(banco.TREINAMENTO, sessao_id=sessao["id"], cpf=cpf):
        st.info("Este CPF já está registrado nesta lista. Não precisa registrar de novo.")
        return

    caminho = None
    if png:
        try:
            caminho = evidencia.subir_assinatura(png, nome, sessao["treinamento"], sessao["data_treinamento"])
        except Exception as erro:
            st.error(f"Não foi possível salvar a assinatura. Tente de novo. ({erro})")
            return

    ok, msg = banco.inserir(banco.TREINAMENTO, [{
        "nome": texto(nome), "cpf": cpf, "funcao": funcao, "setor": texto(setor),
        "vinculo": vinculo, "avaliacao": avaliacao,
        "treinamento": sessao["treinamento"], "instrutor": sessao.get("instrutor"),
        "conteudo_programatico": sessao.get("conteudo_programatico"),
        "data_treinamento": sessao["data_treinamento"],
        "filial": sessao["filial"], "cod_filial": sessao["cod_filial"],
        "data_validade": sessao["data_validade"], "sessao_id": sessao["id"],
        "link_assinatura": caminho, "link_evidencia": sessao.get("link_evidencia"),
        "criado_por": "QR Code",
    }])
    if not ok:
        if caminho:
            evidencia.remover(caminho)  # sem registro, a assinatura não fica solta no MinIO
        st.error(msg)  # os campos continuam preenchidos para tentar de novo
        return
    st.session_state["pr_feito"] = texto(nome)
    st.session_state["pr_v"] += 1
    st.rerun()
