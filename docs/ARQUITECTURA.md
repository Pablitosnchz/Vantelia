# Arquitectura del backend de Vantelia

Resultado del refactor `refactor/estable-v1` (junio 2026): el monolito
`api.py` (33.170 líneas) se dividió en un paquete `backend/` por dominios y
`backend/routers/` por secciones de endpoints, manteniendo idéntico el
comportamiento observable (misma tabla de rutas, mismos contratos, mismo
esquema SQLite, mismo snippet de widget).

> **¿Este documento o el otro?** Aquí está **cómo está organizado** el proyecto
> (capas, módulos, convenciones, dónde crear cosas nuevas). Si lo que quieres es
> **cambiar algo concreto** —un mensaje al cliente, el flujo de reserva, un
> cobro— abre antes [`MAPA_DEL_CODIGO.md`](MAPA_DEL_CODIGO.md), que va por
> flujos y avisa de las trampas conocidas.

## Capas (la dependencia solo apunta hacia abajo)

```text
api.py                      Shim de compatibilidad (~150 líneas). uvicorn api:app.
└─ backend/main.py          Crea la app FastAPI, middlewares, mounts, eventos
   │                        startup/shutdown e importa los routers EN ORDEN.
   ├─ backend/routers/      19 módulos de endpoints (decoran app directamente).
   ├─ Dominios de negocio   chat, whatsapp, booking, demo_agenda, voice,
   │                        onboarding, billing, portal, crm, growth,
   │                        outreach, instagram, tiktok
   ├─ Servicios             agenda, rag, security, emailing, messaging,
   │                        stripe_gateway, clients
   ├─ Infraestructura       db (esquema SQLite + conexión), appstate (estado
   │                        mutable + locks), timeutils, textnorm
   └─ backend/settings.py   Env vars, rutas, planes (lee .env al importar)
```

`api_models.py` (Pydantic) y `onboarding_utils.py` quedan en la raíz como
módulos transversales.

## Mapa de módulos

