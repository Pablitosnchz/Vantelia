export const WIDGET_CONFIG = {
  apiUrl: window.IA_WIDGET_API || "http://localhost:8000",
  clienteId: window.IA_WIDGET_CLIENTE || "Clinica_Saga",
};

export let sessionId = localStorage.getItem("ia_session") || generarId();
localStorage.setItem("ia_session", sessionId);

export function generarId() {
  return "s_" + Math.random().toString(36).substr(2, 12);
}

export function scrollMsgs() {
  const msgs = document.getElementById("ia-w-msgs");
  if (!msgs) return;
  setTimeout(() => { msgs.scrollTop = msgs.scrollHeight; }, 100);
  setTimeout(() => { msgs.scrollTop = msgs.scrollHeight; }, 300);
}