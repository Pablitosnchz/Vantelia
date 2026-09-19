// node --experimental-vm-modules --test tests/test_widget_atencion.cjs
// Ejecuta los módulos reales con DOM mínimo, fetch interceptado y formulario espía.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function matches(node, selector) {
  const tag = selector.match(/^[a-z]+/i)?.[0];
  const id = selector.match(/#([\w-]+)/)?.[1];
  const classes = [...selector.matchAll(/\.([\w-]+)/g)].map((m) => m[1]);
  const attr = selector.match(/\[([\w-]+)\]/)?.[1];
  return (!tag || node.tagName === tag.toUpperCase()) && (!id || node.id === id) &&
    classes.every((name) => node.className.split(" ").includes(name)) &&
    (!attr || node.getAttribute(attr) !== null);
}

class Element {
  constructor(tagName) {
    Object.assign(this, { tagName: tagName.toUpperCase(), id: "", className: "", children: [],
      parentNode: null, attributes: new Map(), textContent: "", disabled: false,
      dataset: {}, value: "", listeners: new Map(), offsetTop: 0 });
    this.classList = {
      add: (...names) => { this.className = [...new Set([...this.className.split(" "), ...names])].join(" ").trim(); },
      remove: (...names) => { this.className = this.className.split(" ").filter(n => !names.includes(n)).join(" "); },
    };
  }
  set innerHTML(html) {
    this._html = html; this.children = [];
    const stack = [this];
    for (const token of html.matchAll(/<\/?[a-z][^>]*>|[^<]+/gi)) {
      const text = token[0];
      if (text.startsWith("</")) { if (stack.length > 1) stack.pop(); continue; }
      if (!text.startsWith("<")) { stack.at(-1).textContent += text; continue; }
      const tag = text.match(/^<([\w-]+)/)[1];
      const node = new Element(tag);
      for (const attr of text.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
        const [, name, value = ""] = attr;
        node.setAttribute(name, value);
        if (name === "id" || name === "value") node[name] = value;
        if (name === "class") node.className = value;
        if (name === "disabled" || name === "selected") node[name] = true;
        if (name.startsWith("data-")) node.dataset[name.slice(5)] = value;
      }
      stack.at(-1).appendChild(node);
      if (!["input", "br", "hr", "img", "meta", "link"].includes(tag)) stack.push(node);
    }
  }
  get innerHTML() { return this._html || ""; }
  get options() { return this.querySelectorAll("option"); }
  get selectedIndex() { const index = this.options.findIndex(o => o.selected || (this.value && o.value === this.value)); return index >= 0 ? index : 0; }
  appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
  insertBefore(node, sibling) {
    node.parentNode = this;
    this.children.splice(this.children.indexOf(sibling), 0, node);
    return node;
  }
  remove() {
    if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1);
    this.parentNode = null;
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  async emit(type) { await Promise.all((this.listeners.get(type) || []).map(fn => fn({ target: this }))); }
  scrollTo() {}
  focus() { this.focused = true; }
  contains(node) { return this === node || this.children.some((child) => child.contains(node)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const all = this.children.flatMap((child) => [child, ...child.querySelectorAll("*")]);
    return all.filter((node) => selector.split(",").some((part) => {
      const tokens = part.trim().split(/\s+/);
      if (!matches(node, tokens.pop())) return false;
      let ancestor = node.parentNode;
      while (tokens.length) {
        const token = tokens.pop();
        while (ancestor && !matches(ancestor, token)) ancestor = ancestor.parentNode;
        if (!ancestor) return false;
        ancestor = ancestor.parentNode;
      }
      return true;
    }));
  }
}

async function harness({ realForm = false } = {}) {
  // Reloj de la simulación, independiente del día en que corra CI. Conserva
  // Date() callable, new Date(argumentos), parse/UTC y Date.now coherentes.
  const fixedNow = Date.parse("2026-09-19T12:00:00.000Z");
  function FixtureDate(...args) {
    if (!new.target) return new Date(fixedNow).toString();
    return Reflect.construct(Date, args.length ? args : [fixedNow], new.target);
  }
  Object.setPrototypeOf(FixtureDate, Date);
  FixtureDate.prototype = Object.create(Date.prototype, { constructor: { value: FixtureDate } });
  FixtureDate.now = () => fixedNow;
  const body = new Element("body");
  const events = [], requests = [], responses = [], timers = new Map();
  let formCalls = 0, timerId = 0;
  const document = {
    body, currentScript: { dataset: {}, src: "https://widget.test/widget.js" },
    createElement: (tag) => new Element(tag),
    getElementById: (id) => body.querySelectorAll(`#${id}`)[0] || null,
    querySelectorAll: (selector) => body.querySelectorAll(selector),
    dispatchEvent: (event) => events.push(event.detail),
  };
  const element = (tag, id, parent = body) => {
    const node = new Element(tag); node.id = id; parent.appendChild(node); return node;
  };
  const panel = element("section", "ia-w-window");
  const msgs = element("div", "ia-w-msgs", panel);
  const area = element("div", "ia-w-input-area", panel);
  const input = element("input", "ia-w-input", area);
  const send = element("button", "ia-w-send", area);
  input.value = "";
  const previous = element("div", "", msgs); previous.className = "ia-msg bot";
  previous.textContent = "Respuesta anterior";
  const actions = element("div", "", msgs); actions.className = "ia-action-card";
  const quick = element("button", "", actions); quick.setAttribute("data-quick-message", "Reservar");
  const form = element("div", "ia-form-cita", msgs); form.className = "ia-form-card";
  const field = element("input", "", form);
  const alreadyDisabled = element("button", "", form); alreadyDisabled.disabled = true;
  const contact = element("a", "", form); contact.setAttribute("href", "tel:+34900000000");
  const storage = new Map();
  const window = {
    location: { href: "https://widget.test/", origin: "https://widget.test" },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key) },
    requestAnimationFrame: (callback) => callback(),
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
  };
  const context = vm.createContext({ document, window, URL, URLSearchParams, AbortController, Date: FixtureDate,
    CustomEvent: class { constructor(_name, options) { this.detail = options.detail; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      assert.ok(responses.length, "Ninguna llamada adicional tiene respuesta autorizada");
      const response = await responses.shift();
      return { status: response.status, ok: response.status < 400,
        text: async () => JSON.stringify(response.body) };
    },
  });
  const root = path.resolve(__dirname, "..");
  const utils = new vm.SourceTextModule(await fs.readFile(path.join(root, "widget/utils.js"), "utf8"), { context });
  const formModule = realForm
    ? new vm.SourceTextModule(await fs.readFile(path.join(root, "widget/form.js"), "utf8"), { context })
    : new vm.SyntheticModule(["mostrarFormulario"], function () {
    this.setExport("mostrarFormulario", () => { formCalls += 1; });
  }, { context });
  const chat = new vm.SourceTextModule(await fs.readFile(path.join(root, "widget/chat.js"), "utf8"), { context });
  const modules = { "./utils.js": utils, "./form.js": formModule, "./chat.js": chat };
  // Cargar módulos reales añadidos al widget, sin falsear su estado compartido.
  await chat.link(async (specifier) => {
    if (!modules[specifier]) modules[specifier] = fs.readFile(path.join(root, "widget", specifier), "utf8")
      .then(source => new vm.SourceTextModule(source, { context }));
    return modules[specifier];
  });
  await chat.evaluate();
  utils.namespace.WIDGET_CONFIG.bookingEnabled = true;
  if (realForm) form.remove();
  return { document, events, requests, responses, timers, msgs, input, send, quick, field, contact,
    alreadyDisabled, chat: chat.namespace, utils: utils.namespace, form: formModule.namespace,
    element, formCalls: () => formCalls };
}