| Módulo | Contenido |
| --- | --- |
| `backend/settings.py` | Constantes de entorno, rutas, logger, planes self-serve, plantillas por defecto. Se relee al reimportar `api` (las fixtures de tests dependen de ello). |
| `backend/appstate.py` | Estado mutable compartido: `CONFIG_CLIENTES`, `sesiones`, `indices` RAG, `whatsapp_flows`, `rate_limit_buckets`, `state_lock`, threads/stops de workers. Módulo hoja (solo stdlib). Se llama `appstate` porque `state` colisiona con locals del flujo OAuth. |
| `backend/timeutils.py` | `_utc_now` (punto único de "ahora": los tests lo parchean para time-travel), conversiones ISO/UTC. |
| `backend/textnorm.py` | Normalización de textos/orígenes/URLs/horarios/fechas-ES, parsers de precio y duración, extractores de email/teléfono/fecha. |
| `backend/db.py` | `_init_database` (~65 tablas + migraciones; el mapa de qué guarda cada una está en su docstring), `_get_db_connection` (Row + timeout), helpers `db_*` de clientes/suscripciones. Las DBs de captación (outreach/IG/TikTok/WA) viven en sus dominios. |
| `backend/atencion.py` | Autoridad persistida de atención por tenant en `client_attention_state`: lectura sin caché, transición activa/pausada por versión y auditoría atómica en `client_channel_audit`. Ausencia de fila significa activa v0; error o corrupción nunca dan permiso. Esta fase aún no conecta canales ni facturación y no expone escritor HTTP. |
| `backend/atencion_operaciones.py` | Tickets por evento y diario común `client_attention_operations`, con tipo explícito envío/reserva y transacción compartida con la autoridad CAS. Envíos: ticket/canal/fragmento. Reservas: tenant/acción/clave estable de intento, también entre tickets. Solo el ganador ejecuta; la consulta conserva evidencia sin conceder permiso ni recuperar owners perdidos. Guarda huellas y referencia técnica de reserva, no datos personales; no sustituye `notice_deliveries` ni decide reintentos. La migración de la fase 2a copia y retira `client_attention_sends` atómicamente; requiere reinicio coordinado, sin convivencia de workers con ambos esquemas. |
| `backend/atencion_contexto.py` | Scope interno inmutable por tenant/ticket/intento, restaurado en `finally` y propagable por `_to_thread`. Crear/cancelar/mover admiten antes de claims, liberaciones y proveedores. Evidencia conocida se registra al persistir, antes de auxiliares; un fallo posterior del diario queda conservador y no interrumpe al ganador. `AtencionDetenida` atraviesa wrappers, dispatch y agente como control terminal. `/chat` instala el scope; ausencia de scope conserva el recorrido previo, incluido portal manual, y no acredita cobertura de otros capturadores. Ningún flag de source/modelo/HTTP concede excepción. |
| `backend/atencion_chat.py` | Captura ticket de `/chat` antes de esperar sesión, con vigencia técnica explícita de 120 s; revalida antes de cuota/preparación. Comprueba propiedad de sesión al persistir y conserva inbound. Motor RAG efímero construido del historial persistido, sin restaurar memoria compartida. Middleware ASGI admite antes de primer `send`; historial assistant y `bot_reply` solo tras emitir el cuerpo completo. Acredita emisión del servidor, no lectura del navegador. UUID por petición: sin identidad estable del cliente no promete deduplicar peticiones distintas. Supresión 409 `ATTENTION_STOPPED`; autoridad ausente/no verificable 503 `ATTENTION_UNAVAILABLE`. |
| `backend/atencion_salidas.py` | Admisión del diario común inmediatamente antes de transportes SMTP/Gmail/SMS/Meta bajo contexto interno, con destinatario y contenido efectivos en huella. Gmail verifica antes de preparar/refrescar OAuth y admite la entrega después, con el token obtenido; refrescar solo no abre un asiento de envío. SMTP admite la sesión antes de abrir socket y esa sesión ganadora puede terminar. Una mutación ganadora no concede permiso a su aviso: su corte terminal transporta `operacion_conocida` con tipo/estado/ref de la reserva persistida, separado del estado del envío. Timeout/desconocido detiene fallback; aceptación conocida no se pierde por cierre/auditoría posterior. Sin contexto conserva legacy; no es excepción humana ni cubre aún los capturadores de WhatsApp/voz/workers. |
| `backend/atencion_canal.py` | Lo que comparten las fronteras de canal: una sola forma de preguntar a la autoridad y capturar el ticket. `puede_atender` es la foto barata previa -no autoriza, solo evita gastar en un audio, una llamada o el modelo- y `turno` instala el contexto con su vigencia, fijada por politica de cada adaptador y nunca deducida de las ventanas del proveedor. Si el estado no se puede verificar, no se atiende. |
| `backend/atencion_whatsapp.py` | Frontera de entrada de WhatsApp (vigencia 300 s). Con el negocio ya resuelto -incluido el del numero de demo- y antes de procesar nada, corta preparar respuesta, bajar y transcribir audios, el formulario de reserva y cualquier efecto de cita. No toca la verificacion del webhook, los estados de entrega, los ecos del equipo desde su movil ni el 200 a Meta: un error haria que Meta reintentara el mismo mensaje sin que el negocio pueda pararlo. Lo que escribe la clienta se guarda igual para el panel. |
| `backend/atencion_voz.py` | Frontera de voz (vigencia 300 s). La IA no sostiene conversaciones con la atencion pausada, la arranque quien la arranque: telefono entrante (locucion de no disponible, sin Stream), puente revalidado al conectar antes de abrir -y pagar- la sesion de Realtime, llamada ya en curso con un turno por herramienta (no toca la agenda y se cierra con la despedida; `finalizar_llamada` y `transferir_a_humano` exentas), voz del widget sin acuñar sesion y con turno en cada tool real, y llamadas salientes tampoco desde el boton del panel, que recibe el motivo. No toca el status callback de Twilio ni el registro de la transcripcion al colgar. |
| `backend/atencion_avisos.py` | Frontera del worker de avisos: recordatorios 24 h/2 h, peticiones de resena, rebooking por IA y avisos de caducidad/recompra. Dos momentos con consecuencias distintas: pausa ANTES de empezar un aviso (`hay_atencion`) = no se intenta ni se anota nada, y sale al reactivar si todavia toca; pausa DURANTE el envio (`turno_aviso`, solo recordatorios de cita) = cada fragmento se admite antes del transporte, lo que falta se frena y el aviso queda `omitido/atencion_suprimida`, terminal. El turno es de CADA aviso, no del bucle ni de la llamada que va detras; la identidad del aviso (negocio, cita, generacion, tipo; `atencion_salidas.aviso_reserva_atencion`) evita que otra pasada con otro ticket repita un envio dudoso. Vigencia 900 s a proposito: un ticket vencido cuenta como supresion, y con turno la supresion es terminal, asi que una vigencia corta mataria recordatorios lentos con la etiqueta de una pausa que no hubo. Resenas, rebooking y caducidades siguen solo con la puerta previa. No cubre lo que el equipo manda a mano ni la tarjeta regalo ya pagada. |
| `backend/atencion_panel.py` | La pausa vista por una persona: lista cerrada de motivos (la autoridad exige codigo tecnico y rechaza texto libre), que se para y que sigue igual. Esas listas son la promesa que hace el interruptor y tienen que corresponderse con las fronteras que hay puestas, no con las que nos gustarian. No toca el plan ni los cobros -pausar dos semanas por obras no puede parecerse a darse de baja- y no programa pausas futuras. Endpoints `GET/PUT /auth/app/attention` (permiso `channels.manage`; 409 `ATTENTION_STALE` si otro lo cambio, 503 si no se puede verificar) y lectura administrativa `GET /admin/attention`, que solo lista quien no esta activo. |
| `backend/clients.py` | Config multi-tenant: carga/normaliza/serializa `config.json`, validación runtime, sync con la tabla `clientes`, persistencia, planes (`_plan_limits`). Cargar este módulo puebla `appstate.CONFIG_CLIENTES`. |
| `backend/security.py` | Usuarios, sesiones del portal, cookies, impersonación, tokens de reset, OAuth states, Fernet de canal, guards `Depends` (`_require_*`), rate limit. |
| `backend/emailing.py` | SMTP Vantelia + Gmail OAuth por cliente (`_send_client_email`), emails transaccionales, estados del canal Gmail. |
| `backend/messaging.py` | Primitivas Twilio SMS y WhatsApp Cloud API (`_send_whatsapp_*`), validación de firma Twilio. |
| `backend/stripe_gateway.py` | Único módulo que importa el SDK `stripe` (los tests lo parchean con fakes vía el proxy), precios por plan, Connect v2. |
| `backend/agenda.py` | Empleados, servicios (seed desde info.txt), horarios, bloqueos y el motor de disponibilidad por intervalos. |
| `backend/rag.py` | llama-index por cliente, info.txt IO, prompt de sistema, Q&A, sesiones/mensajes de chat, NLU de disponibilidad. |
| `backend/crm.py` | CRM ligero: contactos unificados, normalización, auditoría, leads. |
| `backend/booking.py` | Ciclo de vida de citas completo + pagos de cita (políticas, checkout Connect, webhooks, enlace de pago por IA) + worker de recordatorios. |
| `backend/notice_deliveries.py` | Reclamación duradera de recordatorios automáticos por tenant, cita, generación, tipo y canal. Confirma la reclamación antes del envío, conserva aceptación/IDs y bloquea reenvío o respaldo ante resultado incierto. Bajo contexto de atención, una supresión acreditada antes del POST cierra por owner como `omitido/atencion_suprimida` y detiene el aviso completo también tras reactivar, sin marcar sent/completo ni probar otro canal. Aceptación parcial e incertidumbre del proveedor permanecen distintas. Aceptación y auditoría de plantilla se guardan juntas; no acredita entrega a la clienta ni reconcilia resultados desconocidos. |
| `backend/demo_agenda.py` | Tenants demo con TTL, página demo, seed/purga de agenda de ejemplo. |
| `backend/chat.py` | `_process_chat_message`: orquestador del chat multi-canal. |
| `backend/whatsapp.py` | Webhook Cloud API y flujo conversacional de agendado. (`api.whatsapp_flows` sigue siendo el dict de estado de appstate.) |
| `backend/onboarding.py` | Provisioning self-serve de clientes. |
| `backend/billing.py` | Suscripciones: checkout, sync Stripe, planes públicos. |
| `backend/portal.py` | Payloads/serialización del panel admin y portal, stats, analytics. |
| `backend/outreach.py`, `instagram.py`, `tiktok.py` | Captación B2B (los try/except de imports de `scripts/` viven aquí; flags `*_AVAILABLE`). `wa_capture.py` se retiró el 9-sep-2026 con el resto de la automatización de productos de Meta. |
| `backend/voice.py` | Voz sobre OpenAI Realtime, por teléfono (Twilio) y por navegador (WebRTC): instrucciones, tools de cita y su despacho, OTP, llamadas salientes, cierre y etiquetado. |
| `backend/growth.py` | Plan de escala (métricas growth_*). |
| `backend/commerce.py` | Productos, bonos y tarjetas regalo + las páginas públicas del negocio (`/central`, `/tienda`, `/gift`, wallets). Nada se materializa al crear el checkout: lo hacen los `_finalize_*_payment` desde el webhook. |
| `backend/paystate.py` | Estado de cobro de una cita. **Fuente única**: suma `booking_payments` (la reserva) y `customer_payments` con `kind='pos'` (el mostrador). Mirar solo uno hace que el saldo mienta. |
| `backend/analytics.py` | Informes del portal: KPIs con delta, series, desgloses y el resumen de mostrador. |
| `backend/keywords.py` | Respuestas deterministas por palabra clave, opt-in por tenant. Va ANTES que las Q&A y que la IA. |
| `backend/intents.py` | Qué quiere el cliente: clasifica el mensaje con el modelo (atajo local gratis primero) y reconoce cuál de las Q&A del negocio le están haciendo, aunque lo escriba con otras palabras. Opt-in `config['ai_intents']`. |
| `backend/playbooks.py` | Situaciones tipicas de un negocio como PLANTILLAS (no dar precio sin ver, pedir foto, derivar a valoracion, pasar a una persona...). El negocio las activa desde el portal y se convierten en filas de `business_rules`: se acabo el script por cliente. |
| `backend/catalog_pick.py` | Elegir el servicio que pide el cliente mirando el catálogo real: filtra por familia, técnica, largo, para quién y edad, y dice qué falta por preguntar. Determinista y testeable: el modelo no decide aquí. |
| `backend/apuntes.py` | Lo que se escribe a mano encima del cuadro de la agenda («Carmen Calvo, pack mechas corto»), traducido a nombre + servicio del catálogo. La coma parte el apunte y el servicio lo decide `catalog_pick`, sin modelo. Si no está claro NO elige: devuelve las opciones reales con su duración para tocar una. |
| `backend/reserva.py` | El ESTADO de la cita que se esta cogiendo (servicio, dia, hora, nombre, cita en gestion) y que falta para cerrarla. Lo llena SOLO lo que devuelven las tools, y decide el siguiente paso ANTES de que hable el modelo: sustituye a los doce detectores que leian su texto para corregirlo despues. |
| `backend/conversation_state.py` | Repositorio SQLite de snapshots por tenant, canal e identidad. Compara versiones al escribir, conserva lápidas de olvido y limpia registros vencidos; no interpreta ni ejecuta reservas. |
| `backend/booking_operations.py` | Identidad opcional de creación por tenant y huella de petición. Recupera la fila guardada y evita repetir un proveedor con resultado incierto. El enlace con confirmaciones de los canales sigue pendiente. |
| `backend/wa_audio.py` | Escuchar las notas de voz de WhatsApp: pide el fichero a Meta con el token del negocio y lo transcribe. El texto entra por el MISMO camino que uno escrito. Se apaga con `WHATSAPP_AUDIO_ENABLED=false`; si falla, se le pide a la clienta que lo escriba. |
| `backend/agent.py` | Coger cita conversando (`booking.estilo = conversacional`): el modelo lleva el diálogo con TOOLS (`buscar_servicio`, `consultar_disponibilidad`, `crear_cita`) que le impiden inventarse un servicio, un hueco o una cita. Reusa el despachador de la voz. |
| `backend/calidad.py` | Vigilancia de calidad: repasa las conversaciones YA guardadas y marca las sospechosas (se repitio, dijo que cerrabais un dia que abris, llego al resumen y no hubo cita, dio un precio teniendolos ocultos...). Solo LEE: ni habla con nadie ni llama al modelo. Corre una vez al dia desde el worker de recordatorios; se consulta en `GET /admin/calidad`. |
| `backend/trazas.py` | Cuaderno de bitacora del asistente: por cada turno, que herramientas llamo, que frenos saltaron, cuanto tardo y cuanto costo (tokens -> euros). Lo rellena `agent.responder`; jamas puede tumbar una conversacion. Se consulta en `GET /admin/traza` y `GET /admin/informe`, y se limpia sola a los 30 dias. |
| `scripts/humo.py` | Cinco conversaciones ENTERAS por el camino real de WhatsApp antes de dar un despliegue por bueno (reservar, elegir opcion, preguntar precio, cancelar, reprogramar). Exige el resultado en la AGENDA y detecta bucles con la traza. Lo lanza `deploy/deploy.ps1`; si falla, el despliegue avisa a gritos. |
| `backend/rules.py` | Reglas del propio negocio (cuando quiera X, haz Y): tabla `business_rules`, gana la primera activa por prioridad. Decide QUÉ hacer con la intención que da `intents`. |
| `backend/fotos.py` | Qué hacer cuando una clienta anuncia o manda una foto: acusar recibo y pasar la conversación a una persona, en vez de seguir preguntando lo de siempre. El asistente no ve imágenes.
| `backend/inbox.py` | Intervención humana sobre una conversación de WhatsApp: mientras alguien la atiende, el asistente se calla (`bot_is_muted`) y se respeta la ventana de 24 h de Meta. |
| `backend/avisos.py` | Avisar al negocio por email cuando una clienta pide hablar con una persona: `inbox` calla al asistente y esto se lo cuenta a alguien. Uno por conversación cada 30 min, apagable con `config['avisos']['pedir_persona']`. |
| `backend/captacion_voz.py` | Captacion por telefono: la agente Sara (ElevenLabs) llama a los negocios con el guion legal (quien llama, que es una IA, que es comercial y que puede pedir no mas llamadas). Tool `enviar_informacion` (SMS si es movil, email del negocio si es fijo y lo sabemos, si no lo pide; apunta el interes y avisa a Pablo), `volver_a_llamar` y `no_volver_a_llamar` (ese telefono no vuelve a sonar); contestador = colgar sin mensaje. Llamadas en `llamadas_voz` de la base de captacion (con `origen` manual/auto y el `conversation_id` de ElevenLabs para leer la transcripcion). Prueba: `POST /admin/captacion/voz/llamada-prueba`; las de captacion las hace `lanzador_llamadas`. |
| `backend/lanzador_llamadas.py` | Lanzador automatico de las llamadas de Sara. Tres llaves: `CAPTACION_LLAMADAS_ENABLED=true`, interruptor del panel (tabla `llamadas_config`, apagado de serie) y nada en `bloqueos()` (Robinson, numero espanol `CAPTACION_TWILIO_NUMBER`, Twilio, ElevenLabs, agente creada). Solo fijos (primero los que abrieron o pincharon nuestros correos), Lista Robinson antes de marcar (sin respuesta no hay llamada; cache 30 dias en `robinson_consultas`), martes a viernes 10:00-12:30 y 16:00-18:00 Madrid, max 2 intentos si nadie lo cogio, nada a quien recibio correo hace <3 dias, una llamada cada vez con hueco y cupo diario. Hilo cada 5 min. Si ElevenLabs no conecta una llamada ya descolgada (`fallo_de_voz`, desde la ruta `/voice/el-captacion/twiml`), el lanzador se apaga solo y avisa a Pablo por correo. Panel: vista "Llamadas" del admin (`GET /admin/captacion/llamadas`, `PUT .../config`, `POST .../ronda`, `GET .../{id}/transcripcion`). |
| `backend/lista_robinson.py` | Cliente de la API de la Lista Robinson (Adigital): huellas SHA-256 (`"04"` + telefono `0034...`, nunca el numero), firma AWS SigV4 en la query, lotes de 60. `consultar()` LANZA si no puede saber: quien llama no puede leer un fallo como "no esta". Vectores del cliente oficial en `tests/test_lanzador_llamadas.py`. |
| `backend/cuenta_elevenlabs.py` | Vigila la cuenta de ElevenLabs (Pablo cancelo la Creator, 24-sep-2026: "lo que nos dure"). `estado()` (cache 30 min) dice si sirve: pago pendiente con factura abierta (ElevenLabs bloquea todo uso aunque diga `creator`), plan gratuito, creditos agotados o clave rechazada = no; el lanzador lo mira en `bloqueos()` y no marca. Un hilo la revisa cada hora y manda UN correo por problema cada 24 h (tambien con menos del 15 % de creditos) con los pasos para pasar a otra cuenta: clave nueva + deploy + sincronizar agentes (crean agente y voz de Laura en la cuenta nueva, `voz_elevenlabs.asegurar_voz`). |
| `backend/voz_elevenlabs.py` | Voz con ElevenLabs Agents (voz castellana "Laura" y modelo de turnos de ElevenLabs). Un agente por negocio generado desde las MISMAS fuentes que la voz de OpenAI (instrucciones, saludo con aviso de IA y tools de cita); ElevenLabs llama a `POST /voice/el/{cliente_id}/tool/{nombre}`, que ejecuta `voice._voice_dispatch_tool`. Sincronizacion: `POST /admin/clientes/{cliente_id}/voz-elevenlabs` (si el id guardado no existe en la cuenta de la clave actual, crea el agente de nuevo). `transcripcion()` lee una conversacion. |
| `backend/voice_engine.py` | `VoiceCallEngine`: el estado y TODA la lógica determinista de una llamada. El puente (`routers/voice_web.py`) solo mueve audio y delega. |
| `backend/wa_flows.py` | Reserva como formulario dentro de WhatsApp (WhatsApp Flows): endpoint cifrado, `flow_token` firmado. Apagado por defecto. |
| `backend/wa_onboarding.py` | Alta self-service del WhatsApp del negocio (Embedded Signup + Coexistence), con sus credenciales cifradas. |
| `backend/wa_plantillas.py` | Plantillas de Meta por negocio (recordatorio de cita fuera de la ventana de 24 h): alta en su WABA, estado de aprobación y payload de envío. |
| `backend/wa_demo.py` | Número de WhatsApp compartido para enseñar demos, con códigos de ruta por tenant. |
| `backend/channel_requests.py` | Solicitudes asistidas de aprovisionamiento de canales. |
| `backend/main.py` | App + middlewares + mounts + init de runtime + eventos. Importa los routers al final: **el orden de import = orden de registro de rutas**. |
| `backend/routers/*` | Endpoints por sección contigua del monolito original (decoran `app` directamente, sin APIRouter, para preservar el orden first-match de FastAPI). |

