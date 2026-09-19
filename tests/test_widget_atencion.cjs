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
      parentNode: null, attributes: new Map(), textContent: "", innerHTML: "", disabled: false });
  }
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
  addEventListener() {}
  focus() { this.focused = true; }
  contains(node) { return this === node || this.children.some((child) => child.contains(node)); }
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

async function harness() {
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
  const context = vm.createContext({ document, window, URL, AbortController,
    CustomEvent: class { constructor(_name, options) { this.detail = options.detail; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      assert.ok(responses.length, "Ninguna llamada adicional tiene respuesta autorizada");
      const response = responses.shift();
      return { status: response.status, ok: response.status < 400,
        text: async () => JSON.stringify(response.body) };
    },
  });
  const root = path.resolve(__dirname, "..");
  const utils = new vm.SourceTextModule(await fs.readFile(path.join(root, "widget/utils.js"), "utf8"), { context });
  const formModule = new vm.SyntheticModule(["mostrarFormulario"], function () {
    this.setExport("mostrarFormulario", () => { formCalls += 1; });
  }, { context });
  const chat = new vm.SourceTextModule(await fs.readFile(path.join(root, "widget/chat.js"), "utf8"), { context });
  await chat.link((specifier) => specifier === "./utils.js" ? utils : formModule);
  await chat.evaluate();
  utils.namespace.WIDGET_CONFIG.bookingEnabled = true;
  return { document, events, requests, responses, timers, msgs, input, send, quick, field, contact,
    alreadyDisabled, chat: chat.namespace, utils: utils.namespace, formCalls: () => formCalls };
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