const attentionStates = [
  [409, "ATTENTION_STOPPED", "La atención automática está pausada."],
  [503, "ATTENTION_UNAVAILABLE", "No se puede comprobar la atención automática."],
];

test("fetchJson conserva status, code y detail estructurado", async () => {
  const h = await harness();
  for (const [status, code, message] of attentionStates) {
    h.responses.push({ status, body: { detail: { code, message } } });
    await assert.rejects(h.utils.fetchJson("https://widget.test/chat"), (error) => {
      assert.equal(error.status, status); assert.equal(error.code, code);
      assert.equal(error.detail.code, code); assert.equal(error.detail.message, message);
      assert.equal(h.utils.humanizeErrorMessage(error), message);
      return true;
    });
  }
});

test("humanize nunca convierte un objeto en texto al cliente", async () => {
  const h = await harness();
  assert.equal(h.utils.humanizeErrorMessage({ message: { code: "OTRO" } }, "Alternativa"), "Alternativa");
  assert.equal(h.utils.humanizeErrorMessage({ message: "[object Object]" }, "Alternativa"), "Alternativa");
});

for (const [status, code, message] of attentionStates) {
  test(`${code}: estado accesible sin respuesta ni acciones; recuperación solo tras respuesta válida`, async () => {
    const h = await harness();
    h.responses.push({ status, body: { detail: { code, message }, respuesta: "No debe mostrarse",
      mostrar_formulario: true, quick_actions: [{ label: "Reservar", message: "Reserva" }] } });
    await h.chat.enviarMensaje("Necesito una cita");
    const notice = h.document.getElementById("ia-w-atencion-status");
    assert.ok(notice, "Debe existir un aviso de interfaz");
    assert.equal(h.msgs.contains(notice), false);
    assert.equal(notice.getAttribute("role"), "status");
    assert.equal(notice.getAttribute("aria-live"), "polite");
    assert.equal(notice.textContent, message);
    assert.equal(notice.children.length, 0);
    assert.equal(h.msgs.querySelectorAll(".ia-msg.user")[0].textContent, "Necesito una cita");
    assert.equal(h.msgs.querySelectorAll(".ia-msg.bot").length, 1);
    assert.equal(h.msgs.querySelectorAll(".ia-action-card").length, 1);
    assert.equal(h.formCalls(), 0);
    assert.equal(h.events.filter((e) => e.event === "widget_message_response").length, 0);
    assert.equal(h.document.getElementById("ia-w-typing"), null);
    assert.equal(h.input.disabled, false); assert.equal(h.send.disabled, false); assert.equal(h.input.focused, true);
    assert.equal(h.quick.disabled, true); assert.equal(h.field.disabled, true);
    assert.equal(h.contact.getAttribute("href"), "tel:+34900000000");
    assert.equal(h.contact.disabled, false);
    assert.equal(h.requests.length, 1); assert.equal(h.timers.size, 0);

    h.responses.push({ status: 500, body: { detail: "Otro fallo" } });
    await h.chat.enviarMensaje("Otro intento manual");
    assert.equal(h.quick.disabled, true); assert.equal(h.field.disabled, true);
    h.responses.push({ status: 200, body: { session_id: "sesion", respuesta: "Ya puedo atenderte" } });
    await h.chat.enviarMensaje("Nuevo mensaje manual");
    assert.equal(h.document.getElementById("ia-w-atencion-status").textContent, "");
    assert.equal(h.quick.disabled, false); assert.equal(h.field.disabled, false);
    assert.equal(h.alreadyDisabled.disabled, true);
    assert.equal(h.events.filter((e) => e.event === "widget_message_response").length, 1);
    assert.equal(h.requests.length, 3); assert.equal(h.timers.size, 0);
  });
}

