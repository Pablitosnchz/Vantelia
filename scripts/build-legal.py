"""Genera 4 paginas legales (privacidad, terminos, cookies, ia-responsable)
con header/footer del sitio y diseno home.css.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "hostinger_site"
LEGAL_DIR = SITE / "legal"
BASE_URL = "https://www.vantelia.es"
LAST_UPDATE = "30 de abril de 2026"

# Reuse same header/footer as build-pages.py (kept in sync manually)
HEADER = """<!-- Cursor ambient glow (desktop) -->
<div id="cursor-glow" aria-hidden="true"></div>

<header class="site-header" id="site-header">
  <div class="shell nav-inner">
    <a href="/" class="brand" aria-label="Vantelia · Inicio">
      <img src="/assets/img/logo-letra.png" alt="Logo Vantelia · Agencia de IA y Marketing B2B" width="200" height="48" fetchpriority="high" decoding="async">
    </a>
    <nav aria-label="Navegación principal">
      <ul class="nav-links">
        <li><a href="/servicios/">Servicios</a></li>
        <li><a href="/plataforma/">Plataforma</a></li>
        <li><a href="/resultados/">Resultados</a></li>
        <li><a href="/nosotros/">Nosotros</a></li>
        <li><a href="/faq/">FAQ</a></li>
      </ul>
    </nav>
    <div style="display:flex;gap:10px;align-items:center" class="nav-cta">
      <a href="https://app.vantelia.es/acceso" class="btn-access" target="_blank" rel="noopener">
        <span class="dot-live" aria-hidden="true"></span>Acceso plataforma
      </a>
      <a href="/consultas/" class="btn btn-primary">Consulta gratuita</a>
    </div>
    <button class="nav-toggle" id="nav-toggle" aria-label="Abrir menú" aria-expanded="false">
      <span></span><span></span><span></span>
    </button>
  </div>
</header>

<div class="mobile-menu" id="mobile-menu" role="dialog" aria-label="Menú de navegación">
  <button class="mobile-close" id="mobile-close" aria-label="Cerrar menú">✕</button>
  <a href="/servicios/"  class="mm-link">Servicios</a>
  <a href="/plataforma/" class="mm-link">Plataforma</a>
  <a href="/resultados/" class="mm-link">Resultados</a>
  <a href="/nosotros/"   class="mm-link">Nosotros</a>
  <a href="/faq/"        class="mm-link">FAQ</a>
  <a href="https://app.vantelia.es/acceso" class="btn-access" target="_blank" rel="noopener" style="margin-top:8px;font-size:1rem;height:48px;padding:0 28px">
    <span class="dot-live"></span>Acceso plataforma
  </a>
  <a href="/consultas/"   class="btn btn-primary btn-lg" style="margin-top:8px">Consulta gratuita</a>
</div>"""

FOOTER = """<footer class="site-footer" aria-label="Pie de página">
  <div class="shell">
    <div class="footer-grid">
      <div class="footer-brand">
        <div class="footer-logo">
          <span class="brand-name">Vantelia</span>
        </div>
        <p class="footer-desc">
          IA aplicada y marketing digital para empresas B2B en España.
          Sistemas que captan, cualifican y cierran oportunidades reales.
        </p>
        <div class="footer-social" aria-label="Redes sociales">
          <a href="https://linkedin.com/company/vantelia" class="social-a" aria-label="LinkedIn" rel="noopener noreferrer" target="_blank">in</a>
          <a href="/consultas/" class="social-a" aria-label="Solicitar consulta">✉</a>
        </div>
      </div>
      <div class="footer-col">
        <div class="col-title">Producto</div>
        <div class="col-links">
          <a href="/servicios/">Servicios</a>
          <a href="/plataforma/">Plataforma</a>
          <a href="/resultados/">Resultados</a>
          <a href="/consultas/">Consulta gratuita</a>
        </div>
      </div>
      <div class="footer-col">
        <div class="col-title">Empresa</div>
        <div class="col-links">
          <a href="/nosotros/">Nosotros</a>
          <a href="/faq/">Preguntas frecuentes</a>
          <a href="/consultas/">Solicitar consulta</a>
        </div>
      </div>
      <div class="footer-col">
        <div class="col-title">Plataforma</div>
        <div class="col-links">
          <a href="https://app.vantelia.es/acceso" target="_blank" rel="noopener">Acceso clientes</a>
          <a href="https://app.vantelia.es/acceso" target="_blank" rel="noopener">Acceso administradores</a>
        </div>
      </div>
      <div class="footer-col">
        <div class="col-title">Legal</div>
        <div class="col-links">
          <a href="/legal/privacidad/">Política de privacidad</a>
          <a href="/legal/terminos/">Términos de uso</a>
          <a href="/legal/cookies/">Política de cookies</a>
          <a href="/legal/ia-responsable/">IA responsable</a>
        </div>
      </div>
    </div>
    <div class="footer-bottom">
      <p>© 2026 Vantelia · Todos los derechos reservados</p>
      <p class="footer-locale">Hecho en España · ES</p>
    </div>
  </div>
