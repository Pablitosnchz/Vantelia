"""Genera sub-paginas HTML con diseno del home (home.css) y SEO completo.
Uso: python scripts/build-pages.py
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "hostinger_site"
BASE_URL = "https://www.vantelia.es"

# ── Header HTML compartido ────────────────────────────────────
HEADER = """<!-- Cursor ambient glow (desktop) -->
<div id="cursor-glow" aria-hidden="true"></div>

<header class="site-header" id="site-header">
  <div class="shell nav-inner">
    <a href="/" class="brand" aria-label="Vantelia · Inicio">
      <img src="/assets/img/logo-letra.png" alt="Logo Vantelia · Agencia de IA y Marketing B2B" width="200" height="48" fetchpriority="high" decoding="async">
    </a>
    <nav aria-label="Navegación principal">
      <ul class="nav-links">
        <li><a href="/servicios/"{servicios_aria}>Servicios</a></li>
        <li><a href="/plataforma/"{plataforma_aria}>Plataforma</a></li>
        <li><a href="/resultados/"{resultados_aria}>Resultados</a></li>
        <li><a href="/nosotros/"{nosotros_aria}>Nosotros</a></li>
        <li><a href="/faq/"{faq_aria}>FAQ</a></li>
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

<script src="/assets/js/home.js" defer></script>
<script
  src="https://app.vantelia.es/widget/widget.min.js?v=20260605-sitewide"
  data-api="https://app.vantelia.es"
  data-client="Vantelia"
  data-position="right"></script>"""


def make_breadcrumbs_jsonld(items):
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": url}
            for i, (name, url) in enumerate(items)
        ],
    }


def make_breadcrumbs_html(items):
    parts = []
    for i, (name, url) in enumerate(items):
        is_last = i == len(items) - 1
        if is_last:
            parts.append(f'<span aria-current="page">{name}</span>')
        else:
            parts.append(f'<a href="{url.replace(BASE_URL, "")}">{name}</a>')
        if not is_last:
            parts.append('<span class="sep" aria-hidden="true">/</span>')
    return '<nav class="breadcrumbs" aria-label="Migas de pan">' + " ".join(parts) + "</nav>"


def page(slug, title, description, og_image, breadcrumbs, hero_eyebrow, hero_h1, hero_lead, hero_cta_primary, hero_cta_secondary, sections, extra_schema=None, body_class=""):
    canonical = f"{BASE_URL}/{slug}/"
    aria = {k: ' aria-current="page"' if k == slug else "" for k in ["servicios", "plataforma", "resultados", "nosotros", "faq"]}
    header_html = HEADER.format(
        servicios_aria=aria.get("servicios", ""),
        plataforma_aria=aria.get("plataforma", ""),
        resultados_aria=aria.get("resultados", ""),
        nosotros_aria=aria.get("nosotros", ""),
        faq_aria=aria.get("faq", ""),
    )

    bc_jsonld = make_breadcrumbs_jsonld(breadcrumbs)
    bc_html = make_breadcrumbs_html(breadcrumbs)

    schema_graph = [
        {"@type": "Organization", "@id": f"{BASE_URL}/#org"},
        bc_jsonld,
        {
            "@type": "WebPage",
            "url": canonical,
            "name": title,
            "description": description,
            "inLanguage": "es-ES",
            "isPartOf": {"@id": f"{BASE_URL}/#website"},
            "publisher": {"@id": f"{BASE_URL}/#org"},
        },
    ]
    if extra_schema:
        schema_graph.extend(extra_schema)

    schema = {"@context": "https://schema.org", "@graph": schema_graph}
    schema_str = json.dumps(schema, ensure_ascii=False, indent=2)

    head = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <meta name="theme-color" content="#0B132B">
  <meta name="author" content="Vantelia">
  <link rel="canonical" href="{canonical}">
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/img/favicon.png">
  <link rel="apple-touch-icon" href="/assets/img/favicon.png">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Vantelia">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{BASE_URL}{og_image}">
  <meta property="og:locale" content="es_ES">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{BASE_URL}{og_image}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="preload" as="image" href="/assets/img/fondo-web.png" fetchpriority="high">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/assets/css/home.css">
  <script type="application/ld+json">
{schema_str}
  </script>
</head>
<body{(' class="' + body_class + '"') if body_class else ''}>"""

    hero_actions = ""
    if hero_cta_primary:
        hero_actions += f'<a href="{hero_cta_primary[1]}" class="btn btn-primary btn-lg">{hero_cta_primary[0]}</a>'
    if hero_cta_secondary:
        hero_actions += f'<a href="{hero_cta_secondary[1]}" class="btn btn-ghost btn-lg">{hero_cta_secondary[0]}</a>'

    hero_html = f"""<section class="subpage-hero" aria-label="Cabecera de página">
  <div class="hero-bg" aria-hidden="true"></div>
  <div class="shell">
    {bc_html}
    <div class="hero-badge">
      <span class="badge-dot" aria-hidden="true"></span>
      {hero_eyebrow}
    </div>
    <h1>{hero_h1}</h1>
    <p class="hero-lead">{hero_lead}</p>
    <div class="hero-actions">{hero_actions}</div>
  </div>
</section>

<div class="glow-line" aria-hidden="true"></div>"""

    sections_html = "\n\n".join(sections)

    cta_html = """<section class="section cta-section" aria-label="Contacto">
  <div class="cta-bg" aria-hidden="true"></div>
  <div class="shell">
    <div class="cta-inner reveal">
      <span class="eyebrow">¿Empezamos?</span>
      <h2>Una sola conversación puede cambiar cómo crece tu empresa.</h2>
      <p>
        Cuéntanos tu situación y te diremos qué tiene más sentido: IA, marketing,
        automatización o las tres a la vez. Primera consulta gratuita y sin compromiso.
      </p>
      <div class="cta-actions">
        <a href="/consultas/" class="btn btn-primary btn-lg">Solicitar auditoría gratuita</a>
        <a href="mailto:info@vantelia.es" class="btn btn-ghost btn-lg">Hablar con Vantelia</a>
      </div>
      <p class="cta-note">Sin costes ocultos · Respuesta en menos de 24h · Equipo senior</p>
    </div>
  </div>
</section>"""

    return f"{head}\n\n{header_html}\n\n{hero_html}\n\n{sections_html}\n\n{cta_html}\n\n{FOOTER}\n\n</body>\n</html>\n"


# ── PAGES ─────────────────────────────────────────────────

PAGES = {}

