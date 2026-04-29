"""Reemplaza bloque <style>...</style> de admin_ui/index.html con CSS SaaS premium.
Conserva HTML/IDs/JS hooks intactos.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "admin_ui" / "index.html"

NEW_CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

:root {
  color-scheme: dark;

  /* Linear/Vercel/Stripe inspired dark */
  --bg:            #0B132B;
  --bg-2:          #091028;
  --bg-3:          #060c1e;
  --surface:       #0F1830;
  --surface-2:     #142039;
  --surface-3:     #182A47;
  --surface-hover: #1D3257;
  --panel:         var(--surface);
  --panel-strong:  var(--surface-2);

  --line:          rgba(255,255,255,0.06);
  --line-strong:   rgba(255,255,255,0.10);

  --text:          #F4F6FB;
  --text-2:        #C7CCE0;
  --soft:          #8fa3b4;
  --soft-2:        #5C6486;
  --muted:         var(--soft);

  /* Vantelia brand accent (cyan + turquoise) */
  --accent:        #00D1FF;
  --accent-2:      #00F5D4;
  --accent-dark:   #0099BB;
  --accent-soft:   rgba(0,209,255,0.12);
  --accent-soft-2: rgba(0,245,212,0.10);
  --accent-line:   rgba(0,209,255,0.28);

  --success:       #22C55E;
  --success-soft:  rgba(34,197,94,0.10);
  --success-line:  rgba(34,197,94,0.30);
  --warn:          #F5A524;
  --warn-soft:     rgba(245,165,36,0.10);
  --warn-line:     rgba(245,165,36,0.30);
  --danger:        #F75D7A;
  --danger-soft:   rgba(247,93,122,0.10);
  --danger-line:   rgba(247,93,122,0.30);
  --info:          #6BA9FF;
  --info-soft:     rgba(107,169,255,0.10);

  --shadow-xs:     0 1px 2px rgba(0,0,0,0.20);
  --shadow-sm:     0 4px 12px rgba(0,0,0,0.20);
  --shadow:        0 8px 24px rgba(0,0,0,0.24);
  --shadow-lg:     0 16px 40px rgba(0,0,0,0.30);
  --ring:          0 0 0 3px rgba(0,209,255,0.22);
  --ring-danger:   0 0 0 3px rgba(247,93,122,0.20);

  --radius-sm:     8px;
  --radius:        12px;
  --radius-lg:     16px;
  --radius-xl:     20px;

  --font:          "Inter", "Segoe UI", system-ui, sans-serif;
  --font-title:    "Space Grotesk", "Inter", sans-serif;

  --topbar-h:      62px;
  --side-w:        268px;
  --side-w-collapsed: 76px;
}

* { box-sizing: border-box; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 999px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.16); }

html { scroll-behavior: smooth; scroll-padding-top: 96px; }

[id], .card, .card.panel, .card.block, section[id], main > section {
  scroll-margin-top: 96px;
}

body {
  margin: 0;
  font-family: var(--font);
  font-size: 14px;
  color: var(--text);
  background:
    radial-gradient(ellipse at 14% 12%, rgba(0,209,255,0.07), transparent 30%),
    radial-gradient(ellipse at 85% 85%, rgba(0,245,212,0.05), transparent 28%),
    linear-gradient(180deg, #0e1b3e 0%, #0B132B 50%, #07101f 100%);
  min-height: 100vh;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

a { color: inherit; text-decoration: none; }
a:hover { color: var(--accent); }

button, input, select, textarea { font: inherit; color: inherit; }

h1,h2,h3,h4 {
  font-family: var(--font-title);
  letter-spacing: -0.02em;
  font-weight: 700;
  margin: 0;
  color: var(--text);
}
h1 { font-size: 1.4rem; line-height: 1.2; }
h2 { font-size: 1.2rem; line-height: 1.3; }
h3 { font-size: 1.05rem; line-height: 1.35; }
h4 { font-size: 0.95rem; line-height: 1.4; }
p { margin: 0; line-height: 1.6; color: var(--text-2); }

/* ── App grid ───────────────────────────────────── */
.app {
  min-height: 100vh;
  display: grid;
  grid-template-columns: var(--side-w) minmax(0, 1fr);
  grid-template-rows: 1fr;
  position: relative;
}
.app.is-collapsed { --side-w: var(--side-w-collapsed); }

/* ── Sidebar ────────────────────────────────────── */
.sidebar {
  border-right: 1px solid var(--line);
  background: rgba(6,7,20,0.94);
  backdrop-filter: blur(18px) saturate(1.4);
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100vh;
  position: sticky;
  top: 0;
  overflow-y: auto;
  overflow-x: hidden;
  transition: width .2s ease;
}

.brand {
  padding: 4px 8px 0;
  display: grid;
  gap: 14px;
}
.brand-mark {
  display: flex; align-items: center; gap: 12px;
  padding: 4px 4px 12px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 4px;
}
.brand-logo {
  width: 36px; height: 36px;
  object-fit: contain;
  border-radius: 8px;
  filter: drop-shadow(0 0 12px rgba(0,209,255,0.20));
  flex: 0 0 auto;
}
.brand-copy { display: grid; gap: 4px; min-width: 0; }
.brand-kicker {
  display: inline-flex; width: fit-content;
  padding: 3px 8px; border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.brand h1 { font-size: 0.98rem; font-weight: 700; line-height: 1.1; }
.brand p { font-size: 12px; color: var(--soft); line-height: 1.45; }
.brand-links { display: flex; gap: 6px; flex-wrap: wrap; }

.app.is-collapsed .brand-copy,
.app.is-collapsed .brand-links,
.app.is-collapsed .nav-text { display: none; }
.app.is-collapsed .brand-mark { justify-content: center; padding-bottom: 8px; }
.app.is-collapsed .nav-button { justify-content: center; padding: 11px 10px; }

/* ── Side nav ───────────────────────────────────── */
.side-nav {
  display: grid;
  gap: 2px;
  padding: 4px 0;
}
.nav-button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 11px;
  justify-content: flex-start;
  padding: 9px 10px;
  background: transparent;
  color: var(--soft);
  border: 1px solid transparent;
  border-radius: 10px;
  text-align: left;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition: background .15s, color .15s, border-color .15s;
  position: relative;
}
.nav-button:hover {
  background: var(--surface-2);
  color: var(--text);
  border-color: var(--line);
  transform: none;
  box-shadow: none;
}
.nav-button.active {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: var(--accent-line);
}
.nav-button.active::before {
  content: '';
  position: absolute;
  left: -6px; top: 8px; bottom: 8px;
  width: 3px;
  border-radius: 999px;
  background: var(--accent);
}

.nav-icon {
  width: 30px;
  height: 30px;
  display: inline-grid;
  place-items: center;
  border-radius: 9px;
  background: rgba(0,209,255,0.10);
  border: 1px solid rgba(0,209,255,0.22);
  color: var(--accent) !important;
  font-family: var(--font-title);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.05em;
  flex: 0 0 auto;
  transition: background .15s, color .15s, border-color .15s, box-shadow .15s, transform .12s;
  text-shadow: 0 0 12px rgba(0,209,255,0.45);
}
.nav-button:hover .nav-icon {
  background: rgba(0,209,255,0.18);
  border-color: rgba(0,209,255,0.40);
  color: var(--accent-2) !important;
  transform: scale(1.04);
}
.nav-button.active .nav-icon {
  background: linear-gradient(135deg, var(--accent), var(--accent-2)) !important;
  border-color: transparent;
  color: #04101c !important;
  text-shadow: none;
  box-shadow: 0 6px 18px rgba(0,209,255,0.40);
}

.nav-text { display: grid; gap: 1px; min-width: 0; }
.nav-text strong, .nav-text span {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block;
}
.nav-text strong { font-size: 13px; font-weight: 600; line-height: 1.2; color: inherit; }
.nav-text span { font-size: 11px; color: var(--soft-2); font-weight: 500; line-height: 1.3; }

/* ── Main column ────────────────────────────────── */
.main {
  padding: 0;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 100vh;
}

/* Topbar (synthesized over .login card / first stats group) */
.login {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  background: rgba(8,10,28,0.86);
  backdrop-filter: blur(18px) saturate(1.4);
  border-bottom: 1px solid var(--line);
  min-height: var(--topbar-h);
}
.login > * { margin: 0 !important; }
.login strong { font-size: 13.5px; color: var(--text); font-weight: 600; }
.login .muted { font-size: 12px; color: var(--soft); }
.login .row { gap: 8px !important; }

/* ── Stats strip ─────────────────────────────────── */
.stats {
  padding: 18px 24px 0;
  display: grid;
  gap: 12px;
}
.stats h2 { font-size: 0.9rem; color: var(--soft); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}
.stat {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: border-color .15s, transform .15s;
}
.stat:hover { border-color: var(--line-strong); transform: translateY(-1px); }
.stat strong {
  font-family: var(--font-title);
  font-size: 1.7rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.1;
}
.stat span {
  font-size: 11.5px;
  color: var(--soft);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
}

/* ── Dashboard view (toggle by .active via JS) ──── */
.dashboard-view { display: none; }
.dashboard-view.active {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px 24px 56px;
  flex: 1;
  animation: fadeUp .25s ease both;
}

/* Client tab panels also driven by .active */
.client-tab-panel { display: none; }
.client-tab-panel.active { display: flex; }

/* ── Cards ──────────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: border-color .18s, box-shadow .18s;
  box-shadow: var(--shadow-xs);
}
.card.panel { padding: 22px 22px 24px; gap: 16px; }
.card:not(.panel):hover { border-color: var(--line-strong); }

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 4px;
}
.section-header > div:first-child { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.section-header h2 { font-size: 1.1rem; }
.section-header p, .section-header .muted { font-size: 12.5px; color: var(--soft); margin: 0; }
.section-header .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

.actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

/* ── Hero card ──────────────────────────────────── */
.hero {
  background:
    linear-gradient(135deg, var(--accent-soft), var(--accent-soft-2)),
    var(--surface);
  border: 1px solid var(--accent-line);
  border-radius: var(--radius-lg);
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.hero h2 { font-size: 1.4rem; }
.hero p { color: var(--text-2); }
.hero-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(0,209,255,0.18);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  width: fit-content;
}

/* ── Buttons ─────────────────────────────────────── */
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #04101c;
  padding: 10px 18px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 13.5px;
  line-height: 1;
  font-family: var(--font-title);
  letter-spacing: 0.01em;
  box-shadow: 0 8px 22px rgba(0,209,255,0.22);
  transition: filter .18s, transform .12s, box-shadow .18s, background .15s, color .15s, border-color .15s;
  white-space: nowrap;
}
button:hover { filter: brightness(1.06); transform: translateY(-1px); box-shadow: 0 12px 28px rgba(0,209,255,0.32); }
button:active { transform: translateY(0); }
button:focus-visible { outline: none; box-shadow: var(--ring), 0 8px 22px rgba(0,209,255,0.22); }
button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; filter: none; }

button.secondary {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--line-strong);
}
button.secondary:hover { background: var(--surface-3); border-color: var(--accent-line); color: var(--text); }

button.ghost {
  background: transparent;
  color: var(--text-2);
  border: 1px solid var(--line-strong);
}
button.ghost:hover { background: var(--surface-2); color: var(--text); border-color: var(--accent-line); }

button.danger {
  background: transparent;
  color: var(--danger);
  border: 1px solid var(--danger-line);
}
button.danger:hover { background: var(--danger-soft); border-color: var(--danger); color: var(--danger); }

button.small {
  padding: 7px 12px;
  font-size: 12px;
  border-radius: 8px;
}

/* ── Forms ──────────────────────────────────────── */
label {
  display: grid;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  letter-spacing: 0.01em;
}

input[type="text"], input[type="email"], input[type="password"], input[type="search"],
input[type="number"], input[type="date"], input[type="time"], input[type="url"], input[type="tel"],
select, textarea {
  width: 100%;
  padding: 10px 12px;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  font-size: 13.5px;
  transition: border-color .15s, box-shadow .15s, background .15s;
  font-family: var(--font);
}
input::placeholder, textarea::placeholder { color: var(--soft-2); }
input:hover, select:hover, textarea:hover { border-color: rgba(0,209,255,0.30); }
input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: var(--ring);
  background: var(--surface-2);
}
input[aria-invalid="true"], textarea[aria-invalid="true"] {
  border-color: var(--danger);
  box-shadow: var(--ring-danger);
}
input:disabled, select:disabled, textarea:disabled { opacity: 0.5; cursor: not-allowed; }
textarea { min-height: 90px; resize: vertical; line-height: 1.55; }

input[type="checkbox"], input[type="radio"] {
  width: 16px; height: 16px; accent-color: var(--accent); margin: 0; flex-shrink: 0;
}

select {
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238fa3b4' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 32px;
}

.field-note {
  font-size: 12px;
  color: var(--soft);
  line-height: 1.5;
  margin-top: 2px;
}

.inline-check {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--text-2); cursor: pointer;
}

/* ── Status / muted / pills ─────────────────────── */
.status {
  font-size: 13px;
  color: var(--text-2);
  padding: 10px 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  line-height: 1.5;
}
.status.success { color: var(--success); border-color: var(--success-line); background: var(--success-soft); }
.status.error { color: var(--danger); border-color: var(--danger-line); background: var(--danger-soft); }
.status.warn { color: var(--warn); border-color: var(--warn-line); background: var(--warn-soft); }

.muted { color: var(--soft); font-size: 13px; line-height: 1.55; }

.pill {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--surface-2);
  color: var(--text-2);
  border: 1px solid var(--line);
  letter-spacing: 0.01em;
}
.pill.success { background: var(--success-soft); color: var(--success); border-color: var(--success-line); }
.pill.warn    { background: var(--warn-soft); color: var(--warn); border-color: var(--warn-line); }
.pill.danger  { background: var(--danger-soft); color: var(--danger); border-color: var(--danger-line); }
.pill.info    { background: var(--info-soft); color: var(--info); border-color: rgba(107,169,255,0.30); }
.pill.accent  { background: var(--accent-soft); color: var(--accent); border-color: var(--accent-line); }

.pills { display: flex; flex-wrap: wrap; gap: 6px; }

/* ── Grids ──────────────────────────────────────── */
.grid { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; }
.grid-3 { display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0,1fr)); }
.split { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

/* ── Panel & subcards ───────────────────────────── */
.panel { display: flex; flex-direction: column; gap: 14px; }
.subcard {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
}

.booking-settings { display: flex; flex-direction: column; gap: 14px; }

/* ── Client tabs ────────────────────────────────── */
.client-tabs {
  display: inline-flex;
  gap: 2px;
  background: var(--surface-2);
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 10px;
  flex-wrap: wrap;
}
.client-tabs button {
  background: transparent;
  color: var(--soft);
  border: none;
  padding: 7px 12px;
  font-size: 12.5px;
  font-weight: 600;
  border-radius: 7px;
  box-shadow: none;
  transform: none;
}
.client-tabs button:hover { background: var(--surface); color: var(--text); transform: none; box-shadow: none; }
.client-tabs button.active { background: var(--accent); color: #061021; }

.client-tab-panel { display: flex; flex-direction: column; gap: 14px; }
.client-tab-panel.hidden { display: none !important; }

/* ── Client directory ───────────────────────────── */
.client-directory { display: flex; flex-direction: column; gap: 8px; }
.client-directory-toolbar {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  padding: 10px 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.client-directory-toolbar input { flex: 1 1 240px; min-width: 180px; }

.client-list-row {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
  transition: background .15s, border-color .15s, transform .12s;
}
.client-list-row:hover { background: var(--surface-2); border-color: var(--line-strong); transform: translateY(-1px); }
.client-list-row.active { border-color: var(--accent); background: var(--accent-soft); }

.client-list-main { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.client-list-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.client-list-side { display: flex; flex-direction: column; gap: 4px; align-items: flex-end; min-width: 0; }
.client-list-name { font-size: 14px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.client-list-meta { font-size: 12px; color: var(--soft); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Client summary block */
.client-summary {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  padding: 14px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.client-summary-block {
  display: flex; flex-direction: column; gap: 4px;
  padding: 10px 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.client-summary-block strong { font-size: 13px; color: var(--text); font-weight: 600; }
.client-summary-block span { font-size: 12px; color: var(--soft); }

/* Account/security cards (sidebar of admin top) */
.account-card, .security-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  display: flex; flex-direction: column; gap: 12px;
}
.account-chip {
  display: inline-flex; padding: 3px 9px;
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  width: fit-content;
}
.account-identity { display: flex; flex-direction: column; gap: 2px; }
.account-actions { display: flex; gap: 6px; flex-wrap: wrap; padding-top: 4px; }
.support-note { font-size: 12px; color: var(--soft-2); }

/* ── Snippet ────────────────────────────────────── */
.snippet {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12.5px;
  background: var(--bg-2);
  color: var(--text);
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  min-height: 96px;
  resize: vertical;
}

/* ── Express panel ──────────────────────────────── */
.express-panel {
  display: flex; flex-direction: column; gap: 16px;
  background:
    linear-gradient(135deg, rgba(0,209,255,0.05), rgba(0,245,212,0.04)),
    var(--surface);
  border: 1px solid var(--accent-line);
}

/* ── Toolbar ────────────────────────────────────── */
.toolbar {
  display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
  padding: 10px 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.toolbar-filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

/* ── Users grid ─────────────────────────────────── */
.users-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
.user-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
  transition: border-color .18s, transform .12s;
}
.user-card:hover { border-color: var(--line-strong); transform: translateY(-1px); }
.user-top { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.user-title { display: grid; gap: 2px; flex: 1; min-width: 0; }
.user-title strong { font-size: 13.5px; color: var(--text); }
.user-title span { font-size: 12px; color: var(--soft); }

.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.meta-box {
  background: var(--surface-2); border: 1px solid var(--line); border-radius: 9px;
  padding: 8px 10px;
  display: flex; flex-direction: column; gap: 2px;
}
.meta-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--soft); font-weight: 600; }
.meta-value { font-size: 13px; color: var(--text); font-weight: 500; word-break: break-word; }
.action-row { display: flex; gap: 6px; flex-wrap: wrap; padding-top: 4px; }

/* ── Empty state ────────────────────────────────── */
.empty {
  padding: 30px 20px;
  text-align: center;
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  color: var(--soft);
  font-size: 13px;
  display: flex; flex-direction: column; gap: 8px; align-items: center;
}

/* ── Loading ────────────────────────────────────── */
.loading-inline {
  display: inline-flex; gap: 6px; align-items: center;
  font-size: 12.5px; color: var(--soft);
}
.loading-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
  animation: pulse 1.2s ease-in-out infinite;
}
.loading-dot:nth-child(2) { animation-delay: 0.15s; }
.loading-dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.85); }
  40% { opacity: 1; transform: scale(1); }
}

/* ── Tables ─────────────────────────────────────── */
.table-shell {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
}
th, td {
  text-align: left;
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
th {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--soft);
  font-weight: 600;
  background: var(--surface-2);
  position: sticky;
  top: 0;
  z-index: 1;
}
tbody tr { transition: background .15s; }
tbody tr:hover { background: var(--surface-2); }
tbody tr:last-child td { border-bottom: none; }

.booking-meta {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 6px;
}
.booking-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.filters-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }

/* ── Guided editor ──────────────────────────────── */
.guided-editor {
  display: flex; flex-direction: column; gap: 12px;
  padding: 14px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.guided-toolbar {
  display: flex; gap: 8px; flex-wrap: wrap;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

/* ── Token list ─────────────────────────────────── */
.token-list { display: flex; flex-wrap: wrap; gap: 6px; min-height: 36px; padding: 6px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; }
.token {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  color: var(--text);
  padding: 4px 8px;
  border-radius: 7px;
  font-size: 12px;
}
.token button {
  background: transparent; color: var(--soft); border: none; padding: 0 0 0 4px;
  font-size: 14px; line-height: 1; cursor: pointer; box-shadow: none; transform: none;
}
.token button:hover { color: var(--danger); transform: none; box-shadow: none; background: transparent; }

/* ── Weekday checks ─────────────────────────────── */
.weekday-checks {
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 8px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.weekday-checks label { padding: 6px 10px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; cursor: pointer; flex-direction: row; align-items: center; gap: 6px; font-size: 12.5px; }

/* ── Modal ──────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(3,4,12,0.74);
  backdrop-filter: blur(6px);
  display: grid; place-items: center;
  z-index: 100;
}
.modal-overlay[aria-hidden="true"] { display: none; }
.modal-card {
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-xl);
  padding: 24px;
  max-width: min(640px, calc(100vw - 32px));
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: var(--shadow-lg);
  display: flex; flex-direction: column; gap: 14px;
}
.modal-card[hidden] { display: none; }
.modal-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.modal-header h3 { font-size: 1.05rem; }
.summary-strip {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px;
  padding: 12px; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius);
}
.summary-item { display: flex; flex-direction: column; gap: 2px; }
.summary-item strong { font-size: 13px; color: var(--text); }
.summary-item span { font-size: 11px; color: var(--soft); text-transform: uppercase; letter-spacing: 0.05em; }
.modal-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

.slot-status { font-size: 13px; color: var(--soft); padding: 8px 0; }
.slot-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  gap: 6px; max-height: 260px; overflow-y: auto;
}
.slot-grid button {
  background: var(--surface-2); color: var(--text); border: 1px solid var(--line);
  padding: 8px 10px; font-size: 12.5px; font-weight: 600;
}
.slot-grid button:hover { background: var(--accent-soft); color: var(--accent); border-color: var(--accent-line); }
.slot-grid button.selected { background: var(--accent); color: #061021; border-color: var(--accent); }

/* ── Timeline ──────────────────────────────────── */
.timeline-list { display: flex; flex-direction: column; gap: 10px; }
.timeline-item { display: grid; grid-template-columns: 36px 1fr; gap: 10px; }
.timeline-dot {
  width: 12px; height: 12px; border-radius: 50%;
  background: var(--accent);
  margin: 5px auto 0;
  border: 3px solid var(--surface);
  box-shadow: 0 0 0 1px var(--accent-line);
}
.timeline-card {
  background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 4px;
}
.timeline-meta { display: flex; gap: 8px; flex-wrap: wrap; font-size: 11.5px; color: var(--soft); }
.timeline-date { font-family: var(--font-title); font-weight: 600; color: var(--text); }

/* ── Login / forgot card centered (when no session) ── */
.login-screen {
  position: fixed; inset: 0;
  display: grid; place-items: center;
  padding: 20px;
}

/* ── Animations ─────────────────────────────────── */
.card.panel:not(.hidden), .card:not(.panel):not(.hidden) {
  animation: fadeUp .25s ease both;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

[data-loading="true"] {
  background: linear-gradient(90deg, var(--surface-2) 0%, var(--surface-3) 50%, var(--surface-2) 100%);
  background-size: 200% 100%;
  animation: skeleton 1.4s ease-in-out infinite;
  color: transparent !important;
  border-radius: 6px;
}
@keyframes skeleton {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

/* ── Hidden helper ──────────────────────────────── */
.hidden { display: none !important; }

/* ── Responsive ─────────────────────────────────── */
@media (max-width: 1180px) {
  :root { --side-w: 230px; }
  .grid, .grid-3, .split { grid-template-columns: 1fr; }
  .modal-grid { grid-template-columns: 1fr; }
}

@media (max-width: 960px) {
  .app {
    grid-template-columns: 1fr;
  }
  .sidebar {
    position: fixed;
    top: 0; left: 0;
    width: 280px;
    height: 100vh;
    z-index: 80;
    transform: translateX(-100%);
    transition: transform .25s ease;
    box-shadow: var(--shadow-lg);
  }
  .sidebar.is-open { transform: translateX(0); }
  .side-nav { padding: 4px 0; }

  .main { padding: 0; }
  .login { padding: 12px 16px; }
  .stats { padding: 14px 16px 0; }
  .dashboard-view { padding: 14px 16px 44px; }

  .grid, .grid-3, .split,
  .client-summary, .meta-grid, .summary-strip, .modal-grid {
    grid-template-columns: 1fr;
  }
  .hero { padding: 18px; }
  .client-list-row { grid-template-columns: 1fr; }
  .client-list-side { align-items: flex-start; }
  .client-list-actions { justify-content: flex-start; }
  .modal-overlay { padding: 16px; }
}

@media (max-width: 560px) {
  body { font-size: 13.5px; }
  h1 { font-size: 1.2rem; }
  h2 { font-size: 1.05rem; }
  .card { padding: 16px; }
  .stat strong { font-size: 1.3rem; }
}
"""

html = INDEX.read_text(encoding="utf-8")
new_html = re.sub(
    r"<style>.*?</style>",
    "<style>" + NEW_CSS + "  </style>",
    html,
    count=1,
    flags=re.DOTALL,
)
INDEX.write_text(new_html, encoding="utf-8")
print(f"admin_ui/index.html: {INDEX.stat().st_size/1024:.1f} KB")
