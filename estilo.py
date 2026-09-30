"""Visual do app — mesmo padrão do Metas TDV (CRUD.py), paleta laranja.

CSS_BASE_CLARA, CSS_MENU e CSS_INTERNO são cópia fiel do CRUD.py. Se mudar
lá, copie de novo em vez de editar aqui, para os apps não divergirem.

  CSS_LOGIN       → só na tela de login (foto escura de fundo)
  CSS_BASE_CLARA  → sempre, logo depois do set_page_config (dropdown, calendário, tooltip)
  CSS_MENU        → tela inicial (arte de fundo + cards)
  CSS_INTERNO     → telas de trabalho (fundo claro, campos, cartões, sidebar)
"""

import streamlit as st

URL_FUNDO_LOGIN = "https://raw.githubusercontent.com/DellaVolpe69/Images/main/AppBackground02.png"
URL_LOGO_BRANCO = "https://raw.githubusercontent.com/DellaVolpe69/Images/main/DellaVolpeLogoBranco.png"
# Arte do Metas TDV com o canto trocado por SEG TRABALHO (arquivo em imagens/).
URL_FUNDO_MENU = "https://raw.githubusercontent.com/DellaVolpe69/Images/main/SEG_TRABALHO.png"
URL_LOGO_COLORIDO = "https://raw.githubusercontent.com/DellaVolpe69/Images/main/logo.png"

CSS_LOGIN = f"""
<style>
.stApp {{
    background: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)),
        url("{URL_FUNDO_LOGIN}");
    background-size: cover;
}}
header, [data-testid="stHeader"] {{ background: transparent; }}
.custom-login-btn {{
    background-color: #FF5D01 !important;
    color: white !important;
    border: 2px solid white !important;
    padding: 0.6em 1.2em;
    border-radius: 10px !important;
    font-size: 1rem;
    font-weight: 500;
    cursor: pointer;
    transition: 0.2s ease;
    text-decoration: none !important;
    display: inline-block;
}}
.custom-login-btn:hover {{
    background-color: white !important;
    color: #FF5D01 !important;
    transform: scale(1.03);
    border: 2px solid #FF5D01 !important;
}}
.center-container {{ text-align: center; margin-top: 10px; }}
</style>
"""

CSS_BASE_CLARA = """
<style>
:root, .stApp { color-scheme: light !important; }

[data-testid="stAppViewContainer"] { color: #2B2420; }
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] span,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] li { color: #3A322C; }

/* menu do selectbox, calendário do date_input e popovers de ajuda: ficam
   fora do container da página, então precisam de regra própria */
[data-baseweb="popover"] [data-baseweb="menu"],
[data-baseweb="popover"] ul[role="listbox"],
[data-baseweb="calendar"],
[data-baseweb="datepicker"] {
    background: #FFFFFF !important;
    color: #2B2420 !important;
    border: 1px solid #EADFD6 !important;
}
[role="option"] { color: #2B2420 !important; background: transparent !important; }
[role="option"]:hover, [role="option"][aria-selected="true"] {
    background: #FDEEE3 !important; color: #B84E08 !important;
}
[data-baseweb="calendar"] [aria-selected="true"] {
    background: #E4610A !important; color: #FFFFFF !important;
}
[data-baseweb="tooltip"] { background: #B84E08 !important; color: #FFFFFF !important; }

/* mensagens de estado: st.success / st.warning / st.error / st.info */
[data-testid="stAlert"] { border-radius: 10px !important; }

/* barra de rolagem no tom do painel */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #E0CFC2; border-radius: 6px; }
::-webkit-scrollbar-track { background: transparent; }
</style>
"""

CSS_MENU = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');

/* A arte entra inteira (100% auto, sem recorte — cover cortaria o logo e o
   selo embutidos) e presa ao viewport, para acompanhar o zoom junto com o
   conteúdo. Sem degradê por cima: a área creme à esquerda já garante a
   leitura. #FBF9F6 é o fallback se o GitHub não responder. */
.stApp {
    background:
        url("URL_DO_FUNDO") top center / 100% auto no-repeat fixed,
        #FBF9F6 !important;
}
header, [data-testid="stHeader"] { background: transparent !important; }
[data-testid="stToolbar"] { right: 1rem; }