# ── SERVICIOS ─────────────────────────────────────────────
PAGES["servicios"] = page(
    slug="servicios",
    title="Asistentes IA personalizados para empresas | Servicios | Vantelia",
    description="Asistentes IA propios entrenados con tus datos. Reservas automáticas, WhatsApp IA, integraciones nativas y panel propio. Marketing digital y SEO B2B como complemento.",
    og_image="/assets/img/resumen.png",
    breadcrumbs=[("Inicio", BASE_URL + "/"), ("Servicios", BASE_URL + "/servicios/")],
    hero_eyebrow="IA + automatización + marketing",
    hero_h1="Asistentes IA personalizables, entrenados con la información de tu empresa.",
    hero_lead="Nuestro producto principal es un asistente conversacional propio para cada cliente: aprende de tu web y documentos, agenda citas, responde por WhatsApp y se conecta a tus herramientas. Todo lo demás (marketing, SEO, automatización) lo construimos alrededor.",
    hero_cta_primary=("Solicitar demo gratuita", "/consultas/"),
    hero_cta_secondary=("Ver plataforma", "/plataforma/"),
    sections=[
        """<section class="section services-bg" aria-label="Producto principal: IA personalizable">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Producto principal</span>
      <h2>Una IA propia para cada empresa. No un chatbot genérico.</h2>
      <p class="section-lead">Cada asistente Vantelia se entrena con la información real de tu negocio: web, documentos, FAQs, precios, servicios. Responde con precisión, deriva al equipo cuando hace falta y aprende de cada conversación.</p>
    </div>
    <div class="services-grid">
      <article class="svc-card wide reveal d1">
        <div class="svc-ico ico-a" aria-hidden="true">🧠</div>
        <span class="svc-tag">01 · Asistente IA personalizado</span>
        <h3>Tu propio cerebro IA, entrenado con tus datos</h3>
        <p>Cada cliente dispone de una IA exclusiva con su propio índice vectorial (RAG). Editas el cerebro, el tono, el saludo, los colores y el logo desde un panel claro. Cero plantillas, cero respuestas genéricas.</p>
        <div class="svc-body">
          <ul class="svc-feats">
            <li class="svc-feat">RAG (Retrieval-Augmented Generation) propio por tenant</li>
            <li class="svc-feat">Configuración de tono, identidad, prompt e instrucciones internas</li>
            <li class="svc-feat">Logo y colores de marca personalizables</li>
            <li class="svc-feat">Reindexación en segundos cuando cambias la información</li>
            <li class="svc-feat">Aislamiento total entre clientes (multi-tenant)</li>
          </ul>
        </div>
      </article>
      <article class="svc-card reveal d2">
        <div class="svc-ico ico-b" aria-hidden="true">📅</div>
        <span class="svc-tag">02 · Reservas y agenda IA</span>
        <h3>Tu IA agenda citas sola</h3>
        <p>El asistente cualifica al usuario, consulta disponibilidad real y reserva la cita en la Agenda de Vantelia. Notifica por email a ambas partes. Cero intervención manual.</p>
        <ul class="svc-feats">
          <li class="svc-feat">Sincronización con la Agenda de Vantelia</li>
          <li class="svc-feat">Servicios, horarios, profesionales y bloqueos por cliente</li>
          <li class="svc-feat">Recordatorios 24h y 2h antes</li>
          <li class="svc-feat">Cancelación y reprogramación con un clic</li>
        </ul>
      </article>
      <article class="svc-card reveal d3">
        <div class="svc-ico ico-c" aria-hidden="true">💬</div>
        <span class="svc-tag">03 · WhatsApp IA</span>
        <h3>Mismo asistente. Por WhatsApp.</h3>
        <p>Webhook nativo con WhatsApp Cloud API. La IA responde, agenda y deriva igual que en la web, con el mismo cerebro. Conversación unificada en el panel.</p>
        <ul class="svc-feats">
          <li class="svc-feat">WhatsApp Cloud API oficial de Meta</li>
          <li class="svc-feat">Webhook por cliente, número propio</li>
          <li class="svc-feat">Mismo RAG, misma configuración, mismo tono</li>
        </ul>
      </article>
      <article class="svc-card reveal d4">
        <div class="svc-ico ico-d" aria-hidden="true">🔗</div>
        <span class="svc-tag">04 · Widget embebible</span>
        <h3>Un snippet JS. Cualquier web.</h3>
        <p>Pega una línea en tu HTML y el asistente está vivo. Compatible con WordPress, Webflow, Shopify, Squarespace o HTML puro. Se adapta a tu marca automáticamente.</p>
        <ul class="svc-feats">
          <li class="svc-feat">Instalación en menos de 5 minutos</li>
          <li class="svc-feat">Posicionamiento configurable y CSS aislado</li>
          <li class="svc-feat">Carga asíncrona sin penalizar el LCP</li>
        </ul>
      </article>
      <article class="svc-card reveal d1">
        <div class="svc-ico ico-a" aria-hidden="true">⚡</div>
        <span class="svc-tag">05 · Alta express</span>
        <h3>De URL a IA operativa en menos de un día</h3>
        <p>Mándanos tu web. Analizamos, indexamos, configuramos y entregamos el widget listo. Tú revisas el cerebro y publicas.</p>
        <ul class="svc-feats">
          <li class="svc-feat">Scraping y extracción automática de tu información pública</li>
          <li class="svc-feat">Generación del índice RAG en horas</li>
          <li class="svc-feat">Editor del cerebro accesible desde el panel</li>
        </ul>
      </article>
      <article class="svc-card reveal d2">
        <div class="svc-ico ico-b" aria-hidden="true">📊</div>
        <span class="svc-tag">06 · Métricas y conversaciones</span>
        <h3>Sabes lo que la IA hace. Siempre.</h3>
        <p>Panel con conversaciones guardadas, intenciones detectadas, citas generadas, leads cualificados y embudo completo. Sin dispersión entre herramientas.</p>
        <ul class="svc-feats">
          <li class="svc-feat">Historial completo de cada conversación con etiquetas de intención</li>
          <li class="svc-feat">KPIs: conversaciones, citas, satisfacción, deflection</li>
          <li class="svc-feat">Exportación a CSV y conexión con tu CRM</li>
        </ul>
      </article>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Servicios complementarios">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Servicios complementarios</span>
      <h2>Marketing y SEO B2B que potencian tu IA.</h2>
      <p class="section-lead">La IA convierte conversaciones en oportunidades. Marketing y SEO traen conversaciones cualificadas. Lo conectamos todo en un sistema único.</p>
    </div>
    <div class="content-grid-4">
      <article class="content-card reveal d1">
        <span class="c-tag">SEO B2B</span>
        <h3>Posicionamiento orgánico</h3>
        <p>Mapeo de intenciones, landings de captación, semántica y autoridad temática para empresas que necesitan tráfico cualificado.</p>
      </article>
      <article class="content-card reveal d2">
        <span class="c-tag">Paid media</span>
        <h3>Campañas y CRO</h3>
        <p>Estructura de campañas alineadas al embudo, revisión de oferta y copy, optimización con datos. Sin gastar por gastar.</p>
      </article>
      <article class="content-card reveal d3">
        <span class="c-tag">Email & CRM</span>
        <h3>Automatización comercial</h3>
        <p>Secuencias de seguimiento, scoring, conexión con HubSpot, Pipedrive o el CRM que uses. La IA alimenta el pipeline.</p>
      </article>
      <article class="content-card reveal d4">
        <span class="c-tag">Analítica</span>
        <h3>Dashboard ejecutivo</h3>
        <p>Lectura unificada de captación, conversión, IA y comercial. Para decidir qué escalar y qué retirar.</p>
      </article>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Cómo trabajamos">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Cómo trabajamos</span>
      <h2>Un modelo pensado para avanzar sin ruido.</h2>
    </div>
    <div class="process-grid">
      <article class="process-step reveal d1">
        <div class="p-num">01</div>
        <h3>Contexto</h3>
        <p>Entendemos negocio, oferta, embudo, stack y fricciones reales entre equipos y canales.</p>
      </article>
      <article class="process-step reveal d2">
        <div class="p-num">02</div>
        <h3>Arquitectura</h3>
        <p>Definimos el sistema de captación, conversión, automatización e IA que mejor encaja.</p>
      </article>
      <article class="process-step reveal d3">
        <div class="p-num">03</div>
        <h3>Despliegue</h3>
        <p>Implementamos por bloques. Cada fase genera aprendizaje y valor antes de la siguiente.</p>
      </article>
      <article class="process-step reveal d4">
        <div class="p-num">04</div>
        <h3>Escalado</h3>
        <p>Ajustamos lo que funciona, retiramos lo que no aporta y concentramos energía donde más mueve negocio.</p>
      </article>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Para qué empresas">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Dónde encaja mejor</span>
      <h2>Especialmente útil para empresas con tracción y sistema fragmentado.</h2>
    </div>
    <div class="content-grid-4">
      <article class="content-card reveal d1">
        <h3>B2B y servicios alto valor</h3>
        <p>Cuando hay varias etapas de decisión y el seguimiento comercial pesa tanto como la captación.</p>
      </article>
      <article class="content-card reveal d2">
        <h3>Equipos con CRM parcial</h3>
        <p>Si ya existe stack pero falta coherencia entre formularios, mensajes, oportunidades y respuesta.</p>
      </article>
      <article class="content-card reveal d3">
        <h3>Marcas con inversión</h3>
        <p>Y necesitan que el rendimiento deje de depender de campañas sueltas o intuiciones dispersas.</p>
      </article>
      <article class="content-card reveal d4">
        <h3>Empresas que aplican IA</h3>
        <p>No como adorno, sino como mejora operativa o comercial con impacto medible.</p>
      </article>
    </div>
  </div>
</section>""",
    ],
    extra_schema=[
        {
            "@type": "Service",
            "serviceType": "Asistentes IA personalizados y plataforma SaaS",
            "provider": {"@id": f"{BASE_URL}/#org"},
            "areaServed": "ES",
            "url": f"{BASE_URL}/servicios/",
            "hasOfferCatalog": {
                "@type": "OfferCatalog",
                "name": "Servicios Vantelia",
                "itemListElement": [
                    {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Asistente IA personalizado por cliente (RAG propio)"}},
                    {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Reservas automáticas y agenda IA"}},
                    {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "WhatsApp IA con webhook nativo"}},
                    {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Widget embebible y alta express"}},
                    {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "SEO B2B y marketing digital complementario"}},
                    {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "Analítica unificada de IA y pipeline"}},
                ],
            },
        }
    ],
    body_class="page-servicios",
)

