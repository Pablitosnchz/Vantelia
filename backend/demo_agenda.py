"""Demos: tenants temporales, pagina demo y datos de agenda de ejemplo (refactor F3).

Seed idempotente de ~1 mes de citas demo (source=demo_seed, empleados
empdemo_*) y purga; registro de demos con TTL.
"""
from __future__ import annotations

import json
import os
import random
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from backend import agenda, appstate, booking, clients, db, rag, security, settings, textnorm, timeutils

DEMO_TENANT_PREFIX = "demo_auto_"


DEMO_TTL_SECONDS = int(os.getenv("DEMO_TENANT_TTL_SECONDS", "3600"))


def _demo_registry_path() -> Path:
    return settings.DATA_DIR / "demo_tenants.json"


def _load_demo_registry() -> Dict[str, float]:
    path = _demo_registry_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in raw.items()}
    except Exception:  # noqa: BLE001
        settings.logger.warning("Registro de demos corrupto; se reinicia.")
        return {}


def _save_demo_registry(registry: Dict[str, float]) -> None:
    path = _demo_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def _register_demo_tenant(cliente_id: str) -> None:
    registry = _load_demo_registry()
    registry[cliente_id] = time.time()
    _save_demo_registry(registry)


def _purge_expired_demos() -> int:
    registry = _load_demo_registry()
    if not registry:
        return 0
    now = time.time()
    expired = [cid for cid, ts in registry.items() if now - ts > DEMO_TTL_SECONDS]
    if not expired:
        return 0
    for cliente_id in expired:
        try:
            if cliente_id in appstate.CONFIG_CLIENTES:
                clients._delete_client_everywhere(cliente_id)
            registry.pop(cliente_id, None)
            settings.logger.info("Demo expirada eliminada: %s", cliente_id)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("No se pudo eliminar demo expirada %s: %s", cliente_id, exc)
            registry.pop(cliente_id, None)
    _save_demo_registry(registry)
    return len(expired)


