# La suite: qué cubre cada fichero

48 ficheros, ~775 tests, unos 8-10 minutos enteros. Casi ninguno necesita red:
el entorno se monta aislado en un `tmp_path` con su propio `config.json`,
`storage/` y `data/`.

```powershell
python -m pytest                      # todo
python -m pytest tests/test_wa_*.py   # solo WhatsApp
python -m pytest -k senal             # por nombre
```

## Qué corro si toco...

| Toco... | Corro |
| --- | --- |
| Reservar / cancelar / reprogramar | `test_booking_exhaustive.py`, `test_reservas_multicanal_e2e.py`, `test_api_smoke.py` |
| Avisos al cliente (email, WhatsApp, SMS) | `test_avisos_cambio_cita.py`, `test_recordatorio_whatsapp_corto.py`, `test_wa_confirmacion_corta.py`, `test_nota_servicio.py` |
| Señal / pago de la cita | `test_senal_visible.py`, `test_senal_canales.py`, `test_aviso_pago_pendiente.py`, `test_confirmacion_tras_pago.py`, `test_bizum.py`, `test_ai_payment_link.py` |
| Horarios y disponibilidad | `test_booking_exhaustive.py`, `test_weekly_hours.py` |
| Catálogo de servicios | `test_catalogo_grande.py`, `test_importar_catalogo.py`, `test_guardar_ficha_no_borra_catalogo.py` |
| Cerebro del asistente (chat) | `test_api_smoke.py`, `test_qa_del_negocio.py`, `test_keyword_rules.py`, `test_chat_menu_y_formato_whatsapp.py`, `test_chat_sin_agenda.py` |
| WhatsApp | todos los `test_wa_*.py` + `test_inbox_takeover.py` |
| Voz | `test_voice_engine.py`, `test_voz_widget_limites.py` |
| Comercio (bonos, tarjetas, tienda, POS) | `test_bonos_gift_journey.py`, `test_shop_public.py`, `test_pos_charge.py` |
| Widget web | `test_widget_reserva.py` |
| Portal, roles y sesión | `test_sesion_deslizante.py`, `test_client_channels.py`, `test_admin_edge_cases_e2e.py` |
| CRM | `test_crm_light.py` |
| Captación (outreach / demos) | `test_captacion_autonoma.py`, `test_outreach_*.py`, `test_demo_conversion.py` |
| Cualquier cosa en `backend/` | `test_shim_compat.py` (el proxy de `api.py`) |

## Tests que vigilan reglas, no funcionalidad

Existen para que no se repita un error concreto. Si uno falla, lee su docstring
antes de "arreglarlo": suele estar diciendo algo cierto.

- `test_patrones_sin_tilde.py` — el texto al cliente lleva tildes; los patrones
  que casan lo que el cliente ESCRIBE, no (se comparan ya normalizados). También
  vigila que no reaparezca texto con doble codificación UTF-8.
- `test_modulos_documentados.py` — los módulos de más de 600 líneas llevan
  índice en su docstring.
- `test_shim_compat.py` — `api.simbolo` sigue reenviando al módulo real.
- `test_guardar_ficha_no_borra_catalogo.py` — guardar la ficha admin no puede
  desactivar servicios (pasó de verdad: 183 → 8).
- `test_mapa_del_codigo_no_miente.py` — lo que citan `docs/MAPA_DEL_CODIGO.md`,
  este README, `CLAUDE.md` y los docstrings de módulo existe de verdad, y
  `docs/ARQUITECTURA.md` nombra todos los módulos de `backend/`.

## Fixtures

En `conftest.py`: `vantelia_env_factory` (entorno aislado), `api_module` (la app
importada con ese entorno) y `client` (TestClient). Los ficheros antiguos
definen su propio `api_module` local, que pytest prioriza; **los nuevos deben
importar el compartido** en vez de duplicar el bloque de entorno:

```python
from test_booking_exhaustive import api_module, client  # noqa: F401
```

Ojo: local corre **Python 3.8** (sin walrus en tests async, sin `dict | dict`);
el contenedor de producción es 3.11.

## Cosas que la suite NO cubre

- Envíos reales (email, WhatsApp, SMS, Stripe): siempre con dobles.
- Twilio call-control y la voz por teléfono de punta a punta: los QA de
  `scripts/qa_voice_realtime_*.py` gastan cuota y van aparte.
- El panel como tal: para eso está `python scripts/qa_e2e.py`, que recorre el
  portal entero en un entorno aislado y sale con 1 si hay bugs.
