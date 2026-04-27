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

  function renderHeader() {
    const container = document.querySelector("[data-site-header]");
    if (!container) return;

    const currentPage = document.body.dataset.page;
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
            <img src="/assets/img/logo-letra.png" alt="Vantelia">
          </a>
          <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">
            Menu
          </button>
          <nav id="site-nav" class="site-nav">
            ${navItems}
            <a class="button button--ghost button--small" href="${getConfigValue("clientPortalUrl", "#")}">Acceso clientes</a>
          </nav>
        </div>
      </header>
    `;
  }

  function renderFooter() {
    const container = document.querySelector("[data-site-footer]");
    if (!container) return;

    const email = getConfigValue("contactEmail", "hola@vantelia.com");
    const phone = getConfigValue("phone", "+34 912 345 678");

    container.innerHTML = `
      <footer class="site-footer">
        <div class="shell footer-grid">
          <div class="footer-card footer-card--brand">
            <img class="footer-logo" src="/assets/img/logo-letra.png" alt="Vantelia">
            <p>${data.tagLine || ""}</p>
          </div>
          <div class="footer-card">
            <p class="eyebrow">Contacto</p>
            <a href="mailto:${email}">${email}</a>
            <a href="tel:${phone.replace(/\s+/g, "")}">${phone}</a>
          </div>
          <div class="footer-card">
            <p class="eyebrow">Accesos</p>
            <a href="/consultas/">Consulta gratuita</a>
            <a href="${getConfigValue("clientPortalUrl", "#")}">Portal de clientes</a>
          </div>
        </div>
        <div class="shell footer-bottom">
          <span>(c) <span data-current-year></span> Vantelia. All rights reserved.</span>
        </div>
      </footer>
    `;
  }

  function wireNavigation() {
    const toggle = document.querySelector(".nav-toggle");
    const nav = document.querySelector(".site-nav");
    if (!toggle || !nav) return;

    toggle.addEventListener("click", function () {
      const isOpen = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  function renderServiceGrids() {
    document.querySelectorAll("[data-service-grid]").forEach((container) => {
      container.innerHTML = (data.serviceCards || [])
        .map(
          (service, index) => `
            <article class="card">
              <span class="card-index">0${index + 1}</span>
              <h3>${service.title}</h3>
              <p>${service.text}</p>
            </article>
          `
        )
        .join("");
    });
  }

  function renderWorkflow() {
    document.querySelectorAll("[data-workflow]").forEach((container) => {
      container.innerHTML = (data.workflow || [])
        .map(
          (step, index) => `
            <li class="timeline__item">
              <span class="timeline__step">0${index + 1}</span>
              <p>${step}</p>
            </li>
          `
        )
        .join("");
    });
  }

  function renderTrust() {
    document.querySelectorAll("[data-trust-grid]").forEach((container) => {
      container.innerHTML = (data.trustHighlights || [])
        .map(
          (item) => `
            <article class="card card--soft">
              <h3>${item.title}</h3>
              <p>${item.text}</p>
            </article>
          `
        )
        .join("");
    });
  }

  function renderStats() {
    document.querySelectorAll("[data-stat-grid]").forEach((container) => {
      container.innerHTML = (data.stats || [])
        .map(
          (item) => `
            <article class="stat">
              <strong>${item.value}</strong>
              <span>${item.label}</span>
            </article>
          `
        )
        .join("");
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
            </article>
          `
        )
        .join("");
    });
  }

  function renderFaqs() {
    document.querySelectorAll("[data-faqs]").forEach((container) => {
      container.innerHTML = (data.faqs || [])
        .map(
          (faq) => `
            <details class="faq">
              <summary>${faq.question}</summary>
              <p>${faq.answer}</p>
            </details>
          `
        )
        .join("");
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

      const targetEmail = getConfigValue("leadEmail", getConfigValue("contactEmail", "hola@vantelia.com"));
      const subject = encodeURIComponent("Consulta desde la web de Vantelia");
      const body = encodeURIComponent(`Nombre: ${name}\nCorreo: ${email}\n\nMensaje:\n${message}`);
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

      const targetEmail = getConfigValue("contactEmail", "hola@vantelia.com");
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
    renderServiceGrids();
    renderWorkflow();
    renderTrust();
    renderStats();
    renderPosts();
    renderFaqs();
    renderCurrentYear();
    wireNavigation();
    wireForms();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
