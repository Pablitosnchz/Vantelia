# Estado actual de Vantelia

**La memoria compartida entre los agentes que trabajan en este repo.** La lee
quien empieza una tarea y la actualiza quien la cierra. Lo que no esté aquí, el
otro agente no lo sabe: cada uno tiene su propia memoria y no se ven entre sí.

Última actualización: 12-sep-2026, Astra (candidato de confirmación persistida;
no implica cambios en producción).

Los dos agentes no comparten memoria. Lo que uno sabe del otro sale de este
fichero, de `git log` y del buzón de `scripts/sincronia.py` (peticiones de
revisión y avisos, que llegan solos a la sesión del otro): Pablo no hace de
mensajero.

## Cómo se trabaja ahora

- **Astra coordina e implementa la consolidación** (encargo vigente de Pablo).
- **Claude auxilia con revisiones, mediciones y piezas encargadas** en ramas propias. Despliegue solo por orden de Pablo.
- **Pablo decide.** Reglas completas en `AGENTS.md`.
- **¿Estáis sincronizados?** → https://app.vantelia.es/sincronia (semáforo, solo
  admin). Pablo no tiene que decir nada: los hooks de los dos agentes los ponen al
  día solos al empezar y con cada mensaje suyo, y el agente le cuenta lo nuevo.
- **Astra termina → Claude revisa solo.** Astra pide revisión, la tarea programada
  «Vantelia revisor» pasa los tests en una copia aparte y lanza la revisión de
  Claude, y la respuesta llega a la sesión de Astra, que se lo cuenta a Pablo.
  Pablo solo dice «despliega», a cualquiera de los dos.
- **Si a uno se le acaban los tokens**, el otro se pone al día solo y sigue en la
  MISMA rama.
- **No solo revisar: trabajan juntos.** Astra le pregunta a Claude
  (`--pedir-ayuda`) o le encarga trabajo en paralelo (`--encargar astra claude`,
  lo hace en su rama `claude/encargo-…`), y Claude a ella (`--encargar claude
  astra`). Todo llega solo a la sesión del otro.

## En curso

Quien tiene el testigo lo actualiza cada vez que cambia (no solo al cerrar). La
página de sincronía lo enseña tal cual.

- **Testigo:** Astra.
- **Tarea:** correcciones b338a2d de la revisión c22cc42 integradas con 6d00071: negativa por regla, centros coherentes, respaldo de texto y siguiente paso, conservando persistencia, confirmación por identidad y núcleo recuperable.
- **Rama:** astra/estado-propuestas, E:/Vantelia-astra-estado. Esta rama vuelve a ser el candidato integrado más reciente; no retomar ramas anteriores por inercia.
- **Siguiente:** Integración con 6d00071: 68 dirigidos verdes. Cerrar los fallos de demos antes de una única suite completa y revisión exacta. Correcciones: 67 dirigidos y 11 de cierre verdes (grupos solapados), pyflakes limpio. La prueba de negativa recorre botón No y resumen real con Pack/mayúsculas; la protección tiene mutación roja. La tarjeta Q&A ya corregida se verifica ejecutando JavaScript.
- **Espera a:** diagnóstico encargado a Claude de 5 fallos en test_demo_conversion de la suite 6d00071 (2261 correctos, 1 omitido). 530ae40 tenía suite verde (2256 correctos, 1 omitido). No duplicar ese diagnóstico ni las suites anteriores. Sin push ni despliegue; todavía pendientes enlace de ejecución recuperable WhatsApp, banco comparable Alicia+otro negocio y recordatorios reales.



Pendientes operativos que no deben perderse: estado de la plantilla de recordatorios
y prueba de envío real; confirmar situación actual con Claude. Última referencia
documental anterior de producción: `aab4d02`, no verificada de nuevo en esta revisión.
Los relatos de medición antiguos de más abajo son históricos; la referencia con
calendario reproducible se distingue arriba y no oculta los reintentos.

Por qué se integró antes de su revisión (Claude): sus 8 tests nuevos fallan 7
contra el código sin el arreglo y pasan con él; pytest completo en verde (2026);
el humo del caso contra una copia de producción no empeora (el fallo original es
poco frecuente: 1 de 4 despliegues el 11-sep). Su worktree tiene cambios sin
commit (`booking.py`, `voice.py` y el test) que no se han tocado.

