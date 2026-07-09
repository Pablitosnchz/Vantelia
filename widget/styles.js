function hexToRgb(hex) {
  const normalized = String(hex || "").replace("#", "").trim();
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) {
    return { r: 31, g: 111, b: 235 };
  }

  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  };
}

function darken(hex, factor = 0.18) {
  const { r, g, b } = hexToRgb(hex);
  const next = (value) => Math.max(0, Math.round(value * (1 - factor)));
  return `rgb(${next(r)}, ${next(g)}, ${next(b)})`;
}

function alpha(hex, opacity = 0.12) {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function normalizeHexColor(value) {
  const normalized = String(value || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(normalized) ? normalized : "";
}

export function inyectarEstilos(color, accentColor) {
  document.getElementById("ia-w-style")?.remove();

  const baseColor = normalizeHexColor(color) || "#1F6FEB";
  const accent = normalizeHexColor(accentColor);
  const colorDark = accent || darken(baseColor, 0.2);
  const colorSoft = alpha(baseColor, 0.12);
  const colorSoftStrong = alpha(baseColor, 0.2);

  const css = document.createElement("style");
  css.id = "ia-w-style";
  css.textContent = `
    :root {
      --ia-color: ${baseColor};
      --ia-color-dark: ${colorDark};
      --ia-color-soft: ${colorSoft};
      --ia-color-soft-strong: ${colorSoftStrong};
      --ia-surface: #ffffff;
      --ia-surface-muted: #f4f7fb;
      --ia-text: #0e1c2e;
      --ia-text-soft: #5a6b7e;
      --ia-border: #dce5ef;
      --ia-shadow: 0 28px 64px rgba(8, 18, 38, 0.20), 0 2px 8px rgba(8, 18, 38, 0.10);
      --ia-radius-xl: 22px;
      --ia-radius-lg: 16px;
      --ia-font: "Inter", "Segoe UI", system-ui, sans-serif;
    }

    #ia-w-container,
    #ia-w-container * {
      box-sizing: border-box;
      font-family: var(--ia-font);
    }

    #ia-w-container .hidden {
      display: none !important;
    }

    #ia-w-container {
      position: fixed;
      right: 24px;
      bottom: 24px;
      z-index: 2147483000;
      color: var(--ia-text);
    }

    #ia-w-container.ia-left,
    #ia-w-container.ia-left #ia-w-chat,
    #ia-w-container.ia-left #ia-w-badge,
    #ia-w-container.ia-left #ia-w-btn {
      right: auto;
      left: 24px;
    }

    #ia-w-btn {
      position: fixed;
      right: 24px;
      bottom: 24px;
      width: 60px;
      height: 60px;
      border: 0;
      border-radius: 999px;
      background:
        radial-gradient(circle at 28% 28%, rgba(255, 255, 255, 0.28), transparent 42%),
        linear-gradient(135deg, var(--ia-color), var(--ia-color-dark));
      color: #fff;
      cursor: pointer;
      box-shadow: 0 10px 32px rgba(11, 24, 49, 0.22), 0 0 0 1px rgba(255,255,255,0.06);
      transition: transform 0.20s ease, box-shadow 0.20s ease, filter 0.20s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }

    #ia-w-btn svg,
    #ia-w-close svg {
      width: 24px;
      height: 24px;
      fill: currentColor;
    }

    #ia-w-btn .ia-launcher-img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      border-radius: 999px;
      display: block;
    }

    #ia-w-btn.ia-launcher-circle:has(.ia-launcher-img) {
      background: #fff;
      padding: 0;
      overflow: hidden;
    }

    #ia-w-btn.ia-launcher-bar {
      gap: 10px;
      font-weight: 700;
      font-size: 14.5px;
      letter-spacing: 0.01em;
      color: #fff;
    }
    #ia-w-btn.ia-launcher-bar svg {
      width: 20px;
      height: 20px;
      flex: 0 0 auto;
    }
    #ia-w-btn.ia-launcher-bar .ia-launcher-img {
      width: 28px;
      height: 28px;
      border-radius: 999px;
      flex: 0 0 auto;
    }
    #ia-w-btn.ia-launcher-bar .ia-launcher-label {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    #ia-w-btn.ia-launcher-bar.abierto {
      transform: rotate(0deg);
    }

    #ia-w-btn:hover {
      transform: translateY(-2px) scale(1.04);
      box-shadow: 0 16px 40px rgba(11, 24, 49, 0.30), 0 0 0 1px rgba(255,255,255,0.10);
      filter: brightness(1.08);
    }

    #ia-w-btn.abierto {
      transform: rotate(90deg);
    }

    #ia-w-badge {
      position: fixed;
      right: 24px;
      bottom: 100px;
      max-width: 280px;
      background: rgba(255, 255, 255, 0.96);
      color: var(--ia-text);
      padding: 13px 15px;
      border-radius: 18px 18px 6px 18px;
      border: 1px solid rgba(20, 34, 53, 0.08);
      box-shadow: 0 14px 30px rgba(9, 20, 40, 0.12);
      backdrop-filter: blur(16px);
      font-size: 14px;
      line-height: 1.45;
      cursor: pointer;
      animation: ia-fade-in 0.25s ease;
    }

    #ia-w-chat {
      position: fixed;
      right: 24px;
      bottom: 100px;
      /* Blindaje: la web anfitriona puede estilizar <section>/<header> genericos
         (padding enorme, min-height 90vh...); estas propiedades se fijan aqui para
         que el panel no herede nada raro. */
      padding: 0;
      margin: 0;
      min-height: 0;
      max-height: none;
      width: min(392px, calc(100vw - 36px));
      height: min(760px, calc(100vh - 112px));
      background: var(--ia-surface);
      border: 1px solid rgba(20, 34, 53, 0.08);
      border-radius: var(--ia-radius-xl);
      box-shadow: var(--ia-shadow);
      overflow: hidden;
      display: none;
      flex-direction: column;
      animation: ia-fade-in 0.2s ease;
    }

    #ia-w-chat.visible {
      display: flex;
    }

    #ia-w-header {
      position: static;
      min-height: 0;
      margin: 0;
      flex: 0 0 auto;
      background:
        radial-gradient(circle at top right, rgba(255, 255, 255, 0.16), transparent 28%),
        linear-gradient(135deg, var(--ia-color-dark), var(--ia-color));
      color: #fff;
      padding: 16px 16px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    #ia-w-header-info {
      display: flex;
      gap: 12px;
      align-items: center;
      min-width: 0;
    }

    #ia-w-header-info p {
      margin: 0;
    }

    #ia-w-header-info p:first-child {
      font-size: 15px;
      font-weight: 800;
    }

    #ia-w-header-info p:last-child {
      font-size: 12px;
      opacity: 0.86;
    }

    .ia-avatar {
      width: 42px;
      height: 42px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: rgba(255, 255, 255, 0.16);
      border: 1px solid rgba(255, 255, 255, 0.18);
      font-size: 17px;
      font-weight: 700;
      letter-spacing: 0.02em;
      flex-shrink: 0;
    }
    .ia-avatar-img {
      width: 42px;
      height: 42px;
      object-fit: contain;
      flex-shrink: 0;
    }

    #ia-w-close {
      width: 34px;
      height: 34px;
      border: 0;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.14);
      color: #fff;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
    }

    #ia-w-header-actions { display: inline-flex; align-items: center; gap: 8px; }
    .ia-w-icon-btn {
      width: 34px; height: 34px; border: 0; border-radius: 999px;
      background: rgba(255, 255, 255, 0.14); color: #fff; cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center; padding: 0;
    }
    .ia-w-icon-btn:hover { background: rgba(255, 255, 255, 0.26); }
    .ia-w-icon-btn svg { width: 18px; height: 18px; }

    /* La llamada de voz ocupa el propio panel del chat (no toda la pantalla) */
    .ia-v-overlay {
      position: absolute; inset: 0; z-index: 6;
      display: flex; align-items: center; justify-content: center; padding: 22px;
      background: linear-gradient(180deg, #14213d, #0b1220);
      color: #fff; border-radius: inherit;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      animation: ia-fade-in 0.18s ease;
    }
    .ia-v-card {
      width: 100%; max-width: 320px; text-align: center;
      background: transparent; box-shadow: none; padding: 0;
    }
    .ia-v-avatar {
      width: 96px; height: 96px; margin: 0 auto 16px; border-radius: 999px;
      display: flex; align-items: center; justify-content: center;
      font-size: 2rem; font-weight: 700; color: #04121a;
      background: linear-gradient(135deg, ${color}, #00f5d4); position: relative;
    }
    .ia-v-avatar::after {
      content: ""; position: absolute; inset: -8px; border-radius: 999px;
      border: 2px solid ${alpha(color, 0.5)}; opacity: 0; transform: scale(0.9);
    }
    .ia-v-avatar.speaking::after { animation: iaVPulse 1.1s ease-out infinite; }
    @keyframes iaVPulse { 0% { opacity: 0.8; transform: scale(0.92); } 100% { opacity: 0; transform: scale(1.28); } }
    .ia-v-name { font-weight: 700; font-size: 1.25rem; }
    .ia-v-status { margin-top: 6px; color: rgba(255, 255, 255, 0.68); font-size: 0.95rem; min-height: 20px; }
    .ia-v-timer { margin-top: 12px; font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: 0.04em; }
    .ia-v-hint { margin-top: 14px; color: rgba(255, 255, 255, 0.5); font-size: 0.84rem; line-height: 1.5; }
    .ia-v-actions { display: flex; gap: 12px; justify-content: center; margin-top: 22px; }
    .ia-v-btn {
      appearance: none; cursor: pointer; font: inherit; font-weight: 600; font-size: 0.92rem;
      border: 1px solid rgba(255, 255, 255, 0.16); color: #fff; background: rgba(255, 255, 255, 0.08);
      padding: 12px 18px; border-radius: 999px;
    }
    .ia-v-btn:hover { background: rgba(255, 255, 255, 0.16); }
    .ia-v-btn.ia-v-hang { background: #ef4444; border-color: #ef4444; }
    .ia-v-btn.ia-v-hang:hover { background: #dc2626; }
    @media (prefers-reduced-motion: reduce) { .ia-v-avatar.speaking::after { animation: none; } }

    #ia-w-msgs {
      flex: 1;
      padding: 14px;
      background:
        radial-gradient(circle at top left, ${colorSoft}, transparent 36%),
        linear-gradient(180deg, #f9fbfe, #f4f7fb 38%, #f9fbfe);
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scroll-padding-bottom: 20px;
    }

    #ia-w-msgs::-webkit-scrollbar {
      width: 7px;
    }

    #ia-w-msgs::-webkit-scrollbar-thumb {
      background: rgba(20, 34, 53, 0.16);
      border-radius: 999px;
    }

    .ia-msg {
      max-width: 88%;
      padding: 11px 13px;
      border-radius: 18px;
      line-height: 1.48;
      font-size: 13px;
      word-break: break-word;
      animation: ia-fade-in 0.18s ease;
    }

    .ia-msg p {
      margin: 0;
    }

    .ia-msg p + p {
      margin-top: 12px;
    }

    .ia-msg.bot {
      align-self: flex-start;
      background: rgba(255, 255, 255, 0.94);
      border: 1px solid rgba(20, 34, 53, 0.08);
      border-bottom-left-radius: 6px;
      box-shadow: 0 6px 18px rgba(9, 20, 40, 0.06);
    }

    .ia-msg.user {
      align-self: flex-end;
      background: linear-gradient(135deg, var(--ia-color), var(--ia-color-dark));
      color: #fff;
      border-bottom-right-radius: 6px;
    }

    .ia-msg.typing {
      align-self: flex-start;
      background: #fff;
      border: 1px solid rgba(20, 34, 53, 0.08);
      border-bottom-left-radius: 6px;
    }

    .ia-rich-list {
      margin: 2px 0 0;
      padding-left: 0;
      list-style: none;
    }

    .ia-rich-list li {
      position: relative;
      padding-left: 15px;
    }

    .ia-rich-list li::before {
      content: "";
      position: absolute;
      left: 1px;
      top: 0.72em;
      width: 5px;
      height: 5px;
      border-radius: 999px;
      background: var(--ia-color);
      opacity: 0.72;
    }

    .ia-rich-list li + li {
      margin-top: 9px;
    }

    .ia-rich-list .ia-list-heading {
      margin-top: 14px;
      padding-left: 0;
      padding-top: 10px;
      border-top: 1px solid rgba(20, 34, 53, 0.08);
      color: var(--ia-text);
      font-weight: 700;
    }

    .ia-rich-list .ia-list-heading::before {
      display: none;
    }

    .ia-rich-list .ia-list-heading:first-child {
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }

    .ia-dots {
      display: flex;
      gap: 5px;
      align-items: center;
      min-height: 12px;
    }

    .ia-dots span {
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--ia-color);
      opacity: 0.55;
      animation: ia-dot-pulse 1.1s infinite ease-in-out;
    }

    .ia-dots span:nth-child(2) {
      animation-delay: 0.18s;
    }

    .ia-dots span:nth-child(3) {
      animation-delay: 0.36s;
    }

    .ia-action-card {
      max-width: 96%;
    }

    .ia-action-card p {
      color: var(--ia-text);
    }

    .ia-action-card p + .ia-action-grid {
      margin-top: 10px;
    }

    .ia-action-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      width: 100%;
    }

    .ia-action-grid button {
      min-width: 0;
      border: 1px solid var(--ia-border);
      border-radius: 12px;
      background: #fbfcfe;
      color: var(--ia-text);
      cursor: pointer;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.25;
      padding: 10px 11px;
      text-align: left;
      transition: border-color 0.16s ease, background 0.16s ease, transform 0.16s ease;
    }

    .ia-action-grid button:hover {
      border-color: var(--ia-color);
      background: var(--ia-color-soft);
      transform: translateY(-1px);
    }

    #ia-w-input-area {
      display: flex;
      gap: 10px;
      align-items: center;
      padding: 12px 14px;
      border-top: 1px solid rgba(20, 34, 53, 0.08);
      background: rgba(255, 255, 255, 0.96);
    }

    #ia-w-input {
      flex: 1;
      min-width: 0;
      border: 1px solid var(--ia-border);
      background: #fbfcfe;
      border-radius: 999px;
      padding: 11px 14px;
      font-size: 13px;
      color: var(--ia-text);
      outline: none;
      transition: border-color 0.16s ease, box-shadow 0.16s ease;
    }

    #ia-w-input:focus,
    .ia-form-card input:focus,
    .ia-form-card select:focus,
    .ia-form-card textarea:focus {
      border-color: var(--ia-color);
      box-shadow: 0 0 0 4px ${colorSoftStrong};
    }

    #ia-w-send {
      min-width: 82px;
      height: 40px;
      border: 0;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--ia-color), var(--ia-color-dark));
      color: #fff;
      font-family: var(--ia-font);
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      padding: 0 16px;
      transition: transform 0.16s ease, filter 0.16s ease, box-shadow 0.16s ease;
      box-shadow: 0 4px 16px rgba(11, 24, 49, 0.18);
    }

    #ia-w-send:not(:disabled):hover {
      transform: translateY(-1px);
      filter: brightness(1.08);
      box-shadow: 0 8px 22px rgba(11, 24, 49, 0.24);
    }

    #ia-w-send:disabled {
      opacity: 0.50;
      cursor: not-allowed;
    }

    .ia-form-card {
      width: 100%;
      align-self: stretch;
      background: #fff;
      border: 1px solid rgba(20, 34, 53, 0.08);
      border-radius: var(--ia-radius-lg);
      overflow: hidden;
      box-shadow: 0 10px 28px rgba(9, 20, 40, 0.08);
      min-height: min(500px, calc(100vh - 260px));
      max-height: 100%;
      display: flex;
      flex-direction: column;
    }

    .ia-form-header {
      padding: 14px 16px 12px;
      background:
        radial-gradient(circle at top right, rgba(255, 255, 255, 0.15), transparent 28%),
        linear-gradient(135deg, var(--ia-color), var(--ia-color-dark));
      color: #fff;
      text-align: center;
    }

    .ia-form-header h4 {
      margin: 0 0 4px;
      font-size: 15px;
      font-weight: 800;
    }

    .ia-form-header p {
      margin: 0;
      font-size: 11px;
      opacity: 0.9;
    }

    .ia-form-progress {
      display: flex;
      justify-content: center;
      gap: 8px;
      padding: 10px 16px 0;
    }

    .ia-form-step-dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: #dbe3ef;
      transition: transform 0.18s ease, background 0.18s ease;
    }

    .ia-form-step-dot.active {
      background: var(--ia-color);
      transform: scale(1.25);
    }

    .ia-form-step-dot.done {
      background: #18a957;
    }

    .ia-form-body {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      padding: 16px;
      overflow-y: auto;
      overscroll-behavior: contain;
    }

    .ia-form-step {
      display: none;
      flex-direction: column;
      gap: 9px;
      min-height: 100%;
      min-width: 0;
    }

    .ia-form-step.active {
      display: flex;
      flex: 1;
      min-height: 0;
    }

    .ia-form-label {
      font-size: 12px;
      font-weight: 800;
      color: var(--ia-text);
      margin-top: 2px;
    }

    .ia-form-card input,
    .ia-form-card select,
    .ia-form-card textarea {
      width: 100%;
      border: 1px solid var(--ia-border);
      border-radius: 14px;
      background: #fbfcfe;
      color: var(--ia-text);
      color-scheme: light;
      padding: 11px 13px;
      outline: none;
      font-size: 13px;
      transition: border-color 0.16s ease, box-shadow 0.16s ease;
    }

    .ia-form-card input::placeholder,
    .ia-form-card textarea::placeholder {
      color: var(--ia-text-soft);
      opacity: 0.72;
    }

    .ia-form-card select option {
      color: var(--ia-text);
      background: #fff;
    }

    .ia-form-card textarea {
      resize: vertical;
      min-height: 86px;
    }

    .ia-invalid {
      border-color: #b42318 !important;
    }

    .ia-field-error {
      color: #b42318;
      font-size: 12px;
      margin-top: -4px;
      margin-bottom: 2px;
    }

    .ia-form-note {
      margin: 2px 0 0;
      font-size: 12px;
      color: var(--ia-text-soft);
      line-height: 1.45;
    }

    .ia-time-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 2px;
    }

    .ia-time-slot {
      border: 1px solid var(--ia-border);
      border-radius: 14px;
      background: #fbfcfe;
      color: var(--ia-text);
      padding: 11px 8px;
      font-size: 12px;
      font-weight: 800;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.16s ease, background 0.16s ease, transform 0.16s ease;
    }

    .ia-time-slot:hover {
      border-color: var(--ia-color);
      background: var(--ia-color-soft);
      transform: translateY(-1px);
    }

    .ia-time-slot.selected {
      color: #fff;
      border-color: var(--ia-color-dark);
      background: linear-gradient(135deg, var(--ia-color), var(--ia-color-dark));
    }

    .ia-time-slot.disabled,
    .ia-time-slot.disabled:hover {
      opacity: 0.45;
      color: var(--ia-text-soft);
      cursor: not-allowed;
      background: #eef2f7;
      border-color: #dbe3ef;
      transform: none;
    }

    .ia-time-slot small {
      display: block;
      margin-top: 4px;
      font-size: 11px;
      color: inherit;
      font-weight: 700;
    }

    .ia-form-actions {
      display: flex;
      gap: 10px;
      margin-top: auto;
      padding-top: 12px;
      position: sticky;
      bottom: 0;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0), #fff 34%);
      padding-bottom: 2px;
    }

    .ia-form-btn {
      flex: 1;
      border: 0;
      border-radius: 14px;
      padding: 12px 14px;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
    }

    .ia-form-btn.primary {
      color: #fff;
      background: linear-gradient(135deg, var(--ia-color), var(--ia-color-dark));
    }

    .ia-form-btn.secondary {
      color: var(--ia-text);
      background: #eef2f7;
    }

    .ia-form-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .ia-loading-slots,
    .ia-empty-slots,
    .ia-slot-error {
      padding: 18px 0 6px;
      font-size: 13px;
      text-align: center;
      color: var(--ia-text-soft);
    }

    .ia-slot-error {
      color: #b42318;
    }

    .ia-spinner {
      width: 18px;
      height: 18px;
      border: 2px solid rgba(20, 34, 53, 0.14);
      border-top-color: var(--ia-color);
      border-radius: 999px;
      display: inline-block;
      animation: ia-spin 0.8s linear infinite;
    }

    .ia-resumen {
      border: 1px solid rgba(20, 34, 53, 0.08);
      border-radius: 16px;
      background: #f8fbff;
      padding: 14px;
      display: grid;
      gap: 10px;
    }

    .ia-resumen-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
    }

    .ia-resumen-row span:first-child {
      color: var(--ia-text-soft);
    }

    .ia-resumen-row span:last-child {
      color: var(--ia-text);
      font-weight: 800;
      text-align: right;
    }

    .ia-form-success {
      text-align: center;
      padding: 20px 18px;
    }

    .ia-form-error {
      border: 1px solid rgba(255, 93, 143, 0.26);
      border-radius: 18px;
      background: rgba(255, 93, 143, 0.07);
    }

    .ia-check {
      width: 58px;
      height: 58px;
      margin: 0 auto 14px;
      border-radius: 999px;
      background: #18a957;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      font-weight: 800;
      letter-spacing: 0.04em;
    }

    .ia-check-error {
      background: #e0446f;
    }

    @keyframes ia-fade-in {
      from {
        opacity: 0;
        transform: translateY(8px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @keyframes ia-dot-pulse {
      0%, 80%, 100% {
        opacity: 0.35;
        transform: scale(0.75);
      }
      40% {
        opacity: 1;
        transform: scale(1);
      }
    }

    @keyframes ia-spin {
      to {
        transform: rotate(360deg);
      }
    }

    @media (prefers-reduced-motion: reduce) {
      #ia-w-btn,
      .ia-msg,
      #ia-w-chat,
      #ia-w-badge,
      .ia-dots span,
      .ia-spinner,
      .ia-time-slot {
        animation: none !important;
        transition: none !important;
      }
    }

    @media (max-width: 640px) {
      #ia-w-btn {
        right: 14px;
        bottom: 14px;
        width: 58px;
        height: 58px;
      }

      #ia-w-chat {
        right: 10px;
        left: 10px;
        bottom: 80px;
        width: auto;
        height: min(82vh, 720px);
        border-radius: 22px;
      }

      #ia-w-badge {
        right: 14px;
        left: 14px;
        bottom: 86px;
        max-width: none;
      }

      #ia-w-header {
        padding: 14px;
      }

      #ia-w-msgs {
        padding: 12px;
        gap: 10px;
      }

      #ia-w-input-area {
        padding: 10px 12px;
        gap: 8px;
      }

      #ia-w-send {
        min-width: 78px;
      }

      .ia-form-card {
        min-height: min(520px, calc(100vh - 220px));
        max-height: 100%;
      }

      .ia-form-body {
        padding: 12px;
      }

      .ia-time-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .ia-resumen-row {
        flex-direction: column;
        gap: 4px;
      }

      .ia-resumen-row span:last-child {
        text-align: left;
      }

      .ia-form-actions {
        flex-direction: column;
      }
    }

    #ia-w-branding {
      text-align: center;
      padding: 5px 14px 8px;
      font-size: 11px;
      color: var(--ia-text-soft);
      background: rgba(255,255,255,0.96);
      border-top: 1px solid rgba(20,34,53,0.05);
      letter-spacing: 0.01em;
    }

    #ia-w-branding a {
      color: var(--ia-color);
      text-decoration: none;
      font-weight: 700;
    }

    #ia-w-branding a:hover {
      text-decoration: underline;
    }
  `;

  document.head.appendChild(css);
}