</footer>

<script src="/assets/js/home.js" defer></script>"""


def page(slug: str, title: str, description: str, body_html: str) -> str:
    canonical = f"{BASE_URL}/legal/{slug}/"
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="robots" content="index,follow,max-image-preview:large">
  <meta name="theme-color" content="#0B132B">
  <link rel="canonical" href="{canonical}">
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/img/favicon.png">
  <link rel="apple-touch-icon" href="/assets/img/favicon.png">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Vantelia">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{BASE_URL}/assets/img/resumen.png">
  <meta property="og:locale" content="es_ES">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/css/home.css">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@graph": [
      {{ "@type": "Organization", "@id": "{BASE_URL}/#org" }},
      {{
        "@type": "WebPage",
        "url": "{canonical}",
        "name": "{title}",
        "description": "{description}",
        "inLanguage": "es-ES",
        "publisher": {{ "@id": "{BASE_URL}/#org" }}
      }},
      {{
        "@type": "BreadcrumbList",
        "itemListElement": [
          {{ "@type": "ListItem", "position": 1, "name": "Inicio", "item": "{BASE_URL}/" }},
          {{ "@type": "ListItem", "position": 2, "name": "Legal", "item": "{BASE_URL}/legal/{slug}/" }}
        ]
      }}
    ]
  }}
  </script>
</head>
<body>
{HEADER}

<main class="legal-page" aria-label="{title}">
  <div class="shell">
    <article>
      {body_html}
    </article>
  </div>
</main>

{FOOTER}
</body>
</html>
"""


