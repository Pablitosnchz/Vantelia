# Requisitos funcionales — Captación de clientes (email outbound)

Contrato de producto de la sección **Captación** del panel admin. Objetivo: máquina de
prospección B2B 100% autónoma que descubre empresas, las contacta por email en secuencia
multi-touch, detecta respuestas y las entrega al dueño sin intervención manual.

Estado de partida (auditoría 04-ago-2026): motor F3 funcional pero estrangulado por
tres bloqueos (SMTP caído, auto-pausa sin reanudación, discovery sin API key en VPS).
Métricas reales conseguidas: 36% open, 4.2% click, 1.7% reply, 2 clientes marcados.

## 1. Objetivo y criterio de éxito

- **RF-1.1** El sistema funciona 24/7 sin intervención: descubre → filtra → importa →
  envía cold → follow-ups → detecta reply → notifica al dueño.
- **RF-1.2** Criterio de éxito operativo: el dueño solo recibe notificaciones de
  respuestas de empresas interesadas y mira el dashboard <5 min/día.
- **RF-1.3** Ningún fallo transitorio (SMTP, Places, IMAP) detiene el sistema de forma
  permanente. Toda pausa automática tiene vencimiento y auto-reanudación.

## 2. Descubrimiento de prospects (discovery)

- **RF-2.1** Discovery GRATIS vía OpenStreetMap/Overpass (con mirrors y retry) por
  combos sector×ciudad + scraping de emails de las webs corporativas. Google Places
  queda RETIRADO por coste (decisión 04-ago-2026): `GOOGLE_PLACES_API_KEY` debe
  permanecer vacía y su ausencia NO es un blocker. Targets manuales del panel tienen
  prioridad; sin targets manuales, rotación automática de combos generados
  (España completa, ~18 por ronda).
- **RF-2.2** Un combo que devuelve 0 empresas importables en 2 rondas consecutivas se
  marca agotado y se excluye de la rotación (reactivable desde panel).
- **RF-2.3** Filtros de importación obligatorios: sin email → fuera; cadenas/franquicias
  conocidas → fuera; duplicados (email/dominio/teléfono normalizados) → fuera;
  suprimidos/bajas → fuera; score mínimo configurable (default 60).
- **RF-2.4** Si el pool de prospects `new` baja de 30, la ronda prioriza discovery
  sobre envío.
- **RF-2.5** Presupuesto por ronda: cap de resultados crudos y de scrapes de email
  configurables por env; coste estimado loggeado en el activity log.

## 3. Secuencia de contacto

- **RF-3.1** Etapas: `cold → fu1 → fu2 → breakup`. Máximo 4 toques por prospect, nunca
  más de un email por etapa.
- **RF-3.2** Separación entre etapas configurable; defaults sanos: fu1 +4d, fu2 +6d,
  breakup +8d. (Los 2/2/2 días detectados en prod son demasiado agresivos.)
- **RF-3.3** La secuencia se detiene inmediatamente y para siempre si el prospect:
  responde (`replied`), se da de baja (`baja`), rebota (`bounced`), o pasa a
  `client`/`lost`.
- **RF-3.4** Subjects con A/B testing estable por hash(email|stage); métricas por
  variante en `/admin/outreach/ab-stats`.
- **RF-3.5** Personalización mínima por email: nicho (hook de valor sectorial), ciudad
  y nombre del negocio. Ninguna variable puede renderizar vacía o con placeholder
  roto: validación pre-envío; si falla, se salta el envío y se loggea.

## 4. Envío y protección de reputación

- **RF-4.1** Espaciado entre emails de un mismo job: 120–300s con jitter (env
  `OUTREACH_SEND_SPACING_MIN/MAX_SEC`). Prohibidas las ráfagas.
- **RF-4.2** Warm-up progresivo tras cualquier parón >7 días: empieza en 10/día y sube
  +5/semana hasta el cap configurado (tope absoluto 30/día con SMTP compartido).
- **RF-4.3** Ventana laboral obligatoria en producción: L-V, 9–19h Europe/Madrid
  (`OUTREACH_RESPECT_WINDOW=true`, `OUTREACH_SKIP_WEEKEND=true`).
- **RF-4.4** Cap diario por dominio destinatario (default 3) para no bombardear una
  misma empresa.
- **RF-4.5** Rate limit SMTP del proveedor → pausa automática CON vencimiento (siguiente
  día laboral 9h), no pausa permanente. Tres días seguidos con rate limit → pausa 72h
  + aviso al dueño. La pausa manual desde panel sí es indefinida y se distingue de la
  automática (`paused_reason`, `paused_until`).
