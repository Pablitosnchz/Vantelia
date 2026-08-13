# Alta de un cliente "llave en mano"

Playbook de lo que se hizo para el primer piloto real (Alicia Rincón Estilistas,
ago-2026) y que se repite tal cual con cualquier negocio nuevo: dejarle el
asistente, la agenda, el panel y una copia de su web con reservas dentro,
**listos para enseñar en una llamada**.

Caso de referencia: `alicia_rincon_estilistas` (ver `docs/TENANTS_PROD.md`).
Script de aprovisionamiento: `scripts/seed_alicia_rincon.py` (copiar y adaptar).

---

## 0. Datos que hacen falta

| Dato | De dónde sale |
| --- | --- |
| Web pública | La que da el cliente |
| Nombre comercial, dirección, teléfonos, email | De su web |
| Horario, día a día | De su web (**ojo: casi nunca es la misma franja todos los días**) |
| Servicios con duración y precio | De su web; si no publica precios, se queda "a consultar" |
| Equipo | De su web; si no publica nombres, plazas "Estilista 2…N" para que las renombre |
| Color de marca, logo/favicon | De su web |
| ¿Ya tiene cuenta creada? | `SELECT email, cliente_id FROM users WHERE email LIKE '%...%'` |

**Antes de nada, comprobar si el cliente ya se registró él mismo.** Si existe, se
migra todo a SU tenant y **no se toca su contraseña**: para entrar al panel se
impersona desde el panel admin (Clientes → Acceder).

---

## 1. Conocimiento (RAG)

1. Rastrear su web entera con Playwright (index + subpáginas), con scroll para
   disparar el lazy-load, y guardar el texto.
2. Escribir `data/<cliente_id>/info.txt` a mano con ese contenido. **No vale el
   scrape en crudo**: el fichero tiene un formato que el sistema parsea.
   - Sección `SERVICIOS Y PRECIOS:` con bloques numerados y líneas
     `- Precio:` / `- Duracion:` / `- Descripcion:` → de ahí se siembra el
     catálogo (`_extract_services_from_info`).
   - Secciones en MAYÚSCULAS terminadas en `:` para el resto (contacto, horario,
     quiénes son, preguntas frecuentes, tono).
   - "A consultar" como precio es válido y se muestra así.
3. Reindexar: `POST /admin/reindex/<cliente_id>` (**en el proceso vivo**, no por
   `docker exec`: el índice se cachea en memoria).

## 2. Tenant en `config.json`

Campos que importan:

- `nombre` y **`empresa` como STRING** (nombre comercial). Si se mete un dict, la
  central publica imprime el diccionario en el hero.
- `color` (su marca) y `accent_color`.
- `contacto.telefono` / `contacto.email`.
- `allowed_origins`: `app.vantelia.es`, `vantelia.es` y **su dominio real**.
- `booking`: `timezone`, `slot_minutes`, `day_start`/`day_end`, `closed_weekdays`
  y **`weekly_hours`** si abre distinto según el día.
- `voice`: `enabled` y `widget_enabled` (voz por el micro del widget, sin número
  de teléfono).
- `shop_public.hero_image_url` y `hero_tagline` para que la central lleve su foto.
- `logo_url`: avatar del asistente (ver paso 5).
- `prompt_extra`: dos o tres frases con el tono y las reglas del negocio.

Solo las secciones registradas en `clients.CONFIG_EXTRA_SECTIONS` sobreviven a un
guardado. Si se añade una nueva, registrarla ahí o desaparece.

## 3. Aprovisionamiento

Copiar `scripts/seed_alicia_rincon.py` y adaptar constantes. Hace, idempotente:

- Usuario del portal: si ya existe, solo se le confirma la propiedad del tenant y
  el plan; **nunca se le cambia la contraseña**.
- Centro con su dirección real.
- Equipo con el **horario por día** (`weekly_hours`) y la agenda general alineada.
- Catálogo sembrado desde `info.txt`.
- Preguntas frecuentes como pares Q&A (`rag._autocreate_qa_from_info` con
  `explicit_pairs`), para que el negocio las vea y las edite.
- Comercio de muestra: productos, bonos y una tarjeta regalo.
- Agenda de muestra (`--with-agenda`): cada profesional encadena citas dentro de
  SU horario, sin solapes, con mezcla de estados y **ocupación decreciente hacia
  el futuro**, para que queden huecos libres que enseñar en la llamada.
  Los precios de muestra se sellan **después** de guardar (`_store_booking`
  resuelve el importe desde el catálogo y pisaría el del record).