# ───────────────────── Privacidad ─────────────────────
PRIVACIDAD = f"""
<h1>Política de privacidad</h1>
<p class="legal-meta">Última actualización: {LAST_UPDATE} · Versión 2.0 · Conforme a RGPD (UE 2016/679) y LOPDGDD (LO 3/2018)</p>

<nav class="legal-toc" aria-label="Índice">
  <strong>Índice</strong>
  <ol>
    <li><a href="#responsable">Responsable del tratamiento</a></li>
    <li><a href="#datos">Qué datos tratamos</a></li>
    <li><a href="#finalidades">Finalidades y base legal</a></li>
    <li><a href="#ia">Tratamiento en sistemas de IA</a></li>
    <li><a href="#destinatarios">Destinatarios y encargados</a></li>
    <li><a href="#transferencias">Transferencias internacionales</a></li>
    <li><a href="#conservacion">Plazos de conservación</a></li>
    <li><a href="#derechos">Tus derechos</a></li>
    <li><a href="#seguridad">Seguridad</a></li>
    <li><a href="#contacto">Contacto y reclamaciones</a></li>
  </ol>
</nav>

<h2 id="responsable">1. Responsable del tratamiento</h2>
<p>Vantelia (en adelante, <strong>"Vantelia"</strong>, <strong>"nosotros"</strong>) es responsable del tratamiento de los datos personales recogidos a través de <a href="https://www.vantelia.es">www.vantelia.es</a>, de la plataforma <a href="https://app.vantelia.es">app.vantelia.es</a> y del widget de IA conversacional embebido en webs de nuestros clientes.</p>
<ul>
  <li><strong>Email de contacto:</strong> <a href="/consultas/">Solicitar consulta</a></li>
  <li><strong>Email del Delegado de Protección de Datos:</strong> <a href="mailto:soporte@vantelia.es">soporte@vantelia.es</a></li>
  <li><strong>Ámbito territorial:</strong> España y Espacio Económico Europeo</li>
</ul>

<h2 id="datos">2. Qué datos tratamos</h2>
<p>Tratamos las siguientes categorías de datos según el canal de interacción:</p>
<table>
  <thead><tr><th>Canal</th><th>Datos tratados</th></tr></thead>
  <tbody>
    <tr><td>Formulario de contacto / consulta</td><td>Nombre, email, empresa, teléfono opcional, mensaje libre</td></tr>
    <tr><td>Asistente IA (widget web)</td><td>Mensajes de la conversación, ID de sesión, IP truncada, user-agent, página de origen</td></tr>
    <tr><td>Reservas a través del asistente</td><td>Nombre, email, teléfono, servicio, fecha y hora seleccionados</td></tr>
    <tr><td>WhatsApp IA</td><td>Número, contenido del mensaje, metadatos provistos por Meta</td></tr>
    <tr><td>Plataforma <code>app.vantelia.es</code></td><td>Email corporativo, contraseña cifrada, rol, tenant, logs de acceso</td></tr>
    <tr><td>Navegación general</td><td>Datos analíticos agregados (cookies, ver <a href="/legal/cookies/">política de cookies</a>)</td></tr>
  </tbody>
</table>
<p>No solicitamos categorías especiales de datos (salud, ideología, orientación sexual, etc.). Si tu mensaje incluye este tipo de datos por iniciativa propia, los borramos en cuanto los detectamos.</p>

<h2 id="finalidades">3. Finalidades y base legal</h2>
<table>
  <thead><tr><th>Finalidad</th><th>Base legal (RGPD art. 6)</th></tr></thead>
  <tbody>
    <tr><td>Atender consultas comerciales y proponer servicios</td><td>Interés legítimo / consentimiento</td></tr>
    <tr><td>Ejecución de contrato con clientes B2B</td><td>Ejecución de contrato (art. 6.1.b)</td></tr>
    <tr><td>Gestionar reservas a través del asistente IA</td><td>Ejecución contractual y consentimiento del usuario final</td></tr>
    <tr><td>Mejorar el rendimiento del asistente IA y prevenir abuso</td><td>Interés legítimo (art. 6.1.f)</td></tr>
    <tr><td>Cumplir obligaciones legales (fiscales, mercantiles)</td><td>Obligación legal (art. 6.1.c)</td></tr>
    <tr><td>Envío de comunicaciones comerciales</td><td>Consentimiento revocable en cualquier momento</td></tr>
  </tbody>
</table>

<h2 id="ia">4. Tratamiento en sistemas de IA</h2>
<p>Vantelia opera asistentes conversacionales con tecnología de IA generativa. Esto implica un tratamiento específico que detallamos por transparencia:</p>
<h3>4.1. Modelos utilizados</h3>
<p>Empleamos modelos de lenguaje de OpenAI (GPT-4o-mini y GPT-4o) y embeddings (text-embedding-3-small) procesados a través de la API empresarial de OpenAI bajo contrato de procesamiento de datos (DPA).</p>
<h3>4.2. Aislamiento por cliente</h3>
<p>Cada cliente B2B dispone de su propio espacio aislado: índice vectorial, base de datos, contraseñas y claves. Los datos de un cliente <strong>nunca</strong> se utilizan para responder a otro cliente.</p>
<h3>4.3. Entrenamiento y reutilización</h3>
<p>Las conversaciones de los usuarios finales <strong>no se usan para entrenar modelos públicos de OpenAI</strong>. La API empresarial impide explícitamente este uso. Las conversaciones pueden almacenarse internamente para auditoría, calidad y depuración hasta los plazos del apartado 7.</p>
<h3>4.4. Decisiones automatizadas</h3>
<p>El asistente IA <strong>no toma decisiones jurídicas ni con efecto significativo</strong> sobre el usuario. Sus respuestas son orientativas; la confirmación de reservas, propuestas comerciales y datos críticos siempre se valida con el cliente humano.</p>
<h3>4.5. Limitaciones conocidas</h3>
<p>El asistente puede equivocarse, dar respuestas incompletas o malinterpretar la intención. Por este motivo recomendamos al usuario contrastar información sensible (precios, disponibilidad, condiciones legales) con un humano del equipo del cliente.</p>

<h2 id="destinatarios">5. Destinatarios y encargados de tratamiento</h2>
<p>Trabajamos con los siguientes proveedores como encargados del tratamiento, todos vinculados por contratos conformes al art. 28 RGPD:</p>
<ul>
  <li><strong>OpenAI Ireland Ltd.</strong> — modelos de IA (UE / EEUU con cláusulas contractuales tipo)</li>
  <li><strong>Hostinger International Ltd.</strong> — alojamiento web (UE)</li>
  <li><strong>Google LLC</strong> — La Agenda de Vantelia para reservas (cláusulas contractuales tipo)</li>
  <li><strong>Calendly LLC</strong> — calendarización opcional (cláusulas contractuales tipo)</li>
  <li><strong>Meta Platforms Ireland Ltd.</strong> — WhatsApp Cloud API (UE)</li>
  <li><strong>Proveedor SMTP transaccional</strong> — envío de emails operativos (UE)</li>
</ul>
<p>No vendemos ni cedemos datos personales a terceros con fines comerciales.</p>

<h2 id="transferencias">6. Transferencias internacionales</h2>
<p>Algunos proveedores procesan datos fuera del EEE (principalmente EEUU). En esos casos aplicamos:</p>
<ul>
  <li>Cláusulas Contractuales Tipo (CCT) aprobadas por la Comisión Europea</li>
  <li>Evaluaciones de impacto cuando son obligatorias</li>
  <li>Medidas técnicas adicionales (cifrado en tránsito y reposo)</li>
</ul>

<h2 id="conservacion">7. Plazos de conservación</h2>
<table>
  <thead><tr><th>Tipo de dato</th><th>Plazo</th></tr></thead>
  <tbody>
    <tr><td>Consultas comerciales no convertidas</td><td>12 meses desde el último contacto</td></tr>
    <tr><td>Datos de cliente B2B activo</td><td>Duración del contrato + 6 años (obligaciones mercantiles y fiscales)</td></tr>
    <tr><td>Conversaciones del asistente IA</td><td>90 días en sistemas operativos; agregadas y anonimizadas pasado ese plazo</td></tr>
    <tr><td>Reservas y citas</td><td>2 años desde la fecha de la cita</td></tr>
    <tr><td>Logs de acceso a la plataforma</td><td>12 meses</td></tr>
  </tbody>
</table>

<h2 id="derechos">8. Tus derechos</h2>
<p>Tienes derecho a ejercer los siguientes derechos en cualquier momento:</p>
<ul>
  <li><strong>Acceso:</strong> conocer qué datos tuyos tratamos</li>
  <li><strong>Rectificación:</strong> corregir datos inexactos</li>
  <li><strong>Supresión ("derecho al olvido"):</strong> eliminar tus datos cuando ya no sean necesarios</li>
  <li><strong>Limitación:</strong> restringir el tratamiento en ciertos supuestos</li>
  <li><strong>Portabilidad:</strong> recibir tus datos en formato estructurado</li>
  <li><strong>Oposición:</strong> oponerte a tratamientos basados en interés legítimo</li>
  <li><strong>No ser objeto de decisiones automatizadas con efectos jurídicos</strong></li>
</ul>
<p>Solicítalos por email a <a href="mailto:soporte@vantelia.es">soporte@vantelia.es</a>. Respondemos en un máximo de 30 días.</p>

<h2 id="seguridad">9. Seguridad</h2>
<p>Aplicamos medidas técnicas y organizativas proporcionales al riesgo:</p>
<ul>
  <li>Cifrado TLS 1.3 en tránsito y AES-256 en reposo donde corresponde</li>
  <li>Hash bcrypt para contraseñas</li>
  <li>Aislamiento multi-tenant a nivel de base de datos e índice vectorial</li>
  <li>Control de acceso por roles (RBAC) y autenticación con tokens firmados</li>
  <li>Rate limiting, registro de accesos y monitorización de anomalías</li>
  <li>Revisión periódica de dependencias y backups cifrados</li>
</ul>

<h2 id="contacto">10. Contacto y reclamaciones</h2>
<p>Si consideras que tus datos no han sido tratados conforme a la normativa puedes:</p>
<ul>
  <li>Escribirnos a <a href="mailto:soporte@vantelia.es">soporte@vantelia.es</a></li>
  <li>Reclamar ante la <strong>Agencia Española de Protección de Datos</strong> en <a href="https://www.aepd.es" target="_blank" rel="noopener">www.aepd.es</a></li>
</ul>
"""

