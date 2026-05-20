import { agregarAccionesIniciales, agregarMensaje, enviarMensaje } from "./chat.js";
import { escapeHtml, scrollMsgs, trackWidgetEvent, WIDGET_CONFIG } from "./utils.js";

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
  const previousValue = abierto;
  abierto = nextValue;

  const chat = document.getElementById("ia-w-chat");
  const button = document.getElementById("ia-w-btn");
  const badge = document.getElementById("ia-w-badge");

  if (!chat || !button) return;

  chat.classList.toggle("visible", abierto);
  const label = button.querySelector(".ia-launcher-label");
  const labelHtml = label ? label.outerHTML : "";
  button.innerHTML = abierto ? getCloseIcon() : (getLauncherIcon() + labelHtml);
  button.setAttribute("aria-expanded", abierto ? "true" : "false");
  button.classList.toggle("abierto", abierto);

  if (badge) badge.style.display = "none";

  if (abierto) {
    window.setTimeout(() => {
      document.getElementById("ia-w-input")?.focus();
      scrollMsgs();
    }, 120);
  }

  if (previousValue !== abierto) {
    trackWidgetEvent(abierto ? "widget_opened" : "widget_closed");
  }
}

export function toggleChat(forceValue) {
  setOpenState(typeof forceValue === "boolean" ? forceValue : !abierto);
}

export function construirWidget(cfg) {
  if (document.getElementById("ia-w-container")) return;

  const logoUrl = String(cfg.logo_url || "").trim();
  const avatarMarkup = logoUrl
    ? `<img class="ia-avatar-img" src="${escapeHtml(logoUrl)}" alt="Logo" />`
    : `<span class="ia-avatar" aria-hidden="true">${escapeHtml(cfg.icono || "AI")}</span>`;

  const launcherShape = cfg.launcher_shape === "bar" ? "bar" : "circle";
  let launcherSize = Number(cfg.launcher_size) || (launcherShape === "bar" ? 200 : 60);
  if (launcherShape === "circle") {
    launcherSize = Math.max(48, Math.min(96, launcherSize));
  } else {
    launcherSize = Math.max(120, Math.min(280, launcherSize));
  }
  const launcherLabel = launcherShape === "bar"
    ? (cfg.nombre ? `Hablar con ${cfg.nombre}` : "Hablar con asistente")
    : "";
  const btnStyle = launcherShape === "bar"
    ? `width:${launcherSize}px;height:48px;border-radius:999px;padding:0 18px;`
    : `width:${launcherSize}px;height:${launcherSize}px;`;

  const container = document.createElement("div");
  container.id = "ia-w-container";
  container.className = WIDGET_CONFIG.position === "left" ? "ia-left" : "ia-right";
  container.dataset.launcherShape = launcherShape;
  container.innerHTML = `
    <div id="ia-w-badge">${escapeHtml(cfg.bienvenida || "Necesitas ayuda?")}</div>
    <button
      id="ia-w-btn"
      class="ia-launcher-${launcherShape}"
      type="button"
      aria-label="Abrir chat"
      aria-controls="ia-w-chat"
      aria-expanded="false"
      style="${btnStyle}"
    >${getLauncherIcon()}${launcherLabel ? `<span class="ia-launcher-label">${escapeHtml(launcherLabel)}</span>` : ""}</button>
    <section id="ia-w-chat" aria-label="Chat con asistente virtual">
      <header id="ia-w-header">
        <div id="ia-w-header-info">
          ${avatarMarkup}
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
      <div id="ia-w-branding">${escapeHtml(WIDGET_CONFIG.brandingText.replace("Vantelia", "")).trimEnd()} <a href="https://www.vantelia.es" target="_blank" rel="noopener noreferrer">Vantelia</a></div>
    </section>
  `;

  document.body.appendChild(container);
  trackWidgetEvent("widget_loaded", {
    booking_enabled: !!cfg.booking_enabled,
  });
  agregarMensaje(cfg.bienvenida || "Hola, en que puedo ayudarte hoy?", "bot");
  agregarAccionesIniciales(Array.isArray(cfg.starter_questions) ? cfg.starter_questions : []);

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
