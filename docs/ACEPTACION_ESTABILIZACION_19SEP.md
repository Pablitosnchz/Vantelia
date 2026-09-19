# Acta de estabilización — 19 septiembre 2026

Base `60993b7`. Candidato en `astra/estabilidad-19sep`; aún no aprobado para despliegue.
No se han modificado datos de producción ni iniciado conexiones/cobros.

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

## Pendiente antes de aceptación técnica

- Congelar SHA con esta evidencia, ejecutar una suite completa y obtener revisión exacta.
- Procedimiento de pausa documentado: conjunto de silencio, facturación y
  reactivación aún no implementado/verificado. No se cierra por el verde de aislamiento.
- Suite completa única tras integración estable y revisión independiente del
  candidato exacto. Registrar fallos y correcciones si aparecen, no ocultar reintentos.
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

El estado será «candidato técnico verificado» únicamente con su evidencia y revisión;
«arranque operativo» exige además cumplir las dependencias del negocio y del canal.
