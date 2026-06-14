// Voz en el widget: el navegador del cliente final habla DIRECTO con OpenAI Realtime
// por WebRTC (token efimero minteado por el backend del negocio). Las funciones que pide
// el modelo (consultar disponibilidad, reservar, cancelar) se ejecutan contra la agenda
// REAL del negocio via /voice/widget/{cliente}/tool. Misma UX que "probar en el navegador".
import { WIDGET_CONFIG, trackWidgetEvent } from "./utils.js";

const MIC_AUDIO = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };

let v = null; // estado de la llamada en curso

function byId(id) { return document.getElementById(id); }
function fmt(s) { const m = Math.floor(s / 60), r = s % 60; return String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0"); }
function isSecure() {
  return window.isSecureContext === true || location.protocol === "https:"
    || location.hostname === "localhost" || location.hostname === "127.0.0.1";
}

function setStatus(t) { const e = byId("ia-v-status"); if (e) e.textContent = t; }
function setHint(t) { const e = byId("ia-v-hint"); if (e) e.textContent = t; }
function speaking(on) { const a = byId("ia-v-avatar"); if (a) a.classList.toggle("speaking", !!on); }

function buildOverlay(cfg) {
  if (byId("ia-v-overlay")) return;
  const initial = ((cfg.nombre || "IA").trim()[0] || "IA").toUpperCase();
  const o = document.createElement("div");
  o.id = "ia-v-overlay";
  o.className = "ia-v-overlay";
  o.innerHTML = `
    <div class="ia-v-card" role="dialog" aria-label="Asistente de voz">
      <div class="ia-v-avatar" id="ia-v-avatar">${initial}</div>
      <div class="ia-v-name" id="ia-v-name"></div>
      <div class="ia-v-status" id="ia-v-status">Conectando…</div>
      <div class="ia-v-timer" id="ia-v-timer">00:00</div>
      <div class="ia-v-hint" id="ia-v-hint">Permite el micrófono para empezar a hablar.</div>
      <div class="ia-v-actions">
        <button class="ia-v-btn" id="ia-v-mute" type="button">Silenciar</button>
        <button class="ia-v-btn ia-v-hang" id="ia-v-hang" type="button">Colgar</button>
      </div>
    </div>
    <audio id="ia-v-audio" autoplay></audio>`;
  // La llamada sale DENTRO del panel del chat (no a pantalla completa).
  const mount = byId("ia-w-chat") || document.body;
  mount.appendChild(o);
  byId("ia-v-name").textContent = cfg.nombre || "Asistente de voz";
  byId("ia-v-mute").addEventListener("click", toggleMute);
  byId("ia-v-hang").addEventListener("click", () => endCall());
}

function teardown() {
  if (!v) return;
  try { if (v.timerId) clearInterval(v.timerId); } catch (_) {}
  try { if (v.maxId) clearTimeout(v.maxId); } catch (_) {}
  try { if (v.dc) v.dc.close(); } catch (_) {}
  try { if (v.pc) v.pc.close(); } catch (_) {}
  try { if (v.micStream) v.micStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
}

function removeOverlay() {
  const o = byId("ia-v-overlay");
  if (o) o.remove();
}

function endCall(title, hint) {
  logCall();
  teardown();
  if (title || hint) { setStatus(title || "Llamada finalizada"); if (hint) setHint(hint); speaking(false); }
  const wasActive = !!v;
  v = null;
  // Cierre suave: deja leer el mensaje final si lo hay, si no cierra ya.
  setTimeout(removeOverlay, (title || hint) ? 1500 : 0);
  if (wasActive) trackWidgetEvent("widget_voice_ended");
}

function fail(title, hint) { setStatus(title); setHint(hint || ""); teardown(); v = null; }

function toggleMute() {
  if (!v || !v.micStream) return;
  v.muted = !v.muted;
  v.micStream.getAudioTracks().forEach((t) => { t.enabled = !v.muted; });
  const b = byId("ia-v-mute");
  if (b) b.textContent = v.muted ? "Activar micro" : "Silenciar";
}

function getMic() {
  if (!isSecure()) return Promise.reject({ name: "InsecureContext" });
  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) return md.getUserMedia({ audio: MIC_AUDIO });
  return Promise.reject({ name: "Unsupported" });
}
function micError(e) {
  const n = (e && e.name) || "";
  if (n === "InsecureContext") fail("Necesita conexión segura", "La web debe cargarse con https para usar el micrófono.");
  else if (n === "NotAllowedError" || n === "SecurityError" || n === "PermissionDeniedError") fail("Micrófono bloqueado", "Permite el micrófono en el navegador para hablar.");
  else if (n === "NotFoundError") fail("Sin micrófono", "Conecta un micrófono y vuelve a intentarlo.");
  else if (n === "Unsupported") fail("Navegador no compatible", "Prueba con Chrome o Safari actualizados.");
  else fail("No se pudo abrir el micrófono", "Revisa los permisos del navegador.");
}

function pushTranscript(role, text) {
  const clean = (text || "").trim();
  if (v && clean) v.transcript.push({ role, text: clean, ts: new Date().toISOString() });
}

function handleEvent(ev) {
  const type = (ev && ev.type) || "";
  if (type.indexOf("output_audio.delta") >= 0 || type.indexOf("audio.delta") >= 0) {
    setStatus("Hablando…"); speaking(true);
    if (v && v.speakId) clearTimeout(v.speakId);
    if (v) v.speakId = setTimeout(() => { speaking(false); if (v) setStatus("En llamada"); }, 650);
  } else if (type === "response.done" || type.indexOf("output_audio.done") >= 0) {
    speaking(false); if (v) setStatus("En llamada");
  } else if (type === "input_audio_buffer.speech_started") {
    setHint("Te escucho…");
  } else if (type === "response.output_audio_transcript.done") {
    pushTranscript("assistant", ev.transcript);
  } else if (type === "conversation.item.input_audio_transcription.completed") {
    pushTranscript("user", ev.transcript);
  } else if (type === "response.function_call_arguments.done") {
    runTool(ev);
  } else if (type === "error") {
    endCall("La llamada terminó", "El asistente devolvió un error.");
  }
}

function logCall() {
  // Registra la transcripcion en el backend para que salga en Conversaciones.
  if (!v || !v.transcript || !v.transcript.length) return;
  const payload = JSON.stringify({
    transcript: v.transcript,
    duration_seconds: Math.max(0, Math.round((Date.now() - (v.startedAt || Date.now())) / 1000)),
  });
  const url = `${WIDGET_CONFIG.apiUrl}/voice/widget/${encodeURIComponent(WIDGET_CONFIG.clienteId)}/log`;
  try {
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: payload, keepalive: true }).catch(() => {});
  } catch (_) {}
}

