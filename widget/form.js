import { WIDGET_CONFIG, scrollMsgs } from './utils.js';
import { agregarMensaje } from './chat.js';

let citaData = { nombre: "", email: "", telefono: "", servicio: "", fecha: "", hora: "", notas: "" };
let currentStep = 0;
let slotsDisponibles = [];

// ======= VALIDACIONES =======
const validaciones = {
  nombre: (v) => {
    if (!v) return "El nombre es obligatorio";
    if (v.length < 3) return "Mínimo 3 caracteres";
    if (!/^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s'-]+$/.test(v)) return "Solo letras y espacios";
    return null;
  },
  email: (v) => {
    if (!v) return "El email es obligatorio";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)) return "Email no válido (ej: tu@email.com)";
    return null;
  },
  telefono: (v) => {
    if (!v) return "El teléfono es obligatorio";
    const limpio = v.replace(/[\s\-\(\)\.]/g, "");
    if (!/^\+?\d{9,15}$/.test(limpio)) return "Teléfono no válido (mín. 9 dígitos)";
    return null;
  },
  fecha: (v) => {
    if (!v) return "Selecciona una fecha";
    const sel = new Date(v + "T00:00");
    const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
    if (sel < hoy) return "La fecha no puede ser pasada";
    if (sel.getDay() === 0) return "No hay servicio los domingos";
    return null;
  },
  hora: (v) => {
    if (!v) return "Selecciona un horario";
    return null;
  },
};

function mostrarError(inputId, mensaje) {
  limpiarError(inputId);
  const input = document.getElementById(inputId);
  if (!input) return;
  input.style.borderColor = "#ef4444";
  input.style.background = "#fef2f2";
  const err = document.createElement("div");
  err.className = "ia-field-error";
  err.id = `${inputId}-error`;
  err.innerHTML = `⚠️ ${mensaje}`;
  err.style.cssText = "color:#ef4444;font-size:12px;margin:4px 0 8px 4px;display:block;animation:ia-fade-in 0.2s ease;";
  input.parentNode.insertBefore(err, input.nextSibling);
}

function limpiarError(inputId) {
  const input = document.getElementById(inputId);
  if (input) { input.style.borderColor = ""; input.style.background = ""; }
  const err = document.getElementById(`${inputId}-error`);
  if (err) err.remove();
}

function validarCampo(inputId, tipo) {
  const input = document.getElementById(inputId);
  if (!input) return false;
  const error = validaciones[tipo](input.value.trim());
  if (error) { mostrarError(inputId, error); return false; }
  limpiarError(inputId);
  input.style.borderColor = "#22c55e";
  input.style.background = "#f0fdf4";
  return true;
}

let SERVICIOS = [];

async function cargarServicios() {
  try {
    const res = await fetch(`${WIDGET_CONFIG.apiUrl}/servicios/${WIDGET_CONFIG.clienteId}`);
    const data = await res.json();
    SERVICIOS = [
      { value: "", label: "Selecciona un servicio..." },
      ...data.servicios.map(s => ({ value: s.id, label: s.nombre }))
    ];
  } catch {
    SERVICIOS = [{ value: "", label: "No se pudieron cargar los servicios" }];
  }
}

