# Acta de estabilización — 19 septiembre 2026

Base `60993b7`. Candidato técnico **19ad09e**, revisión independiente **OK** de
Claude y suite completa comunicada **3025 passed, 1 skipped, 26m32s**.
Desplegado por Claude por orden de Pablo como **0cb61de**, humo comunicado **5/5**
(registro `ef8f2b4`). Este cierre es acotado a la estabilización implementada;
Astra no ha operado sobre producción ni iniciado conexiones/cobros.

## Evidencia completada

| Cambio o revisión | Evidencia | Resultado |
| --- | --- | --- |
| F4 contador de recordatorios, `83e5c56` | Antes: 2 rojos sin canales, 2 positivos verdes. Después: 48 dirigidos verdes (247.57s), incluyendo envíos, omisiones, reintentos, concurrencia y cambios de cita. Revisión independiente de código: OK acotado. | Corregido en candidato. Sin alterar audit/cierre de omitidos. |
| `b417618` teclado catálogo | Test adicional del manejador real con 301 servicios: 1 verde (4.03s); no elige invisible y el filtro alcanza último servicio. Fichero de portal también dentro de 48. | OK acotado, cobertura `eb74dc7`. |
| `0c0838c` fianza email | Lectura de diff y tests de fianza incluidos en 48: confirmed no pagada, pagada, sin depósito, cancelada. | OK acotado; no prueba cobro real Stripe. |
| `73f3302` CRM y `c484131` reparto | Revisor independiente: 66 existentes y 5 nuevos verdes; caso CRM tras limpieza verde. Código base `60993b7`. | OK acotado; cobertura integrada `ff45f3a`. |
| Supresión de aviso 2h, `d9ed572` | 1 dirigido verde; el doble devuelve ahora el contrato real de aceptación. | Conserva la regla de no recordar de nuevo a quien ya confirmó. |
| Aislamiento del portal ES/EN | 5 casos HTTP verdes (45.59s): respuestas por negocio, edición sobre conversaciones existentes y rechazo de lectura/edición/borrado ajenos. | Dos tenants ficticios, sin modelo ni Meta. No acredita pausa de temporada. |
| Apuntes, integración `7534f81` | Dos entregas comparadas: `3c646b0` y `93416aa`; se conserva la segunda, mismo diseño con igualdad de talla y pruebas del resolvedor real. Claude declara 20/20 y 5 mutaciones rojas. | Una implementación, no se suman ambas entregas como avances distintos. |
| Revisión adicional de apuntes | Media melena: 75 frente a 360; balayage descartado: 60 genéricos. Ambos rojos en base (26.47s) y en `93416aa` integrado (30.82s). Tras guardia compartida, 22 verdes (91.50s). | Reusa alias de `catalog_pick`, exige conservar lo escrito y retira el guardia que bastaba con compartir una palabra. |
| Nombres exactos con separadores | La revisión señaló paréntesis; paréntesis y guion: 2 rojos (26.39s). Texto y catálogo pasan ahora por el mismo separador. Dirigidos finales de apuntes y shim: 29 verdes (100.17s). | Revisión independiente de lectura sin nuevos hallazgos. |

No sumar ejecuciones solapadas como casos únicos ni atribuir suites de antecesores
al candidato nuevo. Los tiempos son de las ejecuciones informadas por las herramientas.
El contador de recordatorios acredita aceptación conocida (también recuperada de
una interrupción), no nuevas llamadas al transporte ni recepción de la clienta.

Incidencias de la validación: el primer proceso de aislamiento se interrumpió por
memoria insuficiente sin resultado. Dos ejecuciones posteriores tuvieron 5 errores
de preparación cada una: email `.invalid` rechazado por el esquema de login y
cookie Secure sobre HTTP. Se corrigió la fixture a `example.com` y HTTPS; no son
regresiones demostradas del producto ni se cuentan como casos medidos.

## Pendiente del cierre operativo completo

