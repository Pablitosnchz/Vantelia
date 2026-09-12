# La suite: qué cubre cada fichero

102 ficheros, ~1580 tests, unos 8-10 minutos enteros. Casi ninguno necesita red:
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
| Catálogo de servicios | `test_catalogo_grande.py`, `test_importar_catalogo.py`, `test_guardar_ficha_no_borra_catalogo.py`, `test_cambios_del_panel_se_ven_al_momento.py` |
| Cerebro del asistente (chat) | `test_api_smoke.py`, `test_qa_del_negocio.py`, `test_keyword_rules.py`, `test_intenciones_y_reglas.py`, `test_comprension_en_el_chat.py`, `test_reglas_en_el_portal.py`, `test_chat_menu_y_formato_whatsapp.py`, `test_chat_sin_agenda.py`, `test_menu_y_titulos.py`, `test_cambios_del_panel_se_ven_al_momento.py` |
| Usuario que no sigue el guion | `test_wa_usuario_erratico.py` — nadie puede quedarse encerrado en un paso |
| Menú de opciones (chat + WhatsApp) | `test_menu_y_titulos.py`, `test_wa_menu_starters.py` — el menú es lo que el negocio configura, igual en los dos canales |
| WhatsApp | todos los `test_wa_*.py` + `test_inbox_takeover.py` |
| Voz | `test_voice_engine.py`, `test_voz_widget_limites.py` |
| Comercio (bonos, tarjetas, tienda, POS) | `test_bonos_gift_journey.py`, `test_shop_public.py`, `test_pos_charge.py` |
| Widget web | `test_widget_reserva.py` |
| Portal, roles y sesión | `test_sesion_deslizante.py`, `test_client_channels.py`, `test_admin_edge_cases_e2e.py` |
| CRM | `test_crm_light.py` |
| Captación (outreach / demos) | `test_captacion_autonoma.py`, `test_outreach_*.py`, `test_demo_conversion.py` |
| Sincronía entre agentes (`scripts/sincronia.py`, página /sincronia) | `test_sincronia.py` — sobre repos git de verdad en `tmp_path` |
| Cualquier cosa en `backend/` | `test_shim_compat.py` (el proxy de `api.py`) |

## Tests que vigilan reglas, no funcionalidad

Existen para que no se repita un error concreto. Si uno falla, lee su docstring
antes de "arreglarlo": suele estar diciendo algo cierto.

- `test_no_hay_nombres_sin_definir.py` — dos cosas que compilan y no funcionan.
  (1) Un nombre usado sin importar: `agent.responder` llamaba a `booking.…` sin
  tener `booking` importado, así que el freno que impide soltar la duración sin
  que la pidan reventaba justo en el caso que venía a arreglar, y llegó así a
  producción. (2) Un `` de regex que perdió el prefijo `r` y quedó como el byte
  de retroceso: compila, `pyflakes` calla, y el freno no salta nunca. Pasó cuatro
  veces en una noche.
- `test_los_tests_no_mandan_emails.py` — la suite no habla con el buzón real.
  Pasó de verdad (ago-2026): `pytest` cargaba el `.env` de producción y las
  confirmaciones de cita salían por `smtp.hostinger.com` a `@test.es` y
  `@example.com`; los rebotes duros suspendían el envío de `info@vantelia.es`.
  El cortafuegos está en `conftest.py` (se aplica al importarlo).
- `test_cambios_del_panel_se_ven_al_momento.py` — lo que el negocio guarda en el
  panel manda en la consulta SIGUIENTE. `intents` cachea por tenant las familias
  del catálogo, las preguntas del negocio y la clasificación de cada mensaje (que
  se lleva dentro la RESPUESTA de la Q&A reconocida): todo eso lleva el sello del
  tenant (`intents.sellos_del_tenant`, derivado de la BD, así que también se
  entera el worker que no recibió el POST). Si este falla, se está contestando
  con una Q&A borrada o se ofrece un servicio retirado. Incluye la prueba del
  instrumento: con el sello congelado el fallo reaparece.
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
- `test_comprension_en_el_chat.py` — el ORDEN de las capas del chat es la lógica
  del asistente: lo que el negocio escribe a mano (palabras clave, Q&A literales)
  va antes que la comprensión por modelo, y con una gestión de cita a medias no
  se clasifica nada. Si este falla, alguien movió una capa de sitio.
