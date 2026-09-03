# Caza de fallos: el prompt que me doy a mí mismo

Pablo lo dijo así: *"cuando te digo un fallo suelen salir más"*. Tiene razón, y la
razón es concreta: los fallos de este repo **no son sucesos aislados, son clases**.
Cuando uno aparece, sus hermanos ya estaban ahí — nadie había ido a buscarlos.

Este documento es el prompt reutilizable. No describe funcionalidad: describe
**cómo se rompe este proyecto**, con la búsqueda que encuentra cada clase.

---

## Cómo usarlo

> Audita el repo contra `docs/CAZA_DE_FALLOS.md`. Para cada clase, corre su
> búsqueda, revisa TODOS los resultados y decide caso por caso: fallo real,
> aceptable o falso positivo. Antes de arreglar, escribe el test que reproduce el
> fallo y **verifícalo contra el código actual** (si pasa sin el arreglo, no vale).
> Reporta lo que decidas no arreglar y por qué.

Regla que ha costado tiempo aprender: **un test que no falla con el bug presente
no prueba nada**. Se comprueba con `git stash` del arreglo.

---

## Las clases, ordenadas por lo que han costado

### 1. Divergencia entre canales

El mismo concepto implementado por separado en chat, WhatsApp y voz. Cada canal
"mejora" lo suyo y acaban discrepando entre ellos y con el panel.

Casos reales: el menú (3 opciones en el panel, 4 en el chat, 6 en WhatsApp); el
saludo de WhatsApp ignorando la bienvenida configurada; el horario del prompt
saliendo de config crudo mientras la disponibilidad usaba la matriz semanal.

```bash
# Textos casi iguales en dos canales: candidatos a fuente única
rg -n '"(Hola|Menú|📋|👋)' backend/chat.py backend/whatsapp.py backend/voice.py
# Constantes de negocio duplicadas
rg -n 'BASE_STARTERS|_resolve_widget_starters|menu_entries' backend/
```

**Pregunta a hacerse:** ¿esto lo decide el negocio en el panel? Entonces solo
puede haber UNA función que lo lea, y los tres canales la llaman.

---

### 2. El cliente encerrado en un paso

Máquinas de estado (`flow.flow` en WhatsApp) donde una rama responde un error y
`return`, sin salida. El agravante típico es una guarda "protectora"
(`if not flow.flow`) que impide que un saludo o el menú rescaten al usuario.

```bash
# Errores que terminan en return dentro de una rama de estado
rg -n -B2 -A4 'No he reconocido|no he entendido|No entiendo' backend/
# Guardas que apagan capas enteras cuando hay flujo activo
rg -n 'if not flow\.flow' backend/whatsapp.py
```

**Pregunta:** si el cliente escribe algo razonable pero fuera de guion, ¿tiene
salida? ¿Y si escribe "hola"?

---

### 3. Estado en memoria que nadie caduca

Diccionarios globales en `appstate` que crecen sin fin, o —peor— que devuelven un
estado viejo como si fuera actual. `whatsapp_flows` guardaba `last_seen` y no lo
miraba nadie: quien abandonaba una reserva reaparecía en el mismo paso días después.

```bash
rg -n '^[a-z_]+: Dict' backend/appstate.py
# Para cada uno: ¿quién lo purga? ¿quién comprueba su antigüedad?
rg -n 'last_seen|TTL|_purge|expired' backend/
```

**Pregunta:** ¿qué pasa si el usuario vuelve mañana? ¿Y con 10.000 conversaciones?

---

### 4. Límites de plataforma aplicados a lo bruto

WhatsApp corta títulos a 24 caracteres y descripciones a 72; una lista admite 10
filas. Recortar con `[:24]` convirtió "Keratina premium corto chico" en "Keratina
premium corto c" — idéntico al recorte de "corto medio".

```bash
rg -n '\[:[0-9]{1,3}\]' backend/ --glob '!**/test_*'
```

**Pregunta:** ¿este recorte lo lee una persona? ¿Dos elementos distintos pueden
quedar iguales después de cortar?

---

### 5. Texto que no casa lo que el cliente escribe

Patrones acentuados comparados contra texto ya normalizado sin tildes; mojibake
por doble codificación. Ambos fallan **en silencio**: sin error y sin log.

Ya lo vigila `tests/test_patrones_sin_tilde.py`. Ver sección 9 de
`docs/MAPA_DEL_CODIGO.md`.

---

### 6. Operaciones destructivas con un flag inocente

`_sync_services_from_info(deactivate_missing=True)` desactivó 183 servicios de un
salón real al guardar la ficha del panel.

```bash
rg -n 'deactivate|delete_missing|purge|DELETE FROM|UPDATE .* SET is_active' backend/
```

