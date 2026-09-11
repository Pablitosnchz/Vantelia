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

1. `CLAUDE.md` — reglas de oro, arquitectura, qué hace cada módulo y por qué.
2. `docs/MAPA_DEL_CODIGO.md` — "quiero cambiar X, ¿qué fichero abro?", por flujo.
3. `docs/CAZA_DE_FALLOS.md` — las clases de fallo que YA han costado un incidente.
   Si vas a revisar código, este es tu documento principal.
4. `docs/COMO_PIENSA_EL_ASISTENTE.md` — antes de tocar cómo responde el asistente.
5. `docs/COMO_SE_MIDE.md` — los instrumentos de medida y sus trampas.
6. `tests/README.md` — qué cubre cada test, y cuáles vigilan REGLAS.
7. `docs/ARQUITECTURA.md` — mapa de módulos de `backend/`.

## Tu papel aquí: revisor, no autor

El reparto es deliberado:

- **Claude Code implementa, prueba y despliega.** Tiene el contexto del proyecto
  y la memoria de los incidentes.
- **Tú revisas y das una segunda opinión** sobre cambios concretos (un diff sin
  commitear, una rama, un commit), antes de que se fusionen.

Por tanto:

- **No despliegues.** Nunca. Ni `deploy/deploy.ps1`, ni `docker compose`, ni nada
  contra el VPS. Dos despliegues cruzados se pisan.
- **No hagas `git push`, ni reescribas historia, ni cambies de rama** sin que te lo
  pidan.
- **No toques producción ni secretos**: `.env`, claves SSH, tokens, `storage/`.
- **No edites ficheros en los que otro agente esté trabajando.** Ninguna de las
  integraciones entre agentes resuelve conflictos: el último que escribe gana y
  el otro pierde su trabajo sin enterarse. Si te piden cambios, que sea en tu propia
  rama o `git worktree`.

## Qué buscar al revisar

Estilo y nombres no importan. Importa lo que rompe algo que ve una clienta. Las
clases que más se repiten en este repo (detalle y ejemplos reales en
`docs/CAZA_DE_FALLOS.md`):

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
- **Un test que no falla sin el arreglo**, o que comprueba una línea literal del
  código en vez del comportamiento.
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

## Cómo comprobar algo

```powershell
python -m pytest                                  # ~2000 tests, ~12 min
python scripts/humo.py                            # 5 conversaciones enteras
python scripts/evaluar_asistente.py --db-copia <ruta_temporal>   # banco, con modelo real
```

El banco y el humo hablan con el modelo de verdad y cuestan dinero; el banco
EXIGE `--db-copia` para no escribir en la agenda de un negocio real.

## Cómo entregar una revisión

Para cada hallazgo:

1. **Gravedad**: crítico (una clienta se queda sin cita, se inventa un precio, se
   niega un servicio que existe, se escribe a quien no toca) / importante / menor.
2. **Dónde**: `fichero:línea`.
3. **El caso concreto**: qué escribe la clienta o qué pulsa, y qué pasa. Sin caso
   concreto no es un hallazgo, es una sospecha.
4. **Si algún test lo cazaría hoy.** Si no, cuál lo cazaría.

Si no encuentras nada, dilo. Una revisión vacía y honesta vale más que una lista
de sugerencias de estilo.
