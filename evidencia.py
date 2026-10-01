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
import uuid
from pathlib import Path

import streamlit as st

import banco  # noqa: F401 — clona o Modulos e o coloca no sys.path
import Modulos.Minio.examples.MinIO as meu_minio
from comum import texto

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


def mostrar(link) -> None:
    """Botão para abrir a evidência já gravada (MinIO ou link antigo do SharePoint)."""
    link = texto(link)
    if not link:
        st.caption("Nenhuma evidência anexada.")
        return
    if link.startswith("http"):
        st.link_button("📎 Abrir evidência", link)
        return
    try:
        # o bucket não é público: o link é gerado na hora e vale 1 hora
        url = _manager().generate_presigned_download_url(BUCKET, link, expires_hours=1)
    except Exception as erro:
        st.caption(f"Evidência `{link}` — não foi possível gerar o link ({erro}).")
        return
    st.link_button("📎 Abrir evidência", url)
