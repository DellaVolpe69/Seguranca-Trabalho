"""Controle de acesso por filial — quem vê e lança o quê.

  ADMINS (lista abaixo) .......... todas as filiais
  segtrabalho_usuario ............ só as filiais da pessoa (1 linha por e-mail × filial,
                                   carregada de Responsaveis_por_Filial.xlsx)

O recorte é pelo código SAP da filial (cod_filial), não pelo nome: "Cubatão",
"cubatao" e "CUBATAO - SP" são a mesma filial, e o código não muda.

ATENÇÃO — este filtro é da APLICAÇÃO (decisão do projeto). O Supabase não sabe
quem está logado: quem tiver a URL e a chave lê tudo por fora do app.
"""

import pandas as pd
import streamlit as st

import banco

# Veem e lançam para todas as filiais. Incluir aqui o SESMT corporativo.
ADMINS = {
    "anderson.junior@dellavolpe.com.br",
    "pamela.santos@dellavolpe.com.br",
    "thayna.paula@dellavolpe.com.br",
}

# Código SAP → nome da filial (mesmo cadastro do COD_FILIAL.sql do Sustentabilidade)
FILIAIS = {
    "0001": "São Paulo - SP",
    "0002": "Rio de Janeiro - RJ",
    "0019": "Santos - SP",
    "0025": "Jaboatão dos G. - PE",
    "0028": "Cubatão - SP",
    "0041": "Fortaleza - CE",
    "0044": "Viana - ES",
    "0055": "Curitiba - PR",
    "0069": "Pindamonhangaba - SP",
    "0087": "Piracicaba - SP",
    "0108": "Timóteo - MG",
    "0111": "Canoas - RS",
    "0119": "Feira de Santana - BA",
    "0122": "Araquari - SC",
    "0124": "Mauá - SP",
    "0125": "São Luiz - MA",
    "0127": "Parauapebas - PA",
    "0129": "Trindade - PE",
    "0131": "Ananindeua - PA",
    "0133": "Uberlândia - MG",
    "0134": "Açailândia - MA",
    "0138": "Ourilândia do Norte - PA",
    "0141": "Aparecida de Goiania - GO",
    "0142": "Marabá - PA",
    "0144": "Rosário do Catete - SE",
    "0145": "Camaçari - BA",
    "0150": "Corumbá - MS",
    "0152": "Divinópolis - MG",
    "0153": "Bom Jesus do Amparo - MG",
    "0154": "Canaã dos Carajas - PA",
    "0155": "Ribeirão Preto - SP",
    "0156": "Barcarena - PA",
    "0157": "Dourados - MS",
    "0158": "Cachoeiro Itapemirim - ES",
    "0159": "Contagem MG",
    "0160": "Ipatinga MG",
    "0161": "Várzea Grande MT",
    "0163": "Três Lagoas MS",
    "0165": "Maceió AL",
    "0166": "SINOP MT",
    "0167": "Porto Velho",
    "0168": "Manaus",
    "0169": "Primavera do Leste - MT",
}


def carregar_perfil(email: str) -> dict:
    """{'admin', 'codigos'}. Calculado uma vez no login e guardado na sessão."""
    email = email.strip().lower()
    if email in {e.lower() for e in ADMINS}:
        return {"admin": True, "codigos": sorted(FILIAIS)}
    try:
        usuarios = banco.listar(banco.USUARIO)
    except Exception as erro:
        st.error(f"Não foi possível ler {banco.USUARIO}: {erro}")
        return {"admin": False, "codigos": []}
    if usuarios.empty:
        return {"admin": False, "codigos": []}
    minhas = usuarios[usuarios["email"].str.strip().str.lower() == email]
    codigos = sorted({c for c in minhas["cod_filial"].dropna().astype(str).str.strip() if c})
    return {"admin": False, "codigos": codigos}


def perfil() -> dict:
    return st.session_state.get("perfil", {"admin": False, "codigos": []})


