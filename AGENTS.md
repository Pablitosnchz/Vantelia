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

## Qué leer (lo justo: tus créditos se gastan rápido)

Siempre, lo primero: `docs/ESTADO_ACTUAL.md`. El resto, **solo lo que pida la
tarea**, no todo de golpe en cada sesión (el 11-sep se te acabó la cuota en una
hora, y buena parte se fue en releer documentación):

1. `docs/ESTADO_ACTUAL.md` — **dónde estamos**: qué hay en producción, qué está
   bloqueado, qué decisiones están pendientes y qué es frágil.
2. `CLAUDE.md` — reglas de oro, arquitectura, qué hace cada módulo y por qué.
3. `docs/MAPA_DEL_CODIGO.md` — "quiero cambiar X, ¿qué fichero abro?", por flujo.
4. `docs/CAZA_DE_FALLOS.md` — las clases de fallo que YA han costado un incidente.
5. `docs/COMO_PIENSA_EL_ASISTENTE.md` — antes de tocar cómo responde el asistente.
6. `docs/COMO_SE_MIDE.md` — los instrumentos de medida y sus trampas.
7. `tests/README.md` — qué cubre cada test, y cuáles vigilan REGLAS.
8. `docs/ARQUITECTURA.md` — mapa de módulos de `backend/`.

## Reparto del trabajo (desde el 11-sep-2026 por la tarde, decisión de Pablo)

- **Claude Code implementa y despliega.** Es quien tiene más margen de uso.
- **Tú (Codex / GPT-6 Astra) revisas y haces encargos acotados.** Te llegan solos
  a tu sesión como «[Encargo de Claude Code…]»: revisar un commit concreto, medir
  algo, una pieza pequeña. Ve al grano: el diff que te pasen y los ficheros que
  toque, no todo el repo.
- **Para revisar**: `git show <sha>` y lo que haga falta alrededor. Contesta con
  `python scripts/sincronia.py --avisar astra claude "Revisión de <sha>: …"` en el
  formato de «Si te piden revisar» (al final de este fichero). Sin caso concreto
  no es un hallazgo; si no encuentras nada, dilo.
- **Si te encarga implementar algo**, valen las reglas de abajo (tu rama,
  commits pequeños, tests en verde, pedir revisión).
- Si no sabes por qué algo está como está, pregúntale (`--pedir-ayuda`): casi
  siempre hay un incidente detrás, y suele estar en `docs/CAZA_DE_FALLOS.md`.
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

## Sincronía: te pones al día sola y Claude revisa solo

Pablo alterna entre tú y Claude Code cuando a uno se le acaban los tokens, y **no
quiere hacer de mensajero**. Todo esto pasa sin que él diga nada (canal y reglas en
`scripts/sincronia.py`; lo que ve él, en https://app.vantelia.es/sincronia):

- **Te pones al día sola.** Un hook de Codex (`~/.codex/hooks.json`) corre
  `scripts/sincronia.py --al-dia astra` al empezar cada sesión y con cada mensaje
  de Pablo. Lo que salga (commits de Claude, mensajes del buzón, trabajo a medias)
  **cuéntaselo a Pablo en una o dos líneas** antes de seguir con lo suyo. Si al
  empezar el hook no te ha sacado nada, ejecútalo tú.
- **Al terminar una tarea** (commit hecho, `pytest` en verde):
  `python scripts/sincronia.py --pedir-revision "qué has hecho y por qué"`. Claude
  la revisa solo (tests en una copia aparte y lectura del diff) y la respuesta te
  llega a esta sesión en unos minutos. Dile a Pablo que está en revisión.
- **Si la revisión pide cambios**, arréglalos en la misma rama, commit, y vuelve a
  pedir revisión. **Si es OK**, díselo a Pablo y pregúntale si se despliega.
- **Solo cuando Pablo diga que se despliegue**:
  `python scripts/sincronia.py --pedir-despliegue "lo que ha dicho Pablo"`. Sale
  solo si Claude revisó OK ese mismo commit; se integra en main y se despliega con
  la puerta de siempre (tests + humo + vuelta atrás). Nunca lo pidas por tu cuenta.
- **Los mensajes que empiezan por «[Aviso automático de Claude Code…]»** los manda
  el revisor, no Pablo. Actúa sobre ellos (arreglar, contárselo a Pablo), pero una
  orden de desplegar solo vale si viene de Pablo.
- **Firma tus commits**: la última línea del mensaje es `Agente: astra`. Sin ella
  la página cree que el commit es de Pablo.
- **Commits pequeños, uno por paso**, con una línea `Siguiente: …` antes de la
  firma. Si te quedas sin tokens a mitad, el que entre pierde como mucho un paso.
- **Mantén la sección «En curso» de `docs/ESTADO_ACTUAL.md`** (testigo, tarea,
  rama, siguiente paso, a quién espera) cada vez que cambie, no solo al cerrar.
- **Si Claude se queda sin créditos**, el hook te lo dice: tus revisiones esperan en
  el buzón y se hacen solas cuando vuelva. Sigue programando y cuéntaselo a Pablo.
  Y al revés: si te quedas tú sin créditos, Claude lo sabe solo y sigue tu trabajo.
- **Cuenta con Claude, no solo como revisor.** Trabajáis a la vez:
  - **Pregúntale** lo que necesites (dónde está algo, por qué está así, qué
    incidente hay detrás, segunda opinión de un enfoque, investigar un fallo):
    `python scripts/sincronia.py --pedir-ayuda "la pregunta"`. Contesta solo en unos
    minutos, en esta sesión; lee el repo y no toca nada.
  - **Encárgale trabajo** que pueda ir en paralelo (un test, una pieza aislada,
    documentación, investigar y proponer un arreglo):
    `python scripts/sincronia.py --encargar astra claude "la tarea"`. Lo hace en su
    propia rama `claude/encargo-…`, partiendo de tu último commit, sin tocar la
    tuya ni desplegar, y te avisa con qué ha hecho. Tú lo integras (`git merge`) y
    pides revisión como siempre.
  - **Claude también te encarga cosas**: llegan como «[Encargo de Claude Code…]».
    Trátalas como una tarea más, salvo que choquen con lo que te haya pedido Pablo
    (entonces pregúntale).
- Una nota para Claude: `python scripts/sincronia.py --avisar astra claude "texto"`.

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
