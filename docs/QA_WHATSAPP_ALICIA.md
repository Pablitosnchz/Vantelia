# Prueba corta del asistente de Alicia por WhatsApp

> Actualizado el 16-sep-2026 para la versión candidata del cierre (rama
> `claude/servicio-y-titular`). Es el recorrido corto del bloque 5 de
> [CIERRE_ALICIA_16SEP.md](CIERRE_ALICIA_16SEP.md): hacerlo **después de desplegar**,
> con números de prueba acordados y nunca escribiendo a clientas reales.
>
> Cada paso dice **qué mandar**, **qué tiene que pasar** y **qué sería un fallo**.
> Si algo falla, apunta el número del paso y pega la conversación.

## Antes de empezar

- **Antes de conectar su número:** manda `DEMO YDCP9E` al número de demo (vigente
  hasta el 13-oct). Carga el asistente de Alicia Rincón Estilistas.
- **Con su número conectado:** escribe a su número desde un móvil que no sea de una
  clienta.
- Ten el panel abierto en `https://app.vantelia.es/app` → **Citas**. Varias
  comprobaciones se hacen ahí.
- Para empezar de cero: escribe `hola`.

## 1. Coger cita (lo que más se usa)

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 1 | `quiero cita para un corte de señora` | Te pregunta qué día te viene bien | Que te suelte una lista de días u horas |
| 2 | `el primer hueco que tengas` | Te ofrece dos o tres horas de un día concreto | Que te vuelva a preguntar el día |
| 3 | Eliges una hora | Te pide el nombre | Que te pida el teléfono (ya lo tiene) |
| 4 | `me llamo Ana Ruiz` (un apellido vale) | Llega **📋 Resumen de tu cita** con **✅ Confirmar** y **❌ Cancelar** | Que diga «ya está reservada» sin resumen, o que exija dos apellidos |
| 5 | Pulsa **✅ Confirmar** | **✅ Cita confirmada** con número de reserva R-XXXX | Que no dé número |
| 6 | — | En el panel: la cita con tu nombre, servicio y hora, una sola vez | Que no aparezca o aparezca dos veces |

## 2. Cambiar de opinión (lo que falló el 15-sep)

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 7 | `quiero cita para unas mechas` → `por los hombros` → `pues quiero un grey blending` → `medio` → un día y hora → tu nombre | Resumen del **grey blending**, con quien lo hace | Que pregunte «¿mechas o grey blending?» o salga con Jose |
| 8 | Igual, pero `en vez de las mechas quiero un grey blending` | Lo mismo | Lo mismo |
| 9 | Si en algún momento te pregunta algo | **No** llega el resumen hasta que contestas | Resumen con botones mientras te está preguntando |
| 10 | `quiero unas mechas, tengo el pelo largo` → `no quiero cita para diagnóstico, quiero cita para hacérmelas` | Sigue con las mechas y te pregunta el día | Que vuelva a ofrecerte el diagnóstico |

## 3. Cambiar y anular

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 11 | `necesito cambiar mi cita` | Te dice qué cita tienes (o pide el número de reserva) | Que diga que no la encuentra |
| 12 | `cualquier otro hueco me vale` → `vale, la primera` | **¿Cambiamos tu cita?** con **Sí, cambiar cita** y **Mantener cita** | Que la mueva sin preguntarte |
| 13 | Pulsa **Sí, cambiar cita** (o escribe `sí`) | Confirma el cambio, mismo servicio y mismo número de reserva | Que cambie el tratamiento o cree otra cita |
| 14 | — | En el panel: la cita **se movió**, no hay dos | Que siga en su sitio o esté duplicada |
| 15 | `anula mi cita` | Pide confirmación con **Sí, cancelar cita** | Que la anule sin preguntar |
| 16 | Confirmas | En el panel: cancelada | Que siga viva |

## 4. Las condiciones de Alicia

| # | Le escribes | Tiene que pasar | Sería un fallo |
| --- | --- | --- | --- |
| 17 | `cuánto cuestan unas mechas?` | Sin cifra: cita de diagnóstico de 15 min o llamar | Cualquier cifra en euros |
| 18 | `cuánto vale un corte de señora?` | **Hoy tampoco da precio** (falta la lista de Alicia de servicios con precio) | Una cifra |
| 19 | `me pasáis presupuesto de un alisado?` | Pide foto por detrás | Precio, o no pedir la foto |
| 20 | `quiero coger cita para un alisado` | No pide foto: pregunta el largo | Pedir foto a quien solo quiere cita |
| 21 | `ponéis extensiones?` | Sí, con valoración en persona | Precio |
| 22 | `no me va bien ninguna hora` | Ofrece llamar al salón | Despedirse sin ofrecerlo |

## 5. Cambios desde el panel (lo que el asistente tiene que respetar)

| # | Haces | Tiene que pasar |
| --- | --- | --- |
| 23 | En **Horarios**, pones vacaciones un día abierto | Al pedir cita ese día, el asistente no ofrece horas y propone otro |
| 24 | Quitas las vacaciones | Vuelve a ofrecer ese día |
| 25 | Coges una cita de un **pack** (p. ej. Pack maquillaje y recogido) | En la agenda se ve por pasos (Maquillaje, Recogido), sin «libre» encima de las esperas y sin precios |

## 6. El tono (solo lo juzgas tú)

- ¿Te llama «cariño» con naturalidad? ¿Emojis que encajan, y ninguno si te quejas?
- ¿Te tutea siempre? ¿Suena a alguien del salón?

## Lo que se sabe que no está resuelto

- «Es para mi hija» **sin decir el nombre**: el resumen sale a nombre de quien escribe.
  Se ve antes de confirmar.
- «No quiero el corte tan corto, quiero un elumen» vuelve a preguntar qué quiere: es
  a propósito, para no reservar menos tiempo del que hace falta.
- Si la primera cita de un teléfono es para otra persona, la ficha se queda con ese
  nombre hasta editarla en el panel.
- Recordatorios por WhatsApp: necesitan la plantilla aprobada por Meta y un método de
  pago en su WhatsApp Manager. Sin eso salen por email si la clienta dio email.
- Cobro de la fianza: Stripe sin cobros activados; las citas se reservan sin cobrarla.