# ───────────────────── Términos ─────────────────────
TERMINOS = f"""
<h1>Términos de uso</h1>
<p class="legal-meta">Última actualización: {LAST_UPDATE} · Versión 2.0</p>

<nav class="legal-toc" aria-label="Índice">
  <strong>Índice</strong>
  <ol>
    <li><a href="#identificacion">Identificación</a></li>
    <li><a href="#objeto">Objeto y aceptación</a></li>
    <li><a href="#servicios">Servicios prestados</a></li>
    <li><a href="#cuentas">Cuentas y acceso a la plataforma</a></li>
    <li><a href="#uso-aceptable">Uso aceptable y prohibiciones</a></li>
    <li><a href="#contenido">Contenido del cliente</a></li>
    <li><a href="#asistente">Uso del asistente IA</a></li>
    <li><a href="#disponibilidad">Disponibilidad del servicio</a></li>
    <li><a href="#propiedad">Propiedad intelectual</a></li>
    <li><a href="#responsabilidad">Limitación de responsabilidad</a></li>
    <li><a href="#facturacion">Facturación y pagos</a></li>
    <li><a href="#terminacion">Terminación</a></li>
    <li><a href="#legislacion">Legislación aplicable</a></li>
  </ol>
</nav>

<h2 id="identificacion">1. Identificación</h2>
<p>Los presentes términos regulan el uso de los servicios prestados por <strong>Vantelia</strong>, accesibles a través de <a href="https://www.vantelia.es">www.vantelia.es</a> y <a href="https://app.vantelia.es">app.vantelia.es</a>. Datos de contacto: <a href="/consultas/">Solicitar consulta</a>.</p>

<h2 id="objeto">2. Objeto y aceptación</h2>
<p>Estos términos regulan la relación entre Vantelia y el usuario que accede al sitio web, contrata cualquier servicio o utiliza la plataforma. El uso del servicio implica la aceptación de estos términos y de la <a href="/legal/privacidad/">política de privacidad</a>.</p>

<h2 id="servicios">3. Servicios prestados</h2>
<p>Vantelia ofrece, entre otros:</p>
<ul>
  <li>Consultoría e implementación de IA aplicada a marketing y operaciones</li>
  <li>Desarrollo y mantenimiento de asistentes conversacionales propios por cliente</li>
  <li>Integración de canales: web, WhatsApp, calendarios, CRM y herramientas de marketing</li>
  <li>Servicios de SEO, marketing digital, automatización y analítica</li>
  <li>Acceso a la plataforma <code>app.vantelia.es</code> con panel de cliente y configuración del asistente</li>
</ul>

<h2 id="cuentas">4. Cuentas y acceso a la plataforma</h2>
<p>El acceso a la plataforma requiere credenciales individuales. El cliente es responsable de:</p>
<ul>
  <li>Custodiar las credenciales y rotar contraseñas con regularidad</li>
  <li>Notificar inmediatamente cualquier acceso no autorizado</li>
  <li>Supervisar el uso por parte de su equipo</li>
</ul>

<h2 id="uso-aceptable">5. Uso aceptable y prohibiciones</h2>
<p>Está prohibido utilizar los servicios para:</p>
<ul>
  <li>Actividades ilegales, fraudulentas o que infrinjan derechos de terceros</li>
  <li>Generar contenido que incite al odio, sea sexualmente explícito sobre menores, o promueva violencia</li>
  <li>Ingeniería inversa, scraping no autorizado o intentar acceder a datos de otros tenants</li>
  <li>Sobrecargar deliberadamente la API o el widget (ataques DoS, scraping masivo)</li>
  <li>Hacer afirmaciones falsas sobre la naturaleza humana del asistente IA en flujos comerciales</li>
</ul>

<h2 id="contenido">6. Contenido del cliente</h2>
<p>El cliente conserva todos los derechos sobre el contenido que aporta (web, documentos, FAQs, datos comerciales). Concede a Vantelia una licencia limitada, no exclusiva y revocable para procesar dicho contenido con la finalidad estricta de prestar el servicio contratado, incluyendo su indexación en sistemas de RAG (Retrieval-Augmented Generation).</p>

<h2 id="asistente">7. Uso del asistente IA</h2>
<p>El cliente reconoce que:</p>
<ul>
  <li>El asistente puede equivocarse o producir respuestas no precisas</li>
  <li>Es responsabilidad del cliente revisar y validar respuestas con impacto comercial</li>
  <li>Los precios, disponibilidad y condiciones generadas por el asistente son orientativas hasta validación humana</li>
  <li>Vantelia no garantiza que el asistente sustituya 100% la atención humana</li>
</ul>

<h2 id="disponibilidad">8. Disponibilidad del servicio</h2>
<p>Vantelia se compromete a un SLA del 99% mensual sobre los servicios de plataforma. No se contabilizan interrupciones por mantenimiento programado anunciado con 48 h de antelación, fuerza mayor, o caídas de proveedores externos (OpenAI, Hostinger, Google, Meta) ajenas a Vantelia.</p>

<h2 id="propiedad">9. Propiedad intelectual</h2>
<p>El software, marca, dominios, diseño y documentación de Vantelia son titularidad exclusiva de Vantelia o sus licenciantes. Queda prohibida su reproducción sin autorización escrita.</p>

<h2 id="responsabilidad">10. Limitación de responsabilidad</h2>
<p>En la máxima medida permitida por la ley, Vantelia no responde por:</p>
<ul>
  <li>Lucro cesante, pérdidas indirectas o consecuenciales</li>
  <li>Errores derivados de respuestas del asistente IA cuando el cliente no haya configurado o validado adecuadamente la información de su negocio</li>
  <li>Caídas o errores de proveedores terceros (OpenAI, calendarios, WhatsApp)</li>
</ul>
<p>La responsabilidad agregada de Vantelia frente al cliente queda limitada al importe efectivamente abonado en los 12 meses anteriores al hecho que motiva la reclamación.</p>

<h2 id="facturacion">11. Facturación y pagos</h2>
<p>Los planes y precios aplicables se acuerdan en propuesta o contrato firmado. Los importes se facturan en EUR, IVA no incluido salvo indicación expresa. El impago superior a 30 días faculta a Vantelia a suspender el servicio previa notificación.</p>

<h2 id="terminacion">12. Terminación</h2>
<p>Cualquiera de las partes puede terminar la relación con preaviso de 30 días naturales. En caso de terminación, Vantelia conservará los datos del cliente durante 30 días adicionales para facilitar exportación, transcurridos los cuales serán eliminados conforme al apartado 7 de la <a href="/legal/privacidad/">política de privacidad</a>.</p>

<h2 id="legislacion">13. Legislación aplicable</h2>
<p>Estos términos se rigen por la legislación española. Cualquier controversia se someterá a los Juzgados y Tribunales de la ciudad donde Vantelia tenga su domicilio social, salvo que la normativa imperativa establezca otro fuero (consumidores).</p>
"""

