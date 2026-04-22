import {
  WIDGET_CONFIG,
  escapeHtml,
  fetchJson,
  getSessionId,
  humanizeErrorMessage,
  scrollMsgs,
  setSessionId,
} from "./utils.js";
import { mostrarFormulario } from "./form.js";

let sending = false;

function formatInline(text) {
  return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

export function formatMessage(text) {
  const safeText = escapeHtml(text || "");
  const lines = safeText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return "<p>No hay contenido disponible.</p>";
  }

  let html = "";
  let listItems = [];

  const flushList = () => {
    if (!listItems.length) return;
    html += '<ul class="ia-rich-list">';
    listItems.forEach((item) => {
      html += `<li>${formatInline(item)}</li>`;
    });
    html += "</ul>";
    listItems = [];
  };

  lines.forEach((line) => {
    if (/^[-*•]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      listItems.push(line.replace(/^([-*•]|\d+\.)\s+/, ""));
      return;
    }

    flushList();
    html += `<p>${formatInline(line)}</p>`;
  });

  flushList();
  return html;
}

export function agregarMensaje(texto, tipo) {
  const msgs = document.getElementById("ia-w-msgs");
  if (!msgs) return null;

  const div = document.createElement("div");
  div.className = `ia-msg ${tipo}`;

  if (tipo === "bot") {
    div.innerHTML = formatMessage(texto);
  } else {
    div.textContent = texto;
  }

  msgs.appendChild(div);
  scrollMsgs();
  return div;
}

export function mostrarTyping() {
  const msgs = document.getElementById("ia-w-msgs");
  if (!msgs || document.getElementById("ia-w-typing")) return;

  const div = document.createElement("div");
  div.className = "ia-msg typing";
  div.id = "ia-w-typing";
  div.innerHTML = '<div class="ia-dots"><span></span><span></span><span></span></div>';
  msgs.appendChild(div);
  scrollMsgs();
}

export function ocultarTyping() {
  document.getElementById("ia-w-typing")?.remove();
}

export async function enviarMensaje() {
  if (sending) return;

  const input = document.getElementById("ia-w-input");
  const sendBtn = document.getElementById("ia-w-send");
  if (!input || !sendBtn) return;

  const texto = input.value.trim();
  if (!texto) return;

  sending = true;
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;
  agregarMensaje(texto, "user");
  mostrarTyping();

  try {
    const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cliente_id: WIDGET_CONFIG.clienteId,
        mensaje: texto,
        session_id: getSessionId(),
      }),
    });

    setSessionId(data.session_id);
    ocultarTyping();
    agregarMensaje(data.respuesta, "bot");

    if (data.mostrar_formulario && WIDGET_CONFIG.bookingEnabled) {
      mostrarFormulario();
    }
  } catch (error) {
    ocultarTyping();
    agregarMensaje(
      humanizeErrorMessage(
        error,
        "No se ha podido enviar el mensaje. Intentalo de nuevo en unos segundos."
      ),
      "bot"
    );
  } finally {
    sending = false;
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
}
