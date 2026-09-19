import { humanizeErrorMessage } from "./utils.js";

// Una sola autoridad de interfaz para chat y formulario. La revisión invalida
// preparaciones anteriores al corte, incluso si después llega una recuperación.
let revision = 0;
let stopped = false;
const disabledControls = new Map();

export function attentionRevision() { return revision; }

export function attentionAllows(preparedAt = revision) {
  return !stopped && preparedAt === revision;
}

export function attentionStatusElement() {
  let status = document.getElementById("ia-w-atencion-status");
  const inputArea = document.getElementById("ia-w-input-area");
  if (!status && inputArea?.parentNode) {
    status = document.createElement("div");
    status.id = "ia-w-atencion-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.setAttribute("aria-atomic", "true");
    inputArea.parentNode.insertBefore(status, inputArea);
  }
  return status;
}

export function showAttentionError(error) {
  if (!((error?.status === 409 && error?.code === "ATTENTION_STOPPED") ||
        (error?.status === 503 && error?.code === "ATTENTION_UNAVAILABLE"))) return false;
  stopped = true;
  revision += 1;
  const status = attentionStatusElement();
  if (status) status.textContent = humanizeErrorMessage(error);
  // No incluye entrada de chat ni enlaces humanos; conserva datos y disabled previo.
  document.querySelectorAll(
    "#ia-w-msgs .ia-action-card button[data-quick-message], " +
    "#ia-form-cita button, #ia-form-cita input, #ia-form-cita select, #ia-form-cita textarea"
  ).forEach(control => {
    if (!disabledControls.has(control)) disabledControls.set(control, control.disabled);
    control.disabled = true;
  });
  return true;
}

export function clearAttentionStatus(preparedAt) {
  if (preparedAt !== revision) return false;
  stopped = false;
  const status = document.getElementById("ia-w-atencion-status");
  if (status) status.textContent = "";
  disabledControls.forEach((disabled, control) => { control.disabled = disabled; });
  disabledControls.clear();
  return true;
}