# ───────────────────── Cookies ─────────────────────
COOKIES = f"""
<h1>Política de cookies</h1>
<p class="legal-meta">Última actualización: {LAST_UPDATE} · Versión 2.0 · Conforme a LSSI-CE y Directiva ePrivacy</p>

<nav class="legal-toc" aria-label="Índice">
  <strong>Índice</strong>
  <ol>
    <li><a href="#que-son">Qué son las cookies</a></li>
    <li><a href="#tipos">Tipos de cookies que utilizamos</a></li>
    <li><a href="#tabla">Tabla detallada</a></li>
    <li><a href="#consentimiento">Tu consentimiento</a></li>
    <li><a href="#gestion">Cómo gestionar cookies</a></li>
    <li><a href="#widget">Cookies en el widget IA</a></li>
    <li><a href="#actualizaciones">Actualizaciones</a></li>
  </ol>
</nav>

<h2 id="que-son">1. Qué son las cookies</h2>
<p>Las cookies son pequeños ficheros que un sitio web instala en tu dispositivo para almacenar información de tu navegación (preferencias, sesión, identificadores anónimos). Junto con otras tecnologías similares (localStorage, sessionStorage, fingerprinting técnico), se rigen por la presente política.</p>

<h2 id="tipos">2. Tipos de cookies que utilizamos</h2>
<ul>
  <li><strong>Técnicas o necesarias:</strong> imprescindibles para el funcionamiento del sitio. No requieren consentimiento.</li>
  <li><strong>De preferencias:</strong> recuerdan elecciones del usuario (idioma, zona horaria).</li>
  <li><strong>Analíticas:</strong> permiten medir el uso agregado del sitio (páginas vistas, dispositivos, tiempo de sesión). Sólo se activan con consentimiento.</li>
  <li><strong>De marketing:</strong> actualmente <strong>no utilizamos</strong> cookies publicitarias de terceros. Si en el futuro las añadimos, lo notificaremos.</li>
</ul>

<h2 id="tabla">3. Tabla detallada</h2>
<table>
  <thead><tr><th>Cookie / Storage</th><th>Tipo</th><th>Finalidad</th><th>Duración</th><th>Propietario</th></tr></thead>
  <tbody>
    <tr><td><code>vantelia_session</code></td><td>Técnica</td><td>Mantener sesión en plataforma</td><td>Sesión</td><td>Vantelia</td></tr>
    <tr><td><code>ia_session_id</code> (sessionStorage)</td><td>Técnica</td><td>Mantener contexto del asistente IA durante 30 min</td><td>30 min</td><td>Vantelia</td></tr>
    <tr><td><code>cookie_consent</code></td><td>Técnica</td><td>Recordar tu elección sobre cookies</td><td>12 meses</td><td>Vantelia</td></tr>
    <tr><td><code>vantelia_locale</code></td><td>Preferencia</td><td>Idioma y zona horaria</td><td>12 meses</td><td>Vantelia</td></tr>
  </tbody>
</table>
<p>No utilizamos Google Analytics, Meta Pixel, ni similares en el sitio público.</p>

<h2 id="consentimiento">4. Tu consentimiento</h2>
<p>Las cookies técnicas se aplican siempre por necesidad operativa. Cualquier cookie no técnica requiere tu consentimiento explícito a través del banner cuando entras al sitio. Puedes aceptar todas, rechazar las no esenciales, o personalizar tu elección. Esta decisión se almacena durante 12 meses y puedes modificarla en cualquier momento.</p>

<h2 id="gestion">5. Cómo gestionar cookies</h2>
<p>Puedes bloquear o eliminar cookies desde la configuración de tu navegador:</p>
<ul>
  <li><a href="https://support.google.com/chrome/answer/95647" target="_blank" rel="noopener">Chrome</a></li>
  <li><a href="https://support.mozilla.org/es/kb/proteccion-antirrastreo-mejorada-firefox-escritorio" target="_blank" rel="noopener">Firefox</a></li>
  <li><a href="https://support.apple.com/es-es/guide/safari/sfri11471/mac" target="_blank" rel="noopener">Safari</a></li>
  <li><a href="https://support.microsoft.com/es-es/microsoft-edge" target="_blank" rel="noopener">Edge</a></li>
</ul>
<p>El bloqueo de cookies técnicas puede afectar a la disponibilidad del servicio.</p>

<h2 id="widget">6. Cookies en el widget IA</h2>
<p>El widget conversacional embebido en webs de clientes utiliza únicamente almacenamiento local (sessionStorage) para mantener el contexto de la conversación durante 30 minutos. No deja cookies en dominios cruzados ni rastreo entre sitios.</p>

<h2 id="actualizaciones">7. Actualizaciones</h2>
<p>Esta política puede actualizarse para reflejar cambios técnicos o legales. La fecha de última revisión figura al inicio del documento.</p>
"""

