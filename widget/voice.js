// Voz en el widget: el navegador del cliente final habla DIRECTO con OpenAI Realtime
// por WebRTC (token efimero minteado por el backend del negocio). Las funciones que pide
// el modelo (consultar disponibilidad, reservar, cancelar) se ejecutan contra la agenda
// REAL del negocio via /voice/widget/{cliente}/tool. Misma UX que "probar en el navegador".
import { WIDGET_CONFIG, trackWidgetEvent } from "./utils.js";
import {
  isUnintelligibleText, toolResponseInstruction, extractBookingContact, CONTINUE_NUDGE_TEXT,
} from "./voice_core.js";

const MIC_AUDIO = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };

let v = null; // estado de la llamada en curso
const SILENCE_WATCHDOG_MS = 1700;
const ACTIVE_RESPONSE_GRACE_MS = 8000;
const POST_CANCEL_WATCHDOG_MS = 850;

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
  try { clearSilenceWatchdog(); } catch (_) {}
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

function clearSilenceWatchdog() {
  if (!v || !v.silenceWatchdogId) return;
  clearTimeout(v.silenceWatchdogId);
  v.silenceWatchdogId = null;
  v.silenceWatchdogReason = "";
  v.silenceWatchdogUsed = false;
}
function armSilenceWatchdog(reason) {
  if (!v || !v.dc) return;
  if (v.silenceWatchdogId) clearTimeout(v.silenceWatchdogId);
  v.silenceWatchdogReason = reason || "";
  v.silenceWatchdogUsed = false;
  v.silenceWatchdogId = setTimeout(runSilenceWatchdog, SILENCE_WATCHDOG_MS);
}
function armPostCancelWatchdog() {
  if (!v || !v.dc) return;
  if (v.silenceWatchdogId) clearTimeout(v.silenceWatchdogId);
  v.silenceWatchdogUsed = false;
  v.silenceWatchdogId = setTimeout(runSilenceWatchdog, POST_CANCEL_WATCHDOG_MS);
}
function cancelActiveResponse() {
  if (!v || !v.dc || v.responseCancelPending) return false;
  try { v.dc.send(JSON.stringify({ type: "response.cancel" })); } catch (_) {}
  v.responseCancelPending = true;
  v.responseCancelStartedAt = Date.now();
  v.responseActive = false;
  v.responseActiveStartedAt = 0;
  armPostCancelWatchdog();
  return true;
}

function sendResponse(instructions, toolChoice) {
  if (!v || !v.dc) return false;
  const payload = { type: "response.create" };
  if (instructions) payload.response = { instructions };
  if (payload.response && toolChoice) payload.response.tool_choice = toolChoice;
  try {
    v.dc.send(JSON.stringify(payload));
    v.responseActive = true;
    v.responseActiveStartedAt = Date.now();
    armSilenceWatchdog("response_create");
    return true;
  } catch (_) { return false; }
}
function speakSystemText(text) {
  if (!v || !v.dc || !text) return false;
  try {
    v.dc.send(JSON.stringify({ type: "conversation.item.create", item: { type: "message", role: "user", content: [{ type: "input_text", text }] } }));
    return true;
  } catch (_) { return false; }
}
function speakToolResult(name, result) {
  const instruction = toolResponseInstruction(name, result);
  if (!instruction) return sendResponse("", "");
  speakSystemText(`[sistema] Resultado interno de ${name}: ${JSON.stringify(result)}\n${instruction}`);
  return sendResponse(instruction, "none");
}
// Empujon INTERNO cuando el modelo se queda mudo: el modelo decide que decir/hacer con sus
// palabras (tool_choice libre). Sin frases fijas de cara al cliente. Mismo espiritu que el
// motor de telefono (voice_engine.py).
function continueNudge() {
  if (!v || !v.dc || v.expectingToolResponse) return false;
  speakSystemText(CONTINUE_NUDGE_TEXT);
  return sendResponse("", "");
}