## 4. Su web, clonada e integrada

1. `python scripts/clone_public_site.py --base-url <web> --output-dir client_sites/<carpeta>`
2. Descargar lo que el clonador no se lleva: `media/*`, `assets/*.js`, tipografías
   (`.ttf`, `.woff2`). Comprobar 404 con el navegador, no a ojo.
3. Comprimir las imágenes grandes y poner `loading="lazy"` salvo logo y hero.
4. Inyectar en **todas** las páginas: `<meta name="robots" content="noindex,nofollow">`,
   el botón **RESERVAR** (enlace a `/central/<cliente_id>`) en la barra y en el hero,
   y el `<script>` del widget con `data-client="<cliente_id>"`.
5. Se sirve en `/site/<carpeta>/`. **Es una copia de trabajo**: decírselo al
   cliente y no publicarla en su dominio sin permiso.

## 5. Avatar del asistente

Su favicon suele ser un monograma cuadrado y es la mejor pieza. Componerlo en un
círculo blanco (el monograma suele ser negro y la cabecera del widget va con el
color de marca), guardarlo en `client_sites/<carpeta>/assets/` y ponerlo en
`logo_url`. Servido desde nuestro dominio, no enlazado al suyo.

---

## 6. Despliegue: qué viaja y qué no

| Ruta | Cómo llega a producción |
| --- | --- |
| `config.json` | **NO** lo sube el deploy (es volumen). Se fusiona a mano por SSH, con copia previa |
| `data/`, `storage/` | Volúmenes: no se sobrescriben |
| `client_sites/` | Volumen: basta `scp` del fichero |
| `backend/`, `scripts/`, `app_ui/` | Horneados en la imagen: `docker cp` para probar, `up -d --build` para que persista |

`scripts/` no es volumen: para lanzar un seeder nuevo hay que `docker cp` al
contenedor antes de ejecutarlo.

## 7. Verificación antes de enseñarlo

Nada de "debería funcionar": comprobarlo.

- `GET /health` y `GET /admin/email-health`.
- `GET /cliente/<id>`, `/servicios/<id>`, `/profesionales/<id>`.
- `/disponibilidad` **día a día de una semana**: que los días cerrados salgan
  vacíos y que el último hueco respete la duración del servicio más largo.
- Reserva real de punta a punta: que llegue el **email de confirmación**
  (`customer_email_status` en la BD) y que el enlace de gestión responda 200.
- Chat: cinco preguntas reales del negocio, incluida una que obligue a generar.
- Voz: `POST /voice/widget/<id>/session` y una tool (`consultar_disponibilidad`).
- Páginas de gestión y confirmación, **en móvil**: sin scroll lateral.
- Tiempo de carga de su web y cero 404 (con el navegador, no con curl).
- Panel impersonando: agenda, horarios, Q&A e informes.
- `python -m pytest`.

Borrar las citas de prueba al terminar.

---

## 8. Trampas conocidas (todas costaron un rato)

- **`empresa` como dict** → la central imprime el diccionario en el hero.
- **Horario por día**: sin `weekly_hours`, la agenda ofrece huecos que el negocio
  no tiene y el asistente cuenta un horario falso.
- **Micrófono**: `/site/...` lo sirve StaticFiles y necesita
  `Permissions-Policy: microphone=(self)`; si no, la voz muere con "no se pudo
  abrir el canal de audio".
- **Límite de OpenAI**: `gpt-realtime` va por su propio cupo (40.000 tokens/min en
  el escalón de entrada) y el prompt viaja ENTERO en cada turno. Un prompt gordo
  agota el cupo en cuatro turnos y las respuestas fallan **en silencio**.
- **Saldo de OpenAI**: sin crédito, la voz y el chat generativo se caen; las
  respuestas de Q&A siguen saliendo y disimulan el problema.
- **Precios inventados, nunca.** Si el negocio cotiza tras diagnóstico, "a
  consultar" es lo correcto; los importes de muestra van solo en el snapshot de
  las citas de demo, no en el catálogo público.
- **Fechas**: los días son LOCALES del negocio y `created_at` va en UTC. Comparar
  a pelo pierde ventas en las horas en que las dos fechas no coinciden.