for (const [status, detail] of [[409, "Horario ocupado"], [503, { code: "OTHER", message: "Otro fallo" }],
  [409, { code: "ATTENTION_UNAVAILABLE", message: "Código sin su estado HTTP" }]]) {
  test(`error ajeno ${status}/${typeof detail === "string" ? detail : detail.code}: conserva su conducta`, async () => {
    const h = await harness();
    h.responses.push({ status, body: { detail } });
    await h.chat.enviarMensaje("Mensaje");
    const bots = h.msgs.querySelectorAll(".ia-msg.bot");
    assert.equal(bots.length, 2);
    assert.match(bots[1].innerHTML, /consulta gratuita/);
    assert.doesNotMatch(bots[1].innerHTML, /\[object Object\]/);
    assert.equal(h.quick.disabled, false); assert.equal(h.field.disabled, false);
    assert.equal(h.input.disabled, false); assert.equal(h.send.disabled, false);
    assert.equal(h.formCalls(), 0); assert.equal(h.requests.length, 1);
  });
}

function deferredResponse() {
  let resolve;
  const response = new Promise(done => { resolve = done; });
  return { response, resolve: (body, status = 200) => resolve({ status, body }) };
}

function catalogResponses(h, employees = []) {
  h.responses.push({ status: 200, body: { servicios: [{ id: "corte", nombre: "Corte" }] } },
    { status: 200, body: { items: employees } });
}