# ── PLATAFORMA ────────────────────────────────────────────
PAGES["plataforma"] = page(
    slug="plataforma",
    title="Plataforma de IA para Empresas | app.vantelia.es | Vantelia",
    description="Plataforma multi-tenant: asistente IA propio, panel de administración, portal de cliente, configuración de IA, conversaciones, agenda y métricas. Una sola arquitectura.",
    og_image="/assets/img/prototipo-web.png",
    breadcrumbs=[("Inicio", BASE_URL + "/"), ("Plataforma", BASE_URL + "/plataforma/")],
    hero_eyebrow="app.vantelia.es",
    hero_h1="Una plataforma. Cada empresa con su IA propia.",
    hero_lead="Multi-tenant. Cada cliente tiene asistente, cerebro, panel y métricas separados. Nosotros gestionamos la infraestructura. Tú decides cómo se comporta tu IA, qué sabe, qué responde y cómo se conecta.",
    hero_cta_primary=("Acceder a la plataforma", "https://app.vantelia.es/acceso"),
    hero_cta_secondary=("Solicitar demo", "/consultas/"),
    sections=[
        """<section class="section platform-bg" aria-label="Vistas de la plataforma">
  <div class="shell">
    <div class="section-head centered reveal" style="margin-inline:auto;text-align:center;max-width:680px">
      <span class="eyebrow">Vistas reales · app.vantelia.es</span>
      <h2>Esto es lo que ves al entrar.</h2>
      <p class="section-lead">Capturas fieles de la plataforma actual. Cada vista es navegable y operativa desde el primer día tras el alta.</p>
    </div>

    <!-- VISTA 1 — EDITOR IA -->
    <div class="platform-grid reveal" style="margin-top:64px">
      <div class="platform-visual" style="order:1">
        <div class="platform-screen">
          <div class="pscreen-bar">
            <div class="pscreen-dot" style="background:#ff5f57"></div>
            <div class="pscreen-dot" style="background:#febc2e"></div>
            <div class="pscreen-dot" style="background:#28c840"></div>
            <div class="pscreen-url">app.vantelia.es/portal#ia</div>
          </div>
          <div class="pscreen-body">
            <div class="pscreen-head">
              <div class="pscreen-title">Editor del asistente</div>
              <div class="pscreen-badge">● Live preview</div>
            </div>
            <div style="display:grid;gap:8px;font-size:.78rem">
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:9px 11px">
                <div style="color:var(--muted-2);font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Título del asistente</div>
                <div style="color:var(--text)">Clínica Estética Plus</div>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">
                <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:9px 11px">
                  <div style="color:var(--muted-2);font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Color principal</div>
                  <div style="display:flex;align-items:center;gap:6px"><span style="width:12px;height:12px;border-radius:50%;background:#00D1FF"></span><code style="font-size:.74rem;color:var(--text)">#00D1FF</code></div>
                </div>
                <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:9px 11px">
                  <div style="color:var(--muted-2);font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Color acento</div>
                  <div style="display:flex;align-items:center;gap:6px"><span style="width:12px;height:12px;border-radius:50%;background:#00F5D4"></span><code style="font-size:.74rem;color:var(--text)">#00F5D4</code></div>
                </div>
              </div>
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:9px 11px">
                <div style="color:var(--muted-2);font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Mensaje de bienvenida</div>
                <div style="color:var(--text);font-size:.78rem">Hola, soy el asistente de Clínica Estética Plus. ¿En qué puedo ayudarte hoy?</div>
              </div>
              <div style="background:rgba(0,209,255,.06);border:1px solid rgba(0,209,255,.20);border-radius:10px;padding:9px 11px">
                <div style="color:var(--primary);font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Instrucciones internas</div>
                <div style="color:var(--text);font-size:.76rem;line-height:1.5">Responde en tono cercano. No inventes precios. Deriva a humano si detectas urgencia médica.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="platform-copy">
        <span class="eyebrow">01 · Configuración de IA</span>
        <h3 style="font-size:1.4rem">Edita el cerebro de tu asistente, sin tocar código</h3>
        <p>Título, logo, colores de marca, tono, mensaje de bienvenida e instrucciones internas. Todo desde un panel claro con preview en vivo del widget.</p>
        <ul class="bullet-list">
          <li>Logo y colores personalizables</li>
          <li>Prompt de sistema editable con texto plano</li>
          <li>Instrucciones internas que el usuario nunca ve</li>
          <li>Cerebro (info.txt) editable y reindexación automática</li>
        </ul>
      </div>
    </div>

    <!-- VISTA 2 — PORTAL CLIENTE: agenda + citas -->
    <div class="platform-grid reveal" style="margin-top:64px">
      <div class="platform-copy">
        <span class="eyebrow">02 · Portal cliente</span>
        <h3 style="font-size:1.4rem">Calendario, citas del día y métricas</h3>
        <p>Cada empresa ve sus reservas, gestiona profesionales, define horarios y bloquea fechas. Días cerrados en rojo, vacaciones en amarillo, cambios al instante.</p>
        <ul class="bullet-list">
          <li>Calendario mensual con eventos coloreados por estado</li>
          <li>Citas del día con servicio, profesional y datos del cliente</li>
          <li>Reprogramar y cancelar con un clic</li>
          <li>Bloqueos y vacaciones por profesional o agenda general</li>
        </ul>
      </div>
      <div class="platform-visual">
        <div class="platform-screen">
          <div class="pscreen-bar">
            <div class="pscreen-dot" style="background:#ff5f57"></div>
            <div class="pscreen-dot" style="background:#febc2e"></div>
            <div class="pscreen-dot" style="background:#28c840"></div>
            <div class="pscreen-url">app.vantelia.es/portal#calendario</div>
          </div>
          <div class="pscreen-body">
            <div class="pscreen-head">
              <div class="pscreen-title">Jueves, 30 de abril · 2 citas</div>
              <div class="pscreen-badge">● Live</div>
            </div>
            <div style="display:grid;gap:6px">
              <div style="display:grid;grid-template-columns:48px 1fr;gap:10px;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px 12px">
                <div style="font-family:var(--font-d);color:var(--primary);font-weight:700;font-size:.92rem">09:30</div>
                <div>
                  <div style="font-size:.82rem;color:var(--text);font-weight:600">Pablo Sánchez</div>
                  <div style="font-size:.72rem;color:var(--muted)"><span style="color:var(--accent);font-weight:600">Dra Marta</span> · Automatización de procesos</div>
                </div>
              </div>
              <div style="display:grid;grid-template-columns:48px 1fr;gap:10px;background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px 12px">
                <div style="font-family:var(--font-d);color:var(--primary);font-weight:700;font-size:.92rem">11:00</div>
                <div>
                  <div style="font-size:.82rem;color:var(--text);font-weight:600">Sofía Fernández</div>
                  <div style="font-size:.72rem;color:var(--muted)"><span style="color:var(--accent);font-weight:600">Paco</span> · Campañas personalizadas</div>
                </div>
              </div>
              <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-top:8px">
                <div style="background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:6px;padding:6px;text-align:center;font-size:.7rem">28</div>
                <div style="background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:6px;padding:6px;text-align:center;font-size:.7rem">29</div>
                <div style="background:rgba(0,209,255,.10);border:1px solid var(--primary);border-radius:6px;padding:6px;text-align:center;font-size:.7rem;color:var(--primary);font-weight:700">30</div>
                <div style="background:rgba(247,93,122,.10);border:1px solid rgba(247,93,122,.45);border-radius:6px;padding:6px;text-align:center;font-size:.7rem;color:#F75D7A">1</div>
                <div style="background:rgba(245,165,36,.10);border:1px solid rgba(245,165,36,.45);border-radius:6px;padding:6px;text-align:center;font-size:.7rem;color:#F5A524">2</div>
                <div style="background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:6px;padding:6px;text-align:center;font-size:.7rem">3</div>
                <div style="background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:6px;padding:6px;text-align:center;font-size:.7rem">4</div>
              </div>
              <div style="display:flex;gap:14px;font-size:.7rem;color:var(--muted);margin-top:6px">
                <span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:#F75D7A;margin-right:5px"></span>Cerrado</span>
                <span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:#F5A524;margin-right:5px"></span>Bloqueado</span>
                <span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:var(--primary);margin-right:5px"></span>Hoy</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- VISTA 3 — CONVERSACIONES -->
    <div class="platform-grid reveal" style="margin-top:64px">
      <div class="platform-visual" style="order:1">
        <div class="platform-screen">
          <div class="pscreen-bar">
            <div class="pscreen-dot" style="background:#ff5f57"></div>
            <div class="pscreen-dot" style="background:#febc2e"></div>
            <div class="pscreen-dot" style="background:#28c840"></div>
            <div class="pscreen-url">app.vantelia.es/portal#conversaciones</div>
          </div>
          <div class="pscreen-body">
            <div class="pscreen-head">
              <div class="pscreen-title">Conversaciones del asistente</div>
              <div class="pscreen-badge">● 8 mensajes</div>
            </div>
            <div style="display:grid;gap:6px;font-size:.78rem">
              <div style="background:linear-gradient(135deg,rgba(0,209,255,.10),rgba(0,245,212,.06));border:1px solid rgba(0,209,255,.28);border-radius:10px;padding:8px 10px">
                <div style="font-size:.66rem;color:var(--primary);font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px">Asistente IA</div>
                <div style="color:var(--text)">Hola, soy el asistente de Clínica Estética Plus. ¿En qué puedo ayudarte?</div>
              </div>
              <div style="background:rgba(255,255,255,.05);border:1px solid var(--border);border-radius:10px;padding:8px 10px;margin-left:auto;max-width:80%">
                <div style="color:var(--text)">Quiero información sobre tratamiento facial</div>
              </div>
              <div style="background:linear-gradient(135deg,rgba(0,209,255,.10),rgba(0,245,212,.06));border:1px solid rgba(0,209,255,.28);border-radius:10px;padding:8px 10px">
                <div style="font-size:.66rem;color:var(--primary);font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px">Asistente IA</div>
                <div style="color:var(--text)">Te recomiendo nuestro Hydrafacial Premium. ¿Quieres ver disponibilidad?</div>
              </div>
              <div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:4px">
                <span style="background:rgba(0,245,212,.10);border:1px solid rgba(0,245,212,.30);color:#00F5D4;padding:2px 8px;border-radius:5px;font-size:.66rem;font-weight:600">recomendación</span>
                <span style="background:rgba(0,209,255,.10);border:1px solid rgba(0,209,255,.30);color:var(--primary);padding:2px 8px;border-radius:5px;font-size:.66rem;font-weight:600">agenda</span>
                <span style="background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--muted);padding:2px 8px;border-radius:5px;font-size:.66rem;font-weight:600">2026-04-25</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="platform-copy">
        <span class="eyebrow">03 · Conversaciones</span>
        <h3 style="font-size:1.4rem">Cada conversación guardada y etiquetada</h3>
        <p>Historial completo de cada chat con la IA. Etiquetas automáticas de intención (consulta, agenda, recomendación, queja). Filtros por fecha, dominio y estado.</p>
        <ul class="bullet-list">
          <li>Mensajes diferenciados por rol (usuario · IA · sistema)</li>
          <li>Etiquetas de intención generadas en tiempo real</li>
          <li>Búsqueda por contenido y filtros temporales</li>
          <li>Exportación a CSV para análisis externo</li>
        </ul>
      </div>
    </div>

    <!-- VISTA 4 — METRICAS -->
    <div class="platform-grid reveal" style="margin-top:64px">
      <div class="platform-copy">
        <span class="eyebrow">04 · Métricas</span>
        <h3 style="font-size:1.4rem">KPIs reales. No vanity metrics.</h3>
        <p>Conversaciones, mensajes, intenciones, citas próximas, archivadas e historial. Resumen operativo automático para saber si la IA está moviendo negocio.</p>
        <ul class="bullet-list">
          <li>Conversaciones IA y mensajes procesados</li>
          <li>Citas activas, próximas y completadas</li>
          <li>Intenciones detectadas (diagnóstico, recomendación, agenda)</li>
          <li>Tasa de deflection (consultas resueltas sin humano)</li>
        </ul>
      </div>
      <div class="platform-visual">
        <div class="platform-screen">
          <div class="pscreen-bar">
            <div class="pscreen-dot" style="background:#ff5f57"></div>
            <div class="pscreen-dot" style="background:#febc2e"></div>
            <div class="pscreen-dot" style="background:#28c840"></div>
            <div class="pscreen-url">app.vantelia.es/portal#metricas</div>
          </div>
          <div class="pscreen-body">
            <div class="pscreen-head">
              <div class="pscreen-title">Dashboard de métricas</div>
              <div class="pscreen-badge">● 30 días</div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px"><div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Conversaciones</div><div style="font-family:var(--font-d);font-size:1.4rem;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">247</div></div>
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px"><div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Mensajes</div><div style="font-family:var(--font-d);font-size:1.4rem;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">1.8K</div></div>
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px"><div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Citas mes</div><div style="font-family:var(--font-d);font-size:1.4rem;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">38</div></div>
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px"><div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Intenciones</div><div style="font-family:var(--font-d);font-size:1.4rem;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">12</div></div>
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px"><div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Deflection</div><div style="font-family:var(--font-d);font-size:1.4rem;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">76%</div></div>
              <div style="background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:10px;padding:10px"><div style="font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Satisfacción</div><div style="font-family:var(--font-d);font-size:1.4rem;font-weight:700;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">94%</div></div>
            </div>
            <div style="background:rgba(0,209,255,.06);border:1px solid rgba(0,209,255,.20);border-radius:10px;padding:8px 11px;margin-top:6px">
              <div style="color:var(--primary);font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Resumen operativo</div>
              <div style="color:var(--text);font-size:.74rem;line-height:1.5">+18% conversaciones vs mes anterior. 76% resueltas sin humano. Intención dominante: agenda.</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Capacidades técnicas">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Capacidades técnicas</span>
      <h2>Infraestructura robusta. Operación simple.</h2>
    </div>
    <div class="content-grid-4">
      <article class="content-card reveal d1">
        <span class="c-tag">RAG</span>
        <h3>RAG por cliente</h3>
        <p>Índice vectorial propio entrenado con tu información. Respuestas precisas, no genéricas. Reindexación con un clic.</p>
      </article>
      <article class="content-card reveal d2">
        <span class="c-tag">Integraciones</span>
        <h3>Integraciones nativas</h3>
        <p>La Agenda de Vantelia, WhatsApp Cloud API, SMTP. Webhooks para CRM personalizables por cliente.</p>
      </article>
      <article class="content-card reveal d3">
        <span class="c-tag">Multi-tenant</span>
        <h3>Aislamiento por cliente</h3>
        <p>Cada empresa con base de datos, índice y configuración propios. Cero filtración entre tenants.</p>
      </article>
      <article class="content-card reveal d4">
        <span class="c-tag">Seguridad</span>
        <h3>RGPD + control de dominios</h3>
        <p>Allowed origins, sesiones con TTL, rate limiting, hash bcrypt, datos en infraestructura europea.</p>
      </article>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Alta express">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Alta express</span>
      <h2>De URL a IA operativa en menos de un día.</h2>
    </div>
    <div class="content-grid-3">
      <article class="content-card reveal d1">
        <span class="c-tag">01</span>
        <h3>Análisis automático</h3>
        <p>Procesamos tu web y documentación pública para construir el cerebro IA inicial sin formularios largos.</p>
      </article>
      <article class="content-card reveal d2">
        <span class="c-tag">02</span>
        <h3>Generación del índice RAG</h3>
        <p>Indexamos tu información en una base vectorial propia. Tu asistente sabe responder con precisión.</p>
      </article>
      <article class="content-card reveal d3">
        <span class="c-tag">03</span>
        <h3>Widget listo</h3>
        <p>Snippet JS embebible en cualquier web. Personalización de marca y tono. Operativo el mismo día.</p>
      </article>
    </div>
  </div>
</section>""",
    ],
    extra_schema=[
        {
            "@type": "SoftwareApplication",
            "name": "Plataforma Vantelia",
            "url": f"{BASE_URL}/plataforma/",
            "applicationCategory": "BusinessApplication",
            "operatingSystem": "Web",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
            "description": "Plataforma multi-tenant de IA conversacional con panel de administración, portal de cliente y configuración de asistentes.",
        }
    ],
)

