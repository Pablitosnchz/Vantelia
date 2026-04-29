"""Reemplaza bloque <style>...</style> de portal_ui/index.html con nuevo CSS SaaS.
Conserva intacto el HTML, IDs y bindings JS.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "portal_ui" / "index.html"

NEW_CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

/* ── Design tokens ─────────────────────────────── */
:root {
  color-scheme: dark;

  /* Base palette - Vantelia brand dark */
  --bg:            #0B132B;
  --bg-2:          #091028;
  --bg-3:          #060c1e;
  --surface:       #0F1830;
  --surface-2:     #142039;
  --surface-3:     #182A47;
  --surface-hover: #1D3257;

  --line:          rgba(255,255,255,0.06);
  --line-strong:   rgba(255,255,255,0.10);
  --line-accent:   rgba(0,209,255,0.22);

  --text:          #F0F4F8;
  --text-2:        #C8D3E2;
  --soft:          #8fa3b4;
  --soft-2:        #637c8e;
  --muted:         #8fa3b4;

  /* Accent: Vantelia brand (cyan + turquoise) */
  --accent:        #00D1FF;
  --accent-2:      #00F5D4;
  --accent-soft:   rgba(0,209,255,0.12);
  --accent-soft-2: rgba(0,245,212,0.10);
  --accent-line:   rgba(0,209,255,0.28);
  --accent-dark:   #0099BB;

  /* Semantic */
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

  /* Shadows */
  --shadow-xs:     0 1px 2px rgba(0,0,0,0.20);
  --shadow-sm:     0 4px 12px rgba(0,0,0,0.20);
  --shadow:        0 8px 24px rgba(0,0,0,0.24);
  --shadow-lg:     0 16px 40px rgba(0,0,0,0.30);
  --ring:          0 0 0 3px rgba(0,209,255,0.20);
  --ring-danger:   0 0 0 3px rgba(247,93,122,0.20);

  /* Radius */
  --radius-sm:     8px;
  --radius:        12px;
  --radius-lg:     16px;
  --radius-xl:     20px;

  /* Typography */
  --font:          "Inter", "Segoe UI", system-ui, sans-serif;
  --font-title:    "Space Grotesk", "Inter", sans-serif;

  /* Spacing & layout */
  --maxw:          100%;
  --side-w:        272px;
}

* { box-sizing: border-box; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 999px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.16); }

html { scroll-behavior: smooth; scroll-padding-top: 96px; }

/* All scrollable targets get padding so sticky topbar doesn't cover them */
[id], .card, .card.panel, .card.block, .card.hero, section[id], main > section {
  scroll-margin-top: 96px;
}

body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font);
  font-size: 14px;
  color: var(--text);
  background:
    radial-gradient(ellipse at 14% 12%, rgba(0,209,255,0.07), transparent 30%),
    radial-gradient(ellipse at 85% 85%, rgba(0,245,212,0.05), transparent 28%),
    linear-gradient(180deg, #0e1b3e 0%, #0B132B 50%, #07101f 100%);
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

a { color: inherit; text-decoration: none; }
a:hover { color: var(--accent); }

button, input, select, textarea {
  font: inherit;
  color: inherit;
}

h1, h2, h3, h4 {
  font-family: var(--font-title);
  letter-spacing: -0.02em;
  font-weight: 700;
  margin: 0;
  color: var(--text);
}

h1 { font-size: 1.45rem; line-height: 1.2; }
h2 { font-size: 1.25rem; line-height: 1.3; }
h3 { font-size: 1.05rem; line-height: 1.35; }
h4 { font-size: 0.95rem; line-height: 1.4; }

p { margin: 0; line-height: 1.6; color: var(--text-2); }

/* ── App layout ─────────────────────────────────── */
.page {
  width: 100%;
  min-height: 100vh;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: var(--side-w) minmax(0, 1fr);
  grid-template-rows: auto 1fr;
  align-items: start;
}

/* TOPBAR – sits across whole top row visually but defined to occupy left column structurally  */
.topbar {
  grid-column: 1 / -1;
  grid-row: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--line);
  background: rgba(11,16,28,0.85);
  backdrop-filter: blur(18px) saturate(1.4);
  z-index: 30;
  position: sticky;
  top: 0;
  min-height: auto;
}

.topbar .brand { display: grid; gap: 0; }
.topbar .brand-mark {
  display: flex; align-items: center; gap: 12px;
}
.topbar .brand-logo {
  width: 36px; height: 36px; object-fit: contain;
  border-radius: 8px;
  filter: drop-shadow(0 0 12px rgba(0,209,255,0.20));
}
.topbar .brand-copy { display: grid; gap: 0; }
.topbar .brand-kicker {
  display: none;
}
.topbar .brand h1 {
  margin: 0;
  font-size: 1.05rem;
  font-family: var(--font-title);
  font-weight: 800;
  letter-spacing: -0.01em;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.topbar .brand p {
  display: none;
}
.top-actions {
  display: flex; align-items: center; gap: 10px;
}

/* SIDEBAR */
.shell {
  display: contents;
}

.sidebar {
  grid-column: 1;
  grid-row: 2;
  width: var(--side-w);
  border-right: 1px solid var(--line);
  background: rgba(8,12,22,0.94);
  backdrop-filter: blur(16px);
  padding: 18px 14px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: calc(100vh - 65px);
  position: sticky;
  top: 65px;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* MAIN content */
.main {
  grid-column: 2;
  grid-row: 2;
  padding: 28px 32px 64px;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

/* ── Card system ────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  overflow: visible;
  transition: border-color .18s, box-shadow .18s;
}

.block {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card.panel {
  padding: 22px 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card.hero {
  padding: 26px 28px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background:
    linear-gradient(135deg, rgba(0,209,255,0.06), rgba(0,245,212,0.04)),
    var(--surface);
  border-color: var(--line-strong);
}
.hero h2 { font-size: 1.5rem; }
.hero p { color: var(--text-2); max-width: 720px; }
.hero-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  width: fit-content;
}

/* ── Buttons ────────────────────────────────────── */
/* Default button: neutral surface, NO brand shadow */
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  border: 1px solid var(--line-strong);
  background: var(--surface-2);
  color: var(--text);
  padding: 9px 16px;
  border-radius: 10px;
  font-weight: 600;
  font-size: 13.5px;
  line-height: 1;
  font-family: var(--font);
  transition: background .15s, border-color .15s, transform .12s, color .15s, filter .15s, box-shadow .15s;
  white-space: nowrap;
  box-shadow: none;
}
button:hover { background: var(--surface-3); border-color: var(--accent-line); transform: translateY(-1px); }
button:active { transform: translateY(0); }
button:focus-visible { outline: none; box-shadow: var(--ring); }
button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; filter: none; }

/* Primary: gradient brand + glow shadow */
button.primary {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #04101c;
  border-color: transparent;
  font-family: var(--font-title);
  font-weight: 700;
  border-radius: 999px;
  padding: 10px 18px;
  box-shadow: 0 8px 22px rgba(0,209,255,0.22);
}
button.primary:hover { filter: brightness(1.06); transform: translateY(-1px); box-shadow: 0 12px 28px rgba(0,209,255,0.32); border-color: transparent; background: linear-gradient(135deg, var(--accent), var(--accent-2)); }

button.secondary {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--line-strong);
  box-shadow: none;
}
button.secondary:hover { background: var(--surface-3); border-color: var(--accent-line); color: var(--text); }

button.ghost {
  background: transparent;
  color: var(--text-2);
  border: 1px solid var(--line-strong);
  box-shadow: none;
}
button.ghost:hover { background: var(--surface-2); color: var(--text); border-color: var(--line-accent); }

button.danger {
  background: transparent;
  color: var(--danger);
  border: 1px solid var(--danger-line);
  box-shadow: none;
}
button.danger:hover { background: var(--danger-soft); border-color: var(--danger); color: var(--danger); }

button.small {
  padding: 7px 12px;
  font-size: 12.5px;
  border-radius: 8px;
}

.row {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
}
.grid {
  display: grid; gap: 12px;
}

/* ── Sidebar nav ────────────────────────────────── */
.side-nav {
  display: grid;
  gap: 2px;
  padding: 6px;
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
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
}
.nav-icon svg {
  width: 17px;
  height: 17px;
  display: block;
  stroke: currentColor !important;
  fill: none !important;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
  pointer-events: none;
}
.nav-icon svg * { stroke: currentColor !important; fill: none !important; }
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
  box-shadow: 0 6px 18px rgba(0,209,255,0.40);
}

.nav-text {
  display: grid;
  gap: 1px;
  min-width: 0;
}
.nav-text strong, .nav-text span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}
.nav-text strong {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.2;
  color: inherit;
}
.nav-text span {
  font-size: 11px;
  font-weight: 500;
  color: var(--soft-2);
  line-height: 1.3;
}

.nav-button-inline {
  background: transparent;
  border: 1px dashed var(--line-strong);
  color: var(--soft);
  padding: 8px 12px;
  font-size: 12.5px;
}
.nav-button-inline:hover { background: var(--surface-2); color: var(--text); border-color: var(--accent-line); border-style: solid; }

/* ── Sidebar widgets ─────────────────────────────── */
.role-pill {
  display: inline-flex;
  width: fit-content;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.status {
  font-size: 13px;
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--line);
  padding: 10px 12px;
  border-radius: 10px;
  line-height: 1.5;
}
.status.success { color: var(--success); border-color: var(--success-line); background: var(--success-soft); }
.status.error { color: var(--danger); border-color: var(--danger-line); background: var(--danger-soft); }
.status.warn { color: var(--warn); border-color: var(--warn-line); background: var(--warn-soft); }

.muted { color: var(--soft); font-size: 13px; line-height: 1.55; }

.hidden { display: none !important; }

/* ── Forms ──────────────────────────────────────── */
label {
  display: grid;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  letter-spacing: 0.01em;
}

input[type="text"],
input[type="email"],
input[type="password"],
input[type="search"],
input[type="number"],
input[type="date"],
input[type="time"],
input[type="url"],
input[type="tel"],
select,
textarea {
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

input:hover, select:hover, textarea:hover { border-color: var(--line-accent); }

input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: var(--ring);
  background: var(--surface-2);
}

input:disabled, select:disabled, textarea:disabled { opacity: 0.5; cursor: not-allowed; }

input[aria-invalid="true"], textarea[aria-invalid="true"], select[aria-invalid="true"] {
  border-color: var(--danger);
  box-shadow: var(--ring-danger);
}

textarea {
  min-height: 88px;
  resize: vertical;
  line-height: 1.55;
  font-family: var(--font);
}

input[type="checkbox"], input[type="radio"] {
  width: 16px; height: 16px;
  accent-color: var(--accent);
  margin: 0;
  flex-shrink: 0;
}

.inline-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
}

select {
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238fa3b4' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'></polyline></svg>");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 32px;
}

/* ── Stats grid (top of main) ────────────────────── */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.stat {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: border-color .18s, transform .15s;
}
.stat:hover { border-color: var(--line-strong); transform: translateY(-1px); }
.stat strong {
  font-family: var(--font-title);
  font-size: 1.8rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.1;
  letter-spacing: -0.02em;
}
.stat span {
  font-size: 12px;
  color: var(--soft);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

/* ── Metric grid ────────────────────────────────── */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}
.metric-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.metric-card span:first-child {
  font-size: 12px;
  color: var(--soft);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.metric-card strong {
  font-family: var(--font-title);
  font-size: 2rem;
  font-weight: 700;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.1;
  letter-spacing: -0.02em;
  margin: 2px 0;
}
.metric-card small {
  font-size: 12px;
  color: var(--soft-2);
  line-height: 1.5;
}

.insight-panel {
  padding: 14px 16px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-line);
  border-radius: var(--radius);
  display: grid;
  gap: 6px;
}
.insight-panel strong { color: var(--accent); font-size: 13px; }

/* ── Panel header ────────────────────────────────── */
.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.panel-header h3 { font-size: 1.05rem; }
.panel-header .muted { font-size: 12.5px; }

/* ── Segmented control ──────────────────────────── */
.segmented {
  display: inline-flex;
  background: var(--surface-2);
  padding: 4px;
  border-radius: 10px;
  border: 1px solid var(--line);
  gap: 2px;
}
.segmented button {
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
.segmented button:hover { background: var(--surface); color: var(--text); transform: none; box-shadow: none; }
.segmented button.active {
  background: var(--accent);
  color: #061021;
  box-shadow: 0 1px 3px rgba(0,0,0,0.20);
}

/* ── Booking grid + cards ───────────────────────── */
.booking-grid {
  display: grid;
  gap: 14px;
}
.booking-toolbar {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  padding: 10px;
  background: var(--surface-2);
  border-radius: var(--radius);
  border: 1px solid var(--line);
}
.quick-actions {
  display: flex; gap: 6px; flex-wrap: wrap;
}

.booking-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: border-color .18s, box-shadow .18s, transform .15s;
}
.booking-card:hover {
  border-color: var(--line-strong);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.booking-top {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  flex-wrap: wrap;
}
.booking-heading {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1 1 auto;
  min-width: 0;
}
.booking-date-tile {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  background: var(--accent-soft);
  border: 1px solid var(--accent-line);
  border-radius: 12px;
  padding: 10px 14px;
  text-align: center;
  min-width: 64px;
}
.booking-date-tile .day {
  font-family: var(--font-title); font-size: 1.5rem; font-weight: 700; color: var(--accent); line-height: 1;
}
.booking-date-tile .month {
  font-size: 10px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.06em; margin-top: 4px;
}
.booking-title {
  display: grid; gap: 4px; min-width: 0;
}
.booking-title strong { font-size: 14px; color: var(--text); }
.booking-title .muted { font-size: 12.5px; }

.pills { display: flex; flex-wrap: wrap; gap: 6px; }
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
.pill.info    { background: var(--info-soft); color: var(--info); border-color: var(--accent-line); }
.pill.accent  { background: var(--accent-soft); color: var(--accent); border-color: var(--accent-line); }

.booking-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}
.meta-box {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  display: flex; flex-direction: column; gap: 2px;
}
.meta-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--soft); font-weight: 600; }
.meta-value { font-size: 13px; color: var(--text); font-weight: 500; word-break: break-word; }

.booking-actions {
  display: flex; gap: 8px; flex-wrap: wrap;
  padding-top: 4px;
}

/* ── Calendar ───────────────────────────────────── */
.calendar-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.calendar-head {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
}
.calendar-title {
  font-family: var(--font-title); font-size: 1.05rem; font-weight: 700; color: var(--text);
}
.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 4px;
}
.calendar-weekday {
  font-size: 10.5px;
  color: var(--soft);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  text-align: center;
  padding: 6px 0;
  font-weight: 600;
}
.calendar-day {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 8px;
  min-height: 70px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  transition: background .15s, border-color .15s, transform .12s;
}
.calendar-day:hover { background: var(--surface-3); border-color: var(--line-accent); transform: translateY(-1px); }
.calendar-day.is-other-month { opacity: 0.4; }
.calendar-day.is-today { border-color: var(--accent); background: var(--accent-soft); }
.calendar-day.is-selected { border-color: var(--accent); box-shadow: var(--ring); }
.calendar-day.is-empty { background: transparent; border-color: transparent; cursor: default; }

/* Closed days (rest day / commerce closed) — RED */
.calendar-day.is-closed,
.calendar-day[data-state="closed"],
.calendar-day.closed {
  background: rgba(247,93,122,0.10);
  border-color: rgba(247,93,122,0.45);
}
.calendar-day.is-closed .calendar-number,
.calendar-day[data-state="closed"] .calendar-number,
.calendar-day.closed .calendar-number { color: var(--danger); }
.calendar-day.is-closed::after,
.calendar-day[data-state="closed"]::after,
.calendar-day.closed::after {
  content: 'Cerrado';
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--danger);
  font-weight: 700;
  margin-top: auto;
}

/* Blocked / vacation days — YELLOW */
.calendar-day.is-blocked,
.calendar-day[data-state="blocked"],
.calendar-day.blocked,
.calendar-day.is-vacation,
.calendar-day[data-state="vacation"] {
  background: rgba(245,165,36,0.10);
  border-color: rgba(245,165,36,0.45);
}
.calendar-day.is-blocked .calendar-number,
.calendar-day[data-state="blocked"] .calendar-number,
.calendar-day.blocked .calendar-number,
.calendar-day.is-vacation .calendar-number,
.calendar-day[data-state="vacation"] .calendar-number { color: var(--warn); }

/* Calendar event variations */
.calendar-event.closed,
.calendar-event[data-state="closed"] {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger-line);
}
.calendar-event.blocked,
.calendar-event[data-state="blocked"],
.calendar-event.vacation {
  background: var(--warn-soft);
  color: var(--warn);
  border-color: var(--warn-line);
}

.calendar-number {
  font-size: 12.5px; font-weight: 700; color: var(--text); font-family: var(--font-title);
}
.calendar-day.is-today .calendar-number { color: var(--accent); }
.calendar-count { font-size: 10px; color: var(--soft); }

.calendar-event {
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid var(--accent-line);
  border-radius: 5px;
  padding: 2px 5px;
  font-size: 10.5px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.calendar-event.success { background: var(--success-soft); color: var(--success); border-color: var(--success-line); }
.calendar-event.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn-line); }
.calendar-event.danger { background: var(--danger-soft); color: var(--danger); border-color: var(--danger-line); }

/* ── Day agenda ─────────────────────────────────── */
.day-agenda {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.day-agenda-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.day-agenda-title { font-family: var(--font-title); font-size: 1.05rem; font-weight: 700; }
.day-agenda-list { display: grid; gap: 8px; }
.day-agenda-item {
  display: grid;
  grid-template-columns: 80px minmax(0,1fr) auto;
  gap: 12px;
  align-items: center;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
}
.day-agenda-time {
  font-family: var(--font-title); font-weight: 700; color: var(--accent); font-size: 13.5px;
}
.day-agenda-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.day-agenda-main strong { font-size: 14px; color: var(--text); font-weight: 600; }
.day-agenda-main .muted { font-size: 12.5px; color: var(--soft); }
/* Highlight professional name (data-employee, .professional, .employee-name inline) */
.day-agenda-main .employee-name,
.day-agenda-main [data-employee],
.day-agenda-main .professional,
.booking-card .employee-name,
.booking-card [data-employee],
.booking-card .professional,
.today-booking-card .employee-name,
.today-booking-card [data-employee],
.today-booking-card .professional {
  color: var(--accent-2) !important;
  font-weight: 700;
  font-family: var(--font-title);
  letter-spacing: 0.005em;
}
.day-agenda-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.day-agenda-actions button { padding: 7px 12px; font-size: 12px; }

/* ── Today layout ───────────────────────────────── */
.today-layout {
  display: grid; gap: 16px;
}
.today-menu-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.today-menu-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.today-menu-list { display: grid; gap: 6px; }
.today-menu-item {
  display: grid; grid-template-columns: 56px 1fr auto; gap: 10px;
  align-items: center;
  padding: 8px 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 9px;
  font-size: 12.5px;
}

.today-summary-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px;
}
.today-summary-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.today-summary-card strong {
  font-size: 1.5rem; font-family: var(--font-title); font-weight: 700; line-height: 1.1;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.today-summary-card span { font-size: 11.5px; color: var(--soft); text-transform: uppercase; letter-spacing: 0.05em; }

.today-columns {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
}
.today-list { display: grid; gap: 8px; }
.today-booking-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.today-booking-top {
  display: flex; justify-content: space-between; gap: 8px; align-items: center; flex-wrap: wrap;
}
.today-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 8px;
  background: var(--surface-3);
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-2);
}

/* ── Reschedule ─────────────────────────────────── */
.reschedule-panel {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px;
  display: flex; flex-direction: column; gap: 12px;
}
.reschedule-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.slot-status { font-size: 13px; color: var(--soft); }
.slot-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 6px;
  max-height: 280px; overflow-y: auto;
}

/* ── Empty state ────────────────────────────────── */
.empty {
  padding: 32px 24px;
  text-align: center;
  background: var(--surface);
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  color: var(--soft);
  font-size: 13px;
  display: flex; flex-direction: column; gap: 8px; align-items: center;
}
.empty::before {
  content: '';
  width: 40px; height: 40px;
  border-radius: 12px;
  background:
    linear-gradient(135deg, var(--accent-soft), var(--accent-soft-2));
  border: 1px solid var(--accent-line);
  display: grid; place-items: center;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%2300D1FF' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'><rect x='3' y='4' width='18' height='18' rx='2'/><line x1='16' y1='2' x2='16' y2='6'/><line x1='8' y1='2' x2='8' y2='6'/><line x1='3' y1='10' x2='21' y2='10'/></svg>");
  background-position: center;
  background-repeat: no-repeat;
}

/* ── Pagination ─────────────────────────────────── */
.pagination {
  display: flex; gap: 6px; flex-wrap: wrap; align-items: center; justify-content: center;
  padding-top: 8px;
}

/* ── User create + admin menu ───────────────────── */
.user-create {
  display: grid; gap: 12px;
  padding: 16px; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius);
}
.admin-menu {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  padding: 8px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.admin-view { display: flex; flex-direction: column; gap: 14px; }

/* ── Toolbar ────────────────────────────────────── */
.toolbar {
  display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
  padding: 10px 12px;
  background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius);
}
.toolbar-filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

/* ── Subcards (used inside settings) ────────────── */
.subcard {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
}
.service-check-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px;
}

/* ── Team / employees ───────────────────────────── */
.team-shell { display: grid; gap: 14px; }
#employeeEditorCard { display: flex; flex-direction: column; gap: 14px; }
.employee-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
  transition: border-color .18s, transform .12s;
}
.employee-card:hover { border-color: var(--line-strong); transform: translateY(-1px); }
.employee-top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.employee-name { font-size: 14px; font-weight: 600; color: var(--text); }
.employee-color {
  width: 14px; height: 14px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.20);
  flex-shrink: 0;
}
.employee-stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px;
}
.employee-stat {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 8px 10px;
  display: flex; flex-direction: column; gap: 2px;
}
.employee-stat strong { font-size: 1.05rem; font-family: var(--font-title); }
.employee-stat span { font-size: 11px; color: var(--soft); text-transform: uppercase; letter-spacing: 0.05em; }

/* ── Templates ──────────────────────────────────── */
.template-list { display: grid; gap: 10px; }
.message-template-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
}
.message-template-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.template-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; }

/* ── Template preview ───────────────────────────── */
.template-preview-shell { display: grid; gap: 10px; }
.template-preview-card {
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  padding: 14px 16px;
}
.template-preview-html { font-size: 13px; line-height: 1.55; color: var(--text-2); }

/* ── AI editor ──────────────────────────────────── */
.ai-editor-grid {
  display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 14px;
}
.ai-preview-card {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px;
  display: flex; flex-direction: column; gap: 12px;
}
.ai-widget-mock {
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  display: flex; flex-direction: column; gap: 10px;
}
.ai-widget-head { display: flex; align-items: center; gap: 10px; }
.ai-widget-avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  display: grid; place-items: center;
  font-family: var(--font-title); font-weight: 700; color: #061021;
}
.ai-widget-title { font-size: 13.5px; font-weight: 600; }
.ai-widget-bubble {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.55;
}
.ai-widget-footer { font-size: 11px; color: var(--soft-2); padding-top: 4px; border-top: 1px solid var(--line); }

.brain-textarea {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 12.5px;
  min-height: 220px;
  background: var(--bg-2);
}

/* ── Conversations ──────────────────────────────── */
.conversation-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 14px;
  min-height: 480px;
}
.conversation-toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.conversation-messages {
  display: flex; flex-direction: column; gap: 10px;
  max-height: 540px; overflow-y: auto;
  padding: 14px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
}
.conversation-messages > * { width: fit-content; max-width: 92%; }
.conversation-list { display: flex; flex-direction: column; gap: 6px; max-height: 540px; overflow-y: auto; padding: 4px; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius); }

.conversation-message {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 6px;
  max-width: 92%;
  word-break: break-word;
  overflow-wrap: anywhere;
}
.conversation-message[data-role="assistant"],
.conversation-message.assistant,
.conversation-message.from-bot {
  background: linear-gradient(135deg, rgba(0,209,255,0.10), rgba(0,245,212,0.06));
  border-color: var(--accent-line);
  color: var(--text);
  align-self: flex-start;
}
.conversation-message[data-role="user"],
.conversation-message.user,
.conversation-message.from-user {
  background: var(--surface-3);
  border-color: var(--line-strong);
  align-self: flex-end;
  color: var(--text);
}
.conversation-message[data-role="system"],
.conversation-message.system {
  background: var(--warn-soft);
  border-color: var(--warn-line);
  color: var(--warn);
  font-size: 12.5px;
  align-self: center;
  text-align: center;
}
.conversation-message strong, .conversation-message .role {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--soft);
  font-weight: 700;
}
.conversation-message[data-role="assistant"] strong,
.conversation-message.assistant strong { color: var(--accent); }
.conversation-item {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 4px;
  cursor: pointer;
  transition: background .15s, border-color .15s;
}
.conversation-item:hover { background: var(--surface); border-color: var(--line); }
.conversation-item.active { background: var(--accent-soft); border-color: var(--accent-line); }

.conversation-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.conversation-tag {
  display: inline-flex; padding: 2px 7px;
  background: var(--surface-3);
  border: 1px solid var(--line);
  border-radius: 5px;
  font-size: 10.5px;
  color: var(--text-2);
  font-weight: 600;
}

.conversation-detail { display: flex; flex-direction: column; gap: 12px; }
.conversation-message-body { font-size: 13.5px; color: var(--text); line-height: 1.55; white-space: pre-wrap; }

/* ── User cards ─────────────────────────────────── */
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
.user-title { display: grid; gap: 2px; min-width: 0; flex: 1; }
.user-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 12px; color: var(--soft); }
.action-row { display: flex; gap: 6px; flex-wrap: wrap; padding-top: 4px; }

/* ── Stack utility ──────────────────────────────── */
.stack { display: flex; flex-direction: column; gap: 12px; }

/* ── Contact / link / feedback ──────────────────── */
.contact-card {
  display: flex; flex-direction: column; gap: 8px;
  padding: 12px 14px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  font-size: 13px;
}
.link-btn {
  background: transparent;
  color: var(--accent);
  padding: 4px 0;
  font-size: 12.5px;
  font-weight: 600;
  border: none;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.link-btn:hover { color: var(--accent-2); transform: none; box-shadow: none; }

.support-note { font-size: 12px; color: var(--soft-2); }

.feedback-box {
  padding: 10px 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 12.5px;
  color: var(--text-2);
}
.feedback-box.success { background: var(--success-soft); color: var(--success); border-color: var(--success-line); }
.feedback-box.error   { background: var(--danger-soft); color: var(--danger); border-color: var(--danger-line); }
.feedback-box:empty { display: none; }

.helper-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* Simple table reset */
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
}
th, td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}
th {
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--soft);
  font-weight: 600;
  background: var(--surface-2);
}
tbody tr { transition: background .15s; }
tbody tr:hover { background: var(--surface-2); }

/* ── Skeleton loader (for any [data-loading]) ──── */
@keyframes skeleton {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
[data-loading="true"] {
  background: linear-gradient(90deg, var(--surface-2) 0%, var(--surface-3) 50%, var(--surface-2) 100%);
  background-size: 200% 100%;
  animation: skeleton 1.4s ease-in-out infinite;
  color: transparent !important;
  border-radius: 6px;
}

/* ── Modal overlays (if used) ───────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(3,7,15,0.74);
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
  max-width: min(560px, calc(100vw - 32px));
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: var(--shadow-lg);
  display: flex; flex-direction: column; gap: 14px;
}

/* ── Smooth transition on view changes ────────── */
.card.panel:not(.hidden), .card.block:not(.hidden) {
  animation: fadeUp .25s ease both;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Responsive ─────────────────────────────────── */
@media (max-width: 1180px) {
  :root { --side-w: 240px; }
  .conversation-layout { grid-template-columns: 1fr; }
  .ai-editor-grid { grid-template-columns: 1fr; }
}

@media (max-width: 960px) {
  .topbar { padding: 12px 16px; }
  .sidebar {
    position: fixed;
    top: 60px;
    left: 0;
    width: 280px;
    height: calc(100vh - 60px);
    z-index: 50;
    transform: translateX(-100%);
    transition: transform .25s ease;
  }
  .sidebar.is-open { transform: translateX(0); }
  .page { grid-template-columns: 1fr; }
  .main { grid-column: 1; padding: 18px 16px 56px; }
  .booking-top { flex-direction: column; align-items: stretch; }
  .booking-meta { grid-template-columns: 1fr 1fr; }
  .today-columns { grid-template-columns: 1fr; }
  .reschedule-grid { grid-template-columns: 1fr; }
  .calendar-grid { gap: 2px; }
  .calendar-day { padding: 4px 6px; min-height: 50px; }
  .calendar-event { font-size: 9.5px; padding: 1px 3px; }
  .day-agenda-item { grid-template-columns: 64px 1fr; }
  .day-agenda-actions { grid-column: 1 / -1; }
  .user-meta { grid-template-columns: 1fr; }
  .segmented { flex-wrap: wrap; }
  .admin-menu { padding: 6px; }
  .main { padding: 16px 12px 44px; }
}

@media (max-width: 560px) {
  body { font-size: 13.5px; }
  .booking-card, .day-agenda { padding: 14px; }
  h1 { font-size: 1.25rem; }
  h2 { font-size: 1.1rem; }
  .stat strong { font-size: 1.4rem; }
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
print(f"portal_ui/index.html actualizado: {INDEX.stat().st_size/1024:.1f} KB")
