# Cómo piensa el asistente

> Empieza por aquí si vas a tocar cómo responde el asistente a un cliente final.
> Explica **por qué** está montado así, que es lo que evita repetir los errores.

## El problema que resolvió esta arquitectura

Durante meses el asistente fue **seis capas de heurísticas** compitiendo por
contestar:

```
saludo → palabras clave → Q&A exacta → comprensión+reglas → disponibilidad (regex) → RAG
```

Funcionaba, pero casi todos los fallos que aparecían **no eran de inteligencia,
eran de enrutado**: contestaba la capa equivocada.

- La Q&A del horario se comía *"¿estáis abiertos ahora?"* y soltaba el horario
  semanal a las 21:15 de un sábado.
- El regex de disponibilidad se comía *"¿a qué hora abrís?"*.
- El clasificador entendía *"no espera, mejor un corte"* como **reprogramar** y le
  pedía a la clienta un número de reserva que no tenía.

Y cada arreglo era un parche más en una de las seis capas. El juego del topo.

## Cómo está montado ahora

**Un agente con herramientas lleva la conversación.** El modelo decide *qué
consultar*; las herramientas devuelven la verdad del negocio. No hay enrutado que
fallar porque casi no hay enrutado.

```
saludo puro          → menú o bienvenida
palabras clave       → configuración LITERAL del negocio
Q&A exactas          → configuración LITERAL del negocio (salvo si la pregunta es de HOY)
AGENTE (backend/agent.py) → todo lo demás, con herramientas
```

Quedan dos interceptores deterministas a propósito: **lo que el negocio ha escrito
palabra por palabra manda sobre cualquier deducción nuestra.** Es una petición
explícita de cliente, no un accidente.

### Las herramientas

| Herramienta | Garantiza |
| --- | --- |
| `consultar_horario` | El horario real y si está abierto **ahora** |
| `buscar_servicio` | Solo servicios que existen en SU catálogo |
| `consultar_disponibilidad` | Solo huecos reales de su agenda |
| `crear_cita` | Todos los datos presentes y el hueco libre |
| `consultar_cita` / `cancelar_cita` / `reprogramar_cita` | La cita existe y es suya |
| `politica_del_negocio` | Lo que ESTE negocio tiene escrito sobre un tema |

`crear_cita` y las de gestión reusan `voice._voice_dispatch_tool`: **una sola forma
de crear una cita** en todo el producto, la misma que usa el teléfono.

## La regla que más veces se ha ganado a pulso

> **Lo que el modelo puede hacer mal, lo impide el CÓDIGO, no el prompt.**

Pedírselo en las instrucciones se le escapa cada pocas respuestas. Estos tres son
reales, los tres pasaron, y los tres están arreglados en las tools:

1. Creó una cita con el nombre **"clienta"**, inventado, porque la tool exigía un
   nombre y él no lo tenía → la tool **rechaza** nombres que no lo son.
2. Creó **dos citas**: una sin nombre y otra al dárselo → dedup mirando la agenda.
3. Dijo *"el jueves que viene, 29 de agosto"* siendo el jueves el **27** → ya no
   calcula fechas: recibe los próximos 14 días con su fecha y si el negocio abre.

Y dos más de la misma familia:

4. Afirmaba que un día estaba **cerrado** sin haber mirado la agenda → si su
   respuesta habla de días u horas y no ha consultado, se le obliga a consultar.
5. Negó las cejas teniendo tres servicios de cejas → la búsqueda la hace el código
   y le pasa el resultado.

## Elegir el servicio: decide el código

`backend/catalog_pick.py`. El modelo **extrae** lo que dice la clienta (familia,
técnica, largo, para quién, edad); el código **decide** mirando el catálogo:

1. Filtra los servicios que encajan con esos datos.
2. Si queda uno → lo elige.
3. Si quedan **técnicas distintas** y no dijo cuál → pregunta (keratina vs ácido
   láctico son 240 € y 260 €: no se elige por ella).
4. Si quedan **tallas** y no sabe el largo → pregunta el largo.
5. Si ya tiene todos los datos → coge el más sencillo.

Con los mismos datos, la misma decisión **siempre**. Por eso se puede testear sin
llamar al modelo (`tests/test_elegir_servicio.py`), y por eso no puede repreguntar
algo que ya le han dicho: cada pregunta nace de mirar qué falta *en los datos*.

## Un negocio nuevo: las situaciones típicas

