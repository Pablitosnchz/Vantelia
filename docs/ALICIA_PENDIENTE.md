# Alicia Rincón Estilistas: lo pedido, lo hecho y lo que falta

Estado a 21-ago-2026. Tenant `alicia_rincon_estilistas`.

Este documento existe porque sus peticiones llegan por WhatsApp a lo largo del
día y se pierden. Cuando algo se cierra, se borra de aquí.

---

## Hecho y en producción

### Catálogo: exactamente su Excel

**191 servicios** (186 activos + 5 pasos internos de packs), 11 categorías. Se
borraron los 24 que ya no estaban en su tabla, tras comprobar que ninguno tenía
citas.

### Los tiempos de espera (lo de más valor)

Confirmado por ella en llamada el 19-ago: en la hoja **Servicios** está lo que
tarda **ella en hacer** el servicio, y el **tiempo de exposición** de la hoja
*Packs* es el rato que queda **libre para atender a otra clienta**.

Un servicio pasa a ser `activo → espera → activo`. Los tramos viven en
`services.gap_json`, se copian a la cita al reservar y `agenda._booked_intervals`
—fuente única de "qué está ocupado"— devuelve solo los tramos activos. **Sin
tramos, todo se comporta igual que antes.**

37 servicios con tramos. Medido en producción: con el pack de grey blending largo
(8,8 h) encima, a la profesional le quedaban **18 huecos libres** ese mismo día.

### Lo demás

- **Agenda cada 15 minutos** en todo el equipo: 42 huecos al día en vez de 21.
- **Señal**: 65 servicios (64 de 50 € y la extensión real de 100 €).
- **Equipo**: Alicia, Lorena, Conchi, Lucía y Jose, en ese orden. Con lo que hace
  cada una según su columna "Operario" (Lucía y Jose, solo los marcados "Todos").
- **Precios**: nunca de mechas, balayage, grey, landing, extensiones ni cambios
  de color. En su lugar, cita de diagnóstico de **15 minutos, gratis**.
- **Alisados**: si piden presupuesto, se les pide **foto por detrás**; si quieren
  cita, se les coge preguntando el largo.
- **Tono cercano con emojis** y **"¡Gracias a ti! 😊"** siempre que agradezcan.
- **Franjas horarias en WhatsApp**: antes solo se veían los huecos hasta las
  14:30 y ninguna clienta veía las tardes.
- **Sin hueco → que llamen**, con su teléfono.

### El asistente entiende, ya no adivina

Sus normas vivían dentro del *prompt*: el modelo podía ignorarlas, no había forma
de saber cuántas veces se aplicaban, y cambiarlas exigía tocar la configuración
del tenant a mano.

Ahora la intención la decide el modelo (`backend/intents.py`) y lo que se hace con
ella lo decide **ella**, desde la pestaña Q&A del portal → **"Reglas de tu
negocio"** (`business_rules`). Medido contra el modelo real:

- De **19 formas naturales de pedir cita se resolvían 2**. Ahora **18**, medido
  contra su asistente ya en producción: 14 abren el formulario y 4 contestan con
  huecos reales. ("me pones una cita?", "resérvame el jueves", "hazme un hueco" y
  "quiero ponerme guapa el sábado" no abrían nada.) La que falta, "necesito que
  me atiendan", contesta igualmente ofreciéndole cita.
- Sus **Q&A** ahora casan aunque la clienta pregunte con otras palabras: 10 de 10
  en la prueba, incluida la que **no** debía casar (nadie preguntó por el parking).

Sus tres normas, ya como reglas editables (`scripts/reglas_alicia.py`):

| Cuando quieran | Solo en | El asistente |
| --- | --- | --- |
| presupuesto o precio | alisado | pide la **foto por detrás** |
| presupuesto, precio o info | extensiones | ofrece **cita de valoración** |
| presupuesto o precio | mechas, balayage, color… | ofrece valoración o su teléfono |

**Acotadas a esas familias a propósito**: su catálogo sí tiene precio cerrado para
corte, peinado o recogido, y una regla de "nunca doy precios" sin acotar los
taparía todos.

---

## Preguntas abiertas

1. **Servicios más baratos que la señal.** 20 servicios de las familias con
   fianza cuestan menos de 50 € (mechas de gorro 18-24 €, flequillos 40-45 €,
   grey blending corto 40 €). Ahora mismo se quedan **sin señal**, porque pedir
   50 € por un servicio de 24 € no se sostiene. ¿Los deja así o quiere una señal
   más pequeña para ellos?
2. **"Pack grey blending largo" son 8,8 h** (5,4 trabajando + 3,4 esperando). Se
   llama "largo" pero casi todos sus pasos son de **extra largo**, y lleva **dos
   matices** (uno extra largo y otro corto-corto medio). Conviene que lo revise.
3. **"RECOGIDO"** desapareció de su tabla nueva, y el "Pack maquillaje y
   recogido" lo usaba como paso: ese pack se calcula sin él.
4. **Lucía y Jose**: qué servicios hacen de verdad (su columna "Operario" no los
   nombra; de momento hacen los marcados "Todos") y qué horario tienen (ahora, el
   de Alicia: 09:00-20:30).

---

## Bloqueado

**Stripe**: su cuenta figura conectada pero sin `charges_enabled`, así que los 65
servicios con señal **se reservan sin cobrarla**. Se espera a la verificación de
Meta antes de retomarlo (decisión del 20-ago).

---

## Descartado (decisión cerrada, 21-ago)

**Repartir un servicio entre dos profesionales** cuando no hay hueco para una
sola: *"si no hay 90 minutos de una, pero sí 45 de dos, que la monten a medias"*.
**No se va a hacer.** Decisión de Pablo tras valorarlo.

Los motivos, por si vuelve a plantearse:

1. Unas mechas de 90 minutos no son 45 + 45: hay pasos que dependen del anterior,
   y que dos puedan trabajar a la vez depende de la técnica y del pelo de esa
   clienta. **Su Excel no dice qué servicios son divisibles** — la columna
   "Operario" dice quién está capacitada, que es otra cosa.
2. Habría que buscar pares de huecos solapados entre dos profesionales dentro del
   motor de disponibilidad, que es la pieza de la que han salido los fallos más
   serios (solape concurrente, tiempos de espera).
3. Una cita tiene UN profesional: meter dos toca calendario, avisos,
   recordatorios, detalle de cita e informes.
4. Si el sistema se equivoca, **lo paga la clienta**: se planta en el salón con
   una cita que no se le puede atender.
5. Ya hay solución, y la propuso ella: si no hay hueco, que llame y lo cuadran
   ellas, que son las que saben si ese día pueden. Hecho y desplegado.

Su columna "Operario" **no** expresa eso: dice quién está capacitada para cada
servicio, que es otra cosa (y esa sí está aplicada).

---

## Si hay que reimportar su Excel

`scripts/importar_catalogo_excel.py` lee sus dos hojas y calcula duraciones,
precios, categorías, señales y tramos de espera. **Ojo con dos cosas** que no
salen de su tabla y habría que volver a aplicar:

- La señal de **grey blending y cambios de color**: sus filas FIANZA solo nombran
  extensiones y "mechas-alisados-decoloraciones-balayage-permanente". Lo demás lo
  confirmó por WhatsApp. Lo ideal es que lo añada a su Excel.
- Que **Alicia no tenga lista de servicios** (los hace todos): así los servicios
  nuevos le entran solos. Enumerarlos fue lo que provocó que el panel dijera "el
  servicio seleccionado no está disponible para ese profesional".
