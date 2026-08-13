/* =========================================================
   Mejora progresiva del formulario de contacto del sitio.
   Envía la consulta a /api/contact (correo con Cloudflare)
   sin tocar el diseño ni la animación de confirmación
   existentes. Se inyecta en la página vía el Worker.
========================================================= */
(function(){
  "use strict";
  var form = document.getElementById("contactForm");
  if(!form) return;

  var val = function(sel){
    var el = form.querySelector(sel);
    return el ? el.value.trim() : "";
  };

  form.addEventListener("submit", function(){
    // se lee en el momento del envío, antes de que el form se resetee
    var payload = {
      nombre:   val('[name="nombre"]'),
      telefono: val('[name="telefono"]'),
      mensaje:  val('[name="mensaje"]'),
      website:  val('[name="website"]') // honeypot (si existe)
    };
    if(!payload.nombre || !payload.telefono || !payload.mensaje) return;

    // envío en segundo plano; la confirmación visual la gestiona el sitio
    fetch("/api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).catch(function(){ /* silencioso: no rompe la experiencia */ });
  });
})();