# ───────────────────── IA Responsable ─────────────────────
IA_RESPONSABLE = f"""
<h1>IA responsable</h1>
<p class="legal-meta">Última actualización: {LAST_UPDATE} · Versión 1.0 · Alineado con AI Act (UE 2024/1689) y principios OECD AI</p>

<nav class="legal-toc" aria-label="Índice">
  <strong>Índice</strong>
  <ol>
    <li><a href="#mision">Compromiso</a></li>
    <li><a href="#principios">Principios</a></li>
    <li><a href="#transparencia">Transparencia algorítmica</a></li>
    <li><a href="#sesgos">Sesgos y mitigación</a></li>
    <li><a href="#supervision">Supervisión humana</a></li>
    <li><a href="#datos">Datos de entrenamiento</a></li>
    <li><a href="#riesgos">Clasificación de riesgo (AI Act)</a></li>
    <li><a href="#derechos-usuario">Derechos del usuario final</a></li>
    <li><a href="#incidentes">Gestión de incidentes</a></li>
    <li><a href="#contacto">Contacto</a></li>
  </ol>
</nav>

<h2 id="mision">1. Compromiso</h2>
<p>Vantelia construye sistemas de IA conversacional para empresas. Asumimos públicamente que la IA es una tecnología potente con riesgos reales (alucinaciones, sesgo, opacidad) y nos comprometemos a operar con transparencia, supervisión humana y mejora continua.</p>

<h2 id="principios">2. Principios</h2>
<ul>
  <li><strong>Transparencia:</strong> el usuario final siempre sabe que conversa con una IA.</li>
  <li><strong>Trazabilidad:</strong> conservamos logs auditables de las conversaciones del asistente.</li>
  <li><strong>Privacidad por diseño:</strong> aislamiento por cliente, mínima recogida, cifrado.</li>
  <li><strong>Equidad:</strong> revisión periódica de sesgos en respuestas críticas.</li>
  <li><strong>Supervisión humana:</strong> rutas de escalado a humanos definidas.</li>
  <li><strong>Robustez:</strong> rate limits, validación de salida, fallback a respuestas conservadoras.</li>
</ul>

<h2 id="transparencia">3. Transparencia algorítmica</h2>
<h3>3.1. Modelos</h3>
<p>Utilizamos modelos de OpenAI (GPT-4o-mini, GPT-4o, text-embedding-3-small) accedidos vía API empresarial. No empleamos modelos opacos sin documentación o desarrollados por proveedores no auditables.</p>
<h3>3.2. Configuración por cliente</h3>
<p>Cada cliente puede consultar y modificar:</p>
<ul>
  <li>Mensaje de bienvenida y tono del asistente</li>
  <li>Instrucciones internas que condicionan el comportamiento</li>
  <li>Contenido del "cerebro" (info.txt) que alimenta el RAG</li>
  <li>Activación/desactivación de canales (web, WhatsApp)</li>
</ul>

<h2 id="sesgos">4. Sesgos y mitigación</h2>
<p>Los modelos de lenguaje pueden reflejar sesgos presentes en sus datos de entrenamiento. Para mitigarlos:</p>
<ul>
  <li>Limitamos el dominio de respuesta al cerebro de cada cliente (RAG selectivo)</li>
  <li>Evitamos preguntas de opinión, ideología o consejos médicos/legales/financieros</li>
  <li>Auditamos muestras aleatorias de conversaciones cada trimestre</li>
  <li>Permitimos al cliente reportar respuestas inapropiadas para ajuste inmediato</li>
</ul>

<h2 id="supervision">5. Supervisión humana</h2>
<p>El asistente nunca toma decisiones con efecto jurídico o significativo sobre personas. Decisiones críticas (precios, citas, condiciones contractuales) se confirman con un humano del equipo del cliente. Detectamos automáticamente situaciones que requieren escalado: peticiones complejas, frustración del usuario, ambigüedad alta.</p>

<h2 id="datos">6. Datos de entrenamiento</h2>
<p>Vantelia <strong>no entrena modelos de IA con datos de clientes</strong>. Las conversaciones tampoco se utilizan para entrenar modelos públicos de OpenAI (la API empresarial lo prohíbe contractualmente). Las únicas adaptaciones por cliente son:</p>
<ul>
  <li>Indexación vectorial del "cerebro" propio del cliente para RAG</li>
  <li>Configuración del prompt de sistema (no entrenamiento)</li>
</ul>

<h2 id="riesgos">7. Clasificación de riesgo (AI Act)</h2>
<p>Conforme al Reglamento (UE) 2024/1689 (AI Act), los sistemas de Vantelia operan en la categoría de <strong>riesgo limitado</strong> (asistentes conversacionales con obligaciones de transparencia). No prestamos servicios en categorías de alto riesgo (selección de personal, scoring crediticio, asistencia legal vinculante, decisiones administrativas, etc.). Si un cliente nos solicitara aplicar la IA a usos de alto riesgo, lo declinaríamos o realizaríamos la evaluación de conformidad correspondiente.</p>

<h2 id="derechos-usuario">8. Derechos del usuario final</h2>
<p>Cualquier persona que interactúe con un asistente Vantelia tiene derecho a:</p>
<ul>
  <li>Saber que conversa con una IA (se indica explícitamente)</li>
  <li>Solicitar atención humana en cualquier momento</li>
  <li>Pedir el borrado de su conversación (ver <a href="/legal/privacidad/">privacidad</a>)</li>
  <li>Recibir explicación sobre cómo se generó una respuesta concreta</li>
  <li>No ser objeto de decisiones automatizadas con efecto jurídico</li>
</ul>

<h2 id="incidentes">9. Gestión de incidentes</h2>
<p>Si detectas una respuesta incorrecta, ofensiva o problemática, repórtanos a <a href="mailto:soporte@vantelia.es">soporte@vantelia.es</a>. Procedimiento:</p>
<ul>
  <li>Acuse de recibo en 48 h hábiles</li>
  <li>Análisis con el cliente afectado en 5 días</li>
  <li>Aplicación de medida correctiva (ajuste de prompt, contenido del cerebro, lógica de respuesta)</li>
  <li>Notificación de cierre del caso al usuario que reportó</li>
</ul>

<h2 id="contacto">10. Contacto</h2>
<p>Para consultas sobre IA responsable: <a href="mailto:soporte@vantelia.es">soporte@vantelia.es</a> o <a href="/consultas/">Solicitar consulta</a>.</p>
"""