VOICE_DEMO_TEMPLATE = """
<style>
  .cta-voice {
    background: linear-gradient(135deg, #10b981, #06b6d4);
    color: #04121a;
  }
  #vdemoOverlay {
    position: fixed; inset: 0; z-index: 60;
    display: none; align-items: center; justify-content: center;
    padding: 24px;
    background: radial-gradient(1200px 700px at 50% -10%, rgba(0,245,212,0.12), transparent 60%),
                rgba(5, 10, 24, 0.92);
    backdrop-filter: blur(8px);
  }
  #vdemoOverlay.open { display: flex; animation: vdemoFade 0.25s ease both; }
  @keyframes vdemoFade { from { opacity: 0; } to { opacity: 1; } }
  .vdemo-card {
    width: 100%; max-width: 360px;
    background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 24px;
    padding: 34px 26px 28px;
    text-align: center;
    box-shadow: 0 30px 80px rgba(0,0,0,0.5);
  }
  .vdemo-avatar {
    width: 104px; height: 104px; margin: 0 auto 18px;
    border-radius: 999px;
    display: grid; place-items: center;
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 2.2rem; color: #04121a;
    background: linear-gradient(135deg, __COLOR__, #00F5D4);
    position: relative;
  }
  .vdemo-avatar::after {
    content: ""; position: absolute; inset: -8px;
    border-radius: 999px; border: 2px solid rgba(0,245,212,0.45);
    opacity: 0; transform: scale(0.9);
  }
  .vdemo-card.speaking .vdemo-avatar::after { animation: vdemoRing 1.1s ease-out infinite; }
  @keyframes vdemoRing {
    0% { opacity: 0.8; transform: scale(0.92); }
    100% { opacity: 0; transform: scale(1.25); }
  }
  .vdemo-name { font-family: "Space Grotesk", sans-serif; font-weight: 700; font-size: 1.3rem; color: #fff; }
  .vdemo-status { margin-top: 6px; color: rgba(255,255,255,0.66); font-size: 0.96rem; min-height: 22px; }
  .vdemo-timer { margin-top: 12px; font-variant-numeric: tabular-nums; font-size: 1.5rem; font-weight: 600; color: #fff; letter-spacing: 0.04em; }
  .vdemo-actions { display: flex; gap: 14px; justify-content: center; margin-top: 24px; }
  .vdemo-btn {
    appearance: none; cursor: pointer; font: inherit; font-weight: 600; font-size: 0.92rem;
    border: 1px solid rgba(255,255,255,0.16); color: #fff;
    background: rgba(255,255,255,0.06);
    padding: 12px 18px; border-radius: 999px; transition: all 0.16s ease;
  }
  .vdemo-btn:hover { background: rgba(255,255,255,0.12); }
  .vdemo-btn.on { background: rgba(255,255,255,0.2); }
  .vdemo-btn.hang { background: #ef4444; border-color: #ef4444; color: #fff; }
  .vdemo-btn.hang:hover { background: #dc2626; }
  .vdemo-hint { margin-top: 18px; color: rgba(255,255,255,0.5); font-size: 0.84rem; line-height: 1.5; }
</style>
<div id="vdemoOverlay" role="dialog" aria-modal="true" aria-label="Llamada con el asistente">
  <div class="vdemo-card" id="vdemoCard">
    <div class="vdemo-avatar">__INITIAL__</div>
    <div class="vdemo-name">__NOMBRE__</div>
    <div class="vdemo-status" id="vdemoStatus">Llamando…</div>
    <div class="vdemo-timer" id="vdemoTimer">00:00</div>
    <div class="vdemo-actions">
      <button type="button" class="vdemo-btn" id="vdemoMute">Silenciar</button>
      <button type="button" class="vdemo-btn hang" id="vdemoHang">Colgar</button>
    </div>
    <div class="vdemo-hint" id="vdemoHint">Habla con normalidad, como en una llamada real.</div>
  </div>
  <audio id="vdemoAudio" autoplay playsinline></audio>
</div>
<script>
(function(){
  var CFG = __VOICE_CFG__;
  var btn = document.getElementById('vdemoCallBtn');
  if(!btn) return;
  var overlay = document.getElementById('vdemoOverlay');
  var card = document.getElementById('vdemoCard');
  var statusEl = document.getElementById('vdemoStatus');
  var timerEl = document.getElementById('vdemoTimer');
  var hintEl = document.getElementById('vdemoHint');
  var audioEl = document.getElementById('vdemoAudio');
  var muteBtn = document.getElementById('vdemoMute');
  var hangBtn = document.getElementById('vdemoHang');

  var pc=null, dc=null, micStream=null, timerId=null, maxId=null, speakId=null;
  var seconds=0, muted=false, active=false, ended=false, MAXS=120;

  function setStatus(t){ if(statusEl) statusEl.textContent=t; }
  function setHint(t){ if(hintEl) hintEl.textContent=t; }
  function fmt(s){ var m=Math.floor(s/60), x=s%60; return (m<10?'0':'')+m+':'+(x<10?'0':'')+x; }
  function speaking(on){ if(card) card.classList.toggle('speaking', !!on); }

  function cleanup(){
    active=false;
    if(timerId){ clearInterval(timerId); timerId=null; }
    if(maxId){ clearTimeout(maxId); maxId=null; }
    if(speakId){ clearTimeout(speakId); speakId=null; }
    speaking(false);
    try{ if(dc) dc.close(); }catch(e){}
    try{ if(pc) pc.close(); }catch(e){}
    try{ if(micStream) micStream.getTracks().forEach(function(t){ t.stop(); }); }catch(e){}
    pc=null; dc=null; micStream=null;
    if(audioEl){ try{ audioEl.srcObject=null; }catch(e){} }
  }
  function resetCallUI(){
    ended=false;
    if(muteBtn){ muteBtn.style.display=''; muteBtn.textContent='Silenciar'; muteBtn.classList.remove('on'); }
    if(hangBtn){ hangBtn.textContent='Colgar'; hangBtn.classList.add('hang'); }
    if(overlay) overlay.classList.remove('ended');
  }
  function closeOverlay(){ cleanup(); resetCallUI(); if(overlay) overlay.classList.remove('open'); document.body.style.overflow=''; }
  // Fin de llamada NO solicitado por el usuario: deja el overlay abierto como un pop-up
  // que explica el motivo, y convierte "Colgar" en "Cerrar". Asi el usuario siempre ve
  // por que se ha cortado.
  function endCall(reason, detail){
    if(ended) return;
    ended=true; active=false;
    cleanup();
    setStatus(reason || 'Llamada finalizada');
    setHint(detail || 'La llamada ha terminado.');
    if(muteBtn) muteBtn.style.display='none';
    if(hangBtn){ hangBtn.textContent='Cerrar'; hangBtn.classList.remove('hang'); }
    if(overlay) overlay.classList.add('ended');
  }
  function fail(msg, hint){ endCall(msg || 'No se pudo conectar', hint || 'Revisa los permisos e inténtalo de nuevo.'); }

  function isSecure(){
    return window.isSecureContext === true
      || location.protocol === 'https:'
      || location.hostname === 'localhost'
      || location.hostname === '127.0.0.1';
  }
  // Pide el microfono de forma universal: API moderna y, si no existe, los nombres
  // antiguos por navegador. Rechaza con un nombre claro si no se puede ni intentar.
  // Forzamos cancelacion de eco/ruido: sin esto el mic recaptura la voz del propio
  // asistente (audioEl) y el server_vad la toma como habla del usuario -> corta la
  // frase a medias y entra en bucle volviendo a saludar/responder.
  var MIC_AUDIO = { echoCancellation:true, noiseSuppression:true, autoGainControl:true };
  function getMic(){
    if(!isSecure()) return Promise.reject({ name:'InsecureContext' });
    var md = navigator.mediaDevices;
    if(md && md.getUserMedia) return md.getUserMedia({ audio:MIC_AUDIO });
    var legacy = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia;
    if(legacy) return new Promise(function(res, rej){ legacy.call(navigator, { audio:MIC_AUDIO }, res, rej); });
    return Promise.reject({ name:'Unsupported' });
  }
  function micError(e){
    var n = (e && e.name) || '';
    if(n==='InsecureContext') fail('Necesita conexión segura', 'Abre el demo con https:// para poder hablar.');
    else if(n==='NotAllowedError' || n==='SecurityError' || n==='PermissionDeniedError') fail('Micrófono bloqueado', 'Toca el candado/ajustes del navegador y permite el micrófono para esta web.');
    else if(n==='NotFoundError' || n==='DevicesNotFoundError') fail('No se detecta micrófono', 'Conecta o activa un micrófono y vuelve a intentarlo.');
    else if(n==='NotReadableError' || n==='TrackStartError') fail('Micrófono ocupado', 'Otra app está usando el micrófono. Ciérrala e inténtalo de nuevo.');
    else if(n==='Unsupported') fail('Navegador no compatible', 'Prueba con Chrome o Safari actualizados.');
    else fail('No se pudo abrir el micrófono', 'Revisa los permisos del navegador e inténtalo de nuevo.');
  }

  function handleEvent(ev){
    var type = (ev && ev.type) || '';
    if(type.indexOf('output_audio.delta')>=0 || type.indexOf('audio.delta')>=0){
      setStatus('Hablando…'); speaking(true);
      if(speakId) clearTimeout(speakId);
      speakId=setTimeout(function(){ speaking(false); if(active) setStatus('En llamada'); }, 650);
    } else if(type==='response.done' || type.indexOf('output_audio.done')>=0){
      speaking(false); if(active) setStatus('En llamada');
    } else if(type==='input_audio_buffer.speech_started'){
      if(active) setHint('Te escucho…');
    } else if(type==='response.function_call_arguments.done'){
      runTool(ev);
    } else if(type==='error'){
      var em = (ev && ev.error && (ev.error.message || ev.error.code)) || '';
      endCall('La llamada terminó', em ? ('Motivo: '+em) : 'El asistente devolvió un error. Vuelve a intentarlo.');
    }
  }

  // El navegador habla directo con OpenAI; cuando el modelo pide una funcion (consultar
  // disponibilidad, agendar...), la ejecutamos contra el backend y devolvemos el resultado
  // por el data channel. Sin esto el modelo se quedaria esperando -> silencio largo.
  async function runTool(ev){
    var name = ev && ev.name;
    var callId = ev && ev.call_id;
    var argsStr = (ev && ev.arguments) || '{}';
    if(!name || !callId || !dc) return;
    if(active) setHint('Un momento, lo compruebo…');
    var result;
    try{
      var base = (CFG.api||'').replace(/\\/$/,'');
      var r = await fetch(base + '/demo/' + encodeURIComponent(CFG.cliente) + '/voice/tool', {
        method:'POST', headers:{ 'Content-Type':'application/json' },
        body: JSON.stringify({ name:name, arguments:argsStr })
      });
      result = r.ok ? await r.json() : { ok:false, error:'No se pudo consultar ahora mismo.' };
    }catch(e){ result = { ok:false, error:'No se pudo consultar ahora mismo.' }; }
    try{
      dc.send(JSON.stringify({ type:'conversation.item.create', item:{ type:'function_call_output', call_id:callId, output: JSON.stringify(result) } }));
      dc.send(JSON.stringify({ type:'response.create' }));
    }catch(_){}
  }

  async function postSDP(model, sdp, secret){
    var endpoints = [
      'https://api.openai.com/v1/realtime/calls?model='+model,
      'https://api.openai.com/v1/realtime?model='+model
    ];
    var lastErr;
    for(var i=0;i<endpoints.length;i++){
      try{
        var r = await fetch(endpoints[i], { method:'POST', body:sdp, headers:{ 'Authorization':'Bearer '+secret, 'Content-Type':'application/sdp' } });
        if(r.ok) return await r.text();
        lastErr = new Error('sdp http '+r.status);
      }catch(e){ lastErr=e; }
    }
    throw lastErr || new Error('sdp failed');
  }

  async function call(){
    if(active) return;
    resetCallUI();
    active=true;
    overlay.classList.add('open'); document.body.style.overflow='hidden';
    setStatus('Pidiendo micrófono…'); timerEl.textContent='00:00';
    setHint('Permite el micrófono para empezar a hablar.');
    muted=false;

    try{
      micStream = await getMic();
    }catch(e){ micError(e); return; }

    var sess;
    setStatus('Conectando…');
    try{
      var base = (CFG.api||'').replace(/\\/$/,'');
      var r = await fetch(base + '/demo/' + encodeURIComponent(CFG.cliente) + '/voice/session', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:'{}' });
      if(r.status===429){ fail('Demasiados intentos', 'Has iniciado varias llamadas seguidas. Espera un minuto y vuelve a probar.'); return; }
      if(r.status===503){ fail('Voz no disponible', 'El asistente de voz no está configurado ahora mismo.'); return; }
      if(!r.ok) throw new Error('http '+r.status);
      sess = await r.json();
    }catch(e){ fail('No se pudo iniciar la voz', 'Hubo un problema al conectar con el asistente. Inténtalo de nuevo.'); return; }
    MAXS = sess.max_duration_seconds || 120;

    try{
      pc = new RTCPeerConnection();
      pc.ontrack = function(e){ try{ audioEl.srcObject = e.streams[0]; audioEl.play().catch(function(){}); }catch(_){} };
      pc.onconnectionstatechange = function(){
        if(!pc) return;
        var s = pc.connectionState;
        if(s==='connected'){ if(active && !ended) setStatus('En llamada'); }
        else if(s==='failed'){ endCall('Se cortó la llamada', 'Se perdió la conexión con el asistente. Comprueba tu internet y vuelve a llamar.'); }
        else if(s==='disconnected'){ if(active && !ended) setStatus('Reconectando…'); }
      };
      pc.oniceconnectionstatechange = function(){
        if(pc && pc.iceConnectionState==='failed'){ endCall('Se cortó la llamada', 'No se pudo mantener la conexión de audio (red o firewall). Vuelve a intentarlo.'); }
      };
      micStream.getTracks().forEach(function(t){ pc.addTrack(t, micStream); });
      dc = pc.createDataChannel('oai-events');
      dc.onmessage = function(m){ try{ handleEvent(JSON.parse(m.data)); }catch(_){} };
      dc.onclose = function(){ if(active && !ended) endCall('La llamada se cerró', 'El asistente cerró la sesión. Vuelve a llamar para seguir probando.'); };
      dc.onopen = function(){
        try{
          var g = sess.greeting || '';
          if(g){
            dc.send(JSON.stringify({ type:'conversation.item.create', item:{ type:'message', role:'user', content:[{ type:'input_text', text:'Inicia la llamada saludando exactamente con: "'+g+'"' }] } }));
            dc.send(JSON.stringify({ type:'response.create' }));
          }
        }catch(_){}
      };
      var offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      var sdpAnswer = await postSDP(encodeURIComponent(sess.model||''), offer.sdp, sess.client_secret);
      await pc.setRemoteDescription({ type:'answer', sdp:sdpAnswer });
    }catch(e){ fail('No se pudo establecer la llamada', 'No se pudo abrir el canal de audio con el asistente. Inténtalo de nuevo.'); return; }

    setStatus('En llamada');
    setHint('Habla con normalidad. Pulsa Colgar para terminar.');
    seconds=0; timerEl.textContent='00:00';
    timerId=setInterval(function(){ seconds++; timerEl.textContent=fmt(seconds); }, 1000);
    maxId=setTimeout(function(){
      endCall('Tiempo de demo agotado', 'Esta demo de voz dura '+MAXS+' segundos. Pulsa "Llamar al asistente" para hablar otra vez.');
    }, MAXS*1000);
  }

  btn.addEventListener('click', call);
  if(muteBtn) muteBtn.addEventListener('click', function(){
    muted=!muted;
    if(micStream) micStream.getAudioTracks().forEach(function(t){ t.enabled=!muted; });
    muteBtn.textContent = muted ? 'Activar micro' : 'Silenciar';
    muteBtn.classList.toggle('on', muted);
  });
  if(hangBtn) hangBtn.addEventListener('click', closeOverlay);
})();
</script>
"""


