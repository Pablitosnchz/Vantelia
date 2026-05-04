import { agregarMensaje } from "./chat.js";
import {
  escapeHtml,
  fetchJson,
  formatLocalDate,
  humanizeErrorMessage,
  scrollMsgs,
  trackWidgetEvent,
  WIDGET_CONFIG,
} from "./utils.js";

const MAX_WIDGET_BOOKING_DAYS = 60;

let citaData = {};
let currentStep = 0;
let services = [];
let employees = [];
let slotsDisponibles = [];

function bringFormIntoView(form, behavior = "smooth") {
  const msgs = document.getElementById("ia-w-msgs");
  if (!form || !msgs) return;

  window.requestAnimationFrame(() => {
    const top = Math.max(0, form.offsetTop - 8);
    msgs.scrollTo({ top, behavior });
  });
}

function resetState() {
  citaData = {
    nombre: "",
    email: "",
    telefono: "",
    servicio: "",
    employeeId: "",
    employeeName: "",
    fecha: "",
    hora: "",
    notas: "",
  };
  currentStep = 0;
  services = [];
  employees = [];
  slotsDisponibles = [];
}

const validaciones = {
  nombre(valor) {
    if (!valor) return "El nombre es obligatorio.";
    if (valor.length < 3) return "Escribe al menos 3 caracteres.";
    if (!/^[\p{L}\s'-]+$/u.test(valor)) {
      return "Usa solo letras, espacios o apostrofes.";
    }
    return "";
  },
  email(valor) {
    if (!valor) return "El email es obligatorio.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(valor)) return "El email no es valido.";
    return "";
  },
  telefono(valor) {
    if (!valor) return "El telefono es obligatorio.";
    const limpio = valor.replace(/[\s\-().]/g, "");
    if (!/^\+?\d{9,15}$/.test(limpio)) return "Introduce un telefono valido.";
    return "";
  },
  fecha(valor) {
    if (!valor) return "Selecciona una fecha.";
    return "";
  },
  hora(valor) {
    if (!valor) return "Selecciona un horario.";
    return "";
  },
};

function setFieldError(inputId, message) {
  const input = document.getElementById(inputId);
  if (!input) return;

  clearFieldError(inputId);
  input.classList.add("ia-invalid");

  const error = document.createElement("div");
  error.className = "ia-field-error";
  error.id = `${inputId}-error`;
  error.textContent = message;
  input.insertAdjacentElement("afterend", error);
}

function clearFieldError(inputId) {
  const input = document.getElementById(inputId);
  input?.classList.remove("ia-invalid");
  document.getElementById(`${inputId}-error`)?.remove();
}

function validateField(inputId, validatorName) {
  const input = document.getElementById(inputId);
  if (!input) return false;

  const value = input.value.trim();
  const error = validaciones[validatorName](value);
  if (error) {
    setFieldError(inputId, error);
    return false;
  }

  clearFieldError(inputId);
  return true;
}

async function cargarServicios() {
  const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/servicios/${WIDGET_CONFIG.clienteId}`);
  services = Array.isArray(data.servicios) ? data.servicios : [];

  if (!services.length) {
    services = [{ id: "consulta_general", nombre: "Consulta general" }];
  }
}

async function cargarProfesionales() {
  const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/profesionales/${WIDGET_CONFIG.clienteId}`);
  employees = Array.isArray(data.items) ? data.items : [];
  if (!employees.length) {
    throw new Error("No hay profesionales disponibles para reservar en este momento.");
  }
}

function fillServiceOptions(select) {
  if (!select) return;

  const selectedEmployee = employees.find((employee) => employee.employee_id === citaData.employeeId);
  const allowedServiceIds = Array.isArray(selectedEmployee?.service_ids) ? selectedEmployee.service_ids : [];
  const scopedServices = selectedEmployee && !selectedEmployee.allows_all_services && allowedServiceIds.length
    ? services.filter((service) => allowedServiceIds.includes(service.id))
    : services;

  select.innerHTML = "";
  select.disabled = false;

  if (!scopedServices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No hay servicios disponibles";
    option.selected = true;
    select.appendChild(option);
    select.disabled = true;
    return;
  }

  scopedServices.forEach((service) => {
    const option = document.createElement("option");
    option.value = service.id;
    option.textContent = service.nombre;
    select.appendChild(option);
  });
}