def descricao() -> str:
    p = perfil()
    if p["admin"]:
        return "todas as filiais"
    return ", ".join(FILIAIS.get(c, c) for c in p["codigos"]) or "nenhuma filial"


def listar(tabela: str) -> pd.DataFrame:
    """banco.listar() já recortado pelas filiais do usuário logado.

    O recorte é feito aqui, e não dentro do banco.listar(): aquele resultado
    fica em cache para todos os usuários do app.
    """
    df = banco.listar(tabela)
    if perfil()["admin"] or df.empty:
        return df
    if "cod_filial" not in df:
        return df.iloc[0:0]
    return df[df["cod_filial"].isin(perfil()["codigos"])]


def campo_filial(rotulo: str, key: str, cod_atual=None) -> tuple:
    """Lista fixa com as filiais que o usuário pode lançar. Devolve (código, nome)."""
    codigos = perfil()["codigos"]
    if not codigos:
        st.selectbox(rotulo, ["Sem filial liberada para o seu usuário"], key=key, disabled=True)
        return None, None
    opcoes = codigos if len(codigos) == 1 else [None] + codigos
    cod_atual = str(cod_atual).strip() if cod_atual is not None and not pd.isna(cod_atual) else None
    indice = opcoes.index(cod_atual) if cod_atual in opcoes else 0
    escolha = st.selectbox(
        rotulo, opcoes, index=indice, key=key,
        format_func=lambda c: "—" if c is None else f"{FILIAIS.get(c, c)} · {c}",
    )
    return (escolha, FILIAIS.get(escolha)) if escolha else (None, None)


OUTRO_LOCAL = "__outro__"


def campo_filial_ou_local(rotulo: str, key: str, cod_atual=None, nome_atual=None) -> tuple:
    """campo_filial + "OUTRO — digitar", para o que é feito fora da filial (ex.: treinamento no cliente).

    O local digitado vai no nome (`filial`); o código continua sendo o da filial
    responsável — é ele que decide quem vê o registro. Devolve (código, nome).
    """
    codigos = perfil()["codigos"]
    if not codigos:
        st.selectbox(rotulo, ["Sem filial liberada para o seu usuário"], key=key, disabled=True)
        return None, None
    cod_atual = str(cod_atual).strip() if cod_atual is not None and not pd.isna(cod_atual) else None
    nome_atual = str(nome_atual).strip() if nome_atual is not None and not pd.isna(nome_atual) else None
    fora = bool(cod_atual and nome_atual and nome_atual != FILIAIS.get(cod_atual))

    def nome(c):
        if c is None:
            return "—"
        return "OUTRO — digitar (ex.: cliente)" if c == OUTRO_LOCAL else f"{FILIAIS.get(c, c)} · {c}"

    opcoes = ([None] if len(codigos) > 1 else []) + codigos + [OUTRO_LOCAL]
    indice = opcoes.index(OUTRO_LOCAL) if fora else opcoes.index(cod_atual) if cod_atual in opcoes else 0
    escolha = st.selectbox(rotulo, opcoes, index=indice, key=key, format_func=nome)
    if escolha != OUTRO_LOCAL:
        return (escolha, FILIAIS.get(escolha)) if escolha else (None, None)

    local = st.text_input("LOCAL (cliente)", value=nome_atual if fora else "", key=f"{key}_local",
                          placeholder="Ex.: Cliente X — unidade Y")
    if len(codigos) == 1:
        cod = codigos[0]
        st.caption(f"Filial responsável: {FILIAIS.get(cod, cod)}")
    else:
        responsaveis = [None] + codigos
        cod = st.selectbox("FILIAL RESPONSÁVEL", responsaveis, key=f"{key}_resp", format_func=nome,
                           index=responsaveis.index(cod_atual) if cod_atual in responsaveis else 0,
                           help="Filial que fez o treinamento: é ela que vê e acompanha o registro no app.")
    local = local.strip() or None
    return (cod, local) if cod and local else (None, None)