// ======= FORMULARIO PRINCIPAL =======
export async function mostrarFormulario() {
  const msgs = document.getElementById("ia-w-msgs");

  // Evitar duplicar formulario
  if (document.getElementById("ia-form-cita")) {
    agregarMensaje("Ya tienes un formulario abierto más arriba 👆", "bot");
    scrollMsgs();
    return;
  }

    // Cargar servicios del info.txt
  await cargarServicios();

  const form = document.createElement("div");
  form.className = "ia-form-card";
  form.id = "ia-form-cita";

  const serviciosHTML = SERVICIOS.map(s =>
    `<option value="${s.value}">${s.label}</option>`
  ).join("");

  form.innerHTML = `
    <div class="ia-form-header">
      <h4>📅 Reservar Cita</h4>
      <p>Completa los datos en 4 sencillos pasos</p>
    </div>
    <div class="ia-form-progress">
      <div class="ia-form-step-dot active" data-step="0"></div>
      <div class="ia-form-step-dot" data-step="1"></div>
      <div class="ia-form-step-dot" data-step="2"></div>
      <div class="ia-form-step-dot" data-step="3"></div>
    </div>
    <div class="ia-form-body">

      <!-- STEP 0: Datos personales -->
      <div class="ia-form-step active" data-step="0">
        <label class="ia-form-label">👤 Nombre completo <span style="color:#ef4444">*</span></label>
        <input type="text" id="ia-f-nombre" placeholder="Ej: María García López" maxlength="60" autocomplete="name" />

        <label class="ia-form-label">📧 Email <span style="color:#ef4444">*</span></label>
        <input type="email" id="ia-f-email" placeholder="tu@email.com" maxlength="80" autocomplete="email" />

        <label class="ia-form-label">📱 Teléfono <span style="color:#ef4444">*</span></label>
        <input type="tel" id="ia-f-tel" placeholder="+34 600 000 000" maxlength="20" autocomplete="tel" />

        <div class="ia-form-actions">
          <button class="ia-form-btn primary" id="ia-f-next0">Siguiente →</button>
        </div>
      </div>

      <!-- STEP 1: Servicio -->
      <div class="ia-form-step" data-step="1">
        <label class="ia-form-label">🏥 ¿Qué servicio necesitas? <span style="color:#ef4444">*</span></label>
        <select id="ia-f-servicio">${serviciosHTML}</select>

        <div id="ia-f-notas-wrap" style="display:none;">
          <label class="ia-form-label">📝 Cuéntanos más (opcional)</label>
          <textarea id="ia-f-notas" placeholder="Describe brevemente tu consulta..." 
            style="width:100%;padding:14px 16px;border:1.5px solid #e0e4ea;border-radius:14px;font-size:14px;
            font-family:inherit;background:#fafbfc;resize:vertical;min-height:80px;max-height:140px;
            outline:none;transition:all 0.2s;" maxlength="500"></textarea>
          <div style="text-align:right;font-size:11px;color:#aaa;margin-top:2px;">
            <span id="ia-f-notas-count">0</span>/500
          </div>
        </div>

        <div class="ia-form-actions">
          <button class="ia-form-btn secondary" id="ia-f-back0">← Atrás</button>
          <button class="ia-form-btn primary" id="ia-f-next1">Siguiente →</button>
        </div>
      </div>

      <!-- STEP 2: Fecha y hora -->
      <div class="ia-form-step" data-step="2">
        <label class="ia-form-label">📆 Selecciona fecha <span style="color:#ef4444">*</span></label>
        <input type="date" id="ia-f-fecha" />

        <div id="ia-fecha-error-wrap"></div>

        <label class="ia-form-label">🕐 Horarios disponibles</label>
        <div id="ia-time-slots">
          <p style="color:#aaa;font-size:14px;text-align:center;padding:24px 0;">
            ☝️ Selecciona una fecha para ver horarios
          </p>
        </div>

        <div class="ia-form-actions">
          <button class="ia-form-btn secondary" id="ia-f-back1">← Atrás</button>
          <button class="ia-form-btn primary" id="ia-f-next2" disabled>Siguiente →</button>
        </div>
      </div>

      <!-- STEP 3: Confirmación -->
      <div class="ia-form-step" data-step="3">
        <label class="ia-form-label">✅ Confirma tu cita</label>
        <div class="ia-resumen" id="ia-resumen"></div>

        <div class="ia-form-actions">
          <button class="ia-form-btn secondary" id="ia-f-back2">← Atrás</button>
          <button class="ia-form-btn primary" id="ia-f-confirm">Confirmar Cita ✓</button>
        </div>
      </div>

    </div>
  `;
  msgs.appendChild(form);
  scrollMsgs();

  // ======= SETUP FECHA MIN =======
  const hoy = new Date();
  const manana = new Date(hoy);
  manana.setDate(manana.getDate() + 1);
  document.getElementById("ia-f-fecha").setAttribute("min", manana.toISOString().split("T")[0]);

  // Max 60 días adelante
  const maxFecha = new Date(hoy);
  maxFecha.setDate(maxFecha.getDate() + 60);
  document.getElementById("ia-f-fecha").setAttribute("max", maxFecha.toISOString().split("T")[0]);

  // ======= VALIDACIÓN EN TIEMPO REAL =======
  document.getElementById("ia-f-nombre").addEventListener("blur", () => validarCampo("ia-f-nombre", "nombre"));
  document.getElementById("ia-f-email").addEventListener("blur", () => validarCampo("ia-f-email", "email"));
  document.getElementById("ia-f-tel").addEventListener("blur", () => validarCampo("ia-f-tel", "telefono"));

  // Limpiar error al escribir
  ["ia-f-nombre", "ia-f-email", "ia-f-tel"].forEach(id => {
    document.getElementById(id).addEventListener("input", () => limpiarError(id));
  });

  // Formatear teléfono
  document.getElementById("ia-f-tel").addEventListener("input", (e) => {
    let val = e.target.value.replace(/[^\d+\s\-()]/g, "");
    e.target.value = val;
  });

  // ======= STEP 0 → 1 =======
  document.getElementById("ia-f-next0").onclick = () => {
    const v1 = validarCampo("ia-f-nombre", "nombre");
    const v2 = validarCampo("ia-f-email", "email");
    const v3 = validarCampo("ia-f-tel", "telefono");
    if (!v1 || !v2 || !v3) return;
    citaData.nombre = document.getElementById("ia-f-nombre").value.trim();
    citaData.email = document.getElementById("ia-f-email").value.trim();
    citaData.telefono = document.getElementById("ia-f-tel").value.trim();
    irAStep(1);
  };

  // ======= STEP 1: SERVICIO =======
  document.getElementById("ia-f-servicio").onchange = (e) => {
    const wrap = document.getElementById("ia-f-notas-wrap");
    wrap.style.display = e.target.value ? "block" : "none";
  };

  document.getElementById("ia-f-notas")?.addEventListener("input", (e) => {
    document.getElementById("ia-f-notas-count").textContent = e.target.value.length;
  });

  document.getElementById("ia-f-next1").onclick = () => {
    const serv = document.getElementById("ia-f-servicio").value;
    if (!serv) {
      document.getElementById("ia-f-servicio").style.borderColor = "#ef4444";
      return;
    }
    document.getElementById("ia-f-servicio").style.borderColor = "#22c55e";
    citaData.servicio = SERVICIOS.find(s => s.value === serv)?.label || serv;
    citaData.notas = document.getElementById("ia-f-notas")?.value.trim() || "";
    irAStep(2);
  };

  // ======= STEP 2: FECHA =======
  document.getElementById("ia-f-fecha").onchange = async (e) => {
    const fecha = e.target.value;
    if (!fecha) return;

    const errorFecha = validaciones.fecha(fecha);
    const errorWrap = document.getElementById("ia-fecha-error-wrap");
    if (errorFecha) {
      errorWrap.innerHTML = `<div style="color:#ef4444;font-size:12px;margin:-8px 0 10px 4px;">⚠️ ${errorFecha}</div>`;
      document.getElementById("ia-f-fecha").style.borderColor = "#ef4444";
      return;
    }
    errorWrap.innerHTML = "";
    document.getElementById("ia-f-fecha").style.borderColor = "#22c55e";

    citaData.fecha = fecha;
    citaData.hora = "";
    document.getElementById("ia-f-next2").disabled = true;
    await cargarSlots(fecha);
  };

  document.getElementById("ia-f-next2").onclick = () => {
    if (!citaData.hora) return;
    renderResumen();
    irAStep(3);
  };


  document.getElementById("ia-f-confirm").onclick = confirmarCita;

  // ======= BOTONES ATRÁS =======
  document.getElementById("ia-f-back0").onclick = () => irAStep(0);
  document.getElementById("ia-f-back1").onclick = () => irAStep(1);
  document.getElementById("ia-f-back2").onclick = () => irAStep(2);

  currentStep = 0;
}

