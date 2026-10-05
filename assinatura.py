"""Quadro de assinatura em tela cheia, para o celular (presença por QR Code).

O botão "Toque para assinar" abre um quadro que ocupa a tela inteira. Virando
o celular de lado, a pessoa ganha a largura toda — como na maquininha de
cartão. Ao confirmar, a assinatura volta para o Python como PNG.

Feito com st.components.v2 (Streamlit >= 1.53): HTML/CSS/JS nossos, sem
componente de terceiros. O quadro em tela cheia é criado direto no <body> da
página (e não dentro do componente) para cobrir a tela toda; por isso o CSS
dele vai numa <style> própria no <head>.
"""

import base64

import streamlit as st

CSS = """
.dv-ass-btn {
  width: 100%; padding: 14px 16px; border-radius: 10px; cursor: pointer;
  border: 1.5px dashed #E4610A; background: #FFF6EF; color: #B84E08;
  font: 600 16px/1.2 "Poppins", sans-serif;
}
.dv-ass-btn.feita { border-style: solid; background: #F2FAF4; border-color: #2E7D46; color: #1F5F33; }
"""

# Tudo do quadro em tela cheia vive aqui (anexado ao <body>, fora do componente)
CSS_TELA_CHEIA = """
#dv-ass-tela { position: fixed; inset: 0; z-index: 2147483000; background: #FFFFFF;
  display: flex; flex-direction: column; touch-action: none; overscroll-behavior: contain;
  font-family: "Poppins", sans-serif; }
#dv-ass-tela .topo { padding: 10px 16px 4px; color: #2B2420; }
#dv-ass-tela .topo b { font-size: 17px; }
#dv-ass-tela .dica { font-size: 13px; color: #B84E08; margin-top: 2px; }
#dv-ass-tela .area { position: relative; flex: 1; margin: 6px 12px; border: 1.5px solid #E8B894;
  border-radius: 12px; overflow: hidden; background: #FFFFFF; }
#dv-ass-tela .linha { position: absolute; left: 6%; right: 6%; bottom: 24%; border-bottom: 1.5px solid #D9CFC7; }
#dv-ass-tela .xis { position: absolute; left: 6%; bottom: calc(24% + 6px); color: #B9AEA6; font-size: 22px; }
#dv-ass-tela canvas { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; }
#dv-ass-tela .botoes { display: flex; gap: 10px; padding: 8px 12px 14px; }
#dv-ass-tela button { flex: 1; padding: 13px 8px; border-radius: 10px; font: 600 15px "Poppins", sans-serif;
  border: 1.5px solid #E8B894; background: #FFFFFF; color: #2B2420; }
#dv-ass-tela button.ok { background: #E4610A; border-color: #E4610A; color: #FFFFFF; }
#dv-ass-tela .aviso { color: #8C1D18; font-size: 13px; min-height: 16px; padding: 0 16px; }
"""