async function openRealForm(h, employees = []) {
  h.responses.push({ status: 200, body: { items: [
    { location_id: "centro_a", name: "Centro A" }, { location_id: "centro_b", name: "Centro B" },
  ] } });
  catalogResponses(h, employees);
  await h.form.mostrarFormulario();
  assert.ok(h.document.getElementById("ia-form-cita"));
}

async function stopAttention(h, status, code, message) {
  h.responses.push({ status, body: { detail: { code, message } } });
  await h.chat.enviarMensaje("¿Seguís ahí?");
}

function assertFormStopped(h) {
  const controls = h.document.querySelectorAll(
    "#ia-form-cita input, #ia-form-cita button, #ia-form-cita select, #ia-form-cita textarea");
  assert.ok(controls.every(node => node.disabled), "Ningún control tardío puede quedar habilitado");
}

for (const [status, code, message] of attentionStates) {
  test(`${code}: formulario real pendiente de centros no aparece habilitado tras el corte`, async () => {
    const h = await harness({ realForm: true });
    const centers = deferredResponse();
    h.responses.push(centers.response);
    const pending = h.form.mostrarFormulario();
    await stopAttention(h, status, code, message);
    catalogResponses(h);
    centers.resolve({ items: [] });
    await pending;
    assertFormStopped(h);
    assert.equal(h.document.getElementById("ia-w-atencion-status").textContent, message);
  });
}

test("una respuesta válida posterior no revive una apertura anterior a la pausa", async () => {
  const h = await harness({ realForm: true });
  const centers = deferredResponse();
  h.responses.push(centers.response);
  const pending = h.form.mostrarFormulario();
  await stopAttention(h, ...attentionStates[0]);
  h.responses.push({ status: 200, body: { respuesta: "Ahora puedo atenderte" } });
  await h.chat.enviarMensaje("Nuevo intento");
  catalogResponses(h);
  centers.resolve({ items: [] });
  await pending;
  assert.equal(h.document.getElementById("ia-form-cita"), null,
    "La recuperación no autoriza la preparación antigua");
  h.responses.length = 0;
  await openRealForm(h);
  assert.equal(h.document.getElementById("ia-f-nombre").disabled, false);
});

