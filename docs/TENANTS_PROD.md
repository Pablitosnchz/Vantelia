# Tenants en producción (app.vantelia.es)

Estado a 16-jul-2026. Fuente de verdad: `config.json` del VPS (`/srv/vantelia/config.json`).
El `config.json` local NO coincide con el de prod (el deploy nunca lo sobrescribe): antes de
asumir que un tenant existe, comprobarlo contra prod (`GET /central/{id}` o el propio JSON del VPS).

| Tenant | Qué es | Reglas |
| --- | --- | --- |
| `Vantelia` | Asistente de la propia web comercial (widget de vantelia.es, `data-client="Vantelia"`). Creado por alta-express el 16-jul-2026 con RAG de la web nueva. | NO borrar. Si cambian planes/precios en la web → `POST /admin/reindex/Vantelia`. |
| `van` | Tenant de demostración (masajes). Es la central embebida en la home (`/central/van?embed=1`) y el ejemplo enlazado desde la web. | NO borrar. Pueden entrar reservas de prueba de visitantes: son ruido esperado, limpiarlas de vez en cuando desde el panel. |
| `demo_*` (≈20) | Demos autogeneradas por `/demo/` (7 días de vida, registro en `storage/demo_tenants.json`). | Se autolimpian al expirar; no tocar a mano. |
| `aliciarincon` | **Alicia Rincón Estilistas** (peluquería colorista, Elche). Primer cliente real en piloto (ago-2026). Portal, central de reservas, widget y copia integrada de su web en `/site/aliciarincon/`. | NO borrar. Horario por día real (`weekly_hours`); si cambian servicios o textos → `POST /admin/reindex/aliciarincon`. La copia de su web lleva `noindex` y no debe publicarse en su dominio sin permiso. |
| `thenook` | Prospect que no cerró (jul 2026). | ELIMINADO el 16-jul-2026 vía `DELETE /admin/clientes/thenook`. Restos locales (client_sites, data, scripts) borrados del repo el 13-ago-2026. |

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