def _build_demo_page(cliente_id: str, request: Request) -> str:
    config = clients._get_client_config(cliente_id)
    assets = clients._build_install_snippet(cliente_id, request)
    nombre = escape(config["nombre"])
    color = escape(config["color"])
    booking_enabled = bool(config["booking"]["enabled"])
    api_base_url = escape(assets["api_base_url"])
    cliente_safe = escape(cliente_id)
    script_url = escape(assets["widget_script_url"])
    favicon_url = escape(textnorm._brand_asset_public_path("favicon.png"))
    fondo_url = escape(textnorm._brand_asset_public_path("fondo-desktop.png") or textnorm._brand_asset_public_path("Fondo_Web.png"))
    fondo_movil_url = escape(textnorm._brand_asset_public_path("fondo-movil.png") or fondo_url)

    booking_example = (
        '<button type="button" class="ex-chip" data-msg="¿Tenéis disponibilidad mañana?">'
        '<span class="ex-icon">📅</span><span>¿Tenéis disponibilidad mañana?</span></button>'
        if booking_enabled else ""
    )

    # Self-serve bridge: only auto demos (demo_auto_*) without an owner can be claimed.
    is_claimable_demo = (
        (cliente_id.startswith(DEMO_TENANT_PREFIX) or bool(config.get("demo_claimable")))
        and not db.db_get_client_owner(cliente_id)
    )
    claim_banner = (
        f'<section class="claim-banner">'
        f'  <div class="claim-banner-inner">'
        f'    <div class="claim-text">'
        f'      <strong>Tu asistente ya esta listo</strong>'
        f'      <span>Guardalo en tu cuenta, copia el snippet e instalalo en tu web. Sin tarjeta.</span>'
        f'    </div>'
        f'    <a class="claim-cta" data-claim-cta="1" href="/acceso?mode=signup&amp;claim={cliente_safe}">'
        f'      Activar gratis e instalar'
        f'    </a>'
        f'  </div>'
        f'</section>'
        if is_claimable_demo else ""
    )
    booking_step = (
        '<article class="step">'
        '<div class="step-num">1</div>'
        '<h3>Pide una cita</h3>'
        '<p>Reserva como lo haría tu cliente. La IA muestra huecos y agenda en tiempo real.</p>'
        '</article>'
        if booking_enabled else
        '<article class="step">'
        '<div class="step-num">1</div>'
        '<h3>Haz una consulta</h3>'
        '<p>Pregunta lo que un cliente real preguntaría. La IA responde al instante.</p>'
        '</article>'
    )

    # Llamada simulada por voz (browser WebRTC, sin telefono): boton en el hero +
    # bloque overlay/JS inyectado como valor (llaves literales, no las parsea el f-string).
    voice_initial = escape((config.get("icono") or config["nombre"][:2] or "IA").upper())
    voice_js_cfg = json.dumps(
        {"api": assets["api_base_url"], "cliente": cliente_id}
    ).replace("</", "<\\/")
    voice_cta_button = (
        '<button type="button" id="vdemoCallBtn" class="cta cta-voice">'
        '📞 Llamar al asistente</button>'
    )
    voice_call_block = (
        VOICE_DEMO_TEMPLATE
        .replace("__VOICE_CFG__", voice_js_cfg)
        .replace("__NOMBRE__", nombre)
        .replace("__INITIAL__", voice_initial)
        .replace("__COLOR__", color)
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Prueba la IA de {nombre} | Vantelia</title>
  <meta name="robots" content="noindex, nofollow" />
  <link rel="icon" type="image/png" href="{favicon_url}" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      color-scheme: dark;
      --bg-1: #0B132B;
      --bg-2: #091028;
      --bg-3: #060c1e;
      --ink: #ffffff;
      --soft: rgba(255,255,255,0.72);
      --muted: rgba(255,255,255,0.55);
      --primary: {color};
      --accent: #00F5D4;
      --line: rgba(255,255,255,0.08);
      --card: rgba(255,255,255,0.04);
      --card-hover: rgba(255,255,255,0.07);
      --radius-lg: 20px;
      --radius-md: 14px;
      --shadow: 0 30px 80px rgba(0,0,0,0.45);
      --font: "Inter", "Segoe UI", system-ui, sans-serif;
      --font-display: "Space Grotesk", "Inter", sans-serif;
    }}

    * {{ box-sizing: border-box; }}

    html, body {{ margin: 0; padding: 0; }}

    body {{
      font-family: var(--font);
      color: var(--ink);
      background:
        linear-gradient(180deg, rgba(11,19,43,0.78) 0%, rgba(9,16,40,0.85) 60%, rgba(6,12,30,0.92) 100%),
        url("{fondo_url}") center top / cover fixed no-repeat,
        var(--bg-1);
      min-height: 100vh;
      overflow-x: hidden;
    }}

    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      background:
        radial-gradient(1200px 700px at 80% -10%, rgba(0,245,212,0.18), transparent 60%),
        radial-gradient(900px 600px at -10% 30%, rgba(0,177,217,0.18), transparent 60%);
      pointer-events: none;
      z-index: 0;
    }}

    .page {{
      position: relative;
      z-index: 1;
      max-width: 1180px;
      margin: 0 auto;
      padding: 56px 24px 140px;
    }}

    /* HERO */
    .hero {{
      text-align: center;
      padding: 40px 16px 24px;
      animation: fadeUp 0.7s ease both;
    }}

    .badge-live {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 14px;
      border-radius: 999px;
      background: rgba(0,245,212,0.08);
      border: 1px solid rgba(0,245,212,0.25);
      font-size: 13px;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 22px;
    }}

    .claim-banner {{
      max-width: 880px;
      margin: 0 auto 28px;
      animation: fadeUp 0.7s ease both;
    }}
    .claim-banner-inner {{
      background: linear-gradient(135deg, rgba(0,245,212,0.17), rgba(0,177,217,0.12));
      border: 1px solid rgba(0,245,212,0.46);
      border-radius: var(--radius-md);
      padding: 18px 20px;
      display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
      justify-content: space-between;
      box-shadow: 0 18px 44px rgba(0,209,255,0.2);
    }}
    .claim-text {{ flex: 1 1 320px; min-width: 0; line-height: 1.5; }}
    .claim-text strong {{ display: block; font-size: 16px; color: var(--ink); }}
    .claim-text span {{ display: block; color: var(--soft); font-size: 13.5px; margin-top: 2px; }}
    .claim-cta {{
      display: inline-flex; align-items: center; gap: 8px;
      padding: 11px 18px;
      background: var(--accent);
      color: #07101f;
      border-radius: 12px;
      text-decoration: none;
      font-weight: 700; font-size: 14px;
      transition: transform .15s ease, box-shadow .15s ease;
      white-space: nowrap;
    }}
    .claim-cta:hover {{ transform: translateY(-1px); box-shadow: 0 10px 24px rgba(0,245,212,0.35); }}

    .badge-live .dot {{
      width: 8px; height: 8px; border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 0 rgba(0,245,212,0.6);
      animation: pulse 1.8s infinite;
    }}

    .hero h1 {{
      font-family: var(--font-display);
      font-weight: 700;
      font-size: clamp(2.2rem, 5vw, 4rem);
      line-height: 1.05;
      margin: 0 0 18px;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #ffffff 0%, #b8e8ff 60%, var(--accent) 100%);
      -webkit-background-clip: text;
      background-clip: text;
      -webkit-text-fill-color: transparent;
    }}

    .hero p.lead {{
      max-width: 720px;
      margin: 0 auto 30px;
      font-size: clamp(1rem, 1.4vw, 1.18rem);
      line-height: 1.6;
      color: var(--soft);
    }}

    .cta {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 14px 28px;
      border: 0;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      font-size: 1rem;
      color: #001018;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      border-radius: 999px;
      box-shadow: 0 12px 30px rgba(0,245,212,0.22);
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }}

    .cta:hover {{
      transform: translateY(-2px);
      box-shadow: 0 18px 40px rgba(0,245,212,0.32);
    }}

    .cta svg {{ width: 18px; height: 18px; }}

    .hero-ctas {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: center;
      align-items: center;
      max-width: 480px;
      margin: 0 auto;
    }}
    .hero-ctas .cta {{ flex: 0 1 auto; }}

    /* STEPS */
    .section {{
      margin-top: 80px;
      animation: fadeUp 0.7s ease both;
    }}

    .section-head {{
      text-align: center;
      margin-bottom: 36px;
    }}

    .section-head h2 {{
      font-family: var(--font-display);
      font-size: clamp(1.5rem, 2.4vw, 2.1rem);
      font-weight: 700;
      margin: 0 0 10px;
      letter-spacing: -0.01em;
    }}

    .section-head p {{
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
    }}

    .steps {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 18px;
    }}

    .step {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 26px 22px;
      transition: transform 0.2s ease, background 0.2s ease, border-color 0.2s ease;
    }}

    .step:hover {{
      transform: translateY(-4px);
      background: var(--card-hover);
      border-color: rgba(0,245,212,0.3);
    }}

    .step-num {{
      width: 38px; height: 38px;
      border-radius: 12px;
      display: grid; place-items: center;
      font-family: var(--font-display);
      font-weight: 700;
      font-size: 1.05rem;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: #001018;
      margin-bottom: 16px;
    }}

    .step h3 {{
      font-family: var(--font-display);
      margin: 0 0 8px;
      font-size: 1.1rem;
      font-weight: 600;
    }}

    .step p {{
      margin: 0;
      color: var(--soft);
      font-size: 0.94rem;
      line-height: 1.55;
    }}

    /* EXAMPLES */
    .examples {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: center;
      max-width: 880px;
      margin: 0 auto;
    }}

    .ex-chip {{
      appearance: none;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      font-size: 0.95rem;
      padding: 12px 18px;
      border-radius: 999px;
      background: rgba(255,255,255,0.05);
      color: var(--ink);
      border: 1px solid var(--line);
      display: inline-flex;
      align-items: center;
      gap: 10px;
      transition: all 0.18s ease;
    }}

    .ex-chip:hover {{
      transform: translateY(-2px);
      border-color: var(--accent);
      background: rgba(0,245,212,0.08);
      color: var(--accent);
    }}

    .ex-icon {{ font-size: 1.1rem; }}

    /* VALUE */
    .value {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 18px;
    }}

    .value-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 28px 24px;
      text-align: left;
    }}

    .value-card .v-icon {{
      width: 44px; height: 44px;
      border-radius: 12px;
      display: grid; place-items: center;
      background: rgba(0,245,212,0.10);
      color: var(--accent);
      margin-bottom: 16px;
      font-size: 1.4rem;
    }}

    .value-card h3 {{
      font-family: var(--font-display);
      margin: 0 0 8px;
      font-size: 1.05rem;
      font-weight: 600;
    }}

    .value-card p {{
      margin: 0;
      color: var(--soft);
      line-height: 1.55;
      font-size: 0.94rem;
    }}

    /* WIDGET POINTER */
    .widget-pointer {{
      position: fixed;
      right: 110px;
      bottom: 36px;
      z-index: 5;
      display: flex;
      align-items: center;
      gap: 10px;
      pointer-events: none;
      animation: fadeIn 0.6s ease 0.8s both;
    }}

    .widget-pointer .tooltip {{
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: #001018;
      font-weight: 700;
      padding: 10px 16px;
      border-radius: 12px;
      font-size: 0.92rem;
      box-shadow: 0 12px 30px rgba(0,0,0,0.4);
      white-space: nowrap;
      animation: bobX 1.6s ease-in-out infinite;
    }}

    .widget-pointer .arrow {{
      font-size: 1.6rem;
      color: var(--accent);
      animation: bobX 1.6s ease-in-out infinite;
      filter: drop-shadow(0 0 10px rgba(0,245,212,0.6));
    }}

    .widget-pointer.hidden {{
      opacity: 0;
      transition: opacity 0.4s ease;
    }}

    /* WIDGET GLOW */
    #ia-w-btn {{
      animation: widgetGlow 2.2s ease-in-out infinite;
    }}

    .footer {{
      margin-top: 80px;
      text-align: center;
      color: var(--muted);
      font-size: 13px;
    }}

    .footer a {{ color: var(--accent); text-decoration: none; }}

    /* ANIMATIONS */
    @keyframes pulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(0,245,212,0.5); }}
      70% {{ box-shadow: 0 0 0 10px rgba(0,245,212,0); }}
      100% {{ box-shadow: 0 0 0 0 rgba(0,245,212,0); }}
    }}

    @keyframes bobX {{
      0%, 100% {{ transform: translateX(0); }}
      50% {{ transform: translateX(8px); }}
    }}

    @keyframes widgetGlow {{
      0%, 100% {{ box-shadow: 0 10px 30px rgba(0,177,217,0.35), 0 0 0 0 rgba(0,245,212,0.5); }}
      50% {{ box-shadow: 0 10px 30px rgba(0,177,217,0.55), 0 0 0 14px rgba(0,245,212,0); }}
    }}

    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(20px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; }}
      to {{ opacity: 1; }}
    }}

    .reveal {{ opacity: 0; transform: translateY(24px); transition: opacity 0.7s ease, transform 0.7s ease; }}
    .reveal.in {{ opacity: 1; transform: translateY(0); }}

    /* RESPONSIVE */
    @media (max-width: 900px) {{
      .steps {{ grid-template-columns: repeat(2, 1fr); }}
      .value {{ grid-template-columns: 1fr; }}
      .widget-pointer {{ right: 96px; bottom: 30px; }}
      .widget-pointer .tooltip {{ font-size: 0.84rem; padding: 8px 12px; }}
    }}

    @media (max-width: 540px) {{
      .page {{ padding: 36px 18px 120px; }}
      .steps {{ grid-template-columns: 1fr; }}
      .widget-pointer .tooltip {{ display: none; }}
      .hero {{ padding: 28px 4px 18px; }}
      .hero-ctas {{ flex-direction: column; align-items: stretch; max-width: 360px; }}
      .hero-ctas .cta {{ width: 100%; justify-content: center; padding: 15px 20px; }}
    }}

    @media (max-width: 768px) {{
      body {{
        background:
          linear-gradient(180deg, rgba(11,19,43,0.78) 0%, rgba(9,16,40,0.85) 60%, rgba(6,12,30,0.92) 100%),
          url("{fondo_movil_url}") center top / cover fixed no-repeat,
          var(--bg-1);
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      {claim_banner}
      <span class="badge-live"><span class="dot"></span>Demo en vivo · {nombre}</span>
      <h1>Prueba la IA de Vantelia en directo</h1>
      <p class="lead">Habla con el asistente como lo harían tus clientes y descubre cómo agenda citas automáticamente.</p>
      <div class="hero-ctas">
        <button type="button" id="ctaProbar" class="cta">
          Probar ahora
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
        </button>
        {voice_cta_button}
      </div>
    </section>

    <section class="section reveal">
      <div class="section-head">
        <h2>Cómo probar la demo</h2>
        <p>Cuatro formas de comprobar lo que la IA puede hacer por tu negocio.</p>
      </div>
      <div class="steps">
        {booking_step}
        <article class="step">
          <div class="step-num">2</div>
          <h3>Pregunta por servicios</h3>
          <p>Descubre qué ofrece, precios, horarios, ubicación. La IA conoce el negocio.</p>
        </article>
        <article class="step">
          <div class="step-num">3</div>
          <h3>Simula ser un cliente</h3>
          <p>Plantea dudas reales, objeciones, comparativas. Mira cómo gestiona la conversación.</p>
        </article>
        <article class="step">
          <div class="step-num">4</div>
          <h3>Cualquier consulta</h3>
          <p>Pregunta lo que quieras. La IA responde con la información del negocio en segundos.</p>
        </article>
      </div>
    </section>

    <section class="section reveal">
      <div class="section-head">
        <h2>Empieza con un ejemplo</h2>
        <p>Pulsa cualquier sugerencia y se enviará al chat automáticamente.</p>
      </div>
      <div class="examples">
        {booking_example}
        <button type="button" class="ex-chip" data-msg="¿Qué servicios ofrecéis?"><span class="ex-icon">💼</span><span>¿Qué servicios ofrecéis?</span></button>
        <button type="button" class="ex-chip" data-msg="¿Cuánto cuesta?"><span class="ex-icon">💶</span><span>¿Cuánto cuesta?</span></button>
        <button type="button" class="ex-chip" data-msg="Quiero reservar una cita"><span class="ex-icon">✅</span><span>Quiero reservar una cita</span></button>
        <button type="button" class="ex-chip" data-msg="¿Cómo funciona vuestro servicio?"><span class="ex-icon">🤔</span><span>¿Cómo funciona?</span></button>
      </div>
    </section>

    <section class="section reveal">
      <div class="section-head">
        <h2>¿Qué está pasando?</h2>
        <p>Detrás de cada respuesta del chat hay un asistente trabajando 24/7.</p>
      </div>
      <div class="value">
        <article class="value-card">
          <div class="v-icon">⚡</div>
          <h3>Responde automáticamente</h3>
          <p>Sin esperas. La IA atiende cualquier consulta en segundos con información actualizada del negocio.</p>
        </article>
        <article class="value-card">
          <div class="v-icon">📅</div>
          <h3>Gestiona citas</h3>
          <p>Comprueba disponibilidad, agenda y confirma reservas sin intervención humana.</p>
        </article>
        <article class="value-card">
          <div class="v-icon">🌙</div>
          <h3>Atiende 24/7</h3>
          <p>Trabaja noches, fines de semana y festivos. No se cansa, no falta y nunca pierde un cliente.</p>
        </article>
      </div>
    </section>

    <div class="footer">
      Tecnología de <a href="https://www.vantelia.es" target="_blank" rel="noreferrer">Vantelia</a> · Asistentes IA para empresas B2B.
    </div>
  </main>

  <div class="widget-pointer" id="widgetPointer" aria-hidden="true">
    <div class="tooltip">Empieza aquí</div>
    <div class="arrow">➜</div>
  </div>

  <script>
    window.IA_WIDGET_API = "{api_base_url}";
    window.IA_WIDGET_CLIENTE = "{cliente_safe}";
  </script>
  <script
    src="{script_url}"
    data-api="{api_base_url}"
    data-client="{cliente_safe}"
    data-position="right"></script>
  <script>
    (function () {{
      function widgetReady() {{
        return !!document.getElementById("ia-w-btn");
      }}

      function whenWidgetReady(cb) {{
        let attempts = 0;
        (function check() {{
          if (widgetReady()) return cb();
          if (attempts++ < 40) setTimeout(check, 150);
        }})();
      }}

      function openWidget() {{
        const btn = document.getElementById("ia-w-btn");
        if (!btn) return false;
        if (btn.getAttribute("aria-expanded") !== "true") btn.click();
        return true;
      }}

      function trackDemoEvent(event, payload) {{
        try {{
          fetch("/analytics/event", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            keepalive: true,
            body: JSON.stringify(Object.assign({{
              event: event,
              event_source: "demo_page",
              page_path: window.location.pathname,
              page_url: window.location.href,
              cliente_id: "{cliente_safe}"
            }}, payload || {{}}))
          }}).catch(function () {{}});
        }} catch (_) {{}}
      }}

      function sendToWidget(message) {{
        whenWidgetReady(function () {{
          openWidget();
          setTimeout(function () {{
            const input = document.getElementById("ia-w-input");
            const send = document.getElementById("ia-w-send");
            if (!input || !send) return;
            input.value = message;
            input.dispatchEvent(new Event("input", {{ bubbles: true }}));
            send.click();
          }}, 380);
        }});
      }}

      function flashWidget() {{
        const btn = document.getElementById("ia-w-btn");
        if (!btn) return;
        btn.style.transition = "transform 0.4s ease";
        btn.style.transform = "scale(1.18)";
        setTimeout(function () {{ btn.style.transform = ""; }}, 420);
      }}

      function hidePointer() {{
        const p = document.getElementById("widgetPointer");
        if (p) p.classList.add("hidden");
      }}

      document.getElementById("ctaProbar")?.addEventListener("click", function () {{
        whenWidgetReady(function () {{
          openWidget();
          flashWidget();
          hidePointer();
        }});
      }});

      document.querySelector("[data-claim-cta]")?.addEventListener("click", function (ev) {{
        trackDemoEvent("demo_claim_clicked", {{
          cta_label: "Activar gratis e instalar",
          cta_href: ev.currentTarget.href
        }});
      }});

      document.querySelectorAll(".ex-chip").forEach(function (chip) {{
        chip.addEventListener("click", function () {{
          const msg = chip.getAttribute("data-msg") || "";
          if (!msg) return;
          sendToWidget(msg);
          hidePointer();
        }});
      }});

      whenWidgetReady(function () {{
        const btn = document.getElementById("ia-w-btn");
        btn?.addEventListener("click", hidePointer, {{ once: true }});
      }});

      const io = new IntersectionObserver(function (entries) {{
        entries.forEach(function (e) {{
          if (e.isIntersecting) {{
            e.target.classList.add("in");
            io.unobserve(e.target);
          }}
        }});
      }}, {{ threshold: 0.12 }});
      document.querySelectorAll(".reveal").forEach(function (el) {{ io.observe(el); }});
    }})();
  </script>
  {voice_call_block}
</body>
</html>
"""


DEMO_EMPLOYEE_ID_PREFIX = "empdemo_"


DEMO_BOOKING_SOURCE = "demo_seed"


def _sync_demo_bookings_for_service(
    cliente_id: str,
    *,
    old_slug: str,
    old_name: str,
    service_row: sqlite3.Row,
) -> int:
    duration = int(service_row["duration_minutes"] or 0)
    if duration <= 0:
        return 0
    service_slug = service_row["slug"] or old_slug
    service_name = service_row["name"] or old_name
    service_price = int(service_row["price_cents"] or 0)
    updated = 0
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM bookings
            WHERE cliente_id = ? AND source = ?
              AND (service_id IN (?, ?) OR servicio IN (?, ?))
            """,
            (cliente_id, DEMO_BOOKING_SOURCE, old_slug, service_slug, old_name, service_name),
        ).fetchall()
        for booking in rows:
            timezone_name = booking["timezone"] or clients._get_client_config(cliente_id)["booking"]["timezone"]
            try:
                tzinfo = ZoneInfo(timezone_name)
            except Exception:  # noqa: BLE001
                tzinfo = ZoneInfo(settings.DEFAULT_TIMEZONE)
                timezone_name = settings.DEFAULT_TIMEZONE
            start_local = datetime.fromisoformat(
                f"{booking['booking_date']}T{booking['booking_time']}:00"
            ).replace(tzinfo=tzinfo)
            end_local = start_local + timedelta(minutes=duration)
            connection.execute(
                """
                UPDATE bookings
                SET servicio = ?, service_id = ?, service_price_cents = ?,
                    timezone = ?, start_at = ?, end_at = ?
                WHERE id = ?
                """,
                (
                    service_name,
                    service_slug,
                    service_price,
                    timezone_name,
                    timeutils._to_utc_iso(start_local),
                    timeutils._to_utc_iso(end_local),
                    booking["id"],
                ),
            )
            updated += 1
        connection.commit()
    return updated


_DEMO_PROFESSIONALS = [
    {"name": "Laura Fernandez", "role_label": "Profesional", "color": "#00b1d9"},
    {"name": "Carlos Ruiz", "role_label": "Profesional", "color": "#7c5cff"},
    {"name": "Marta Gomez", "role_label": "Profesional", "color": "#f4795b"},
]


_DEMO_CUSTOMER_NAMES = [
    "Ana Martinez", "Javier Lopez", "Lucia Sanchez", "Miguel Torres",
    "Elena Diaz", "Pablo Romero", "Sara Jimenez", "David Moreno",
    "Carmen Ortega", "Sergio Navarro", "Marina Castro", "Alberto Gil",
    "Raquel Vidal", "Hugo Ramos", "Patricia Iglesias", "Daniel Santos",
    "Cristina Molina", "Adrian Herrera", "Beatriz Flores", "Ruben Cano",
]


_DEMO_FALLBACK_SERVICES = [
    "Primera consulta", "Revision", "Sesion de seguimiento", "Consulta general",
]


def _is_bookable_demo_service(service: Dict[str, Any]) -> bool:
    nombre = str(service.get("nombre") or service.get("name") or "").strip().lower()
    descripcion = str(service.get("descripcion") or service.get("description") or "").strip().lower()
    text = f"{nombre} {descripcion}"
    if not nombre:
        return False
    discount_markers = ("bono", "bonos", "descuento", "dto", "%")
    return not any(marker in text for marker in discount_markers)


def _demo_service_names(cliente_id: str) -> List[str]:
    return [service["nombre"] for service in _demo_services(cliente_id)]


def _demo_services(cliente_id: str) -> List[Dict[str, Any]]:
    services: List[Dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for service in agenda._catalog_services(cliente_id):
            nombre = str(service.get("nombre") or "").strip()
            if nombre and nombre not in seen and _is_bookable_demo_service(service):
                services.append(service)
                seen.add(nombre)
    except Exception:  # noqa: BLE001
        services = []
        seen = set()
    if services:
        return services[:12]
    try:
        for service in agenda._extract_services_from_info(cliente_id):
            nombre = str(service.get("nombre") or "").strip()
            if nombre and nombre not in seen and _is_bookable_demo_service(service):
                services.append(service)
                seen.add(nombre)
    except Exception:  # noqa: BLE001
        services = []
    if not services:
        services = [
            {"id": agenda._normalize_service_id(name), "nombre": name, "duration_minutes": 0, "price_cents": 0}
            for name in _DEMO_FALLBACK_SERVICES
        ]
    return services[:12]


def _purge_demo_agenda(cliente_id: str) -> Dict[str, int]:
    """Borra todos los datos demo (bookings + empleados demo) de un cliente."""
    with db._get_db_connection() as connection:
        booking_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM bookings WHERE cliente_id = ? AND source = ?",
                (cliente_id, DEMO_BOOKING_SOURCE),
            ).fetchall()
        ]
        if booking_ids:
            placeholders = ",".join("?" for _ in booking_ids)
            connection.execute(
                f"DELETE FROM booking_audit WHERE cliente_id = ? AND booking_id IN ({placeholders})",
                (cliente_id, *booking_ids),
            )
        bookings_removed = connection.execute(
            "DELETE FROM bookings WHERE cliente_id = ? AND source = ?",
            (cliente_id, DEMO_BOOKING_SOURCE),
        ).rowcount
        employees_removed = connection.execute(
            "DELETE FROM employees WHERE cliente_id = ? AND id LIKE ?",
            (cliente_id, f"{DEMO_EMPLOYEE_ID_PREFIX}%"),
        ).rowcount
        connection.execute(
            "DELETE FROM agenda_blocks WHERE cliente_id = ? AND employee_id LIKE ?",
            (cliente_id, f"{DEMO_EMPLOYEE_ID_PREFIX}%"),
        )
        connection.commit()
    return {
        "bookings_removed": int(bookings_removed or 0),
        "employees_removed": int(employees_removed or 0),
    }


