/* Vantelia · home/site UI scripts */

/* Conversion measurement */
(function () {
  const DEBUG_KEY = 'vantelia_analytics_debug';
  const CONSENT_KEY = 'vantelia_cookie_consent_v1';
  const SERVER_ENDPOINT = window.VANTELIA_ANALYTICS_ENDPOINT || 'https://app.vantelia.es/analytics/event';
  const PAGE_SESSION_ID = 'pv_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);

  function readConsent() {
    if (window.vanteliaConsent) return window.vanteliaConsent;
    try {
      const raw = localStorage.getItem(CONSENT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function hasAnalyticsConsent() {
    const consent = readConsent();
    return !!(consent && consent.analytics);
  }

  function applyGoogleConsent(state) {
    if (typeof window.gtag !== 'function') return;
    window.gtag('consent', 'update', {
      analytics_storage: state && state.analytics ? 'granted' : 'denied',
      ad_storage: state && state.marketing ? 'granted' : 'denied',
      ad_user_data: state && state.marketing ? 'granted' : 'denied',
      ad_personalization: state && state.marketing ? 'granted' : 'denied',
    });
  }

  function cleanPayload(payload) {
    const out = {};
    Object.keys(payload || {}).forEach((key) => {
      const value = payload[key];
      if (value === undefined || value === null || value === '') return;
      out[key] = value;
    });
    return out;
  }

  function track(eventName, payload) {
    if (!eventName) return;
    const event = {
      event: eventName,
      event_source: 'vantelia_site',
      page_path: window.location.pathname,
      page_url: window.location.href,
      session_id: PAGE_SESSION_ID,
      timestamp: new Date().toISOString(),
      ...cleanPayload(payload || {}),
    };

    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push(event);
    sendServerEvent(event);

    if (hasAnalyticsConsent()) {
      if (typeof window.gtag === 'function') {
        const { event: _eventName, ...params } = event;
        window.gtag('event', eventName, params);
      }
      if (typeof window.fbq === 'function') {
        window.fbq('trackCustom', eventName, event);
      }
    }

    try {
      if (localStorage.getItem(DEBUG_KEY) === '1') {
        console.info('[Vantelia analytics]', eventName, event);
      }
    } catch (_) { }

    document.dispatchEvent(new CustomEvent('vantelia:tracked', { detail: event }));
  }

  function sendServerEvent(event) {
    try {
      const body = JSON.stringify(event);
      if (navigator.sendBeacon) {
        const blob = new Blob([body], { type: 'application/json' });
        if (navigator.sendBeacon(SERVER_ENDPOINT, blob)) return;
      }
      fetch(SERVER_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true,
      }).catch(() => { });
    } catch (_) { }
  }

  function ctaLabel(el) {
    return (el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 120);
  }

  document.addEventListener('click', (event) => {
    const link = event.target.closest && event.target.closest('a,button');
    if (!link) return;
    const href = link.getAttribute('href') || '';
    const label = ctaLabel(link);

    if (link.classList && link.classList.contains('plan-cta')) {
      track('plan_cta_click', {
        cta_label: label,
        cta_href: href,
        plan: link.getAttribute('data-plan') || '',
        plan_label: link.getAttribute('data-plan-label') || '',
      });
      track('signup_clicked', {
        cta_label: label,
        cta_href: href,
        plan: link.getAttribute('data-plan') || '',
        plan_label: link.getAttribute('data-plan-label') || '',
        source: 'pricing_card',
      });
    } else if (link.hasAttribute && link.hasAttribute('data-open-chat')) {
      track('chat_consultation_cta_click', {
        cta_label: label,
        cta_location: link.getAttribute('data-cta-location') || '',
      });
    } else if (href.includes('/demo/')) {
      track('demo_cta_click', { cta_label: label, cta_href: href });
    } else if (href.includes('/consultas/')) {
      track('consultation_cta_click', { cta_label: label, cta_href: href });
    } else if (href.includes('app.vantelia.es/acceso')) {
      track('portal_access_click', { cta_label: label, cta_href: href });
      track('signup_clicked', { cta_label: label, cta_href: href, source: 'site_cta' });
    }
  }, true);

  document.addEventListener('vantelia:widget', (event) => {
    const detail = event.detail || {};
    track(detail.event || 'widget_event', detail);
  });

  window.vanteliaTrack = track;

  document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname || '/';
    track('landing_view', {
      source: 'page_load',
      page_type: path === '/' ? 'home' : path.replace(/^\/|\/$/g, '') || 'home',
    });
    if (/\/planes\/?$/i.test(path)) {
      track('pricing_viewed', { source: 'page_load' });
    }
  });
})();