# ── RESULTADOS ────────────────────────────────────────────
PAGES["resultados"] = page(
    slug="resultados",
    title="Resultados Reales de IA y Marketing B2B | Casos | Vantelia",
    description="Resultados medibles de Vantelia: +41% conversión, -35% tareas manuales, 24/7 atención. Casos reales de empresas B2B con IA y marketing digital conectados.",
    og_image="/assets/img/resumen.png",
    breadcrumbs=[("Inicio", BASE_URL + "/"), ("Resultados", BASE_URL + "/resultados/")],
    hero_eyebrow="Resultados reales",
    hero_h1="Números que hablan por sí solos.",
    hero_lead="No prometemos atajos. Construimos sistemas medibles donde IA, marketing y automatización avanzan juntos. Estos son los resultados que generamos para empresas B2B.",
    hero_cta_primary=("Solicitar auditoría", "/consultas/"),
    hero_cta_secondary=("Ver servicios", "/servicios/"),
    sections=[
        """<section class="section results-bg" aria-label="Métricas">
  <div class="shell">
    <div class="section-head centered reveal" style="margin-inline:auto;text-align:center">
      <span class="eyebrow">En números</span>
      <h2>Impacto medible desde el primer mes.</h2>
    </div>
    <div class="kpi-grid">
      <article class="kpi-card reveal d1">
        <div class="k-val">+41%</div>
        <div class="k-label">Mejora de conversión</div>
        <div class="k-desc">Incremento medio al integrar IA, oferta y seguimiento en un sistema coherente.</div>
      </article>
      <article class="kpi-card reveal d2">
        <div class="k-val">-35%</div>
        <div class="k-label">Reducción tareas manuales</div>
        <div class="k-desc">Tiempo recuperado al integrar CRM, automatizaciones y respuesta automática con IA.</div>
      </article>
      <article class="kpi-card reveal d3">
        <div class="k-val">24/7</div>
        <div class="k-label">Atención garantizada</div>
        <div class="k-desc">El asistente IA responde, cualifica y agenda sin intervención humana, a cualquier hora.</div>
      </article>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Por qué funciona">
  <div class="shell">
    <div class="value-grid">
      <div class="value-items reveal">
        <div class="section-head" style="margin-bottom:28px">
          <span class="eyebrow">Por qué funciona</span>
          <h2>Lo que nos hace distintos.</h2>
        </div>
        <div class="value-item">
          <div class="v-num">01</div>
          <div>
            <h3>IA propia, no genérica</h3>
            <p>Cada cliente tiene su propio cerebro IA entrenado con su información real. No un chatbot de plantilla.</p>
          </div>
        </div>
        <div class="value-item">
          <div class="v-num">02</div>
          <div>
            <h3>Sistema integral</h3>
            <p>IA, SEO, paid, automatización y analítica funcionan conectados, no como proyectos paralelos.</p>
          </div>
        </div>
        <div class="value-item">
          <div class="v-num">03</div>
          <div>
            <h3>Equipo senior que ejecuta</h3>
            <p>No delegamos en juniors ni subcontratamos. El equipo que diseña la estrategia es el que la implementa.</p>
          </div>
        </div>
        <div class="value-item">
          <div class="v-num">04</div>
          <div>
            <h3>ROI medible desde el primer mes</h3>
            <p>Priorizamos quick wins de conversión para que el proyecto no arranque a ciegas ni tarde meses en mostrar valor.</p>
          </div>
        </div>
      </div>
      <div class="value-visual reveal d2">
        <div class="stack-list">
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🧠</div><div class="si-body"><h4>RAG por cliente</h4><p>Retrieval-Augmented Generation con datos propios</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🔗</div><div class="si-body"><h4>Integraciones nativas</h4><p>La Agenda de Vantelia, WhatsApp, CRM</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">📊</div><div class="si-body"><h4>Analítica unificada</h4><p>Conversaciones, citas, leads y embudo en un panel</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🛡️</div><div class="si-body"><h4>Seguridad y privacidad</h4><p>Control de dominios, sesiones, rate limit y RGPD</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">⚡</div><div class="si-body"><h4>Alta express en horas</h4><p>De URL a asistente operativo en menos de un día</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🔄</div><div class="si-body"><h4>Mejora continua</h4><p>Revisión mensual, optimización y escalado</p></div><div class="si-check" aria-hidden="true">✓</div></div>
        </div>
      </div>
    </div>
  </div>
</section>""",
        """<section class="section testi-bg" aria-label="Testimonios de clientes">
  <div class="shell">
    <div class="section-head centered reveal" style="margin-inline:auto;text-align:center">
      <span class="eyebrow">Lo que dicen</span>
      <h2>Empresas que ya tienen el sistema funcionando.</h2>
    </div>
    <div class="testi-grid">
      <article class="testi-card reveal d1">
        <div class="testi-stars" aria-label="5 de 5 estrellas">★★★★★</div>
        <p class="testi-text">"El asistente IA ha cambiado completamente cómo cualificamos leads. Antes perdíamos tiempo en consultas que no convertían. Ahora la IA filtra, recomienda y agenda."</p>
        <div class="testi-author">
          <div class="t-av" style="background:linear-gradient(135deg,#00D1FF,#00F5D4)">AM</div>
          <div><div class="t-name">Ana Martínez</div><div class="t-role">Directora · Clínica Estética Plus</div></div>
        </div>
      </article>
      <article class="testi-card reveal d2">
        <div class="testi-stars" aria-label="5 de 5 estrellas">★★★★★</div>
        <p class="testi-text">"Implementamos el widget en nuestra web B2B y en 30 días teníamos datos reales de qué preguntaban nuestros prospectos. Eso solo ya valió el proyecto."</p>
        <div class="testi-author">
          <div class="t-av" style="background:linear-gradient(135deg,#8a63ff,#00D1FF)">CR</div>
          <div><div class="t-name">Carlos Ruiz</div><div class="t-role">CEO · Industrias Técnicas Iberia</div></div>
        </div>
      </article>
      <article class="testi-card reveal d3">
        <div class="testi-stars" aria-label="5 de 5 estrellas">★★★★★</div>
        <p class="testi-text">"El alta express fue increíble. En media jornada teníamos el cerebro IA configurado. Llevamos 3 meses y las consultas por email han caído un 60%."</p>
        <div class="testi-author">
          <div class="t-av" style="background:linear-gradient(135deg,#00F5D4,#48d596)">LG</div>
          <div><div class="t-name">Laura García</div><div class="t-role">Directora · Academia Formación Digital</div></div>
        </div>
      </article>
    </div>
  </div>
</section>""",
    ],
    extra_schema=[
        {
            "@type": "ItemList",
            "name": "Testimonios de clientes Vantelia",
            "itemListElement": [
                {"@type": "Review", "author": {"@type": "Person", "name": "Ana Martínez"}, "reviewRating": {"@type": "Rating", "ratingValue": "5"}, "reviewBody": "El asistente IA ha cambiado completamente cómo cualificamos leads."},
                {"@type": "Review", "author": {"@type": "Person", "name": "Carlos Ruiz"}, "reviewRating": {"@type": "Rating", "ratingValue": "5"}, "reviewBody": "Implementamos el widget en nuestra web B2B y en 30 días teníamos datos reales."},
                {"@type": "Review", "author": {"@type": "Person", "name": "Laura García"}, "reviewRating": {"@type": "Rating", "ratingValue": "5"}, "reviewBody": "El alta express fue increíble. Las consultas por email han caído un 60%."},
            ],
        }
    ],
)

