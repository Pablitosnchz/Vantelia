import { agregarMensaje, enviarMensaje } from "./chat.js";
import { escapeHtml, scrollMsgs, WIDGET_CONFIG } from "./utils.js";

let abierto = false;

function getLauncherIcon() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M4 6.5A3.5 3.5 0 0 1 7.5 3h9A3.5 3.5 0 0 1 20 6.5v6A3.5 3.5 0 0 1 16.5 16H9l-4.1 3.4c-.66.55-1.65.08-1.65-.78V6.5Z" />
    </svg>
  `;
}

function getCloseIcon() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6 6.4 5Z" />
    </svg>
  `;
}

function setOpenState(nextValue) {
  abierto = nextValue;

  const chat = document.getElementById("ia-w-chat");
  const button = document.getElementById("ia-w-btn");
  const badge = document.getElementById("ia-w-badge");

  if (!chat || !button) return;

  chat.classList.toggle("visible", abierto);
  button.innerHTML = abierto ? getCloseIcon() : getLauncherIcon();
  button.setAttribute("aria-expanded", abierto ? "true" : "false");
  button.classList.toggle("abierto", abierto);

  if (badge) badge.style.display = "none";

  if (abierto) {
    window.setTimeout(() => {
      document.getElementById("ia-w-input")?.focus();
      scrollMsgs();
    }, 120);
  }
}

export function toggleChat(forceValue) {
  setOpenState(typeof forceValue === "boolean" ? forceValue : !abierto);
}

export function construirWidget(cfg) {
  if (document.getElementById("ia-w-container")) return;

  const container = document.createElement("div");
  container.id = "ia-w-container";
  container.className = WIDGET_CONFIG.position === "left" ? "ia-left" : "ia-right";
  container.innerHTML = `
    <div id="ia-w-badge">${escapeHtml(cfg.bienvenida || "Necesitas ayuda?")}</div>
    <button
      id="ia-w-btn"
      type="button"
      aria-label="Abrir chat"
      aria-controls="ia-w-chat"
      aria-expanded="false"
    >${getLauncherIcon()}</button>
    <section id="ia-w-chat" aria-label="Chat con asistente virtual">
      <header id="ia-w-header">
        <div id="ia-w-header-info">
          <span class="ia-avatar" aria-hidden="true">${escapeHtml(cfg.icono || "AI")}</span>
          <div>
            <p>${escapeHtml(cfg.nombre || "Asistente virtual")}</p>
            <p>Asistente oficial</p>
          </div>
        </div>
        <button id="ia-w-close" type="button" aria-label="Cerrar chat">${getCloseIcon()}</button>
      </header>
      <div id="ia-w-msgs" role="log" aria-live="polite" aria-atomic="false"></div>
      <div id="ia-w-input-area">
        <input
          id="ia-w-input"
          type="text"
          placeholder="Escribe tu mensaje..."
          autocomplete="off"
          maxlength="500"
        />
        <button id="ia-w-send" type="button" aria-label="Enviar mensaje">Enviar</button>
      </div>
      <div id="ia-w-powered">${escapeHtml(cfg.branding_text || "Powered by Vantelia")}</div>
    </section>
  `;

  document.body.appendChild(container);
  agregarMensaje(cfg.bienvenida || "Hola, en que puedo ayudarte hoy?", "bot");

  document.getElementById("ia-w-btn")?.addEventListener("click", () => toggleChat());
  document.getElementById("ia-w-close")?.addEventListener("click", () => toggleChat(false));
  document.getElementById("ia-w-send")?.addEventListener("click", enviarMensaje);
  document.getElementById("ia-w-input")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      enviarMensaje();
    }
  });
  document.getElementById("ia-w-badge")?.addEventListener("click", () => toggleChat(true));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && abierto) {
      toggleChat(false);
    }
  });

  window.setTimeout(() => {
    const badge = document.getElementById("ia-w-badge");
    if (badge && !abierto) badge.style.display = "none";
  }, 9000);
}
