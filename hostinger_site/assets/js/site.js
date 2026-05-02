(function () {
  const config = window.VANTELIA_CONFIG || {};
  const data = window.VANTELIA_DATA || {};

  function formatDate(isoDate) {
    const date = new Date(isoDate);
    return new Intl.DateTimeFormat("es-ES", {
      day: "numeric",
      month: "long",
      year: "numeric"
    }).format(date);
  }

  function getConfigValue(key, fallback) {
    return config[key] || fallback;
  }

  function getCurrentNavPage() {
    if (document.body.dataset.page === "post") {
      return "noticias";
    }
    return document.body.dataset.page || "";
  }

  function renderHeader() {
    const container = document.querySelector("[data-site-header]");
    if (!container) return;

    const currentPage = getCurrentNavPage();
    const navItems = (data.nav || [])
      .map((item) => {
        const isActive = item.page === currentPage ? " aria-current=\"page\"" : "";
        return `<a href="${item.href}"${isActive}>${item.label}</a>`;
      })
      .join("");

    container.innerHTML = `
      <header class="site-header">
        <div class="shell site-header__inner">
          <a class="brand" href="/" aria-label="Ir al inicio de Vantelia">
            <img src="/assets/img/logo-letra.png?v=hero-bg-desktop-20260501" alt="Vantelia">
          </a>
          <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">
            Menu
          </button>
          <div class="site-nav-wrap">
            <nav id="site-nav" class="site-nav">
              ${navItems}
            </nav>
            <div class="site-actions">
              <a class="site-link" href="${getConfigValue("clientPortalUrl", "#")}">Portal</a>
              <a class="button button--small" href="/consultas/">Solicitar auditoria</a>
            </div>
          </div>
        </div>
      </header>
    `;
  }

  function renderFooter() {
    const container = document.querySelector("[data-site-footer]");
    if (!container) return;

    const email = getConfigValue("contactEmail", "info@vantelia.es");
    const leadEmail = getConfigValue("leadEmail", email);
    const phone = getConfigValue("phone", "+34 912 345 678");

    container.innerHTML = `
      <footer class="site-footer">
        <div class="shell footer-grid">
          <div class="footer-col footer-col--brand">
            <img class="footer-logo" src="/assets/img/logo-letra.png?v=hero-bg-desktop-20260501" alt="Vantelia">
            <p>${data.tagLine || ""}</p>
          </div>
          <div class="footer-col">
            <p class="eyebrow">Servicios</p>
            <div class="footer-list">
              <span>SEO y contenido orientado a demanda</span>
              <span>Paid media y optimizacion de conversion</span>
              <span>Automatizacion comercial y agentes IA</span>
              <span>Analitica, reporting y direccion de crecimiento</span>
            </div>
          </div>
          <div class="footer-col">
            <p class="eyebrow">Explorar</p>
            <div class="footer-list">
              <a href="/servicios/">Servicios</a>
              <a href="/plataforma/">Plataforma</a>
              <a href="/resultados/">Resultados</a>
              <a href="/nosotros/">Nosotros</a>
              <a href="/faq/">FAQ</a>
              <a href="/consultas/">Consulta gratuita</a>
            </div>
          </div>
          <div class="footer-col">
            <p class="eyebrow">Contacto</p>
            <div class="footer-list">
              <a href="mailto:${leadEmail}">${leadEmail}</a>
              <a href="mailto:${email}">${email}</a>
              <a href="tel:${phone.replace(/\s+/g, "")}">${phone}</a>
              <a href="${getConfigValue("clientPortalUrl", "#")}">Acceso clientes</a>
            </div>
          </div>
        </div>
        <div class="shell footer-bottom">
          <span>&copy; <span data-current-year></span> Vantelia. Marketing, automatizacion e inteligencia artificial.</span>
        </div>
      </footer>
    `;
  }

  function wireNavigation() {
    const toggle = document.querySelector(".nav-toggle");
    const navWrap = document.querySelector(".site-nav-wrap");
    if (!toggle || !navWrap) return;

    toggle.addEventListener("click", function () {
      const isOpen = navWrap.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  function renderPosts() {
    document.querySelectorAll("[data-post-grid]").forEach((container) => {
      const mode = container.dataset.postGrid || "all";
      const posts = mode === "featured" ? (data.posts || []).slice(0, 2) : data.posts || [];
      container.innerHTML = posts
        .map(
          (post) => `
            <article class="post-card">
              <p class="eyebrow">${post.category}</p>
              <h3><a href="${post.slug}">${post.title}</a></h3>
              <p>${post.excerpt}</p>
              <div class="post-card__meta">
                <span>${formatDate(post.date)}</span>
                <span>${post.readingTime}</span>
              </div>
              <a class="post-card__cta" href="${post.slug}">Leer insight</a>
            </article>
          `
        )
        .join("");
    });
  }

  function renderFaqs() {
    document.querySelectorAll("[data-faqs]").forEach((container) => {
      container.innerHTML = `
        <div class="faq-list">
          ${(data.faqs || [])
            .map(
              (faq) => `
                <details class="faq">
                  <summary>${faq.question}</summary>
                  <p>${faq.answer}</p>
                </details>
              `
            )
            .join("")}
        </div>
      `;
    });
  }

  function renderCurrentYear() {
    document.querySelectorAll("[data-current-year]").forEach((node) => {
      node.textContent = String(new Date().getFullYear());
    });
  }

  function showFormMessage(form, message, isError) {
    let box = form.querySelector(".form-message");
    if (!box) {
      box = document.createElement("p");
      box.className = "form-message";
      form.appendChild(box);
    }
    box.textContent = message;
    box.dataset.state = isError ? "error" : "success";
  }

  function handleContactSubmit(form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const formData = new FormData(form);
      const name = String(formData.get("name") || "").trim();
      const email = String(formData.get("email") || "").trim();
      const message = String(formData.get("message") || "").trim();

      if (!name || !email || !message) {
        showFormMessage(form, "Completa nombre, correo y mensaje para enviar la consulta.", true);
        return;
      }

      const endpoint = getConfigValue("contactFormEndpoint", "");
      if (endpoint) {
        try {
          const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, email, message, source: "website" })
          });
          if (!response.ok) throw new Error("request_failed");
          form.reset();
          showFormMessage(form, "Consulta enviada. Te responderemos pronto.", false);
          return;
        } catch (error) {
          showFormMessage(form, "No se pudo enviar al endpoint configurado. Se abrira tu cliente de correo.", true);
        }
      }

      const targetEmail = getConfigValue("leadEmail", getConfigValue("contactEmail", "info@vantelia.es"));
      const subject = encodeURIComponent("Solicitud de auditoria desde Vantelia");
      const body = encodeURIComponent(`Nombre: ${name}\nCorreo: ${email}\n\nContexto:\n${message}`);
      window.location.href = `mailto:${targetEmail}?subject=${subject}&body=${body}`;
      showFormMessage(form, "Hemos preparado el correo para que puedas enviarlo desde tu dispositivo.", false);
    });
  }

  function handleNewsletterSubmit(form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const formData = new FormData(form);
      const email = String(formData.get("email") || "").trim();

      if (!email) {
        showFormMessage(form, "Introduce tu correo para suscribirte.", true);
        return;
      }

      const endpoint = getConfigValue("newsletterFormEndpoint", "");
      if (endpoint) {
        try {
          const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, source: "newsletter" })
          });
          if (!response.ok) throw new Error("request_failed");
          form.reset();
          showFormMessage(form, "Suscripcion recibida.", false);
          return;
        } catch (error) {
          showFormMessage(form, "No se pudo enviar al endpoint configurado.", true);
          return;
        }
      }

      const targetEmail = getConfigValue("contactEmail", "info@vantelia.es");
      const subject = encodeURIComponent("Alta newsletter Vantelia");
      const body = encodeURIComponent(`Quiero suscribirme con este correo: ${email}`);
      window.location.href = `mailto:${targetEmail}?subject=${subject}&body=${body}`;
      showFormMessage(form, "Hemos preparado un correo para completar la suscripcion.", false);
    });
  }

  function wireForms() {
    document.querySelectorAll("form[data-form-type='contact']").forEach(handleContactSubmit);
    document.querySelectorAll("form[data-form-type='newsletter']").forEach(handleNewsletterSubmit);
  }

  function init() {
    renderHeader();
    renderFooter();
    renderPosts();
    renderFaqs();
    renderCurrentYear();
    wireNavigation();
    wireForms();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