test("recarga de centro tardía conserva datos y disabled anterior al corte", async () => {
  const h = await harness({ realForm: true });
  await openRealForm(h);
  const name = h.document.getElementById("ia-f-nombre"); name.value = "Ana García";
  const phone = h.document.getElementById("ia-f-tel"); phone.value = "+34900000000";
  const next = h.document.getElementById("ia-f-next2"); assert.equal(next.disabled, true);
  const contact = h.element("a", "human-contact", h.document.getElementById("ia-form-cita"));
  contact.setAttribute("href", "tel:+34900000000");
  const services = deferredResponse(); h.responses.push(services.response);
  const center = h.document.getElementById("ia-f-centro"); center.value = "centro_b";
  const pending = center.emit("change");
  await stopAttention(h, ...attentionStates[1]);
  h.responses.push({ status: 200, body: { items: [] } });
  services.resolve({ servicios: [{ id: "otro", nombre: "Otro" }] });
  await pending;
  assertFormStopped(h);
  assert.equal(name.value, "Ana García"); assert.equal(phone.value, "+34900000000");
  assert.equal(contact.getAttribute("href"), "tel:+34900000000");
  assert.equal(contact.disabled, false);
  h.responses.length = 0;
  h.responses.push({ status: 200, body: { respuesta: "Seguimos" } });
  await h.chat.enviarMensaje("Nuevo mensaje");
  assert.equal(name.disabled, false); assert.equal(next.disabled, true);
  assert.equal(name.value, "Ana García");
});

test("disponibilidad tardía no añade horarios ni acepta eventos de formulario bloqueado", async () => {
  const h = await harness({ realForm: true });
  await openRealForm(h);
  const slots = deferredResponse(); h.responses.push(slots.response);
  const date = h.document.getElementById("ia-f-fecha"); date.value = "2026-09-25";
  const pending = date.emit("change");
  await stopAttention(h, ...attentionStates[0]);
  slots.resolve({ slots: [{ hora: "10:00", disponible: true }] });
  await pending;
  assertFormStopped(h);
  assert.equal(h.document.querySelectorAll(".ia-time-slot").length, 0);
  const requests = h.requests.length;
  await date.emit("change");
  await h.document.getElementById("ia-f-confirm").emit("click");
  assert.equal(h.requests.length, requests, "No admite nuevas consultas ni /agendar durante el corte");
});

test("un 200 sin respuesta válida no borra el corte ni crea acciones o formularios", async () => {
  const h = await harness();
  await stopAttention(h, ...attentionStates[0]);
  h.responses.push({ status: 200, body: { respuesta: " ", mostrar_formulario: true,
    quick_actions: [{ label: "Reservar", message: "Reserva" }] } });
  await h.chat.enviarMensaje("Prueba manual");
  assert.equal(h.document.getElementById("ia-w-atencion-status").textContent, attentionStates[0][2]);
  assert.equal(h.formCalls(), 0);
  assert.equal(h.msgs.querySelectorAll(".ia-action-card").length, 1);
});

test("/agendar en vuelo conserva resultado conocido y el aviso de pausa", async () => {
  const h = await harness({ realForm: true });
  await openRealForm(h);
  const booking = deferredResponse(); h.responses.push(booking.response);
  const pending = h.document.getElementById("ia-f-confirm").emit("click");
  await stopAttention(h, ...attentionStates[0]);
  booking.resolve({ estado: "confirmed", mensaje: "Tu cita está registrada", booking_id: "bk_prueba",
    booking_code: "R-PRUEBA", manage_url: "https://widget.test/gestion" });
  await pending;
  assert.match(h.document.getElementById("ia-form-cita").innerHTML, /R-PRUEBA/);
  assert.equal(h.document.getElementById("ia-w-atencion-status").textContent, attentionStates[0][2]);
  assert.equal(h.requests.filter(r => r.url.endsWith("/agendar")).length, 1);
});

