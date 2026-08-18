const currentScript = document.currentScript;
const dataset = currentScript?.dataset || {};
const memoryStorage = new Map();

function trimTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function getSafeStorage() {
  try {
    const testKey = "__ia_widget_test__";
    window.localStorage.setItem(testKey, "1");
    window.localStorage.removeItem(testKey);
    return window.localStorage;
  } catch (error) {
    return {
      getItem(key) {
        return memoryStorage.has(key) ? memoryStorage.get(key) : null;
      },
      setItem(key, value) {
        memoryStorage.set(key, String(value));
      },
      removeItem(key) {
        memoryStorage.delete(key);
      },
    };
  }
}

function resolveApiUrl() {
  const explicitValue = window.IA_WIDGET_API || dataset.api;
  if (explicitValue) return trimTrailingSlash(explicitValue);

  if (currentScript?.src) {
    return trimTrailingSlash(new URL(currentScript.src, window.location.href).origin);
  }

  return trimTrailingSlash(window.location.origin);
}

function resolveClientId() {
  return String(window.IA_WIDGET_CLIENTE || dataset.client || "demo").trim();
}

function resolveLocationId() {
  return String(window.IA_WIDGET_LOCATION || dataset.location || "").trim();
}

const storage = getSafeStorage();

export const WIDGET_CONFIG = {
  apiUrl: resolveApiUrl(),
  clienteId: resolveClientId(),
  locationId: resolveLocationId(),
  position: dataset.position === "left" ? "left" : "right",
  bookingEnabled: false,
  brandingText: "Powered by Vantelia",
  contactEmail: "",
  contactPhone: "",
  voiceWidgetEnabled: false,
};

const sessionStorageKey = `ia_session_${WIDGET_CONFIG.clienteId}`;
let sessionId = storage.getItem(sessionStorageKey) || generarId();
storage.setItem(sessionStorageKey, sessionId);

export function generarId() {
  if (window.crypto?.randomUUID) {
    return `s_${window.crypto.randomUUID().replace(/-/g, "")}`;
  }

  const random = Math.random().toString(36).slice(2);
  return `s_${random}${Date.now().toString(36)}`;
}

export function getSessionId() {
  return sessionId;
}

export function setSessionId(nextSessionId) {
  if (!nextSessionId) return;
  sessionId = nextSessionId;
  storage.setItem(sessionStorageKey, nextSessionId);
}

export function trackWidgetEvent(eventName, payload = {}) {
  if (!eventName || typeof document === "undefined") return;
  document.dispatchEvent(new CustomEvent("vantelia:widget", {
    detail: {
      event: eventName,
      widget_client_id: WIDGET_CONFIG.clienteId,
      widget_position: WIDGET_CONFIG.position,
      session_id: getSessionId(),
      ...payload,
    },
  }));
}

export function applyPublicConfig(config = {}) {
  WIDGET_CONFIG.bookingEnabled = Boolean(config.booking_enabled);
  WIDGET_CONFIG.brandingText = config.branding_text || WIDGET_CONFIG.brandingText;
  WIDGET_CONFIG.contactEmail = config.contact_email || "";
  WIDGET_CONFIG.contactPhone = config.contact_phone || "";
  WIDGET_CONFIG.voiceWidgetEnabled = Boolean(config.voice_widget_enabled);
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function scrollMsgs() {
  const msgs = document.getElementById("ia-w-msgs");
  if (!msgs) return;

  window.requestAnimationFrame(() => {
    msgs.scrollTop = msgs.scrollHeight;
  });
}

export function humanizeErrorMessage(error, fallbackMessage) {
  const raw = String(error?.message || "").trim();
  if (!raw) return fallbackMessage || "No se pudo completar la solicitud.";

  if (raw.includes("Failed to fetch") || raw.includes("NetworkError")) {
    return "No se ha podido conectar con el asistente. Revisa la conexion o la URL del API.";
  }

  if (raw.includes("Dominio no autorizado")) {
    return "Este dominio no esta autorizado para usar el widget de este cliente.";
  }

  if (raw.includes("verificar el dominio de origen")) {
    return "El servidor no ha podido validar el dominio desde el que se carga el widget.";
  }

  if (raw.includes("límite temporal")) {
    return "Has realizado demasiadas solicitudes seguidas. Espera unos segundos y vuelve a intentarlo.";
  }

  if (raw.includes("ya no está disponible") || raw.includes("acaba de ser reservado")) {
    return "Ese horario acaba de dejar de estar disponible. Elige otro tramo.";
  }

  if (raw.includes("OPENAI_API_KEY")) {
    return "El asistente no esta disponible porque el backend no tiene configurada la clave de OpenAI.";
  }

  return raw || fallbackMessage || "No se pudo completar la solicitud.";
}

export function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutMs || 15000);
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
      signal: controller.signal,
    });

    let data = null;
    let rawText = "";
    try {
      rawText = await response.text();
      data = rawText ? JSON.parse(rawText) : null;
    } catch (error) {
      data = null;
    }

    if (!response.ok) {
      const message =
        data?.detail ||
        (rawText ? `Error ${response.status}: ${rawText.slice(0, 240)}` : `Error ${response.status}.`);
      throw new Error(message);
    }

    return data;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("La solicitud ha tardado demasiado en responder.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}