/* Particle canvas (only when canvas exists; skip on mobile/reduced-motion,
   pause when hero is off-screen) */
(function () {
  const canvas = document.getElementById('particles');
  if (!canvas) return;
  if (window.innerWidth <= 768) return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const ctx = canvas.getContext('2d');
  let pts = [], raf, running = false;

  function resize() {
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
  }
  function Pt() {
    this.x = Math.random() * canvas.width;
    this.y = Math.random() * canvas.height;
    this.vx = (Math.random() - .5) * .38;
    this.vy = (Math.random() - .5) * .38;
    this.r = Math.random() * 1.4 + .5;
    this.o = Math.random() * .45 + .1;
  }
  Pt.prototype.tick = function () {
    this.x += this.vx; this.y += this.vy;
    if (this.x < 0 || this.x > canvas.width) this.vx *= -1;
    if (this.y < 0 || this.y > canvas.height) this.vy *= -1;
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0,209,255,' + this.o + ')';
    ctx.fill();
  };
  function init() {
    const n = Math.min(90, Math.floor(canvas.width * canvas.height / 11000));
    pts = Array.from({ length: n }, () => new Pt());
  }
  function lines() {
    const d = 130;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < d) {
          ctx.beginPath();
          ctx.moveTo(pts[i].x, pts[i].y);
          ctx.lineTo(pts[j].x, pts[j].y);
          ctx.strokeStyle = 'rgba(0,209,255,' + (1 - dist / d) * .11 + ')';
          ctx.lineWidth = .5;
          ctx.stroke();
        }
      }
    }
  }
  function draw() {
    if (!running) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    pts.forEach(p => p.tick());
    lines();
    raf = requestAnimationFrame(draw);
  }
  function start() { if (running) return; running = true; draw(); }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf); }
  window.addEventListener('resize', () => { resize(); init(); }, { passive: true });
  resize(); init();
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (ents) {
      ents.forEach(function (e) { if (e.isIntersecting) start(); else stop(); });
    }, { threshold: 0.05 }).observe(canvas);
  } else {
    start();
  }
})();

/* Header on scroll */
(function () {
  const hdr = document.getElementById('site-header');
  if (!hdr) return;
  window.addEventListener('scroll', () => {
    hdr.classList.toggle('scrolled', window.scrollY > 20);
  }, { passive: true });
})();

/* Mobile menu */
(function () {
  const toggle = document.getElementById('nav-toggle');
  const menu = document.getElementById('mobile-menu');
  const close = document.getElementById('mobile-close');
  if (!toggle || !menu || !close) return;
  let lastFocused = null;
  const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  menu.setAttribute('aria-hidden', 'true');
  menu.setAttribute('aria-modal', 'true');

  function focusableItems() {
    return Array.from(menu.querySelectorAll(focusableSelector)).filter(el => el.offsetParent !== null);
  }

  function openMenu() {
    lastFocused = document.activeElement;
    menu.classList.add('open');
    menu.setAttribute('aria-hidden', 'false');
    toggle.setAttribute('aria-expanded', 'true');
    document.body.classList.add('mobile-nav-open');
    const first = focusableItems()[0] || close;
    first.focus({ preventScroll: true });
  }
  function closeMenu() {
    const wasOpen = menu.classList.contains('open');
    menu.classList.remove('open');
    menu.setAttribute('aria-hidden', 'true');
    toggle.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('mobile-nav-open');
    if (wasOpen && lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus({ preventScroll: true });
    }
  }
  toggle.addEventListener('click', () => {
    if (menu.classList.contains('open')) closeMenu();
    else openMenu();
  });
  close.addEventListener('click', closeMenu);
  menu.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenu));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      closeMenu();
      return;
    }
    if (e.key !== 'Tab' || !menu.classList.contains('open')) return;
    const items = focusableItems();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
  window.addEventListener('resize', () => { if (window.innerWidth > 768) closeMenu(); }, { passive: true });
})();