`backend/playbooks.py`. Las condiciones de un cliente no se escriben en código: son
**plantillas que el negocio activa desde el portal** (pestaña Q&A → "Situaciones
típicas").

| Situación | Para qué |
| --- | --- |
| No dar precio sin ver al cliente | Mechas, implantes, presupuestos a medida |
| Pedir una foto para presupuestar | Cuando SÍ se puede a distancia pero hay que ver algo |
| Derivar a valoración | Lo que no se cierra por mensaje |
| Pasar a una persona | Quejas y temas delicados |
| Responder algo concreto | Formas de pago, parking, acompañantes |
| Solo contarlo | Medir cuánta gente pregunta algo antes de decidir |

Una clínica dice *"no doy precios de implantes sin radiografía"* con la **misma**
plantilla con la que un salón dice *"no doy precios de mechas sin ver el pelo"*.
Cada plantilla se convierte en una fila de `business_rules`, que es lo que ya
consulta el asistente: no es un mecanismo nuevo, es la forma cómoda de rellenar el
que hay.

El tono (`config['tono']`), el estilo de reserva (`booking.estilo`) y el rescate
por teléfono (`booking.rescate_*`) son configuración por negocio igual que esto.

## Los fallos que solo se ven mirando la agenda

Hasta agosto de 2026 el banco de casos miraba **lo que el asistente decía**. Cuatro
fallos graves vivían debajo, porque un asistente puede decir *"listo, te he
apuntado"* sin haber tocado nada:

| Fallo | Qué pasaba de verdad |
| --- | --- |
| Pedía el teléfono por WhatsApp | El canal lo trae verificado. La clienta daba servicio, día, hora y nombre, y la conversación moría pidiendo el número: **ninguna cita se creaba** |
| El agente declaraba `codigo`, la tool leía `codigo_reserva` | Consultar, cancelar y cambiar cita **nunca funcionaron** desde chat ni WhatsApp. La llamada se perdía en silencio, sin error en ningún log |
| Las notas se tiraban | *"soy alérgica"*, *"voy con mi hija"* no llegaban a la cita |
| Barría el calendario | Con *"cualquier hueco me vale"* pedía ocho días de golpe, agotaba el turno y la dejaba sin respuesta |

Por eso un caso ahora puede exigir un **efecto**: `agenda: crea | no_crea | cancela
| cambia`. Y hay un test de contrato (`test_los_argumentos_que_declara_son_los_que_lee_el_despachador`)
que compara lo que cada tool **anuncia** con lo que el despachador **consume**: ese
desajuste no vuelve a pasar inadvertido.

### Lo que sale al probarlo como un cliente de verdad

El dueño lo abrió por WhatsApp y en cuatro mensajes salieron dos fallos que ningún
test veía:

- Al pedir cita **sin decir qué quería**, contestó *"vamos a agendar tu cita para el
  Ácido Láctico Bio Premium - Muy Corto"*. Es el **primer servicio del catálogo**
  que lleva en el prompt: al no saber qué quería, cogió uno. Elegirle a alguien un
  tratamiento de 260 € no es un detalle.
- Y le **recitó diez fechas** en vez de preguntarle cuándo le venía bien.

Los dos se cortan ahora en el código: si nombra un servicio que la clienta no ha
nombrado, se le hace preguntar; y si ofrece horas sin saber el día, también. La
vuelta correctora va **sin herramientas** (`tool_choice="none"`) — dejándoselas, el
modelo volvía a consultar la agenda y a soltar horas en lugar de preguntar.

De paso: al mover una cita llegó a decir que quedaba *"para un corte de señora"*
cuando lo cogido era un alisado. Cambiar de hora no cambia el tratamiento.

Un caso puede pasar solo y fallar en la tirada entera: el modelo no es consistente,
y probando a mano solo ves una de las dos versiones. Por eso un caso se mide por lo
OBJETIVO (¿ofreció horas?) y no por vocabulario ("¿qué día te viene bien?" y "¿te va
bien el martes?" son igual de correctas).

### Aislar la base de datos: comprobarlo, no suponerlo

`settings.DB_PATH` se calcula al **importar** y no lee la variable de entorno, así
que exportar `DB_PATH` no aislaba nada: una tirada metió siete citas de prueba en
la agenda de un salón real. Ahora el runner reapunta el módulo, **verifica** que las
conexiones abren la copia y se niega a arrancar si no. Y la copia se hace con
`backup()` de SQLite, no con `copyfile`: en modo WAL los últimos cambios viven en un
fichero aparte, así que la copia traía citas ya borradas y el dedup las daba por
vivas.

## Cómo se comprueba que funciona

**No basta con probarlo.** Los fallos que importan solo salen escribiendo como un
cliente real: con faltas, partiendo una frase en tres mensajes, cortándose a media
palabra e insistiendo. El guion feliz no los ve.

```powershell
python scripts/evaluar_asistente.py --db-copia /tmp/eval.db
```

Un banco de casos con severidad (`evals/casos_asistente.py`). Trabaja sobre una
**copia de la base de datos**, así que las citas de prueba no tocan la agenda del
negocio. Sale con error si falla un **crítico**: inventarse un precio, dar por
hecha una cita que no existe, negar un servicio que sí hace.

Al escribir un caso, cuidado con los `no_debe`: `"está reservada"` también casa
dentro de *"aún no está reservada"*, que es justo la respuesta **correcta**. Un
banco de casos mal escrito te hace "arreglar" lo que funciona.

## Si vas a tocar algo

- **Un fallo nuevo**: ¿es de enrutado o de una tool? Si el modelo dijo algo falso,
  la tool tiene que impedirlo. Si contestó la capa equivocada, mira si esa capa
  debería existir.
- **Una condición nueva de un cliente**: ¿cabe en una plantilla de `playbooks`? Si
  no cabe, añádela al catálogo — no escribas un script por cliente.
- **Antes de dar algo por bueno**: `python scripts/evaluar_asistente.py` y
  `python -m pytest`.