/* conteúdo encostado à esquerda, na área creme da arte; 8vw acompanha o
   logo da arte, que escala com a largura, e +30px é o respiro */
.block-container {
    max-width: 100% !important;
    padding: calc(8vw + 30px) 2.5rem 2rem 3.2rem !important;
}
.dv-menu { max-width: min(1180px, 100%); }

/* card e botão são dois elementos do Streamlit: sem zerar o espaço entre
   eles ficaria uma fenda no meio do card. Vale para a tela toda porque
   este CSS só é injetado no menu. */
[data-testid="stVerticalBlock"] { gap: 0 !important; }

/* mesma regra do CSS_INTERNO: tudo em Poppins, menos os ícones */
.stApp *:not([data-testid="stIconMaterial"]):not(code):not(pre) {
    font-family: 'Poppins', 'Segoe UI', sans-serif !important;
}

/* ---------- cabeçalho ---------- */
.dv-menu { color: #3A322C; margin: 0 0 22px; }
.dv-menu .dv-eyebrow {
    font-size: 1.35rem !important; font-weight: 300 !important;
    color: #6A5D54 !important; margin: 0 !important; line-height: 1.1;
}
.dv-menu .dv-titulo {
    font-size: 2.7rem !important; font-weight: 700 !important;
    color: #E4610A !important; margin: -2px 0 10px !important; padding: 0 !important;
    line-height: 1.05; letter-spacing: -0.5px;
}
.dv-menu .dv-bemvindo {
    font-size: 0.9rem !important; color: #6A5D54 !important; margin: 0 0 12px !important;
}
.dv-menu .dv-bemvindo b { color: #E4610A !important; font-weight: 500 !important; }
.dv-menu .dv-pilulas { display: flex; flex-wrap: wrap; gap: 8px; }
.dv-menu .dv-pilula {
    display: inline-flex; align-items: center; gap: 8px;
    font-size: 0.8rem !important; color: #6A5D54 !important;
    background: rgba(255,255,255,0.85); border: 1px solid #EADFD6;
    border-radius: 999px; padding: 5px 13px;
}
.dv-menu .dv-pilula svg { width: 15px; height: 15px; color: #E4610A; }

/* ---------- cards ---------- */
/* o topo do card é HTML; o rodapé é um st.button de verdade, colado por
   baixo. Navegação por botão (e não por link) é o que preserva a sessão. */
.dv-cardtopo {
    background: rgba(255,255,255,0.96);
    border: 1px solid #EFE5DC; border-bottom: none;
    border-radius: 14px 14px 0 0;
    /* 18px embaixo: com menos a descrição encosta no rodapé do card e o
       botão, opaco, cobre a metade de baixo das letras */
    padding: 16px 18px 18px;
    /* piso comum: título de 2 linhas + descrição de 3 — assim os cards de
       uma mesma linha ficam da mesma altura */
    min-height: 140px; overflow: visible;
}
.dv-cardtopo .dv-card-topo { display: flex; gap: 13px; align-items: flex-start; }
.dv-cardtopo .dv-card-bolha {
    flex: 0 0 auto; width: 42px; height: 42px; border-radius: 50%;
    display: grid; place-items: center; background: #FDEEE3; color: #E4610A;
}
.dv-cardtopo .dv-card-bolha svg { width: 23px; height: 23px; }
.dv-cardtopo h3 {
    font-size: 0.84rem !important; font-weight: 700 !important;
    letter-spacing: 0.04em; color: #E4610A !important; margin: 2px 0 6px !important;
    padding: 0 !important; line-height: 1.25;
}
.dv-cardtopo p {
    font-size: 0.76rem !important; line-height: 1.5;
    color: #7A6E66 !important; margin: 0 !important;
}

/* rodapé clicável do card */
div[data-testid="stButton"] button {
    background: rgba(255,255,255,0.96) !important;
    color: #E4610A !important;
    border: 1px solid #EFE5DC !important; border-top: none !important;
    border-radius: 0 0 14px 14px !important;
    width: 100% !important; padding: 0.5em 1.1em !important;
    font-weight: 600 !important; font-size: 0.76rem !important;
    letter-spacing: 0.04em;
    justify-content: flex-end !important; text-align: right !important;
    box-shadow: none !important; transition: 0.15s ease;
    margin-bottom: 16px !important;
}
div[data-testid="stButton"] button:hover {
    background: #FDEEE3 !important; border-color: #E4610A !important;
    color: #B84E08 !important; transform: none !important;
}
/* o rótulo vem embrulhado em <p>/<div>: sem isto ele ignora a cor do botão */
div[data-testid="stButton"] button * { color: inherit !important; }

/* ---------- faixa das 4 disciplinas ---------- */
/* abaixo dos cards, na área creme — à direita ela cairia sobre o caminhão */
.dv-faixa {
    background: rgba(255,255,255,0.94); border: 1px solid #EFE5DC;
    border-radius: 16px; padding: 12px 18px 14px;
    /* 48vw acompanha a largura das duas colunas de cards */
    max-width: min(760px, 48vw); margin-top: 6px;
}
.dv-faixa .dv-faixa-titulo {
    text-align: center; font-size: 0.72rem !important; font-weight: 700 !important;
    letter-spacing: 0.12em; text-transform: uppercase;
    color: #7A6E66 !important; margin: 0 0 12px !important;
}
.dv-faixa .dv-faixa-titulo b { color: #E4610A !important; }
.dv-faixa .dv-faixa-itens {
    display: flex; justify-content: space-between; gap: 14px; flex-wrap: wrap;
}
.dv-faixa .dv-disc { flex: 1 1 150px; display: flex; gap: 9px; align-items: flex-start; }
.dv-faixa .dv-disc-n {
    flex: 0 0 auto; width: 26px; height: 26px; border-radius: 50%;
    display: grid; place-items: center; background: #FDEEE3;
    color: #E4610A !important; font-weight: 700; font-size: 0.74rem !important;
}
.dv-faixa .dv-disc b {
    display: block; font-size: 0.72rem; font-weight: 600; color: #2B2420 !important;
    margin: 1px 0 2px; line-height: 1.3;
}
.dv-faixa .dv-disc .dv-disc-tela {
    font-size: 0.64rem !important; font-weight: 600; color: #E4610A !important;
}

/* ---------- telas estreitas ---------- */
/* A arte é 16:9: encolhida, o caminhão avança sobre o texto e o logo fica
   ilegível. Abaixo de 980px ela sai e entra só o logo no canto. */
@media (max-width: 980px) {
    .stApp {
        background:
            url("URL_DO_LOGO") 22px 18px / 160px auto no-repeat,
            #FBF9F6 !important;
    }
    .block-container { padding: 5.5rem 1.2rem 2rem 1.2rem !important; }
    .dv-menu .dv-titulo { font-size: 2.1rem !important; }
    .dv-faixa { max-width: 100%; }
}
</style>
"""

CSS_INTERNO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');

/* Fundo claro nas telas de trabalho; a faixa no topo mantém a identidade
   do menu. */
.stApp {
    background: #FAF7F4 !important;
}
.stApp::before {
    content: ""; position: fixed; top: 0; left: 0; right: 0; height: 5px;
    background: linear-gradient(90deg, #B84E08 0%, #E4610A 45%, #F7A46B 100%);
    z-index: 999;
}
header, [data-testid="stHeader"] { background: transparent !important; }
.block-container { padding-top: 2.6rem !important; max-width: 1250px; }

/* A lista de seletores antiga ([class*="css"], .stMarkdown, label...) não
   pega mais: as classes do Streamlit viraram st-emotion-cache-* e cada <p>
   interno traz a própria fonte. Regra ampla, poupando só os ícones — eles
   são uma fonte de ícones, e com Poppins virariam texto
   ("keyboard_arrow_down"). */
.stApp *:not([data-testid="stIconMaterial"]):not(code):not(pre) {
    font-family: 'Poppins', 'Segoe UI', sans-serif !important;
}

/* títulos das telas */
.stMarkdown h2 {
    color: #E4610A !important; font-weight: 700 !important;
    letter-spacing: -0.3px; font-size: 1.55rem !important;
}
.stMarkdown h3, .stMarkdown h4 { color: #B84E08 !important; font-weight: 600 !important; }
.stMarkdown h3 { font-size: 1.1rem !important; padding-top: 0.9rem !important; }
.stMarkdown p, .stMarkdown li, [data-testid="stCaptionContainer"] { color: #5A4E46; }
hr { border-color: #EADFD6 !important; }

/* rótulos de campo — forçados porque o visitante pode estar no tema escuro */
label, [data-testid="stWidgetLabel"] p {
    color: #3A322C !important; font-size: 0.78rem !important;
    font-weight: 600 !important; letter-spacing: 0.02em;
}

/* campos */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
    background: #FFFFFF !important;
    border-color: #EADFD6 !important;
    border-radius: 9px !important;
}
[data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
[data-baseweb="select"] div { color: #2B2420 !important; }
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {
    border-color: #E4610A !important; box-shadow: 0 0 0 2px rgba(228,97,10,0.14) !important;
}
/* no number_input a borda fica no container, não no [data-baseweb="input"],
   e vem com a cor de secondaryBackgroundColor — branca, invisível sobre o
   cartão branco do expander */
[data-testid="stNumberInputContainer"] {
    border-color: #EADFD6 !important; border-radius: 9px !important;
    background: #FFFFFF !important; overflow: hidden;
}
[data-testid="stNumberInputContainer"]:focus-within {
    border-color: #E4610A !important; box-shadow: 0 0 0 2px rgba(228,97,10,0.14) !important;
}
/* os botões − e + do number_input */
[data-testid="stNumberInput"] button {
    background: #F4F0EC !important; color: #3A322C !important;
}
[data-testid="stNumberInput"] button:hover { background: #FDEEE3 !important; color: #E4610A !important; }

/* abas */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 4px; background: transparent; border-bottom: 1px solid #EADFD6;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important; border-radius: 9px 9px 0 0;
    padding: 8px 16px !important; color: #7A6E66 !important;
    font-weight: 600 !important; font-size: 0.84rem !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
    background: #FFFFFF !important; color: #E4610A !important;
    border: 1px solid #EADFD6 !important; border-bottom-color: #FFFFFF !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background: #E4610A !important; }

/* botões */
div[data-testid="stButton"] button,
div[data-testid="stDownloadButton"] button,
div[data-testid="stFormSubmitButton"] button {
    background: #FFFFFF !important; color: #E4610A !important;
    border: 1px solid #E0CFC2 !important; border-radius: 10px !important;
    padding: 0.45em 1.1em !important; width: auto !important;
    font-weight: 600 !important; font-size: 0.84rem !important;
    box-shadow: none !important; transition: 0.15s ease;
}
div[data-testid="stButton"] button:hover,
div[data-testid="stDownloadButton"] button:hover,
div[data-testid="stFormSubmitButton"] button:hover {
    background: #FDEEE3 !important; border-color: #E4610A !important;
    transform: none !important;
}
/* o rótulo é um <p> dentro do <button>: sem herdar, ele fica preto sobre o
   laranja do botão primário */
div[data-testid="stButton"] button *,
div[data-testid="stDownloadButton"] button *,
div[data-testid="stFormSubmitButton"] button * { color: inherit !important; white-space: nowrap; }

div[data-testid="stButton"] button[kind^="primary"],
div[data-testid="stDownloadButton"] button[kind^="primary"],
div[data-testid="stFormSubmitButton"] button[kind^="primary"] {
    background: #E4610A !important; color: #FFFFFF !important;
    border-color: #E4610A !important;
}
div[data-testid="stButton"] button[kind^="primary"]:hover,
div[data-testid="stDownloadButton"] button[kind^="primary"]:hover,
div[data-testid="stFormSubmitButton"] button[kind^="primary"]:hover {
    background: #B84E08 !important; border-color: #B84E08 !important;
    color: #FFFFFF !important;
}
div[data-testid="stButton"] button:disabled,
div[data-testid="stDownloadButton"] button:disabled,
div[data-testid="stFormSubmitButton"] button:disabled {
    background: #F4F0EC !important; color: #B5AAA2 !important;
    border-color: #EFE5DC !important;
}
div[data-testid="stButton"] button:focus-visible,
div[data-testid="stDownloadButton"] button:focus-visible,
div[data-testid="stFormSubmitButton"] button:focus-visible {
    outline: 2px solid #8A3A06 !important; outline-offset: 2px;
}

/* formulário como cartão branco */
[data-testid="stForm"] {
    background: #FFFFFF; border: 1px solid #EADFD6 !important;
    border-radius: 12px !important; padding: 18px 20px 16px !important;
}

/* cartões de indicador: st.metric não aceita cor por cartão, então estes
   são HTML — dá para pintar fundo, faixa lateral e o número.
   Aqui as cores são de STATUS, não de marca: verde = bom, laranja =
   atenção, vermelho = problema. Por isso o verde sobrevive só aqui. */
.dv-kpi {
    background: #FFFFFF; border: 1px solid #EADFD6;
    border-left: 4px solid #E0CFC2; border-radius: 12px;
    padding: 12px 14px; min-height: 88px;
    display: flex; flex-direction: column; gap: 2px;
}
.dv-kpi.verde {
    border-left-color: #2E7D46;
    background: linear-gradient(180deg, #F2F8F3 0%, #FFFFFF 70%);
}
.dv-kpi.verde strong { color: #1F5F33 !important; }
.dv-kpi.laranja {
    border-left-color: #E4610A;
    background: linear-gradient(180deg, #FFF6F0 0%, #FFFFFF 70%);
}
.dv-kpi.vermelho {
    border-left-color: #B3261E;
    background: linear-gradient(180deg, #FDF0EF 0%, #FFFFFF 70%);
}
.dv-kpi.vermelho strong { color: #8C1D18 !important; }
.dv-kpi-rotulo {
    font-size: 0.68rem !important; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: #7A6E66 !important;
}
.dv-kpi strong {
    font-size: 1.35rem; font-weight: 700; color: #2B2420 !important;
    line-height: 1.2;
}
.dv-kpi.laranja strong { color: #B84E08 !important; }
.dv-kpi-nota { font-size: 0.66rem !important; color: #9A8E86 !important; }

/* título de seção dentro de uma tela */
.dv-secao { margin: 14px 0 8px; }
.dv-secao-titulo {
    font-size: 0.95rem !important; font-weight: 600 !important;
    color: #B84E08 !important; margin: 0 !important;
}
.dv-secao-nota { font-size: 0.74rem !important; color: #7A6E66 !important; margin: 2px 0 0 !important; }

/* lista de equipes */
.dv-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.dv-chip {
    background: #FFFFFF; border: 1px solid #EADFD6; border-radius: 999px;
    padding: 5px 13px; font-size: 0.78rem !important; font-weight: 500;
    color: #B84E08 !important;
}

/* bloco de explicação ao lado de um formulário */
.dv-dica {
    background: #FFFFFF; border: 1px solid #EADFD6; border-left: 4px solid #E4610A;
    border-radius: 12px; padding: 14px 16px 6px;
}
.dv-dica p { font-size: 0.78rem !important; line-height: 1.5; color: #5A4E46 !important; margin: 0 0 10px !important; }
.dv-dica b { color: #B84E08 !important; }

/* barra lateral de páginas */
[data-testid="stSidebar"] {
    background: #FFFFFF !important; border-right: 1px solid #EADFD6;
}
[data-testid="stSidebar"] .dv-sidebar-titulo {
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: #7A6E66; margin: 0 0 10px;
}
/* itens de navegação: texto à esquerda, como lista, não como botão */
[data-testid="stSidebar"] div[data-testid="stButton"] button {
    /* a regra geral de botão é width:auto; aqui é lista, de ponta a ponta */
    width: 100% !important;
    justify-content: flex-start !important; text-align: left !important;
    border-radius: 8px !important; font-size: 0.82rem !important;
    padding: 0.45em 0.8em !important; margin-bottom: 3px !important;
}

/* tabela */
[data-testid="stDataFrame"] {
    border: 1px solid #EADFD6 !important; border-radius: 10px; overflow: hidden;
}

/* mensagens e blocos */
[data-testid="stMetric"] {
    background: #FFFFFF; border: 1px solid #EADFD6; border-radius: 12px;
    padding: 10px 14px;
}
[data-testid="stMetricValue"] { color: #E4610A !important; }
[data-testid="stExpander"] {
    background: #FFFFFF; border: 1px solid #EADFD6 !important; border-radius: 10px;
}
[data-testid="stExpander"] details { border: none !important; }
[data-testid="stExpander"] summary p { font-weight: 500 !important; color: #2B2420 !important; }
[data-testid="stFileUploaderDropzone"] {
    background: #FFFFFF !important; border: 1px dashed #E0CFC2 !important;
}
</style>
"""


# Ajuste próprio deste app sobre o CSS_MENU (que fica idêntico ao Metas TDV):
# a borda original #EFE5DC quase some sobre a área creme da arte. O card é
# dois elementos colados (topo HTML + st.button), então a borda nova vai nos
# dois, sem a linha do meio. Injetar DEPOIS do CSS_MENU.
CSS_MENU_DESTAQUE = """
<style>
.dv-cardtopo {
    border: 1.5px solid #E8B894 !important; border-bottom: none !important;
}
div[data-testid="stButton"] button {
    border: 1.5px solid #E8B894 !important; border-top: none !important;
}
div[data-testid="stButton"] button:hover {
    border-color: #E4610A !important;
}
</style>
"""


# ---------------------------------------------------------------------
# Navegação — sempre st.button + session_state, nunca <a href>: o link
# recarrega a página, abre sessão nova e o login do Azure se perde.
# ---------------------------------------------------------------------

def ir_para(tela: str) -> None:
    st.session_state["tela"] = tela


def cabecalho_tela(titulo: str, subtitulo: str, chave: str) -> None:
    """Título da tela + botão de retorno ao menu. Injeta o CSS interno."""
    st.markdown(CSS_INTERNO, unsafe_allow_html=True)
    esq, dir_ = st.columns([4, 1])
    with esq:
        st.markdown(f"## {titulo}")
        st.caption(subtitulo)
    with dir_:
        st.button("⬅️ Voltar", key=f"voltar_{chave}", on_click=ir_para, args=("menu",))
    st.divider()


def barra_paginas_lateral(estado: str, paginas: dict, prefixo: str) -> str:
    """Navegação por páginas na lateral esquerda. Devolve a página ativa.

    `estado` é a chave no session_state e `prefixo` isola as keys dos botões.
    A página ativa é marcada com type="primary".
    """
    primeira = next(iter(paginas))
    st.session_state.setdefault(estado, primeira)
    if st.session_state[estado] not in paginas:  # estado órfão de sessão antiga
        st.session_state[estado] = primeira

    with st.sidebar:
        st.markdown('<p class="dv-sidebar-titulo">Páginas</p>', unsafe_allow_html=True)
        for chave, nome in paginas.items():
            ativa = st.session_state[estado] == chave
            st.button(
                nome,
                key=f"{prefixo}_pg_{chave}",
                width="stretch",
                type="primary" if ativa else "secondary",
                on_click=lambda c=chave: st.session_state.__setitem__(estado, c),
            )
    return st.session_state[estado]


def sair() -> None:
    """Esquece o login desta sessão; o próximo rerun cai na tela de login."""
    for chave in ("token", "usuario", "tela"):
        st.session_state.pop(chave, None)


def bloco_usuario_lateral(usuario: dict) -> None:
    with st.sidebar:
        st.divider()
        st.caption(f"**{usuario['nome']}**  \n{usuario['email']}")
        st.button("Sair", key="sst_sair", on_click=sair)


# ---------------------------------------------------------------------
# Componentes
# ---------------------------------------------------------------------

def titulo_secao(titulo: str, nota: str = "") -> None:
    """Título pequeno de bloco dentro de uma tela. Os textos já vêm escapados."""
    extra = f'<p class="dv-secao-nota">{nota}</p>' if nota else ""
    st.markdown(
        f'<div class="dv-secao"><p class="dv-secao-titulo">{titulo}</p>{extra}</div>',
        unsafe_allow_html=True,
    )


def cartao_kpi(rotulo: str, valor: str, cor: str = "neutro", nota: str = "") -> str:
    """Cor é de status: verde = bom, laranja = atenção, vermelho = problema."""
    return (
        f'<div class="dv-kpi {cor}">'
        f'<span class="dv-kpi-rotulo">{rotulo}</span>'
        f"<strong>{valor}</strong>"
        f'<span class="dv-kpi-nota">{nota}</span>'
        "</div>"
    )


def linha_cartoes(cartoes: list) -> None:
    """cartoes = [(rotulo, valor_formatado, cor, nota), ...]"""
    if not cartoes:
        return
    caixas = st.columns(len(cartoes))
    for caixa, (rotulo, valor, cor, nota) in zip(caixas, cartoes):
        with caixa:
            st.markdown(cartao_kpi(rotulo, valor, cor, nota), unsafe_allow_html=True)