def _create_demo_employees(cliente_id: str) -> List[Dict[str, Any]]:
    defaults = agenda._employee_defaults_for_client(cliente_id)
    created_at = timeutils._utc_now_iso()
    closed_json = json.dumps(defaults["closed_weekdays"])
    break_windows_json = json.dumps(defaults.get("break_windows", []))
    employees: List[Dict[str, Any]] = []
    with db._get_db_connection() as connection:
        for profile in _DEMO_PROFESSIONALS:
            employee_id = f"{DEMO_EMPLOYEE_ID_PREFIX}{secrets.token_urlsafe(6)}"
            connection.execute(
                """
                INSERT INTO employees (
                    id, cliente_id, name, role_label, color, is_active, is_default,
                    timezone, slot_minutes, day_start, day_end, break_start, break_end,
                    break_windows_json, closed_weekdays_json, service_ids_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)
                """,
                (
                    employee_id, cliente_id, profile["name"], profile["role_label"], profile["color"],
                    defaults["timezone"], int(defaults["slot_minutes"]),
                    defaults["day_start"], defaults["day_end"],
                    defaults["break_start"], defaults["break_end"], break_windows_json, closed_json,
                    created_at, created_at,
                ),
            )
            employees.append({"id": employee_id, "name": profile["name"], "color": profile["color"]})
        connection.commit()
    return employees


