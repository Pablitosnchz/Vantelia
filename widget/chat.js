import {
  WIDGET_CONFIG,
  escapeHtml,
  fetchJson,
  getSessionId,
  humanizeErrorMessage,
  scrollMsgs,
  setSessionId,
  trackWidgetEvent,
} from "./utils.js";
import { mostrarFormulario } from "./form.js";

let sending = false;

const DEFAULT_QUICK_ACTIONS = [
  { label: "Agendar cita", message: "Quiero agendar una cita" },
  { label: "Preguntas frecuentes", message: "Muestrame las preguntas frecuentes principales" },
  { label: "Informacion servicios", message: "Quiero informacion sobre servicios disponibles" },
  { label: "Recomendar servicio", message: "Recomiendame el servicio que mejor encaja con mi caso" },
  { label: "Comparar servicios", message: "Quiero comparar servicios antes de decidir" },
  { label: "Estimar precio", message: "Ayudame a estimar precio, tiempo o alcance aproximado" },
];

function formatInline(text) {
  const linked = text.replace(/\bhttps?:\/\/[^\s<]+/g, (match) => {
    const trailing = match.match(/[.,;:!?)]*$/)?.[0] || "";
    const url = trailing ? match.slice(0, -trailing.length) : match;
    if (!url) return match;
    return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${trailing}`;
  });
  return linked.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function formatListInline(text) {
  return formatInline(text);
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
      const cleanItem = item.trim();
      const isHeading = /:$/.test(cleanItem) && !cleanItem.slice(0, -1).includes(":");
      html += `<li class="${isHeading ? "ia-list-heading" : ""}">${formatListInline(cleanItem)}</li>`;
    });
    html += "</ul>";
    listItems = [];
  };

  lines.forEach((line) => {
    if (/^[-*•·]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      listItems.push(line.replace(/^([-*•·]|\d+\.)\s+/, ""));
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

function buildShortLabel(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed) return "";
  if (trimmed.length <= 32) return trimmed;
  const cut = trimmed.slice(0, 32);
  const lastSpace = cut.lastIndexOf(" ");
  return (lastSpace > 12 ? cut.slice(0, lastSpace) : cut).trimEnd() + "…";
}

export function agregarAccionesIniciales(starterQuestions) {
  const msgs = document.getElementById("ia-w-msgs");
  if (!msgs || document.getElementById("ia-w-start-actions")) return null;

  const fromClient = Array.isArray(starterQuestions)
    ? starterQuestions
        .map((q) => String(q || "").trim())
        .filter(Boolean)
        .slice(0, 8)
    : [];

  const actions = fromClient.length
    ? fromClient.map((q) => ({ label: buildShortLabel(q), message: q }))
    : DEFAULT_QUICK_ACTIONS.slice();

  if (!actions.length) return null;

  const div = document.createElement("div");
  div.className = "ia-msg bot ia-action-card";
  div.id = "ia-w-start-actions";
  div.innerHTML = `
    <p><strong>¿Qué quieres hacer ahora?</strong></p>
    <p>Elige una pregunta rápida o escríbeme la tuya.</p>
    <div class="ia-action-grid">
      ${actions
        .map(
          (action) =>
            `<button type="button" data-quick-message="${escapeHtml(action.message)}">${escapeHtml(action.label)}</button>`
        )
        .join("")}
    </div>
  `;

  div.querySelectorAll("button[data-quick-message]").forEach((button) => {
    button.addEventListener("click", () => {
      const message = button.getAttribute("data-quick-message") || "";
      trackWidgetEvent("widget_quick_action_click", {
        quick_action: message,
      });
      enviarMensaje(message);
    });
  });

  msgs.appendChild(div);
  scrollMsgs();
  return div;
}

export function agregarAccionesMenu(actions = []) {
  const msgs = document.getElementById("ia-w-msgs");
  if (!msgs || !Array.isArray(actions) || !actions.length) return null;

  const cleanActions = actions
    .map((action) => ({
      label: String(action?.label || "").trim(),
      message: String(action?.message || "").trim(),
    }))
    .filter((action) => action.label && action.message)
    .slice(0, 8);
  if (!cleanActions.length) return null;

  const div = document.createElement("div");
  div.className = "ia-msg bot ia-action-card";
  div.innerHTML = `
    <p><strong>Elige una opcion</strong></p>
    <div class="ia-action-grid">
      ${cleanActions
        .map(
          (action) =>
            `<button type="button" data-quick-message="${escapeHtml(action.message)}">${escapeHtml(action.label)}</button>`
        )
        .join("")}
    </div>
  `;

  div.querySelectorAll("button[data-quick-message]").forEach((button) => {
    button.addEventListener("click", () => {
      const message = button.getAttribute("data-quick-message") || "";
      trackWidgetEvent("widget_quick_action_click", {
        quick_action: message,
      });
      enviarMensaje(message);
    });
  });

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

export async function enviarMensaje(textoForzado = "") {
  if (sending) return;

  const input = document.getElementById("ia-w-input");
  const sendBtn = document.getElementById("ia-w-send");
  if (!input || !sendBtn) return;

  const forcedText = typeof textoForzado === "string" ? textoForzado : "";
  const texto = (forcedText || input.value).trim();
  if (!texto) return;

  sending = true;
  trackWidgetEvent("widget_message_sent", {
    message_length: texto.length,
    forced_message: !!forcedText,
  });
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
    trackWidgetEvent("widget_message_response", {
      response_length: String(data.respuesta || "").length,
      booking_form_shown: !!(data.mostrar_formulario && WIDGET_CONFIG.bookingEnabled),
    });
    ocultarTyping();
    agregarMensaje(data.respuesta, "bot");
    if (Array.isArray(data.quick_actions) && data.quick_actions.length) {
      agregarAccionesMenu(data.quick_actions);
    }

    if (data.mostrar_formulario && WIDGET_CONFIG.bookingEnabled) {
      trackWidgetEvent("booking_form_requested");
      mostrarFormulario();
    }
  } catch (error) {
    const message = humanizeErrorMessage(
      error,
      "No se ha podido enviar el mensaje. Intentalo de nuevo en unos segundos."
    );
    trackWidgetEvent("widget_message_error", {
      error_message: error?.message || "unknown",
    });
    ocultarTyping();
    agregarMensaje(`${message} Si quieres, puedes abrir una consulta gratuita desde la web.`, "bot");
  } finally {
    sending = false;
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
}
