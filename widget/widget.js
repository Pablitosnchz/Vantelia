import { WIDGET_CONFIG } from './utils.js';
import { inyectarEstilos } from './styles.js';
import { construirWidget } from './ui.js';

async function init() {
  let config;
  try {
    const res = await fetch(`${WIDGET_CONFIG.apiUrl}/cliente/${WIDGET_CONFIG.clienteId}`);
    config = await res.json();
  } catch {
    config = { nombre: "Clínica Saga", icono: "⚕️", color: "#2E86AB", bienvenida: "¡Hola! Soy Clara, asistente de Clínica Saga. ¿En qué puedo ayudarte? 😊" };
  }
  inyectarEstilos(config.color || "#2E86AB");
  construirWidget(config);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();