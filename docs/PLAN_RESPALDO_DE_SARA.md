# Lo que Sara dice que hará y no hace: el respaldo al terminar la llamada

## El caso (28-sep-2026)

Llamada de prueba de Pablo, ya con el guion nuevo y el audio arreglado. Al final:

- Pablo dijo que no era el dueño: «es José, mañana sobre las 8». Sara no llamó a
  `anotar_responsable`.
- Dictó un correo y Sara dijo «te mando ahora mismo un correo con toda la información».
  No llamó a `enviar_informacion`. No se mandó nada.

Las herramientas estaban bien configuradas: el modelo no las usó. Regla del proyecto: lo
que el modelo puede hacer mal lo impide el código. Al colgar ya llega el análisis de
ElevenLabs (`captacion_voz.DATOS_AL_TERMINAR`); con él, el servidor hace lo que Sara
prometió y no hizo.

## Qué hace

En `transcripciones_llamadas.guardar` (por ahí pasa todo análisis: aviso de fin y
recogida horaria):

1. **Quién decide y cuándo** (`responsable_nombre`, `responsable_cuando`) rellenan lo que
   Sara no apuntó. Solo campos vacíos. La rellamada la decide el lanzador con
   `cuando_esta`, que no rellama si no lo entiende.
2. **La información** (`captacion_voz.enviar_de_respaldo`): si aceptó que se la
   mandáramos (`quiere_informacion`) y la llamada no tiene resultado, se manda con el
   mismo `_enviar_informacion` que la herramienta (correo o SMS, aviso a Pablo), con la
   nota «De respaldo».

## Tabla de fallos

Regla: **como mucho un envío por llamada; ante la duda, no se manda.**

| Situación | Riesgo | Regla |
|---|---|---|
| Sara sí llamó a `enviar_informacion` | Doble envío | Sello compartido: `_enviar_informacion` (la usan la herramienta y el respaldo) reclama la columna `informacion` con `UPDATE ... WHERE informacion=''` ANTES de mandar; solo un camino gana |
| El análisis llega mientras la herramienta aún manda (timeout de ElevenLabs) | Doble envío (lo cazó Astra en la primera versión, que sellaba `resultado` después de enviar) | El mismo sello: la herramienta ya lo tiene en `enviando` y el respaldo no manda |
| Sara llama dos veces a la herramienta | Dos correos | El mismo sello; la segunda vez responde «ya se le ha mandado» |
| El análisis llega dos veces (aviso y recogida horaria) o a la vez | Doble envío | El mismo sello |
| El proceso muere a mitad del envío | ¿Reintentar? | Queda en `enviando` y no se reintenta: antes uno de menos que dos |
| Corrige el correo después de mandado | Se queda con el primero | Aceptado: el aviso a Pablo lleva el correo al que salió |
| El análisis dice «sí» pero el desenlace es rechazo, número equivocado, buzón o colgó | Escribir a quien no quería | No se manda |
| El teléfono está en «no llamar», o el correo en bajas, rebotado o dado de baja | Escribir a una baja | No se manda |
| Ya hay otro resultado (volver a llamar, no llamar) | Contradecir lo que se acordó | No se manda |
| Correo dictado mal formado | Rebote | Se ignora; si es un fijo sin correo del negocio, no se manda |
| Falla el envío | ¿Reintentar? | Igual que la herramienta: queda «NO enviado» y aviso a Pablo para que escriba él; sin reintento |
| La herramienta ya anotó quién decide y cuándo | Pisar datos | Solo se rellenan campos vacíos |
| El análisis se inventa un «sí» | Un correo a quien no lo pidió | Riesgo aceptado: solo con `quiere_informacion` explícito, un único correo informativo con el aviso a Pablo; el guion además prohíbe decir «te lo mando» sin la herramienta |

Tests: `tests/test_respaldo_de_sara.py`, una prueba por fila.