- Revisión y suite del SHA exacto terminadas por Claude: detalle al final.
  No ejecutar otra suite de `19ad09e` por una petición automática atrasada.
- Procedimiento de pausa documentado: conjunto de silencio, facturación y
  reactivación aún no implementado/verificado. No se cierra por el verde de aislamiento.
- Diseño de la siguiente entrega: [PAUSA_TEMPORADA_DISENO.md](PAUSA_TEMPORADA_DISENO.md),
  `6a43942`. Autoridad persistida, admisión de envíos y cobro separado; sin código
  vivo ni pausa efectiva acreditada.
- Evaluar qué medición real comparable corresponde al cambio final: tabla separada
  Alicia/segundo negocio, primer intento/reintentos/fallos/no medidos/no aplica.
  Por ahora esta entrega no tiene nuevos resultados de modelo real.

| Modelo real del candidato nuevo | Primer intento | Tras reintento | Fallos | No medidos |
| --- | --- | --- | --- | --- |
| Alicia | No ejecutado | No ejecutado | No ejecutado | Banco completo |
| Segundo negocio | No ejecutado | No ejecutado | No ejecutado | Banco comparable completo |

El intérprete de apuntes y las reglas ES/EN de estos tests son deterministas: no
consumen modelo. No se relanzan bancos anteriores como si probaran el nuevo SHA,
ni se presenta esta tabla como aceptación del agente completo. La entrega no
cambia los prompts ni habilita el piloto D.

## Dependencias y límites externos

- Alicia: arranque noviembre, respuestas de catálogo aún pendientes; Stripe y
  WhatsApp sin conexión según último relevo. No se inventan datos ni políticas.
- Cap Rocat: documentación/respuestas y conexión pendientes; la pausa contractual
  no tiene un proceso conjunto verificado de silencio, cobro y reactivación.
- Meta: aceptación de transporte simulado no acredita entrega al teléfono. Prueba
  externa solo con entorno y destinatario autorizados, nunca clientas reales.
- Make: retirada ya documentada en producción; no repetir. D aparcado.

`19ad09e` queda como «candidato técnico verificado» para los cambios implementados;
«arranque operativo» exige además cumplir las dependencias del negocio y del canal,
y este acta no declara acabado el plan de consolidación completo.

## Revisión y corrección — 19-sep 15:10 Europe/Madrid

- Claude revisó por lectura el SHA exacto `f2003ec`: **CAMBIOS**. Reducir
  «corto o medio» a una talla ocultaba un pack de 360 min frente a un servicio
  corto de 75. F4 recibió OK acotado, con un doble de prueba adicional a corregir.
- Reproducción local: cuatro casos de tallas alternas rojos (38.57s).
  `1caa5af` conserva todas las tallas no solapadas usando el vocabulario existente;
  `talla_de` mantiene su selección anterior. Se comprueban también cinco vectores
  de compatibilidad y el texto sin coma, sin adivinar dónde acaba el nombre.
- Control de recordatorio: rojo con `failed == 1` cuando el doble devolvía `True`
  (ejecución conjunta: 1 failed, 8 passed, 58.03s). `e057f07` devuelve el contrato
  real y exige aceptación sin fallo. No cambia el transporte del producto.
- Validación conjunta final: **41 passed**, 131.32s, en apuntes, intérprete,
  shim, cita cancelada y contador. Revisión independiente del diff: OK por lectura;
  no sustituye la revisión exacta ni la suite completa del nuevo candidato.
- La suite de `f2003ec` empezó a las 14:39:41 y se detuvo a las 14:56:37 al
  invalidarse ese candidato. Aproximadamente 45%, sin fallos observados hasta
  entonces; **interrumpida, no aprobada**. Log y manifest en
  `E:/Vantelia-astra-estabilidad-evidencia/suite-f2003ec.{log,json}`.
- El modo rápido conserva los 30 minutos aceptados por Pablo: sin elegir una
  sugerencia puede guardar una nota con ese tiempo. No se presenta esta entrega
  como eliminación de ese riesgo operativo ni como nuevo resultado con modelo real.

