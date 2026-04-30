/* Vantelia · home/site UI scripts */

/* Particle canvas (only when canvas exists) */
(function () {
  const canvas = document.getElementById('particles');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let pts = [], raf;

  function resize() {
    canvas.width  = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
  }
  function Pt() {
    this.x  = Math.random() * canvas.width;
    this.y  = Math.random() * canvas.height;
    this.vx = (Math.random() - .5) * .38;
    this.vy = (Math.random() - .5) * .38;
    this.r  = Math.random() * 1.4 + .5;
    this.o  = Math.random() * .45 + .1;
  }
  Pt.prototype.tick = function () {
    this.x += this.vx; this.y += this.vy;
    if (this.x < 0 || this.x > canvas.width)  this.vx *= -1;
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
  const menu   = document.getElementById('mobile-menu');
  const close  = document.getElementById('mobile-close');
  if (!toggle || !menu || !close) return;
  function openMenu()  { menu.classList.add('open'); toggle.setAttribute('aria-expanded', 'true');  document.body.style.overflow = 'hidden'; }
  function closeMenu() { menu.classList.remove('open'); toggle.setAttribute('aria-expanded', 'false'); document.body.style.overflow = ''; }
  toggle.addEventListener('click', () => {
    if (menu.classList.contains('open')) closeMenu();
    else openMenu();
  });
  close.addEventListener('click', closeMenu);
  menu.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenu));
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
    const dur    = 1800;
    const start  = performance.now();
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
      const item   = btn.closest('.faq-item');
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
