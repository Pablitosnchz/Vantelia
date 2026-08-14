# Tenants en producción (app.vantelia.es)

Estado a 16-jul-2026. Fuente de verdad: `config.json` del VPS (`/srv/vantelia/config.json`).
El `config.json` local NO coincide con el de prod (el deploy nunca lo sobrescribe): antes de
asumir que un tenant existe, comprobarlo contra prod (`GET /central/{id}` o el propio JSON del VPS).

| Tenant | Qué es | Reglas |
| --- | --- | --- |
| `Vantelia` | Asistente de la propia web comercial (widget de vantelia.es, `data-client="Vantelia"`). Creado por alta-express el 16-jul-2026 con RAG de la web nueva. | NO borrar. Si cambian planes/precios en la web → `POST /admin/reindex/Vantelia`. |
| `van` | Tenant de demostración (masajes). Es la central embebida en la home (`/central/van?embed=1`) y el ejemplo enlazado desde la web. | NO borrar. Pueden entrar reservas de prueba de visitantes: son ruido esperado, limpiarlas de vez en cuando desde el panel. |
| `demo_*` (≈20) | Demos autogeneradas por `/demo/` (7 días de vida, registro en `storage/demo_tenants.json`). | Se autolimpian al expirar; no tocar a mano. |
| `alicia_rincon_estilistas` | **Alicia Rincón Estilistas** (peluquería colorista, Elche). Primer cliente real en piloto (ago-2026). La cuenta la creó ella misma el 11-ago (`aliciarinconweb@gmail.com`, owner); el 13-ago se migró ahí todo lo preparado y se borró el tenant provisional `aliciarincon`. Portal, central de reservas, widget y copia integrada de su web en `/site/aliciarincon/`. | NO borrar. **Su contraseña es suya**: para entrar al panel, impersonar desde el panel admin (Clientes → Acceder), nunca resetearla. Horario por día real (`weekly_hours`); si cambian servicios o textos → `POST /admin/reindex/alicia_rincon_estilistas`. La copia de su web lleva `noindex` y no debe publicarse en su dominio sin permiso. Provisioning idempotente: `scripts/seed_alicia_rincon.py`. |
| `caprocat` | **Hotel Cap Rocat** (Cala Blava, Mallorca). Lead entrante 13-ago-2026: quieren autorespuestas por palabra clave en WhatsApp, no un chatbot. Provisionado el 14-ago-2026 para que lo prueben: RAG de su web, 7 reglas por palabra clave activas (`keyword_rules.enabled=true`), 5 Q&A y cuenta de portal `reservas@caprocat.com` (owner, plan pro). Agenda y voz DESACTIVADAS a propósito. | Prueba: `/demo/caprocat`. Provisioning idempotente: `scripts/seed_caprocat.py`. WhatsApp **pendiente**: el system user de Meta no tiene ninguna WABA asignada (`me/assigned_whatsapp_business_accounts` = vacío), así que no hay número de pruebas usable; hay que asignar WABA + número al system user y poner el `phone_number_id` en `config['whatsapp']`. Si cambia su web → `POST /admin/reindex/caprocat`. |
| `thenook` | Prospect que no cerró (jul 2026). | ELIMINADO el 16-jul-2026 vía `DELETE /admin/clientes/thenook`. Restos locales (client_sites, data, scripts) borrados del repo el 13-ago-2026. |

## Trampa al fusionar `config.json` en prod (14-ago-2026)

Escribir el JSON a mano en el VPS **mientras la app vieja sigue viva** puede perder secciones:
el proceso en marcha reescribe `config.json` con SU whitelist (`clients.CONFIG_EXTRA_SECTIONS`)
y borra cualquier sección que su versión no conozca. Paso real: se fusionó `keyword_rules`
a las 08:54:39 y el contenedor antiguo reescribió el fichero 16 segundos después, sin esa clave.

Orden correcto: **primero desplegar el código** que conoce la sección nueva, y **después**
activarla por la API del portal (que persiste con el código nuevo y además la deja en memoria),
no editando el JSON a mano. Comprobarlo siempre tras el deploy.

## Backups (arreglado 16-jul-2026)

- Cron: `0 3 * * * bash /srv/vantelia/scripts/backup-nightly.sh` (el `bash` explícito es
  obligatorio: el deploy desde Windows pierde el bit de ejecución y el cron fallaba en
  silencio — así estuvo roto del 4-may al 16-jul).
- Local: `/srv/vantelia-backups/vantelia-*.tar.gz` (14 días). Incluye snapshot atómico de
  SQLite, `config.json`, `data/` y los índices RAG.
- Offsite: copia cifrada (AES-256, clave en `/root/.vantelia-backup.key` y copia en el
  `.env` local como `BACKUP_ENCRYPTION_KEY`) subida por FTP al hosting estático de
  Hostinger: `/domains/vantelia.es/backups_privados/vantelia-diaN.tar.gz.enc`
  (N = día de la semana, rotación 7 días; fuera de `public_html`, no accesible por web).
- Restore probado el 16-jul-2026: descarga FTP → `openssl enc -d -aes-256-cbc -pbkdf2` →
  untar → `PRAGMA integrity_check` ok (1.479 bookings).
- PENDIENTE del dueño: el email de aviso de fallo no sale — el buzón SMTP del VPS está
  "Disabled by user from hPanel". Reactivarlo en hPanel o el script no podrá avisar.

## Monitorización

`.github/workflows/uptime.yml`: cada ~15 min comprueba `GET /health` (status=ok), la web
pública (200) y la central embebida (200). Si falla, GitHub envía email al dueño del repo.
Lanzable a mano desde Actions → "Uptime Vantelia" → Run workflow.