# ── NOSOTROS ──────────────────────────────────────────────
PAGES["nosotros"] = page(
    slug="nosotros",
    title="Sobre Vantelia | Equipo, Misión y Enfoque B2B | Vantelia",
    description="Conoce a Vantelia: agencia B2B especializada en IA aplicada, marketing de conversión y automatización comercial. No solo recomendamos, ejecutamos.",
    og_image="/assets/img/resumen.png",
    breadcrumbs=[("Inicio", BASE_URL + "/"), ("Nosotros", BASE_URL + "/nosotros/")],
    hero_eyebrow="Sobre Vantelia",
    hero_h1="Tu sistema de crecimiento. No otra agencia más.",
    hero_lead="Nacemos de la convicción de que las empresas no necesitan más herramientas aisladas. Necesitan un sistema donde IA, marketing y ventas trabajen en una sola arquitectura coherente.",
    hero_cta_primary=("Hablar con el equipo", "/consultas/"),
    hero_cta_secondary=("Ver servicios", "/servicios/"),
    sections=[
        """<section class="section" aria-label="En números">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">En números</span>
      <h2>Resultados que generamos para nuestros clientes.</h2>
    </div>
    <div class="kpi-grid">
      <article class="kpi-card reveal d1">
        <div class="k-val">+41%</div>
        <div class="k-label">Mejora de conversión</div>
        <div class="k-desc">Al integrar IA, oferta y seguimiento en un sistema coherente.</div>
      </article>
      <article class="kpi-card reveal d2">
        <div class="k-val">-35%</div>
        <div class="k-label">Tareas manuales reducidas</div>
        <div class="k-desc">Con automatizaciones conectadas al CRM y respuesta automática IA.</div>
      </article>
      <article class="kpi-card reveal d3">
        <div class="k-val">25+</div>
        <div class="k-label">Empresas activas</div>
        <div class="k-desc">B2B, clínicas, academias y agencias confían en Vantelia.</div>
      </article>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Cómo pensamos">
  <div class="shell">
    <div class="value-grid">
      <div class="value-items reveal">
        <div class="section-head" style="margin-bottom:28px">
          <span class="eyebrow">Cómo pensamos</span>
          <h2>Estrategia que se convierte en ejecución real.</h2>
        </div>
        <div class="value-item"><div class="v-num">01</div><div><h3>IA con cerebro propio</h3><p>Cada cliente tiene su asistente IA entrenado con su información real, no plantillas.</p></div></div>
        <div class="value-item"><div class="v-num">02</div><div><h3>Métricas reales</h3><p>Medimos pipeline, conversión y oportunidades. Sin métricas de vanidad.</p></div></div>
        <div class="value-item"><div class="v-num">03</div><div><h3>Equipo que ejecuta</h3><p>El equipo que recomienda es el que implementa. Sin subcontratación.</p></div></div>
        <div class="value-item"><div class="v-num">04</div><div><h3>Sistema integral</h3><p>SEO, CRM, IA y analítica avanzando juntos en una arquitectura coherente.</p></div></div>
      </div>
      <div class="value-visual reveal d2">
        <div class="stack-list">
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🎯</div><div class="si-body"><h4>Foco B2B</h4><p>Especialistas en empresas de servicios y producto B2B</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">⚡</div><div class="si-body"><h4>Quick wins</h4><p>Resultados visibles desde el primer mes</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🤝</div><div class="si-body"><h4>Partner real</h4><p>Trabajamos contigo, no para ti</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🛠️</div><div class="si-body"><h4>Plataforma propia</h4><p>Tecnología desarrollada internamente</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🇪🇸</div><div class="si-body"><h4>Equipo en España</h4><p>Comunicación clara y huso horario alineado</p></div><div class="si-check" aria-hidden="true">✓</div></div>
          <div class="stack-item"><div class="si-ico" aria-hidden="true">🔒</div><div class="si-body"><h4>RGPD nativo</h4><p>Cumplimiento europeo desde el diseño</p></div><div class="si-check" aria-hidden="true">✓</div></div>
        </div>
      </div>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Para quién">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Por qué Vantelia</span>
      <h2>Especialmente útil para empresas con tracción y sistema fragmentado.</h2>
    </div>
    <div class="content-grid-4">
      <article class="content-card reveal d1"><h3>B2B alto valor</h3><p>Cuando hay varias etapas de decisión y el seguimiento comercial pesa tanto como la captación.</p></article>
      <article class="content-card reveal d2"><h3>Stack parcial</h3><p>Si ya existe CRM o automatizaciones pero falta coherencia entre formularios, mensajes y oportunidades.</p></article>
      <article class="content-card reveal d3"><h3>Inversión en marketing</h3><p>Y necesitan que el rendimiento deje de depender de campañas sueltas o intuiciones.</p></article>
      <article class="content-card reveal d4"><h3>IA con criterio</h3><p>No como adorno, sino como mejora operativa y comercial con impacto medible.</p></article>
    </div>
  </div>
</section>""",
    ],
    extra_schema=[
        {
            "@type": "AboutPage",
            "name": "Sobre Vantelia",
            "url": f"{BASE_URL}/nosotros/",
            "description": "Equipo, misión y enfoque de trabajo de Vantelia en proyectos de IA, marketing y automatización para empresas B2B.",
            "publisher": {"@id": f"{BASE_URL}/#org"},
        }
    ],
)