Validación local de Astra: las tres regresiones iniciales fallaron sin el arreglo;
el control de reserva nueva pasó. Con el arreglo pasan los ocho casos específicos
(incluyen profesional, duración, exclusión propia, primer hueco automático y código
ajeno/inexistente), y una selección de 99 pruebas de voz, agente y compatibilidad.
Esto mide comportamiento determinista, no la tasa de fallos del modelo real.

## Lo último en producción

- **Agenda del panel**: la cita se lee entera (el día se pinta a 2,2 px/min, así
  que una de 15 min muestra nombre completo y servicio); selector de horas por
  franjas con scroll; estirar o acortar arrastrando cualquiera de los dos bordes,
  de 5 en 5, sin avisar a la clienta; el mostrador puede apuntar citas fuera de
  horario (la IA no).
- **Nombre y dos apellidos obligatorios** al crear cita o cliente desde el panel
  (400 desde el backend). Por WhatsApp se piden los apellidos UNA vez.
- **WhatsApp**: el freno de "cita sin pedir" decide por hechos, no por frases; la
  hora se comprueba ANTES de enseñar el resumen; los botones del aviso de cita
  duplicada ya no revientan en Meta; el resumen solo queda en el historial si
  Meta lo aceptó.
- **Asistente**: no elige la técnica por la clienta; un "sí" a la cita de
  valoración cuenta; no niega un servicio que existe cuando le dan el nombre
  exacto.
- **Captación**: se borró todo el código que automatizaba productos de Meta
  (DMs de Instagram y WhatsApp Web). No se vuelve a montar: ver `CLAUDE.md`.
- **Sincronía entre agentes** (11-sep, `7fb3823`): https://app.vantelia.es/sincronia
  enseña con un semáforo si Claude y Astra han visto lo último del otro, y lo que
  se dicen entre ellos.
- **Revisión automática** (11-sep, `dbdba26` + `83bbeb6`): cuando Astra pide
  revisión, la tarea programada «Vantelia revisor» pasa los tests en una copia
  aparte y lanza la revisión de Claude sin nadie delante. Probada de verdad con
  `claude -p`: revisión útil y veredicto bien leído.
- **Sin créditos** (11-sep, `3fd5e0b`): si uno se queda sin cuota lo sabe el otro
  solo (a Astra se le lee de su propia sesión de Codex, con la hora de vuelta) y
  sigue él; nada se pierde mientras tanto.
- **Reprogramar a la primera** (11-sep, `5d05457`, en producción `1268e4a`): al
  mover una cita solo se ofrecen horas de SU profesional y que el núcleo acepta
  (antes se ofrecían huecos de otra y el cambio se rechazaba). Lo encontró y
  arregló Astra; lo integró y desplegó Claude.
- **Mensaje ilegible por WhatsApp** (11-sep): el primer "hola" al +31 recién
  conectado llegó de Meta sin texto, y al modelo se le pasaba una instrucción por
  el hueco del texto de la clienta; quedaba en el historial como dicha por ella y
  al mensaje siguiente repetía "no puedo leer mensajes que no estén en formato de
  texto". Ahora se pide que lo repita con una frase fija (también el audio que no
  se oye) y abrir el chat por primera vez (`request_welcome`) cuenta como saludo.
  Los avisos de sistema de Meta (cambio de número) no se contestan.
- **«La primera que tengas» acaba en cita** (11-sep): el código elegía el primer
  hueco (a última hora, hoy a diez minutos vista) mientras el modelo le enseñaba
  horas de otro día, y el nombre no se anotaba hasta `crear_cita`: le repetía la
  lista y se quedaba sin cita. Ahora la hora del código sigue al día que ella lee,
  "me llamo X" se anota al momento (se cierra en ese turno), y el primer hueco de
  hoy deja una hora de margen. En 6 conversaciones contra copia de producción:
  5 reservan con el primer "sí"; en la otra el modelo mezcló el día que
  encabezaba su lista con la hora elegida, la herramienta lo frenó (ninguna cita
  mal cogida) y reservó al siguiente "sí". Para esa mezcla, guardarraíl
  (`reserva.dia_cambiado_con_la_hora_elegida`): si la llamada trae la hora elegida
  con otro día que ella no ha dicho, manda el día que se le propuso. Con él, otras
  6 conversaciones: las 6 al primer "sí" (la mezcla no se repitió; la cubre el
  test).