## Convención de acceso (importante al escribir código nuevo)

Entre módulos de backend, el acceso es **cualificado**: `from backend import
booking` y luego `booking._store_booking(...)` — nunca `from backend.booking
import _store_booking`. Así, parchear `api.simbolo` (lo que hacen los tests
vía el proxy) o `backend.modulo.simbolo` afecta a TODOS los llamadores.
Excepciones: clases, dataclasses y modelos Pydantic pueden importarse por
nombre.

Cuidado con locals que pisan nombres de módulo (`booking`, `chat`,
`settings`...): si una función necesita el módulo y tiene un local con ese
nombre, renombra el local (`booking_row`, `channel_settings`...).

## El shim api.py

`api.py` mantiene el contrato histórico del monolito:

- `uvicorn api:app` intacto (Dockerfile/CI/deploy sin cambios).
- Reimportar `api` con otro entorno purga `backend.*` y relee `.env`
  (las fixtures de tests hacen `sys.modules.pop("api")` + import).
- Proxy de namespace plano: `api.simbolo` lee EN VIVO del módulo home;
  `monkeypatch.setattr(api, ...)` parchea el módulo home; `dir(api)` lo
  expone todo (`scripts/qa_e2e.py` lo recorre).
- `tests/test_shim_compat.py` son las guardias de este contrato (escanea
  los nombres que tests y qa_e2e consumen y verifica el forwarding).

## Dónde añadir cosas

- **Endpoint nuevo**: en el router de su sección (`backend/routers/...`),
  decorando `app`. Si abre sección nueva, crear módulo router e importarlo
  al final de `backend/main.py` (el orden importa si hay rutas solapadas).
- **Lógica de dominio**: en su módulo de `backend/` con acceso cualificado.
- **Modelo de payload/respuesta**: en `api_models.py`.
- **Estado mutable compartido**: en `appstate.py`, siempre accedido como
  `appstate.X` y mutado bajo `appstate.state_lock`.
- **Tests nuevos**: usar `vantelia_env_factory`/`api_module`/`client` de
  `tests/conftest.py` (no duplicar el bloque de env).

## Verificación

```powershell
python -m pytest -q                  # suite completa (~10 min, 780+ tests)
python scripts/qa_e2e.py             # E2E aislado del portal (exit 0)
python -m py_compile api.py auto_onboarding.py onboarding_utils.py
npm run build                        # widget reproducible (lo exige CI)
```

Histórico del refactor y decisiones: `docs/AUDITORIA_REFACTOR.md` (sustituye
al antiguo `docs/API_REFACTOR_MAP.md`).