# ── FAQ ───────────────────────────────────────────────────
FAQ_ITEMS = [
    ("¿Qué incluye una auditoría inicial con Vantelia?", "Revisamos captación, conversión, automatización, contenidos, analítica y fricciones operativas. El resultado es una hoja de ruta con prioridades reales, no un informe genérico de recomendaciones."),
    ("¿El asistente IA funciona con cualquier tipo de web?", "Sí. Se instala con un simple snippet de JavaScript en cualquier plataforma (WordPress, Webflow, Shopify, HTML puro). El proceso de alta express analiza tu web y genera el cerebro IA en horas."),
    ("¿Cuánto tarda en verse valor en un proyecto?", "Para el asistente IA, normalmente en la primera semana. Para SEO y estrategia de contenidos, priorizamos quick wins desde las primeras fases. El crecimiento estructural llega en 3-6 meses."),
    ("¿Trabajáis solo IA o también marketing digital completo?", "Trabajamos ambas capas. La IA es una palanca muy potente, pero la conectamos con SEO, paid media, CRO, contenido, CRM y seguimiento comercial para que genere impacto real."),
    ("¿Podéis colaborar con equipos internos o agencias existentes?", "Sí. Podemos actuar como partner estratégico, capa de ejecución especializada o apoyo a equipos internos que necesitan acelerar una parte concreta del sistema."),
    ("¿Y si solo necesito el asistente IA o solo el SEO?", "Encaja perfectamente. Empezamos por una necesidad concreta y, si tiene sentido, escalamos hacia un sistema más completo. No hay mínimos artificiales ni paquetes forzados."),
    ("¿Cómo se entrena el asistente con la información de mi empresa?", "El proceso de alta express analiza tu web automáticamente y construye el cerebro IA con tu información real. Puedes añadir documentos adicionales y el asistente se actualiza sin intervención técnica."),
    ("¿El asistente IA puede gestionar reservas y citas?", "Sí. El asistente cualifica al usuario, consulta disponibilidad y agenda citas en la Agenda de Vantelia, con notificaciones automáticas para ambas partes."),
    ("¿Cumple con el RGPD y la normativa europea?", "Sí. Datos almacenados en infraestructura europea, control de dominios permitidos, gestión de sesiones y cumplimiento RGPD desde el diseño de la plataforma."),
    ("¿Qué presupuesto necesito para empezar?", "Depende de alcance y madurez del proyecto. La consulta inicial es gratuita y sirve para alinear expectativas, ámbito y plazos antes de cualquier propuesta económica."),
]

