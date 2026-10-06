"""Evidências (RQ 10 assinada, relatório do acidente, fotos) no MinIO.

O arquivo sobe com nome único numa pasta por tela, dentro do bucket
seguranca-trabalho, e o caminho vai para a coluna link_evidencia. Uma lista
de presença tem N linhas e um arquivo só: todas as linhas guardam o mesmo
caminho.

Os arquivos não são apagados ao excluir ou substituir: o da lista de presença
é compartilhado entre linhas, e evidência guardada é rastreabilidade.

Credenciais (secrets): MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
MINIO_SECURE — o módulo do Modulos lê de st.secrets e conecta no import.
"""

import io
import re
import unicodedata
import uuid
from pathlib import Path

import streamlit as st

import banco  # noqa: F401 — clona o Modulos e o coloca no sys.path
import Modulos.Minio.examples.MinIO as meu_minio
from comum import para_data, texto

BUCKET = "seguranca-trabalho"
TIPOS = ["pdf", "jpg", "jpeg", "png"]


def _manager():
    manager = getattr(meu_minio, "manager", None)
    if manager is None:
        raise RuntimeError(
            "MinIO indisponível. Confira MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY "
            "e MINIO_SECURE nos secrets e reinicie o app (a conexão é aberta só na inicialização)."
        )
    return manager


def subir(arquivo, pasta: str) -> str:
    """Envia o arquivo e devolve o caminho dele no bucket (ex.: acidente/3f2a....pdf)."""
    manager = _manager()
    extensao = Path(arquivo.name).suffix.lower() or ".bin"
    caminho = f"{pasta}/{uuid.uuid4().hex}{extensao}"
    conteudo = arquivo.getvalue()
    manager.create_bucket_if_not_exists(BUCKET)
    # put_object com os bytes em memória: o upload() do módulo exige arquivo em disco
    manager.client.put_object(
        BUCKET, caminho, io.BytesIO(conteudo), length=len(conteudo),
        content_type=arquivo.type or "application/octet-stream",
    )
    return caminho


def nome_legivel(*partes) -> str:
    """'José da Silva', 'NR-35 Altura' -> 'JOSE_DA_SILVA-NR_35_ALTURA': sem acento nem símbolo."""
    limpas = []
    for parte in partes:
        s = unicodedata.normalize("NFKD", str(parte or ""))
        s = "".join(c for c in s if not unicodedata.combining(c)).upper()
        limpas.append(re.sub(r"[^A-Z0-9]+", "_", s).strip("_") or "SEM_NOME")
    return "-".join(limpas)


PASTA_ASSINATURAS = "treinamento/assinaturas"
PASTA_ASSINATURAS_INSTRUTOR = "treinamento/assinaturas/instrutores"


def subir_assinatura(png: bytes, nome: str, treinamento: str, data_treinamento,
                     pasta: str = PASTA_ASSINATURAS) -> str:
    """Grava a assinatura como <pasta>/NOME-TREINAMENTO-DD-MM-AAAA.png.

    Participante: treinamento/assinaturas/; instrutor: treinamento/assinaturas/instrutores/.

    Nome legível para achar no MinIO e na extração. Se já existir um arquivo
    com esse nome (mesma pessoa, mesmo treinamento, mesmo dia), acrescenta -2, -3…
    em vez de sobrescrever a assinatura anterior.
    """
    manager = _manager()
    manager.create_bucket_if_not_exists(BUCKET)
    data = para_data(data_treinamento)
    base = f"{pasta}/{nome_legivel(nome, treinamento)}-{data:%d-%m-%Y}"
    caminho, n = f"{base}.png", 1
    while _existe(manager, caminho):
        n += 1
        caminho = f"{base}-{n}.png"
    manager.client.put_object(BUCKET, caminho, io.BytesIO(png), length=len(png), content_type="image/png")
    return caminho


def baixar(caminho: str) -> bytes:
    """Conteúdo de um arquivo do bucket (ex.: a assinatura, para o PDF da lista)."""
    resposta = _manager().client.get_object(BUCKET, caminho)
    try:
        return resposta.read()
    finally:
        resposta.close()
        resposta.release_conn()


def _existe(manager, caminho: str) -> bool:
    try:
        manager.client.stat_object(BUCKET, caminho)
        return True
    except Exception:
        return False


def remover(caminho: str) -> None:
    try:
        _manager().client.remove_object(BUCKET, caminho)
    except Exception:
        pass  # só é usado para desfazer um envio; se falhar, sobra um arquivo solto


def gravar(arquivo, pasta: str, salvar) -> tuple:
    """Sobe o arquivo (se houver) e chama salvar(caminho) — caminho é None sem arquivo novo.

    Se a gravação no banco falhar, apaga o arquivo que acabou de subir, para
    não sobrar anexo sem registro.
    """
    caminho = None
    if arquivo is not None:
        try:
            caminho = subir(arquivo, pasta)
        except Exception as erro:
            return False, f"Não anexou a evidência: {erro}"
    ok, msg = salvar(caminho)
    if not ok and caminho:
        remover(caminho)
    return ok, msg


def campo(rotulo: str, key: str, ajuda: str = None):
    return st.file_uploader(
        rotulo, type=TIPOS, key=key,
        help=ajuda or "PDF ou foto (JPG/PNG). Escaneado fica mais legível que foto.",
    )


def mostrar(link, rotulo: str = "📎 Abrir evidência", vazio: str = "Nenhuma evidência anexada.") -> None:
    """Botão para abrir a evidência já gravada (MinIO ou link antigo do SharePoint)."""
    link = texto(link)
    if not link:
        st.caption(vazio)
        return
    if link.startswith("http"):
        st.link_button(rotulo, link)
        return
    try:
        # o bucket não é público: o link é gerado na hora e vale 1 hora
        url = _manager().generate_presigned_download_url(BUCKET, link, expires_hours=1)
    except Exception as erro:
        st.caption(f"`{link}` — não foi possível gerar o link ({erro}).")
        return
    st.link_button(rotulo, url)
