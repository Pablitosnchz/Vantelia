import { inyectarEstilos } from "./styles.js";
import { construirWidget } from "./ui.js";
import { applyPublicConfig, fetchJson, WIDGET_CONFIG } from "./utils.js";

async function init() {
  let config = {
    nombre: "Asistente virtual",
    icono: "AI",
    color: "#1F6FEB",
    accent_color: "",
    logo_url: "",
    bienvenida: "Hola, soy tu asistente virtual. En que puedo ayudarte?",
    booking_enabled: false,
    branding_text: "Powered by Vantelia",
    contact_email: "",
    contact_phone: "",
    starter_questions: [],
  };

  try {
    config = await fetchJson(`${WIDGET_CONFIG.apiUrl}/cliente/${WIDGET_CONFIG.clienteId}`);
  } catch (error) {
    console.warn("No se pudo cargar la configuracion publica del widget.", error);
  }

  applyPublicConfig(config);
  inyectarEstilos(config.color || "#1F6FEB", config.accent_color || "");
  construirWidget(config);

  if (window.IA_WIDGET_OPEN_ON_LOAD) {
    document.getElementById("ia-w-btn")?.click();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