faq_html = '<div class="faq-list">\n'
for q, a in FAQ_ITEMS:
    faq_html += f"""  <div class="faq-item">
    <button class="faq-btn" aria-expanded="false">
      {q}
      <span class="faq-chev" aria-hidden="true">▾</span>
    </button>
    <div class="faq-ans"><div class="faq-ans-in">{a}</div></div>
  </div>
"""
faq_html += "</div>"

PAGES["faq"] = page(
    slug="faq",
    title="Preguntas Frecuentes sobre IA y Marketing B2B | Vantelia",
    description="Respuestas a las preguntas más frecuentes sobre los servicios de IA, asistentes inteligentes, marketing digital y automatización de Vantelia para empresas B2B.",
    og_image="/assets/img/resumen.png",
    breadcrumbs=[("Inicio", BASE_URL + "/"), ("FAQ", BASE_URL + "/faq/")],
    hero_eyebrow="FAQ · Preguntas frecuentes",
    hero_h1="Todo lo que necesitas saber antes de empezar.",
    hero_lead="Respuestas directas sobre cómo trabajamos, qué incluye cada servicio y qué puedes esperar de un proyecto de IA y marketing con Vantelia.",
    hero_cta_primary=("Hablar con el equipo", "/consultas/"),
    hero_cta_secondary=("Ver servicios", "/servicios/"),
    sections=[
        f"""<section class="section" aria-label="Preguntas frecuentes">
  <div class="shell">
    <div class="section-head centered reveal" style="margin-inline:auto;text-align:center">
      <span class="eyebrow">FAQ</span>
      <h2>Preguntas frecuentes.</h2>
      <p style="color:var(--muted);font-size:1.04rem;line-height:1.7;max-width:680px;margin:0 auto">Lo que más nos preguntan sobre IA aplicada, marketing B2B y automatización empresarial.</p>
    </div>
    {faq_html}
  </div>
</section>"""
    ],
    extra_schema=[
        {
            "@type": "FAQPage",
            "url": f"{BASE_URL}/faq/",
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in FAQ_ITEMS
            ],
        }
    ],
)