## Aceptación independiente — 19-sep 17:04 Europe/Madrid

- Claude comunicó **OK** sobre `60993b7..19ad09e`, con foco en `f2003ec..HEAD`,
  a las 17:00:54. Fuente: mensaje
  `20260919T150054115013-claude-7f82cc` en `E:/Vantelia/.sincronia/buzon/`.
  Aunque el sobre procede de main `9c3e3b8`, el veredicto nombra explícitamente
  el candidato `19ad09e`; no se atribuye la validación a ese main.
- Suite completa informada por Claude: **3025 passed, 1 skipped, 26m32s**, en
  `E:/vp-rev-19ad09e`. Astra comprobó que esa copia está limpia y en el SHA exacto
  `19ad09ee1bc2f261e99902be20197a9f80448415`; no ejecutó de nuevo los tests ni
  dispone aquí de un log bruto adicional de esa ejecución.
- Lectura aprobada: tallas alternativas y solapes; compatibilidad de `talla_de`;
  prohibición de aceptar una talla más corta; F4 y contrato de los dobles;
  cobertura de los casos nuevos. No queda hallazgo bloqueante de esta revisión.
- Sonda determinista con catálogo real en copia, comunicada por Claude:
  mechas medio/media melena → pack 360; extra largo → 395; media cabeza largo → 60;
  corte señora → 20; quitar extensiones → Kitar. Mechas, alisado largo, ácido
  láctico chico y elumen y secado preguntan. No es banco con modelo ni envío real.
- Límite de esa sonda: `9c3e3b8` documenta a las 16:35 la actualización autorizada
  del catálogo de Alicia: packs corto 195→230, medio 360→350, largo 440→430,
  tras ajustar Elumen y Flash Repair. Una sonda que informa pack medio 360 no
  acredita ese catálogo posterior; falta identificar su copia. No se modifica
  producción desde esta rama ni se atribuyen esos cambios a Astra.
- Matiz no bloqueante: «mechas pelo largo» y «mechas cabello medio» ofrecen en vez
  de aplicar, porque esas palabras cuentan como contenido. Se conserva como
  mejora posterior de comodidad, sin tocar el candidato revisado.
- Incidencia del revisor: el inicio automático de las 15:12 se observó realmente
  (PID 30080). A las 17:02 no había pytest/revisor activos ni resultado localizado.
  No se afirma que nunca arrancó ni se cuenta esa ejecución como aprobada.
  Claude ejecutó después su suite independiente; solo esta tiene resultado final
  comunicado. La petición original quedó enlazada como atendida para impedir
  otra ejecución automática al restablecerse su cuota. No se fabrica un OK del bot.
- Seguimiento posterior a `19ad09e`: solo documentación; no atribuir su SHA a una
  nueva suite. Sin push, despliegue, cambio de catálogo ni mensajes a clientas.

## Despliegue comunicado y merge contrastado — 19-sep 18:39 Europe/Madrid

- Claude comunica despliegue autorizado por Pablo de `0cb61de`, humo **5/5**;
  registro conservado en main `ef8f2b4`. Astra no repite el despliegue ni las pruebas.
- Comprobación local de Astra: `5037515` es antecesor de main y el diff
  `19ad09e..0cb61de` solo contiene documentación. El código desplegado corresponde
  al SHA de la suite y revisión independientes, sin atribuir otra suite al merge.
- Sonda en vivo comunicada por Claude, ya con catálogo actualizado: mechas
  medio/media melena → pack 350; extra largo → 395; mechas sin talla pregunta.
  Resuelve la discrepancia de la sonda anterior (360 frente a 350).
- Humo y sonda son evidencia adicional acotada, no el banco comparable completo
  de Alicia y otro negocio. Pausa de temporada y dependencias operativas siguen
  pendientes. No hay otro proceso de pruebas o implementación activo al registrar.