function fillEmployeeOptions(select, wrap) {
  if (!select || !wrap) return;

  if (employees.length <= 1) {
    wrap.classList.add("hidden");
    const first = employees[0];
    citaData.employeeId = first?.employee_id || "";
    citaData.employeeName = first?.name || "";
    return;
  }

  wrap.classList.remove("hidden");
  select.innerHTML = '<option value="">Aleatorio</option>';
  employees.forEach((employee) => {
    const option = document.createElement("option");
    option.value = employee.employee_id;
    option.textContent = employee.role_label
      ? `${employee.name} - ${employee.role_label}`
      : employee.name;
    select.appendChild(option);
  });
  citaData.employeeId = "";
  citaData.employeeName = "Aleatorio";
}

function toggleStep(step) {
  currentStep = step;
  const form = document.getElementById("ia-form-cita");
  if (!form) return;
  const formBody = form.querySelector(".ia-form-body");

  form.querySelectorAll(".ia-form-step").forEach((section) => {
    section.classList.remove("active");
  });
  form.querySelectorAll(".ia-form-step-dot").forEach((dot, index) => {
    dot.classList.remove("active", "done");
    if (index < step) dot.classList.add("done");
    if (index === step) dot.classList.add("active");
  });

  form.querySelector(`.ia-form-step[data-step="${step}"]`)?.classList.add("active");
  if (formBody) formBody.scrollTop = 0;
  bringFormIntoView(form);
  scrollMsgs();
}

