# -*- coding: utf-8 -*-
# ================================================
# FORMULÁRIO DE UPLOAD — ITENS SAP -> SUPABASE
# Della Volpe | Setor de B.I.
# Mesmo padrão do Script_Estadia.py (Azure AD + Supabase + MinIO)
# ================================================
import streamlit as st

st.set_page_config(
    page_title="Upload de Itens SAP",
    page_icon="📤",
    layout="wide",
    initial_sidebar_state="collapsed"
)

import pandas as pd
import numpy as np
import os
import sys
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
import hashlib
import tempfile   # usado só pelo arquivamento no MinIO (hoje desativado)
import re
import unicodedata
import subprocess
from datetime import date, datetime
from pathlib import Path

# ================================================
# MODO LOCAL (teste sem Azure / Supabase / MinIO)
# ================================================
# Ative com a variável de ambiente UPLOAD_LOCAL=1 (veja rodar_local.bat).
# Em modo local: login falso e dados em .local_data/.
MODO_LOCAL = os.getenv("UPLOAD_LOCAL", "").strip().lower() in ("1", "true", "sim")


# ================================================
# MANUTENÇÃO — pausa o formulário sem mexer no código
# ================================================
def _segredo(nome, padrao=""):
    """
    Lê um segredo do Streamlit Cloud, caindo para variável de ambiente.

    `st.secrets` estoura quando não existe arquivo de segredos (é o caso da
    máquina local), então a leitura vai dentro de try.
    """
    try:
        if nome in st.secrets:
            return str(st.secrets[nome])
    except Exception:
        pass
    return os.getenv(nome, padrao)


# Para PAUSAR o formulário: crie o segredo MANUTENCAO = "1" no painel do
# Streamlit Cloud (Settings -> Secrets). O app reinicia sozinho ao salvar e
# para AQUI, antes de abrir qualquer conexão com o Supabase — nenhuma sessão
# aberta continua consultando ou gravando. Para liberar, apague o segredo
# (ou ponha "0"). MANUTENCAO_AVISO troca o texto mostrado na tela.
EM_MANUTENCAO = _segredo("MANUTENCAO").strip().lower() in ("1", "true", "sim")

if EM_MANUTENCAO and not MODO_LOCAL:
    st.title("🛠️ Formulário em manutenção")
    st.warning(
        _segredo("MANUTENCAO_AVISO")
        or "O envio de itens está **temporariamente pausado** pelo setor de "
           "B.I. Nenhum dado é consultado ou gravado enquanto esta mensagem "
           "estiver no ar. Guarde a sua planilha e tente de novo mais tarde."
    )
    st.caption("Se precisar enviar algo com urgência, procure o setor de B.I.")
    st.stop()

# ================================================
# 1) CONFIGURAÇÃO DA BASE PADRÃO  <<< AJUSTE AQUI >>>
# ================================================
# Tabelas no Supabase
TABELA_DADOS    = "upload_itens_sap"          # onde os dados são consolidados
TABELA_LOTES    = "upload_lotes"              # log de cada envio (auditoria/estorno)
# Não há tabela de usuários: quem pode usar o app é definido pelo login do
# Azure AD (só @dellavolpe.com.br entra). O e-mail e a data de cada envio
# ficam gravados na própria linha do registro.

# Bucket do MinIO onde o arquivo original ficaria arquivado.
# O arquivamento está DESATIVADO — a constante fica aqui para o dia em que for
# reativado (o bucket precisa existir no MinIO antes).
BUCKET_ARQUIVOS = "uploads"

# Aba da planilha que será lida (None = primeira aba)
ABA_EXCEL = None

# Como gravar:
#   "insert" -> sempre insere (pode duplicar)
#   "upsert" -> insere ou atualiza pela CHAVE_UNICA (exige UNIQUE no banco)
MODO_GRAVACAO = "upsert"

# Chave de negócio: deduplica dentro do arquivo e resolve o upsert no Supabase.
#
# A tabela guarda o HISTÓRICO: o mesmo documento aparece várias vezes, uma por
# mudança de situação. O que não pode existir é o mesmo documento repetindo a
# MESMA categoria + MESMO status na MESMA data — isso é registro redundante, e o
# app avisa quando encontra (no arquivo ou já gravado).
#
# A CATEGORIA entra na chave de propósito: sem ela, uma linha que mudasse só de
# categoria (mesmo status, mesma data) sobrescreveria a anterior e o histórico
# perderia a mudança. Se preferir que categoria seja apenas um atributo, tire-a
# daqui E do índice ux_itens_sap_chave no supabase_ddl.sql — os dois têm de
# combinar, na mesma ordem.
CHAVE_UNICA = ["lancamento_contabil", "data_documento",
               "categoria", "status", "data_status"]

# Quantidade de linhas por request ao Supabase
TAMANHO_LOTE = 2000
# Abaixo disto um pedaço recusado não é partido de novo: o erro é outro.
TAMANHO_LOTE_MINIMO = 100
# Quantos pedaços são gravados ao mesmo tempo. 1 desliga a simultaneidade.
GRAVACOES_SIMULTANEAS = 4
# Lançamentos por consulta quando a conferência vai pelo caminho filtrado.
BLOCO_LANCAMENTOS = 200

# ---------------------------------------------------------------
# 1.a) COLUNAS ESSENCIAIS — são ESTAS que vão para o Supabase.
#      Se faltar alguma, o envio é BLOQUEADO.
#
#   coluna      -> nome da coluna no Supabase (snake_case)
#   titulo      -> cabeçalho exatamente como sai da exportação SAPUI5
#   tipo        -> texto | inteiro | decimal | data | datahora | booleano
#   obrigatorio -> True exige valor preenchido em toda linha
#   dominio     -> lista fixa de valores aceitos (opcional)
#   cadastro    -> "categoria" ou "status": o valor precisa EXISTIR no cadastro
#                  da tela "🏷️ Categorias e Status". Vale a escrita oficial do
#                  cadastro — o arquivo pode vir sem acento ou com outra caixa
#                  que o app normaliza. Valor não cadastrado retém a linha e o
#                  app diz exatamente qual palavra precisa ser cadastrada.
#   retem_linha -> só vale com obrigatorio=True. Em branco, a linha NÃO é um erro
#                  que barra o arquivo: ela fica RETIDA (não sobe) e as demais
#                  seguem normalmente. É o caso de CATEGORIA/STATUS/DATA_STATUS,
#                  que saem vazios do SAP e são preenchidos aos poucos.
# ---------------------------------------------------------------
COLUNAS = [
    {"coluna": "categoria",           "titulo": "CATEGORIA",           "tipo": "texto", "obrigatorio": True,  "retem_linha": True, "cadastro": "categoria", "exemplo": "Registrado"},
    {"coluna": "status",              "titulo": "STATUS",              "tipo": "texto", "obrigatorio": True,  "retem_linha": True, "cadastro": "status",    "exemplo": "Titulo pago"},
    {"coluna": "data_status",         "titulo": "DATA_STATUS",         "tipo": "data",  "obrigatorio": True,  "retem_linha": True, "exemplo": "04/09/2026"},
    {"coluna": "cliente",             "titulo": "Cliente",             "tipo": "texto", "obrigatorio": True,  "exemplo": "1000050410"},
    # O CNPJ PODE vir vazio — e isso não impede o cruzamento: o de-para tem
    # entradas justamente para a trinca com CNPJ em branco (865 delas na
    # BASE_BPS). Vazio de um lado casa com vazio do outro.
    {"coluna": "id_fiscal_1",         "titulo": "Nº ID fiscal 1",      "tipo": "documento", "obrigatorio": False, "exemplo": "60561800004109"},
    {"coluna": "nome_cliente",        "titulo": "Nome do cliente",     "tipo": "texto", "obrigatorio": True,  "exemplo": "NOVELIS DO BRASIL LTDA"},
    {"coluna": "lancamento_contabil", "titulo": "Lançamento contábil", "tipo": "texto", "obrigatorio": True,  "exemplo": "90566896"},
    {"coluna": "data_documento",      "titulo": "Data do documento",   "tipo": "data",  "obrigatorio": True,  "exemplo": "16/08/2026"},
]

# ---------------------------------------------------------------
# 1.b) COLUNAS DE FORMATO — assinatura da exportação SAPUI5.
#      NÃO vão para o Supabase. Servem só para reconhecer a planilha:
#      se faltarem, o app avisa e pede confirmação explícita do usuário
#      antes de deixar enviar (não bloqueia).
# ---------------------------------------------------------------
COLUNAS_FORMATO = [
    "Bloqueio pgto.item",
    "Tipo lçto.contábil",
    "Nº do documento SD",
    "Referência",
    "Data vencimento líq.",
    "Montante (ME)",
    "Cidade",
]

# Ordem em que as colunas saem da exportação SAPUI5 — usada só para gerar o
# arquivo-modelo parecido com o real. A ordem do arquivo enviado não importa.
ORDEM_PLANILHA = [
    "Bloqueio pgto.item", "Tipo lçto.contábil", "Nº do documento SD",
    "Lançamento contábil", "Referência", "Data do documento",
    "Data vencimento líq.", "Montante (ME)", "Cliente",
    "Nº ID fiscal 1", "Nome do cliente", "Cidade",
    "CATEGORIA", "STATUS", "DATA_STATUS",
]

# ---------------------------------------------------------------
# 1.d) CATEGORIAS E STATUS — vocabulário controlado
#
# As duas listas ficam na MESMA tabela, separadas pela coluna `tipo`: são
# cadastros idênticos em estrutura (nome + definição) e assim o CRUD, o log e
# a validação são um só código.
#
# Um item do SAP só sobe se a sua CATEGORIA e o seu STATUS estiverem aqui.
# ---------------------------------------------------------------
TABELA_DOMINIOS = "upload_dominios"

TIPOS_DOMINIO = {
    "categoria": {"titulo": "Categoria", "plural": "Categorias", "icone": "📋"},
    "status":    {"titulo": "Status",    "plural": "Status",     "icone": "🏷️"},
}

# ---------------------------------------------------------------
# 1.e) VALOR CORRETO DO CTE
#
# Planilha à parte (ex.: "AVB_valores corretos.xlsx"), em que o validador
# informa qual é o valor correto de cada CT-e. Da planilha só interessam
# 4 colunas; o resto é apoio de conferência e é ignorado.
#
# A chave é o ID CTE. Reenviar o mesmo ID ATUALIZA o valor — e a tela
# mostra, antes de gravar, exatamente quais valores vão mudar e de quanto
# para quanto. Cada mudança vira uma linha no histórico.
# ---------------------------------------------------------------
TABELA_VALORES_CTE = "upload_valores_cte"

COLUNAS_VALOR_CTE = [
    {"coluna": "id_cte",            "titulo": "ID CTE",                    "tipo": "texto",   "obrigatorio": True},
    {"coluna": "data_documento",    "titulo": "Data do documento",         "tipo": "data",    "obrigatorio": False},
    {"coluna": "montante_original", "titulo": "Montante (ME)",             "tipo": "decimal", "obrigatorio": False},
    {"coluna": "valor_correto",     "titulo": "CONFIRMAR VALOR VALIDADOR", "tipo": "decimal", "obrigatorio": True},
]

# A coluna do valor aceita UM texto no lugar do número: "EM ANALISE". Ele NÃO
# barra a linha — ela SOBE, com `valor_correto` vazio e a `situacao` guardando
# o motivo. É assim que dá para medir quanto ainda falta verificar.
#
# Por que uma coluna à parte e não "valor zero": zero é um valor legítimo em
# dinheiro. Gravar 0 confundiria "o valor correto é R$ 0,00" com "ninguém
# analisou ainda", e estragaria qualquer soma ou média.
#
# A comparação ignora acento e caixa, então "em análise", "EM ANALISE" e
# "Em Analise" são o mesmo. QUALQUER OUTRO texto é escrita errada
# ("VERIFICANDO", "SEM INFORMAÇÃO", "aguardando"...): a linha fica retida e a
# tela pede correção, dizendo qual texto foi usado e em quantas linhas.
VALORES_CTE_TEXTO_ACEITO = ["EM ANALISE"]

# Situação de quem TEM valor informado.
SITUACAO_CTE_CONFIRMADO = "CONFIRMADO"

# ---------------------------------------------------------------
# 1.c) DE-PARA BPS — cadastro auxiliar (CRUD próprio no formulário)
#
# Para cada conjunto (Cliente, Nº ID fiscal 1, Nome do cliente) existe um
# de-para com 6 atributos comerciais. É a mesma trinca que identifica o
# cliente na exportação SAPUI5, então dá para cruzar as duas bases.
#
# Na planilha original (BASE_BPS.xlsx) a coluna "ID" é só a concatenação
# dessa trinca — o app recalcula, não depende dela.
# ---------------------------------------------------------------
TABELA_DEPARA     = "upload_depara_bps"
TABELA_DEPARA_LOG = "upload_depara_log"

# A trinca que identifica o registro. Vazio é gravado como "" (nunca NULL),
# senão o índice único do Postgres não pega duplicata — NULL nunca é igual a
# NULL. Na base real 865 registros não têm CNPJ e 1 não tem código de cliente.
CHAVE_DEPARA = ["cliente", "id_fiscal_1", "nome_cliente"]

CAMPOS_CHAVE_DEPARA = [
    {"coluna": "cliente",      "titulo": "Cliente",        "ajuda": "código SAP do cliente"},
    {"coluna": "id_fiscal_1",  "titulo": "Nº ID fiscal 1", "ajuda": "CNPJ — pode ficar vazio"},
    {"coluna": "nome_cliente", "titulo": "Nome do cliente", "ajuda": "obrigatório"},
]

CAMPOS_DEPARA = [
    {"coluna": "carteira",                "titulo": "CARTEIRA",                "sugerir": True},
    {"coluna": "cliente_grupo",           "titulo": "CLIENTE",                 "sugerir": True},
    {"coluna": "contrato",                "titulo": "CONTRATO",                "sugerir": False},
    {"coluna": "responsavel_cobranca",    "titulo": "RESPONSAVEL COBRANCA",    "sugerir": True},
    {"coluna": "responsavel_faturamento", "titulo": "RESPONSAVEL FATURAMENTO", "sugerir": True},
    {"coluna": "tipo_fatura",             "titulo": "TIPO DE FATURA",          "sugerir": True},
]
# "sugerir" = o campo repete muito (CARTEIRA tem 6 valores distintos em 4.205
# linhas, TIPO DE FATURA tem 3). A tela oferece os valores já usados numa lista,
# com a opção de digitar um novo — evita que um erro de digitação crie uma
# "carteira" nova e fragmente o de-para.

# ================================================
# 2) MÓDULOS INTERNOS (Supabase / MinIO)
# ================================================
# O MinIO está desativado (ver "ARQUIVAMENTO NO MinIO DESATIVADO" em
# gravar_lote). Os dois imports dele ficam comentados — reative os três pontos
# juntos: o import daqui, o bloco em gravar_lote e `minio` no requirements.txt.
if MODO_LOCAL:
    # Sem Supabase: tudo vai para .local_data/ (ver backend_local.py).
    from backend_local import ConectionSupaBase
    # from backend_local import meu_minio
    import backend_local
else:
    modulos_dir = Path(__file__).parent / "Modulos"
    if not modulos_dir.exists():
        subprocess.run([
            "git", "clone",
            "https://github.com/DellaVolpe69/Modulos.git",
            str(modulos_dir)
        ], check=True)
    if str(modulos_dir) not in sys.path:
        sys.path.insert(0, str(modulos_dir))
    from Modulos import ConectionSupaBase
    # import Modulos.Minio.examples.MinIO as meu_minio

# ================================================
# 4) AZURE AD OAUTH2
# ================================================
url_imagem = "https://raw.githubusercontent.com/DellaVolpe69/Images/main/AppBackground02.png"
url_logo   = "https://raw.githubusercontent.com/DellaVolpe69/Images/main/DellaVolpeLogoBranco.png"


