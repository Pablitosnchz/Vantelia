# AGENTS.md — para agentes de código que no son Claude Code

Este fichero lo leen los agentes que siguen la convención `AGENTS.md` (Codex CLI,
GPT-6 Astra y similares). Claude Code lee `CLAUDE.md`. Las reglas son las mismas:
**este fichero no las repite, te manda a donde están.**

## Qué es esto

Vantelia: plataforma SaaS multi-tenant de asistentes IA para negocios españoles
(peluquerías, clínicas, hoteles). API FastAPI + SQLite, panel admin y portal
cliente en HTML/JS vanilla, widget embebible, WhatsApp Cloud API y voz. El primer
cliente real es un salón de peluquería; cada fallo que llega a producción lo ve
una clienta de verdad.

## Lee esto antes de tocar nada, en este orden

1. `docs/ESTADO_ACTUAL.md` — **dónde estamos**: qué hay en producción, qué está
   bloqueado, qué decisiones están pendientes y qué es frágil. Empieza aquí.
2. `CLAUDE.md` — reglas de oro, arquitectura, qué hace cada módulo y por qué.
3. `docs/MAPA_DEL_CODIGO.md` — "quiero cambiar X, ¿qué fichero abro?", por flujo.
4. `docs/CAZA_DE_FALLOS.md` — las clases de fallo que YA han costado un incidente.
5. `docs/COMO_PIENSA_EL_ASISTENTE.md` — antes de tocar cómo responde el asistente.
6. `docs/COMO_SE_MIDE.md` — los instrumentos de medida y sus trampas.
7. `tests/README.md` — qué cubre cada test, y cuáles vigilan REGLAS.
8. `docs/ARQUITECTURA.md` — mapa de módulos de `backend/`.

## Reparto del trabajo (desde el 11-sep-2026)

- **Tú (Codex / GPT-6 Astra) implementas.**
- **Claude Code revisa, aporta contexto y mide**: lee tu diff, lo contrasta con
  las trampas conocidas y pasa los instrumentos (tests, humo, banco) antes de que
  se fusione. Si no sabes por qué algo está como está, pregunta: casi siempre hay
  un incidente detrás, y suele estar escrito en `docs/CAZA_DE_FALLOS.md`.
- **Pablo decide.**

Reglas de trabajo, que existen porque dos agentes sobre el mismo repo se pisan:

- **Trabaja en una rama `astra/<tarea>`, nunca directamente en `main`.** Mejor aún
  en un worktree propio: `git worktree add ../Vantelia-astra -b astra/<tarea>`.
  Ninguna integración entre agentes resuelve conflictos: el último que escribe
  gana y el otro pierde su trabajo sin enterarse.
- **Un cambio, un commit**, con el POR QUÉ en el mensaje (mira `git log`: así
  están escritos todos). El que revisa lee eso antes que el código.
- **Antes de pedir revisión, `python -m pytest` en verde.** Si un test que vigila
  una REGLA se pone rojo, léelo antes de "arreglarlo": suele tener razón él.
- **Un test que no falla sin tu arreglo no prueba nada.** Compruébalo rompiendo el
  arreglo a propósito. Y prueba COMPORTAMIENTO, no el orden de las líneas.
- **No despliegues.** El despliegue lo lanza Claude Code después de revisar, y
  tiene su propia puerta (humo + vuelta atrás automática). Dos despliegues
  cruzados contra el mismo VPS se pisan.
- **No hagas `git push` ni reescribas historia** sin que Pablo lo pida.
- **No toques producción ni secretos**: `.env`, claves SSH, tokens, `storage/`.
- **Al cerrar una tarea, actualiza `docs/ESTADO_ACTUAL.md`**: es la memoria
  compartida entre los dos agentes. Lo que no esté ahí, el otro no lo sabe.
- **Si Claude Code no está disponible** (sin tokens): sigues en tu rama, y en
  «En curso» pones `Espera a: revisión de Claude`. Nada se despliega sin él.

## Ponerse al día y dejar rastro (sincronía)

Pablo cambia de agente cuando a uno se le acaban los tokens, y mira en
https://app.vantelia.es/sincronia si el otro ha visto lo último. Esa página sale
de hechos (git, ficheros sin guardar, cuándo se puso al día cada uno), no de lo
que digas. Para que diga la verdad:

