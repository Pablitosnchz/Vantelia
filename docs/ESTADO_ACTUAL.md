# Estado actual de Vantelia

**La memoria compartida entre los agentes que trabajan en este repo.** La lee
quien empieza una tarea y la actualiza quien la cierra. Lo que no esté aquí, el
otro agente no lo sabe: cada uno tiene su propia memoria y no se ven entre sí.

Última actualización: 11-sep-2026, Claude Code.

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