- **RF-4.6** Bounce rate >8% en los últimos 100 envíos → pausa automática 48h + aviso.
- **RF-4.7** Soporte de perfil SMTP dedicado para captación (env
  `OUTREACH_SMTP_HOST/PORT/USERNAME/PASSWORD`, fallback al SMTP global) para poder
  separar el cold del email transaccional del SaaS sin tocar código.

## 5. Respuestas y bounces (IMAP)

- **RF-5.1** Poller IMAP detecta replies por `In-Reply-To`/remitente conocido, marca
  `replied`, corta la secuencia y filtra autoresponders (out-of-office).
- **RF-5.2** Cada reply detectada genera notificación inmediata al dueño (email a
  `CONSULTA_NOTIFICATION_EMAIL`) con el texto de la respuesta y ficha del prospect.
  Si el SMTP está caído, la notificación se encola y reintenta.
- **RF-5.3** NDRs/bounces se detectan (mailer-daemon, delivery-status), el destinatario
  original se marca `bounced` y entra en supresiones.
- **RF-5.4** Emails con "BAJA" (o List-Unsubscribe) → supresión inmediata y permanente.

## 6. Autopilot (orquestación)

- **RF-6.1** Worker con tick horario (env `OUTREACH_AUTONOMOUS_TICK_MINUTES`). Cada
  tick: comprobar pausas/ventana → follow-ups → cold hasta cap → discovery si toca.
- **RF-6.2** Kill-switch dual: env `OUTREACH_AUTONOMOUS_ENABLED` (infra) + `enabled` en
  DB (operativo). Al arrancar el contenedor, una pausa automática ya vencida se
  reanuda sola.
- **RF-6.3** Todo lo que hace o salta una ronda queda en `autopilot_activity_log`
  (evento estructurado + detalle). El log es consultable desde el panel.
- **RF-6.4** Heartbeat: `last_tick` visible en panel; >2h sin tick = alerta roja.

## 7. Panel admin (sección Captación)

- **RF-7.1** Dashboard operable en <5 min/día: estado del autopilot (verde/rojo, motivo
  y vencimiento de pausa), funnel del mes, hot leads, replies sin atender, actividad
  reciente.
- **RF-7.2** Banner rojo si: check SMTP real falla, último tick >2h, o pausa automática
  activa.
- **RF-7.3** Widget "Replies sin atender" arriba del todo: respuestas IMAP no marcadas
  como gestionadas.
- **RF-7.4** Hot leads (abren/clican sin responder) con teléfono clicable y mailto:
  con plantilla precargada.
- **RF-7.5** El resto (prospects, campañas, plantillas, bajas, config avanzada) en
  sub-tabs; el dashboard no se sobrecarga.

## 8. Salud del email (transversal al SaaS)

- **RF-8.1** Check SMTP real (login+NOOP, sin enviar) expuesto en
  `GET /admin/email-health` y como check no bloqueante de `/health`. El `smtp_ok` del
  autopilot usa este check, no la mera presencia de config.
- **RF-8.2** El workflow de uptime (GitHub Actions) vigila `email-health` y falla si el
  SMTP lleva caído → email automático al dueño. (Incidente real: SMTP muerto semanas
  sin que nadie lo supiera.)
- **RF-8.3** Los leads de `POST /consulta` se persisten SIEMPRE en DB
  (`consulta_leads`) antes de intentar el email; visibles en el panel con aviso de
  pendientes. Un fallo de email nunca pierde un lead.

## 9. Compliance (no negociable)

- **RF-9.1** Footer legal LSSI/RGPD en todos los emails (razón social, finalidad,
  baja de un clic). `OUTREACH_LEGAL_FOOTER=true` en producción.
- **RF-9.2** Cabeceras `List-Unsubscribe` + `List-Unsubscribe-Post: One-Click`.
- **RF-9.3** Solo emails públicos de webs corporativas (interés legítimo). Sin listas
  compradas. Supresiones honradas en discovery, envío y autopilot.
- **RF-9.4** SPF + DKIM + DMARC correctos en el dominio remitente (verificado ok en
  `vantelia.es` a 04-ago-2026).

## 10. Métricas objetivo

| Métrica | Mínimo aceptable | Objetivo |
| --- | --- | --- |
| Open rate cold | >25% | >35% |
| Reply rate global | >1% | >3% |
| Bounce rate | <8% | <3% |
| Prospects nuevos/semana | >30 | >75 |
| Ticks fallidos/semana | 0 permanentes | 0 |

## 11. QA

- Unit: auto-reanudación por vencimiento, warm-up, espaciado (sleep mockeado),
  detección NDR, persistencia de `consulta_leads` con SMTP roto, pausa manual vs
  automática, filtros de importación.
- E2E dry-run del tick completo con SMTP y Places mockeados.
- Prohibido enviar emails reales en tests/desarrollo; smoke de producción solo al
  buzón del dueño con asunto de test explícito.