**Pregunta:** ¿quién llama a esto y con qué flag? ¿Qué pasa si el origen viene vacío?

---

### 7. Una verdad repartida en dos sitios

Hay **dos** tablas de pago (`booking_payments` y `customer_payments`). Mirar solo
una hace que el saldo mienta; por eso existe `backend/paystate.py`.

```bash
rg -n 'booking_payments|customer_payments' backend/ | grep -v paystate.py
```

**Pregunta:** ¿esta consulta ve las dos fuentes? ¿O debería llamar a `paystate`?

---

### 8. Índices y contadores que se desalinean

`menu_starter_N` se resolvía contra una lista distinta de la que pintó el menú: al
añadir la fila de tarjeta regalo, los índices dejaban de coincidir.

```bash
rg -n 'enumerate\(|_%d|\[index\]|\[indice\]' backend/whatsapp.py backend/chat.py
```

**Pregunta:** ¿la lista que numera y la que resuelve son la MISMA llamada?

---

### 9. Excepciones tragadas

`except Exception: pass` que oculta un fallo real y deja al cliente sin respuesta.

```bash
rg -n -A2 'except Exception' backend/ | rg -n 'pass$|continue$'
```

**Pregunta:** si esto falla, ¿alguien se entera? ¿El cliente recibe algo?

---

### 10. Lo que promete el panel y no cumple el backend

El panel dice *"las 3 primeras son fijas; Vantelia no añade más sugerencias
automáticamente"* mientras WhatsApp anteponía cuatro. La UI es un contrato.

```bash
rg -n 'panel-sub|<p class="panel-sub"' app_ui/index.html
```

**Pregunta:** ¿el backend cumple literalmente lo que esa frase promete?

---

### 11. Pedir algo vs preguntar por ello

Un detector que casa la palabra suelta confunde las dos cosas. "no quiero
cancelar nada, solo preguntar" recibía el formulario de cancelación; "¿se puede
pagar con tarjeta?" y "no quiero pagar ahora" disparaban el **enlace de cobro**.

```bash
rg -n 'def _message_requests_' backend/
```

**Pregunta:** ¿qué pasa si el cliente **niega** el verbo, o pregunta **por** la
acción en vez de pedirla? Reglas compartidas: `booking.MANAGE_NEGATION_RE`,
`_message_is_question_about_management`.

---

### 12. Datos que rellena un modelo, no un formulario

Las tools de voz reciben lo que gpt-realtime deduce de una llamada con ruido.
Puede mandar "mañana" donde se espera una fecha ISO. Eso levantaba un
`ValidationError` que **colgaba la llamada**: el puente lo captura, marca
`failed` y cierra el WebSocket.

```bash
rg -n 'await voice._voice_dispatch_tool|_voice_dispatch_tool\(' backend/
```

**Pregunta:** entre el modelo y el código, ¿quién es el muro? Ninguna tool puede
escapar con una excepción — el cliente se queda escuchando silencio.

---

### 13. La fila que se leyó hace un rato

Un worker que carga una lista y luego la recorre haciendo I/O trabaja con datos
viejos. `_run_booking_reminders` mandaba recordatorios a quien había cancelado
mientras el worker recorría la lista.

```bash
rg -n -B2 'for row in rows|for fila in filas' backend/
```

**Pregunta:** entre leer y actuar, ¿cuánto pasa? ¿Y si el cliente cambia algo
justo ahí? Se relee antes de tocar.

---

### 14. Comprobar y luego insertar

Dos peticiones simultáneas pasan las dos la comprobación. Un alisado de 90 min a
las 14:00 y un corte a las 14:30 se creaban **los dos**: el índice único de la BD
solo cubre el choque exacto de hora.

```bash
rg -n 'if not await .*_available|if .*_disponible' backend/
```

**Pregunta:** ¿qué pasa si dos personas hacen esto a la vez? Si la respuesta es
"se cuelan las dos", hace falta atomicidad (`appstate.booking_insert_lock`).

---

## Clases de comportamiento del asistente

Las de arriba son de código: se encuentran leyendo el repo. Estas se encuentran
**leyendo conversaciones enteras**, y son las que llegan por WhatsApp de la dueña
de un salón. Ninguna se ve en un resumen ni en una captura suelta.

---

### 15. El mensaje del cliente no llega al que decide

Se sustituye lo que escribió por una etiqueta, un texto fijo o un resumen, y la
capa que decide contesta a otra cosa. El síntoma no es "no me hace caso": es que
literalmente **no la oyó**.