- **El asistente vuelve a la hora** (11-sep, decisión de Pablo): tras contestar el
  equipo desde WhatsApp Business se calla 1 h desde su último mensaje (antes 2 h;
  por negocio, `whatsapp.silencio_tras_responder_min`). Al volver, un "hola" no
  saca la bienvenida con el menú: lo coge el agente, que conserva lo hablado (su
  historial ya no se corta a la media hora si ha intervenido una persona).
- **"Corte de señora" es "Corte señora"** (11-sep): un "de" de más en el nombre
  que escribe el modelo ya no cambia el servicio. Antes no se encontraba y la
  cita se cogía de 15 min (el paso de la agenda) en vez de 20, con un nombre que
  no existe en el catálogo.
- **Recordatorios por WhatsApp fuera de la ventana de 24 h** (11-sep, `57f6d45`):
  Meta solo deja escribir texto libre 24 h desde el último mensaje de la clienta,
  así que un recordatorio del día antes casi siempre se perdía. Ahora sale como
  plantilla (`vantelia_recordatorio_cita`, transaccional) de la cuenta del propio
  negocio, con los mismos botones «Confirmo» y «Cancelar cita», que ya se
  procesan al pulsarlos. La plantilla la da de alta y consulta el worker; en la
  cuenta del +31 ya está creada y en revisión. Sin plantilla aprobada no sale por
  WhatsApp: el aviso sigue por el siguiente canal y el motivo queda anotado.
  Además, **las citas de demo ya no avisan ni llaman a nadie** (la cuenta de
  revisión de Meta tiene 191 con móviles inventados). Cada plantilla fuera de
  ventana la cobra Meta al negocio, que necesita método de pago allí.
- **Dos apellidos por WhatsApp** (11-sep, decisión de Pablo): a una clienta nueva
  se le piden nombre y dos apellidos antes del resumen (freno en `crear_cita` del
  agente y en el flujo con listas, que junta lo que va diciendo; a la tercera se le
  ofrece llamar). A una clienta conocida no se le pide nada.
- **No ofrece una hora que no existe** (12-sep, `e6be556`): tras enseñarle
  09:00-10:00, a un «a las 15» contestaba *«mañana a las 15:00 tengo disponible»*,
  ella decía que sí, y la mentira solo se descubría al crear la cita, tres turnos
  después (la cita imposible NUNCA nació: el hueco se comprueba al crearla). Ahora,
  si ofrece una hora que no está en los huecos que tenemos y no ha mirado la agenda
  en ese turno, se le obliga a mirarla. En las trazas se ve funcionando: contesta
  «las 15:00 no las tengo, tengo estas por la mañana» en el turno bueno.
- **Lo de Astra, verificado e integrado** (12-sep, `aab4d02`): el botón de mover
  cita ya no canta éxito cuando el núcleo rechaza el cambio; el pack de la cita no
  se convierte en el servicio suelto al moverla; a una clienta ya conocida no se le
  vuelven a pedir los apellidos; y una respuesta que Meta rechaza no queda en el
  historial como enviada. Comprobado antes de integrar: sus 5 tests fallan contra
  main sin sus arreglos, suite entera sobre su rama (2082) y sobre la fusión (2116).

## El crítico que no cierra (12-sep, medido de madrugada)

El caso `dice-que-si-y-acaba-en-cita` sigue siendo INTERMITENTE y es lo único rojo
del banco: **42 de 43** contra copia fresca de producción con la config viva.

Lo que se sabe, medido:

- Con el freno de la hora inventada: 4 de 9. La MENTIRA está tapada; lo que falla
  es el cierre. La conversación se atasca porque el servicio sigue sin concretarse
  («no lo tengo claro») y el modelo vuelve a preguntar la técnica en vez de cerrar.
