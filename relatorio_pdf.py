"""Lista de presença em PDF (no formato da RQ 10), com as assinaturas.

Uma lista = um treinamento, numa data, numa filial. Cada participante sai
numa linha com nome, CPF, função, setor, avaliação e a assinatura feita no
celular (presença por QR Code). Listas lançadas à mão ou por Excel saem com
a coluna de assinatura em branco: a assinatura delas é a RQ 10 de papel.

Usa fpdf2 com as fontes padrão do PDF (Helvetica): cobrem o português
(latin-1), mas não emoji — por isso os textos passam por _t().
"""

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from fpdf import FPDF
from PIL import Image

from comum import fmt_cpf, fmt_data, texto
from estilo import URL_LOGO_COLORIDO

LARANJA = (228, 97, 10)
CINZA_LINHA = (217, 207, 199)
# (título, largura em mm) — A4 deitado: 277 mm úteis
COLUNAS = [("#", 8), ("NOME", 66), ("CPF", 30), ("FUNÇÃO", 42), ("SETOR", 34),
           ("AVALIAÇÃO", 25), ("ASSINATURA", 72)]
ALTURA_LINHA = 12


def _t(valor) -> str:
    """Texto que a fonte padrão do PDF consegue escrever (sem emoji)."""
    return (texto(valor) or "").encode("latin-1", "replace").decode("latin-1")


class _Lista(FPDF):
    def __init__(self, cabecalho: dict, gerado_por: str):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.cabecalho = cabecalho
        agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
        self.rodape = _t(f"RQ 10 - Lista de Presença - gerada pelo app Segurança do Trabalho em {agora} "
                         f"por {gerado_por}")
        self.set_auto_page_break(False)
        self.set_margins(10, 10, 10)
        self.com_tabela = True  # False na página que só leva o rodapé (conteúdo + instrutor)

    def header(self):
        try:
            self.image(URL_LOGO_COLORIDO, x=10, y=8, h=11)
        except Exception:
            pass  # sem logo, o PDF sai do mesmo jeito
        self.set_xy(10, 9)
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(*LARANJA)
        self.cell(0, 9, _t("Lista de Presença"), align="C")
        self.set_text_color(43, 36, 32)

        c = self.cabecalho
        self.set_xy(10, 22)
        campos = [("Treinamento", c["treinamento"], 120), ("Data", c["data"], 38),
                  ("Filial", c["filial"], 60), ("Validade", c["validade"], 59)]
        for rotulo, valor, largura in campos:
            self.set_font("Helvetica", "B", 9)
            self.cell(self.get_string_width(_t(rotulo + ": ")) + 1, 6, _t(rotulo + ": "))
            self.set_font("Helvetica", "", 9)
            self.cell(largura - self.get_string_width(_t(rotulo + ": ")) - 1, 6, _t(valor), )
        self.set_xy(10, 28)
        self.set_font("Helvetica", "B", 9)
        self.cell(19, 6, "Instrutor: ")
        self.set_font("Helvetica", "", 9)
        self.cell(120, 6, _t(c["instrutor"]))
        self.cell(0, 6, _t(f"{c['total']} participante{'' if c['total'] == 1 else 's'}"), align="R")

        # cabeçalho da tabela (repete em toda página que tem participantes)
        self.set_xy(10, 36)
        if not self.com_tabela:
            return
        self.set_font("Helvetica", "B", 8.5)
        self.set_fill_color(*LARANJA)
        self.set_text_color(255, 255, 255)
        self.set_draw_color(*LARANJA)
        for titulo, largura in COLUNAS:
            self.cell(largura, 8, _t(titulo), border=1, align="C", fill=True)
        self.ln(8)
        self.set_text_color(43, 36, 32)

    def footer(self):
        self.set_y(-11)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(120, 110, 104)
        self.cell(0, 5, self.rodape)
        self.cell(0, 5, f"Página {self.page_no()}/{{nb}}", align="R")