def _seed_demo_agenda(cliente_id: str) -> Dict[str, Any]:
    """Genera ~1 mes de citas demo repartidas entre varios profesionales.

    Idempotente: limpia datos demo previos antes de regenerar. Todas las citas
    quedan marcadas con source='demo_seed' y los profesionales con id 'empdemo_*'
    para poder borrarlas despues sin tocar datos reales del cliente.
    """
    _purge_demo_agenda(cliente_id)

    defaults = agenda._employee_defaults_for_client(cliente_id)
    tz_name = defaults["timezone"] or settings.DEFAULT_TIMEZONE
    slot_minutes = max(10, int(defaults["slot_minutes"] or 30))
    closed_weekdays = set(defaults["closed_weekdays"] or [])
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
        tz_name = "UTC"

    start_dt = textnorm._parse_time(defaults["day_start"] or "09:00")
    end_dt = textnorm._parse_time(defaults["day_end"] or "18:00")
    break_intervals = agenda._break_intervals_from_windows(defaults.get("break_windows", []))
    day_slots: List[str] = []
    cursor = start_dt
    while cursor + timedelta(minutes=slot_minutes) <= end_dt:
        slot = cursor.strftime("%H:%M")
        slot_start_min = textnorm._time_to_min(slot)
        slot_end_min = (slot_start_min + slot_minutes) if slot_start_min is not None else None
        if (
            slot_start_min is not None
            and slot_end_min is not None
            and not agenda._interval_overlaps(slot_start_min, slot_end_min, break_intervals)
        ):
            day_slots.append(slot)
        cursor += timedelta(minutes=slot_minutes)
    if not day_slots:
        day_slots = ["10:00", "11:00", "12:00", "16:00", "17:00"]

    employees = _create_demo_employees(cliente_id)
    services = _demo_services(cliente_id)
    today = datetime.now(tz).date()
    rng = random.Random(f"{cliente_id}:{today.isoformat()}")
    created_at = timeutils._utc_now_iso()
    bookings_created = 0
    max_bookings = 350
    end_day_min = textnorm._time_to_min(end_dt.strftime("%H:%M")) or (24 * 60)
    occupied_by_employee_day: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}

    for offset in range(-7, 29):  # ~5 semanas alrededor de hoy
        day = today + timedelta(days=offset)
        if day.weekday() in closed_weekdays:
            continue
        is_past = day < today
        for emp in employees:
            sample_size = max(1, int(len(day_slots) * rng.uniform(0.25, 0.55)))
            chosen = rng.sample(day_slots, min(sample_size, len(day_slots)))
            for hora in chosen:
                if bookings_created >= max_bookings:
                    break
                service = rng.choice(services)
                service_name = str(service.get("nombre") or service.get("name") or "Consulta general").strip()
                service_id = str(service.get("id") or service.get("slug") or agenda._normalize_service_id(service_name))
                try:
                    service_duration = int(service.get("duration_minutes") or 0)
                except (TypeError, ValueError):
                    service_duration = 0
                if service_duration <= 0:
                    # Si el servicio no tiene duración definida, asignar una duración
                    # realista y variada para que el demo no quede monótono.
                    _DEMO_DURATION_POOL = [30, 45, 60, 45, 75, 30, 60, 90, 45, 60]
                    service_duration = _DEMO_DURATION_POOL[
                        hash(service_name) % len(_DEMO_DURATION_POOL)
                    ]
                try:
                    service_price = int(service.get("price_cents") or 0)
                except (TypeError, ValueError):
                    service_price = 0
                start_min = textnorm._time_to_min(hora)
                if start_min is None:
                    continue
                end_min = start_min + service_duration
                if end_min > end_day_min:
                    continue
                if agenda._interval_overlaps(start_min, end_min, break_intervals):
                    continue
                occupied_key = (emp["id"], day.isoformat())
                occupied = occupied_by_employee_day.setdefault(occupied_key, [])
                if any(start_min < busy_end and end_min > busy_start for busy_start, busy_end in occupied):
                    continue
                start_local = datetime.fromisoformat(f"{day.isoformat()}T{hora}:00").replace(tzinfo=tz)
                end_local = start_local + timedelta(minutes=service_duration)
                if is_past:
                    status_value = "cancelled" if rng.random() < 0.18 else "completed"
                else:
                    status_value = "pending_review" if rng.random() < 0.2 else "confirmed"
                booking_id = secrets.token_urlsafe(16)
                record = {
                    "id": booking_id,
                    "cliente_id": cliente_id,
                    "employee_id": emp["id"],
                    "employee_name": emp["name"],
                    "nombre": rng.choice(_DEMO_CUSTOMER_NAMES),
                    "email": f"demo+{booking_id[:8].lower()}@example.com",
                    "telefono": f"+34 6{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
                    "servicio": service_name,
                    "booking_date": day.isoformat(),
                    "booking_time": hora,
                    "notas": "Cita de demostracion",
                    "status": status_value,
                    "provider_name": "internal",
                    "provider_status": status_value,
                    "provider_booking_id": "",
                    "provider_booking_url": "",
                    "manage_token": booking._generate_manage_token(),
                    "timezone": tz_name,
                    "start_at": timeutils._to_utc_iso(start_local),
                    "end_at": timeutils._to_utc_iso(end_local),
                    "confirmed_at": created_at if status_value in ("confirmed", "completed") else "",
                    "cancelled_at": created_at if status_value == "cancelled" else "",
                    **booking._booking_blank_tracking_fields(),
                    "service_id": service_id,
                    "service_price_cents": service_price,
                    "source": DEMO_BOOKING_SOURCE,
                    "created_at": created_at,
                }
                try:
                    booking._store_booking(record)
                except sqlite3.IntegrityError:
                    continue
                occupied.append((start_min, end_min))
                bookings_created += 1
        if bookings_created >= max_bookings:
            break

    return {
        "employees_created": len(employees),
        "bookings_created": bookings_created,
        "timezone": tz_name,
    }




_DEMO_SECTOR_DEFAULTS: Dict[str, tuple] = {
    "centro de masajes": ("Centro de masajes y bienestar.", "Masajes terapeuticos, relajantes y descontracturantes. Reserva de sesiones."),
    "clinica dental": ("Clinica dental.", "Revisiones, limpiezas, ortodoncia, implantes y estetica dental."),
    "clinica estetica": ("Centro de estetica y belleza.", "Tratamientos faciales, corporales y de belleza."),
    "fisioterapia": ("Clinica de fisioterapia.", "Fisioterapia, rehabilitacion y recuperacion de lesiones."),
    "peluqueria": ("Peluqueria y salon de belleza.", "Corte, color, peinado y tratamientos capilares."),
    "centro veterinario": ("Centro veterinario.", "Consultas, vacunaciones, cirugia y urgencias veterinarias."),
}

