# Que la IA entienda, y que cada negocio le diga qué hacer

## El problema, medido

De **19 formas naturales de pedir cita, el asistente reconoce 2**:

```
✓ quiero agendar una cita        ✗ me pones una cita?
✓ agendar cita                   ✗ tenéis hueco para un corte?
                                 ✗ quiero pedir hora
                                 ✗ resérvame el jueves
                                 ✗ apúntame para el martes
                                 ✗ me gustaría ir el viernes
                                 ✗ hazme un hueco
                                 ✗ …y 10 más
```

La causa no es un patrón mal escrito: es que **estamos usando expresiones
regulares para adivinar intenciones**. Cada variante nueva es un parche, y el
español tiene infinitas maneras de pedir cita. Hoy se arregla "agendare", mañana
aparece "me pones una". Esa carrera no se gana.

Y hay un segundo problema encima. Las reglas del negocio —lo que de verdad
diferencia a un cliente de otro— viven hoy repartidas entre el prompt, las Q&A y
sus etiquetas. Este es un requisito real de un salón:

> *"Solo tiene que pedir foto cuando quieran cita para alisado **pero** quieran
> presupuesto: entonces se le pide la foto por detrás y se le dice que en breve
> nos pondremos en contacto para darles el precio nosotros."*

Eso es **intención + servicio → acción + respuesta**. Hoy se sostiene con una
instrucción en el prompt (que el modelo puede ignorar) y una Q&A con etiquetas
escritas a mano, una por cada forma de preguntarlo. Frágil por los dos lados.

---

## El diseño

Tres piezas, cada una con una responsabilidad clara.

### 1. Comprensión: el modelo dice QUÉ quiere el cliente

Una sola llamada barata (`gpt-4o-mini`) que devuelve estructura, no texto:

```json
{
  "intencion": "presupuesto",
  "familia": "alisado",
  "servicio": "keratina premium",
  "fecha": null,
  "confianza": 0.93
}
```

Intenciones cerradas: `reservar · cancelar · reprogramar · disponibilidad ·
precio · presupuesto · info · pago · agradecimiento · queja · otro`.

Las familias salen del **catálogo del propio tenant**, así que no hay nada
hardcodeado: en un salón serán alisados y mechas, en una clínica serán
tratamientos.

Los patrones actuales **se quedan como atajo**: si uno casa, no se llama al
modelo. Rápido y gratis para lo evidente; el modelo solo entra en lo dudoso, que
es justo donde hoy fallamos.

### 2. Reglas del negocio: el negocio dice QUÉ HACER

Tabla `business_rules` por tenant. Una regla es **cuándo → entonces**:

| cuándo | entonces |
| --- | --- |
| `intencion=presupuesto` + `familia=alisado` | `pedir_foto` + responder *"mándanos una foto por detrás…"* + `avisar_al_equipo` |
| `intencion=precio` + `familia∈(mechas, balayage, grey, color)` | responder *"hay que verlo"* + `ofrecer_cita(diagnostico, 15min)` |
| `intencion=reservar` | `mostrar_formulario` |
| `intencion=agradecimiento` | `anteponer("¡Gracias a ti! 😊")` |
| `intencion=disponibilidad` + `sin_hueco` | responder *"llámanos y te lo cuadramos"* |

Acciones disponibles (el catálogo lo definimos nosotros, el negocio las combina):

```
responder_texto · mostrar_formulario · ofrecer_cita(servicio)
pedir_foto · pasar_a_humano · avisar_al_equipo
enviar_enlace_pago · consultar_disponibilidad · no_dar_precio
```

### 3. Ejecución

El orden de siempre, con las reglas en medio:

```
saludo → reglas por palabra clave → REGLAS DE NEGOCIO → Q&A → heurísticas → RAG
```

Gana la primera regla que casa (por prioridad). Si ninguna casa, todo sigue
exactamente como hoy.

---

## Por qué esto reduce los fallos

| Hoy | Con esto |
| --- | --- |
| "quiero agendare una cita" no abre el formulario | El modelo entiende que quiere reservar |
| Hay que escribir "presupuesto **de un** alisado" y "presupuesto **para un** alisado" como etiquetas distintas | Una regla: `presupuesto + alisado` |
| Lo que quiere el negocio vive en un prompt que el modelo puede ignorar | Es una regla determinista que se ejecuta siempre |
| Cada cliente nuevo me necesita a mí para afinar patrones | El negocio lo configura en su panel |

---

## Cómo se hace sin romper nada

**Flag por tenant.** Se activa en un cliente (Alicia), el resto sigue con el
camino de siempre. Si algo va mal, se apaga y vuelve al comportamiento actual sin
desplegar nada.

Y si la llamada al modelo falla o tarda, **se cae al flujo actual**: el
clasificador nunca puede dejar a un cliente sin respuesta.

---

## Fases

**A · Comprensión** (lo que más impacto tiene, y lo más acotado)
`intents.classify(cliente_id, mensaje)` → intención + familia. Se enchufa donde
hoy fallan los patrones. Sin él, las 17 frases de arriba seguirán fallando.

**B · Reglas** Tabla + motor + las acciones de la lista. Se migran a reglas las
tres cosas que Alicia tiene hoy en el prompt (no dar precios, foto del alisado,
extensiones).

**C · Panel** Pantalla "Reglas del asistente": *cuando* [intención] + [servicio]
*entonces* [acción] + [mensaje]. Es lo que te hace independiente para dar de alta
clientes nuevos sin tocar código.

**D · Herramientas (a futuro)** El asistente de voz **ya funciona así**: el
modelo decide cuándo llamar a "crear cita" o "consultar disponibilidad". Unificar
el chat con ese mismo mecanismo eliminaría la capa de adivinar por completo. Es
el destino natural, pero es un cambio grande y no bloquea nada de lo anterior.

---

## Coste y riesgo

| Fase | Riesgo | Nota |
| --- | --- | --- |
| A | Bajo | Función nueva, con caída al comportamiento actual |
| B | Medio | Toca el orden de capas del chat; mitigado con el flag |
| C | Bajo | Pantalla nueva, no toca el motor |
| D | Alto | Reescribe la decisión del chat |

Coste por mensaje de la fase A: una llamada de `gpt-4o-mini` **solo cuando los
atajos no resuelven**. Fracciones de céntimo, y únicamente en los mensajes que
hoy contestamos mal.
