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


### Servicio retirado al confirmar

`test_servicio_retirado_al_confirmar.py` (entrega de Claude ee939c8, adaptada al
candidato integrado) comprueba retiro desde el portal, motivo distinguible del
hueco ocupado, excepción del mostrador, alternativas de voz y continuidad de
WhatsApp hasta elegir otro servicio. Los botones usan la identidad del resumen
enviado. Complementa `test_retirado_recorrido_real.py` (widget y reprogramación)
y los tests de confirmación/creación recuperable; no mide Meta ni modelo reales.

`test_estado_servicio_retirado.py` vigila que el estado no vuelva a pedir crear el
servicio rechazado, conserva contacto/fecha, respeta alternativas y citas ya
terminadas, y comprueba que el aviso de WhatsApp solo entra en historial tras envío.

`test_demo_conversion.py` usa una fixture de API de ámbito módulo: una fixture de
sesión puede quedar apuntando al backend anterior después de que otros módulos de
agenda lo reimporten. Reproducción del fallo de aislamiento: ejecutar primero
`test_demo_conversion.py::test_registry_keeps_two_different_email_demos_registered_concurrently`,
después `test_tres_fallos_de_la_demo.py::test_la_tool_no_devuelve_la_palabra_como_servicio`
y finalmente `test_demo_conversion.py`. Sin la fixture local fallaban tokens,
engagement y constructor de pre-generación; con ella los 23 casos pasan.

### Evidencia del banco sin ocultar intentos

`test_informe_banco.py` comprueba JSON opcional con ambos intentos completos,
primer intento medido/fallido y reintentos no medidos. No preparar la cita previa
es una precondición no medida; una conversación que falla sigue contada aunque
después no pueda prepararse el reintento. El destino se comprueba antes de tocar
la BD y los checkpoints atómicos conservan intentos ante interrupción o fallo de
reemplazo. La preparación real pasa por el núcleo con webhook y wrappers de
email/SMS interceptados. Estas pruebas no llaman al modelo ni acreditan que una
copia/configuración concreta coincida con producción.

### Cancelación y recordatorios pendientes

`test_cancelacion_whatsapp_confirmada.py` prueba ofrecer/aceptar/ejecutar con
identidad persistida, botón antiguo y cita cambiada, separación de crear/cancelar,
reinicio, CAS, resultado desconocido y fallo de envío. Menú, saludo y atención
humana no deben perder una operación aceptada pendiente ni entregarla a otro
recorrido. Precondición del núcleo probada con mutación; no acredita atomicidad
durante la red ni recuperación fuera del TTL.

Los recorridos de cancelación en `test_api_smoke.py` y `test_booking_exhaustive.py`
comprueban que código/botón de recordatorio solo ofrecen la propuesta: capturan
el ID real, mantienen la cita activa hasta aceptarlo y conservan los asserts de
cancelación y teléfono ajeno. La adaptación ca8e626 no sustituye el núcleo por un
mock ni elimina comprobaciones de efecto en la base de datos.

`test_recordatorio_omitido_y_fallido.py` prueba que omisión de email y fallo de
WhatsApp sin entrega aceptada no marcan enviado. Mantiene los casos totalmente
omitidos y las aceptaciones parciales sin reenvío. El caso de dos ejecutores
concurrentes ya es regresión normal en astra/entregas-recordatorios; conserva
su xfail histórico en el candidato 2235d25, cuya suite fue roja por cancelación.

`test_entregas_recordatorios.py` cubre generación monotónica al mover y devolver
una cita, aislamiento por tenant, reclamación con dos conexiones, actor perdido,
cancelación antes del envío y protección de la generación nueva durante I/O.
Comprueba también respaldo entre canales y recuperación de aceptación sin repetir.

`test_avisos_reintento_sin_duplicar.py` fija la decisión de Pablo del 14-sep-2026:
un fallo de email o SMS se reintenta en la siguiente vuelta y pasa al siguiente
canal; un WhatsApp dudoso o un envío colgado no se repiten por su canal, pero pasados
30 minutos (`notice_deliveries.GRACIA_AVISO_DUDOSO_MIN`) sale el siguiente. Frontera
29/31 min; dentro del plazo sigue bloqueando el respaldo. Tras la revisión de Codex
avanza el reloj de verdad (la banda del recordatorio), un ejecutor que vuelve tarde o
justo al límite no duplica, y sin intento previo no hay aviso tardío.