async function cargarSlots(fecha) {
  const container = document.getElementById("ia-time-slots");
  const nextButton = document.getElementById("ia-f-next2");
  if (!container || !nextButton) return;

  nextButton.disabled = true;
  container.innerHTML =
    '<div class="ia-loading-slots"><span class="ia-spinner"></span><div>Consultando disponibilidad...</div></div>';

  try {
    const params = new URLSearchParams({
      cliente_id: WIDGET_CONFIG.clienteId,
      fecha,
    });
    if (citaData.employeeId) params.set("employee_id", citaData.employeeId);
    if (citaData.servicio) params.set("servicio", citaData.servicio);
    const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/disponibilidad?${params.toString()}`);
    slotsDisponibles = Array.isArray(data.slots) ? data.slots : [];
    renderSlots();
  } catch (error) {
    slotsDisponibles = [];
    container.innerHTML = `<div class="ia-slot-error">${escapeHtml(
      humanizeErrorMessage(error, "No se ha podido cargar la disponibilidad.")
    )}</div>`;
  }
}

function renderSlots() {
  const container = document.getElementById("ia-time-slots");
  const nextButton = document.getElementById("ia-f-next2");
  if (!container || !nextButton) return;

  container.innerHTML = "";

  if (!slotsDisponibles.length) {
    container.innerHTML = '<div class="ia-empty-slots">No hay horarios disponibles para este dia.</div>';
    return;
  }

  const availableCount = slotsDisponibles.filter((slot) => slot.disponible).length;
  if (!availableCount) {
    container.innerHTML = '<div class="ia-empty-slots">Todos los horarios de este dia estan ocupados.</div>';
    return;
  }

  const info = document.createElement("div");
  info.className = "ia-empty-slots";
  info.textContent = `${availableCount} horario${availableCount === 1 ? "" : "s"} disponible${availableCount === 1 ? "" : "s"}`;
  container.appendChild(info);

  const grid = document.createElement("div");
  grid.className = "ia-time-grid";

  slotsDisponibles.forEach((slot) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `ia-time-slot${slot.disponible ? "" : " disabled"}`;
    button.disabled = !slot.disponible;
    button.dataset.hora = slot.hora;
    button.innerHTML = `${escapeHtml(slot.hora)}<small>${slot.disponible ? "Libre" : "Ocupado"}</small>`;

    if (slot.disponible) {
      button.addEventListener("click", () => {
        grid.querySelectorAll(".ia-time-slot").forEach((item) => item.classList.remove("selected"));
        button.classList.add("selected");
        citaData.hora = slot.hora;
        nextButton.disabled = false;
        trackWidgetEvent("booking_slot_selected", {
          date: citaData.fecha,
          time: citaData.hora,
          service: citaData.servicio,
        });
      });
    }

    grid.appendChild(button);
  });

  container.appendChild(grid);
}

function renderResumen() {
  const resumen = document.getElementById("ia-resumen");
  if (!resumen) return;

  const selectedDate = new Date(`${citaData.fecha}T12:00:00`);
  const formattedDate = selectedDate.toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  resumen.innerHTML = `
    <div class="ia-resumen-row"><span>Nombre</span><span>${escapeHtml(citaData.nombre)}</span></div>
    <div class="ia-resumen-row"><span>Email</span><span>${escapeHtml(citaData.email)}</span></div>
    <div class="ia-resumen-row"><span>Telefono</span><span>${escapeHtml(citaData.telefono)}</span></div>
    ${
      citaData.employeeName
        ? `<div class="ia-resumen-row"><span>Profesional</span><span>${escapeHtml(citaData.employeeName)}</span></div>`
        : ""
    }
    <div class="ia-resumen-row"><span>Servicio</span><span>${escapeHtml(citaData.servicio)}</span></div>
    <div class="ia-resumen-row"><span>Fecha</span><span>${escapeHtml(formattedDate)}</span></div>
    <div class="ia-resumen-row"><span>Hora</span><span>${escapeHtml(citaData.hora)}</span></div>
    ${
      citaData.notas
        ? `<div class="ia-resumen-row"><span>Notas</span><span>${escapeHtml(citaData.notas)}</span></div>`
        : ""
    }
  `;
}

function fallbackContacto() {
  const contacto = [WIDGET_CONFIG.contactPhone, WIDGET_CONFIG.contactEmail].filter(Boolean);
  if (!contacto.length) return "";
  return ` Tambien puedes contactar directamente por ${contacto.join(" / ")}.`;
}

async function confirmarCita() {
  const confirmButton = document.getElementById("ia-f-confirm");
  if (!confirmButton) return;

  confirmButton.disabled = true;
  confirmButton.innerHTML = '<span class="ia-spinner"></span>';
  trackWidgetEvent("booking_submit", {
    service: citaData.servicio,
    has_employee: !!citaData.employeeId,
  });

  try {
    const response = await fetchJson(`${WIDGET_CONFIG.apiUrl}/agendar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cliente_id: WIDGET_CONFIG.clienteId,
        nombre: citaData.nombre,
        email: citaData.email,
        telefono: citaData.telefono,
        servicio: citaData.servicio,
        employee_id: citaData.employeeId,
        fecha: citaData.fecha,
        hora: citaData.hora,
        notas: citaData.notas,
      }),
    });

    const form = document.getElementById("ia-form-cita");
    if (!form) return;

    const title = response.estado === "pending_review" ? "Solicitud recibida" : "Solicitud registrada";
    const manageButton = response.manage_url
      ? `<a class="ia-form-btn secondary" href="${escapeHtml(response.manage_url)}" target="_blank" rel="noreferrer">Gestionar cita</a>`
      : "";
    const providerButton = response.provider_booking_url
      ? `<a class="ia-form-btn secondary" href="${escapeHtml(response.provider_booking_url)}" target="_blank" rel="noreferrer">Abrir proveedor</a>`
      : "";
    form.innerHTML = `
      <div class="ia-form-success">
        <div class="ia-check">${response.estado === "pending_review" ? "!" : "OK"}</div>
        <h4>${escapeHtml(title)}</h4>
        <p>${escapeHtml(response.mensaje)}</p>
        <p><strong>ID:</strong> ${escapeHtml(response.booking_id)}</p>
        <div class="ia-form-actions">
          ${manageButton}
          ${providerButton}
        </div>
      </div>
    `;
    trackWidgetEvent("booking_submitted", {
      booking_id: response.booking_id,
      booking_status: response.estado,
      service: citaData.servicio,
      has_manage_url: !!response.manage_url,
      has_provider_booking_url: !!response.provider_booking_url,
    });
    trackWidgetEvent("booking_confirmed", {
      booking_id: response.booking_id,
      booking_status: response.estado,
      service: citaData.servicio,
      has_manage_url: !!response.manage_url,
      has_provider_booking_url: !!response.provider_booking_url,
    });
    agregarMensaje(response.mensaje, "bot");
  } catch (error) {
    confirmButton.disabled = false;
    confirmButton.textContent = "Confirmar solicitud";
    trackWidgetEvent("booking_submit_error", {
      service: citaData.servicio,
      error_message: error?.message || "unknown",
    });
    const form = document.getElementById("ia-form-cita");
    const message = `${humanizeErrorMessage(
      error,
      "No se ha podido registrar la solicitud."
    )}.${fallbackContacto()}`.trim();
    if (form) {
      form.innerHTML = `
        <div class="ia-form-success ia-form-error">
          <div class="ia-check ia-check-error">!</div>
          <h4>No se ha podido confirmar</h4>
          <p>${escapeHtml(message)}</p>
          <div class="ia-form-actions">
            <button id="ia-f-retry" class="ia-form-btn primary" type="button">Reintentar</button>
          </div>
        </div>
      `;
      document.getElementById("ia-f-retry")?.addEventListener("click", confirmarCita);
    }
    agregarMensaje(message, "bot");
  }
}