test("fallo de /agendar en vuelo no habilita reintento ni convierte incertidumbre en cancelación", async () => {
  const h = await harness({ realForm: true });
  await openRealForm(h);
  const name = h.document.getElementById("ia-f-nombre"); name.value = "Ana García";
  const booking = deferredResponse(); h.responses.push(booking.response);
  const pending = h.document.getElementById("ia-f-confirm").emit("click");
  await stopAttention(h, ...attentionStates[0]);
  booking.resolve({ detail: "No se recibió el resultado del proveedor" }, 503);
  await pending;
  assertFormStopped(h);
  assert.equal(h.document.getElementById("ia-f-nombre"), name);
  assert.equal(name.value, "Ana García");
  assert.equal(h.document.getElementById("ia-w-atencion-status").textContent, attentionStates[0][2]);
  assert.equal(h.events.filter(e => e.event === "booking_confirmed").length, 0);
  assert.equal(h.requests.filter(r => r.url.endsWith("/agendar")).length, 1);
});

test("recuperar centro B interrumpido no envía catálogo A y permite completar B explícitamente", async () => {
  const h = await harness({ realForm: true });
  await openRealForm(h, [{ employee_id: "persona_a", name: "Profesional A", allows_all_services: true }]);
  const name = h.document.getElementById("ia-f-nombre"); name.value = "Ana García";
  const phone = h.document.getElementById("ia-f-tel"); phone.value = "+34900000000";
  const professionals = deferredResponse();
  h.responses.push({ status: 200, body: { servicios: [{ id: "otro", nombre: "Servicio B" }] } },
    professionals.response);
  const center = h.document.getElementById("ia-f-centro"); center.value = "centro_b";
  const pending = center.emit("change");
  await new Promise(setImmediate);
  assert.ok(h.requests.some(r => r.url.includes("/profesionales/") && r.url.includes("centro_b")),
    "La pausa ocurre después de servicios B y durante profesionales B");
  await stopAttention(h, ...attentionStates[0]);
  professionals.resolve({ items: [] });
  await pending;
  h.responses.push({ status: 200, body: { respuesta: "Seguimos" } });
  await h.chat.enviarMensaje("Nuevo mensaje");
  await h.document.getElementById("ia-f-next0").emit("click");
  await h.document.getElementById("ia-f-next1").emit("click");
  h.responses.push({ status: 200, body: { slots: [{ hora: "10:00", disponible: true }] } });
  const date = h.document.getElementById("ia-f-fecha"); date.value = "2026-09-25";
  await date.emit("change");
  assert.equal(h.requests.filter(r => r.url.includes("/disponibilidad")).length, 0,
    "B sin catálogo completo no puede consultar horarios con el servicio A conservado en DOM");
  const retry = h.document.getElementById("ia-f-reload-center");
  assert.ok(retry && !retry.disabled, "Debe poder completar B con una acción explícita");
  h.responses.length = 0;
  h.responses.push({ status: 200, body: { servicios: [{ id: "otro", nombre: "Servicio B" }] } },
    { status: 200, body: { items: [{ employee_id: "persona_b", name: "Profesional B", allows_all_services: true }] } });
  await retry.emit("click");
  h.responses.push({ status: 200, body: { slots: [{ hora: "10:00", disponible: true }] } });
  await date.emit("change");
  const query = new URL(h.requests.find(r => r.url.includes("/disponibilidad")).url).searchParams;
  assert.equal(query.get("location_id"), "centro_b"); assert.equal(query.get("servicio"), "Servicio B");
  assert.equal(query.get("employee_id"), "persona_b");
  await h.document.querySelectorAll(".ia-time-slot")[0].emit("click");
  await h.document.getElementById("ia-f-next2").emit("click");
  h.responses.push({ status: 200, body: { estado: "confirmed", booking_id: "bk_b", mensaje: "Cita registrada" } });
  await h.document.getElementById("ia-f-confirm").emit("click");
  const payload = JSON.parse(h.requests.find(r => r.url.endsWith("/agendar")).options.body);
  assert.equal(payload.location_id, "centro_b"); assert.equal(payload.servicio, "Servicio B");
  assert.equal(payload.employee_id, "persona_b"); assert.equal(payload.nombre, "Ana García");
  assert.equal(payload.telefono, "+34900000000");
  assert.equal(name.value, "Ana García"); assert.equal(phone.value, "+34900000000");
});