/* Scroll reveal */
(function () {
  const els = document.querySelectorAll('.reveal');
  if (!els.length || !('IntersectionObserver' in window)) return;
  const ro = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('visible'); ro.unobserve(e.target); }
    });
  }, { threshold: .12, rootMargin: '0px 0px -36px 0px' });
  els.forEach(el => ro.observe(el));
})();

/* Animated counters */
(function () {
  function animCount(el) {
    const target = parseInt(el.dataset.count, 10);
    const suffix = el.dataset.suffix || '';
    const dur = 1800;
    const start = performance.now();
    (function step(now) {
      const p = Math.min((now - start) / dur, 1);
      const e = 1 - Math.pow(1 - p, 3);
      el.textContent = (e < 1 ? '+' : (suffix === '%' ? '' : '+')) + Math.round(e * target) + suffix;
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = (suffix === '%' ? '' : '+') + target + suffix;
    })(start);
  }
  const els = document.querySelectorAll('[data-count]');
  if (!els.length || !('IntersectionObserver' in window)) return;
  const co = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting && e.target.dataset.count) { animCount(e.target); co.unobserve(e.target); }
    });
  }, { threshold: .5 });
  els.forEach(el => co.observe(el));
})();

/* FAQ accordion */
(function () {
  document.querySelectorAll('.faq-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.faq-item');
      const isOpen = item.classList.contains('open');
      document.querySelectorAll('.faq-item.open').forEach(i => {
        i.classList.remove('open');
        i.querySelector('.faq-btn').setAttribute('aria-expanded', 'false');
      });
      if (!isOpen) { item.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); }
    });
  });
})();

/* Cursor ambient glow (desktop only) */
(function () {
  if (window.innerWidth <= 768) return;
  const glow = document.getElementById('cursor-glow');
  if (!glow) return;
  let mx = 0, my = 0, gx = 0, gy = 0;
  document.addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; });
  (function tick() {
    gx += (mx - gx) * .07; gy += (my - gy) * .07;
    glow.style.left = gx + 'px'; glow.style.top = gy + 'px';
    requestAnimationFrame(tick);
  })();
})();

/* Smooth scroll for in-page #anchors only on home */
(function () {
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    a.addEventListener('click', e => {
      const href = a.getAttribute('href');
      if (!href || href === '#') return;
      const t = document.querySelector(href);
      if (t) { e.preventDefault(); t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    });
  });
})();

/* ========================================================
   Cookie consent banner (RGPD)
   - Aparece en primera visita, persiste eleccion en localStorage.
   - Aceptar = activa cookies analiticas/marketing (window.vanteliaConsent.analytics).
   - Rechazar = solo cookies tecnicas estrictas.
   - Configurar = abre /legal/cookies/ para detalle.
   - Reabrir desde footer: window.openCookiePreferences().
   ======================================================== */
