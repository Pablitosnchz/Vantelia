# Estado actual de Vantelia

**La memoria compartida entre los agentes que trabajan en este repo.** La lee
quien empieza una tarea y la actualiza quien la cierra. Lo que no esté aquí, el
otro agente no lo sabe: cada uno tiene su propia memoria y no se ven entre sí.

Última actualización: 11-sep-2026 tarde, Claude Code (Coexistence desbloqueado;
el +31 contesta con el asistente de Alicia).

Los dos agentes no comparten memoria. Lo que uno sabe del otro sale de este
fichero, de `git log` y del buzón de `scripts/sincronia.py` (peticiones de
revisión y avisos, que llegan solos a la sesión del otro): Pablo no hace de
mensajero.

## Cómo se trabaja ahora

- **Claude Code implementa y despliega** (decisión de Pablo, 11-sep por la tarde:
  a Astra se le acabaron los créditos en una hora).
- **GPT-6 Astra (Codex) revisa y hace encargos acotados** que Claude le pasa; le
  llegan solos a su sesión. Si está sin créditos, Claude sigue con sus propios
  instrumentos (tests + humo) y le deja la revisión esperando en el buzón.
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

- **Testigo:** nadie
- **Tarea:** ninguna abierta. «La primera que tengas» ya acaba en cita (ver «Lo último»).
- **Rama:** main.
- **Siguiente:** que Astra revise la integración (`5d05457`), el mensaje ilegible (`33f274a`) y «la primera que tengas»; los tres le esperan en el buzón.
- **Espera a:** nada. Astra, sin créditos hasta las 20:46.

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
  las 6 reservan con el primer "sí".

## Bloqueado por fuera del código

- **Coexistence: DESBLOQUEADO (11-sep).** Meta aprobó la revisión de la app y
  Pablo la publicó. El +31 97006546256 de Vantelia funciona en Coexistence (WA
  Business en su móvil + asistente a la vez). Desde las ~17:00 ese número contesta
  con el **asistente de Alicia**, solo lo que entra: sus avisos de cita siguen
  saliendo por email, porque se le quitó WhatsApp de los canales de aviso para que
  el "Vantelia" del +31 no escriba a sus clientas reales. Las citas de prueba por
  el +31 caen en SU agenda real. Si alguien contesta desde WA Business, el
  asistente se calla 2 h en ese chat (vuelve solo, o «Devolver al asistente» en
  Conversaciones).
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

1. **Alicia con su propio número**: Meta ya lo permite. Falta decidir cuándo:
   añadirla a `WHATSAPP_ES_TENANTS` y que conecte su número desde el portal
   (sigue usando su móvil como siempre). Hasta entonces el +31 hace de número suyo.
2. **Rigidez de los dos apellidos en el panel**: obligatorio a secas (lo actual),
   obligatorio con salida para quien de verdad no tiene segundo apellido, o solo
   aviso.
3. **`scripts/tiktok_autosend.py`**: misma clase de riesgo que las
   automatizaciones de Meta que se borraron; ¿se retira también?
4. Hecho (11-sep): Pablo aprobó en Codex los hooks de Astra (`~/.codex/hooks.json`,
   desde la terminal: la app de escritorio no tiene `/hooks`). Astra estaba sin
   créditos hasta las 15:30; al volver, en una sesión nueva se pone al día sola.

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
