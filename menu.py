"""Tela inicial (menu) e roteador — mesmo padrão do Metas TDV.

A arte de fundo já traz o logo, a área creme à esquerda (onde o texto fica
legível) e o caminhão à direita — por isso o conteúdo fica encostado à
esquerda e os cards não passam da metade da tela.

Cada card é montado em duas partes: o topo (ícone, título e descrição) é
HTML, e o rodapé é um st.button de verdade, colado por baixo pelo CSS.
"""

import html
from datetime import date

import streamlit as st

import acesso
import pagina_acidente
import pagina_cat
import pagina_indicadores
import pagina_plano_acao
import pagina_treinamento
from estilo import (
    CSS_MENU, CSS_MENU_DESTAQUE, URL_FUNDO_MENU, URL_LOGO_COLORIDO, html_selo_canto, ir_para,
)

# Nome no canto superior direito da arte: (parte em laranja, parte escura).
# Num app novo, é só trocar aqui — a imagem de fundo é a mesma para todos.
NOME_NO_CANTO = ("SEG", "TRABALHO")

# ícones em SVG: currentColor faz cada um herdar a cor do seu card
SVG_CAPELO = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M2.5 9L12 4.5 21.5 9 12 13.5z"/><path d="M6.5 11v4.5c0 1.4 2.5 3 5.5 3s5.5-1.6 5.5-3V11"/>'
    '<path d="M21.5 9v5"/></svg>'
)
SVG_ALERTA = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3.5L21.5 20h-19z"/><path d="M12 10v4.5"/><path d="M12 17.3v.2"/></svg>'
)
SVG_CHECKLIST = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M10 6h10"/><path d="M10 12h10"/><path d="M10 18h10"/>'
    '<path d="M3.5 6l1.5 1.5L7.5 5"/><path d="M3.5 12l1.5 1.5 2.5-2.5"/>'
    '<path d="M3.5 18l1.5 1.5 2.5-2.5"/></svg>'
)
SVG_ESCUDO = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z"/>'
    '<path d="M9 12l2.2 2.2L15.5 10"/></svg>'
)
SVG_CRUZ = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="3.5" y="5.5" width="17" height="14" rx="2"/><path d="M9 5.5V4h6v1.5"/>'
    '<path d="M12 9.5v6"/><path d="M9 12.5h6"/></svg>'
)
SVG_GRAFICO = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 20h16"/><path d="M7 16v-4"/><path d="M12 16V8"/><path d="M17 16v-6"/></svg>'
)
SVG_CALENDARIO = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"'
    ' stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16"/>'
    '<path d="M9 3v4"/><path d="M15 3v4"/></svg>'
)

CARDS_MENU = [
    ("treinamento", "TREINAMENTOS", SVG_CAPELO,
     "Listas de presença (RQ 10): treinamentos, integrações e reciclagens, com validade e avaliação."),
    ("acidente", "ACIDENTES", SVG_ALERTA,
     "Relatório de Acidente: o que aconteceu, quem se envolveu, veículo e tipo de perda."),
    ("plano_acao", "PLANO DE AÇÃO", SVG_CHECKLIST,
     "Ações de acidentes, inspeções e PGR: prazo, conclusão e eficácia."),
    ("cat", "ACIDENTES INTERNOS", SVG_CRUZ,
     "CAT: acidentes de motoristas próprios e funcionários, afastamentos e dias perdidos."),
    ("indicadores", "INDICADORES", SVG_GRAFICO,
     "Painel de indicadores: acidentes internos, afastamentos e dias perdidos por filial e mês."),
]

ROTAS = {
    "treinamento": pagina_treinamento.tela,
    "acidente": pagina_acidente.tela,
    "plano_acao": pagina_plano_acao.tela,
    "cat": pagina_cat.tela,
    "indicadores": pagina_indicadores.tela,
}


def html_cabecalho(usuario: dict) -> str:
    return (
        '<div class="dv-menu">'
        '<p class="dv-eyebrow">Painel de</p>'
        '<h1 class="dv-titulo">Segurança do Trabalho</h1>'
        f'<p class="dv-bemvindo">Bem-vindo(a), {html.escape(usuario["nome"])} — '
        f'<b>{html.escape(usuario["email"])}</b></p>'
        '<div class="dv-pilulas">'
        f'<span class="dv-pilula">{SVG_ESCUDO} Acesso: {html.escape(acesso.descricao())}</span>'
        f'<span class="dv-pilula">{SVG_CALENDARIO} Hoje, {date.today():%d/%m/%Y}</span>'
        "</div></div>"
    )


def html_card_topo(titulo: str, icone: str, descricao: str) -> str:
    return (
        '<div class="dv-cardtopo"><div class="dv-card-topo">'
        f'<div class="dv-card-bolha">{icone}</div>'
        f"<div><h3>{titulo}</h3><p>{descricao}</p></div>"
        "</div></div>"
    )


def tela_menu(usuario: dict) -> None:
    estilo = CSS_MENU.replace("URL_DO_FUNDO", URL_FUNDO_MENU).replace("URL_DO_LOGO", URL_LOGO_COLORIDO)
    st.markdown(estilo, unsafe_allow_html=True)
    st.markdown(CSS_MENU_DESTAQUE, unsafe_allow_html=True)
    st.markdown(html_selo_canto(*NOME_NO_CANTO), unsafe_allow_html=True)
    st.markdown(html_cabecalho(usuario), unsafe_allow_html=True)

    # a terceira coluna é só respiro: mantém os cards na área creme, sem
    # avançar sobre o caminhão (mesma proporção do Metas TDV)
    col_a, col_b, _respiro = st.columns([1, 1, 1.9], gap="small")
    for i, (tela, titulo, icone, descricao) in enumerate(CARDS_MENU):
        with col_a if i % 2 == 0 else col_b:
            st.markdown(html_card_topo(titulo, icone, descricao), unsafe_allow_html=True)
            st.button(
                "Acessar  →", key=f"card_{tela}", on_click=ir_para, args=(tela,), width="stretch"
            )


def rodar(usuario: dict) -> None:
    """Abre a tela guardada na sessão; tela desconhecida cai no menu."""
    st.session_state.setdefault("tela", "menu")
    tela = ROTAS.get(st.session_state["tela"])
    if tela is None:
        st.session_state["tela"] = "menu"
        tela_menu(usuario)
    else:
        tela(usuario)
