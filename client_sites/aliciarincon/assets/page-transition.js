/* =========================================================
   TRANSICIÓN ENTRE PÁGINAS · Alicia Rincón Estilistas
   Una cortina de tinta que sube al salir y sigue subiendo al
   entrar: el movimiento continúa de una página a la siguiente.
   Animado con GSAP.

   Mejora progresiva: sin JavaScript la cortina no existe; sin
   GSAP (o con "reducir movimiento") la navegación es la normal.
========================================================= */
(function(){
  "use strict";

  const root  = document.documentElement;
  const veil  = document.getElementById("pageVeil");
  const inner = veil && veil.querySelector(".page-veil-inner");
  const line  = veil && veil.querySelector(".page-veil-line");

  /* el temporizador de seguridad de la cabecera retira la cortina si
     este script no llega a ejecutarse; una vez aquí, sobra */
  function clearGuard(){
    if(window.__ptGuard){ clearTimeout(window.__ptGuard); window.__ptGuard = null; }
  }

  function drop(){
    clearGuard();
    root.classList.remove("pt-on");
  }

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const gsap   = window.gsap;

  /* sin cortina, sin GSAP o con movimiento reducido: navegación normal */
  if(!veil || !gsap || reduce){ drop(); return; }

  const ENTER = 0.85;   // segundos: la cortina se retira
  const EXIT  = 0.55;   // segundos: la cortina cubre la página

  clearGuard();   // a partir de aquí manda la animación, no el temporizador

  /* ---------- llegada ----------
     La página nueva empieza tal y como terminó la anterior (cortina
     puesta, con la firma y el filete dorado): el corte no se ve.
     Desde ahí, la cortina sigue subiendo y descubre el contenido. */
  gsap.timeline({ onComplete: drop })
    .to(inner, { opacity: 0, duration: 0.28, ease: "power1.out" }, 0)
    .to(veil, {
      scaleY: 0,
      transformOrigin: "50% 0%",
      duration: ENTER,
      ease: "power3.inOut"
    }, 0.1);

  /* ---------- salida: la cortina sube desde el pie ---------- */
  let leaving = false;

  function leave(href){
    if(leaving) return;
    leaving = true;

    root.classList.add("pt-on");
    gsap.set(veil,  { scaleY: 0, transformOrigin: "50% 100%" });
    gsap.set(inner, { opacity: 0 });
    gsap.set(line,  { scaleX: 0, transformOrigin: "50% 50%" });

    /* si la red tarda, la cortina ya cubre: nunca se queda a medias */
    gsap.timeline({ onComplete: () => { window.location.href = href; } })
      .to(veil,  { scaleY: 1, duration: EXIT, ease: "power3.inOut" })
      .to(inner, { opacity: 1, duration: 0.3, ease: "power1.out" }, "-=0.26")
      .to(line,  { scaleX: 1, duration: 0.5, ease: "power2.out" }, "-=0.30");
  }

  /* ---------- qué enlaces se animan ---------- */
  function targetOf(a){
    if(a.hasAttribute("download")) return null;
    if(a.target && a.target !== "_self") return null;
    if((a.getAttribute("rel") || "").indexOf("external") !== -1) return null;

    const href = a.getAttribute("href") || "";
    if(!href || href.charAt(0) === "#") return null;      // ancla de la misma página

    let url;
    try{ url = new URL(a.href, location.href); }catch(e){ return null; }

    if(url.origin !== location.origin) return null;        // WhatsApp, Google, Instagram…
    if(url.protocol !== "http:" && url.protocol !== "https:") return null;  // mailto:, tel:
    /* mismo documento (sólo cambia el ancla): que el navegador haga su trabajo */
    if(url.pathname === location.pathname && url.search === location.search) return null;

    return url.href;
  }

  document.addEventListener("click", function(e){
    if(e.defaultPrevented || e.button !== 0) return;
    if(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;   // abrir en pestaña nueva

    const a = e.target.closest ? e.target.closest("a[href]") : null;
    if(!a) return;

    const href = targetOf(a);
    if(!href) return;

    e.preventDefault();
    leave(href);
  });

  /* volver con el botón "atrás": la página vuelve de la caché
     con la cortina puesta, hay que retirarla */
  window.addEventListener("pageshow", function(e){
    if(!e.persisted) return;
    leaving = false;
    gsap.set(veil, { clearProps: "all" });
    drop();
  });
})();