export async function mostrarFormulario() {
  if (!WIDGET_CONFIG.bookingEnabled) {
    agregarMensaje("La reserva online no esta habilitada para este cliente.", "bot");
    return;
  }

  if (document.getElementById("ia-form-cita")) {
    agregarMensaje("Ya tienes un formulario de solicitud abierto en la conversacion.", "bot");
    return;
  }

  resetState();
  trackWidgetEvent("booking_form_opened");

  try {
    await cargarServicios();
    await cargarProfesionales();
  } catch (error) {
    trackWidgetEvent("booking_form_error", {
      error_message: error?.message || "unknown",
    });
    agregarMensaje(
      humanizeErrorMessage(error, "No se ha podido cargar el formulario de reserva.") + fallbackContacto(),
      "bot"
    );
    return;
  }

  const msgs = document.getElementById("ia-w-msgs");
  if (!msgs) return;

  const form = document.createElement("div");
  form.className = "ia-form-card";
  form.id = "ia-form-cita";
  form.innerHTML = `
    <div class="ia-form-header">
      <h4>Solicitar cita</h4>
      <p>Recogemos tus datos para que el equipo pueda confirmar la solicitud.</p>
    </div>
    <div class="ia-form-progress">
      <div class="ia-form-step-dot active"></div>
      <div class="ia-form-step-dot"></div>
      <div class="ia-form-step-dot"></div>
      <div class="ia-form-step-dot"></div>
    </div>
    <div class="ia-form-body">
      <div class="ia-form-step active" data-step="0">
        <label class="ia-form-label" for="ia-f-nombre">Nombre completo</label>
        <input id="ia-f-nombre" type="text" autocomplete="name" maxlength="80" />

        <label class="ia-form-label" for="ia-f-email">Email</label>
        <input id="ia-f-email" type="email" autocomplete="email" maxlength="120" />

        <label class="ia-form-label" for="ia-f-tel">Telefono</label>
        <input id="ia-f-tel" type="tel" autocomplete="tel" maxlength="30" />

        <div class="ia-form-actions">
          <button id="ia-f-next0" class="ia-form-btn primary" type="button">Siguiente</button>
        </div>
      </div>

      <div class="ia-form-step" data-step="1">
        <div id="ia-f-employee-wrap" class="hidden">
          <label class="ia-form-label" for="ia-f-employee">Profesional</label>
          <select id="ia-f-employee"></select>
        </div>

        <label class="ia-form-label" for="ia-f-servicio">Servicio</label>
        <select id="ia-f-servicio"></select>

        <label class="ia-form-label" for="ia-f-notas">Notas adicionales</label>
        <textarea id="ia-f-notas" rows="4" maxlength="500" placeholder="Cuentanos un poco mas sobre la consulta"></textarea>

        <p class="ia-form-note">Tus datos se usaran solo para gestionar esta solicitud.</p>

        <div class="ia-form-actions">
          <button id="ia-f-back0" class="ia-form-btn secondary" type="button">Atras</button>
          <button id="ia-f-next1" class="ia-form-btn primary" type="button">Siguiente</button>
        </div>
      </div>

      <div class="ia-form-step" data-step="2">
        <label class="ia-form-label" for="ia-f-fecha">Fecha</label>
        <input id="ia-f-fecha" type="date" />

        <label class="ia-form-label">Horarios disponibles</label>
        <div id="ia-time-slots"></div>

        <div class="ia-form-actions">
          <button id="ia-f-back1" class="ia-form-btn secondary" type="button">Atras</button>
          <button id="ia-f-next2" class="ia-form-btn primary" type="button" disabled>Siguiente</button>
        </div>
      </div>

      <div class="ia-form-step" data-step="3">
        <label class="ia-form-label">Resumen de la solicitud</label>
        <div id="ia-resumen" class="ia-resumen"></div>

        <div class="ia-form-actions">
          <button id="ia-f-back2" class="ia-form-btn secondary" type="button">Atras</button>
          <button id="ia-f-confirm" class="ia-form-btn primary" type="button">Confirmar solicitud</button>
        </div>
      </div>
    </div>
  `;

  msgs.appendChild(form);
  bringFormIntoView(form, "auto");

  const serviceSelect = document.getElementById("ia-f-servicio");
  const employeeSelect = document.getElementById("ia-f-employee");
  const employeeWrap = document.getElementById("ia-f-employee-wrap");
  fillEmployeeOptions(employeeSelect, employeeWrap);
  fillServiceOptions(serviceSelect);
  citaData.servicio = serviceSelect && !serviceSelect.disabled
    ? (serviceSelect.options[0]?.textContent || "Consulta general")
    : "";

  const dateInput = document.getElementById("ia-f-fecha");
  const today = new Date();
  dateInput.min = formatLocalDate(today);

  const maxDate = new Date();
  maxDate.setDate(maxDate.getDate() + MAX_WIDGET_BOOKING_DAYS);
  dateInput.max = formatLocalDate(maxDate);

  ["ia-f-nombre", "ia-f-email", "ia-f-tel", "ia-f-servicio", "ia-f-fecha", "ia-f-employee"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => clearFieldError(id));
    document.getElementById(id)?.addEventListener("change", () => clearFieldError(id));
  });

  document.getElementById("ia-f-next0")?.addEventListener("click", () => {
    const isValid =
      validateField("ia-f-nombre", "nombre") &&
      validateField("ia-f-email", "email") &&
      validateField("ia-f-tel", "telefono");

    if (!isValid) return;

    citaData.nombre = document.getElementById("ia-f-nombre").value.trim();
    citaData.email = document.getElementById("ia-f-email").value.trim();
    citaData.telefono = document.getElementById("ia-f-tel").value.trim();
    toggleStep(1);
  });

  document.getElementById("ia-f-next1")?.addEventListener("click", () => {
    if (employees.length > 1) {
      const selectedEmployee = employees.find((employee) => employee.employee_id === employeeSelect?.value);
      clearFieldError("ia-f-employee");
      citaData.employeeId = selectedEmployee?.employee_id || "";
      citaData.employeeName = selectedEmployee?.name || "Aleatorio";
    }

    const selectedOption = serviceSelect?.options[serviceSelect.selectedIndex];
    if (!selectedOption || serviceSelect?.disabled) {
      setFieldError(
        "ia-f-servicio",
        citaData.employeeId
          ? "Este profesional no tiene servicios disponibles."
          : "No hay servicios disponibles para esta solicitud."
      );
      return;
    }

    clearFieldError("ia-f-servicio");
    citaData.servicio = selectedOption.textContent || "Consulta general";
    citaData.notas = document.getElementById("ia-f-notas").value.trim();
    toggleStep(2);
  });

  employeeSelect?.addEventListener("change", () => {
    const selectedEmployee = employees.find((employee) => employee.employee_id === employeeSelect.value);
    citaData.employeeId = selectedEmployee?.employee_id || "";
    citaData.employeeName = selectedEmployee?.name || "Aleatorio";
    fillServiceOptions(serviceSelect);
    citaData.servicio = serviceSelect && !serviceSelect.disabled
      ? (serviceSelect.options[serviceSelect.selectedIndex]?.textContent || "")
      : "";
    citaData.fecha = "";
    citaData.hora = "";
    if (dateInput) dateInput.value = "";
    const slots = document.getElementById("ia-time-slots");
    if (slots) slots.innerHTML = "";
    document.getElementById("ia-f-next2")?.setAttribute("disabled", "disabled");
  });

  dateInput?.addEventListener("change", async (event) => {
    const fecha = event.target.value;
    const error = validaciones.fecha(fecha);
    if (error) {
      setFieldError("ia-f-fecha", error);
      return;
    }

    clearFieldError("ia-f-fecha");
    citaData.fecha = fecha;
    citaData.hora = "";
    await cargarSlots(fecha);
  });

  serviceSelect?.addEventListener("change", () => {
    const selectedOption = serviceSelect.options[serviceSelect.selectedIndex];
    citaData.servicio = selectedOption?.textContent || "";
  });

  document.getElementById("ia-f-next2")?.addEventListener("click", () => {
    const error = validaciones.hora(citaData.hora);
    if (error) {
      agregarMensaje(error, "bot");
      return;
    }

    renderResumen();
    toggleStep(3);
  });

  document.getElementById("ia-f-confirm")?.addEventListener("click", confirmarCita);
  document.getElementById("ia-f-back0")?.addEventListener("click", () => toggleStep(0));
  document.getElementById("ia-f-back1")?.addEventListener("click", () => toggleStep(1));
  document.getElementById("ia-f-back2")?.addEventListener("click", () => toggleStep(2));

  scrollMsgs();
}