- **Lo primero de cada sesión**: `python scripts/sincronia.py --al-dia astra`. Te
  enseña lo que ha cambiado desde tu última vez (commits de Claude, trabajo sin
  guardar, lo que hay en curso) y deja apuntado que lo has visto. Si Pablo te dice
  «ponte al día», es esto. Si enseña commits nuevos, míralos antes de tocar nada.
- **Firma tus commits**: la última línea del mensaje es `Agente: astra`. Sin ella
  la página cree que el commit es de Pablo y no sabe que Claude tiene que verlo.
- **Commits pequeños, uno por paso**, con una línea `Siguiente: …` antes de la
  firma. Si te quedas sin tokens a mitad, el que entre pierde como mucho un paso.
- **Mantén la sección «En curso» de `docs/ESTADO_ACTUAL.md`** (testigo, tarea,
  rama, siguiente paso, a quién espera) cada vez que cambie, no solo al cerrar.

## Lo que más se rompe aquí (tenlo presente al programar)

Detalle y ejemplos reales en `docs/CAZA_DE_FALLOS.md`:

- **Una lista de frases decidiendo una intención.** El modelo reescribe cada frase
  a su manera y la lista siempre pierde por una letra ("te reservo" estaba, "te
  reserve" no). Lo que aguanta es decidir por HECHOS del estado, no por palabras.
- **Una instrucción del código que contradice una regla del negocio** y gana por
  ir después en el prompt.
- **Prometer lo que el núcleo va a rechazar**: enseñar un resumen, una hora o un
  precio que después la reserva no acepta.
- **La forma del payload en la frontera con Meta.** Un id de botón repetido hace
  que Meta rechace el mensaje ENTERO y la conversación se corta sin error visible.
- **Dos sitios calculando lo mismo por su cuenta**: la duración del catálogo frente
  al final real de la cita; el dibujo del calendario frente a la disponibilidad.
- **Arreglar un canal y dejar los otros rotos.** Chat, WhatsApp, voz y widget
  llaman a los MISMOS núcleos de `backend/booking.py`; un arreglo en un canal que
  no pasa por el núcleo es una bomba en los demás.
- **Guardar en el historial lo que no se llegó a enviar.** El panel enseña a la
  dueña mensajes que la clienta nunca recibió.
- **Reemplazos masivos**: un `"nombre"` en un test puede ser un servicio, no una
  persona.

## Reglas técnicas que no se ven a simple vista

- Entre módulos de `backend/` el acceso es CUALIFICADO (`from backend import
  booking` + `booking.helper()`), nunca `from backend.booking import helper`: el
  proxy de `api.py` y los monkeypatch de los tests dependen de ello.
- Lo que el modelo puede hacer mal lo impide el CÓDIGO (en las tools), no el prompt.
- Texto al cliente CON tildes; patrones que casan lo que escribe el cliente, SIN
  (van normalizados). Acentuar un patrón lo rompe en silencio.
- Los tests nunca mandan emails reales: `tests/conftest.py` vacía las credenciales.
- El entorno local es Python 3.8 (sin `removeprefix`, sin `dict | dict`); el
  despliegue corre en 3.11.
- Dos funciones con el MISMO nombre en módulos distintos de `backend/` rompen el
  shim de `api.py` (lo vigila `tests/test_shim_compat.py`).

## Cómo comprobar algo

```powershell
python -m pytest                                  # ~2000 tests, ~12 min
python scripts/humo.py                            # 5 conversaciones enteras
python scripts/evaluar_asistente.py --db-copia <ruta_temporal>   # banco, con modelo real
```

El banco y el humo hablan con el modelo de verdad y cuestan dinero; el banco
EXIGE `--db-copia` para no escribir en la agenda de un negocio real.

## Si te piden revisar (en vez de implementar)

Para cada hallazgo: **gravedad** (crítico = una clienta se queda sin cita, se
inventa un precio, se niega un servicio que existe, se escribe a quien no toca /
importante / menor), **dónde** (`fichero:línea`), **el caso concreto** que lo rompe
y **si algún test lo cazaría hoy**. Sin caso concreto no es un hallazgo, es una
sospecha. Si no encuentras nada, dilo.