(function () {
  const STORAGE_KEY = 'vantelia_cookie_consent_v1';
  const PRIVACY_URL = '/legal/cookies/';

  function applyGoogleConsent(state) {
    if (typeof window.gtag !== 'function') return;
    window.gtag('consent', 'update', {
      analytics_storage: state && state.analytics ? 'granted' : 'denied',
      ad_storage: state && state.marketing ? 'granted' : 'denied',
      ad_user_data: state && state.marketing ? 'granted' : 'denied',
      ad_personalization: state && state.marketing ? 'granted' : 'denied',
    });
  }

  function readConsent() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function writeConsent(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        analytics: !!state.analytics,
        marketing: !!state.marketing,
        ts: new Date().toISOString(),
      }));
    } catch (_) { }
    window.vanteliaConsent = {
      analytics: !!state.analytics,
      marketing: !!state.marketing,
    };
    try { applyGoogleConsent(window.vanteliaConsent); } catch (_) { }
    try {
      document.dispatchEvent(new CustomEvent('vantelia:consent', { detail: window.vanteliaConsent }));
    } catch (_) { }
  }

  function closeWithConsent(wrap, state) {
    if (wrap && typeof wrap.remove === 'function') wrap.remove();
    writeConsent(state);
  }

  function injectStyles() {
    if (document.getElementById('vantelia-cc-styles')) return;
    const css = `
      .vantelia-cc {
        position: fixed; left: 16px; right: 16px; bottom: 16px;
        z-index: 99999;
        max-width: 760px; margin: 0 auto;
        background: rgba(8,16,42,0.96);
        backdrop-filter: blur(14px);
        border: 1px solid rgba(0,209,255,0.28);
        border-radius: 16px;
        padding: 18px 20px;
        color: #F0F4F8;
        font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
        font-size: 14px;
        line-height: 1.55;
        box-shadow: 0 22px 60px rgba(0,0,0,0.42);
        animation: vantelia-cc-rise .35s ease-out;
      }
      @keyframes vantelia-cc-rise {
        from { transform: translateY(20px); opacity: 0; }
        to   { transform: translateY(0); opacity: 1; }
      }
      .vantelia-cc h3 {
        margin: 0 0 6px;
        font-family: 'Space Grotesk','Inter',sans-serif;
        font-size: 16px; font-weight: 700; color: #FFF;
      }
      .vantelia-cc p { margin: 0 0 14px; color: #C7D5E2; }
      .vantelia-cc a { color: #00D1FF; text-decoration: underline; }
      .vantelia-cc .vantelia-cc-actions {
        display: flex; gap: 10px; flex-wrap: wrap;
      }
      .vantelia-cc button {
        font: inherit; font-weight: 600;
        padding: 9px 18px; border-radius: 999px;
        cursor: pointer; border: 1px solid transparent;
        transition: transform .12s, background .15s, border-color .15s;
      }
      .vantelia-cc button:hover { transform: translateY(-1px); }
      .vantelia-cc .cc-accept {
        background: linear-gradient(135deg,#00D1FF,#00F5D4);
        color: #06121f;
      }
      .vantelia-cc .cc-reject {
        background: rgba(255,255,255,0.04);
        color: #F0F4F8;
        border-color: rgba(255,255,255,0.18);
      }
      .vantelia-cc .cc-config {
        background: transparent;
        color: #C7D5E2;
        border-color: rgba(255,255,255,0.14);
      }
      @media (max-width: 560px) {
        .vantelia-cc { left: 8px; right: 8px; bottom: 8px; padding: 14px 16px; }
        .vantelia-cc h3 { font-size: 15px; }
        .vantelia-cc .vantelia-cc-actions { flex-direction: column; }
        .vantelia-cc button { width: 100%; }
      }
    `;
    const style = document.createElement('style');
    style.id = 'vantelia-cc-styles';
    style.textContent = css;
    document.head.appendChild(style);
  }

  function build() {
    injectStyles();
    const wrap = document.createElement('div');
    wrap.className = 'vantelia-cc';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-live', 'polite');
    wrap.setAttribute('aria-label', 'Aviso de cookies');
    wrap.innerHTML = `
      <h3>Cookies en Vantelia</h3>
      <p>Usamos cookies tecnicas necesarias para que la web funcione. Las analiticas y de marketing son opcionales y solo se activan si las aceptas. Mas info en nuestra <a href="${PRIVACY_URL}">politica de cookies</a>.</p>
      <div class="vantelia-cc-actions">
        <button type="button" class="cc-accept">Aceptar todas</button>
        <button type="button" class="cc-reject">Solo necesarias</button>
        <a class="cc-config" href="${PRIVACY_URL}" style="display:inline-flex;align-items:center;padding:9px 18px;border-radius:999px;text-decoration:none;border:1px solid rgba(255,255,255,0.14);color:#C7D5E2;">Configurar</a>
      </div>
    `;
    wrap.querySelector('.cc-accept').addEventListener('click', () => {
      closeWithConsent(wrap, { analytics: true, marketing: true });
    });
    wrap.querySelector('.cc-reject').addEventListener('click', () => {
      closeWithConsent(wrap, { analytics: false, marketing: false });
    });
    document.body.appendChild(wrap);
  }

  function init() {
    const existing = readConsent();
    if (existing) {
      window.vanteliaConsent = {
        analytics: !!existing.analytics,
        marketing: !!existing.marketing,
      };
      applyGoogleConsent(window.vanteliaConsent);
      return;
    }
    build();
  }

  window.openCookiePreferences = function () {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) { }
    const old = document.querySelector('.vantelia-cc');
    if (old) old.remove();
    build();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

