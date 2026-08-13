/* =========================================================
   Animaciones GSAP de la sección "Equipo".
   Efectos sobrios, en el tono editorial del sitio:
   entrada por scroll, parallax suave en las fotos y un
   trazo dorado bajo el título. Degrada sin romper nada.
========================================================= */
(function(){
  "use strict";
  var section = document.getElementById("equipo");
  if(!section) return;

  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var head = section.querySelector(".team-head");
  var cards = Array.prototype.slice.call(section.querySelectorAll(".team-card"));

  // Sin GSAP/ScrollTrigger o con movimiento reducido: todo visible, sin animar.
  if(!window.gsap || !window.ScrollTrigger || reduce) return;

  gsap.registerPlugin(ScrollTrigger);

  // --- Cabecera: eyebrow, título e intro entran escalonados ---
  var headEls = head ? head.querySelectorAll(".eyebrow, h2, p") : [];
  if(headEls.length){
    gsap.set(headEls, { opacity: 0, y: 26 });
    gsap.to(headEls, {
      opacity: 1, y: 0, duration: 1, ease: "power3.out", stagger: 0.12,
      scrollTrigger: { trigger: head, start: "top 82%" }
    });
  }

  // --- Trazo dorado que crece bajo el título ---
  if(head && !head.querySelector(".team-underline")){
    var line = document.createElement("span");
    line.className = "team-underline";
    line.style.cssText = "display:block;width:0;height:1px;background:var(--gold);margin:28px auto 0;opacity:.8";
    head.appendChild(line);
    gsap.to(line, {
      width: 54, duration: 1.1, ease: "power3.out",
      scrollTrigger: { trigger: head, start: "top 78%" }
    });
  }

  // --- Tarjetas: entrada escalonada al aparecer ---
  gsap.set(cards, { opacity: 0, y: 46 });
  ScrollTrigger.batch(cards, {
    start: "top 88%",
    onEnter: function(batch){
      gsap.to(batch, { opacity: 1, y: 0, duration: 1.05, ease: "power3.out", stagger: 0.14, overwrite: true });
    }
  });

  // --- Parallax suave de cada foto al hacer scroll ---
  cards.forEach(function(card){
    var img = card.querySelector(".team-photo img");
    if(!img) return;
    gsap.set(img, { scale: 1.12 });               // margen para el desplazamiento
    gsap.fromTo(img,
      { yPercent: -6 },
      { yPercent: 6, ease: "none",
        scrollTrigger: { trigger: card, start: "top bottom", end: "bottom top", scrub: true } }
    );
  });

  // --- Monograma del placeholder: leve aparición con rebote ---
  var monos = section.querySelectorAll(".team-photo--empty .team-ph-mono");
  if(monos.length){
    gsap.from(monos, {
      scale: 0.6, opacity: 0, duration: 0.9, ease: "back.out(1.7)", stagger: 0.1,
      scrollTrigger: { trigger: section, start: "top 70%" }
    });
  }

  // recalcula posiciones cuando cargan fuentes/imágenes
  window.addEventListener("load", function(){ ScrollTrigger.refresh(); });
})();