JS = """
export default function (component) {
  const { parentElement, setStateValue, data } = component;
  const feita = !!(data && data.feita);

  // botão que fica na página
  parentElement.querySelectorAll('.dv-ass-btn').forEach((b) => b.remove());
  const botao = document.createElement('button');
  botao.type = 'button';
  botao.className = 'dv-ass-btn' + (feita ? ' feita' : '');
  botao.textContent = feita ? '✅ Assinado — toque para assinar de novo' : '✍️ Toque para assinar';
  parentElement.appendChild(botao);

  if (!document.getElementById('dv-ass-estilo')) {
    const estilo = document.createElement('style');
    estilo.id = 'dv-ass-estilo';
    estilo.textContent = data.css;
    document.head.appendChild(estilo);
  }

  botao.onclick = () => abrir();

  function abrir() {
    fechar();
    const tela = document.createElement('div');
    tela.id = 'dv-ass-tela';
    tela.innerHTML =
      '<div class="topo"><b>Assine com o dedo</b>' +
      '<div class="dica">Dica: vire o celular de lado para ter mais espaço.</div></div>' +
      '<div class="area"><div class="linha"></div><div class="xis">✕</div><canvas></canvas></div>' +
      '<div class="aviso"></div>' +
      '<div class="botoes"><button class="limpar">Limpar</button>' +
      '<button class="cancelar">Cancelar</button><button class="ok">Confirmar</button></div>';
    document.body.appendChild(tela);
    const corpoOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const area = tela.querySelector('.area');
    const canvas = tela.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    const dica = tela.querySelector('.dica');
    const aviso = tela.querySelector('.aviso');
    let tracos = [];   // pontos de 0 a 1: redesenha igual quando o celular gira
    let atual = null;

    function ajustar() {
      const r = area.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(r.width * dpr);
      canvas.height = Math.round(r.height * dpr);
      dica.style.display = r.height > r.width ? 'block' : 'none';
      redesenhar();
    }
    function redesenhar() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.strokeStyle = '#1F2A44';
      ctx.lineWidth = 2.6 * (window.devicePixelRatio || 1);
      for (const t of tracos) {
        ctx.beginPath();
        t.forEach((p, i) => {
          const x = p[0] * canvas.width, y = p[1] * canvas.height;
          if (i === 0) { ctx.moveTo(x, y); ctx.lineTo(x + 0.1, y + 0.1); } else { ctx.lineTo(x, y); }
        });
        ctx.stroke();
      }
    }
    function ponto(e) {
      const r = canvas.getBoundingClientRect();
      return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
    }
    canvas.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
      atual = [ponto(e)]; tracos.push(atual); aviso.textContent = ''; redesenhar();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!atual) return;
      e.preventDefault();
      const eventos = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
      (eventos.length ? eventos : [e]).forEach((ev) => atual.push(ponto(ev)));
      redesenhar();
    });
    const soltar = () => { atual = null; };
    canvas.addEventListener('pointerup', soltar);
    canvas.addEventListener('pointercancel', soltar);
    canvas.addEventListener('pointerleave', soltar);

    tela.querySelector('.limpar').onclick = () => { tracos = []; redesenhar(); };
    tela.querySelector('.cancelar').onclick = () => fechar();
    tela.querySelector('.ok').onclick = () => {
      if (!tracos.length) { aviso.textContent = 'Assine no quadro antes de confirmar.'; return; }
      setStateValue('assinatura', exportar());
      fechar();
    };

    // PNG só com a área assinada (fundo branco, margem, até 900 x 360)
    function exportar() {
      const pts = tracos.flat();
      const W = canvas.width, H = canvas.height;
      let x0 = Math.min(...pts.map((p) => p[0])) * W, x1 = Math.max(...pts.map((p) => p[0])) * W;
      let y0 = Math.min(...pts.map((p) => p[1])) * H, y1 = Math.max(...pts.map((p) => p[1])) * H;
      const m = 12 * (window.devicePixelRatio || 1);
      x0 = Math.max(0, x0 - m); y0 = Math.max(0, y0 - m); x1 = Math.min(W, x1 + m); y1 = Math.min(H, y1 + m);
      const w = Math.max(1, x1 - x0), h = Math.max(1, y1 - y0);
      const escala = Math.min(1, 900 / w, 360 / h);
      const saida = document.createElement('canvas');
      saida.width = Math.round(w * escala); saida.height = Math.round(h * escala);
      const c = saida.getContext('2d');
      c.fillStyle = '#FFFFFF'; c.fillRect(0, 0, saida.width, saida.height);
      c.drawImage(canvas, x0, y0, w, h, 0, 0, saida.width, saida.height);
      return saida.toDataURL('image/png');
    }

    // reajusta quando a área muda de tamanho (celular girou, barra do navegador sumiu)
    const observador = window.ResizeObserver ? new ResizeObserver(() => ajustar()) : null;
    if (observador) observador.observe(area);
    const aoGirar = () => setTimeout(ajustar, 150);
    window.addEventListener('resize', aoGirar);
    tela._limpar = () => {
      if (observador) observador.disconnect();
      window.removeEventListener('resize', aoGirar);
      document.body.style.overflow = corpoOverflow;
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    };
    // Android: tela cheia de verdade (some a barra do navegador). iPhone ignora — o quadro já cobre a tela.
    if (tela.requestFullscreen) tela.requestFullscreen().catch(() => {});
    ajustar();
  }

  function fechar() {
    const tela = document.getElementById('dv-ass-tela');
    if (tela) { tela._limpar && tela._limpar(); tela.remove(); }
  }

  return fechar;  // ao sair da página, não deixa o quadro aberto
}
"""

def _registrar():
    return st.components.v2.component("dv_assinatura", css=CSS, js=JS)


_QUADRO = _registrar()


def campo_assinatura(key: str):
    """Botão que abre o quadro em tela cheia. Devolve o PNG (bytes) da assinatura, ou None."""
    global _QUADRO
    estado = f"{key}_png"
    argumentos = dict(key=key, data={"feita": bool(st.session_state.get(estado)), "css": CSS_TELA_CHEIA},
                      on_assinatura_change=lambda: None)
    try:
        resultado = _QUADRO(**argumentos)
    except Exception as erro:
        if "not registered" not in str(erro):
            raise
        _QUADRO = _registrar()  # o Streamlit reiniciou e esqueceu o componente: registra de novo
        resultado = _QUADRO(**argumentos)
    url = getattr(resultado, "assinatura", None)
    prefixo = "data:image/png;base64,"
    png = base64.b64decode(url[len(prefixo):]) if isinstance(url, str) and url.startswith(prefixo) else None
    if png and png != st.session_state.get(estado):
        st.session_state[estado] = png
        st.rerun()  # redesenha o botão como "✅ Assinado"
    return st.session_state.get(estado)