/* ════════════════════════════════════════════════
   Hero mock — 3 canales: chat / reservas / voz
   ════════════════════════════════════════════════ */
(function () {
  var chat = document.getElementById('mwChat');
  var tabsWrap = document.getElementById('mockTabs');
  if (!chat || !tabsWrap) return;

  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var tabs = Array.prototype.slice.call(tabsWrap.querySelectorAll('.mock-tab'));
  var panes = Array.prototype.slice.call(document.querySelectorAll('.mock-pane'));
  var barLabel = document.getElementById('mockBarLabel');
  var BAR_LABELS = { chat: 'tunegocio.es', book: 'tunegocio.es/reservas', voice: 'Tu línea · IA' };

  /* ---------- helpers chat ---------- */
  function scrollChat() { chat.scrollTop = chat.scrollHeight; }
  function addBubble(who, text) {
    var b = document.createElement('div');
    b.className = 'mw-bubble ' + who;
    if (who === 'confirm') b.innerHTML = text; else b.textContent = text;
    chat.appendChild(b); scrollChat(); return b;
  }
  function showTyping(ms, cb) {
    var t = document.createElement('div');
    t.className = 'mw-bubble typing';
    t.innerHTML = '<span></span><span></span><span></span>';
    chat.appendChild(t); scrollChat();
    setTimeout(function () { t.remove(); cb(); }, ms);
  }
  function buildOptions() {
    var card = document.createElement('div');
    card.className = 'mw-card';
    card.innerHTML = '<p class="mw-card-title">¿En qué te ayudo?</p><div class="mw-opts"></div>';
    var box = card.querySelector('.mw-opts');
    [
      { icon: '📅', label: 'Reservar cita' },
      { icon: '💳', label: 'Pagar mi reserva' },
      { icon: '❓', label: 'Preguntas frecuentes' }
    ].forEach(function (it) {
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'mw-opt';
      btn.innerHTML = '<em>' + it.icon + '</em> <span>' + it.label + '</span>';
      box.appendChild(btn);
    });
    chat.appendChild(card); scrollChat();
    return card.querySelectorAll('.mw-opt');
  }
  function buildCalendar() {
    var card = document.createElement('div');
    card.className = 'mw-card';
    card.innerHTML = '<p class="mw-card-title">📅 Elige día</p><div class="mw-cal"></div>';
    var cal = card.querySelector('.mw-cal');
    [
      { dow: 'Lun', n: 19, dis: true },
      { dow: 'Mar', n: 20, dis: false },
      { dow: 'Mié', n: 21, dis: false },
      { dow: 'Jue', n: 22, dis: false },
      { dow: 'Vie', n: 23, dis: false },
      { dow: 'Sáb', n: 24, dis: true },
      { dow: 'Dom', n: 25, dis: true },
      { dow: 'Lun', n: 26, dis: false }
    ].forEach(function (d) {
      var el = document.createElement('div');
      el.className = 'mw-cal-day' + (d.dis ? ' is-disabled' : '');
      el.innerHTML = d.dow + '<b>' + d.n + '</b>';
      el.dataset.label = d.dow + ' ' + d.n;
      cal.appendChild(el);
    });
    chat.appendChild(card); scrollChat();
    return card.querySelectorAll('.mw-cal-day:not(.is-disabled)');
  }
  function buildSlots(dayLabel) {
    var card = document.createElement('div');
    card.className = 'mw-card';
    card.innerHTML = '<p class="mw-card-title">🕐 Huecos disponibles</p><p class="mw-card-sub">' + dayLabel + '</p><div class="mw-slots"></div>';
    var box = card.querySelector('.mw-slots');
    ['10:00', '11:30', '12:30', '17:00', '18:30'].forEach(function (h) {
      var sp = document.createElement('span');
      sp.className = 'mw-slot'; sp.textContent = h;
      box.appendChild(sp);
    });
    chat.appendChild(card); scrollChat();
    return card.querySelectorAll('.mw-slot');
  }
  function buildFaqList(items) {
    var card = document.createElement('div');
    card.className = 'mw-card';
    card.innerHTML = '<p class="mw-card-title">❓ Preguntas frecuentes</p><div class="mw-faq-list"></div>';
    var box = card.querySelector('.mw-faq-list');
    items.forEach(function (q) {
      var btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'mw-faq-q'; btn.textContent = q;
      box.appendChild(btn);
    });
    chat.appendChild(card); scrollChat();
    return card.querySelectorAll('.mw-faq-q');
  }
  function clickWithDelay(el, ms, cb) {
    setTimeout(function () {
      el.classList.add('is-clicked');
      setTimeout(cb, 420);
    }, ms);
  }

  /* ---------- flujos chat ---------- */
  function flowAgenda(done) {
    chat.innerHTML = '';
    addBubble('bot', 'Hola 👋 Soy el asistente de tu negocio. ¿En qué te ayudo?');
    setTimeout(function () {
      var opts = buildOptions();
      clickWithDelay(opts[0], 1400, function () {
        addBubble('user', 'Reservar cita');
        showTyping(900, function () {
          var cal = buildCalendar();
          clickWithDelay(cal[2], 1300, function () {
            var picked = cal[2].dataset.label;
            addBubble('user', picked);
            showTyping(800, function () {
              var sl = buildSlots(picked);
              clickWithDelay(sl[2], 1100, function () {
                var hour = sl[2].textContent;
                addBubble('user', hour);
                showTyping(900, function () {
                  addBubble('confirm', '✅ <b>Cita confirmada</b><br>' + picked + ' · ' + hour + '<br><small>Recordatorios 24 h y 2 h antes.</small>');
                  setTimeout(done, 3200);
                });
              });
            });
          });
        });
      });
    }, 1200);
  }
  function flowPago(done) {
    chat.innerHTML = '';
    addBubble('bot', '¡Hola de nuevo! ¿Te ayudo con algo más?');
    setTimeout(function () {
      var opts = buildOptions();
      clickWithDelay(opts[1], 1400, function () {
        addBubble('user', 'Pagar mi reserva');
        showTyping(1000, function () {
          addBubble('bot', 'Tu cita del miércoles 21 a las 12:30 tiene pendiente la señal de 15 €. Te acabo de enviar el enlace de pago seguro 💳');
          setTimeout(function () {
            addBubble('confirm', '✅ <b>Pago recibido</b><br>Señal de 15 € · Stripe<br><small>Recibirás el justificante por email.</small>');
            setTimeout(done, 3400);
          }, 1600);
        });
      });
    }, 1100);
  }
  function flowFaq(done) {
    chat.innerHTML = '';
    addBubble('bot', '¿En qué te ayudo?');
    setTimeout(function () {
      var opts = buildOptions();
      clickWithDelay(opts[2], 1400, function () {
        addBubble('user', 'Preguntas frecuentes');
        showTyping(800, function () {
          var faqs = buildFaqList([
            '¿Cuánto dura la primera sesión?',
            '¿Puedo pagar con tarjeta?',
            '¿Cómo cancelo mi cita?',
            '¿Tenéis aparcamiento?'
          ]);
          clickWithDelay(faqs[2], 1400, function () {
            addBubble('user', '¿Cómo cancelo mi cita?');
            showTyping(1000, function () {
              addBubble('bot', 'En el email de confirmación tienes un enlace para cancelar o cambiar tu cita en un clic, sin llamar. Hasta 24 h antes no tiene coste.');
              setTimeout(done, 3400);
            });
          });
        });
      });
    }, 1100);
  }
  function chatLoop() {
    flowAgenda(function () {
      flowPago(function () {
        flowFaq(function () { chatLoop(); });
      });
    });
  }

  /* ---------- pane reservas ---------- */
  var mbBody = document.getElementById('mbBody');
  var mbBar = document.getElementById('mbBar');
  var mbStepLabel = document.getElementById('mbStepLabel');

  function mbSetStep(n, label) {
    if (mbBar) mbBar.style.width = (n * 25) + '%';
    if (mbStepLabel) mbStepLabel.textContent = 'Paso ' + n + ' de 4 · ' + label;
  }
  function mbTitle(text) {
    var t = document.createElement('p');
    t.className = 'mb-title'; t.textContent = text;
    mbBody.appendChild(t);
  }
  function mbService(name, mins, price) {
    var el = document.createElement('div');
    el.className = 'mb-svc';
    el.innerHTML = '<div><b>' + name + '</b><span>' + mins + ' min</span></div><em>' + price + '</em>';
    mbBody.appendChild(el); return el;
  }
  function bookLoop() {
    if (!mbBody) return;
    mbBody.innerHTML = '';
    mbSetStep(1, 'Servicio');
    mbTitle('Elige tu servicio');
    var s1 = mbService('Masaje descontracturante', 45, '40 €');
    mbService('Fisioterapia', 50, '55 €');
    mbService('Sesión premium', 60, '75 €');
    clickWithDelay(s1, 1500, function () {
      mbBody.innerHTML = '';
      mbSetStep(2, 'Fecha');
      mbTitle('¿Qué día te viene bien?');
      var cal = document.createElement('div');
      cal.className = 'mw-cal';
      [
        { dow: 'Mar', n: 20, dis: false },
        { dow: 'Mié', n: 21, dis: false },
        { dow: 'Jue', n: 22, dis: false },
        { dow: 'Vie', n: 23, dis: false },
        { dow: 'Sáb', n: 24, dis: true },
        { dow: 'Dom', n: 25, dis: true },
        { dow: 'Lun', n: 26, dis: false },
        { dow: 'Mar', n: 27, dis: false }
      ].forEach(function (d) {
        var el = document.createElement('div');
        el.className = 'mw-cal-day' + (d.dis ? ' is-disabled' : '');
        el.innerHTML = d.dow + '<b>' + d.n + '</b>';
        cal.appendChild(el);
      });
      mbBody.appendChild(cal);
      var days = cal.querySelectorAll('.mw-cal-day:not(.is-disabled)');
      clickWithDelay(days[3], 1400, function () {
        mbBody.innerHTML = '';
        mbSetStep(3, 'Hora');
        mbTitle('Huecos libres · Vie 23');
        var box = document.createElement('div');
        box.className = 'mw-slots';
        ['09:30', '10:30', '12:00', '16:30', '18:00'].forEach(function (h) {
          var sp = document.createElement('span');
          sp.className = 'mw-slot'; sp.textContent = h;
          box.appendChild(sp);
        });
        mbBody.appendChild(box);
        var slots = box.querySelectorAll('.mw-slot');
        clickWithDelay(slots[1], 1300, function () {
          mbBody.innerHTML = '';
          mbSetStep(4, 'Confirmación');
          var done = document.createElement('div');
          done.className = 'mb-done';
          done.innerHTML = '✅ <b>Reserva confirmada</b><br>Masaje descontracturante · Vie 23 · 10:30<br>Señal de 15 € pagada con tarjeta 💳<br><small>Email y recordatorios en camino.</small>';
          mbBody.appendChild(done);
          setTimeout(bookLoop, 4200);
        });
      });
    });
  }

  /* ---------- pane voz ---------- */
  var mvTranscript = document.getElementById('mvTranscript');
  var mvTimer = document.getElementById('mvTimer');
  var mvSeconds = 0;

  function mvLine(kind, text) {
    var el = document.createElement('div');
    el.className = 'mv-line ' + kind;
    el.textContent = text;
    mvTranscript.appendChild(el);
    while (mvTranscript.children.length > 5) mvTranscript.removeChild(mvTranscript.firstChild);
  }
  function voiceLoop() {
    if (!mvTranscript) return;
    mvTranscript.innerHTML = '';
    mvSeconds = 0;
    var script = [
      [900,  'caller', '«Hola, ¿puedo cambiar mi cita del jueves?»'],
      [2600, 'ia',     '«¡Claro! La tienes el jueves a las 17:00. ¿Qué día te viene mejor?»'],
      [5200, 'caller', '«El viernes por la mañana, si puede ser.»'],
      [7600, 'ia',     '«Tengo un hueco el viernes a las 10:30 con Marta. ¿Te lo confirmo?»'],
      [10200, 'caller', '«Perfecto, gracias.»'],
      [12000, 'result', '🔁 Cita reprogramada · SMS de confirmación enviado']
    ];
    script.forEach(function (step) {
      setTimeout(function () { mvLine(step[1], step[2]); }, step[0]);
    });
    setTimeout(voiceLoop, 16500);
  }
  if (mvTimer) {
    setInterval(function () {
      mvSeconds += 1;
      var m = Math.floor(mvSeconds / 60), sec = mvSeconds % 60;
      mvTimer.textContent = (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
    }, 1000);
  }

  /* ---------- controlador de paneles ---------- */
  var ORDER = ['chat', 'book', 'voice'];
  var DUR = { chat: 21000, book: 12500, voice: 17000 };
  var idx = 0, rotTimer = null;

  function setPane(name) {
    tabs.forEach(function (t) { t.classList.toggle('active', t.dataset.pane === name); });
    panes.forEach(function (p) { p.classList.toggle('active', p.dataset.pane === name); });
    if (barLabel) barLabel.textContent = BAR_LABELS[name] || 'tunegocio.es';
    idx = ORDER.indexOf(name);
  }
  function scheduleNext() {
    clearTimeout(rotTimer);
    rotTimer = setTimeout(function () {
      var next = ORDER[(idx + 1) % ORDER.length];
      setPane(next);
      scheduleNext();
    }, DUR[ORDER[idx]] || 15000);
  }
  tabs.forEach(function (t) {
    t.addEventListener('click', function () {
      setPane(t.dataset.pane);
      if (!reduced) scheduleNext();
    });
  });

  /* ---------- estático si reduce-motion ---------- */
  if (reduced) {
    addBubble('bot', 'Hola 👋 Soy el asistente de tu negocio. ¿En qué te ayudo?');
    addBubble('user', 'Quiero reservar una cita');
    addBubble('confirm', '✅ <b>Cita confirmada</b><br>Mié 21 · 12:30<br><small>Recordatorios 24 h y 2 h antes.</small>');
    if (mbBody) {
      mbSetStep(1, 'Servicio');
      mbTitle('Elige tu servicio');
      mbService('Masaje descontracturante', 45, '40 €');
      mbService('Fisioterapia', 50, '55 €');
    }
    if (mvTranscript) {
      mvLine('caller', '«¿Puedo cambiar mi cita del jueves?»');
      mvLine('ia', '«Tengo un hueco el viernes a las 10:30. ¿Te lo confirmo?»');
      mvLine('result', '🔁 Cita reprogramada · SMS enviado');
    }
    return;
  }

  /* ---------- arranque al entrar en viewport ---------- */
  function startAll() {
    chatLoop();
    bookLoop();
    voiceLoop();
    scheduleNext();
  }
  if ('IntersectionObserver' in window) {
    var started = false;
    var io2 = new IntersectionObserver(function (ents) {
      ents.forEach(function (e) {
        if (e.isIntersecting && !started) { started = true; startAll(); io2.disconnect(); }
      });
    }, { threshold: 0.2 });
    io2.observe(chat);
  } else {
    startAll();
  }
})();

/* ════════════════════════════════════════════════
   Central de reservas embebida — carga perezosa
   ════════════════════════════════════════════════ */
(function () {
  var frame = document.getElementById('centralIframe');
  var skeleton = document.getElementById('centralSkeleton');
  if (!frame || !frame.dataset.src) return;

  function load() {
    if (frame.src) return;
    frame.addEventListener('load', function () {
      if (skeleton) skeleton.style.display = 'none';
      if (window.vanteliaTrack) window.vanteliaTrack('central_demo_loaded', { source: 'home_embed' });
    });
    frame.src = frame.dataset.src;
  }

  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (ents) {
      ents.forEach(function (e) {
        if (e.isIntersecting) { load(); io.disconnect(); }
      });
    }, { rootMargin: '600px 0px' });
    io.observe(frame);
  } else {
    load();
  }
})();
