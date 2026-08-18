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
let locations = [];
let effectiveLocationId = "";
let slotsDisponibles = [];
let slotsRequestSeq = 0;
let loadedSlotsKey = "";

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
  locations = [];
  // Centro fijado por el snippet (data-location) o, si no, el que elija el cliente.
  effectiveLocationId = WIDGET_CONFIG.locationId || "";
  slotsDisponibles = [];
}

async function cargarCentros() {
  // Solo necesitamos elegir centro si el negocio tiene >1 y el snippet no fija uno.
  if (WIDGET_CONFIG.locationId) { locations = []; return; }
  try {
    const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/centros/${WIDGET_CONFIG.clienteId}`);
    locations = Array.isArray(data.items) ? data.items : [];
  } catch (_) {
    locations = [];
  }
  if (locations.length > 1 && !effectiveLocationId) {
    effectiveLocationId = locations[0].location_id; // por defecto el primero; el cliente puede cambiarlo
  }
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
    if (!valor) return "";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(valor)) return "El email no es valido.";
    return "";
  },
  telefono(valor) {
    if (!valor) return "";
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

function validateReminderContact(emailInputId, phoneInputId) {
  const email = document.getElementById(emailInputId)?.value.trim() || "";
  const telefono = document.getElementById(phoneInputId)?.value.trim() || "";
  const emailOk = validateField(emailInputId, "email");
  const phoneOk = validateField(phoneInputId, "telefono");
  if (!emailOk || !phoneOk) return false;
  if (!email && !telefono) {
    const message = "Indica al menos email o telefono para enviarte confirmaciones y recordatorios.";
    setFieldError(emailInputId, message);
    setFieldError(phoneInputId, message);
    return false;
  }
  return true;
}

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
  const qs = effectiveLocationId
    ? `?location_id=${encodeURIComponent(effectiveLocationId)}`
    : "";
  const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/servicios/${WIDGET_CONFIG.clienteId}${qs}`);
  services = Array.isArray(data.servicios) ? data.servicios : [];

  if (!services.length) {
    services = [{ id: "consulta_general", nombre: "Consulta general" }];
  }
}

