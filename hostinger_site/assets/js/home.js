/* Vantelia · home/site UI scripts */

/* Conversion measurement */
(function () {
  const DEBUG_KEY = 'vantelia_analytics_debug';
  const CONSENT_KEY = 'vantelia_cookie_consent_v1';
  const SERVER_ENDPOINT = window.VANTELIA_ANALYTICS_ENDPOINT || 'https://app.vantelia.es/analytics/event';

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
    }
  }, true);

  document.addEventListener('vantelia:widget', (event) => {
    const detail = event.detail || {};
    track(detail.event || 'widget_event', detail);
  });

  window.vanteliaTrack = track;
})();

/* Particle canvas (only when canvas exists) */
(function () {
  const canvas = document.getElementById('particles');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let pts = [], raf;

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
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    pts.forEach(p => p.tick());
    lines();
    raf = requestAnimationFrame(draw);
  }
  window.addEventListener('resize', () => { resize(); init(); }, { passive: true });
  resize(); init(); draw();
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
  function openMenu() {
    menu.classList.add('open');
    toggle.setAttribute('aria-expanded', 'true');
    document.body.classList.add('mobile-nav-open');
  }
  function closeMenu() {
    menu.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('mobile-nav-open');
  }
  toggle.addEventListener('click', () => {
    if (menu.classList.contains('open')) closeMenu();
    else openMenu();
  });
  close.addEventListener('click', closeMenu);
  menu.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenu));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
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
    document.dispatchEvent(new CustomEvent('vantelia:consent', { detail: window.vanteliaConsent }));
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
      writeConsent({ analytics: true, marketing: true });
      wrap.remove();
    });
    wrap.querySelector('.cc-reject').addEventListener('click', () => {
      writeConsent({ analytics: false, marketing: false });
      wrap.remove();
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