Caso real (2-sep-2026): `_wa_start_booking_flow` llamaba al agente con el texto
fijo `"Quiero coger cita."`. La clienta escribió tres veces *"no quiero cita para
diagnóstico"* y el asistente siguió ofreciéndoselo. Además intentó resolver esa
frase inventada contra el catálogo: *"no tengo un servicio que se llame coger
cita"*.

```bash
# Textos fijos que viajan como si fueran del cliente
rg -n 'incoming_text\s*=\s*"' backend/
rg -n 'mensaje\s*=\s*"[A-Z]' backend/
```

**Pregunta:** ¿lo que recibe quien decide es LO QUE ESCRIBIÓ el cliente? Si hay
que transmitir una intención, va en un parámetro aparte, no falseando el mensaje.

---

### 16. Un dato del prompt que se lee como otro

El modelo copia la cifra que tiene al lado. Pasa cuando dos números distintos
comparten línea sin etiqueta.

Caso real: el catálogo decía `Secado al aire corto · 10 min · precio: NO se da por
mensaje`, y contestó *"El precio es de 10 €"* de un servicio que cuesta 4. No
filtraba el catálogo -no ve esos precios-: se los **inventaba** copiando la
duración, siempre por encima del doble.

```bash
# Lineas de prompt con varias cifras y poca etiqueta
rg -n 'f"\{.*\} min"|· \{' backend/booking.py backend/rag.py backend/voice.py
```