def lista_presenca(linhas: pd.DataFrame, assinaturas: dict, gerado_por: str,
                   assinatura_instrutor: bytes | None = None) -> bytes:
    """PDF da lista. `assinaturas` = {id do registro: PNG em bytes}."""
    primeira = linhas.iloc[0]
    instrutores = sorted({texto(i) for i in linhas.get("instrutor", []) if texto(i)})
    validades = sorted({fmt_data(v) for v in linhas["data_validade"] if fmt_data(v)})
    cabecalho = {
        "treinamento": primeira["treinamento"],
        "data": fmt_data(primeira["data_treinamento"]),
        "filial": primeira["filial"],
        "validade": ", ".join(validades) or "sem validade",
        "instrutor": ", ".join(instrutores) or "não informado",
        "total": len(linhas),
    }
    pdf = _Lista(cabecalho, gerado_por)
    pdf.add_page()
    pdf.set_draw_color(*CINZA_LINHA)

    for n, (_, p) in enumerate(linhas.iterrows(), start=1):
        if pdf.get_y() + ALTURA_LINHA > pdf.h - 14:
            pdf.add_page()
            pdf.set_draw_color(*CINZA_LINHA)
        y = pdf.get_y()
        valores = [str(n), p["nome"], fmt_cpf(p["cpf"]), p["funcao"], p["setor"], p["avaliacao"]]
        pdf.set_font("Helvetica", "", 8.5)
        for (_, largura), valor in zip(COLUNAS, valores):
            texto_celula = _t(valor)
            while texto_celula and pdf.get_string_width(texto_celula) > largura - 2:
                texto_celula = texto_celula[:-1]  # corta o que não cabe na coluna
            pdf.cell(largura, ALTURA_LINHA, texto_celula, border=1, align="C" if largura < 30 else "L")
        x_ass, largura_ass = pdf.get_x(), COLUNAS[-1][1]
        pdf.cell(largura_ass, ALTURA_LINHA, "", border=1)
        png = assinaturas.get(p["id"])
        if png:
            _assinatura(pdf, png, x_ass, y, largura_ass)
        pdf.set_xy(10, y + ALTURA_LINHA)

    if not assinaturas:
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 5, _t("Lista sem assinaturas digitais: a assinatura desta lista está na RQ 10 de papel."))
        pdf.ln(5)

    conteudo = next((str(c).strip() for c in linhas.get("conteudo_programatico", []) if texto(c)), "")
    _rodape_rq10(pdf, conteudo, cabecalho, assinatura_instrutor)
    return bytes(pdf.output())


def _rodape_rq10(pdf: FPDF, conteudo: str, cabecalho: dict, assinatura_instrutor) -> None:
    """Conteúdo programático + Instrutor / Assinatura / Data — o pé da RQ 10 de papel."""
    largura = sum(l for _, l in COLUNAS)
    linhas_conteudo = [_t(l) for l in conteudo.splitlines() if l.strip()] or ["-"]
    pdf.set_font("Helvetica", "", 9)
    altura_conteudo = max(18, 5 * sum(1 + int(pdf.get_string_width(l) // (largura - 52)) for l in linhas_conteudo) + 4)
    if pdf.get_y() + 4 + altura_conteudo + 14 > pdf.h - 14:
        pdf.com_tabela = False
        pdf.add_page()
    y = pdf.get_y() + 4
    pdf.set_draw_color(*CINZA_LINHA)

    # Conteúdo programático
    pdf.set_xy(10, y)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(48, altura_conteudo, _t("Conteúdo Programático:"), border=1, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.rect(58, y, largura - 48, altura_conteudo)
    pdf.set_xy(60, y + 2)
    pdf.multi_cell(largura - 52, 5, "\n".join(linhas_conteudo))

    # Instrutor | Assinatura | Data
    y += altura_conteudo
    pdf.set_xy(10, y)
    for rotulo, valor, larg_rotulo, larg_valor in (("Instrutor:", cabecalho["instrutor"], 22, 78),
                                                    ("Assinatura:", "", 24, 80),
                                                    ("Data:", cabecalho["data"], 14, 59)):
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(larg_rotulo, 14, _t(rotulo), border=1, align="C")
        pdf.set_font("Helvetica", "", 9)
        x_valor = pdf.get_x()
        pdf.cell(larg_valor, 14, _t(valor), border=1, align="C")
        if rotulo == "Assinatura:" and assinatura_instrutor:
            _imagem_na_caixa(pdf, assinatura_instrutor, x_valor, y, larg_valor, 14)


def _assinatura(pdf: FPDF, png: bytes, x: float, y: float, largura: float) -> None:
    _imagem_na_caixa(pdf, png, x, y, largura, ALTURA_LINHA)


def _imagem_na_caixa(pdf: FPDF, png: bytes, x: float, y: float, largura: float, altura: float) -> None:
    """Assinatura centralizada na célula, sem distorcer."""
    try:
        w, h = Image.open(io.BytesIO(png)).size
        escala = min((largura - 4) / w, (altura - 2) / h)
        iw, ih = w * escala, h * escala
        pdf.image(io.BytesIO(png), x=x + (largura - iw) / 2, y=y + (altura - ih) / 2, w=iw, h=ih)
    except Exception:
        pass  # imagem ilegível: a célula fica em branco
