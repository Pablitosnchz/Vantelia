// Núcleo determinista COMPARTIDO de la voz en el navegador (widget embebido + portal app_ui).
// Solo funciones PURAS: detección de intención/silencio, normalización de texto y construcción
// de instrucciones para el modelo. Sin DOM, sin estado, sin fetch — para que exista UNA sola
// copia de esta lógica fina (regex de anti-silencio, confirmación, fecha) en vez de duplicarla
// en widget/voice.js y app_ui/index.html. El bucle con estado (watchdog, nudges) vive en cada
// cliente, pero TODA la decisión de "qué frase decir / cuándo empujar" sale de aquí.
//
// Consumo:
//   - widget/voice.js  -> `import * as voiceCore from "./voice_core.js"` (esbuild lo inlinea).
//   - app_ui (single-file SPA) -> <script type="module" src="/widget/voice_core.js"> expone
//     window.VanteliaVoiceCore (mismo objeto). El portal usa window.VanteliaVoiceCore.*.
//
// Mantener en sync conceptual con backend/voice.py (motor Twilio): misma SPEC, distinto runtime.

export function normalizeVoiceText(text) {
  return String(text || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^0-9a-z\s]/g, " ").replace(/\s+/g, " ").trim();
}

export function isUnintelligibleText(text) {
  const t = normalizeVoiceText(text);
  if (!t) return true;
  const meaningful = t.replace(/[^0-9a-z]/g, "");
  if (meaningful.length < 2) return true;
  if (
    t.indexOf("subtitulos realizados por la comunidad de amara") >= 0
    || (t.indexOf("subt") >= 0 && t.indexOf("tulos realizados por la comunidad de amara") >= 0)
  ) return true;
  if (/^diosos?\s+mios?$/.test(t)) return true;
  if (/^(y\s+)?a\s*las?$/.test(t) || /^y\s+alas$/.test(t)) return true;
  return false;
}


export function toolFollowupPrompt(name, result) {
  if (!result || typeof result !== "object") return "";
  const msg = String(result.mensaje_voz || result.mensaje || result.error || "").trim();
  if (!msg) return "";
  if (result.needs_service) return `[sistema] Falta el servicio. Pregunta esto en una sola frase natural, sin anadir pasos: "${msg}"`;
  if (result.needs_location) return `[sistema] Falta el centro. Pregunta esto en una sola frase natural, sin anadir pasos: "${msg}"`;
  if (result.needs_slot) return `[sistema] Falta dia u hora. Pregunta esto en una sola frase natural, sin anadir pasos: "${msg}"`;
  if (name === "verificar_codigo" && result.ok) return `[sistema] El codigo ya esta verificado. Si el cliente ya habia pedido cancelar o reprogramar, llama ahora a la herramienta correspondiente sin hablar todavia. Si no hay accion pendiente, di una sola frase natural: "${msg}"`;
  if (name === "consultar_disponibilidad" && result.ok && result.hora && result.hora_disponible === true) return `[sistema] Hay hueco a la hora pedida. Di esta idea en una sola frase natural y pide solo nombre completo y telefono. No digas 'repito' ni pidas confirmacion de datos todavia, porque aun no tienes los datos del cliente: "${msg}"`;
  if (result.ok) return `[sistema] Di esta idea en una sola frase natural, sin anadir pasos ni explicaciones: "${msg}"`;
  if (!result.ok) return `[sistema] Di este problema de forma breve y, si procede, pregunta el siguiente dato minimo: "${msg}"`;
  return `[sistema] Di una sola frase natural: "${msg}"`;
}

export function toolResponseInstruction(name, result) {
  // Guia NATURAL (no verbatim): el modelo transmite el resultado con sus palabras, manteniendo
  // exactos los datos. Antes se forzaba 'di exactamente esta frase' y sonaba robotico.
  return toolFollowupPrompt(name, result) || (
    "Di al cliente el resultado en una frase breve y natural, manteniendo exactos los datos "
    + "(horas, fechas, precios, numero de reserva)."
  );
}

// Empujon INTERNO cuando el modelo se queda mudo (mismo espiritu que el motor de telefono):
// le recordamos el contexto y que continue, pero la frase la elige EL. No es texto de cara al
// cliente. Compartido por widget y portal para no divergir.
export const CONTINUE_NUDGE_TEXT =
  "[sistema] Te has quedado en silencio y el cliente espera. Continua la conversacion de forma "
  + "natural, con tus palabras y sin decir 'un momento': si esperabas un dato, vuelve a pedirlo; "
  + "si acabas de usar una herramienta, di su resultado; si el cliente pidio reservar, cancelar o "
  + "cambiar una cita, da el siguiente paso (identificar la cita, verificar la identidad o llamar "
  + "a la herramienta que toque). No repitas la misma frase de antes.";




export function extractBookingContact(text) {
  const raw = String(text || "");
  const match = raw.match(/(?:\+|00)?\d[\d\s().-]{7,}\d/);
  if (!match) return null;
  const phone = match[0].trim();
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 9) return null;
  let name = raw.replace(match[0], " ");
  name = name.replace(/\b(mi\s+nombre\s+es|me\s+llamo|soy|telefono|tel[eé]fono|movil|m[oó]vil)\b/gi, " ");
  name = name.replace(/[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]+/g, " ");
  name = name.replace(/-/g, " ").split(/\s+/).filter((p) => p.length > 1).join(" ").trim();
  if (name.length < 3) return null;
  return { nombre: name.slice(0, 120), telefono: phone };
}



// Expuesto como global para consumidores no-módulo (app_ui es single-file SPA y lo carga via
// <script type="module" src="/widget/voice_core.js">). El widget lo usa por import (bundle).
if (typeof window !== "undefined") {
  window.VanteliaVoiceCore = {
    normalizeVoiceText,
    isUnintelligibleText,
    toolFollowupPrompt,
    toolResponseInstruction,
    extractBookingContact,
    CONTINUE_NUDGE_TEXT,
  };
}