function runSilenceWatchdog() {
  if (!v || !v.dc || v.silenceWatchdogUsed || v.expectingToolResponse) return;
  v.silenceWatchdogId = null;
  if (v.responseCancelPending) {
    if (Date.now() - (v.responseCancelStartedAt || 0) < 800) {
      armPostCancelWatchdog();
      return;
    }
    v.responseCancelPending = false;
    v.responseCancelStartedAt = 0;
    v.responseActive = false;
    v.responseActiveStartedAt = 0;
  }
  if (v.turnHadAssistantOutput || v.turnHadFunctionCall) {
    clearSilenceWatchdog();
    return;
  }
  if ((v.silenceRecoveries || 0) >= 3) return;
  v.silenceWatchdogUsed = true;
  if (v.responseActive) {
    const activeFor = Date.now() - (v.responseActiveStartedAt || Date.now());
    if (activeFor < ACTIVE_RESPONSE_GRACE_MS) {
      v.silenceWatchdogUsed = false;
      armPostCancelWatchdog();
      return;
    }
    v.silenceWatchdogUsed = false;
    cancelActiveResponse();
    return;
  }
  v.silenceRecoveries = (v.silenceRecoveries || 0) + 1;
  continueNudge();
}

function handleEvent(ev) {
  const type = (ev && ev.type) || "";
  if (type === "response.created") {
    if (v) { v.responseActive = true; v.responseActiveStartedAt = Date.now(); }
  } else if (type.indexOf("output_audio.delta") >= 0 || type.indexOf("audio.delta") >= 0) {
    if (v) { v.turnHadAssistantOutput = true; v.silenceRecoveries = 0; v.responseCancelPending = false; v.responseCancelStartedAt = 0; clearSilenceWatchdog(); }
    setStatus("Hablando…"); speaking(true);
    if (v && v.speakId) clearTimeout(v.speakId);
    if (v) v.speakId = setTimeout(() => { speaking(false); if (v) setStatus("En llamada"); }, 650);
  } else if (type === "response.done" || type.indexOf("output_audio.done") >= 0) {
    speaking(false); if (v) setStatus("En llamada");
    if (type === "response.done" && v) {
      v.responseActive = false;
      v.responseActiveStartedAt = 0;
      v.responseCancelPending = false;
      v.responseCancelStartedAt = 0;
      v.responseDoneSeen = true;
      if (v.expectingToolResponse) { v.fnResponseDone = true; maybeCreateToolResponse(); }
      // Colgado limpio (paridad con telefono): el asistente pidio finalizar_llamada y ya
      // dijo la despedida -> colgamos tras dejar sonar el audio pendiente.
      if (v.endCallPending && v.turnHadAssistantOutput && !v.expectingToolResponse) {
        v.endCallPending = false;
        clearSilenceWatchdog();
        setTimeout(() => endCall("Llamada finalizada", "El asistente ha terminado la llamada."), 3500);
      }
      // Si el turno cerro sin audio y sin tool pendiente, el watchdog dara UN empujon interno.
    }
  } else if (type === "input_audio_buffer.speech_started") {
    setHint("Te escucho…");
  } else if (type === "response.output_audio_transcript.done") {
    if (v) v.lastAssistantText = String(ev.transcript || "");
    if (v && ev.transcript) { v.turnHadAssistantOutput = true; v.silenceRecoveries = 0; v.responseCancelPending = false; v.responseCancelStartedAt = 0; clearSilenceWatchdog(); }
    pushTranscript("assistant", ev.transcript);
  } else if (type === "conversation.item.input_audio_transcription.completed") {
    if (v) {
      v.autoNudgeUsed = false;  // nuevo turno del cliente: rearma la red anti-silencio
      v.confirmationNudgeUsed = false;
      v.contactConfirmationNudgeUsed = false;
      v.lastUserText = String(ev.transcript || "");
      v.responseDoneSeen = false;
      v.turnHadAssistantOutput = false;
      v.turnHadFunctionCall = false;
      v.silenceRecoveries = 0;
      if (v.pendingBookingSlot) {
        const contact = extractBookingContact(ev.transcript);
        if (contact) v.pendingBookingContact = contact;
      }
      armSilenceWatchdog(isUnintelligibleText(ev.transcript) ? "unintelligible_user" : "user_turn");
    }
    pushTranscript("user", ev.transcript);
  } else if (type === "response.function_call_arguments.done") {
    if (v) { v.turnHadFunctionCall = true; clearSilenceWatchdog(); }
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
    outcome: v.outcome || "",
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
  let parsedArgs = {};
  try { parsedArgs = JSON.parse(argsStr || "{}") || {}; } catch (_) { parsedArgs = {}; }
  setHint("Un momento, lo compruebo…");
  // La respuesta que emitió la function_call sigue ACTIVA: no podemos pedir
  // response.create hasta que llegue su response.done (si no, OpenAI lo rechaza y
  // el asistente se queda mudo hasta que el usuario vuelve a hablar). Latch: lo
  // disparamos cuando estén LOS DOS — output enviado y response.done recibido.
  v.expectingToolResponse = true; v.fnOutputReady = false; v.fnResponseDone = !!v.responseDoneSeen; v.pendingToolFollowup = "";
  let result;
  try {
    const r = await fetch(`${WIDGET_CONFIG.apiUrl}/voice/widget/${encodeURIComponent(WIDGET_CONFIG.clienteId)}/tool`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, arguments: argsStr }),
    });
    result = r.ok ? await r.json() : { ok: false, error: "No se pudo consultar ahora mismo." };
  } catch (_) { result = { ok: false, error: "No se pudo consultar ahora mismo." }; }
  // Etiqueta de resultado (paridad con el motor de telefono): la ultima accion gana.
  if (result && result.ok) {
    if (name === "crear_cita") v.outcome = "reservada";
    else if (name === "cancelar_cita") v.outcome = "cancelada";
    else if (name === "reprogramar_cita") v.outcome = "reprogramada";
    else if (name === "transferir_a_humano" && result.transfer) v.outcome = "transferida";
  }
  if (name === "consultar_disponibilidad" && result && result.ok && result.hora && result.hora_disponible === true) {
    v.pendingBookingSlot = {
      servicio: String(parsedArgs.servicio || ""),
      centro: String(parsedArgs.centro || ""),
      fecha: String(result.fecha || parsedArgs.fecha || ""),
      fecha_texto: String(parsedArgs.fecha_texto || result.fecha_texto || result.fecha || ""),
      hora: String(result.hora || parsedArgs.hora || ""),
    };
    v.pendingBookingContact = null;
  } else if (name === "crear_cita" && result && result.ok) {
    v.pendingBookingSlot = null;
    v.pendingBookingContact = null;
  } else if ((name === "cancelar_cita" || name === "reprogramar_cita") && result && result.ok) {
    v.pendingBookingSlot = null;
    v.pendingBookingContact = null;
  }
  if (result && result.end_call) v.endCallPending = true;
  v.lastToolName = name;
  v.lastToolResult = result || {};
  try {
    v.dc.send(JSON.stringify({ type: "conversation.item.create", item: { type: "function_call_output", call_id: callId, output: JSON.stringify(result) } }));
    const followup = toolResponseInstruction(name, result);
    v.pendingToolFollowup = followup || "";
    v.fnOutputReady = true;
    maybeCreateToolResponse();
  } catch (_) {}
}