# ── CONSULTAS ─────────────────────────────────────────────
# /consultas/ NO se regenera desde aquí: tiene formulario propio editado a mano.
# Para evitar sobreescribir, dejamos la asignación pero no la guardamos.
_CONSULTAS_DISABLED = page(
    slug="consultas",
    title="Consulta Gratuita de IA y Marketing B2B | Vantelia",
    description="Solicita una consulta gratuita con Vantelia. Auditamos captación, conversión, automatización e IA en tu empresa B2B y te damos una hoja de ruta clara.",
    og_image="/assets/img/resumen.png",
    breadcrumbs=[("Inicio", BASE_URL + "/"), ("Consulta gratuita", BASE_URL + "/consultas/")],
    hero_eyebrow="Consulta gratuita",
    hero_h1="Auditamos tu sistema de captación, conversión e IA. Sin compromiso.",
    hero_lead="En 30 minutos revisamos tu web, embudo y operación. Te decimos qué priorizar y qué ignorar. Sin formularios infinitos ni propuestas genéricas.",
    hero_cta_primary=("Escribir a info@vantelia.es", "mailto:info@vantelia.es"),
    hero_cta_secondary=("Ver servicios", "/servicios/"),
    sections=[
        """<section class="section" aria-label="Qué obtienes">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Qué obtienes</span>
      <h2>Una conversación útil. Aunque no nos contrates.</h2>
    </div>
    <div class="content-grid-3">
      <article class="content-card reveal d1">
        <span class="c-tag">01</span>
        <h3>Diagnóstico real</h3>
        <p>Revisión de tu captación, conversión, automatización e IA aplicada con criterio profesional, no con plantilla.</p>
      </article>
      <article class="content-card reveal d2">
        <span class="c-tag">02</span>
        <h3>Hoja de ruta</h3>
        <p>Tres prioridades concretas para mover negocio en los próximos 90 días, ordenadas por impacto y esfuerzo.</p>
      </article>
      <article class="content-card reveal d3">
        <span class="c-tag">03</span>
        <h3>Sin compromiso</h3>
        <p>Si encaja, hablamos de cómo trabajar juntos. Si no, te quedas con la hoja de ruta. Tan simple como eso.</p>
      </article>
    </div>
  </div>
</section>""",
        """<section class="section" aria-label="Cómo es la sesión">
  <div class="shell">
    <div class="section-head reveal">
      <span class="eyebrow">Cómo funciona</span>
      <h2>30 minutos. Sin presentación corporativa.</h2>
    </div>
    <div class="process-grid">
      <article class="process-step reveal d1"><div class="p-num">01</div><h3>Escribes</h3><p>Mándanos un email a info@vantelia.es con la URL de tu web y una línea sobre tu situación.</p></article>
      <article class="process-step reveal d2"><div class="p-num">02</div><h3>Revisamos</h3><p>Antes de la llamada, analizamos tu web, embudo y presencia digital con foco en oportunidades reales.</p></article>
      <article class="process-step reveal d3"><div class="p-num">03</div><h3>Hablamos</h3><p>Videollamada de 30 minutos. Te explicamos qué vemos y qué priorizaríamos.</p></article>
      <article class="process-step reveal d4"><div class="p-num">04</div><h3>Resumen</h3><p>Te enviamos por escrito las prioridades y el roadmap para que lo puedas usar con o sin nosotros.</p></article>
    </div>
  </div>
</section>""",
    ],
    extra_schema=[
        {
            "@type": "ContactPage",
            "name": "Consulta gratuita Vantelia",
            "url": f"{BASE_URL}/consultas/",
            "description": "Página de contacto y solicitud de consulta gratuita con Vantelia.",
            "publisher": {"@id": f"{BASE_URL}/#org"},
        }
    ],
)


def main():
    for slug, html in PAGES.items():
        out_dir = SITE / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "index.html"
        out.write_text(html, encoding="utf-8")
        size_kb = out.stat().st_size / 1024
        print(f"  /{slug}/ -> {out.relative_to(SITE)}  ({size_kb:.1f} KB)")
    print(f"\n{len(PAGES)} pagina(s) generada(s).")


if __name__ == "__main__":
    main()