- **El atajo que debería cortar eso lleva desde el 8-sep muerto.**
  `_hay_que_cogerle_la_valoracion` corta a la TERCERA pregunta y coge el
  diagnóstico, pero el contador (`veces_falta`) solo subía si faltaba el MISMO dato
  dos veces seguidas, y el modelo alterna (técnica, largo, técnica): se reiniciaba
  siempre. No saltó ni una vez en 12 conversaciones medidas. Hay un intento de
  arreglo en `claude/hora-sin-mirar` (`_veces_sin_concretar`), **sin validar**: con
  él tampoco llegó a saltar, así que la causa puede ser otra.
- Ampliar el freno de la hora (que frenara también sin huecos sobre la mesa):
  1 de 6. Descartado de momento.

**DOS TRAMPAS DEL INSTRUMENTO, las dos costaron conclusiones falsas esta noche:**

1. Medir desde un worktree NO vale: no tiene `.env`, así que no hay clave de
   OpenAI y todas las conversaciones fallan por lo mismo. Dio un 0 de 4 que no
   medía nada. Los worktrees valen para tests, no para el banco.
2. **El guion del caso dice «manana», y el resultado depende de qué día sea.**
   Medido en la madrugada del sábado al domingo: «mañana» cae en domingo, que el
   salón CIERRA, así que la conversación correcta ya no puede acabar en cita. Peor:
   algunas tiradas «pasaban» porque el modelo reservaba HOY llamándolo «mañana».
   Comparar medidas tomadas a un lado y otro de la medianoche es comparar días
   distintos. Si se toca este caso, medir de día y con «mañana» abierto.

Fragilidad aparte: `tests/test_estirar_la_cita.py` da 11 errores en un worktree
limpio (fixture que reserva y recibe 409) y pasa en `E:/Vantelia`. Depende de
estado local, no es hermético. No es de esta noche: pasa igual en `aab4d02`.

## Bloqueado por fuera del código

- **Coexistence: DESBLOQUEADO (11-sep).** Meta aprobó la revisión de la app y
  Pablo la publicó. El +31 97006546256 de Vantelia funciona en Coexistence (WA
  Business en su móvil + asistente a la vez) y contesta con el **asistente de
  Vantelia** (tenant `metareview`, "Clara"). Estuvo unas horas con el de Alicia y se
  deshizo a petición de Pablo: su pestaña WhatsApp está limpia para que conecte el
  suyo. Si alguien contesta desde WA Business, el asistente se calla 1 h desde su
  último mensaje en ese chat (vuelve solo, sin saludar de nuevo y sabiendo lo
  hablado; o «Devolver al asistente» en Conversaciones).
- **Avisos de cita de Alicia: hoy no sale ninguno.** En el bloque que usa el motor
  (`booking.message_template_channels`) tiene el email apagado y solo WhatsApp, y
  WhatsApp no está conectado. Cuando conecte su número empezarán las
  confirmaciones por WhatsApp; los recordatorios de 24 h casi nunca saldrán hasta
  que haya plantillas (`docs/PLAN_RECORDATORIOS_WHATSAPP.md`).
- El alta self-service de WhatsApp sigue limitada al tenant de pruebas
  `metareview` (variable `WHATSAPP_ES_TENANTS`). Conectar el número PROPIO de
  Alicia pasa por añadirla ahí (ver decisión 1).
- **Stripe de Alicia**: cuenta conectada pero `charges_enabled=0`,
  `payouts_enabled=0`, `details_submitted=0` (sin cambios desde el 27-ago). Los
  servicios con señal **se reservan sin cobrarla**. Se retoma después de Meta.

## Piloto de Alicia: comprobado en producción (11-sep)

Leído de la BD de producción, no de los documentos de agosto. Sustituye a las
"preguntas abiertas" de `docs/ALICIA_PENDIENTE.md` donde choquen.

- **Señal**: 53 servicios activos la llevan. **Ninguno de menos de 50 €** (hay 91
  activos por debajo, todos sin señal). La pregunta de agosto sigue igual: es
  decisión de Alicia, no un fallo.