async function runTool(ev) {
  const name = ev && ev.name;
  const callId = ev && ev.call_id;
  const argsStr = (ev && ev.arguments) || "{}";
  if (!name || !callId || !v || !v.dc) return;
  setHint("Un momento, lo compruebo…");
  let result;
  try {
    const r = await fetch(`${WIDGET_CONFIG.apiUrl}/voice/widget/${encodeURIComponent(WIDGET_CONFIG.clienteId)}/tool`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, arguments: argsStr }),
    });
    result = r.ok ? await r.json() : { ok: false, error: "No se pudo consultar ahora mismo." };
  } catch (_) { result = { ok: false, error: "No se pudo consultar ahora mismo." }; }
  try {
    v.dc.send(JSON.stringify({ type: "conversation.item.create", item: { type: "function_call_output", call_id: callId, output: JSON.stringify(result) } }));
    v.dc.send(JSON.stringify({ type: "response.create" }));
  } catch (_) {}
}

async function postSDP(model, sdp, secret) {
  const eps = ["https://api.openai.com/v1/realtime/calls?model=" + model, "https://api.openai.com/v1/realtime?model=" + model];
  let lastErr;
  for (const ep of eps) {
    try {
      const r = await fetch(ep, { method: "POST", body: sdp, headers: { Authorization: "Bearer " + secret, "Content-Type": "application/sdp" } });
      if (r.ok) return await r.text();
      lastErr = new Error("sdp " + r.status);
    } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error("sdp failed");
}

export async function startVoice(cfg) {
  if (v) return;
  buildOverlay(cfg || {});
  v = { muted: false, pc: null, dc: null, micStream: null, timerId: null, maxId: null, speakId: null, seconds: 0, transcript: [], startedAt: Date.now() };
  setStatus("Pidiendo micrófono…"); setHint("Permite el micrófono para empezar a hablar.");
  trackWidgetEvent("widget_voice_started");
  try { v.micStream = await getMic(); } catch (e) { micError(e); return; }
  setStatus("Conectando…");
  let sess;
  try {
    const r = await fetch(`${WIDGET_CONFIG.apiUrl}/voice/widget/${encodeURIComponent(WIDGET_CONFIG.clienteId)}/session`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    if (r.status === 403) { fail("Voz no disponible", "Este asistente de voz no está activado."); return; }
    if (r.status === 429) { fail("Demasiados intentos", "Espera un minuto y vuelve a probar."); return; }
    if (r.status === 503) { fail("Voz no disponible", "El asistente de voz no está disponible ahora mismo."); return; }
    if (!r.ok) throw new Error("http " + r.status);
    sess = await r.json();
  } catch (_) { fail("No se pudo iniciar la voz", "Hubo un problema al conectar. Inténtalo de nuevo."); return; }
  const maxS = sess.max_duration_seconds || 120;
  try {
    v.pc = new RTCPeerConnection();
    v.pc.ontrack = (e) => { try { const a = byId("ia-v-audio"); a.srcObject = e.streams[0]; a.play().catch(() => {}); } catch (_) {} };
    v.pc.onconnectionstatechange = () => {
      if (!v || !v.pc) return;
      const s = v.pc.connectionState;
      if (s === "connected") setStatus("En llamada");
      else if (s === "failed") endCall("Se cortó la llamada", "Se perdió la conexión.");
      else if (s === "disconnected") setStatus("Reconectando…");
    };
    v.micStream.getTracks().forEach((t) => v.pc.addTrack(t, v.micStream));
    v.dc = v.pc.createDataChannel("oai-events");
    v.dc.onmessage = (m) => { try { handleEvent(JSON.parse(m.data)); } catch (_) {} };
    v.dc.onopen = () => {
      try {
        const g = sess.greeting || "";
        if (g) {
          v.dc.send(JSON.stringify({ type: "conversation.item.create", item: { type: "message", role: "user", content: [{ type: "input_text", text: 'Inicia la llamada saludando exactamente con: "' + g + '"' }] } }));
          v.dc.send(JSON.stringify({ type: "response.create" }));
        }
      } catch (_) {}
    };
    const offer = await v.pc.createOffer();
    await v.pc.setLocalDescription(offer);
    const ans = await postSDP(encodeURIComponent(sess.model || ""), offer.sdp, sess.client_secret);
    await v.pc.setRemoteDescription({ type: "answer", sdp: ans });
  } catch (_) { fail("No se pudo establecer la llamada", "No se pudo abrir el canal de audio."); return; }
  setStatus("En llamada"); setHint("Habla con normalidad. Pulsa Colgar para terminar.");
  v.timerId = setInterval(() => { if (!v) return; v.seconds++; const t = byId("ia-v-timer"); if (t) t.textContent = fmt(v.seconds); }, 1000);
  v.maxId = setTimeout(() => endCall("Llamada finalizada", "Se alcanzó el tiempo máximo. Pulsa el micrófono para hablar otra vez."), maxS * 1000);
}
