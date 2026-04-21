import { WIDGET_CONFIG, sessionId, scrollMsgs } from './utils.js';
import { mostrarFormulario } from './form.js';

export function formatMessage(text) {
  text = text.replace(/ - \*\*/g, '\n- **');
  text = text.replace(/ - /g, '\n- ');
  let lines = text.split('\n'), html = '', enLista = false;
  lines.forEach(line => {
    line = line.trim();
    if (!line) return;
    line = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    if (line.startsWith('- ') || line.startsWith('• ')) {
      if (!enLista) { html += '<div style="background:#f0f7ff;border-radius:12px;padding:12px 14px;margin:8px 0;border-left:3px solid #2E86AB">'; enLista = true; }
      let c = line.replace(/^[-•]\s*/, '');
      c = c.replace(/(\d+€[^\s]*|Desde \d+€|Consultar precio|\d+% de descuento)/g, '<span style="color:#2E86AB;font-weight:600">$1</span>');
      html += `<div style="padding:6px 0;border-bottom:1px solid #e8f0f8;display:flex;align-items:center;gap:6px"><span style="color:#2E86AB">💎</span><span>${c}</span></div>`;
    } else {
      if (enLista) { html += '</div>'; enLista = false; }
      html += `<p style="margin:6px 0">${line}</p>`;
    }
  });
  if (enLista) html += '</div>';
  return html;
}

export function agregarMensaje(texto, tipo) {
  const msgs = document.getElementById("ia-w-msgs");
  const div = document.createElement("div");
  div.className = `ia-msg ${tipo}`;
  if (tipo === "bot") div.innerHTML = formatMessage(texto);
  else div.textContent = texto;
  msgs.appendChild(div);
  scrollMsgs();
  return div;
}

export function mostrarTyping() {
  const msgs = document.getElementById("ia-w-msgs");
  const div = document.createElement("div");
  div.className = "ia-msg typing";
  div.id = "ia-w-typing";
  div.innerHTML = '<div class="ia-dots"><span></span><span></span><span></span></div>';
  msgs.appendChild(div);
  scrollMsgs();
}

export function ocultarTyping() {
  const el = document.getElementById("ia-w-typing");
  if (el) el.remove();
}

export async function enviarMensaje() {
  const input = document.getElementById("ia-w-input");
  const sendBtn = document.getElementById("ia-w-send");
  const texto = input.value.trim();
  if (!texto) return;
  input.value = "";
  sendBtn.disabled = true;
  agregarMensaje(texto, "user");
  mostrarTyping();
  try {
    const res = await fetch(`${WIDGET_CONFIG.apiUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cliente_id: WIDGET_CONFIG.clienteId, mensaje: texto, session_id: sessionId }),
    });
    ocultarTyping();
    if (!res.ok) throw new Error();
    const data = await res.json();
    agregarMensaje(data.respuesta, "bot");
    if (data.mostrar_formulario) mostrarFormulario();
  } catch {
    ocultarTyping();
    agregarMensaje("⚠️ Error de conexión. Intenta de nuevo.", "bot");
  }
  sendBtn.disabled = false;
  input.focus();
}