PAGES = {
    "privacidad": ("Política de privacidad | Vantelia", "Política de privacidad de Vantelia conforme a RGPD: tratamiento de datos en sistemas de IA, derechos del usuario, encargados y plazos.", PRIVACIDAD),
    "terminos":   ("Términos de uso | Vantelia",        "Términos y condiciones de uso de los servicios y plataforma de Vantelia: IA, marketing digital y automatización para empresas B2B.", TERMINOS),
    "cookies":    ("Política de cookies | Vantelia",     "Política de cookies de Vantelia: tipos, finalidad, duración y cómo gestionar tu consentimiento conforme a la Directiva ePrivacy.", COOKIES),
    "ia-responsable": ("IA responsable | Vantelia",      "Compromiso de Vantelia con una IA transparente, supervisada y conforme al AI Act europeo. Principios, sesgos, riesgos y derechos.", IA_RESPONSABLE),
}


def main():
    LEGAL_DIR.mkdir(parents=True, exist_ok=True)
    for slug, (title, desc, body) in PAGES.items():
        out_dir = LEGAL_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "index.html"
        out.write_text(page(slug, title, desc, body), encoding="utf-8")
        size_kb = out.stat().st_size / 1024
        print(f"  /legal/{slug}/  ({size_kb:.1f} KB)")
    print(f"\n{len(PAGES)} pagina(s) legal(es) generada(s).")


if __name__ == "__main__":
    main()
