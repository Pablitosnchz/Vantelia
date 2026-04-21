import { scrollMsgs } from './utils.js';
import { enviarMensaje, agregarMensaje } from './chat.js';

let abierto = false;

export function construirWidget(cfg) {
  const c = document.createElement("div");
  c.id = "ia-w-container";
  c.innerHTML = `
    <div id="ia-w-badge">${cfg.bienvenida || "¿Necesitas ayuda?"}</div>
    <button id="ia-w-btn">💬</button>
    <div id="ia-w-chat">
      <div id="ia-w-header">
        <div id="ia-w-header-info">
          <span>${cfg.icono || "🤖"}</span>
          <div>
            <p>${cfg.nombre || "Asistente"}</p>
            <p>🟢 En línea</p>
          </div>
        </div>
        <button id="ia-w-close">✕</button>
      </div>
      <div id="ia-w-msgs"></div>
      <div id="ia-w-input-area">
        <input id="ia-w-input" type="text" placeholder="Escribe tu mensaje..." autocomplete="off" />
        <button id="ia-w-send">➤</button>
      </div>
      <div id="ia-w-powered">⚡ Powered by TuAgencia.com</div>
    </div>
  `;
  document.body.appendChild(c);
  agregarMensaje(cfg.bienvenida || "¡Hola! ¿En qué puedo ayudarte?", "bot");

  document.getElementById("ia-w-btn").onclick = toggleChat;
  document.getElementById("ia-w-close").onclick = () => toggleChat(false);
  document.getElementById("ia-w-send").onclick = enviarMensaje;
  document.getElementById("ia-w-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarMensaje(); }
  });
  document.getElementById("ia-w-badge").onclick = () => toggleChat(true);
  setTimeout(() => {
    const b = document.getElementById("ia-w-badge");
    if (b && !abierto) b.style.display = "none";
  }, 6000);
}

export function toggleChat(f) {
  abierto = typeof f === "boolean" ? f : !abierto;
  document.getElementById("ia-w-chat").classList.toggle("visible", abierto);
  const btn = document.getElementById("ia-w-btn");
  btn.innerHTML = abierto ? "✕" : "💬";
  btn.classList.toggle("abierto", abierto);
  const badge = document.getElementById("ia-w-badge");
  if (badge) badge.style.display = "none";
  if (abierto) setTimeout(() => document.getElementById("ia-w-input").focus(), 100);
}