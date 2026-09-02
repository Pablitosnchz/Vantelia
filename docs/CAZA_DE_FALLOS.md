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

### 21. Reprogramar da vueltas (VIVO, ~40 % de las veces, 3-sep-2026)

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
pierde igual o mas. Pista para quien lo retome: el problema no parece ser que no
sepa los huecos, sino que insiste en la hora que ya decidio. Antes de volver a
tocarlo, medir 5 tiradas de linea base: la variacion normal es alta y a ojo no
se distingue una mejora de la suerte.
