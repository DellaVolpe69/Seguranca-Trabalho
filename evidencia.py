"""Segurança do Trabalho — lançamentos do SESMT (Streamlit + Supabase).

Mesmo padrão do Metas TDV: login Azure → menu com a arte de fundo → telas
de trabalho com páginas na barra lateral.

Arquivos:
  streamlit_app.py       login Azure e controle de acesso
  menu.py                tela inicial (cards) e roteador
  estilo.py              CSS e componentes visuais (cópia do Metas TDV)
  banco.py               leitura/gravação no Supabase
  comum.py               utilitários de tela (CPF, datas, campos)
  pagina_treinamento.py  RQ 10 → segtrabalho_treinamento
  pagina_presenca.py     tela do QR Code (sem login): participante se registra
  pagina_acidente.py     Relatório de Acidente → segtrabalho_acidente
  pagina_plano_acao.py   Plano de ação → segtrabalho_plano_acao
  pagina_cat.py          Acidentes internos (CAT) → segtrabalho_cat
  evidencia.py           anexos no MinIO (bucket seguranca-trabalho)
"""

import time

import streamlit as st

# Configuração da página — DEVE ser a primeira chamada Streamlit
st.set_page_config(page_title="Segurança do Trabalho", page_icon="🦺", layout="wide")

from requests_oauthlib import OAuth2Session  # noqa: E402

import acesso  # noqa: E402
import banco  # noqa: E402
import menu  # noqa: E402
import pagina_presenca  # noqa: E402
from estilo import CSS_BASE_CLARA, CSS_INTERNO, CSS_LOGIN, URL_LOGO_BRANCO, sair  # noqa: E402

st.markdown(CSS_BASE_CLARA, unsafe_allow_html=True)


# ================================================
# CONTROLE DE ACESSO
# ================================================
# Quem entra e quais filiais vê: acesso.py (ADMINS no código + tabela
# segtrabalho_usuario). Além disso, só e-mail @dellavolpe.com.br.
DOMINIO = "@dellavolpe.com.br"


# ================================================
# AUTENTICAÇÃO AZURE AD (INLINE)
# ================================================
# Mesmo fluxo do Metas TDV. O estado do login fica SÓ em st.session_state
# (isolado por usuário): guardar em variável de módulo compartilha o login
# entre todas as sessões do processo.
GRAPH_ME = "https://graph.microsoft.com/v1.0/me"
SCOPE = ["openid", "email", "profile", "https://graph.microsoft.com/User.Read"]


def config_azure() -> dict:
    return {
        "client_id": st.secrets["AZURE_CLIENT_ID"],
        "client_secret": st.secrets["AZURE_CLIENT_SECRET"],
        "redirect_uri": st.secrets["AZURE_REDIRECT_URI"],
        "auth_url": st.secrets["AZURE_AUTH_URL"],
        "token_url": st.secrets["AZURE_TOKEN_URL"],
    }


def url_de_login(cfg: dict) -> str:
    azure = OAuth2Session(cfg["client_id"], scope=SCOPE, redirect_uri=cfg["redirect_uri"])
    url, _estado = azure.authorization_url(cfg["auth_url"], prompt="select_account")
    return url


def tela_login(cfg: dict) -> None:
    st.markdown(CSS_LOGIN, unsafe_allow_html=True)
    _, meio, _ = st.columns([1, 2, 1])
    with meio:
        st.image(URL_LOGO_BRANCO)
    _, centro, _ = st.columns([1, 1, 1])
    with centro:
        # Aqui o link é correto: ainda não há sessão a preservar.
        st.markdown(
            f'<div class="center-container"><a href="{url_de_login(cfg)}" '
            'class="custom-login-btn">🔐 Login com Microsoft</a></div>',
            unsafe_allow_html=True,
        )
    st.stop()


def autenticar() -> dict:
    """Devolve {'nome', 'email', 'cargo'} do usuário logado, ou para na tela de login."""
    cfg = config_azure()
    st.session_state.setdefault("token", None)

    # Token vencido: pede login de novo em vez de seguir com uma sessão morta.
    token = st.session_state["token"]
    if token and token.get("expires_at", float("inf")) < time.time():
        sair()
        st.session_state["token"] = None

    # Volta do Azure com ?code=...
    codigo = st.query_params.get("code")
    if codigo and st.session_state["token"] is None:
        azure = OAuth2Session(cfg["client_id"], redirect_uri=cfg["redirect_uri"], scope=SCOPE)
        try:
            st.session_state["token"] = azure.fetch_token(
                cfg["token_url"], client_secret=cfg["client_secret"], code=codigo
            )
        except Exception as erro:
            st.query_params.clear()
            if "Scope has changed" in str(erro):
                st.warning("Escopos alterados. É necessário iniciar um novo login.")
                st.link_button("🔐 Iniciar novo login", url_de_login(cfg))
            else:
                st.error(f"Erro ao obter token: {erro}")
            st.stop()
        st.query_params.clear()
        st.rerun()

    if st.session_state["token"] is None:
        tela_login(cfg)

    # Perfil do Graph: uma vez por sessão, não a cada clique.
    if "usuario" not in st.session_state:
        azure = OAuth2Session(cfg["client_id"], token=st.session_state["token"])
        resposta = azure.get(GRAPH_ME)
        if resposta.status_code != 200:
            st.error(f"Falha ao obter perfil do usuário ({resposta.status_code}): {resposta.text}")
            st.button("🔐 Entrar novamente", on_click=sair)
            st.stop()
        info = resposta.json()
        email = (info.get("mail") or info.get("userPrincipalName") or "").strip().lower()
        if not email:
            st.error("Não foi possível identificar seu e-mail no Azure AD.")
            st.stop()
        st.session_state["usuario"] = {
            "nome": info.get("displayName") or "Usuário",
            "email": email,
            "cargo": info.get("jobTitle") or "",
        }
    return st.session_state["usuario"]


# Presença por QR Code: a única tela sem login (motorista agregado e terceiro
# não têm conta da empresa). Só registra a pessoa na lista aberta pelo TST.
codigo_presenca = st.query_params.get("presenca")
if codigo_presenca:
    pagina_presenca.tela(codigo_presenca)
    st.stop()

usuario = autenticar()

url_sb, key_sb = banco.credenciais()
if not url_sb or not key_sb:
    st.markdown(CSS_INTERNO, unsafe_allow_html=True)
    st.error("SUPABASE_URL e/ou SUPABASE_KEY não encontrados em st.secrets — nada vai gravar.")
    st.stop()

# Filiais do usuário: lidas uma vez por sessão (o "Sair" limpa)
if "perfil" not in st.session_state:
    st.session_state["perfil"] = acesso.carregar_perfil(usuario["email"])
perfil = st.session_state["perfil"]

if not usuario["email"].endswith(DOMINIO) or not (perfil["admin"] or perfil["codigos"]):
    st.markdown(CSS_INTERNO, unsafe_allow_html=True)
    st.error("Seu usuário não tem acesso a este app. Fale com o SESMT.")
    st.caption(f"E-mail identificado: {usuario['email']}")
    st.button("Sair", on_click=sair)
    st.stop()

menu.rodar(usuario)