- **Grey blending**: los sueltos de 75/90/105/120 min están desactivados; queda
  activo "Grey blending corto-med" (90 min, 48 €). Packs: corto 370 min, medio
  440, **largo 530, extra largo 495**. Que el largo dure más que el extra largo
  hay que preguntárselo a ella (en agosto ya se vio que el "largo" usa pasos de
  extra largo).
- **Recogidos**: existen y están activos (medio recogido 20 min, con postizo 30,
  recogido con postizo 40, pack maquillaje y recogido 170, pack maquillaje y
  medio recogido 215). No se han revisado los pasos internos de los packs.
- **Equipo**: Alicia tiene **0 servicios asignados a propósito**: lista vacía =
  los hace todos (`agenda._services_for_employee`), y así los servicios nuevos le
  entran solos. No "arreglarlo" poniéndole una lista. Lorena 190, Conchi 193,
  Lucía 108, Jose 108.
- Sin comprobar todavía: horario real de Lucía y Jose, y si Alicia ha probado la
  última versión.

## Decisiones pendientes de Pablo

1. **Alicia con su propio número: LISTO para que lo conecte** (11-sep, comprobado
   en producción). Le sale el botón «Conectar mi WhatsApp» en la pestaña WhatsApp
   de su portal (`WHATSAPP_ES_TENANTS=metareview,alicia_rincon_estilistas` en el
   `.env` del VPS). Al conectar, su configuración pasa sola al número nuevo. Es la
   prueba de que el alta vale para una empresa que no es la nuestra. Después,
   vigilar sus avisos (ver «Avisos de cita de Alicia» arriba) y el punto 2.
2. **Siguiente gran tarea: recordatorios por WhatsApp** (plantillas de Meta). Plan
   para ejecutar tal cual en `docs/PLAN_RECORDATORIOS_WHATSAPP.md`.
3. Decidido (11-sep): **dos apellidos obligatorios** en el panel y también por
   WhatsApp a las clientas nuevas; a las conocidas no se les pide nada.
4. **Anotado para más adelante** (Pablo, 11-sep: "con el resto ya seguiremos"):
   - `scripts/tiktok_autosend.py`: misma clase de riesgo que las automatizaciones
     de Meta que se borraron; ¿se retira?
   - Rotar `WHATSAPP_APP_SECRET` (se imprimió en claro el 9-sep): lo lleva Pablo.
   - Stripe de Alicia sin activar: Pablo se lo pide a ella.
   - Preguntar a Alicia: grey blending "largo" (530 min) dura más que el "extra
     largo" (495); horario real de Lucía y Jose.
   - El formulario de reserva dentro de WhatsApp (Flows) está en borrador y en la
     WABA de Vantelia: en números de otros negocios no sale (sigue por mensajes).
   - Aviso al negocio de un mensaje normal (hoy solo cuando piden persona) y push.
   - Esfuerzo de razonamiento de Astra (con `xhigh` gasta la cuota en una hora).
5. Hecho (11-sep): Pablo aprobó en Codex los hooks de Astra (`~/.codex/hooks.json`,
   desde la terminal: la app de escritorio no tiene `/hooks`).

## Frágil, a vigilar

- El humo da por bueno lo que llega a la agenda, no cómo llega: `corte-acaba-en-cita`
  "pasaba" 6 de 6 con la clienta viendo la lista de horas dos veces, gracias al
  "sí, confirmo" de sobra del guion. Arreglado el fallo (ver «Lo último»), el
  instrumento sigue sin verlo: leer las conversaciones, no solo el veredicto.
- En el catálogo de Alicia conviven "Corte señora" (20 min) y "Corte de señora"
  (15 min), y el asistente coge uno u otro. Preguntarle cuál vale.
- Cualquier sitio donde una lista de frases decide qué quiere decir la clienta.
- La frontera con Meta: un payload mal formado corta la conversación sin error
  visible para nadie; solo sale en los logs del servidor.
- Los fallos de estas semanas NO los encontraron los tests ni el banco: los
  encontró Pablo usando el producto como una clienta. Probar a mano la
  conversación entera sigue siendo imprescindible.