// Dispara el response.create del resultado del tool solo cuando se cumplen las dos
// condiciones (output enviado + response.done de la respuesta de la function_call).
function maybeCreateToolResponse() {
  if (v && v.fnOutputReady && v.fnResponseDone && v.dc) {
    v.fnOutputReady = false; v.fnResponseDone = false; v.expectingToolResponse = false;
    const followup = v.pendingToolFollowup || "";
    v.pendingToolFollowup = "";
    sendResponse(followup, followup ? "none" : "");
  }
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
  v = { muted: false, pc: null, dc: null, micStream: null, timerId: null, maxId: null, speakId: null, seconds: 0, transcript: [], startedAt: Date.now(), lastAssistantText: "", lastUserText: "", lastToolName: "", lastToolResult: {}, endCallPending: false, autoNudgeUsed: false, confirmationNudgeUsed: false, contactConfirmationNudgeUsed: false, pendingToolFollowup: "", pendingBookingSlot: null, pendingBookingContact: null, responseDoneSeen: false, responseActive: false, responseActiveStartedAt: 0, responseCancelPending: false, responseCancelStartedAt: 0, turnHadAssistantOutput: false, turnHadFunctionCall: false, silenceWatchdogId: null, silenceWatchdogReason: "", silenceWatchdogUsed: false, silenceRecoveries: 0 };
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
          v.dc.send(JSON.stringify({ type: "conversation.item.create", item: { type: "message", role: "user", content: [{ type: "input_text", text: 'Tu primer mensaje debe ser, palabra por palabra y sin cambiar ningún nombre propio (di los nombres tal cual aparecen), exactamente este y nada más: "' + g + '"' }] } }));
          v.dc.send(JSON.stringify({ type: "response.create" }));
          v.responseActive = true;
          v.responseActiveStartedAt = Date.now();
          armSilenceWatchdog("greeting");
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