- `test_situaciones_de_negocio.py` — las condiciones de un cliente son plantillas,
  no código por cliente. Incluye una clínica dental con normas propias: si eso
  falla, el asistente ha dejado de servir para negocios que no sean peluquerías.
- `test_como_una_clienta_de_verdad.py` — fallos que solo salen escribiendo con
  faltas, partiendo frases e insistiendo. El guion feliz no los ve.
- `test_condiciones_del_salon.py` — las condiciones que el cliente piloto fue
  pidiendo por WhatsApp, una por una. Son el contrato con SU clienta: si una
  deja de cumplirse hay que enterarse aquí, no en su salón.
- `test_elegir_servicio.py` — elegir el servicio es del CÓDIGO, no del modelo:
  con los mismos datos, la misma decisión siempre. Si este falla, alguien le ha
  devuelto la decisión al modelo y volverá la variación entre ejecuciones.
- `test_agente_de_citas.py` — el modelo lleva la conversación, pero las tools no
  le dejan inventarse un servicio, un hueco ni una cita.
- `test_cambiar_de_idea_ya_reservada.py` — cambiar de idea con la cita cogida no
  deja mentiras ni citas de sobra. La tool `reprogramar_cita` no aceptaba
  `servicio`, asi que el agente no podia cambiarlo: o cogia una segunda cita o
  decia que lo habia cambiado sin hacerlo. Fija ademas que no se le confirme una
  hora distinta de la que tiene, y que ofrecer huecos NO cuente como confirmar.
- `test_digresiones.py` — una pregunta de verdad a media reserva se contesta con
  lo que el negocio tiene escrito, y se sigue. La dueña del salón preguntó por la
  lactancia eligiendo alisado y recibió "consulta con tu médico" teniendo escrito
  que su Ácido Láctico Bio Premium es apto. Fija además que pedir cita NO es una
  digresión: meter texto del negocio en un turno de reserva la descarrila.
- `test_no_elige_por_ella.py` — con "no sé, ni idea de qué largo tengo" no se le
  elige el tratamiento. Incluye los DOS formatos de nombre del catálogo (con
  guion y con espacio): comparando el nombre entero, el freno no saltaba con la
  mitad del catálogo.
- `test_tres_fallos_de_la_demo.py` — los tres de la demo del 8-sep-2026, en una
  sola conversación: una palabra suelta ("mañana", "a las 10") tomada por el
  nombre de un servicio; el "sí" al diagnóstico que no contaba porque solo valía
  escribir la palabra; y la técnica elegida por ella, que **la pedía nuestra
  propia nota anti‑repetición** ("mójate y recomiéndale UNA"). Vigila también que
  no haya TERCERA pregunta: dicho dos veces que no sabe, se le coge la
  valoración. REGLA: un freno nuevo tiene que decir qué hace cuando el negocio ya
  ha dicho lo contrario.