`test_reenvio_confirmacion_whatsapp_dudoso.py`: el botón «Enviar confirmación» del
panel con un WhatsApp dudoso (decisión de Pablo, «avisar y dejar reenviar»). El dudoso
se explica, el siguiente reenvío responde `WHATSAPP_SIN_CONFIRMAR` y solo reenvía con
`force`; también tras la confirmación de pago, con un reenvío solo por email en medio o
con una confirmación automática dudosa posterior a otra entrega.

`test_reprogramacion_whatsapp_confirmada.py`: fase 4, el flujo guiado de WhatsApp no
mueve la cita hasta aceptar el cambio concreto (botones con identidad, cita cambiada desde
el portal, hueco ocupado, reinicio, doble pulsación y resultado perdido). El agente
conversacional no cambia (decisión de Pablo del 14-sep-2026).

`test_vacaciones_son_dia_cerrado.py`: un bloqueo que deja sin horario a todos los que
trabajan ese día (vacaciones de día entero desde Horario) es un día CERRADO para
`voice._dia_cerrado`, `consultar_disponibilidad` y el freno `dijo_cerrado_estando_abierto`
(`agenda.motivo_de_cierre_del_dia`). Antes el asistente decía «ese día lo tengo completo».
Un bloqueo parcial, o las vacaciones de una sola profesional mientras otra trabaja, no cierran.

`test_agenda_por_pasos.py`: en la agenda un pack se pinta como sus pasos (encargo de Pablo del
15-sep-2026). Cada tramo de `gap_json` puede llevar su nombre (`paso`), la API del panel devuelve
`work_steps` con hora y nombre (los de la cita o, si es anterior, los del pack actual cuando tiene
los mismos pasos; nunca inventados), la agenda pinta un bloque por paso y la ficha del pack edita
y guarda los pasos. Reservar sigue siendo el pack entero. Con Node (se salta sin él) ejecuta las
funciones de pintado del panel: pasos cortos seguidos se juntan en un bloque en vez de taparse, y
la espera no tapa ninguna cita dibujada, tampoco las del filtro «Canceladas» (revisión de Codex).

`test_horario_no_depende_del_dia.py`: el caso del banco `horario-escrito-manda` exige el
horario de la SEMANA (`horario_semanal`): dos días de la semana, «todos los días» o «excepto
los domingos»; los días pegados a hoy/mañana no cuentan. Con «lunes» a secas pasaba los
domingos y suspendía los lunes. Incluye las reproducciones de la revisión de Astra.

`test_recordatorios_meta_ledger.py` recorre el builder real hasta un transporte
simulado, guarda IDs y resultado, y verifica aceptación/auditoría en una misma
transacción. Caída tras commit conserva el tope, sin reenvío ni evento duplicado;
el nombre auditado coincide con el payload. No acredita entrega real al teléfono,
reconciliación externa ni exclusión global del cupo entre citas distintas.

`test_whatsapp_resultado_transporte.py` cubre resultado tipado y contrato booleano,
POST único, respuestas ambiguas/5xx/timeout sin fallback y texto parcial con IDs
conservados. Cerrar el cliente no borra una aceptación ya recibida.

`test_formulario_confirmacion_compartida.py` verifica token tenant/teléfono,
replay, propuesta compartida, aceptación única y recuperación sin repetir
proveedor. Exige disponibilidad real antes del resumen y fija profesional/centro
para no reasignar tras aceptación; no prueba estabilidad de términos económicos
si cambia el catálogo entre oferta y click (bloque siguiente).

`test_acciones_del_arnes.py` mantiene texto libre como texto y exige acción
estructurada. `test_arnes_boton_crea_cita.py` recorre resumen/botón/núcleo/agenda
sin modelo ni POST real; verifica normalización del builder y cuarto botón
descartado. El arnés aún filtra propuestas obsoletas antes del producto: no
demuestra rechazo productivo de esos botones ni compatibilidad con baseline
anterior. Las fixtures de resumen heredadas consultan huecos sintéticos reales,
sin reemplazar los validadores por stubs.

`test_copia_segura_banco.py` impide que copiar o guardar el informe borre origen,
WAL o SHM mediante alias, distingue origen inexistente/desaparecido y conserva
datos WAL. La copia de solo lectura y la comprobación de aislamiento comparten
normalización, incluidas rutas con ~. Todo usa archivos temporales sintéticos.