**Pregunta:** si tapo la etiqueta, ¿se puede confundir este número con otro?
Etiquétalo ("dura 10 min") y deja el hueco vacío explícito ("SIN PRECIO
PUBLICADO"), nunca ambiguo.

---

### 17. El freno que solo protege un camino

Un guardarraíl bien hecho, enganchado en el bucle del agente… y otra rama que
responde sin pasar por él. Con el tiempo el freno "existe" y no frena.

Caso real: `_da_un_precio_prohibido` corregía al agente, pero la respuesta
documental del chat web salía por otra puerta y decía el precio igual.

```bash
# Frenos usados en un solo sitio
rg -n '_da_un_precio_prohibido|_freno_de|no_se_da_precio_de' backend/ | rg -v tests
# Puntos por donde sale texto al cliente
rg -n 'RespuestaChat\(|_send_whatsapp_text\(' backend/ | wc -l
```

**Pregunta:** ¿cuántas puertas de salida tiene el texto al cliente, y por cuántas
pasa este freno? Si no son las mismas, el freno es decorativo.

---

### 18. Lo que no es texto se tira

Una foto, un audio, una ubicación, un contacto. Si no hay rama propia, cae en un
saco genérico y el modelo recibe una instrucción que no tiene nada que ver con lo
que pasó.

Caso real: una imagen se convertía en *"El usuario ha enviado un mensaje que no es
texto"*, y el asistente, a media reserva, volvía a preguntar el largo del pelo.
La clienta insistió cuatro veces.

```bash
rg -n 'message_type ==|no es texto' backend/whatsapp.py
```

**Pregunta:** ¿qué pasa con cada tipo que Meta puede mandar? Y cuando el
asistente no puede con algo, ¿lo dice y lo pasa a una persona, o disimula?

---

### 19. Decir cosas que nadie ha preguntado

Cada Q&A, regla o plantilla que se añade es algo que el modelo puede recitar en
el momento equivocado. Se construye mucha capacidad de decir y poca de callarse.

Casos reales: soltar `440 minutos` al elegir servicio; enumerar variantes internas
del catálogo (*"Mechas corto-med"*); repetir la política de precios después del
resumen de la cita. Palabras de la dueña: *"no le he preguntado nada de precio ni
del tiempo que dura, todo eso no tiene que decirlo"*.

```bash
rg -n 'nota"|nota_al_confirmar|aviso_' backend/agent.py
```

**Pregunta:** ¿esto lo ha pedido en ESTE mensaje? Si no, ¿por qué se dice?

---

### 18 bis. Lo que solo funciona si el negocio lo configura

Una capacidad existe en el codigo, funciona bien... y esta atada a que el negocio
cree una regla. Si no la crea -y no la crea nadie-, para el cliente sencillamente
no existe.

Caso real (2-sep-2026): `pasar_a_humano` estaba impecable -contesta y llama a
`inbox.claim`, que calla al asistente en esa conversacion- pero solo se disparaba
desde una REGLA del negocio, y su plantilla va atada a la intencion "queja". El
salon piloto tiene tres reglas y ninguna es esa, asi que a *"quiero hablar con
una persona"* el asistente seguia hablando.

```bash
# Acciones potentes que solo se alcanzan desde una regla
rg -n 'accion.*==.*"(pasar_a_humano|pedir_foto|formulario)"' backend/
rg -n '"intenciones": \[' backend/playbooks.py
```

**Pregunta:** ¿esto es una preferencia del negocio o algo que SIEMPRE hay que
hacer? Pedir una persona, mandar una foto o quejarse no son preferencias: pasan
en cualquier negocio y el comportamiento correcto es el mismo. Eso va en codigo,
encendido por defecto y apagable; no en una plantilla que hay que activar.

---

### 19 bis. El muro reformulado (INTENTADO Y DESCARTADO, 2-sep-2026)

La clienta insiste en algo que el negocio no hace y recibe la misma negativa una
y otra vez. `_ya_dijo_esto` compara los 90 primeros caracteres EXACTOS, y el
modelo la esquiva cambiando dos palabras:

    "Lamento QUE NO TENGAMOS servicios de manicura ni de unas de gel..."
    "Lamento INFORMARTE QUE NO TENEMOS servicios de manicura ni de unas de gel..."

**Se intento comparar por parecido y se descarto con datos.** Midiendo la
coincidencia de palabras sobre casos reales:

| | parecido |
| --- | --- |
| negativa reformulada (hay que frenarla) | 0,647 |
| regla del precio repetida (hay que frenarla) | 0,714 |
| "corte de senora, 20 min" vs "corte de caballero, 30 min" (NO frenar) | **0,667** |
| dos ofertas de horas distintas (NO frenar) | 0,526 |

El caso que NO hay que frenar se parece MAS que uno de los que si. Cualquier
umbral que cace la negativa reformulada bloquea una respuesta legitima, y
bloquear una respuesta buena es peor que repetir una.

Si se retoma, la senyal no es cuanto se parecen sino QUE cambia: en las que hay
que frenar solo cambian conectores y formas verbales (tengamos/tenemos,
que/informarte), y en las que no, cambian las palabras con contenido (senora/
caballero, 20/30). Habria que pesar los tokens, no contarlos.

---

### 20. Afirmar sobre lo que no se tiene configurado

Ante un hueco en la configuración, el modelo elige una respuesta rotunda en vez de
reconocer que no lo sabe.

Caso real: *"No tenemos promociones específicas para el alisado en este momento"*
cuando el negocio SÍ tenía promoción; simplemente no estaba en el sistema. Es
primo hermano de negar un servicio que sí se hace, que ya es crítico.

**Pregunta:** ante un hueco, ¿el asistente niega o consulta? Negar por defecto
cuesta clientas.

---

## Después de auditar

- Los fallos encontrados van con test que reproduce, verificado contra el código
  anterior.
- Las clases nuevas se añaden aquí, con su búsqueda.
- Si una clase deja de tener sentido, se borra: un documento que miente es peor
  que no tenerlo.

---

### 21. Reprogramar da vueltas (CERRADA el 3-sep-2026: era el instrumento)

Ella pide mover la cita sin decir hora ("cualquier otro hueco que tengas me
vale"). El modelo llama a `reprogramar_cita` con una hora que se inventa, el
freno `_hora_que_nadie_ha_pedido` la rechaza, y **vuelve a llamar con la misma
hora**. A la tercera, el humo lo corta: "reprogramar_cita se ha llamado 3 veces
con lo mismo: esta dando vueltas".

Medido con `scripts/humo.py --caso reprogramar-mueve-la-cita`, 5 tiradas: falla
al primer intento **2 de 5**. El reintento suele salvarlo, asi que el gate del
despliegue lo tumba solo cuando fallan los DOS (0,4x0,4 = 16 %). Paso la noche
del 2 al 3 de septiembre y volvio atras un despliegue entero.

**Intentado y descartado CON DATOS:** meter los huecos REALES dentro del propio
rechazo (`resultado["huecos_reales"]`), para que no tuviera nada que adivinar.

| | MAL de 5 tiradas |
| --- | --- |
| sin tocar nada | 0 (2 con reintento) |
| con los huecos en el rechazo | **2** |

Sale PEOR. La hipotesis era que le faltaba informacion; con mas informacion se
**CERRADA.** No era del producto: la BD local tenia una "Agenda general"
fantasma sin dias cerrados, asi que se ofrecian huecos de un LUNES -dia en que el
salon cierra- y la validacion, que va contra la profesional REAL, los rechazaba
uno tras otro. De ahi las seis llamadas seguidas con los mismos argumentos.

Con un snapshot de PRODUCCION, `scripts/humo.py --caso reprogramar-mueve-la-cita`
sale **5 de 5 a la primera**. Llevaba semanas tumbando despliegues. Antes de
volver a tocar este caso, comprueba el instrumento: lunes y domingo tienen que dar
CERO huecos.

Lo de abajo es de cuando se creia un fallo del producto, y se deja por la leccion:

pierde igual o mas. Pista para quien lo retome: el problema no parece ser que no
sepa los huecos, sino que insiste en la hora que ya decidio. Antes de volver a
tocarlo, medir 5 tiradas de linea base: la variacion normal es alta y a ojo no
se distingue una mejora de la suerte.

---

### 22. Elegir por ella (CERRADA, 3-sep-2026)

El salon tiene escrito que sin ver el cabello no se puede decir cual conviene.
Preguntado DE FRENTE lo contesta perfecto. Dicho como duda, se lo inventaba:

    ELLA  no se, ni idea de que largo tengo
    IA    te recomendaria el Acido lactico bio premium

Misma forma que el fallo de la lactancia (clase 20): la capa que entiende dispara
con la pregunta directa y se queda muda cuando la duda se expresa sin preguntar.

Arreglado en dos piezas: la duda se traduce a la pregunta que lleva dentro y se le
pregunta al negocio, y un freno impide recomendar un servicio concreto. **Lo
dispara la RECOMENDACION, no que ella dude**: asi cae tambien la que nadie pidio
("te recomendaria Keratina premium" cuando ella solo habia dicho el dia), que es
la que mas molesta a la duenya. Solo actua donde el negocio lo ha dicho por
escrito.

### 23. El abandono blando (CERRADA, 3-sep-2026)

    ELLA  dejalo, ya lo miro luego
    IA    Entiendo, no hay problema. PERO para reservar necesito saber el largo...

"Mira al final no, gracias" YA se cerraba bien. Fallaba el abandono BLANDO
("dejalo", "me lo pienso", "ya te dire"), que es justo el que un humano deja
marchar sin insistir. Es el tercer patron de reparacion de los asistentes de
produccion -cancellation en Rasa, junto a digressions (clase 20) y corrections
(que YA funcionaban: cambiar de dia, de servicio, "es para mi hija")-.

**Trampa:** el detector tiene que mirar SOLO el ultimo mensaje. Con
`dicho_de_ella`, que acumula todo lo que ella ha escrito, quien decia "dejalo" y
dos mensajes despues "va, si que quiero, el viernes" seguia recibiendo la
despedida: la conversacion quedaba muerta.

### 24. Vender sobre una queja (CERRADA, 3-sep-2026)

    ELLA  me hice el alisado y se me ha quedado fatal el pelo
    IA    Para solucionarlo, podemos optar por Keratina premium o Acido lactico

A quien se queja de un trabajo mal hecho se le vende otro. El playbook
`pasar_a_persona` lo cubre para quien lo active en el portal -el salon piloto NO
lo tenia-, pero el suelo no puede depender de que alguien se acuerde.

**Trampa:** el filtro de nombres pedia 10 caracteres (heredado de la clase 22) y
"Matiz" y "Elumen" se colaban enteros. Dentro de una queja se puede apretar a 5
con palabra completa: nombrar CUALQUIER servicio sobra.

### Abierto, medido, sin cerrar

- **Precio tras insistir** (inestable). A la tercera insistencia -"dime un rango
  aunque sea aproximado"- una tirada empezo a desglosar precios por largo y otra
  deflecto correctamente al diagnostico. Ademas se le vio pedir el largo "para
  darte un rango", que es el rodeo que ya prohibe
  `test_precio_oculto_no_pregunta_el_largo.py`. Medir varias tiradas antes de
  tocar: una sola no distingue el fallo de la suerte.
- **Nombra un servicio equivocado al pedir varios.** "corte y secado y tambien
  tinte" -> "He encontrado el servicio de Tinte cejas". La AGENDA esta protegida
  (`_freno_de_varios_servicios` actua al crear, y su caso critico pasa); lo que
  falla es lo que le dice por el camino.

### 25. Le repite su muletilla como si fuera un servicio (CERRADA, 3-sep-2026)

    ELLA  hola?
    IA    No tengo un servicio especifico llamado "hola"

Lo primero que ve alguien que solo estaba saludando. Se intento PRIMERO pidiendolo
en el mensaje de la tool ("si lo que ha escrito no es un servicio, no se lo
repitas como si lo fuera") y no cambio absolutamente nada. Es el ejemplo mas
limpio de la regla de la casa: lo que el modelo puede hacer mal lo impide el
codigo, no el prompt.

### 26. Dos personas en un hueco (CERRADA, 3-sep-2026)

"Cita para mi y para mi madre, cortes las dos" creaba UNA cita de veinte minutos.
Misma familia que varios servicios en una cita. Avisa una vez y luego las coge de
una en una: un freno que solo mire el texto acumulado bloquea PARA SIEMPRE -lo
que ella escribio no se borra- y la deja sin NINGUNA cita, que es peor.

### 27. Se inventa servicios que el negocio no hace (ABIERTA, medida 3-sep-2026)

A quien preguntaba por la manicura, en un salon que no toca las unas:

    IA  No tenemos manicura. Te gustaria un tratamiento de unas o un esmaltado?

Es el espejo del caso critico de negar un servicio que si existe, y sale igual de
caro: la clienta se planta alli.

**Intentado y retirado el mismo dia.** Un detector que, dentro de una negativa,
buscara lo que ofrece y lo comprobara contra el catalogo. Marca la palabra
equivocada: de "un tratamiento de unas o algo relacionado" se queda con
"relacionado" (un adjetivo), y da por inventada una frase correcta como "otro
tipo de servicio relacionado con el cabello". Bloquear una respuesta legitima es
peor que dejar pasar una mala -misma conclusion que la clase 19 bis-, asi que se
retiro en vez de dejarlo a medias.

Pista para quien lo retome: el nucleo del problema es identificar el SUSTANTIVO
que manda en lo que ofrece, y eso con expresiones regulares no sale. Con el
catalogo delante seguramente lo resuelve una llamada corta al modelo, pagando una
por respuesta que niegue algo (son pocas).

### 28. Le coge el TRATAMIENTO a quien preguntaba el precio (ABIERTA, medida 3-sep-2026)

Simulador de 40 clientas, 3 de las 8 conversaciones rotas:

    "le ha cogido 'Pack mechas o balayage medio' en vez de la valoracion"
    "le ha cogido 'Flash repair largo y extralargo' en vez de la valoracion"  x2

Preguntan el precio y acaban con un pack de horas cogido en la agenda en lugar de
la valoracion de quince minutos. `preguntar_precio` es el peor objetivo del
simulador con diferencia: **16,7 % (1 de 6)**, cuando reservar va al 94 %.

La causa esta localizada: el freno que canjea el tratamiento por la valoracion
existe y funciona -"Pack mechas o balayage medio" -> "Diagnostico y presupuesto"-
pero solo actua si `estado.veces_sin_precio` es mayor que cero, y ese contador
solo sube cuando el asistente se NIEGA a dar el precio. En este salon la pregunta
la contesta antes la Q&A escrita a mano, asi que el contador se queda a cero y el
freno no llega nunca.

**Dos intentos, los dos medidos, los dos peores:**

1. Abrir la condicion entera (`o _pregunta_el_precio(dicho_de_ella)`). La rama que
   BLOQUEA cuando la regla del negocio es otra -para los alisados, pedir foto- se
   abre tambien, y la clienta acaba sin ninguna cita y mandada al telefono:
   "no podemos agendar la cita para el diagnostico sin antes ver tu cabello".
2. Abrir SOLO el canje, dejando la rama que bloquea como estaba. Deja de bloquear,
   pero el canje tampoco se ve: da vueltas preguntando el largo y no coge nada.

**Tercer intento, tambien medido, tambien peor.** Decirle en la guia del turno,
ANTES de que empiece a pedir datos, que la cita que toca es la valoracion y que no
pregunte el largo (para esa cita no hace falta). Acierta el servicio -deja de
elegir "Pack mechas o balayage medio" y apunta a "Diagnostico y presupuesto"- pero
la conversacion se queda dando vueltas en la confirmacion y no llega a crear nada.
Medido con `--persona mechas-precio`, 8 conversaciones:

| | consigue lo que queria | repite | coge el tratamiento |
| --- | --- | --- | --- |
| sin tocar nada | **37,5 %** | 4 | 1 |
| con la guia | 25,0 % | 5 | 1 |

Ni siquiera baja el fallo que venia a arreglar.

**CUARTO intento: este SI mejora, y no iba de elegir el servicio.** Poniendo una
traza en el envio de mensajes se ve que en el turno de confirmar salen DOS, y se
contradicen:

    IA  Ana, para confirmar, tenemos el servicio de mechas o balayage corto el
        jueves 4 de septiembre a las 10:00.
    IA  Te lo digo con sinceridad: el precio depende mucho de tu pelo... ¿Te cojo
        la cita de valoracion?

`_wa_freno_del_precio` esta pegado al resumen, y el resumen se manda DESPUES del
mensaje del agente. El freno hace su trabajo -explica la regla, deja apuntada la
valoracion y pregunta si se la coge-, pero llega detras de una confirmacion que
lo contradice, y el segundo mensaje reabre la pregunta que ella acababa de
contestar.

Moverlo delante (`tests/test_freno_del_precio_antes_de_hablar.py`):

| | consigue lo que queria | repite |
| --- | --- | --- |
| el agente habla primero | 37,5 % | 4 |
| el freno va antes | **50,0 %** | 3 |

Aviso sobre una pista que escribi aqui y era FALSA: dije que el texto de rescate
salia en cada turno como mensaje aparte. No es cierto -la regla solo dispara en la
pregunta de precio-; lo que veia era esto otro. La traza en el envio lo resolvio
en diez minutos despues de tres intentos a ciegas.

Pista para quien lo retome: "Flash repair" (un alisado) NO esta en las familias
que exigen valoracion, asi que para esos dos casos el canje no aplica y lo que
toca es la regla de la foto. El unico de los tres que el canje arregla es el de
mechas. Conviene separarlos y medir cada uno por su lado, con el simulador y no
con una conversacion suelta: los dos intentos de arriba parecian razonables al
leerlos.

---

### 29. Cambiar de idea con la cita ya cogida (CERRADA, 3-sep-2026)

Reserva unas mechas el domingo a las 12:00 y luego cambia de idea:

    ELLA  he estado pensando y creo que solo quiero cortarme las puntas
    IA    Entonces haremos un corte de puntas en lugar de las mechas.
    ELLA  el domingo a las 11:30
    IA    Perfecto, te esperamos el domingo a las 11:30 para cortarte las puntas.

En la agenda seguian las MECHAS a las 12:00. Se lo dijo tres veces. En otras
tiradas le cogia una SEGUNDA cita dejando la primera puesta.

**La causa no era el modelo.** La tool `reprogramar_cita` del agente solo aceptaba
fecha y hora. El motor de debajo (`_voice_reschedule_booking`) SI sabe cambiar el
servicio -se anadio en 16c4a56- pero el agente no tenia como pedirlo, asi que solo
le quedaban salidas malas: dejarlo como estaba, coger otra cita, o decir que lo
habia cambiado. Cuando un modelo hace tres cosas raras seguidas, merece la pena
mirar si le falta la herramienta antes de escribirle otra instruccion.

Dos arreglos, medidos por separado con `--persona cambia-de-idea` (8 conv):

| | consigue lo que queria | fallos |
| --- | --- | --- |
| linea base | 12,5 % | 3 servicio, 1 duplicada, 1 repite |
| + freno de la hora | 25,0 % | 4 servicio |
| + servicio en la tool | **50,0 %** | 3 servicio, 1 duplicada |

El freno de la hora compara la hora que dice con la que hay en la agenda, y solo
cuando AFIRMA algo sobre su cita (ofrecer huecos no cuenta). Es mas firme que
comparar servicios: los nombres del catalogo normalizan de forma distinta segun el
sitio ("Mechas o balayage medio" -> "mechas balayage") y no casan con lo que dice
el modelo.

Queda abierto el `servicio_equivocado` (3 de 8): pide corte y acaba con mechas.

---

### 30. Mover la cita pidiendo un codigo que ya sabemos (CERRADA, 3-sep-2026)

Medido contra datos de PRODUCCION. La clienta quiere mover su cita y la
conversacion no cierra:

    ELLA  Me viene bien a las 14:00.
    IA    ... el 8 de septiembre a las 14:00. Confirmas esta cita?
    ELLA  Confirmo.                              (SEIS veces)

Instrumentando el estado turno a turno, la causa cabe en una linea:

    [estado] intencion=cancelar codigo= fecha=2026-09-08 hora=14:00 FALTA='codigo'

`que_falta` devuelve 'codigo' siempre, asi que `instruccion_de_cierre` -la unica
que dice "llama a reprogramar_cita AHORA"- no sale nunca. Y pedirle el codigo no
tenia sentido: tiene UNA cita y el telefono viene verificado; las tools ya buscan
por telefono sin codigo.

| | consigue lo que queria | |
| --- | --- | --- |
| base | 50,0 % | 4 atascadas sin mover la cita |
| + freno del dia que nadie pidio | 37,5 % | 3 citas DUPLICADAS -> retirado |
| codigo automatico, sin ese freno | **87,5 %** | 0 atascadas |

**Solo para reprogramar.** Autocompletarlo tambien en `cancelar` hizo esto, en el
primer mensaje: "Hola! Queria hablar sobre mi cita" -> "he cancelado tu cita del 5
de septiembre". Anular es destructivo; mover no.

**Retirado con datos:** el freno `dia_que_nadie_ha_pedido` (para que no le muevan
la cita a un dia que ella no ha pedido). Al bloquear el movimiento, el modelo
cogia una cita NUEVA y dejaba la vieja: 3 duplicadas de 8. El problema que venia a
arreglar es real -"queria saber si hay disponibilidad para otro dia" -> le movio
la cita al martes- pero frenarlo asi sale mas caro que el fallo.

**Ademas, dos regresiones MIAS de esa manyana, las dos medidas y arregladas:** el
freno de la hora rompia las reprogramaciones (la hora que ella PIDE no es un
error) y el de recomendar se metia en mitad de una confirmacion (si el servicio lo
nombro ella, repetirselo no es recomendar).

Queda abierto que la intencion se quede pegada en `cancelar` cuando ella dice
"no puedo ir, podria moverla": ni `_message_requests_cancel_booking` ni
`_message_requests_reschedule_booking` casan esa frase, asi que viene de otro
sitio (`anotar_intencion_por_tool` pone `cancelar` en cuanto el modelo llama a
`cancelar_cita`, aunque la llamada se rechace).

---

### 31. La regla del precio, repetida cada turno (ABIERTA, medida 3-sep-2026)

Con datos de PRODUCCION, la clienta que pregunta el precio es la que peor va:
**25 % (2 de 8), y 6 de 8 repiten**. El asistente le suelta la explicacion entera
en CADA turno, palabra por palabra, mientras ella contesta lo mismo:

    ELLA  ya tengo la cita de diagnostico para el viernes a las 11:00
    IA    Ya se que te lo he dicho, carino, y te entiendo. Son dos citas
          seguidas... 1. Diagnostico y presupuesto - 15 minutos, gratis...
    ELLA  ya tengo la cita de diagnostico para el viernes a las 11:00
    IA    (lo mismo, identico)                                    x3

La causa: `_wa_freno_del_precio` va pegado al resumen y vuelve a dispararse en
cuanto el modelo resuelve otra vez el servicio.

**DOS intentos, los dos medidos, los dos descartados:**

| | | |
| --- | --- | --- |
| sin tocar nada | 25,0 % | 6 repite, 1 precio indebido |
| explicarla UNA vez por conversacion | 50,0 % | 0 repite, pero **4 revientan** |
| lo mismo, cortando antes del resumen | 25,0 % | 4 repite, **4 precios indebidos** |

El primero quita las repeticiones -que era el objetivo- pero al soltar los datos
de la cita el resumen sigue adelante con la fecha vacia y salta
`HTTPException(400, "Fecha invalida")`. El segundo arregla el reventon cortando
antes del resumen, y entonces habla el agente por su cuenta y CUADRUPLICA el fallo
critico de dar un precio que este negocio no da.

Pista para quien lo retome: el freno hace dos cosas a la vez -explicar la regla y
parar la cita- y al separarlas se rompe una u otra. Lo que hay que conseguir es
que la SEGUNDA vez siga parando la cita y hablando, pero con otras palabras y sin
volver a explicar lo mismo; el texto de `_wa_explicar_la_regla_del_precio` es fijo.
Y medir siempre `da_un_precio_que_no_debe`, no solo las repeticiones: es facil
cambiar un fallo visible por otro mas caro.

---

### 32. Se va sin cita porque le piden un dato que ese servicio no tiene (ABIERTA, 3-sep-2026)

Con datos de produccion:

    ELLA  Creo que un "Corte de nino de 0 a 7" seria lo mejor, tiene 7 anos.
    ELLA  Para el martes 8, podria ser a las 10:30?
    IA    Solo necesito que me confirmes como tiene el pelo de largo: corto,
          medio o largo?
    ELLA  Confirmo. Gracias!
    IA    Solo necesito saber como tiene el pelo de largo...

Se fue SIN CITA. Le pedian el largo del pelo para un corte infantil, que no tiene
variantes por largo.

**Origen exacto**, encontrado llamando a `catalog_pick.elegir` a pelo: el catalogo
dice "Corte nino de 0 a 7" y ella escribio "corte DE nino de 0 a 7". Por esa
palabra no lo reconoce, devuelve `falta="tecnica"`, y el modelo convierte esa falta
en una pregunta inventada.

**Intentado y descartado (medido).** Un resolutor que acepta el servicio cuando
ella lo nombra tal cual: todas las palabras con contenido del nombre presentes en
lo que dijo, y que encaje UNO solo. Resuelve el caso en la unidad -da con "Corte
nino de 0 a 7" y no toca "unas mechas", que sigue pidiendo la talla- pero sobre 8
conversaciones:

| | consigue lo que queria | se fue sin cita |
| --- | --- | --- |
| sin tocar nada | 87,5 % | 1 |
| con el resolutor por nombre | 75,0 % | 2 |

Sin evidencia de mejora y con el fallo que venia a arreglar al alza. Para quien lo
retome: el caso concreto SI se arregla, asi que el danyo esta en otra parte -alguna
conversacion que antes se resolvia por familia ahora se cierra antes de tiempo-.
Y mide con mas de 8 conversaciones: con esa muestra, 7 frente a 6 no distingue una
mejora de la suerte.