def autenticar_azure():
    """Fluxo OAuth2 do Azure AD. Retorna (nome, email) do usuário logado."""
    from requests_oauthlib import OAuth2Session
    client_id              = st.secrets["AZURE_CLIENT_ID"]
    client_secret          = st.secrets["AZURE_CLIENT_SECRET"]
    redirect_uri           = st.secrets["AZURE_REDIRECT_URI"]
    authorization_base_url = st.secrets["AZURE_AUTH_URL"]
    token_url              = st.secrets["AZURE_TOKEN_URL"]
    scope = [
        "openid",
        "email",
        "profile",
        "https://graph.microsoft.com/User.Read",
    ]

    if "token" not in st.session_state:
        st.session_state["token"] = None

    query_params = st.query_params
    if "code" in query_params and st.session_state["token"] is None:
        code = query_params["code"]
        azure = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scope)
        try:
            token = azure.fetch_token(token_url, client_secret=client_secret, code=code)
            st.session_state["token"] = token
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao obter token: {e}")
            st.session_state["token"] = None
            st.rerun()

    if st.session_state["token"] is not None:
        from oauthlib.oauth2 import TokenExpiredError
        try:
            azure = OAuth2Session(client_id, token=st.session_state["token"])
            test_resp = azure.get("https://graph.microsoft.com/v1.0/me")
            if test_resp.status_code == 401:
                raise TokenExpiredError()
        except TokenExpiredError:
            st.session_state["token"] = None
            st.rerun()
        except Exception:
            pass

    if st.session_state["token"] is None:
        azure = OAuth2Session(client_id, scope=scope, redirect_uri=redirect_uri)
        authorization_url, state = azure.authorization_url(authorization_base_url, prompt="select_account")
        st.markdown(f"""
            <style>
            .stApp {{
                background: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)), url("{url_imagem}");
                background-size: cover;
            }}
            </style>
        """, unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            st.image(url_logo)
        esp1, centro, esp2 = st.columns([1, 1, 1])
        with centro:
            st.markdown("""
                <style>
                .custom-login-btn {
                    background-color: #FF5D01 !important; color: white !important;
                    border: 2px solid white !important; padding: 0.6em 1.2em;
                    border-radius: 10px !important; font-size: 1rem; font-weight: 500;
                    cursor: pointer; transition: 0.2s ease;
                    text-decoration: none !important; display: inline-block;
                }
                .custom-login-btn:hover {
                    background-color: white !important; color: #FF5D01 !important;
                    transform: scale(1.03); border: 2px solid #FF5D01 !important;
                }
                .center-container { text-align: center; margin-top: 10px; }
                </style>
            """, unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="center-container">
                    <a href="{authorization_url}" class="custom-login-btn">🔐 Login com Microsoft</a>
                </div>
                """,
                unsafe_allow_html=True
            )
        st.stop()

    # ================================================
    # 5) USUÁRIO AUTENTICADO
    # ================================================
    azure = OAuth2Session(client_id, token=st.session_state["token"])
    me_resp = azure.get("https://graph.microsoft.com/v1.0/me")
    if me_resp.status_code != 200:
        st.error(f"Falha ao obter perfil do usuário ({me_resp.status_code}): {me_resp.text}")
        st.stop()

    user_info  = me_resp.json()
    user_name  = user_info.get("displayName", "Usuário")
    user_email = (user_info.get("mail") or user_info.get("userPrincipalName") or "desconhecido")
    if isinstance(user_email, str):
        user_email = user_email.lower()
    if not isinstance(user_email, str) or not user_email.endswith("@dellavolpe.com.br"):
        st.error("Acesso restrito a usuários @dellavolpe.com.br.")
        st.stop()

    return user_name, user_email


if MODO_LOCAL:
    user_name  = os.getenv("UPLOAD_LOCAL_NOME", "Usuário de Teste")
    user_email = os.getenv("UPLOAD_LOCAL_EMAIL", "teste@dellavolpe.com.br").lower()
else:
    user_name, user_email = autenticar_azure()

# Sem cadastro nem nível: quem passou pelo login do Azure AD com e-mail
# @dellavolpe.com.br já está autorizado a usar o formulário.
st.session_state.user_real_name = user_name

# ================================================
# 6) CONFIG VISUAL (padrão Della Volpe)
# ================================================
st.markdown(f"""
    <style>
        header,[data-testid="stHeader"] {{ background: transparent; }}
        :root {{
            --primary-color: #FF5D01;
            --background-color: #0E1117;
            --secondary-background-color: #262730;
            --text-color: #FAFAFA;
        }}
        [data-testid="stAppViewContainer"] {{
            background: linear-gradient(rgba(0,0,0,0.75), rgba(0,0,0,0.75)),
                        url("{url_imagem}") !important;
            background-size: cover !important;
            background-position: center !important;
            background-attachment: fixed !important;
        }}
        input, textarea {{
            border: 1px solid white !important;
            border-radius: 5px !important;
            color: white !important;
        }}
        .stSelectbox div[data-baseweb="select"] > div {{
            border: 1px solid white !important;
            border-radius: 5px !important;
            color: white !important;
        }}
        .stButton > button, .stDownloadButton > button {{
            background-color: #FF5D01 !important;
            color: white !important;
            border: 2px solid white !important;
            padding: .6em 1.2em;
            border-radius: 10px !important;
            font-size: 1rem;
            font-weight: 500;
        }}
        .stButton > button:hover, .stDownloadButton > button:hover {{
            background-color: white !important;
            color: #FF5D01 !important;
            transform: scale(1.03);
            border: 2px solid #FF5D01 !important;
        }}
        [data-testid="stFileUploaderDropzone"] {{
            border: 2px dashed #FF5D01 !important;
            background-color: rgba(38,39,48,0.75) !important;
            border-radius: 10px !important;
        }}
        .card-kpi {{
            background: rgba(38,39,48,0.88);
            border-left: 5px solid #FF5D01;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 10px;
        }}
        .card-kpi .rotulo {{
            color: #bbb; font-size: .72rem; text-transform: uppercase;
            letter-spacing: .5px; font-weight: 700;
        }}
        .card-kpi .valor {{ color: #fff; font-size: 1.6rem; font-weight: 700; }}
        .footer {{
            position: fixed; left: 0; bottom: 0; width: 100%;
            background: rgba(0,0,0,0.6); color: white;
            text-align: center; font-size: 13px; padding: 6px 0; z-index: 999;
        }}
        /* Folga no fim da página para o rodapé fixo não cobrir a última linha
           das tabelas. */
        .block-container {{ padding-bottom: 70px !important; }}
    </style>
    <div class="footer">© 2026 <b>Della Volpe</b> | Setor de B.I.</div>
""", unsafe_allow_html=True)


def kpi(rotulo, valor):
    st.markdown(
        f"""<div class="card-kpi"><div class="rotulo">{rotulo}</div>
            <div class="valor">{valor}</div></div>""",
        unsafe_allow_html=True
    )


# ================================================
# 7) FUNÇÕES AUXILIARES — MODELO E VALIDAÇÃO
# ================================================
def normalizar_texto(texto):
    """Remove acentos, espaços extras e caixa — usado p/ casar cabeçalhos."""
    if texto is None:
        return ""
    txt = str(texto)
    nfkd = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(txt.split()).strip().lower()


def canonizar_documento(valor):
    """
    Deixa CNPJ/CPF num formato único: só dígitos, completado com zeros à
    esquerda até 14.

    É isto que faz as duas bases conversarem. Na BASE_BPS os 3.340 CNPJs têm
    todos 14 dígitos (958 começam com zero). Já na exportação do SAP o Excel
    costuma guardar esse campo como NÚMERO — e número não tem zero à esquerda.
    Resultado: o mesmo cliente chegava como `924429000175` de um lado e
    `00924429000175` do outro, e o cruzamento não achava nada.

    Vazio continua vazio: 865 registros do de-para não têm CNPJ e não podem
    virar `00000000000000`.
    """
    digitos = re.sub(r"\D", "", "" if valor is None else str(valor))
    if not digitos:
        return ""
    return digitos.zfill(14) if len(digitos) <= 14 else digitos


def normalizar_nome(valor):
    """
    Nome do cliente para fins de COMPARAÇÃO: sem acento, sem pontuação, caixa e
    espaços uniformes. O nome é GRAVADO como veio — isto vale só no cruzamento.

    Na BASE_BPS isso funde 24 trincas que diferem apenas por "LTDA" vs "LTDA."
    ou por uma vírgula; nenhuma delas tem de-para divergente, então fundir é
    seguro e faz o item casar mesmo quando o SAP escreve o nome de outro jeito.
    """
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalizar_texto(valor)).split())


EXEMPLOS_FORMATO = {
    "Bloqueio pgto.item": "", "Tipo lçto.contábil": "RV",
    "Nº do documento SD": "91313245", "Referência": "000455525-001",
    "Data vencimento líq.": "14/12/2026", "Montante (ME)": 269.74,
    "Cidade": "PINDAMONHANGABA",
}


def gerar_modelo_xlsx():
    """
    Monta o arquivo-modelo em memória, com as 14 colunas na ordem da exportação
    SAPUI5 — as 7 essenciais mais as 7 de formato, para o arquivo ficar igual ao
    que sai do SAP.
    """
    por_titulo = {c["titulo"]: c for c in COLUNAS}
    linha = {}
    for titulo in ORDEM_PLANILHA:
        if titulo in por_titulo:
            linha[titulo] = por_titulo[titulo].get("exemplo", "")
        else:
            linha[titulo] = EXEMPLOS_FORMATO.get(titulo, "")
    df_modelo = pd.DataFrame([linha])[ORDEM_PLANILHA]

    instrucoes = []
    for titulo in ORDEM_PLANILHA:
        spec = por_titulo.get(titulo)
        if spec:
            instrucoes.append({
                "Coluna": titulo,
                "Vai para o banco?": "SIM",
                "Tipo": spec["tipo"],
                "Obrigatório": "SIM" if spec.get("obrigatorio") else "não",
                "Valores aceitos": ", ".join(spec["dominio"]) if spec.get("dominio") else "—",
                "Exemplo": spec.get("exemplo", ""),
            })
        else:
            instrucoes.append({
                "Coluna": titulo,
                "Vai para o banco?": "não — só identifica o formato",
                "Tipo": "—",
                "Obrigatório": "não (mas a falta pede confirmação)",
                "Valores aceitos": "—",
                "Exemplo": EXEMPLOS_FORMATO.get(titulo, ""),
            })
    df_instrucoes = pd.DataFrame(instrucoes)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_modelo.to_excel(writer, index=False, sheet_name="Dados")
        df_instrucoes.to_excel(writer, index=False, sheet_name="Instruções")
        for aba, df_ref in (("Dados", df_modelo), ("Instruções", df_instrucoes)):
            ws = writer.sheets[aba]
            for i, col in enumerate(df_ref.columns, start=1):
                largura = max(len(str(col)) + 4,
                              *(len(str(v)) + 4 for v in df_ref[col].astype(str)))
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(largura, 45)
    buffer.seek(0)
    return buffer.getvalue()


def df_para_xlsx(df, nome_aba="Dados"):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=nome_aba)
    buffer.seek(0)
    return buffer.getvalue()


def _vazio(valor):
    """True para None/NaN/NaT/string em branco (tolerante a tipos exóticos)."""
    if valor is None:
        return True
    try:
        if pd.isna(valor):
            return True
    except (TypeError, ValueError):
        pass
    return str(valor).strip() == ""


def _converter_valor(valor, tipo):
    """Converte um valor para o tipo alvo. Retorna (valor, erro_ou_None)."""
    if _vazio(valor):
        return None, None
    texto = str(valor).strip()
    if texto == "":
        return None, None

    try:
        if tipo == "documento":
            # CNPJ/CPF: só dígitos, com zeros à esquerda até 14. Sem isto o
            # Excel (que guarda o campo como número) entrega 924429000175 e o
            # de-para tem 00924429000175 — o cruzamento não casaria.
            return canonizar_documento(texto), None

        if tipo == "texto":
            # Cliente, CNPJ e Lançamento contábil são números guardados como
            # texto. Se o Excel os gravar como numérico, str() devolveria
            # "90566896.0" e "6.05618e+13" — o que corromperia a chave.
            if isinstance(valor, (int, np.integer)) and not isinstance(valor, bool):
                return str(int(valor)), None
            if isinstance(valor, (float, np.floating)) and float(valor).is_integer():
                return str(int(valor)), None
            return texto, None

        if tipo == "inteiro":
            limpo = texto.replace(".", "").replace(",", ".")
            return int(round(float(limpo))), None

        if tipo == "decimal":
            limpo = texto.replace("R$", "").strip()
            # Formato brasileiro: 1.234,56 -> 1234.56
            if "," in limpo:
                limpo = limpo.replace(".", "").replace(",", ".")
            return float(limpo), None

        if tipo == "data":
            if isinstance(valor, (datetime, pd.Timestamp)):
                return valor.date().isoformat(), None
            if isinstance(valor, date):
                return valor.isoformat(), None
            dt = pd.to_datetime(texto, dayfirst=True, errors="raise")
            return dt.date().isoformat(), None

        if tipo == "datahora":
            if isinstance(valor, (datetime, pd.Timestamp)):
                return pd.Timestamp(valor).isoformat(), None
            dt = pd.to_datetime(texto, dayfirst=True, errors="raise")
            return dt.isoformat(), None

        if tipo == "booleano":
            normal = normalizar_texto(texto)
            if normal in ("sim", "s", "true", "verdadeiro", "1", "x"):
                return True, None
            if normal in ("nao", "n", "false", "falso", "0"):
                return False, None
            return None, "valor booleano inválido (use SIM/NÃO)"

    except Exception:
        return None, f"não é um valor válido para o tipo '{tipo}'"

    return texto, None


def titulo_de(coluna):
    """Cabeçalho da planilha correspondente a uma coluna do banco."""
    for spec in COLUNAS:
        if spec["coluna"] == coluna:
            return spec["titulo"]
    return coluna


def _resultado(df=None, erros=None, avisos=None, formato_ausente=None,
               retidas=None, duplicadas=None, nao_cadastrados=None):
    """Formato único de retorno da validação."""
    vazio = pd.DataFrame()
    return {
        "df": df,
        "erros": erros if erros is not None else pd.DataFrame(
            columns=["Linha", "Coluna", "Valor", "Problema"]),
        "avisos": avisos or [],
        "formato_ausente": formato_ausente or [],
        "retidas": retidas if retidas is not None else vazio,
        "duplicadas": duplicadas if duplicadas is not None else vazio,
        "nao_cadastrados": nao_cadastrados or {},
    }


def validar_planilha(df_bruto):
    """
    Valida o DataFrame lido da planilha. Retorna um dicionário com:
      df              -> linhas prontas para o Supabase (None se nada pode subir)
      erros           -> Linha / Coluna / Valor / Problema (se houver, barra tudo)
      avisos          -> mensagens informativas
      formato_ausente -> colunas de assinatura que não vieram (pedem confirmação)
      retidas         -> linhas sem STATUS/DATA_STATUS: não sobem, as outras sim
      duplicadas      -> linhas repetidas na CHAVE_UNICA dentro do arquivo
    """
    avisos = []
    erros = []
    retencoes = {}        # posição da linha -> colunas que a retêm
    # Os cadastros são lidos UMA vez, aqui. Já estiveram dentro do laço, num
    # dict.setdefault(chave, mapa_dominio(...)) — e o Python avalia o segundo
    # argumento SEMPRE, mesmo com a chave já presente. Resultado: mapa_dominio()
    # rodava uma vez por célula (403 mil vezes num arquivo de 200 mil linhas),
    # cada uma atravessando o @st.cache_data. Era 97% do tempo de validação.
    cadastros = {tipo: mapa_dominio(tipo)
                 for tipo in {c["cadastro"] for c in COLUNAS if c.get("cadastro")}}
    nao_cadastrados = {}  # {tipo: {valor escrito no arquivo: quantas linhas}}

    mapa_arquivo = {normalizar_texto(c): c for c in df_bruto.columns}

    # --- Assinatura do formato: só avisa, não bloqueia ---
    formato_ausente = [c for c in COLUNAS_FORMATO
                       if normalizar_texto(c) not in mapa_arquivo]

    # --- Casamento de cabeçalhos (tolerante a acento/caixa/espaço) ---
    faltando, renomear = [], {}
    for spec in COLUNAS:
        chave = normalizar_texto(spec["titulo"])
        chave_alt = normalizar_texto(spec["coluna"])
        origem = mapa_arquivo.get(chave) or mapa_arquivo.get(chave_alt)
        if origem is None:
            faltando.append(spec["titulo"])
        else:
            renomear[origem] = spec["coluna"]

    if faltando:
        return _resultado(erros=pd.DataFrame([{
            "Linha": "—", "Coluna": c, "Valor": "—",
            "Problema": "coluna essencial ausente na planilha"
        } for c in faltando]), avisos=avisos, formato_ausente=formato_ausente)

    extras = [c for c in df_bruto.columns if c not in renomear]
    if extras:
        avisos.append(
            "Colunas lidas mas não gravadas (só identificam o formato): "
            + ", ".join(map(str, extras))
        )

    df = df_bruto.rename(columns=renomear)[[s["coluna"] for s in COLUNAS]].copy()

    # Remove linhas 100% vazias (sobras do Excel)
    antes = len(df)
    df = df.dropna(how="all").reset_index(drop=True)
    if antes != len(df):
        avisos.append(f"{antes - len(df)} linha(s) totalmente vazia(s) descartada(s).")

    if df.empty:
        return _resultado(erros=pd.DataFrame([{
            "Linha": "—", "Coluna": "—", "Valor": "—",
            "Problema": "a planilha não tem nenhuma linha preenchida"
        }]), avisos=avisos, formato_ausente=formato_ausente)

    # Guarda o nº da linha no Excel (cabeçalho = 1)
    linhas_excel = [i + 2 for i in range(len(df))]

    # --- Conversão de tipos + obrigatoriedade + domínio ---
    for spec in COLUNAS:
        col, tipo, titulo = spec["coluna"], spec["tipo"], spec["titulo"]
        convertidos = []
        for pos, valor in enumerate(df[col].tolist()):
            novo, erro = _converter_valor(valor, tipo)
            if erro:
                erros.append({"Linha": linhas_excel[pos], "Coluna": titulo,
                              "Valor": valor, "Problema": erro})
                convertidos.append(None)
                continue
            if novo is None and spec.get("obrigatorio"):
                if spec.get("retem_linha"):
                    # Não é erro de arquivo: a linha só fica retida (ver abaixo).
                    retencoes.setdefault(pos, []).append(f"{titulo} (em branco)")
                else:
                    erros.append({"Linha": linhas_excel[pos], "Coluna": titulo,
                                  "Valor": "", "Problema": "campo obrigatório não preenchido"})
            if novo is not None and spec.get("dominio"):
                aceitos = {normalizar_texto(v): v for v in spec["dominio"]}
                chave = normalizar_texto(novo)
                if chave not in aceitos:
                    erros.append({"Linha": linhas_excel[pos], "Coluna": titulo, "Valor": novo,
                                  "Problema": f"valor fora da lista aceita ({', '.join(spec['dominio'])})"})
                else:
                    novo = aceitos[chave]  # normaliza para o valor oficial
            if novo is not None and spec.get("cadastro"):
                # O valor precisa existir no cadastro de Categorias/Status.
                # A comparação ignora acento, caixa e espaços; o que vai para o
                # banco é a escrita OFICIAL do cadastro.
                oficial = cadastros[spec["cadastro"]].get(normalizar_texto(novo))
                if oficial is None:
                    retencoes.setdefault(pos, []).append(f"{titulo} (não cadastrado)")
                    nao_cadastrados.setdefault(spec["cadastro"], {}).setdefault(
                        str(novo).strip(), 0)
                    nao_cadastrados[spec["cadastro"]][str(novo).strip()] += 1
                else:
                    novo = oficial
            convertidos.append(novo)
        df[col] = convertidos

    # --- Erro de verdade barra o arquivo inteiro, antes de qualquer envio ---
    if erros:
        return _resultado(
            erros=pd.DataFrame(erros, columns=["Linha", "Coluna", "Valor", "Problema"]),
            avisos=avisos, formato_ausente=formato_ausente)

    # --- Linhas RETIDAS: faltou STATUS e/ou DATA_STATUS ---
    # Não são erro. Ficam fora deste envio (o usuário preenche e reenvia depois);
    # todas as outras seguem normalmente para o Supabase.
    df_retidas = pd.DataFrame()
    if retencoes:
        linhas_ret = []
        for pos in sorted(retencoes):
            registro = {"Linha": linhas_excel[pos]}
            for col in CHAVE_UNICA:
                if col not in ("status", "data_status"):
                    registro[titulo_de(col)] = df.iloc[pos][col]
            registro["Nome do cliente"] = df.iloc[pos].get("nome_cliente")
            registro["Problema"] = ", ".join(retencoes[pos])
            linhas_ret.append(registro)
        df_retidas = pd.DataFrame(linhas_ret)

        df = df.drop(index=list(retencoes.keys())).reset_index(drop=True)
        linhas_excel = [n for i, n in enumerate(linhas_excel) if i not in retencoes]

    if df.empty:
        return _resultado(avisos=avisos, formato_ausente=formato_ausente,
                          retidas=df_retidas, nao_cadastrados=nao_cadastrados)

    # --- Repetidos na CHAVE_UNICA dentro do arquivo ---
    # A chave inclui STATUS e DATA_STATUS: o mesmo documento PODE aparecer várias
    # vezes com status diferentes. Repetir os 4 campos, porém, é registro
    # redundante — mantemos a última ocorrência e mostramos quais foram.
    df_duplicadas = pd.DataFrame()
    if CHAVE_UNICA:
        repetidas = df.duplicated(subset=CHAVE_UNICA, keep=False)
        if repetidas.any():
            linhas_dup = []
            for pos in np.where(repetidas)[0]:
                registro = {"Linha": linhas_excel[pos]}
                for col in CHAVE_UNICA:
                    registro[titulo_de(col)] = df.iloc[pos][col]
                registro["Situação"] = ("mantida (última)"
                                        if not df.duplicated(subset=CHAVE_UNICA, keep="last")[pos]
                                        else "descartada")
                linhas_dup.append(registro)
            df_duplicadas = pd.DataFrame(linhas_dup)

            descartar = df.duplicated(subset=CHAVE_UNICA, keep="last")
            df = df[~descartar].reset_index(drop=True)

    return _resultado(df=df, avisos=avisos, formato_ausente=formato_ausente,
                      retidas=df_retidas, duplicadas=df_duplicadas,
                      nao_cadastrados=nao_cadastrados)


def contar_linhas(tabela, apenas_ativas=True):
    """
    Quantas linhas a tabela tem, em UMA viagem.

    Com `count="exact"` o PostgREST devolve o total que casa com o filtro no
    cabeçalho Content-Range, e `.limit(1)` evita trazer as linhas junto.
    """
    consulta = (ConectionSupaBase.conexao().table(tabela)
                .select("id", count="exact"))
    if apenas_ativas:
        consulta = consulta.eq("excluido", False)
    return consulta.limit(1).execute().count or 0


def consultar_existentes(df_pronto):
    """
    Procura no Supabase linhas que já tenham exatamente a mesma CHAVE_UNICA.

    O caro aqui não é a conta: é o número de VIAGENS ao servidor. Há dois
    caminhos para descobrir o que já está gravado, e o barato depende do
    tamanho do arquivo e do banco:

      • filtrar pelos lançamentos do arquivo, em blocos  -> distintos / 200
      • varrer a tabela inteira, de 1.000 em 1.000       -> linhas_banco / 1.000

    O código só conhecia o primeiro, e com 200 mil linhas ele pedia mais de
    mil viagens — minutos de espera só para montar um aviso. Agora perguntamos
    antes quantas linhas o banco tem (1 viagem) e escolhemos o menor dos dois.
    Se a tabela estiver vazia, não há o que procurar e saímos sem consulta
    nenhuma.

    Retorna um DataFrame com as linhas do arquivo que já existem no banco.
    """
    if df_pronto is None or df_pronto.empty or not CHAVE_UNICA:
        return pd.DataFrame()

    sb = ConectionSupaBase.conexao()
    lancamentos = sorted({str(v) for v in df_pronto["lancamento_contabil"].dropna()})
    chaves_banco = set()

    try:
        total_banco = contar_linhas(TABELA_DADOS)
        if total_banco == 0:
            return pd.DataFrame()

        def arredonda(valor, bloco):
            return -(-valor // bloco)        # divisão para cima

        custo_varredura = arredonda(total_banco, PAGINA_SUPABASE)
        custo_filtro = arredonda(len(lancamentos), BLOCO_LANCAMENTOS)

        if custo_varredura <= custo_filtro:
            paginas = [buscar_paginado(lambda: (
                sb.table(TABELA_DADOS)
                .select(",".join(CHAVE_UNICA))
                .eq("excluido", False)), teto=total_banco + PAGINA_SUPABASE)]
        else:
            paginas = []
            for i in range(0, len(lancamentos), BLOCO_LANCAMENTOS):
                fatia = lancamentos[i:i + BLOCO_LANCAMENTOS]
                # Pagina: um bloco de lançamentos pode render mais de 1.000
                # linhas (o mesmo documento aparece uma vez por status).
                paginas.append(buscar_paginado(lambda f=fatia: (
                    sb.table(TABELA_DADOS)
                    .select(",".join(CHAVE_UNICA))
                    .in_("lancamento_contabil", f)
                    .eq("excluido", False))))

        for achadas in paginas:
            for registro in achadas:
                chaves_banco.add(tuple(
                    None if registro.get(c) is None else str(registro.get(c))
                    for c in CHAVE_UNICA
                ))
    except Exception as e:
        # Não impede o envio: o upsert continua garantindo a unicidade.
        st.info(f"Não foi possível conferir duplicidades já gravadas ({e}).")
        return pd.DataFrame()

    if not chaves_banco:
        return pd.DataFrame()

    # Coluna a coluna, não linha a linha: `iterrows()` monta uma Series por
    # linha e, com 200 mil delas, sozinho já custava mais que a consulta.
    colunas = [df_pronto[c].tolist() for c in CHAVE_UNICA]
    repetidas = [pos for pos, valores in enumerate(zip(*colunas))
                 if tuple(None if v is None else str(v) for v in valores)
                 in chaves_banco]
    if not repetidas:
        return pd.DataFrame()

    achadas = df_pronto.iloc[repetidas][list(CHAVE_UNICA)]
    achadas.columns = [titulo_de(c) for c in CHAVE_UNICA]
    return achadas.reset_index(drop=True)


# ================================================
# 8) FUNÇÕES DE GRAVAÇÃO NO SUPABASE
# ================================================
def registros_para_json(df, lote_id):
    """Converte o DataFrame validado em lista de dicts prontos p/ o Supabase."""
    agora = datetime.now().isoformat()
    base = df.where(pd.notnull(df), None).to_dict(orient="records")
    saida = []
    for linha in base:
        limpo = {}
        for k, v in linha.items():
            if isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = None if pd.isna(v) else float(v)
            elif isinstance(v, (np.bool_,)):
                v = bool(v)
            elif isinstance(v, (pd.Timestamp, datetime, date)):
                v = v.isoformat()
            elif isinstance(v, float) and pd.isna(v):
                v = None
            limpo[k] = v
        limpo.update({
            "lote_id": lote_id,
            "criado_por_email": user_email,
            "criado_por_nome": st.session_state.get("user_real_name", user_name),
            "criado_em": agora,
            "excluido": False,
        })
        saida.append(limpo)
    return saida


def hash_arquivo(conteudo_bytes):
    return hashlib.sha256(conteudo_bytes).hexdigest()


def lote_ja_enviado(hash_hex):
    """Retorna o lote anterior com o mesmo hash de arquivo, se houver."""
    try:
        sb = ConectionSupaBase.conexao()
        res = (sb.table(TABELA_LOTES).select("*")
               .eq("hash_arquivo", hash_hex).eq("status", "efetivado").execute())
        return res.data[0] if res.data else None
    except Exception:
        return None


def _erro_de_tamanho(erro):
    """O servidor reclamou do TAMANHO do pedaço (ou demorou demais nele)?"""
    partes = [str(getattr(erro, campo, "") or "")
              for campo in ("code", "message", "details", "hint")]
    texto = " ".join(partes + [str(erro)]).lower()
    return any(p in texto for p in
               ("413", "too large", "timeout", "timed out", "504", "502",
                "57014", "canceling statement"))


def gravar_pedaco(pedaco):
    """
    Grava um pedaço e devolve quantas linhas foram.

    Cada chamada abre a SUA conexão: o cliente do supabase-py guarda estado e
    não foi feito para ser usado por várias threads ao mesmo tempo.

    Se o servidor recusar pelo tamanho — ou estourar o tempo —, o pedaço é
    partido ao meio e tentado de novo. Assim dá para mandar lotes grandes sem
    apostar que o servidor aguenta: ele mesmo dita o limite. Qualquer outro
    erro sobe na hora, sem retentativa, para não mascarar problema de dados.
    """
    sb = ConectionSupaBase.conexao()
    try:
        if MODO_GRAVACAO == "upsert" and CHAVE_UNICA:
            sb.table(TABELA_DADOS).upsert(
                pedaco, on_conflict=",".join(CHAVE_UNICA)).execute()
        else:
            sb.table(TABELA_DADOS).insert(pedaco).execute()
    except Exception as erro:
        if len(pedaco) <= TAMANHO_LOTE_MINIMO or not _erro_de_tamanho(erro):
            raise
        meio = len(pedaco) // 2
        gravar_pedaco(pedaco[:meio])
        gravar_pedaco(pedaco[meio:])
    return len(pedaco)


def gravar_lote(df_pronto, nome_arquivo, conteudo_bytes, formato_ausente=None, retidas=0):
    """Grava o lote inteiro no Supabase e arquiva o xlsx original no MinIO."""
    sb = ConectionSupaBase.conexao()
    lote_id = str(uuid.uuid4())
    total = len(df_pronto)

    # 1) Abre o lote como "processando" (se cair no meio, fica o rastro)
    sb.table(TABELA_LOTES).insert({
        "id": lote_id,
        "arquivo": nome_arquivo,
        "hash_arquivo": hash_arquivo(conteudo_bytes),
        "linhas": total,
        # Fica registrado que o usuário enviou uma planilha fora do formato
        # padrão e confirmou mesmo assim.
        "formato_ausente": ", ".join(formato_ausente) if formato_ausente else None,
        "linhas_retidas": int(retidas or 0),
        "status": "processando",
        "criado_por_email": user_email,
        "criado_por_nome": st.session_state.get("user_real_name", user_name),
        "criado_em": datetime.now().isoformat(),
    }).execute()

    registros = registros_para_json(df_pronto, lote_id)
    pedacos = [registros[i:i + TAMANHO_LOTE]
               for i in range(0, total, TAMANHO_LOTE)]
    barra = st.progress(0.0, text="Gravando no Supabase...")
    gravados = 0
    try:
        # Em paralelo: o tempo aqui é quase todo espera de rede, não cálculo.
        # Os pedaços não disputam linha nenhuma entre si — as chaves repetidas
        # dentro do arquivo já foram descartadas na validação.
        with ThreadPoolExecutor(max_workers=max(1, GRAVACOES_SIMULTANEAS)) as fila:
            for n in fila.map(gravar_pedaco, pedacos):
                gravados += n
                barra.progress(gravados / total,
                               text=f"Gravando... {gravados}/{total} linhas")
    except Exception as e:
        sb.table(TABELA_LOTES).update({
            "status": "erro", "mensagem": str(e)[:500]
        }).eq("id", lote_id).execute()
        barra.empty()
        raise

    barra.progress(1.0, text="Finalizando...")

    # 2) ARQUIVAMENTO NO MinIO DESATIVADO (a pedido).
    #    Para reativar: descomente o bloco abaixo E o import de `meu_minio`
    #    na seção "2) MÓDULOS INTERNOS", e devolva `minio` ao requirements.txt.
    #    O bucket BUCKET_ARQUIVOS precisa existir antes.
    destino = None
    # try:
    #     ext = nome_arquivo.split(".")[-1]
    #     destino = f"{datetime.now():%Y/%m}/{lote_id} - {nome_arquivo}"
    #     with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
    #         tmp.write(conteudo_bytes)
    #         tmp_path = tmp.name
    #     meu_minio.upload(object_name=destino, bucket_name=BUCKET_ARQUIVOS, file_path=tmp_path)
    #     os.remove(tmp_path)
    # except Exception as e:
    #     destino = None
    #     st.warning(f"Dados gravados, mas não foi possível arquivar o arquivo no MinIO: {e}")

    # 3) Fecha o lote
    sb.table(TABELA_LOTES).update({
        "status": "efetivado",
        "arquivo_minio": destino,
    }).eq("id", lote_id).execute()

    barra.empty()
    return lote_id


# ESTORNO DESATIVADO (a pedido). Descomente para reativar — a tela que usa
# esta função está comentada na página "Envios".
# def estornar_lote(lote_id):
    # """
    # Desfaz um envio inteiro (soft delete das linhas + marca o lote).
    # Retorna quantas linhas foram realmente marcadas.

    # Atenção: com MODO_GRAVACAO='upsert', uma linha pertence ao ÚLTIMO lote que a
    # tocou. Se um envio posterior sobrescreveu as mesmas chaves, o estorno do lote
    # antigo não encontra mais nada — e não há como restaurar o valor anterior.
    # Por isso devolvemos a contagem, para a tela poder avisar.
    # """
    # sb = ConectionSupaBase.conexao()
    # afetadas = sb.table(TABELA_DADOS).update({"excluido": True}).eq("lote_id", lote_id).execute()
    # sb.table(TABELA_LOTES).update({
        # "status": "estornado",
        # "estornado_por": user_email,
        # "estornado_em": datetime.now().isoformat(),
    # }).eq("id", lote_id).execute()
    # return len(afetadas.data or [])


# O PostgREST (que é o que o Supabase expõe) devolve NO MÁXIMO 1.000 linhas por
# request e não avisa: um `.limit(20000)` volta com 1.000 e pronto. Toda leitura
# que pode passar disso precisa paginar com `.range()`.
PAGINA_SUPABASE = 1000


def descrever_erro_supabase(erro):
    """
    Texto legível do que o banco respondeu.

    O Streamlit Cloud troca a mensagem original de qualquer exceção que chegue
    à tela por "redacted to prevent data leaks", e o usuário fica com um
    traceback sem causa. Por isso capturamos o erro e escrevemos nós mesmos o
    código/mensagem que vieram do PostgREST.
    """
    rotulos = (("code", "código"), ("message", "mensagem"),
               ("details", "detalhes"), ("hint", "dica"))
    linhas = [f"- **{rotulo}**: {getattr(erro, campo)}"
              for campo, rotulo in rotulos if getattr(erro, campo, None)]
    return "\n".join(linhas) or f"`{type(erro).__name__}: {erro}`"


def _fim_da_paginacao(erro):
    """
    O PostgREST responde **416 / PGRST103** ("Requested range not satisfiable")
    quando o começo do intervalo passa do total de linhas — e isso inclui o
    caso da tabela VAZIA, em que até o `range(0, 999)` é recusado.

    Quem está paginando não deve tratar isso como falha: é só o fim dos dados.
    Foi o que derrubou o envio em produção — a validação pedia as categorias
    cadastradas, a tabela estava vazia, e o 416 subia como APIError até a tela.

    Vale também para a tabela cujo total é múltiplo exato de 1.000: a página
    seguinte, que existiria em teoria, devolve 416 em vez de uma lista vazia.
    """
    partes = [str(getattr(erro, campo, "") or "")
              for campo in ("code", "message", "details", "hint")]
    texto = " ".join(partes + [str(erro)]).lower()
    return "pgrst103" in texto or "not satisfiable" in texto


def buscar_paginado(montar_consulta, tamanho=PAGINA_SUPABASE, teto=200000):
    """
    Lê TODAS as linhas de uma consulta, de 1.000 em 1.000.

    `montar_consulta` é uma função que devolve uma consulta NOVA a cada chamada
    — o construtor do supabase-py guarda estado, então não dá para reaproveitar
    o mesmo objeto entre as páginas.

    Foi a falta disto que fez o de-para carregar só os 1.000 primeiros clientes
    em produção: os itens de todos os outros apareciam como "sem de-para".
    """
    linhas, inicio = [], 0
    while inicio < teto:
        try:
            pagina = (montar_consulta()
                      .range(inicio, inicio + tamanho - 1)
                      .execute().data) or []
        except Exception as erro:
            # Fim dos dados — não é falha. Veja _fim_da_paginacao().
            if _fim_da_paginacao(erro):
                break
            raise
        linhas.extend(pagina)
        if len(pagina) < tamanho:
            break
        inicio += tamanho
    return linhas


@st.cache_data(ttl=60)
def carregar_lotes():
    sb = ConectionSupaBase.conexao()
    res = (sb.table(TABELA_LOTES).select("*")
           .order("criado_em", desc=True).limit(500).execute())
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_consolidado(limite=200000):
    def consulta():
        sb = ConectionSupaBase.conexao()
        return (sb.table(TABELA_DADOS).select("*")
                .eq("excluido", False).order("criado_em", desc=True))
    dados = buscar_paginado(consulta, teto=limite)
    return pd.DataFrame(dados) if dados else pd.DataFrame()



# ================================================
# 8.b) DE-PARA BPS — leitura, gravação e log
# ================================================
def _texto_chave(valor):
    """Normaliza um pedaço da chave: None/NaN viram "" (nunca NULL no banco)."""
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(valor, (int, np.integer)) and not isinstance(valor, bool):
        return str(int(valor))
    if isinstance(valor, (float, np.floating)) and float(valor).is_integer():
        return str(int(valor))
    return str(valor).strip()


def _valor_chave_depara(coluna, valor):
    """Normaliza um campo da chave do de-para para GRAVAÇÃO."""
    if coluna == "id_fiscal_1":
        return canonizar_documento(valor)
    return _texto_chave(valor)


def chave_depara(registro):
    """Trinca normalizada — mesma concatenação que a coluna ID da planilha."""
    return "-".join(_valor_chave_depara(c, registro.get(c)) for c in CHAVE_DEPARA)


@st.cache_data(ttl=60)
def carregar_depara(incluir_excluidos=False):
    def consulta():
        sb = ConectionSupaBase.conexao()
        q = sb.table(TABELA_DEPARA).select("*")
        if not incluir_excluidos:
            q = q.eq("excluido", False)
        return q.order("nome_cliente")
    dados = buscar_paginado(consulta)
    df = pd.DataFrame(dados) if dados else pd.DataFrame()
    if not df.empty:
        df["ID"] = df.apply(chave_depara, axis=1)
    return df


@st.cache_data(ttl=60)
def carregar_log(entidades=None, limite=2000):
    def consulta():
        sb = ConectionSupaBase.conexao()
        q = sb.table(TABELA_DEPARA_LOG).select("*")
        if entidades:
            q = q.in_("entidade", list(entidades))
        return q.order("em", desc=True)
    dados = buscar_paginado(consulta, teto=limite)
    return pd.DataFrame(dados) if dados else pd.DataFrame()


def registrar_log(entidade, registro_id, acao, chave, antes=None, depois=None):
    """
    Grava uma linha no histórico. Nunca derruba a operação principal.

    A MESMA tabela serve ao de-para, às categorias e aos status — `entidade`
    diz de qual cadastro veio o evento.
    """
    try:
        ConectionSupaBase.conexao().table(TABELA_DEPARA_LOG).insert({
            "entidade": entidade,
            "registro_id": registro_id,
            "acao": acao,
            "chave": chave,
            "antes": antes,
            "depois": depois,
            "por_email": user_email,
            "por_nome": st.session_state.get("user_real_name", user_name),
            "em": datetime.now().isoformat(),
        }).execute()
    except Exception as e:
        st.warning(f"A operação foi feita, mas o histórico não registrou: {e}")


def buscar_depara_por_chave(dados, incluir_excluidos=True):
    """Procura um registro pela trinca. Retorna o dict ou None."""
    sb = ConectionSupaBase.conexao()
    consulta = sb.table(TABELA_DEPARA).select("*")
    for col in CHAVE_DEPARA:
        consulta = consulta.eq(col, _valor_chave_depara(col, dados.get(col)))
    res = consulta.execute()
    for registro in (res.data or []):
        if incluir_excluidos or not registro.get("excluido"):
            return registro
    return None


def inserir_depara(dados):
    """
    Cria um registro no de-para.
    Retorna (ok, mensagem). Se a trinca já existir:
      - ativa  -> recusa (é duplicata)
      - excluída -> reativa o registro antigo, preservando o histórico dele
    """
    sb = ConectionSupaBase.conexao()
    limpo = {c: _valor_chave_depara(c, dados.get(c)) for c in CHAVE_DEPARA}
    if not limpo["nome_cliente"]:
        return False, "O **Nome do cliente** é obrigatório."
    for campo in CAMPOS_DEPARA:
        limpo[campo["coluna"]] = (dados.get(campo["coluna"]) or "").strip() or None

    existente = buscar_depara_por_chave(limpo)
    if existente and not existente.get("excluido"):
        return False, (
            f"Já existe um de-para com essa trinca (`{chave_depara(limpo)}`). "
            "Use a aba **Editar** para alterá-lo."
        )

    agora = datetime.now().isoformat()
    autor = {
        "criado_por_email": user_email,
        "criado_por_nome": st.session_state.get("user_real_name", user_name),
        "criado_em": agora,
        "alterado_por_email": None,
        "alterado_por_nome": None,
        "alterado_em": None,
        "excluido": False,
    }

    if existente:   # estava excluído: reativa em vez de criar outro
        sb.table(TABELA_DEPARA).update({**limpo, **autor}).eq("id", existente["id"]).execute()
        registrar_log('depara', existente["id"], "restaurado", chave_depara(limpo),
                             antes=existente, depois={**limpo, **autor})
        return True, "Registro que estava excluído foi **restaurado** com os novos dados."

    res = sb.table(TABELA_DEPARA).insert({**limpo, **autor}).execute()
    novo_id = (res.data or [{}])[0].get("id")
    registrar_log('depara', novo_id, "criado", chave_depara(limpo), depois={**limpo, **autor})
    return True, "De-para cadastrado."


def atualizar_depara(registro_id, dados, antes):
    """Altera um registro existente (a trinca também pode mudar)."""
    sb = ConectionSupaBase.conexao()
    limpo = {c: _valor_chave_depara(c, dados.get(c)) for c in CHAVE_DEPARA}
    if not limpo["nome_cliente"]:
        return False, "O **Nome do cliente** é obrigatório."
    for campo in CAMPOS_DEPARA:
        limpo[campo["coluna"]] = (dados.get(campo["coluna"]) or "").strip() or None

    # Mudou a trinca? não pode colidir com outro registro
    if any(limpo[c] != _valor_chave_depara(c, antes.get(c)) for c in CHAVE_DEPARA):
        conflito = buscar_depara_por_chave(limpo, incluir_excluidos=False)
        if conflito and conflito["id"] != registro_id:
            return False, (
                f"Outro registro já usa a trinca `{chave_depara(limpo)}`. "
                "Ajuste os campos-chave ou edite aquele registro."
            )

    limpo["alterado_por_email"] = user_email
    limpo["alterado_por_nome"] = st.session_state.get("user_real_name", user_name)
    limpo["alterado_em"] = datetime.now().isoformat()

    mudou = {c: (antes.get(c), v) for c, v in limpo.items()
             if c not in ("alterado_por_email", "alterado_por_nome", "alterado_em")
             and (antes.get(c) or None) != (v or None)}
    if not mudou:
        return False, "Nada foi alterado."

    sb.table(TABELA_DEPARA).update(limpo).eq("id", registro_id).execute()
    registrar_log('depara', registro_id, "editado", chave_depara(limpo),
                         antes={c: antes.get(c) for c in mudou},
                         depois={c: limpo[c] for c in mudou})
    return True, f"{len(mudou)} campo(s) alterado(s)."


def excluir_depara(registro_id, antes):
    """Exclusão lógica: marca excluido=True. O histórico guarda como estava."""
    sb = ConectionSupaBase.conexao()
    sb.table(TABELA_DEPARA).update({
        "excluido": True,
        "alterado_por_email": user_email,
        "alterado_por_nome": st.session_state.get("user_real_name", user_name),
        "alterado_em": datetime.now().isoformat(),
    }).eq("id", registro_id).execute()
    registrar_log('depara', registro_id, "excluido", chave_depara(antes), antes=antes)
    return True, "Registro excluído."


def ler_planilha_depara(conteudo_bytes):
    """
    Lê a BASE_BPS.xlsx. O arquivo real tem uma linha em branco antes do
    cabeçalho e colunas separadoras chamadas "#", então procuramos a linha que
    contém "Nome do cliente" em vez de assumir uma posição fixa.
    Retorna (df, erro).
    """
    try:
        bruto = pd.read_excel(io.BytesIO(conteudo_bytes), header=None, dtype=object)
    except Exception as e:
        return None, f"Não consegui ler a planilha: {e}"

    alvo = normalizar_texto("Nome do cliente")
    linha_cab = None
    for i in range(min(10, len(bruto))):
        if any(normalizar_texto(v) == alvo for v in bruto.iloc[i].tolist()):
            linha_cab = i
            break
    if linha_cab is None:
        return None, "Não achei a linha de cabeçalho (nenhuma com 'Nome do cliente')."

    df = pd.read_excel(io.BytesIO(conteudo_bytes), header=linha_cab, dtype=object)

    # ATENÇÃO: a planilha tem DUAS colunas que só diferem pela caixa —
    # "Cliente" (código SAP, parte da chave) e "CLIENTE" (agrupador do
    # de-para). Casar ignorando a caixa funde as duas, então o casamento é
    # feito primeiro pelo nome EXATO; só o que sobrar cai na comparação
    # tolerante a acento/caixa/espaço.
    exatos = {}
    for c in df.columns:
        exatos.setdefault(str(c).strip(), c)
    normalizados = {}
    for c in df.columns:
        normalizados.setdefault(normalizar_texto(c), []).append(c)

    renomear, faltando, usados = {}, [], set()
    for spec in CAMPOS_CHAVE_DEPARA + CAMPOS_DEPARA:
        origem = exatos.get(spec["titulo"])
        if origem is None or origem in usados:
            sobrando = [c for c in normalizados.get(normalizar_texto(spec["titulo"]), [])
                        if c not in usados]
            origem = sobrando[0] if len(sobrando) == 1 else None
        if origem is None:
            faltando.append(spec["titulo"])
        else:
            usados.add(origem)
            renomear[origem] = spec["coluna"]
    if faltando:
        return None, "Colunas ausentes na planilha: " + ", ".join(faltando)

    df = df.rename(columns=renomear)[list(renomear.values())].copy()
    df = df.dropna(how="all").reset_index(drop=True)
    for col in CHAVE_DEPARA:
        df[col] = df[col].map(lambda v, c=col: _valor_chave_depara(c, v))
    for campo in CAMPOS_DEPARA:
        df[campo["coluna"]] = df[campo["coluna"]].map(
            lambda v: None if _texto_chave(v) == "" else _texto_chave(v))
    df = df[df["nome_cliente"] != ""].reset_index(drop=True)
    return df, None


def importar_depara(df):
    """
    Carga da planilha inteira, com upsert pela trinca: quem já existe é
    atualizado, quem não existe é criado. Registra UMA linha no histórico
    (a carga toda), não uma por registro — senão o log vira lixo com 4 mil linhas.
    Retorna (gravados, descartados_duplicados).
    """
    sb = ConectionSupaBase.conexao()
    antes_dedup = len(df)
    df = df.drop_duplicates(subset=CHAVE_DEPARA, keep="last").reset_index(drop=True)
    descartados = antes_dedup - len(df)

    agora = datetime.now().isoformat()
    registros = []
    for linha in df.to_dict(orient="records"):
        linha = {k: (None if (isinstance(v, float) and pd.isna(v)) else v)
                 for k, v in linha.items()}
        linha.update({
            "criado_por_email": user_email,
            "criado_por_nome": st.session_state.get("user_real_name", user_name),
            "criado_em": agora,
            "excluido": False,
        })
        registros.append(linha)

    barra = st.progress(0.0, text="Gravando o de-para...")
    total = len(registros)
    for inicio in range(0, total, TAMANHO_LOTE):
        pedaco = registros[inicio:inicio + TAMANHO_LOTE]
        sb.table(TABELA_DEPARA).upsert(
            pedaco, on_conflict=",".join(CHAVE_DEPARA)).execute()
        barra.progress(min(1.0, (inicio + len(pedaco)) / total),
                       text=f"Gravando... {inicio + len(pedaco)}/{total}")
    barra.empty()

    registrar_log('depara', 
        None, "importado", f"{total} registro(s)",
        depois={"registros": total, "duplicados_descartados": descartados},
    )
    return total, descartados


def valores_sugeridos(df, coluna):
    """Valores já usados numa coluna, para a lista de sugestão do formulário."""
    if df.empty or coluna not in df.columns:
        return []
    return sorted(v for v in df[coluna].dropna().unique() if str(v).strip())

def juntar_com_depara(df_itens):
    """
    Traz os campos do de-para para cada item, casando pela trinca
    (cliente, id_fiscal_1, nome_cliente).

    O cruzamento é feito na LEITURA, não na gravação: corrigir um contrato no
    de-para passa a valer para todos os itens daquele cliente, inclusive os já
    enviados. Se os campos fossem copiados para a linha do item no upload,
    ficariam congelados no valor da época.

    Retorna (df, quantos_sem_depara).
    """
    colunas_dp = [c["coluna"] for c in CAMPOS_DEPARA]
    if df_itens.empty:
        return df_itens, 0

    df = df_itens.copy()
    df_dp = carregar_depara()
    if df_dp.empty:
        for col in colunas_dp:
            df[col] = None
        return df, len(df)

    # A chave de comparação é canônica dos DOIS lados, porque as bases chegam
    # com formatos diferentes para o mesmo dado:
    #   - CNPJ: o de-para tem 14 dígitos com zero à esquerda; o SAP vem sem os
    #     zeros quando o Excel guarda o campo como número;
    #   - nome: "LTDA" x "LTDA.", "S.A" x "S/A", vírgulas a mais.
    # Canonizar aqui também conserta o que já foi gravado antes desta correção,
    # sem precisar mexer no banco.
    def chave_normalizada(tabela, coluna):
        if coluna not in tabela.columns:
            return ""
        if coluna == "id_fiscal_1":
            return tabela[coluna].map(canonizar_documento)
        if coluna == "nome_cliente":
            return tabela[coluna].map(normalizar_nome)
        return tabela[coluna].map(lambda v: _texto_chave(v).lstrip("0"))

    chaves_tmp = [f"_k_{c}" for c in CHAVE_DEPARA]
    for col, tmp in zip(CHAVE_DEPARA, chaves_tmp):
        df[tmp] = chave_normalizada(df, col)

    direita = df_dp[CHAVE_DEPARA + colunas_dp].copy()
    for col, tmp in zip(CHAVE_DEPARA, chaves_tmp):
        direita[tmp] = chave_normalizada(direita, col)
    # Depois de normalizar o nome, trincas que só diferiam por pontuação viram
    # a mesma chave — mantemos uma para o merge não multiplicar linhas.
    direita = direita.drop(columns=CHAVE_DEPARA).drop_duplicates(subset=chaves_tmp)

    df = df.merge(direita, on=chaves_tmp, how="left", indicator=True)
    sem_depara = int((df["_merge"] == "left_only").sum())
    df["_tem_depara"] = df["_merge"] == "both"
    df = df.drop(columns=chaves_tmp + ["_merge"])
    return df, sem_depara



# ================================================
# 8.c) CATEGORIAS E STATUS — cadastro, log e validação
# ================================================
@st.cache_data(ttl=60)
def carregar_dominios(tipo=None, incluir_excluidos=False):
    def consulta():
        sb = ConectionSupaBase.conexao()
        q = sb.table(TABELA_DOMINIOS).select("*")
        if tipo:
            q = q.eq("tipo", tipo)
        if not incluir_excluidos:
            q = q.eq("excluido", False)
        return q.order("nome")
    dados = buscar_paginado(consulta)
    return pd.DataFrame(dados) if dados else pd.DataFrame()


def mapa_dominio(tipo):
    """
    {escrita normalizada -> escrita OFICIAL} do cadastro.

    É o que permite o arquivo chegar com "enviar documentacao" e ser gravado
    como "Enviar documentação": a comparação ignora acento, caixa e espaços,
    mas o que vai para o banco é sempre o texto oficial do cadastro.
    """
    df = carregar_dominios(tipo)
    if df.empty:
        return {}
    return {normalizar_texto(n): n for n in df["nome"].dropna()}


def inserir_dominio(tipo, nome, definicao):
    """Cadastra uma categoria ou um status. Retorna (ok, mensagem)."""
    nome = (nome or "").strip()
    if not nome:
        return False, "Informe o nome."

    sb = ConectionSupaBase.conexao()
    # A comparação é normalizada: não adianta cadastrar "Registrado" se já
    # existe "registrado" — seriam o mesmo valor na hora de validar o arquivo.
    existentes = carregar_dominios(tipo, incluir_excluidos=True)
    if not existentes.empty:
        igual = existentes[existentes["nome"].map(normalizar_texto)
                           == normalizar_texto(nome)]
        if not igual.empty:
            registro = igual.iloc[0].to_dict()
            if not registro.get("excluido"):
                return False, f"**{registro['nome']}** já está cadastrado."
            sb.table(TABELA_DOMINIOS).update({
                "nome": nome, "definicao": (definicao or "").strip() or None,
                "excluido": False,
                "alterado_por_email": user_email,
                "alterado_por_nome": st.session_state.get("user_real_name", user_name),
                "alterado_em": datetime.now().isoformat(),
            }).eq("id", registro["id"]).execute()
            registrar_log(TIPOS_DOMINIO[tipo]["titulo"].lower(), registro["id"],
                          "restaurado", nome, antes=registro)
            return True, f"**{nome}** estava excluído e foi restaurado."

    dados = {
        "tipo": tipo,
        "nome": nome,
        "definicao": (definicao or "").strip() or None,
        "criado_por_email": user_email,
        "criado_por_nome": st.session_state.get("user_real_name", user_name),
        "criado_em": datetime.now().isoformat(),
        "excluido": False,
    }
    res = sb.table(TABELA_DOMINIOS).insert(dados).execute()
    novo_id = (res.data or [{}])[0].get("id")
    registrar_log(tipo, novo_id, "criado", nome, depois=dados)
    return True, f"**{nome}** cadastrado."


def atualizar_dominio(registro_id, tipo, definicao, antes):
    """
    Altera só a DEFINIÇÃO. O nome é imutável depois de cadastrado.

    Motivo: o nome é o valor que fica gravado em cada item e entra na chave.
    Se ele pudesse ser reescrito, os itens antigos ficariam apontando para uma
    palavra que não existe mais no cadastro — órfãos silenciosos. Sendo fixo,
    o próprio nome funciona como identificador estável.

    Para corrigir um nome errado: exclua e cadastre de novo. A tela mostra
    quantos itens usam o valor antes de deixar excluir.
    """
    nova = (definicao or "").strip() or None
    if (antes.get("definicao") or None) == nova:
        return False, "Nada foi alterado."

    ConectionSupaBase.conexao().table(TABELA_DOMINIOS).update({
        "definicao": nova,
        "alterado_por_email": user_email,
        "alterado_por_nome": st.session_state.get("user_real_name", user_name),
        "alterado_em": datetime.now().isoformat(),
    }).eq("id", registro_id).execute()
    registrar_log(tipo, registro_id, "editado", antes.get("nome"),
                  antes={"definicao": antes.get("definicao")},
                  depois={"definicao": nova})
    return True, "Definição atualizada."


def excluir_dominio(registro_id, tipo, antes, em_uso):
    """
    Exclusão lógica. `em_uso` é quantos itens já gravados usam esse valor —
    excluir não apaga nada do histórico, mas um novo envio com essa palavra
    passa a ser recusado, então a tela avisa antes.
    """
    ConectionSupaBase.conexao().table(TABELA_DOMINIOS).update({
        "excluido": True,
        "alterado_por_email": user_email,
        "alterado_por_nome": st.session_state.get("user_real_name", user_name),
        "alterado_em": datetime.now().isoformat(),
    }).eq("id", registro_id).execute()
    registrar_log(tipo, registro_id, "excluido", antes.get("nome"), antes=antes)
    return True, (f"**{antes.get('nome')}** excluído."
                  + (f" {em_uso} item(ns) já gravados continuam com esse valor."
                     if em_uso else ""))



# ================================================
# 8.d) VALOR CORRETO DO CTE — leitura, comparação e gravação
# ================================================
@st.cache_data(ttl=60)
def carregar_valores_cte():
    def consulta():
        sb = ConectionSupaBase.conexao()
        return (sb.table(TABELA_VALORES_CTE).select("*")
                .eq("excluido", False).order("id_cte"))
    dados = buscar_paginado(consulta)
    return pd.DataFrame(dados) if dados else pd.DataFrame()


def ler_planilha_valores_cte(conteudo_bytes):
    """
    Lê a planilha de valores corretos.

    O arquivo real tem uma linha em branco antes do cabeçalho, colunas
    separadoras e DUAS colunas chamadas "ID CTE" (a de apoio é a segunda).
    Por isso procuramos a linha de cabeçalho e casamos pelo nome EXATO —
    o pandas renomeia a segunda para "ID CTE.1", então a primeira é a certa.

    Retorna (df_pronto, df_retidas, avisos, erro, textos_desconhecidos).
    """
    try:
        bruto = pd.read_excel(io.BytesIO(conteudo_bytes), header=None, dtype=object)
    except Exception as e:
        return None, None, [], f"Não consegui ler a planilha: {e}", {}

    alvo = normalizar_texto("ID CTE")
    linha_cab = None
    for i in range(min(10, len(bruto))):
        if any(normalizar_texto(v) == alvo for v in bruto.iloc[i].tolist()):
            linha_cab = i
            break
    if linha_cab is None:
        return None, None, [], "Não achei a linha de cabeçalho (nenhuma com 'ID CTE').", {}

    df = pd.read_excel(io.BytesIO(conteudo_bytes), header=linha_cab, dtype=object)

    exatos = {}
    for c in df.columns:
        exatos.setdefault(str(c).strip(), c)
    renomear, faltando = {}, []
    for spec in COLUNAS_VALOR_CTE:
        origem = exatos.get(spec["titulo"])
        if origem is None:
            faltando.append(spec["titulo"])
        else:
            renomear[origem] = spec["coluna"]
    if faltando:
        return None, None, [], "Colunas ausentes na planilha: " + ", ".join(faltando), {}

    avisos = []
    ignoradas = [c for c in df.columns if c not in renomear]
    if ignoradas:
        avisos.append(f"{len(ignoradas)} coluna(s) de apoio ignoradas — só "
                      f"{', '.join(s['titulo'] for s in COLUNAS_VALOR_CTE)} são gravadas.")

    df = df.rename(columns=renomear)[list(renomear.values())].copy()
    antes = len(df)
    df = df.dropna(how="all").reset_index(drop=True)
    if antes != len(df):
        avisos.append(f"{antes - len(df)} linha(s) totalmente vazia(s) descartada(s).")

    linhas_excel = [i + linha_cab + 2 for i in range(len(df))]
    erros, retidos = [], []
    convertido = {c["coluna"]: [] for c in COLUNAS_VALOR_CTE}
    convertido["situacao"] = []
    # {escrita normalizada -> texto oficial} dos textos aceitos
    aceitos = {normalizar_texto(t): t for t in VALORES_CTE_TEXTO_ACEITO}
    textos_desconhecidos = {}   # {texto escrito: quantas linhas}

    for pos in range(len(df)):
        linha = df.iloc[pos]
        problema = None
        situacao = SITUACAO_CTE_CONFIRMADO
        valores = {}
        for spec in COLUNAS_VALOR_CTE:
            col, bruto_valor = spec["coluna"], linha[spec["coluna"]]
            novo, erro = _converter_valor(bruto_valor, spec["tipo"])

            if col == "valor_correto" and erro:
                # Não é número: só pode ser um dos textos aceitos. Se for, a
                # linha SOBE com valor vazio e a situação registrada. Se não
                # for, é escrita errada: aí a linha fica retida e a tela pede
                # correção, em vez de barrar o arquivo inteiro por uma palavra.
                escrito = str(bruto_valor).strip()
                oficial = aceitos.get(normalizar_texto(escrito))
                if oficial:
                    situacao = oficial
                else:
                    problema = problema or f"{spec['titulo']}: texto não reconhecido"
                    textos_desconhecidos[escrito] = textos_desconhecidos.get(escrito, 0) + 1
                valores[col] = None
                continue

            if erro:
                erros.append({"Linha": linhas_excel[pos], "Coluna": spec["titulo"],
                              "Valor": bruto_valor, "Problema": erro})
                novo = None
            elif novo is None and spec.get("obrigatorio"):
                # Célula vazia retém a linha. Não assumimos "EM ANALISE" por
                # ela: "em análise" é uma afirmação do validador, e uma célula
                # em branco não afirma nada.
                problema = problema or f"{spec['titulo']} em branco"
            valores[col] = novo
        valores["situacao"] = situacao
        for col, v in valores.items():
            convertido[col].append(v)
        if problema and not valores.get("id_cte"):
            problema = "ID CTE em branco"
        if problema:
            retidos.append({"Linha": linhas_excel[pos],
                            "ID CTE": valores.get("id_cte"),
                            "Montante (ME)": valores.get("montante_original"),
                            "Problema": problema})

    if erros:
        return None, pd.DataFrame(erros), avisos, None, textos_desconhecidos

    for col, vals in convertido.items():
        df[col] = vals

    retidas_pos = {r["Linha"] for r in retidos}
    df_retidas = pd.DataFrame(retidos)
    df = df[[l not in retidas_pos for l in linhas_excel]].reset_index(drop=True)

    repetidos = int(df.duplicated(subset=["id_cte"]).sum())
    if repetidos:
        avisos.append(f"{repetidos} ID CTE repetido(s) no arquivo — vale a última ocorrência.")
        df = df.drop_duplicates(subset=["id_cte"], keep="last").reset_index(drop=True)

    return df, df_retidas, avisos, None, textos_desconhecidos


def comparar_valores_cte(df_novo):
    """
    Confronta a planilha com o que já está gravado.

    Retorna (df_alterados, novos), onde df_alterados lista os CT-e cujo valor
    OU situação muda — é esse o aviso que o usuário vê antes de gravar. Sair de
    "EM ANALISE" para um valor confirmado também é uma mudança, e das mais
    importantes. Reenviar o mesmo arquivo sem mudança devolve a lista vazia.
    """
    if df_novo is None or df_novo.empty:
        return pd.DataFrame(), 0

    sb = ConectionSupaBase.conexao()
    ids = sorted({str(v) for v in df_novo["id_cte"].dropna()})
    atuais = {}
    BLOCO = 200
    try:
        for i in range(0, len(ids), BLOCO):
            fatia = ids[i:i + BLOCO]
            for r in buscar_paginado(lambda f=fatia: (
                    sb.table(TABELA_VALORES_CTE)
                    .select("id_cte,valor_correto,situacao")
                    .in_("id_cte", f).eq("excluido", False))):
                atuais[str(r["id_cte"])] = (r.get("valor_correto"), r.get("situacao"))
    except Exception as e:
        st.info(f"Não foi possível conferir os valores já gravados ({e}).")
        return pd.DataFrame(), len(df_novo)

    mudancas, novos = [], 0
    for _, linha in df_novo.iterrows():
        chave = str(linha["id_cte"])
        if chave not in atuais:
            novos += 1
            continue
        # Ao virar coluna de DataFrame, os None dos pendentes viram NaN — e
        # `NaN is None` é falso. Sem normalizar, TODO pendente apareceria como
        # "valor alterado" a cada reenvio, sem ter mudado nada.
        def _num(v):
            if v is None:
                return None
            try:
                return None if pd.isna(v) else round(float(v), 2)
            except (TypeError, ValueError):
                return None

        valor_antes = _num(atuais[chave][0])
        sit_antes = atuais[chave][1]
        valor_depois = _num(linha["valor_correto"])
        sit_depois = linha["situacao"]

        mesmo_valor = valor_antes == valor_depois
        if mesmo_valor and (sit_antes or "") == (sit_depois or ""):
            continue

        diferenca = None
        if valor_antes is not None and valor_depois is not None:
            diferenca = round(valor_depois - valor_antes, 2)
        mudancas.append({
            "ID CTE": chave,
            "Situação antes": sit_antes,
            "Valor gravado": valor_antes,
            "Situação nova": sit_depois,
            "Valor novo": valor_depois,
            "Diferença": diferenca,
        })
    return pd.DataFrame(mudancas), novos


def gravar_valores_cte(df_pronto, df_alterados, nome_arquivo):
    """
    Grava por upsert no ID CTE e registra UMA linha de histórico por valor
    que mudou (não por linha do arquivo) — mais um evento de resumo da carga.
    Assim o log responde "quem mudou o valor de qual CT-e, de quanto para
    quanto" sem virar ruído com milhares de linhas inalteradas.
    """
    sb = ConectionSupaBase.conexao()
    agora = datetime.now().isoformat()
    registros = []
    for linha in df_pronto.to_dict(orient="records"):
        limpo = {k: (None if (isinstance(v, float) and pd.isna(v)) else v)
                 for k, v in linha.items()}
        limpo.update({
            "criado_por_email": user_email,
            "criado_por_nome": st.session_state.get("user_real_name", user_name),
            "criado_em": agora,
            "excluido": False,
        })
        registros.append(limpo)

    total = len(registros)
    barra = st.progress(0.0, text="Gravando os valores...")
    for inicio in range(0, total, TAMANHO_LOTE):
        pedaco = registros[inicio:inicio + TAMANHO_LOTE]
        sb.table(TABELA_VALORES_CTE).upsert(pedaco, on_conflict="id_cte").execute()
        barra.progress(min(1.0, (inicio + len(pedaco)) / total),
                       text=f"Gravando... {inicio + len(pedaco)}/{total}")
    barra.empty()

    for _, m in df_alterados.iterrows():
        registrar_log("valor_cte", None, "valor alterado", m["ID CTE"],
                      antes={"valor_correto": m["Valor gravado"],
                             "situacao": m["Situação antes"]},
                      depois={"valor_correto": m["Valor novo"],
                              "situacao": m["Situação nova"]})
    registrar_log("valor_cte", None, "importado", nome_arquivo,
                  depois={"linhas": total, "valores_alterados": len(df_alterados)})
    return total


def atualizar_valor_cte(id_cte, valor_novo, antes):
    """Ajuste pontual de um CT-e, sem precisar montar planilha."""
    if valor_novo is None:
        return False, "Informe o valor."
    atual = antes.get("valor_correto")
    if atual is not None and round(float(atual), 2) == round(float(valor_novo), 2):
        return False, "O valor é o mesmo que já está gravado."

    ConectionSupaBase.conexao().table(TABELA_VALORES_CTE).update({
        "valor_correto": float(valor_novo),
        "situacao": SITUACAO_CTE_CONFIRMADO,
        "alterado_por_email": user_email,
        "alterado_por_nome": st.session_state.get("user_real_name", user_name),
        "alterado_em": datetime.now().isoformat(),
    }).eq("id_cte", id_cte).execute()
    registrar_log("valor_cte", None, "valor alterado", id_cte,
                  antes={"valor_correto": atual, "situacao": antes.get("situacao")},
                  depois={"valor_correto": float(valor_novo),
                          "situacao": SITUACAO_CTE_CONFIRMADO})
    return True, (f"Valor do CT-e **{id_cte}** atualizado de "
                  f"{'(vazio)' if atual is None else f'R$ {float(atual):,.2f}'} para "
                  f"R$ {float(valor_novo):,.2f}.")


def limpar_caches():
    carregar_lotes.clear()
    carregar_consolidado.clear()
    carregar_depara.clear()
    carregar_dominios.clear()
    carregar_valores_cte.clear()
    carregar_log.clear()


# ================================================
# 9) MENU
# ================================================
st.sidebar.title("📂 Menu")
st.sidebar.markdown(
    f"**{user_name}**  \n`{user_email}`"
)
st.sidebar.divider()


# ================================================
# 8.e) INDICADOR — leitura do cubo pré-calculado
# ================================================
# O cubo é gerado fora daqui, pelo montar_base_indicador.py (cron no servidor).
# Ele traz as contagens já feitas por combinação de filtro: ~37 mil linhas,
# 0,4 MB. Cruzar as quatro bases ao vivo exigiria carregar 1,6 milhão de linhas
# da ARITMCLI e 6,7 milhões da ponte — não cabe na memória do Streamlit Cloud,
# e pesaria no servidor a cada acesso.
OBJETO_CUBO = "dados_tratados/indicador_cubo.parquet"
BUCKET_CUBO = "calculation-view"


OBJETO_DETALHE = "dados_tratados/indicador_detalhe.parquet"

# Colunas do detalhe que vão para a exportação. A ordem é a que o usuário lê.
COLUNAS_DETALHE = [
    "documento", "data_documento", "tipo_documento", "cliente_codigo",
    "cliente_nome", "cliente_cnpj", "grupo_economico", "valor",
    "data_vencimento", "em_aberto", "bloqueio_pagamento",
    "id_cte", "serie", "status_ligacao", "cte_cancelado",
    "categoria", "status", "data_status", "enviado", "justificado",
    "situacao_valor", "valor_correto", "montante_original",
]

TITULOS_DETALHE = {
    "documento": "Lançamento contábil", "data_documento": "Data do documento",
    "tipo_documento": "Tipo", "cliente_codigo": "Cliente",
    "cliente_nome": "Nome do cliente", "cliente_cnpj": "CNPJ",
    "grupo_economico": "Grupo econômico", "valor": "Valor (R$)",
    "data_vencimento": "Vencimento", "em_aberto": "Em aberto",
    "bloqueio_pagamento": "Bloqueio de pagamento", "id_cte": "ID CT-e",
    "serie": "Série", "status_ligacao": "Ligação com o CT-e",
    "cte_cancelado": "CT-e cancelado", "categoria": "Justificativa",
    "status": "Status", "data_status": "Data do status",
    "enviado": "Enviado ao formulário", "justificado": "Justificado",
    "situacao_valor": "Situação do valor", "valor_correto": "Valor correto",
    "montante_original": "Montante original",
}

# Acima disto a exportação sai em CSV: o Excel trava para abrir, e gerar o
# xlsx de centenas de milhares de linhas leva minutos (medido: gravar xlsx é
# ~60x mais lento que CSV no mesmo volume).
TETO_XLSX = 100_000

# Teto DURO de exportação. Medido: 1,51 milhão de documentos custa 167s e
# pico de 1,19 GB — o Streamlit Cloud tem ~1 GB e morreria. O gasto está em
# materializar o CSV inteiro em memória, que é o que o botão de download
# exige. 200 mil linhas ficam em ~160 MB, que cabe com folga.
#
# Não é só limitação técnica: ninguém audita 1,5 milhão de linhas no Excel.
# Conferir um número grande se faz por recorte — um cliente, um mês — e o
# total agregado continua disponível no resumo.
TETO_DOCUMENTOS = 200_000


@st.cache_resource(ttl=1800)
def arquivo_detalhe():
    """
    Baixa o detalhe UMA vez e devolve o caminho em disco.

    Guardamos o caminho, não o DataFrame: é isso que permite ler depois só a
    fatia filtrada. O pyarrow usa as estatísticas de cada bloco para pular o
    que não interessa — filtrar por um cliente lê 9.911 linhas de 1,6 milhão,
    com 19 MB de pico em vez de 173 MB.
    """
    if MODO_LOCAL:
        caminho = Path(__file__).parent / "indicador_justificativas.parquet"
        return str(caminho) if caminho.exists() else None

    import Modulos.Minio.examples.MinIO as meu_minio
    destino = Path(tempfile.gettempdir()) / "indicador_detalhe.parquet"
    if not destino.exists():
        meu_minio.download(object_name=OBJETO_DETALHE, bucket_name=BUCKET_CUBO,
                           download_path=str(destino))
    return str(destino)


def documentos(filtros):
    """Lê do detalhe só as linhas que casam com `filtros` (pushdown)."""
    caminho = arquivo_detalhe()
    if not caminho:
        return pd.DataFrame()
    df = pd.read_parquet(caminho, columns=COLUNAS_DETALHE,
                         filters=filtros or None)
    return df


# ---------------------------------------------------------------
# Cores dos gráficos do indicador
# ---------------------------------------------------------------
# Os três estados são ETAPAS ORDENADAS de um processo, não categorias
# independentes — então a escala é ordinal: uma cor só, do escuro ao claro.
#
# A primeira tentativa usou a paleta de status (verde/amarelo/laranja) e o
# validador reprovou: amarelo e laranja ficam a ΔE 13,6 em visão NORMAL, abaixo
# do piso de 15. Lado a lado na mesma barra, ninguém distinguiria.
#
# Esta rampa passa em tudo contra o fundo real do app (#0E1117): tons em ordem
# de luminosidade, degraus visíveis e a ponta clara com contraste suficiente.
# O escuro é o "pronto": uma barra quase toda clara lê-se como "quase nada feito".
# Paleta da casa, a mesma do painel de Segurança do Trabalho
# (pagina_indicadores.py): laranja Della Volpe para o que já foi feito, tons
# claros para o que falta. Validada como rampa ORDINAL contra o fundo escuro
# do app (#0E1117): luminosidade monotônica, degraus visíveis, ponta com
# 5,41:1 de contraste. (Como paleta categórica ela reprovaria — o bege tem
# croma quase nulo —, mas aqui os três são etapas ordenadas, não categorias.)
ESTADOS_ORDEM = ["Justificado", "Enviado sem definição", "Nunca enviado"]
ESTADOS_COR = ["#E4610A", "#F7A46B", "#D9CBBF"]

SUPERFICIE = "#0E1117"
TINTA = "#e6e6e6"
TINTA_FRACA = "#9a9a9a"


def legenda_html(series, cores):
    """Legenda em texto, para ir no título da seção.

    A legenda nativa do Altair dentro do tema do Streamlit sobrepõe rótulos
    quando o gráfico é estreito — o painel de Segurança do Trabalho resolveu
    assim, e aqui vale o mesmo.
    """
    return " &nbsp; ".join(f'<span style="color:{c}">■</span> {s}'
                           for s, c in zip(series, cores))


def titulo_secao(titulo, subtitulo=""):
    st.markdown(f"**{titulo}**"
                + (f"<br><span style='font-size:0.85em;opacity:0.75'>{subtitulo}</span>"
                   if subtitulo else ""),
                unsafe_allow_html=True)


def seta(atual, antes, unidade, sobe_bom=True):
    """('▲ 12 documentos', cor) — a cor diz se a direção é boa ou ruim."""
    if atual == antes:
        return "= igual", "neutro"
    dif = atual - antes
    bom = (dif > 0) == sobe_bom
    return (f"{'▲' if dif > 0 else '▼'} {abs(dif):,}".replace(",", ".")
            + f" {unidade}", "verde" if bom else "vermelho")


def classificar_estado(df):
    """Etiqueta cada linha do cubo com a etapa em que ela está."""
    estado = pd.Series("Nunca enviado", index=df.index)
    estado[df["enviado"] & ~df["justificado"]] = "Enviado sem definição"
    estado[df["justificado"]] = "Justificado"
    return estado


def grafico_progresso(dados, dimensao, rotulo_dim, altura=260, horizontal=True):
    """
    Barra empilhada: o comprimento é o TOTAL, as fatias são o andamento.

    É a forma que responde "quanto falta" sem exigir conta: a barra inteira é
    o universo daquele corte, e a parte escura é o que já foi justificado.
    """
    import altair as alt

    if dados.empty:
        return None

    totais = dados.groupby(dimensao, as_index=False)["documentos"].sum()
    totais = totais.rename(columns={"documentos": "total"})
    base = dados.merge(totais, on=dimensao)

    eixo_dim = alt.X if not horizontal else alt.Y
    eixo_val = alt.Y if not horizontal else alt.X

    ordem = (alt.EncodingSortField(field="total", op="max", order="descending")
             if horizontal else None)

    barras = (
        alt.Chart(base)
        .mark_bar(
            # 2px da cor do fundo entre as fatias: separa sem desenhar borda
            stroke=SUPERFICIE, strokeWidth=2,
            cornerRadiusEnd=4,
        )
        .encode(
            eixo_dim(f"{dimensao}:{'T' if dimensao == 'mes' else 'N'}",
                     title=rotulo_dim, sort=ordem,
                     axis=alt.Axis(labelColor=TINTA, titleColor=TINTA_FRACA,
                                   domainColor=TINTA_FRACA, tickColor=TINTA_FRACA,
                                   labelFontSize=12)),
            eixo_val("sum(documentos):Q", title="Documentos",
                     axis=alt.Axis(labelColor=TINTA_FRACA, titleColor=TINTA_FRACA,
                                   gridColor="#2a2d35", domainColor=TINTA_FRACA,
                                   format="~s")),
            color=alt.Color(
                "estado:N", title=None,
                scale=alt.Scale(domain=ESTADOS_ORDEM, range=ESTADOS_COR),
                sort=ESTADOS_ORDEM,
                legend=None),   # vai no título da seção
            order=alt.Order("color_estado_sort_index:Q"),
            tooltip=[
                alt.Tooltip(f"{dimensao}:{'T' if dimensao == 'mes' else 'N'}",
                            title=rotulo_dim),
                alt.Tooltip("estado:N", title="Situação"),
                alt.Tooltip("sum(documentos):Q", title="Documentos", format=","),
                alt.Tooltip("max(total):Q", title="Total do grupo", format=","),
            ],
        )
    )

    # O total na ponta da barra é o que o usuário quer ver junto — mas com
    # muitas barras os rótulos se sobrepõem e viram uma mancha. Acima deste
    # limite o número fica só no tooltip, que é onde ele continua legível.
    if len(totais) > 15:
        return (barras
                .properties(height=altura, background="transparent")
                .configure_view(stroke=None)
                .configure_legend(titleColor=TINTA_FRACA))

    texto = (
        alt.Chart(totais)
        .mark_text(align="left" if horizontal else "center",
                   dx=4 if horizontal else 0, dy=0 if horizontal else -6,
                   color=TINTA_FRACA, fontSize=11)
        .encode(
            eixo_dim(f"{dimensao}:{'T' if dimensao == 'mes' else 'N'}",
                     sort=ordem, title=rotulo_dim),
            eixo_val("total:Q"),
            text=alt.Text("total:Q", format=","),
        )
    )

    return ((barras + texto)
            .properties(height=altura, background="transparent")
            .configure_view(stroke=None)
            .configure_legend(titleColor=TINTA_FRACA))


def cubo_ainda_nao_existe(erro):
    """
    O arquivo não está no bucket — é diferente de o MinIO estar fora do ar.

    Confundir os dois esconderia uma falha de infraestrutura atrás de um
    "ainda não foi gerado", e ninguém iria procurar o problema certo.
    """
    texto = str(erro).lower()
    return ("nosuchkey" in texto or "not exist" in texto
            or "no such key" in texto or "nosuchbucket" in texto)


@st.cache_data(ttl=1800)
def carregar_cubo():
    """Lê o cubo do MinIO. Em modo local, lê o arquivo ao lado do script."""
    if MODO_LOCAL:
        caminho = Path(__file__).parent / "indicador_cubo.parquet"
        if not caminho.exists():
            return pd.DataFrame()
        return pd.read_parquet(caminho)
    import Modulos.Minio.examples.MinIO as meu_minio
    return meu_minio.read_file(OBJETO_CUBO, BUCKET_CUBO)


CORES_CARTAO = {"neutro": "#9A8E86", "laranja": "#E4610A",
                "vermelho": "#B3261E", "verde": "#2E7D46"}


def kpi_nota(rotulo, valor, nota="", cor="neutro"):
    """Cartão com valor e uma NOTA embaixo — o padrão do painel de Segurança.

    A nota é o que transforma um número solto em informação: "5,2%" não diz
    nada sozinho, "5,2% do total · 39.784 sem definição" diz.
    """
    st.markdown(
        f"""<div class="card-kpi" style="border-left:4px solid {CORES_CARTAO.get(cor, '#9A8E86')}">
            <div class="rotulo">{rotulo}</div>
            <div class="valor">{valor}</div>
            <div class="rotulo" style="opacity:.75">{nota}</div></div>""",
        unsafe_allow_html=True)


def kpi_pct(rotulo, quantidade, total, ajuda=None):
    """
    Card com a quantidade e, quando faz sentido, o percentual.

    `total=None` desliga o percentual — serve para o card de valor em reais,
    onde "0,0%" não significaria nada.
    """
    numero = f"{quantidade:,.0f}".replace(",", ".")
    linha_pct = ""
    if total:
        pct_txt = f"{100.0 * quantidade / total:.1f}".replace(".", ",")
        linha_pct = f'<div class="rotulo">{pct_txt}%</div>'
    st.markdown(
        f"""<div class="card-kpi"><div class="rotulo">{rotulo}</div>
            <div class="valor">{numero}</div>{linha_pct}</div>""",
        unsafe_allow_html=True)
    if ajuda:
        st.caption(ajuda)


opcoes_full = {
    "Enviar":      "📤 Enviar Itens",
    "Envios":      "🧾 Envios",
    "Consolidado": "🗂️ Dados Consolidados",
    "Depara":      "🔗 De-Para BPS",
    "Dominios":    "🏷️ Categorias e Status",
    "ValoresCTE":  "💲 Valor Correto do CT-e",
    "Indicador":   "📊 Indicador",
}

menu = st.sidebar.radio(
    "Selecione:", list(opcoes_full.values()), label_visibility="collapsed")
st.sidebar.divider()
if st.sidebar.button("🔄 Atualizar dados"):
    limpar_caches()
    st.rerun()

if MODO_LOCAL:
    st.sidebar.divider()
    st.sidebar.warning(
        "🧪 **MODO LOCAL**\n\n"
        "Sem Azure, sem Supabase, sem MinIO. Os dados ficam em `.local_data/`."
    )
    contagem = backend_local.resumo()
    if contagem:
        st.sidebar.caption(" · ".join(f"{t}: {n}" for t, n in contagem.items()))
    if st.sidebar.button("🧹 Zerar base local"):
        backend_local.resetar()
        limpar_caches()
        st.rerun()

# ================================================
# 10) PÁGINA — ENVIAR BASE
# ================================================
if menu == opcoes_full["Enviar"]:
    st.title("📤 Enviar Itens do SAP")

    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(
            "Exporte os itens no SAP, preencha **CATEGORIA**, **STATUS** e **DATA_STATUS** "
            "na planilha e envie o arquivo aqui. Você confere o resultado da validação "
            "antes de qualquer coisa ser gravada. Categoria e status precisam estar "
            "cadastrados em **🏷️ Categorias e Status**."
        )
    with col_b:
        st.download_button(
            "📄 Baixar modelo",
            data=gerar_modelo_xlsx(),
            file_name="Modelo_Base_Padrao.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

    with st.expander("ℹ️ Colunas esperadas"):
        st.markdown("**Essenciais** — são estas que vão para o banco. Se faltar alguma, o envio é bloqueado.")
        st.dataframe(
            pd.DataFrame([{
                "Coluna na planilha": c["titulo"],
                "Tipo": c["tipo"],
                "Obrigatório": "SIM" if c.get("obrigatorio") else "não",
            } for c in COLUNAS]),
            hide_index=True, width="stretch"
        )
        st.markdown(
            "**De formato** — não são gravadas. Servem para reconhecer a exportação "
            "padrão; se faltarem, o app pede sua confirmação antes de enviar."
        )
        st.dataframe(
            pd.DataFrame({"Coluna na planilha": COLUNAS_FORMATO}),
            hide_index=True, width="stretch"
        )

    arquivo = st.file_uploader(
        "Arraste aqui a exportação .xlsx do SAP",
        type=["xlsx", "xlsm"],
    )

    if arquivo is not None:
        conteudo = arquivo.getvalue()
        assinatura = hash_arquivo(conteudo)

        # Novo arquivo? zera a validação anterior
        if st.session_state.get("assinatura_atual") != assinatura:
            st.session_state.assinatura_atual = assinatura
            st.session_state.pop("df_validado", None)

        # Ler e validar 200 mil linhas leva minutos. O Streamlit roda o script
        # inteiro a CADA interação — marcar a confirmação, abrir um painel,
        # apertar Gravar —, então sem guardar o resultado o usuário pagava a
        # validação de novo em cada clique. Era daí que vinha a maior parte da
        # espera, não da gravação. O resultado fica preso à assinatura do
        # arquivo: trocou o arquivo, revalida; é o mesmo, reaproveita.
        if st.session_state.get("df_validado") is None:
            try:
                df_bruto = pd.read_excel(
                    io.BytesIO(conteudo),
                    sheet_name=ABA_EXCEL if ABA_EXCEL is not None else 0,
                    dtype=object,
                )
            except Exception as e:
                st.error(f"Não consegui ler a planilha: {e}")
                st.stop()

            try:
                resultado = validar_planilha(df_bruto)
            except Exception as e:
                st.error("Não consegui validar a planilha: o banco recusou uma "
                         "consulta.\n\n" + descrever_erro_supabase(e))
                st.stop()

            # A conferência de duplicidades também é cara e também vinha sendo
            # refeita a cada clique. Entra no mesmo pacote.
            resultado["existentes"] = consultar_existentes(resultado["df"])
            # O bruto some daqui: guardar 200 mil linhas cruas na sessão seria
            # memória à toa. O que a tela ainda usa dele é só a contagem.
            resultado["linhas_arquivo"] = len(df_bruto)
            del df_bruto
            st.session_state["df_validado"] = resultado

        resultado = st.session_state["df_validado"]
        if st.button("🔄 Revalidar", help="Refaz a leitura e a conferência do "
                     "arquivo — use depois de cadastrar o que estava faltando."):
            st.session_state.pop("df_validado", None)
            limpar_caches()
            st.rerun()
        df_pronto       = resultado["df"]
        df_erros        = resultado["erros"]
        avisos          = resultado["avisos"]
        formato_ausente = resultado["formato_ausente"]
        df_retidas      = resultado["retidas"]
        df_duplicadas   = resultado["duplicadas"]
        nao_cadastrados = resultado["nao_cadastrados"]

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            kpi("Linhas no arquivo", f'{resultado["linhas_arquivo"]:,}'.replace(",", "."))
        with c2:
            kpi("Vão subir", f"{0 if df_pronto is None else len(df_pronto):,}".replace(",", "."))
        with c3:
            kpi("Retidas", f"{len(df_retidas):,}".replace(",", "."))
        with c4:
            kpi("Problemas", f"{len(df_erros):,}".replace(",", "."))

        for aviso in avisos:
            st.info(aviso)

        # --- Assinatura do formato: não bloqueia, mas exige confirmação ---
        # Estas colunas não vão para o banco; servem para reconhecer que o
        # arquivo é mesmo a exportação padrão. Faltando alguma, a planilha pode
        # ser de outra origem — então paramos e perguntamos.
        formato_confirmado = True
        if formato_ausente:
            st.warning(
                "⚠️ **Esta planilha não parece ser a exportação padrão.**\n\n"
                "Não encontrei estas colunas de identificação do formato: **"
                + ", ".join(formato_ausente) + "**.\n\n"
                "Elas não são gravadas no banco, mas a ausência delas sugere que o "
                "arquivo veio de outra origem ou foi alterado. Confira se é mesmo a "
                "planilha certa antes de seguir."
            )
            formato_confirmado = st.checkbox(
                "Confirmo que esta é a planilha correta e quero continuar mesmo assim.",
                key="confirma_formato",
            )
            if not formato_confirmado:
                st.info("Marque a confirmação acima para liberar o envio.")

        if not formato_confirmado:
            pass  # trava o fluxo até o usuário confirmar

        elif not df_erros.empty:
            st.error("A planilha tem problemas e **não foi gravada**. Corrija as linhas abaixo e envie novamente.")
            st.dataframe(df_erros, hide_index=True, width="stretch", height=320)
            st.download_button(
                "⬇️ Baixar relatório de erros",
                data=df_para_xlsx(df_erros, "Erros"),
                file_name=f"Erros_{arquivo.name.rsplit('.', 1)[0]}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        else:
            # ---- Alerta: valor de CATEGORIA/STATUS que não está cadastrado ----
            # Vem antes das retidas porque é o problema acionável: basta
            # cadastrar a palavra e reenviar.
            if nao_cadastrados:
                partes = []
                for tipo, valores in nao_cadastrados.items():
                    rotulo = TIPOS_DOMINIO[tipo]["titulo"].upper()
                    itens = ", ".join(
                        f"**{v}** ({n} linha{'s' if n > 1 else ''})"
                        for v, n in sorted(valores.items(), key=lambda x: -x[1]))
                    partes.append(f"- {rotulo}: {itens}")
                st.error(
                    "🚫 **Há valores que ainda não estão cadastrados.** As linhas "
                    "que os usam não sobem — cadastre-os em **🏷️ Categorias e "
                    "Status** e reenvie a planilha.\n\n"
                    + "\n".join(partes)
                )

            # ---- Alerta: linhas retidas por falta de STATUS/DATA_STATUS ----
            if not df_retidas.empty:
                st.warning(
                    f"⚠️ **{len(df_retidas)} linha(s) ficam de fora deste envio** — "
                    "a coluna *Problema* diz o motivo de cada uma: campo em branco "
                    "ou valor que ainda não está cadastrado.\n\n"
                    + (f"As outras **{len(df_pronto)}** seguem normalmente para o Supabase. "
                       if df_pronto is not None else "")
                    + "Corrija a planilha (ou cadastre o que falta) e reenvie para completar."
                )
                with st.expander(f"Ver as {len(df_retidas)} linha(s) retida(s)", expanded=True):
                    st.dataframe(df_retidas, hide_index=True, width="stretch", height=240)
                    st.download_button(
                        "⬇️ Baixar linhas retidas",
                        data=df_para_xlsx(df_retidas, "Retidas"),
                        file_name=f"Retidas_{arquivo.name.rsplit('.', 1)[0]}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

            # ---- Alerta: chave repetida dentro do próprio arquivo ----
            if not df_duplicadas.empty:
                descartadas = int((df_duplicadas["Situação"] == "descartada").sum())
                st.warning(
                    f"⚠️ **Registros repetidos no arquivo:** {len(df_duplicadas)} linha(s) têm o "
                    "mesmo Lançamento contábil, Data do documento, STATUS e DATA_STATUS.\n\n"
                    f"Como não pode haver dois registros iguais nesses 4 campos, "
                    f"{descartadas} foram descartadas e ficou só a última ocorrência de cada."
                )
                with st.expander(f"Ver as {len(df_duplicadas)} linha(s) repetida(s)"):
                    st.dataframe(df_duplicadas, hide_index=True, width="stretch", height=240)

            if df_pronto is None or df_pronto.empty:
                st.error(
                    "Nenhuma linha deste arquivo pode ser enviada — veja os motivos "
                    "acima. Corrija a planilha (ou cadastre os valores que faltam) "
                    "e envie novamente."
                )
            else:
                # ---- Alerta: já existe no Supabase com a mesma chave ----
                df_existentes = resultado.get("existentes", pd.DataFrame())
                if not df_existentes.empty:
                    st.warning(
                        f"⚠️ **{len(df_existentes)} linha(s) já estão gravadas** com exatamente o "
                        "mesmo Lançamento contábil, Data do documento, STATUS e DATA_STATUS.\n\n"
                        "Não vão gerar registro duplicado — o envio apenas regrava o que já existe. "
                        "Se a intenção era registrar uma mudança de status, confira o STATUS e a "
                        "DATA_STATUS dessas linhas antes de continuar."
                    )
                    with st.expander(f"Ver as {len(df_existentes)} linha(s) já gravada(s)"):
                        st.dataframe(df_existentes, hide_index=True, width="stretch", height=240)

                anterior = lote_ja_enviado(assinatura)
                if anterior:
                    st.warning(
                        f"⚠️ Este arquivo idêntico já foi enviado em "
                        f"{str(anterior.get('criado_em'))[:16].replace('T', ' ')} por "
                        f"{anterior.get('criado_por_nome')}."
                    )

                st.success(f"✅ {len(df_pronto)} linha(s) prontas para envio. Confira a prévia e confirme.")
                st.dataframe(df_pronto.head(50), hide_index=True, width="stretch", height=320)
                if len(df_pronto) > 50:
                    st.caption(f"Exibindo 50 de {len(df_pronto)} linhas.")

                confirmar = st.checkbox("Confirmo que os dados acima estão corretos.")
                if st.button("🚀 Gravar no Supabase", disabled=not confirmar):
                    try:
                        lote_id = gravar_lote(df_pronto, arquivo.name, conteudo,
                                              formato_ausente, len(df_retidas))
                        limpar_caches()
                        st.session_state.pop("df_validado", None)
                        st.success(
                            f"🎉 {len(df_pronto)} linha(s) consolidadas com sucesso!\n\n"
                            + (f"⚠️ {len(df_retidas)} linha(s) ficaram retidas por falta de "
                               "STATUS/DATA_STATUS.\n\n" if not df_retidas.empty else "")
                            + f"**Lote:** `{lote_id}`"
                        )
                        st.balloons()
                    except Exception as e:
                        st.error(f"Erro ao gravar: {e}")


# ================================================
# 11) PÁGINA — ENVIOS (histórico + estorno)
# ================================================
elif menu == opcoes_full["Envios"]:
    st.title("🧾 Envios")
    st.caption("Todo envio feito no formulário, por qualquer usuário.")
    df_lotes = carregar_lotes()

    if df_lotes.empty:
        st.info("Nenhum envio registrado ainda.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            kpi("Envios", len(df_lotes))
        with c2:
            kpi("Linhas gravadas", f"{int(df_lotes['linhas'].fillna(0).sum()):,}".replace(",", "."))
        with c3:
            retidas_col = df_lotes["linhas_retidas"] if "linhas_retidas" in df_lotes else pd.Series(dtype=float)
            kpi("Linhas retidas", f"{int(retidas_col.fillna(0).sum()):,}".replace(",", "."))
        with c4:
            kpi("Estornados", int((df_lotes["status"] == "estornado").sum()))

        colunas_visiveis = [c for c in
                            ["criado_em", "arquivo", "linhas", "linhas_retidas", "status",
                             "criado_por_nome", "criado_por_email", "formato_ausente", "mensagem"]
                            if c in df_lotes.columns]
        st.dataframe(df_lotes[colunas_visiveis], hide_index=True, width="stretch", height=340)


        # ------------------------------------------------------------------
        # ESTORNO DESATIVADO (a pedido) — para reativar, descomente este bloco
        # e a função estornar_lote() logo acima da seção de caches.
        # ------------------------------------------------------------------
        # st.subheader("↩️ Estornar um envio")
        # st.caption(
            # "O estorno marca como excluídas todas as linhas daquele envio (soft delete — "
            # "nada é apagado de fato)."
        # )
        # ativos = df_lotes[df_lotes["status"] == "efetivado"]
        # if ativos.empty:
            # st.info("Não há envios efetivados para estornar.")
        # else:
            # rotulos = {
                # f"{str(r['criado_em'])[:16].replace('T', ' ')} · {r['arquivo']} · "
                # f"{int(r['linhas']) if pd.notna(r['linhas']) else 0} linhas · "
                # f"{r.get('criado_por_nome') or r.get('criado_por_email')}": r["id"]
                # for _, r in ativos.iterrows()
            # }
            # escolhido = st.selectbox("Envio:", list(rotulos.keys()))
            # confirma = st.checkbox("Confirmo o estorno deste envio.", key="confirma_estorno")
            # if st.button("↩️ Estornar envio", disabled=not confirma):
                # try:
                    # afetadas = estornar_lote(rotulos[escolhido])
                    # limpar_caches()
                    # if afetadas:
                        # st.success(f"Envio estornado: {afetadas} linha(s) marcadas como excluídas.")
                    # else:
                        # st.warning(
                            # "Envio marcado como estornado, mas **nenhuma linha foi alterada**: "
                            # "as linhas dele já haviam sido sobrescritas por um envio posterior "
                            # "com as mesmas chaves. Para voltar aos valores antigos, reenvie a "
                            # "planilha correta."
                        # )
                # except Exception as e:
                    # st.error(f"Erro ao estornar: {e}")

# ================================================
# 12) PÁGINA — DADOS CONSOLIDADOS
# ================================================
elif menu == opcoes_full["Consolidado"]:
    st.title("🗂️ Dados Consolidados")
    df_cons = carregar_consolidado()

    if df_cons.empty:
        st.info("Ainda não há dados consolidados.")
    else:
        # Carteira, cliente, contrato, responsáveis e tipo de fatura NÃO vêm do
        # arquivo do SAP: vêm do cadastro De-Para BPS, casado pela trinca.
        df_cons, sem_depara = juntar_com_depara(df_cons)
        colunas_dp = [c["coluna"] for c in CAMPOS_DEPARA]

        st.caption(
            "Os campos comerciais (carteira, cliente, contrato, responsáveis e tipo "
            "de fatura) vêm do cadastro **🔗 De-Para BPS**, casados pela trinca "
            "*Cliente + Nº ID fiscal 1 + Nome do cliente*. Alterar o de-para muda "
            "esta tela na hora, inclusive para itens já enviados."
        )

        busca = st.text_input(
            "Buscar", placeholder="lançamento, cliente, CNPJ, nome, contrato...",
            key="cons_busca")

        # --- Filtros vindos do DE-PARA (+ o STATUS, que é do item) ---
        l1 = st.columns(4)
        l2 = st.columns(4)
        caixas = l1 + l2
        filtros_disponiveis = [
            ("status", "STATUS"),
            ("carteira", "CARTEIRA"),
            ("cliente_grupo", "CLIENTE"),
            ("contrato", "CONTRATO"),
            ("tipo_fatura", "TIPO DE FATURA"),
            ("responsavel_cobranca", "RESPONSAVEL COBRANCA"),
            ("responsavel_faturamento", "RESPONSAVEL FATURAMENTO"),
        ]

        df_filtrado = df_cons.copy()
        escolhas = {}
        for caixa, (coluna, titulo) in zip(caixas, filtros_disponiveis):
            with caixa:
                if coluna not in df_cons.columns:
                    continue
                valores = sorted(df_cons[coluna].dropna().astype(str).unique().tolist())
                escolhas[coluna] = st.selectbox(
                    titulo, ["(todos)"] + valores, key=f"cons_f_{coluna}")

        with caixas[7]:
            st.write("")
            so_sem_depara = st.checkbox(
                "Só sem de-para", key="cons_sem_dp",
                help="Itens cujo cliente ainda não está cadastrado no De-Para BPS.")

        for coluna, escolha in escolhas.items():
            if escolha != "(todos)":
                df_filtrado = df_filtrado[df_filtrado[coluna].astype(str) == escolha]

        if so_sem_depara:
            df_filtrado = df_filtrado[~df_filtrado["_tem_depara"]]

        if busca.strip():
            alvo = normalizar_texto(busca)
            colunas_busca = [c for c in
                             ["lancamento_contabil"] + CHAVE_DEPARA + colunas_dp
                             if c in df_filtrado.columns]
            df_filtrado = df_filtrado[df_filtrado[colunas_busca].apply(
                lambda linha: alvo in normalizar_texto(" ".join(
                    "" if v is None else str(v) for v in linha)), axis=1)]

        # --- KPIs ---
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            kpi("Linhas exibidas", f"{len(df_filtrado):,}".replace(",", "."))
        with k2:
            kpi("Clientes", df_filtrado["nome_cliente"].nunique()
                if "nome_cliente" in df_filtrado else 0)
        with k3:
            kpi("Contratos", df_filtrado["contrato"].nunique()
                if "contrato" in df_filtrado else 0)
        with k4:
            kpi("Sem de-para", f"{sem_depara:,}".replace(",", "."))

        if sem_depara:
            st.warning(
                f"⚠️ **{sem_depara} item(ns) não têm de-para cadastrado** — ficam sem "
                "carteira, contrato e responsáveis, e não aparecem quando você filtra "
                "por esses campos. Marque **Só sem de-para** para ver quais são e "
                "cadastre a trinca na aba **🔗 De-Para BPS**."
            )

        # Ordem das colunas: item primeiro, de-para depois, controle no fim.
        do_item = [c["coluna"] for c in COLUNAS if c["coluna"] in df_filtrado.columns]
        controle = [c for c in ["criado_por_nome", "criado_por_email", "criado_em"]
                    if c in df_filtrado.columns]
        visiveis = do_item + [c for c in colunas_dp if c in df_filtrado.columns] + controle

        st.dataframe(df_filtrado[visiveis], hide_index=True, width="stretch", height=420)
        st.download_button(
            "⬇️ Baixar em Excel",
            data=df_para_xlsx(df_filtrado[visiveis], "Consolidado"),
            file_name=f"Consolidado_{datetime.now():%Y%m%d_%H%M}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )




# ================================================
# 14) PÁGINA — INDICADOR DE JUSTIFICATIVAS
# ================================================
elif menu == opcoes_full["Indicador"]:
    st.title("📊 Indicador de Justificativas")

    try:
        cubo = carregar_cubo()
    except Exception as e:
        if cubo_ainda_nao_existe(e):
            cubo = pd.DataFrame()
        else:
            st.error("Não consegui ler a base do indicador no MinIO.\n\n"
                     + descrever_erro_supabase(e))
            st.stop()

    if cubo.empty:
        st.warning(
            "**A base do indicador ainda não foi gerada.**\n\n"
            f"O formulário procura `{OBJETO_CUBO}` no bucket "
            f"`{BUCKET_CUBO}` e não encontrou. Rode o "
            "**montar_base_indicador.py --minio** no servidor e atualize "
            "esta página."
        )
        st.stop()

    st.caption(
        "Universo: os documentos do SAP cujos **tipos** estiverem marcados "
        "abaixo. Vêm marcados por padrão os de faturamento — os de "
        "recebimento e ajuste não têm CT-e e nunca entraram no fluxo de "
        "justificativa, mas estão disponíveis para conferência. A base é "
        "recalculada uma vez por dia."
    )

    # ---------------- tipos de documento ----------------
    # O arquivo traz TODOS os tipos; os marcados por padrão são os que o job
    # definiu como universo. Deixar a escolha aqui é o que permite validar o
    # recorte com a área de negócio sem regerar a base.
    contagem_tipo = (cubo.groupby("tipo_documento")["documentos"].sum()
                     .sort_values(ascending=False))
    padrao = set(cubo.loc[cubo["tipo_padrao"], "tipo_documento"].unique())
    marcados_agora = [t for t in contagem_tipo.index
                      if st.session_state.get(f"ind_tipo_{t}", t in padrao)]

    with st.expander(f"🧾 Tipos de documento — {len(marcados_agora)} de "
                     f"{len(contagem_tipo)} marcados", expanded=False):
        st.caption(
            "Só os tipos de faturamento têm CT-e por trás (RV 98,2%, ZB 96,1%); "
            "nos demais a ligação é 0%. Marcar um tipo de recebimento infla o "
            "universo com documentos que ninguém vai justificar — útil para "
            "conferir, enganoso como indicador."
        )
        tipos_marcados = []
        caixas = st.columns(5)
        for i, (tipo, quantos) in enumerate(contagem_tipo.items()):
            with caixas[i % 5]:
                rotulo = f"{tipo} ({quantos:,})".replace(",", ".")
                if st.checkbox(rotulo, value=(tipo in padrao),
                               key=f"ind_tipo_{tipo}"):
                    tipos_marcados.append(tipo)

    if not tipos_marcados:
        st.info("Marque ao menos um tipo de documento para ver os números.")
        st.stop()

    # ---------------- filtros ----------------
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1.4])
    with c1:
        clientes = sorted(cubo["cliente_nome"].dropna().unique().tolist())
        f_cliente = st.multiselect("CLIENTE", clientes, key="ind_cliente")
    with c2:
        categorias = sorted(cubo["categoria"].dropna().unique().tolist())
        f_categoria = st.multiselect(
            "JUSTIFICATIVA", categorias, key="ind_categoria",
            help="A categoria é a justificativa. Documentos ainda não enviados "
                 "não têm nenhuma — use o filtro de situação para vê-los.")
    with c3:
        meses = sorted(cubo["mes"].dropna().unique().tolist())
        if meses:
            de, ate = st.select_slider(
                "PERÍODO (mês do documento)",
                options=meses,
                value=(meses[0], meses[-1]),
                format_func=lambda d: pd.Timestamp(d).strftime("%m/%Y"),
                key="ind_periodo")
        else:
            de = ate = None
    with c4:
        f_aberto = st.selectbox("SITUAÇÃO NO SAP",
                                ["(todos)", "Em aberto", "Compensado"],
                                key="ind_aberto")

    df = cubo[cubo["tipo_documento"].isin(tipos_marcados)].copy()
    if f_cliente:
        df = df[df["cliente_nome"].isin(f_cliente)]
    if f_categoria:
        df = df[df["categoria"].isin(f_categoria)]
    if de is not None:
        df = df[(df["mes"] >= de) & (df["mes"] <= ate)]
    if f_aberto == "Em aberto":
        df = df[df["em_aberto"]]
    elif f_aberto == "Compensado":
        df = df[~df["em_aberto"]]

    if df.empty:
        st.info("Nenhum documento com esses filtros.")
        st.stop()

    def soma(condicao=None):
        alvo = df if condicao is None else df[condicao]
        return int(alvo["documentos"].sum())

    total = soma()

    # ---------------- 1) falta justificar ----------------
    st.subheader("Justificativa")
    justificados = soma(df["justificado"])
    sem_definicao = soma(df["enviado"] & ~df["justificado"])
    nao_enviados = soma(~df["enviado"])

    def mil(n):
        """Separador de milhar brasileiro, número a número — formatar a frase
        inteira com .replace(',', '.') comia também a pontuação do texto."""
        return f"{int(n):,}".replace(",", ".")

    def pct(parte):
        return f"{100.0 * parte / total:.1f}%".replace(".", ",") if total else "—"

    falta = sem_definicao + nao_enviados
    k = st.columns(4)
    with k[0]:
        kpi_nota("DOCUMENTOS NO SAP", mil(total),
                 f"tipos: {', '.join(sorted(tipos_marcados))}")
    with k[1]:
        kpi_nota("JUSTIFICADOS", mil(justificados), f"{pct(justificados)} do total",
                 "verde" if justificados and justificados >= falta else "laranja")
    with k[2]:
        kpi_nota("FALTA JUSTIFICAR", mil(falta),
                 f"{pct(falta)} · {mil(nao_enviados)} nem enviados, "
                 f"{mil(sem_definicao)} sem definição",
                 "vermelho" if falta else "verde")
    with k[3]:
        milhoes = df["valor"].sum() / 1e6
        # pt-BR: troca ponto e vírgula de papel. O .replace(",", ".") sozinho
        # transformava "1,754.0" em "1.754.0" — ponto decimal errado.
        texto_valor = f"{milhoes:,.1f}".replace(",", "~").replace(".", ",").replace("~", ".")
        kpi_nota("VALOR NO FILTRO", f"R$ {texto_valor} mi",
                 "soma dos documentos selecionados")

    def mil(n):
        """Separador de milhar brasileiro. Formatar número a número evita o
        .replace(',', '.') na frase inteira, que comia também a pontuação."""
        return f"{n:,}".replace(",", ".")

    # --- o ritmo: quantas justificativas por mês ---
    # ATENÇÃO ao eixo. Comparar pelo mês do DOCUMENTO mede maturidade, não
    # desempenho: um mês recente aparece sempre com 0% justificado porque
    # ninguém chegou nele ainda — foi o que a primeira versão desta tela
    # mostrou (set/2026 com 0% contra 49% de ago/2026, o que parecia uma
    # queda e era só o calendário). O eixo certo é a DATA DO STATUS: quando
    # a justificativa foi de fato registrada.
    ritmo = (df[df["justificado"] & df["mes_status"].notna()]
             .groupby("mes_status", as_index=False)["documentos"].sum()
             .sort_values("mes_status"))

    if len(ritmo) >= 2:
        atual, antes = ritmo.iloc[-1], ritmo.iloc[-2]
        nome = pd.Timestamp(atual["mes_status"]).strftime("%m/%Y")
        nome_ant = pd.Timestamp(antes["mes_status"]).strftime("%m/%Y")
        txt, cor = seta(int(atual["documentos"]), int(antes["documentos"]),
                        "documentos")
        titulo_secao("Ritmo das justificativas",
                     "Quantas foram registradas em cada mês, pela data do "
                     "status. Mede o andamento do trabalho — diferente do mês "
                     "do documento, que mede só a idade do que entrou.")
        c = st.columns(4)
        with c[0]:
            kpi_nota(f"JUSTIFICADAS EM {nome}", mil(int(atual["documentos"])),
                     f"{nome_ant}: {mil(int(antes['documentos']))}")
        with c[1]:
            kpi_nota("CONTRA O MÊS ANTERIOR", txt, "em quantidade", cor)
        with c[2]:
            restante = falta
            por_mes = int(atual["documentos"]) or 1
            kpi_nota("NO RITMO ATUAL", f"{restante / por_mes:,.0f} meses"
                     .replace(",", "."),
                     "para zerar o que falta, se o ritmo se mantiver",
                     "vermelho" if restante / por_mes > 12 else "laranja")
        with c[3]:
            kpi_nota("MESES COM REGISTRO", str(len(ritmo)),
                     "histórico disponível para comparar")
        if len(ritmo) < 3:
            st.caption(
                "Só há " + str(len(ritmo)) + " meses de histórico: o processo "
                "começou agora. A comparação ganha sentido com mais tempo.")

    # ---------------- 2) valor correto ----------------
    st.subheader("Valor correto do CT-e")
    com_cte = soma(df["tem_cte"])
    confirmado = soma(df["tem_cte"] & (df["situacao_valor"] == "CONFIRMADO"))
    analise = soma(df["tem_cte"] & (df["situacao_valor"] == "EM ANALISE"))
    sem_registro = soma(df["tem_cte"] & (df["situacao_valor"] == "SEM REGISTRO"))

    k = st.columns(4)
    with k[0]:
        kpi_pct("COM CT-e", com_cte, total)
    with k[1]:
        kpi_pct("VALOR CONFIRMADO", confirmado, com_cte)
    with k[2]:
        kpi_pct("EM ANÁLISE", analise, com_cte)
    with k[3]:
        kpi_pct("SEM REGISTRO", sem_registro, com_cte)
    st.caption(
        "Os percentuais desta linha são sobre os documentos **com CT-e** — "
        "só esses têm valor a conferir. *Sem registro* é o que nunca foi "
        "enviado na aba 💲 Valor Correto do CT-e; *em análise* já foi enviado, "
        "mas ainda sem valor apurado."
    )

    # ---------------- 3) comparações ----------------
    st.subheader("Onde está o que falta")
    st.caption(
        "Em cada barra, o comprimento é o **total** daquele corte e as fatias "
        "mostram o andamento. Quanto mais clara a barra, mais longe de estar "
        "justificada. O número na ponta é o total."
    )

    st.markdown(legenda_html(ESTADOS_ORDEM, ESTADOS_COR), unsafe_allow_html=True)

    graf = df.copy()
    graf["estado"] = classificar_estado(graf)

    aba_mes, aba_tipo, aba_cli = st.tabs(
        ["Por mês", "Por tipo de documento", "Maiores clientes"])

    with aba_mes:
        # O eixo vai de 2018 a hoje, mas 2018-2024 somam menos de 4% do volume:
        # no padrão, dois terços da largura ficavam vazios e as barras que
        # importam viravam fios. Este corte é SÓ do gráfico — os KPIs acima
        # continuam sobre o período inteiro do filtro.
        recente = st.checkbox("Mostrar apenas os últimos 24 meses", value=True,
                              key="ind_mes_recente")
        por_mes = (graf.groupby(["mes", "estado"], as_index=False)["documentos"]
                   .sum())
        if recente and not por_mes.empty:
            corte = sorted(por_mes["mes"].unique())[-24:]
            por_mes = por_mes[por_mes["mes"].isin(corte)]
        g = grafico_progresso(por_mes, "mes", "Mês do documento",
                              altura=300, horizontal=False)
        if g is not None:
            st.altair_chart(g, width="stretch")
        st.caption("É aqui que se vê se a fila está sendo vencida ou crescendo.")

    with aba_tipo:
        por_tipo = (graf.groupby(["tipo_documento", "estado"], as_index=False)
                    ["documentos"].sum())
        g = grafico_progresso(por_tipo, "tipo_documento", "Tipo",
                              altura=max(180, 46 * por_tipo["tipo_documento"].nunique()))
        if g is not None:
            st.altair_chart(g, width="stretch")

    with aba_cli:
        maiores = (graf.groupby("cliente_nome")["documentos"].sum()
                   .nlargest(10).index)
        por_cli = (graf[graf["cliente_nome"].isin(maiores)]
                   .groupby(["cliente_nome", "estado"], as_index=False)
                   ["documentos"].sum())
        g = grafico_progresso(por_cli, "cliente_nome", "Cliente", altura=380)
        if g is not None:
            st.altair_chart(g, width="stretch")
        st.caption("Os 10 maiores em volume dentro do filtro atual.")

    # ---------------- 4) por status ----------------
    st.subheader("Dos justificados, quantidade por status")
    por_status = (df[df["justificado"]]
                  .groupby("status", dropna=False)["documentos"].sum()
                  .sort_values(ascending=False).reset_index())
    if por_status.empty:
        st.info("Nenhum documento justificado com esses filtros.")
    else:
        por_status["%"] = (100.0 * por_status["documentos"]
                           / por_status["documentos"].sum()).round(1)
        por_status.columns = ["STATUS", "DOCUMENTOS", "%"]
        # Barra DENTRO da tabela (ProgressColumn), como no painel de
        # Segurança: o rótulo longo não é cortado como seria num eixo.
        st.dataframe(
            por_status, hide_index=True, width="stretch",
            height=min(460, 45 + 35 * len(por_status)),
            column_config={
                "STATUS": st.column_config.TextColumn("STATUS", width="large"),
                "DOCUMENTOS": st.column_config.ProgressColumn(
                    "DOCUMENTOS", format="%d", min_value=0,
                    max_value=int(por_status["DOCUMENTOS"].max())),
                "%": st.column_config.NumberColumn("%", format="%.1f%%"),
            })

        # A justificativa manda no status: ver os dois juntos evita ler
        # um status fora do contexto da categoria que o gerou.
        with st.expander("Abrir por justificativa × status"):
            cruz = (df[df["justificado"]]
                    .pivot_table(index="categoria", columns="status",
                                 values="documentos", aggfunc="sum",
                                 fill_value=0, margins=True, margins_name="TOTAL"))
            st.dataframe(cruz, width="stretch")

    # ---------------- conferência ----------------
    st.divider()
    st.subheader("Conferir os números")
    st.caption(
        "Todo número desta tela pode ser aberto documento a documento. "
        "Escolha qual conjunto quer examinar: a contagem aqui tem de bater "
        "exatamente com o card correspondente lá em cima."
    )

    with st.expander("ℹ️ Como cada número é calculado"):
        tipos_txt = ", ".join(sorted(cubo["tipo_documento"].dropna().unique()))
        st.markdown(f"""
**Universo** — todo documento do SAP (`CV_G_DM_ARITMCLI`) cujo tipo é
{tipos_txt}. Um documento é identificado por *lançamento contábil + data do
documento*; essa dupla é única, enquanto o número sozinho se repete entre
períodos fiscais. Tipos de recebimento e ajuste ficam de fora: não têm CT-e
e nunca entraram no fluxo de justificativa.

**Justificado** — o documento existe no `upload_itens_sap` e o seu status não
é um dos que significam "ainda não analisado". Quando há histórico, vale a
**última** situação (maior data de status).

**Falta justificar** — o resto, separado em *nunca enviado ao formulário* e
*enviado, mas sem definição*.

**Com CT-e** — o documento casou com o `CTE_CONTABIL` por *documento + data do
CT-e*. Atenção: a "Data do documento" do SAP é a data de **emissão do CT-e**,
não a de lançamento — usar a de lançamento perderia 12% das ligações.

**Situação do valor** — vem do `upload_valores_cte`, casado pela
*Referência* do SAP (a chave do conhecimento). *Sem registro* é o que nunca
foi enviado na aba 💲; *em análise* foi enviado, mas ainda sem valor apurado.
        """)

    conjuntos = {
        "Tudo que está no filtro": [],
        f"Falta justificar ({mil(sem_definicao + nao_enviados)})":
            [("justificado", "=", False)],
        f"— nunca enviados ({mil(nao_enviados)})": [("enviado", "=", False)],
        f"— enviados sem definição ({mil(sem_definicao)})":
            [("enviado", "=", True), ("justificado", "=", False)],
        f"Justificados ({mil(justificados)})": [("justificado", "=", True)],
        f"Valor em análise ({mil(analise)})":
            [("situacao_valor", "=", "EM ANALISE")],
        f"Valor sem registro ({mil(sem_registro)})":
            [("situacao_valor", "=", "SEM REGISTRO")],
        f"Valor confirmado ({mil(confirmado)})":
            [("situacao_valor", "=", "CONFIRMADO")],
    }

    escolha = st.selectbox("Conjunto a examinar", list(conjuntos.keys()),
                           key="ind_conjunto")

    # Os mesmos filtros da tela, traduzidos para o detalhe.
    filtros = list(conjuntos[escolha])
    filtros.append(("tipo_documento", "in", tipos_marcados))
    if f_cliente:
        filtros.append(("cliente_nome", "in", f_cliente))
    if f_categoria:
        filtros.append(("categoria", "in", f_categoria))
    if de is not None:
        filtros.append(("mes", ">=", de))
        filtros.append(("mes", "<=", ate))
    if f_aberto == "Em aberto":
        filtros.append(("em_aberto", "=", True))
    elif f_aberto == "Compensado":
        filtros.append(("em_aberto", "=", False))

    # A contagem sai do cubo, de graça: não custa ler o detalhe para descobrir
    # que ele é grande demais.
    previsto = {
        "Tudo que está no filtro": total,
    }.get(escolha)
    if previsto is None:
        for rotulo, quantos in (("Falta justificar", sem_definicao + nao_enviados),
                                ("nunca enviados", nao_enviados),
                                ("enviados sem definição", sem_definicao),
                                ("Justificados", justificados),
                                ("Valor em análise", analise),
                                ("Valor sem registro", sem_registro),
                                ("Valor confirmado", confirmado)):
            if rotulo in escolha:
                previsto = quantos
                break

    grande_demais = previsto is not None and previsto > TETO_DOCUMENTOS
    if grande_demais:
        st.warning(
            f"Este conjunto tem **{mil(previsto)}** documentos — acima do teto "
            f"de {mil(TETO_DOCUMENTOS)} para exportação.\n\n"
            "Estreite os filtros (um cliente, um período) e a exportação "
            "libera. O teto existe porque montar um arquivo desse tamanho "
            "consome mais memória do que o servidor tem, e porque uma "
            "planilha de centenas de milhares de linhas não é conferível na "
            "prática — o resumo agregado desta tela continua baixável abaixo."
        )

    if st.button("🔍 Carregar os documentos", key="ind_carregar",
                 disabled=grande_demais):
        with st.spinner("Lendo o detalhe..."):
            try:
                st.session_state["ind_detalhe"] = documentos(filtros)
            except Exception as e:
                st.error("Não consegui ler o detalhe.\n\n"
                         + descrever_erro_supabase(e))
                st.session_state.pop("ind_detalhe", None)

    det = st.session_state.get("ind_detalhe")
    if det is not None:
        if det.empty:
            st.info("Nenhum documento neste conjunto — ou o arquivo de "
                    "detalhe ainda não foi publicado no MinIO.")
        else:
            st.success(f"**{mil(len(det))}** documento(s). "
                       "Confira contra o card correspondente.")
            visao = det.head(500).rename(columns=TITULOS_DETALHE)
            st.dataframe(visao, hide_index=True, width="stretch", height=320)
            if len(det) > 500:
                st.caption(f"Mostrando 500 de {mil(len(det))}. "
                           "A exportação leva tudo.")

            exportar = det.rename(columns=TITULOS_DETALHE)
            nome = f"Documentos_{datetime.now():%Y-%m-%d}"
            if len(det) <= TETO_XLSX:
                st.download_button(
                    f"⬇️ Baixar {mil(len(det))} documento(s) em Excel",
                    data=df_para_xlsx(exportar, "Documentos"),
                    file_name=nome + ".xlsx",
                    mime="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet")
            else:
                st.download_button(
                    f"⬇️ Baixar {mil(len(det))} documento(s) em CSV",
                    data=exportar.to_csv(index=False, sep=";",
                                         decimal=",").encode("utf-8-sig"),
                    file_name=nome + ".csv", mime="text/csv")
                st.caption(
                    f"Acima de {mil(TETO_XLSX)} linhas a saída é CSV — gerar "
                    "um xlsx desse tamanho levaria minutos e o Excel "
                    "trava para abrir. O CSV usa ponto e vírgula e vírgula "
                    "decimal, então abre direto no Excel em português.")

    st.divider()
    st.download_button(
        "⬇️ Baixar o resumo desta tela (números agregados)",
        data=df_para_xlsx(df, "Indicador"),
        file_name=f"Indicador_resumo_{datetime.now():%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ================================================
# 13) PÁGINA — DE-PARA BPS (CRUD)
# ================================================
elif menu == opcoes_full["Depara"]:
    st.title("🔗 De-Para BPS")
    st.caption(
        "Para cada **Cliente + Nº ID fiscal 1 + Nome do cliente** existe um de-para "
        "com carteira, cliente, contrato, responsáveis e tipo de fatura. "
        "Toda alteração fica registrada no histórico."
    )

    df_dp = carregar_depara()

    def campo_de_valor(spec, atual, sugestoes, prefixo):
        """
        Desenha um campo do de-para. Quando o valor costuma se repetir, mostra
        uma lista com os valores já usados + "➕ novo valor" — assim um erro de
        digitação não cria uma carteira/responsável inexistente.
        """
        chave = f"{prefixo}_{spec['coluna']}"
        if not spec.get("sugerir") or not sugestoes:
            return st.text_input(spec["titulo"], value=atual or "", key=chave)

        opcoes = ["(vazio)"] + sugestoes + ["➕ novo valor..."]
        indice = opcoes.index(atual) if atual in sugestoes else 0
        escolha = st.selectbox(spec["titulo"], opcoes, index=indice, key=chave)
        if escolha == "➕ novo valor...":
            return st.text_input(f"Novo valor para {spec['titulo']}",
                                 key=f"{chave}_novo").strip()
        return "" if escolha == "(vazio)" else escolha

    aba_consulta, aba_novo, aba_editar, aba_importar, aba_log = st.tabs(
        ["🔍 Consultar", "➕ Adicionar", "✏️ Editar / Excluir",
         "📥 Importar planilha", "🕑 Histórico"]
    )

    # ------------------------------------------------------------------
    with aba_consulta:
        if df_dp.empty:
            st.info("Nenhum de-para cadastrado. Use a aba **Importar planilha** "
                    "para carregar a BASE_BPS de uma vez.")
        else:
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                busca = st.text_input(
                    "Buscar", placeholder="cliente, CNPJ, nome, contrato, responsável...",
                    key="dp_busca")
            with c2:
                carteiras = ["(todas)"] + valores_sugeridos(df_dp, "carteira")
                f_carteira = st.selectbox("CARTEIRA", carteiras, key="dp_f_carteira")
            with c3:
                tipos = ["(todos)"] + valores_sugeridos(df_dp, "tipo_fatura")
                f_tipo = st.selectbox("TIPO DE FATURA", tipos, key="dp_f_tipo")

            filtrado = df_dp
            if busca.strip():
                alvo = normalizar_texto(busca)
                colunas_busca = CHAVE_DEPARA + [c["coluna"] for c in CAMPOS_DEPARA]
                mascara = filtrado[colunas_busca].apply(
                    lambda linha: alvo in normalizar_texto(" ".join(
                        "" if v is None else str(v) for v in linha)), axis=1)
                filtrado = filtrado[mascara]
            if f_carteira != "(todas)":
                filtrado = filtrado[filtrado["carteira"] == f_carteira]
            if f_tipo != "(todos)":
                filtrado = filtrado[filtrado["tipo_fatura"] == f_tipo]

            k1, k2, k3 = st.columns(3)
            with k1:
                kpi("Cadastrados", f"{len(df_dp):,}".replace(",", "."))
            with k2:
                kpi("Encontrados", f"{len(filtrado):,}".replace(",", "."))
            with k3:
                sem_carteira = int(filtrado["carteira"].isna().sum()) if len(filtrado) else 0
                kpi("Sem carteira", sem_carteira)

            visiveis = (CHAVE_DEPARA + [c["coluna"] for c in CAMPOS_DEPARA]
                        + ["criado_por_nome", "criado_em", "alterado_por_nome", "alterado_em"])
            visiveis = [c for c in visiveis if c in filtrado.columns]
            st.dataframe(filtrado[visiveis], hide_index=True, width="stretch", height=420)
            st.download_button(
                "⬇️ Baixar resultado em Excel",
                data=df_para_xlsx(filtrado[visiveis], "DeParaBPS"),
                file_name=f"DePara_BPS_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    # ------------------------------------------------------------------
    with aba_novo:
        st.markdown("**Chave** — a trinca que identifica o cliente")
        c1, c2, c3 = st.columns(3)
        novo = {}
        for coluna, spec in zip([c1, c2, c3], CAMPOS_CHAVE_DEPARA):
            with coluna:
                novo[spec["coluna"]] = st.text_input(
                    spec["titulo"], help=spec["ajuda"], key=f"novo_{spec['coluna']}").strip()

        st.markdown("**De-para**")
        colunas = st.columns(3)
        for i, spec in enumerate(CAMPOS_DEPARA):
            with colunas[i % 3]:
                novo[spec["coluna"]] = campo_de_valor(
                    spec, None, valores_sugeridos(df_dp, spec["coluna"]), "novo")

        if st.button("➕ Cadastrar", key="dp_btn_novo"):
            ok, msg = inserir_depara(novo)
            if ok:
                limpar_caches()
                st.success(msg)
            else:
                st.error(msg)

    # ------------------------------------------------------------------
    with aba_editar:
        if df_dp.empty:
            st.info("Nada cadastrado ainda.")
        else:
            filtro = st.text_input(
                "Localizar o registro", placeholder="digite parte do nome, CNPJ ou código",
                key="dp_edit_busca")
            candidatos = df_dp
            if filtro.strip():
                alvo = normalizar_texto(filtro)
                candidatos = df_dp[df_dp["ID"].map(lambda v: alvo in normalizar_texto(v))]

            if candidatos.empty:
                st.warning("Nenhum registro com esse texto.")
            elif len(candidatos) > 200:
                st.info(f"{len(candidatos)} registros encontrados — refine a busca "
                        "para escolher um (mostro no máximo 200 na lista).")
            else:
                rotulos = {r["ID"]: r["id"] for _, r in candidatos.iterrows()}
                escolhido = st.selectbox("Registro:", list(rotulos.keys()), key="dp_edit_sel")
                antes = df_dp[df_dp["id"] == rotulos[escolhido]].iloc[0].to_dict()

                st.markdown("**Chave**")
                c1, c2, c3 = st.columns(3)
                editado = {}
                for coluna, spec in zip([c1, c2, c3], CAMPOS_CHAVE_DEPARA):
                    with coluna:
                        editado[spec["coluna"]] = st.text_input(
                            spec["titulo"], value=antes.get(spec["coluna"]) or "",
                            help=spec["ajuda"],
                            key=f"ed_{spec['coluna']}_{antes['id']}").strip()

                st.markdown("**De-para**")
                colunas = st.columns(3)
                for i, spec in enumerate(CAMPOS_DEPARA):
                    with colunas[i % 3]:
                        editado[spec["coluna"]] = campo_de_valor(
                            spec, antes.get(spec["coluna"]),
                            valores_sugeridos(df_dp, spec["coluna"]), f"ed{antes['id']}")

                b1, b2 = st.columns([1, 1])
                with b1:
                    if st.button("💾 Salvar alterações", key="dp_btn_salvar"):
                        ok, msg = atualizar_depara(antes["id"], editado, antes)
                        if ok:
                            limpar_caches()
                            st.success(msg)
                        else:
                            st.warning(msg)
                with b2:
                    confirma = st.checkbox("Confirmo a exclusão deste registro.",
                                           key="dp_conf_excluir")
                    if st.button("🗑️ Excluir", disabled=not confirma, key="dp_btn_excluir"):
                        ok, msg = excluir_depara(antes["id"], antes)
                        if ok:
                            limpar_caches()
                            st.success(msg)
                            # sem st.rerun() aqui: ele recarrega a tela e apaga a mensagem de sucesso

                st.caption(
                    f"Criado por {antes.get('criado_por_nome') or '—'} em "
                    f"{str(antes.get('criado_em'))[:16].replace('T', ' ')}"
                    + (f" · última alteração por {antes.get('alterado_por_nome')} em "
                       f"{str(antes.get('alterado_em'))[:16].replace('T', ' ')}"
                       if antes.get("alterado_em") else "")
                )

    # ------------------------------------------------------------------
    with aba_importar:
        st.markdown(
            "Carrega a **BASE_BPS.xlsx** inteira de uma vez. Quem já existe é "
            "atualizado pela trinca; quem não existe é criado. **Nada é excluído** "
            "por não estar na planilha."
        )
        arquivo_dp = st.file_uploader("Planilha do de-para (.xlsx)",
                                      type=["xlsx", "xlsm"], key="dp_upload")
        if arquivo_dp is not None:
            df_novo, erro = ler_planilha_depara(arquivo_dp.getvalue())
            if erro:
                st.error(erro)
            else:
                repetidos = int(df_novo.duplicated(subset=CHAVE_DEPARA).sum())
                c1, c2, c3 = st.columns(3)
                with c1:
                    kpi("Linhas na planilha", f"{len(df_novo):,}".replace(",", "."))
                with c2:
                    kpi("Trincas repetidas", repetidos)
                with c3:
                    sem_carteira = int(df_novo["carteira"].isna().sum())
                    kpi("Sem CARTEIRA", sem_carteira)

                if repetidos:
                    st.warning(
                        f"{repetidos} linha(s) repetem a trinca — vale só a última "
                        "ocorrência de cada."
                    )
                if sem_carteira:
                    st.info(
                        f"{sem_carteira} linha(s) vêm sem CARTEIRA e demais campos. "
                        "Elas entram assim mesmo — dá para completar depois na aba Editar."
                    )

                st.dataframe(df_novo.head(30), hide_index=True, width="stretch", height=300)
                if st.checkbox("Confirmo a importação.", key="dp_conf_import"):
                    if st.button("📥 Importar", key="dp_btn_import"):
                        try:
                            gravados, descartados = importar_depara(df_novo)
                            limpar_caches()
                            st.success(
                                f"🎉 {gravados} registro(s) importados"
                                + (f" ({descartados} duplicado(s) descartado(s))"
                                   if descartados else "") + "."
                            )
                        except Exception as e:
                            st.error(f"Erro ao importar: {e}")

    # ------------------------------------------------------------------
    with aba_log:
        df_log = carregar_log(['depara'])
        if df_log.empty:
            st.info("Nenhuma alteração registrada ainda.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                kpi("Eventos", len(df_log))
            with c2:
                kpi("Pessoas", df_log["por_email"].nunique())
            acoes = ["(todas)"] + sorted(df_log["acao"].dropna().unique())
            f_acao = st.selectbox("Ação", acoes, key="dp_f_acao")
            visivel = df_log if f_acao == "(todas)" else df_log[df_log["acao"] == f_acao]
            colunas = [c for c in ["em", "acao", "chave", "por_nome", "por_email",
                                   "antes", "depois"] if c in visivel.columns]
            st.dataframe(visivel[colunas], hide_index=True, width="stretch", height=420)
            st.caption("As colunas *antes* e *depois* mostram só os campos que mudaram.")

# ================================================
# 14) PÁGINA — CATEGORIAS E STATUS (CRUD)
# ================================================
elif menu == opcoes_full["Dominios"]:
    st.title("🏷️ Categorias e Status")
    st.caption(
        "O vocabulário aceito na planilha. Um item do SAP só sobe se a sua "
        "**CATEGORIA** e o seu **STATUS** estiverem cadastrados aqui — o arquivo "
        "pode vir sem acento ou com outra caixa, que o app normaliza para a "
        "escrita oficial. Toda alteração fica no histórico."
    )

    df_itens_uso = carregar_consolidado()

    def aba_cadastro(tipo):
        """Uma aba completa (listar + adicionar + editar/excluir) de um tipo."""
        info = TIPOS_DOMINIO[tipo]
        df = carregar_dominios(tipo)
        # Quantos itens já gravados usam cada valor — vira aviso na exclusão.
        if not df_itens_uso.empty and tipo in df_itens_uso.columns:
            uso = df_itens_uso[tipo].value_counts().to_dict()
        else:
            uso = {}

        c1, c2 = st.columns(2)
        with c1:
            kpi(f"{info['plural']} no cadastro", len(df))
        with c2:
            kpi("Sem definição", int(df["definicao"].isna().sum()) if not df.empty else 0)

        if df.empty:
            st.info(
                f"Nenhum item cadastrado em **{info['plural']}**. Enquanto estiver "
                "vazio, **nenhum item sobe** — o app vai recusar toda linha."
            )
        else:
            visiveis = [c for c in ["nome", "definicao", "criado_por_nome",
                                    "criado_em", "alterado_por_nome", "alterado_em"]
                        if c in df.columns]
            tabela = df[visiveis].copy()
            tabela.insert(2, "itens usando", tabela["nome"].map(lambda n: uso.get(n, 0)))
            st.dataframe(tabela, hide_index=True, width="stretch", height=260)

        st.divider()
        st.markdown(f"**➕ Nova {info['titulo'].lower()}**")
        n1, n2, n3 = st.columns([2, 3, 1])
        with n1:
            nome_novo = st.text_input("Nome", key=f"dom_novo_nome_{tipo}")
        with n2:
            def_nova = st.text_input("Definição", key=f"dom_nova_def_{tipo}",
                                     help="Para que serve — aparece só aqui, como referência.")
        with n3:
            st.write("")
            st.write("")
            if st.button("Cadastrar", key=f"dom_btn_novo_{tipo}"):
                ok, msg = inserir_dominio(tipo, nome_novo, def_nova)
                limpar_caches()
                (st.success if ok else st.error)(msg)

        if df.empty:
            return

        st.divider()
        st.markdown(f"**✏️ Editar ou excluir**")
        rotulos = {r["nome"]: r["id"] for _, r in df.iterrows()}
        # A lista SELECIONA o registro; o campo "Nome" abaixo é o valor em si.
        # Os dois mostram o mesmo texto, então o rótulo precisa deixar claro
        # qual deles altera alguma coisa.
        escolhido = st.selectbox(
            f"Qual {info['titulo'].lower()} você quer editar?",
            list(rotulos.keys()), key=f"dom_sel_{tipo}")
        antes = df[df["id"] == rotulos[escolhido]].iloc[0].to_dict()
        em_uso = uso.get(antes["nome"], 0)

        # O NOME não é editável: é ele que fica gravado em cada item e entra na
        # chave. Se pudesse ser reescrito, os itens antigos apontariam para uma
        # palavra que não existe mais. Para corrigir, exclua e cadastre de novo.
        st.caption(
            f"Editando **{antes['nome']}** · "
            + (f"{em_uso} item(ns) já gravados usam este valor." if em_uso
               else "nenhum item usa este valor ainda.")
        )
        def_ed = st.text_input(
            "Definição", value=antes.get("definicao") or "",
            help="O nome não muda depois de cadastrado — para corrigi-lo, "
                 "exclua este registro e cadastre com a grafia certa.",
            key=f"dom_ed_def_{tipo}_{antes['id']}")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("💾 Salvar definição", key=f"dom_btn_salvar_{tipo}"):
                ok, msg = atualizar_dominio(antes["id"], tipo, def_ed, antes)
                limpar_caches()
                (st.success if ok else st.warning)(msg)
        with b2:
            if em_uso:
                st.caption(f"⚠️ {em_uso} item(ns) já gravados usam este valor.")
            confirma = st.checkbox("Confirmo a exclusão.", key=f"dom_conf_exc_{tipo}")
            if st.button("🗑️ Excluir", disabled=not confirma, key=f"dom_btn_exc_{tipo}"):
                ok, msg = excluir_dominio(antes["id"], tipo, antes, em_uso)
                limpar_caches()
                st.success(msg)
                # sem st.rerun() aqui: ele recarrega a tela e apaga a mensagem de sucesso

    abas = st.tabs([f"{TIPOS_DOMINIO['categoria']['icone']} Categorias",
                    f"{TIPOS_DOMINIO['status']['icone']} Status",
                    "🕑 Histórico"])
    with abas[0]:
        aba_cadastro("categoria")
    with abas[1]:
        aba_cadastro("status")
    with abas[2]:
        df_log = carregar_log(["categoria", "status"])
        if df_log.empty:
            st.info("Nenhuma alteração registrada ainda.")
        else:
            colunas = [c for c in ["em", "entidade", "acao", "chave", "por_nome",
                                   "antes", "depois"] if c in df_log.columns]
            st.dataframe(df_log[colunas], hide_index=True, width="stretch", height=420)
            st.caption(
                "Mesmo histórico do De-Para BPS — a coluna *entidade* separa de onde "
                "veio cada evento."
            )

# ================================================
# 15) PÁGINA — VALOR CORRETO DO CTE
# ================================================
elif menu == opcoes_full["ValoresCTE"]:
    st.title("💲 Valor Correto do CT-e")
    st.caption(
        "Onde o validador informa qual é o valor correto de cada CT-e. A chave é "
        "o **ID CTE** — reenviar o mesmo ID atualiza o valor, e a tela mostra "
        "antes quais valores mudam e de quanto para quanto."
    )

    df_vcte = carregar_valores_cte()

    aba_envio, aba_consulta, aba_ajuste, aba_log = st.tabs(
        ["📥 Importar planilha", "🔍 Consultar", "✏️ Ajustar um CT-e", "🕑 Histórico"])

    # ------------------------------------------------------------------
    with aba_envio:
        st.markdown(
            "Da planilha são lidas **4 colunas**: `ID CTE`, `Data do documento`, "
            "`Montante (ME)` e `CONFIRMAR VALOR VALIDADOR`. As demais são de "
            "conferência e ficam de fora."
        )
        arquivo_v = st.file_uploader("Planilha de valores (.xlsx)",
                                     type=["xlsx", "xlsm"], key="vcte_upload")
        if arquivo_v is not None:
            (df_novo, df_retidas, avisos_v, erro_v,
             textos_ruins) = ler_planilha_valores_cte(arquivo_v.getvalue())

            if erro_v:
                st.error(erro_v)
            elif df_novo is None:
                st.error("A planilha tem valores inválidos e **não foi gravada**.")
                st.dataframe(df_retidas, hide_index=True, width="stretch", height=300)
            else:
                df_alterados, novos = comparar_valores_cte(df_novo)

                pendentes = int((df_novo["situacao"] != SITUACAO_CTE_CONFIRMADO).sum())                     if not df_novo.empty else 0
                k1, k2, k3, k4, k5 = st.columns(5)
                with k1:
                    kpi("Linhas válidas", f"{len(df_novo):,}".replace(",", "."))
                with k2:
                    kpi("Com valor", f"{len(df_novo) - pendentes:,}".replace(",", "."))
                with k3:
                    kpi("Falta verificar", f"{pendentes:,}".replace(",", "."))
                with k4:
                    kpi("Mudanças", f"{len(df_alterados):,}".replace(",", "."))
                with k5:
                    kpi("Retidas", f"{len(df_retidas):,}".replace(",", "."))

                for aviso in avisos_v:
                    st.info(aviso)

                # ---- Texto escrito errado na coluna do valor ----
                if textos_ruins:
                    itens = "\n".join(
                        f"- **{t}** — {n} linha{'s' if n > 1 else ''}"
                        for t, n in sorted(textos_ruins.items(), key=lambda x: -x[1]))
                    st.error(
                        "🚫 **Texto não reconhecido na coluna "
                        "`CONFIRMAR VALOR VALIDADOR`.** Essas linhas não sobem — "
                        "corrija a escrita na planilha e reenvie.\n\n"
                        + itens
                        + "\n\nNessa coluna vale o **valor numérico** ou "
                        + ("o texto " if len(VALORES_CTE_TEXTO_ACEITO) == 1
                           else "um destes textos: ")
                        + ", ".join(f"**{t}**" for t in VALORES_CTE_TEXTO_ACEITO)
                        + ". A escrita pode variar em acento e maiúscula/minúscula."
                    )

                if not df_retidas.empty:
                    st.warning(
                        f"⚠️ **{len(df_retidas)} linha(s) ficam de fora** — veja a "
                        "coluna *Problema*. Linhas sem valor **não** entram aqui: "
                        "elas sobem marcadas como pendentes."
                    )
                    with st.expander(f"Ver as {len(df_retidas)} linha(s) retida(s)"):
                        st.dataframe(df_retidas, hide_index=True, width="stretch", height=240)
                        st.download_button(
                            "⬇️ Baixar linhas retidas",
                            data=df_para_xlsx(df_retidas, "Retidas"),
                            file_name=f"Retidas_{arquivo_v.name.rsplit('.', 1)[0]}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="vcte_dl_retidas")

                # ---- O aviso que o Ricardo pediu: o que vai ser ATUALIZADO ----
                if not df_alterados.empty:
                    st.warning(
                        f"⚠️ **{len(df_alterados)} CT-e já têm valor gravado e vão ser "
                        "ATUALIZADOS.** Confira a lista antes de confirmar — cada "
                        "alteração fica registrada no histórico com o valor antigo "
                        "e o novo."
                    )
                    with st.expander(f"Ver os {len(df_alterados)} valores que mudam",
                                     expanded=True):
                        st.dataframe(df_alterados, hide_index=True,
                                     width="stretch", height=260)
                        st.download_button(
                            "⬇️ Baixar as alterações",
                            data=df_para_xlsx(df_alterados, "Alteracoes"),
                            file_name=f"Alteracoes_{datetime.now():%Y%m%d_%H%M}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="vcte_dl_alt")
                else:
                    # Sem alterações. Ainda assim o usuário precisa saber o que
                    # vai acontecer — reenviar o mesmo arquivo não pode ficar
                    # sem resposta nenhuma na tela.
                    iguais = len(df_novo) - novos
                    if novos and iguais:
                        st.success(
                            f"✅ {novos} CT-e novos e {iguais} que já estavam "
                            "gravados com o mesmo valor — **nenhum valor muda**.")
                    elif novos:
                        st.success(f"✅ {novos} CT-e novos — nada é sobrescrito.")
                    else:
                        st.success(
                            f"✅ Os {iguais} CT-e deste arquivo já estão gravados com "
                            "exatamente estes valores — **nada muda**. Pode enviar "
                            "de novo sem efeito algum.")

                if pendentes:
                    resumo = df_novo[df_novo["situacao"] != SITUACAO_CTE_CONFIRMADO]
                    por_situacao = resumo["situacao"].value_counts().to_dict()
                    st.info(
                        f"ℹ️ **{pendentes} CT-e sobem sem valor**, marcados como "
                        + ", ".join(f"**{k}** ({v})" for k, v in por_situacao.items())
                        + ". Ficam na base para você medir quanto falta verificar — "
                        "o `valor_correto` fica vazio, nunca zero."
                    )

                if df_novo.empty:
                    st.error("Nenhuma linha para gravar.")
                else:
                    st.dataframe(df_novo.head(50), hide_index=True,
                                 width="stretch", height=280)
                    if len(df_novo) > 50:
                        st.caption(f"Exibindo 50 de {len(df_novo)} linhas.")
                    rotulo = ("Confirmo o envio"
                              + (f" — ciente de que {len(df_alterados)} valor(es) serão "
                                 "sobrescritos." if not df_alterados.empty else "."))
                    if st.checkbox(rotulo, key="vcte_conf"):
                        if st.button("🚀 Gravar valores", key="vcte_btn"):
                            try:
                                n = gravar_valores_cte(df_novo, df_alterados, arquivo_v.name)
                                limpar_caches()
                                st.success(
                                    f"🎉 {n} CT-e gravados"
                                    + (f", {len(df_alterados)} com valor atualizado"
                                       if not df_alterados.empty else "") + ".")
                                st.balloons()
                            except Exception as e:
                                st.error(f"Erro ao gravar: {e}")

    # ------------------------------------------------------------------
    with aba_consulta:
        if df_vcte.empty:
            st.info("Nenhum valor cadastrado ainda.")
        else:
            c1, c2 = st.columns([3, 1])
            with c1:
                busca_v = st.text_input("Buscar por ID CTE", key="vcte_busca",
                                        placeholder="ex.: 328140-A9-079")
            with c2:
                situacoes = ["(todas)"] + sorted(
                    df_vcte["situacao"].dropna().unique().tolist())                     if "situacao" in df_vcte.columns else ["(todas)"]
                f_situacao = st.selectbox("Situação", situacoes, key="vcte_f_sit")
            filtrado = df_vcte
            if f_situacao != "(todas)":
                filtrado = filtrado[filtrado["situacao"] == f_situacao]
            if busca_v.strip():
                alvo = normalizar_texto(busca_v)
                filtrado = filtrado[filtrado["id_cte"].map(
                    lambda v: alvo in normalizar_texto(v))]

            # Quantos tiveram o valor efetivamente corrigido
            if {"montante_original", "valor_correto"} <= set(filtrado.columns):
                difere = filtrado.apply(
                    lambda r: (r["montante_original"] is not None
                               and r["valor_correto"] is not None
                               and round(float(r["montante_original"]), 2)
                               != round(float(r["valor_correto"]), 2)), axis=1)
                qtd_difere = int(difere.sum()) if len(filtrado) else 0
            else:
                qtd_difere = 0

            falta = int((df_vcte["situacao"] != SITUACAO_CTE_CONFIRMADO).sum())                 if "situacao" in df_vcte.columns else 0
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                kpi("CT-e cadastrados", f"{len(df_vcte):,}".replace(",", "."))
            with k2:
                kpi("Falta verificar", f"{falta:,}".replace(",", "."))
            with k3:
                kpi("Encontrados", f"{len(filtrado):,}".replace(",", "."))
            with k4:
                kpi("Valor difere do original", f"{qtd_difere:,}".replace(",", "."))

            if falta and "situacao" in df_vcte.columns:
                detalhe = (df_vcte[df_vcte["situacao"] != SITUACAO_CTE_CONFIRMADO]
                           ["situacao"].value_counts().to_dict())
                st.caption("Falta verificar: "
                           + " · ".join(f"**{k}**: {v}" for k, v in detalhe.items()))

            visiveis = [c for c in ["id_cte", "data_documento", "montante_original",
                                    "valor_correto", "situacao",
                                    "criado_por_nome", "criado_em",
                                    "alterado_por_nome", "alterado_em"]
                        if c in filtrado.columns]
            st.dataframe(filtrado[visiveis], hide_index=True, width="stretch", height=420)
            st.download_button(
                "⬇️ Baixar em Excel",
                data=df_para_xlsx(filtrado[visiveis], "ValoresCTE"),
                file_name=f"Valores_CTE_{datetime.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="vcte_dl")

    # ------------------------------------------------------------------
    with aba_ajuste:
        if df_vcte.empty:
            st.info("Importe a planilha primeiro.")
        else:
            st.caption("Para corrigir um CT-e sem montar uma planilha de uma linha só.")
            filtro_a = st.text_input("Localizar o CT-e", key="vcte_aj_busca",
                                     placeholder="digite parte do ID CTE")
            candidatos = df_vcte
            if filtro_a.strip():
                alvo = normalizar_texto(filtro_a)
                candidatos = df_vcte[df_vcte["id_cte"].map(
                    lambda v: alvo in normalizar_texto(v))]

            if candidatos.empty:
                st.warning("Nenhum CT-e com esse texto.")
            elif len(candidatos) > 200:
                st.info(f"{len(candidatos)} CT-e encontrados — refine a busca.")
            else:
                escolhido = st.selectbox("CT-e:", candidatos["id_cte"].tolist(),
                                         key="vcte_aj_sel")
                antes = df_vcte[df_vcte["id_cte"] == escolhido].iloc[0].to_dict()
                atual = antes.get("valor_correto")
                def _reais(v):
                    return "—" if v is None else f"R$ {float(v):,.2f}"
                st.caption(
                    f"Montante original: {_reais(antes.get('montante_original'))}"
                    f" · valor correto hoje: {_reais(atual)}"
                )
                novo_valor = st.number_input(
                    "Novo valor correto", min_value=0.0, step=0.01, format="%.2f",
                    value=float(atual) if atual is not None else 0.0,
                    key=f"vcte_aj_val_{escolhido}")
                if st.button("💾 Salvar valor", key="vcte_aj_btn"):
                    ok, msg = atualizar_valor_cte(escolhido, novo_valor, antes)
                    limpar_caches()
                    (st.success if ok else st.warning)(msg)

    # ------------------------------------------------------------------
    with aba_log:
        df_log_v = carregar_log(["valor_cte"])
        if df_log_v.empty:
            st.info("Nenhuma alteração registrada ainda.")
        else:
            alteracoes = df_log_v[df_log_v["acao"] == "valor alterado"]
            k1, k2 = st.columns(2)
            with k1:
                kpi("Eventos", len(df_log_v))
            with k2:
                kpi("Valores alterados", len(alteracoes))
            colunas = [c for c in ["em", "acao", "chave", "antes", "depois", "por_nome"]
                       if c in df_log_v.columns]
            st.dataframe(df_log_v[colunas], hide_index=True, width="stretch", height=420)
            st.caption("*chave* é o ID CTE (ou o nome do arquivo, nos eventos de carga).")