// ======= NAVEGACIÓN =======
function irAStep(step) {
  currentStep = step;
  const form = document.getElementById("ia-form-cita");
  form.querySelectorAll(".ia-form-step").forEach(s => s.classList.remove("active"));
  form.querySelectorAll(".ia-form-step-dot").forEach((d, i) => {
    d.classList.remove("active", "done");
    if (i < step) d.classList.add("done");
    if (i === step) d.classList.add("active");
  });
  form.querySelector(`.ia-form-step[data-step="${step}"]`).classList.add("active");
  scrollMsgs();
}

// ======= SLOTS =======
async function cargarSlots(fecha) {
  const container = document.getElementById("ia-time-slots");
  container.innerHTML = `<div class="ia-loading-slots"><div class="ia-spinner"></div>Consultando disponibilidad...</div>`;
  try {
    const res = await fetch(`${WIDGET_CONFIG.apiUrl}/disponibilidad?cliente_id=${WIDGET_CONFIG.clienteId}&fecha=${fecha}`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    slotsDisponibles = data.slots || [];
    renderSlots();
  } catch {
    slotsDisponibles = generarSlotsFallback();
    renderSlots();
  }
}

function generarSlotsFallback() {
  const slots = [];
  for (let h = 9; h <= 19; h++) {
    slots.push({ hora: `${String(h).padStart(2, "0")}:00`, disponible: Math.random() > 0.2 });
    if (h < 19) slots.push({ hora: `${String(h).padStart(2, "0")}:30`, disponible: Math.random() > 0.25 });
  }
  return slots;
}

function renderSlots() {
  const container = document.getElementById("ia-time-slots");
  if (slotsDisponibles.length === 0) {
    container.innerHTML = '<p style="color:#ef4444;font-size:14px;text-align:center;padding:24px 0;">😔 No hay horarios disponibles este día. Prueba otra fecha.</p>';
    return;
  }

  const disponibles = slotsDisponibles.filter(s => s.disponible).length;
  let html = `<div style="font-size:12px;color:#888;margin-bottom:8px;text-align:center;">
    ${disponibles} horario${disponibles !== 1 ? "s" : ""} disponible${disponibles !== 1 ? "s" : ""}
  </div>`;
  html += '<div class="ia-time-grid">';
  slotsDisponibles.forEach(slot => {
    const cls = slot.disponible ? "" : "disabled";
    const statusTxt = slot.disponible
      ? '<span class="ia-slot-status" style="color:#22c55e;">Libre</span>'
      : '<span class="ia-slot-status" style="color:#ef4444;">Ocupado</span>';
    html += `<div class="ia-time-slot ${cls}" data-hora="${slot.hora}">${slot.hora}${statusTxt}</div>`;
  });
  html += '</div>';
  container.innerHTML = html;

  container.querySelectorAll(".ia-time-slot:not(.disabled)").forEach(el => {
    el.onclick = () => {
      container.querySelectorAll(".ia-time-slot").forEach(s => s.classList.remove("selected"));
      el.classList.add("selected");
      citaData.hora = el.dataset.hora;
      document.getElementById("ia-f-next2").disabled = false;
    };
  });
}

// ======= RESUMEN =======
function renderResumen() {
  const fechaFormateada = new Date(citaData.fecha + "T00:00").toLocaleDateString("es-ES", {
    weekday: "long", day: "numeric", month: "long", year: "numeric"
  });
  document.getElementById("ia-resumen").innerHTML = `
    <div class="ia-resumen-row"><span>👤 Nombre</span><span>${citaData.nombre}</span></div>
    <div class="ia-resumen-row"><span>📧 Email</span><span>${citaData.email}</span></div>
    <div class="ia-resumen-row"><span>📱 Teléfono</span><span>${citaData.telefono}</span></div>
    <div class="ia-resumen-row"><span>🏥 Servicio</span><span>${citaData.servicio}</span></div>
    <div class="ia-resumen-row"><span>📆 Fecha</span><span style="text-transform:capitalize">${fechaFormateada}</span></div>
    <div class="ia-resumen-row"><span>🕐 Hora</span><span>${citaData.hora}h</span></div>
    ${citaData.notas ? `<div class="ia-resumen-row" style="flex-direction:column;gap:4px;"><span>📝 Notas</span><span style="font-weight:400;font-size:13px;color:#666;">${citaData.notas}</span></div>` : ""}
  `;
}

// ======= CONFIRMAR =======
async function confirmarCita() {
  const btn = document.getElementById("ia-f-confirm");
  btn.disabled = true;
  btn.innerHTML = '<span style="display:inline-flex;align-items:center;gap:8px;"><span class="ia-spinner" style="width:18px;height:18px;border-width:2px;margin:0;"></span> Reservando...</span>';

  try {
    const res = await fetch(`${WIDGET_CONFIG.apiUrl}/agendar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cliente_id: WIDGET_CONFIG.clienteId,
        nombre: citaData.nombre,
        email: citaData.email,
        telefono: citaData.telefono,
        servicio: citaData.servicio,
        fecha: citaData.fecha,
        hora: citaData.hora,
        notas: citaData.notas,
      }),
    });
    if (!res.ok) throw new Error();

    const form = document.getElementById("ia-form-cita");
    form.innerHTML = `
      <div class="ia-form-success">
        <div class="ia-check">✓</div>
        <h4>¡Cita Confirmada!</h4>
        <p style="margin-bottom:12px;">Te hemos enviado confirmación a<br/><strong>${citaData.email}</strong></p>
        <div style="background:#f0fdf4;border-radius:12px;padding:14px;text-align:left;font-size:13px;color:#333;">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
            <span>📆 ${new Date(citaData.fecha + "T00:00").toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" })}</span>
            <span>🕐 ${citaData.hora}h</span>
          </div>
          <div>${citaData.servicio}</div>
        </div>
      </div>
    `;
    agregarMensaje("¡Perfecto! Tu cita ha quedado reservada. Te enviaremos un recordatorio por email. 😊", "bot");
  } catch {
    btn.disabled = false;
    btn.textContent = "Confirmar Cita ✓";
    agregarMensaje("⚠️ Error al reservar. Por favor, inténtalo de nuevo.", "bot");
  }
}