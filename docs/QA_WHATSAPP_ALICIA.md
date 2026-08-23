# Probar el asistente por WhatsApp

> Guion para probarlo como una clienta de verdad. Cada bloque dice **qué mandar**,
> **qué tiene que pasar** y **qué sería un fallo**.
>
> Empieza mandando `DEMO YDCP9E` al número de demo: eso carga el asistente de
> Alicia Rincón Estilistas.
>
> Si algo falla, dime el número del paso y pégame la conversación.

## Antes de empezar

- Ten el panel abierto en `https://app.vantelia.es/app` → pestaña **Citas**. La
  mitad de las pruebas se comprueban ahí, no en el chat.
- Para empezar de cero en cualquier momento: escribe `hola`.
- El banco de casos automático cubre estos 28 flujos, pero **no ve el tono**. Eso
  solo lo juzgas tú.

---

## Bloque 1 — Coger cita (lo que más se usa)

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 1 | `quiero agendar una cita` | Te **pregunta qué te quieres hacer** | Que elija él un tratamiento («vamos a agendar tu Ácido Láctico…») |
| 2 | `quiero cita para un corte de señora` | Te **pregunta qué día te viene bien** | Que te suelte una lista de fechas o de horas |
| 3 | `el primer hueco que tengas` | Te ofrece **dos o tres horas** de un día concreto | Que te vuelva a preguntar el día |
| 4 | Eliges una hora | Te pide **el nombre** y nada más | **Que te pida el teléfono** (ya lo tiene) o el email |
| 5 | `me llamo <tu nombre>` | Te da un **número de reserva R-XXXX** | Que diga «ya está reservada» sin darte el número |
| 6 | — | **En el panel**: la cita aparece con tu nombre, servicio y hora | Que no aparezca, o que aparezcan dos |

## Bloque 2 — Cambiar y cancelar

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 7 | `necesito cambiar mi cita` | Te pide el número de reserva | Que te pregunte «¿qué te quieres hacer?» |
| 8 | `R-XXXX` (el tuyo) | Te dice **qué cita tienes** (servicio, día y hora) | Que diga que no la encuentra |
| 9 | `cualquier otro hueco me vale` | Te ofrece alternativas | Que se ponga a recitar días |
| 10 | `vale, la primera` | Confirma el cambio, **mismo servicio** | Que cambie el tratamiento, o que se quede sin hacerlo |
| 11 | — | **En el panel**: la cita **se movió**, no hay dos | Que siga en su sitio o que haya duplicado |
| 12 | `anula mi cita` → `R-XXXX` → `sí` | Confirma la cancelación | Que diga que la cancela y siga viva |
| 13 | — | **En el panel**: cancelada | — |

## Bloque 3 — Las condiciones de Alicia

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 14 | `cuánto cuestan unas mechas?` | Cita de **15 min** de diagnóstico, gratis | **Cualquier cifra en euros** |
| 15 | `más o menos en cuánto se me queda un balayage?` | Lo mismo, preguntado de otra forma | Que aquí sí dé precio |
| 16 | `me pasáis presupuesto de un alisado?` | Te pide **foto por detrás** y dice que os ponéis en contacto | Que dé precio, o que no pida foto |
| 17 | `quiero coger cita para un alisado` | **No** pide foto: pregunta el largo | Que pida foto a quien solo quiere cita |
| 18 | `ponéis extensiones?` | Sí, pero **diagnóstico en persona** | Que dé precio |
| 19 | `cuánto vale un corte de señora?` | **20 €** — ese sí tiene precio cerrado | Que se lo calle |
| 20 | `gracias` | Empieza con **«¡Gracias a ti!»** | Que no lo diga |
| 21 | `no me va bien ninguna hora` | Te ofrece **llamar al salón** | Que se despida sin ofrecerlo |

## Bloque 4 — Que sepa de lo suyo

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 22 | `me hacéis las cejas?` | **Sí**, y te dice cuáles | «No ofrecemos ese servicio» (sí lo hacen) |
| 23 | `me hacéis la manicura?` | Dice claramente que **no** | Que se lo invente |
| 24 | `cuánto tiempo tengo que estar para unas mechas?` → `por los hombros` | Una duración **real** en minutos | Un rango inventado («de 45 min a 2 h») |
| 25 | `qué servicios tenéis?` | Un resumen por categorías | Que recite 186 servicios |
| 26 | `estáis abiertos ahora?` | Responde **de hoy y de esta hora** | Que suelte el horario semanal |
| 27 | `se me está cayendo mucho el pelo, qué me recomiendas?` | Entiende el problema y recomienda | **Que te proponga un alisado** |

## Bloque 5 — Rompiéndolo como una clienta real

> Aquí es donde salen los fallos que el guion feliz no ve.

| # | Le escribes | Tiene que pasar |
| --- | --- | --- |
| 28 | `kiero pedi ora pa las cejas` (con faltas) | Lo entiende igual |
| 29 | Tres mensajes seguidos: `quiero cita` / `para mechas` / `el viernes` | Los junta, no los trata por separado |
| 30 | A media reserva: `oye y tenéis parking?` | Contesta la duda **y sigue con la cita donde estaba** |
| 31 | A media reserva: `no espera, mejor un corte` | Cambia de servicio; **no** te pide un número de reserva |
| 32 | `asdfgh` | No se rompe ni inventa nada |
| 33 | `cuánto vale un corte?` y **nada más** | **No** te coge cita: no la has pedido |

## Bloque 6 — El tono (esto solo lo juzgas tú)

Léelo entero y pregúntate si suena a alguien del salón:

- ¿Te llama **«cariño»**? ¿Suena natural o forzado?
- ¿Los **emojis** encajan con el momento? (**ninguno** si te estás quejando)
- ¿Te **tutea** siempre?
- Al despedirse, ¿termina con **😉🤗😘**?
- ¿Recomienda como una dependienta, o parece un formulario con emojis?

## Lo que NO se puede probar todavía

- Su **número propio**: sigue en el de demo, pendiente de la verificación de Meta.
- El **formulario dentro de WhatsApp** (Flows): bloqueado por Meta; hoy cae al
  flujo por mensajes, que es lo que estás probando.
- **Cobros**: Stripe sin `charges_enabled`.
