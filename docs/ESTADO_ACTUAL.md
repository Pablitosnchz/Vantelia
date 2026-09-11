# Estado actual de Vantelia

**La memoria compartida entre los agentes que trabajan en este repo.** La lee
quien empieza una tarea y la actualiza quien la cierra. Lo que no esté aquí, el
otro agente no lo sabe: cada uno tiene su propia memoria y no se ven entre sí.

Última actualización: 11-sep-2026, Claude Code (datos del piloto comprobados en
producción).

Los dos agentes **no se hablan directamente**: lo que uno sepa del otro sale de
este fichero, de `git log` o de lo que Pablo le pase.

## Cómo se trabaja ahora

- **GPT-6 Astra (Codex) implementa**, en una rama `astra/<tarea>`.
- **Claude Code revisa, aporta contexto y mide** (diff + tests + humo + banco), y
  despliega después de revisar.
- **Pablo decide.** Reglas completas en `AGENTS.md`.

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

## Bloqueado por fuera del código

- **Coexistence** (que un negocio conecte su propio número y siga usando su
  móvil). La app de Meta está en modo desarrollo y los permisos de WhatsApp en
  acceso ESTÁNDAR (solo activos propios). La verificación de acceso como
  proveedor de tecnología ya está hecha; la revisión de la app para
  `manage_app_solution` está EN CURSO (hasta 20 días) y el botón de publicar está
  deshabilitado hasta que termine. Al escanear el QR, Meta responde "missing
  required Graph API permissions for Cloud API companion pairing". Esto no lo
  arregla el código.
- El alta self-service de WhatsApp está limitada al tenant de pruebas
  `metareview` (variable `WHATSAPP_ES_TENANTS`); el resto de clientes ven "escríbenos
  y la activamos".
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

1. **Alicia**: esperar a Coexistence o arrancar ya con un número dedicado bajo la
   cuenta de Vantelia (funciona hoy en modo desarrollo; se cambia a su número
   cuando Meta apruebe).
2. **Rigidez de los dos apellidos en el panel**: obligatorio a secas (lo actual),
   obligatorio con salida para quien de verdad no tiene segundo apellido, o solo
   aviso.
3. **`scripts/tiktok_autosend.py`**: misma clase de riesgo que las
   automatizaciones de Meta que se borraron; ¿se retira también?

## Frágil, a vigilar

- En el humo, `reprogramar-mueve-la-cita` a veces solo pasa al segundo intento. Un
  camino que necesita dos intentos es uno que falla a alguna clienta.
- Cualquier sitio donde una lista de frases decide qué quiere decir la clienta.
- La frontera con Meta: un payload mal formado corta la conversación sin error
  visible para nadie; solo sale en los logs del servidor.
- Los fallos de estas semanas NO los encontraron los tests ni el banco: los
  encontró Pablo usando el producto como una clienta. Probar a mano la
  conversación entera sigue siendo imprescindible.