async function cargarProfesionales() {
  const qs = effectiveLocationId
    ? `?location_id=${encodeURIComponent(effectiveLocationId)}`
    : "";
  const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/profesionales/${WIDGET_CONFIG.clienteId}${qs}`);
  employees = (Array.isArray(data.items) ? data.items : []).filter(e => !e.is_default);
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

  // Con catalogos largos (un salon real tiene 185 servicios) una lista plana no hay
  // quien la lea: se agrupa por categoria. Sin categorias queda igual que antes.
  const usaCategorias = scopedServices.some((service) => (service.category || "").trim());
  const destinos = new Map();
  const destinoDe = (service) => {
    if (!usaCategorias) return select;
    const clave = (service.category || "").trim() || "Otros";
    if (!destinos.has(clave)) {
      const grupo = document.createElement("optgroup");
      grupo.label = clave;
      select.appendChild(grupo);
      destinos.set(clave, grupo);
    }
    return destinos.get(clave);
  };

  scopedServices.forEach((service) => {
    const option = document.createElement("option");
    option.value = service.id;
    option.dataset.nombre = service.nombre;
    const bits = [];
    if (service.duration_minutes) bits.push(`${service.duration_minutes} min`);
    if (service.price_label) bits.push(service.price_label);
    option.textContent = bits.length ? `${service.nombre} · ${bits.join(" · ")}` : service.nombre;
    destinoDe(service).appendChild(option);
  });
}

function _selectedServiceName(select, index) {
  const opt = select && select.options[index === undefined ? select.selectedIndex : index];
  if (!opt) return "";
  return opt.dataset.nombre || opt.textContent || "";
}

function _slotsKey(fecha, servicio, employeeId) {
  return [
    String(fecha || ""),
    String(servicio || ""),
    String(employeeId || ""),
  ].join("|");
}

function invalidateSlots(message = "") {
  slotsRequestSeq += 1;
  loadedSlotsKey = "";
  slotsDisponibles = [];
  citaData.hora = "";

  const nextButton = document.getElementById("ia-f-next2");
  if (nextButton) nextButton.disabled = true;

  const container = document.getElementById("ia-time-slots");
  if (container) {
    container.innerHTML = message
      ? `<div class="ia-empty-slots">${escapeHtml(message)}</div>`
      : "";
  }
}

function fillEmployeeOptions(select, wrap) {
  if (!select || !wrap) return;

  if (!employees.length) {
    wrap.classList.add("hidden");
    citaData.employeeId = "";
    citaData.employeeName = "";
    return;
  }

  wrap.classList.remove("hidden");

  if (employees.length === 1) {
    // Un solo profesional: preseleccionado, sin opción "Aleatorio"
    const emp = employees[0];
    select.innerHTML = "";
    const option = document.createElement("option");
    option.value = emp.employee_id;
    option.textContent = emp.role_label ? `${emp.name} - ${emp.role_label}` : emp.name;
    option.selected = true;
    select.appendChild(option);
    citaData.employeeId = emp.employee_id;
    citaData.employeeName = emp.name;
    return;
  }

  // 2+ profesionales: selector libre con opción "Sin preferencia"
  select.innerHTML = '<option value="">Sin preferencia</option>';
  employees.forEach((employee) => {
    const option = document.createElement("option");
    option.value = employee.employee_id;
    option.textContent = employee.role_label
      ? `${employee.name} - ${employee.role_label}`
      : employee.name;
    select.appendChild(option);
  });
  citaData.employeeId = "";
  citaData.employeeName = "Sin preferencia";
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

  const requestId = ++slotsRequestSeq;
  const requestService = citaData.servicio;
  const requestEmployeeId = citaData.employeeId;
  const requestKey = _slotsKey(fecha, requestService, requestEmployeeId);

  loadedSlotsKey = "";
  slotsDisponibles = [];
  citaData.hora = "";
  nextButton.disabled = true;
  container.innerHTML =
    '<div class="ia-loading-slots"><span class="ia-spinner"></span><div>Consultando disponibilidad...</div></div>';

  try {
    const params = new URLSearchParams({
      cliente_id: WIDGET_CONFIG.clienteId,
      fecha,
    });
    if (requestEmployeeId) params.set("employee_id", requestEmployeeId);
    if (requestService) params.set("servicio", requestService);
    if (effectiveLocationId) params.set("location_id", effectiveLocationId);
    const data = await fetchJson(`${WIDGET_CONFIG.apiUrl}/disponibilidad?${params.toString()}`);
    if (
      requestId !== slotsRequestSeq ||
      requestKey !== _slotsKey(citaData.fecha, citaData.servicio, citaData.employeeId)
    ) {
      return;
    }
    slotsDisponibles = Array.isArray(data.slots) ? data.slots : [];
    loadedSlotsKey = requestKey;
    renderSlots();
  } catch (error) {
    if (
      requestId !== slotsRequestSeq ||
      requestKey !== _slotsKey(citaData.fecha, citaData.servicio, citaData.employeeId)
    ) {
      return;
    }
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
        location_id: effectiveLocationId,
        fecha: citaData.fecha,
        hora: citaData.hora,
        notas: citaData.notas,
      }),
    });

    const form = document.getElementById("ia-form-cita");
    if (!form) return;

    // Servicio con senal o pago previo: la cita nace "pending_payment" y el hueco
    // solo queda guardado un rato. Sin ensenar aqui el enlace, el cliente cree que
    // ha reservado, no recibe email (se bloquea hasta que pague) y la reserva se
    // cae sola. Mismo texto que la central publica y que WhatsApp.
    const pendingPayment =
      response.estado === "pending_payment" || response.payment_status === "pending";
    const title = pendingPayment
      ? "Reserva pendiente de pago"
      : response.estado === "pending_review"
      ? "Solicitud recibida"
      : "Solicitud registrada";
    const successText = pendingPayment
      ? "Hemos guardado el hueco de forma provisional. Completa el pago para confirmar la cita."
      : response.mensaje;
    const payButton = response.payment_url
      ? `<a class="ia-form-btn" href="${escapeHtml(response.payment_url)}" target="_blank" rel="noreferrer">${
          pendingPayment ? "Completar pago para confirmar" : "Completar pago"
        }</a>`
      : "";
    const manageButton = response.manage_url
      ? `<a class="ia-form-btn secondary" href="${escapeHtml(response.manage_url)}" target="_blank" rel="noreferrer">Gestionar cita</a>`
      : "";
    const providerButton = response.provider_booking_url
      ? `<a class="ia-form-btn secondary" href="${escapeHtml(response.provider_booking_url)}" target="_blank" rel="noreferrer">Abrir proveedor</a>`
      : "";
    form.innerHTML = `
      <div class="ia-form-success">
        <div class="ia-check">${response.estado === "pending_review" || pendingPayment ? "!" : "OK"}</div>
        <h4>${escapeHtml(title)}</h4>
        <p>${escapeHtml(successText)}</p>
        ${response.booking_code && !pendingPayment
          ? `<p><strong>Numero de reserva:</strong> ${escapeHtml(response.booking_code)}</p>`
          : ""}
        <div class="ia-form-actions">
          ${payButton}
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
    // Un solo aviso: la tarjeta de arriba ya lleva el texto y los botones de pagar
    // y gestionar. Repetirlo en el chat con la URL entera de Stripe (~300
    // caracteres) solo estorbaba.
    if (!pendingPayment) agregarMensaje(successText, "bot");
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
    await cargarCentros();
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
  // Selector de centro: solo si el negocio tiene >1 centro y el snippet no fija uno.
  const showCenters = locations.length > 1;
  const centerPickerHtml = showCenters
    ? `<label class="ia-form-label" for="ia-f-centro">Centro</label>
        <select id="ia-f-centro">${locations
          .map((loc) => `<option value="${escapeHtml(loc.location_id)}"${loc.location_id === effectiveLocationId ? " selected" : ""}>${escapeHtml(loc.name)}</option>`)
          .join("")}</select>`
    : "";
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
        <p class="ia-form-note">Indica email o telefono para recibir confirmaciones y recordatorios.</p>

        <div class="ia-form-actions">
          <button id="ia-f-next0" class="ia-form-btn primary" type="button">Siguiente</button>
        </div>
      </div>

      <div class="ia-form-step" data-step="1">
        ${centerPickerHtml}
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
    ? (_selectedServiceName(serviceSelect, 0) || "Consulta general")
    : "";

  // Cambiar de centro recarga profesionales y servicios de ESE centro.
  if (showCenters) {
    document.getElementById("ia-f-centro")?.addEventListener("change", async (event) => {
      effectiveLocationId = event.target.value || "";
      try {
        await cargarServicios();
        await cargarProfesionales();
      } catch (_) {}
      fillEmployeeOptions(employeeSelect, employeeWrap);
      fillServiceOptions(serviceSelect);
      citaData.servicio = serviceSelect && !serviceSelect.disabled
        ? (_selectedServiceName(serviceSelect, serviceSelect.selectedIndex >= 0 ? serviceSelect.selectedIndex : 0) || "")
        : "";
      invalidateSlots();
    });
  }

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
      validateReminderContact("ia-f-email", "ia-f-tel");

    if (!isValid) return;

    citaData.nombre = document.getElementById("ia-f-nombre").value.trim();
    citaData.email = document.getElementById("ia-f-email").value.trim();
    citaData.telefono = document.getElementById("ia-f-tel").value.trim();
    toggleStep(1);
  });

  document.getElementById("ia-f-next1")?.addEventListener("click", async () => {
    const previousSlotsKey = loadedSlotsKey;
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
    citaData.servicio = _selectedServiceName(serviceSelect) || "Consulta general";
    citaData.notas = document.getElementById("ia-f-notas").value.trim();
    toggleStep(2);

    const selectedDate = dateInput?.value || "";
    if (selectedDate) {
      citaData.fecha = selectedDate;
      const nextSlotsKey = _slotsKey(citaData.fecha, citaData.servicio, citaData.employeeId);
      if (previousSlotsKey !== nextSlotsKey || loadedSlotsKey !== nextSlotsKey) {
        await cargarSlots(citaData.fecha);
      }
    }
  });

  employeeSelect?.addEventListener("change", () => {
    const selectedEmployee = employees.find((employee) => employee.employee_id === employeeSelect.value);
    citaData.employeeId = selectedEmployee?.employee_id || "";
    citaData.employeeName = selectedEmployee?.name || "Aleatorio";
    fillServiceOptions(serviceSelect);
    citaData.servicio = serviceSelect && !serviceSelect.disabled
      ? _selectedServiceName(serviceSelect)
      : "";
    citaData.fecha = "";
    if (dateInput) dateInput.value = "";
    invalidateSlots();
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
    const nextService = _selectedServiceName(serviceSelect);
    if (nextService !== citaData.servicio) {
      citaData.servicio = nextService;
      invalidateSlots(citaData.fecha ? "Pulsa Siguiente para actualizar los horarios de este servicio." : "");
    }
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