- `test_abandono_suave.py` — quien dice que lo deja se va sin que le insistan.
  Mira SOLO el último mensaje: con el texto acumulado, quien volvía ("va, sí que
  quiero") seguía recibiendo la despedida para siempre.
- `test_queja_no_se_vende.py` — a quien se queja de un trabajo mal hecho no se le
  ofrece otro tratamiento.
- `test_dos_personas_dos_huecos.py` — "cita para mí y para mi madre" no cabe en un
  hueco. Avisa una vez y luego las coge de una en una: bloquear siempre la dejaba
  sin ninguna cita.
- `test_no_le_repite_su_muletilla.py` — a "hola?" no se le contesta "no tengo un
  servicio llamado 'hola'". Se pidió primero en el mensaje de la tool y no cambió
  nada: por eso el freno está en el código.
- `test_pedir_persona_gana_siempre.py` — pedir hablar con una persona funciona
  también a media reserva. El traspaso vivía dentro del bloque que solo corre sin
  flujo activo.
- `test_freno_del_precio_antes_de_hablar.py` — si la cita se va a parar, el agente
  no habla primero. Salían dos mensajes contradictorios en el mismo turno.
- `test_varios_servicios_una_cita.py` — una cita no puede apartar MENOS tiempo del
  que hace falta. Nació de una cita de 20 minutos para cuatro servicios (corte +
  secado + elumen + alisado) en la agenda de un salón real. Vigila las tres
  formas: reservar uno habiendo pedido varios, bajar a la variante corta de lo que
  se pidió por su nombre largo, y decir una duración que no está en el catálogo.
  La duración se lee con el MISMO resolutor que aparta el hueco, y si el negocio
  trabaja por packs es la del pack.
- `test_precio_oculto_no_pregunta_el_largo.py` — dos instrucciones del código no
  pueden contradecirse en el mismo turno. Un salón que no da precios acababa
  preguntando el largo del pelo como paso previo a decir una cifra que no debe
  decir, porque la nota del catálogo invitaba a darla y ganaba por ir después.
- `test_rollback_conserva_los_datos.py` — la vuelta atrás del VPS revierte el
  CÓDIGO y NUNCA los datos. La primera versión del script movía el estado vivo
  antes de intercambiar los árboles y un `mv` fallido dejaba la base de datos
  fuera de producción: la red de seguridad empeorando el incidente.
- `test_entorno_de_pruebas_aislado.py` — pruebas y producción comparten VPS, así
  que el peligro es un descuido: copiar el `.env` "para que arranque". El deploy
  de pruebas se niega si no tiene `.env` propio, si lleva una clave `sk_live_` o
  si usa el mismo token de WhatsApp que producción. Se ejecuta el MISMO script
  que se sube al servidor, extraído de `deploy/deploy.ps1`.
- `test_whatsapp_mismo_cerebro.py` — WhatsApp tiene recorrido PROPIO y solo
  delegaba en el cerebro al final: que algo funcione en el widget no demuestra
  nada allí. Compara los dos canales con el webhook de verdad. Si este falla,
  una configuración del negocio está comportándose distinto según dónde escriba
  el cliente.

## Fixtures

En `conftest.py`: `vantelia_env_factory` (entorno aislado), `api_module` (la app
importada con ese entorno) y `client` (TestClient). Los ficheros antiguos
definen su propio `api_module` local, que pytest prioriza; **los nuevos deben
importar el compartido** en vez de duplicar el bloque de entorno:

```python
from test_booking_exhaustive import api_module, client  # noqa: F401
```

`conftest.py` además **corta la salida al mundo real al importarse**: vacía las
credenciales de envío del entorno (SMTP, IMAP, Twilio, WhatsApp, OpenAI; Stripe
solo si es `sk_live_`) y bloquea `smtplib`/`imaplib`. Se pone `""` en vez de
borrar la clave porque `load_dotenv` solo rellena lo ausente. Un test que
necesite credenciales de mentira las pone en su `env_overrides` y hace
monkeypatch del envío.

Ojo: local corre **Python 3.8** (sin walrus en tests async, sin `dict | dict`);
el contenedor de producción es 3.11.

## Cosas que la suite NO cubre

- Envíos reales (email, WhatsApp, SMS, Stripe): siempre con dobles.
- Twilio call-control y la voz por teléfono de punta a punta: los QA de
  `scripts/qa_voice_realtime_*.py` gastan cuota y van aparte.
- El panel como tal: para eso está `python scripts/qa_e2e.py`, que recorre el
  portal entero en un entorno aislado y sale con 1 si hay bugs.
