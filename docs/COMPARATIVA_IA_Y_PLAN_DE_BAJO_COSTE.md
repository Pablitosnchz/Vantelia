# Comparación verificable y plan de bajo coste

16-sep-2026. Auditoría documental de fuentes primarias y lectura estática del código
de Vantelia en main `e2b4058` (código desplegado `30c5e15`, versión `c110bd9`).
No es una auditoría independiente de proveedores ni un ensayo comparativo de sus
productos. No conocemos sus costes internos, tasas reales de éxito o arquitectura
privada. No se ejecutaron pruebas nuevas, modelo real ni consultas de producción.

## Fuentes consultadas y comparación

Se eligen empresas con documentación técnica pública relevante; no representan a
todas las agencias. Los beneficios propuestos para Vantelia son inferencias de esta
comparación, no resultados medidos ni promesas comerciales.

| Referencia primaria | Práctica documentada | Vantelia verificado | Decisión |
| --- | --- | --- | --- |
| [Rasa: Writing Flows](https://rasa.com/docs/pro/build/writing-flows/) | El modelo interpreta y genera comandos estructurados; los flujos expresan lógica de negocio y reparaciones conversacionales | Estado y propuestas persistidos, pero selección de servicios todavía depende de patrones en `agent` | Adoptar el principio mediante un piloto sobre nuestra selección. No migrar a Rasa |
| [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | Empezar simple, añadir complejidad con evidencia y cuidar el contrato de herramientas | Núcleo compartido y un agente; varias correcciones compiten dentro de seis vueltas | Conservar la infraestructura; separar validación final de reintento |
| [Anthropic: evaluaciones](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Evaluar efectos, distinguir regresión de capacidad y éxito ocasional de consistencia entre intentos | Banco aislado con comprobación de citas, primer intento/reintentos y críticos repetidos | Ya alineado en buena parte. Ampliar casos concretos, no construir otro banco |
| [Intercom Fin: escalado](https://www.intercom.com/help/en/articles/12396892-manage-fin-ai-agent-s-escalation-guidance-and-rules) | Ofrecer o ejecutar relevo ante peticiones/bucles; distinguir criterio de escalado y destino disponible | `inbox` ya tiene paso a persona y silencio del bot; `reserva` cuenta falta de progreso en algunos recorridos | Reutilizarlo si queda un bucle tras los arreglos. No añadir escalado global ni prometer atención sin destino |
| [Langfuse: trazas](https://langfuse.com/docs/observability/best-practices) y [consumo](https://langfuse.com/docs/observability/features/token-and-cost-tracking) | Relacionar llamadas, modelo, uso, coste y contexto de ejecución | Ya hay tokens, costes aproximados, herramientas, frenos, vueltas y latencia | Completar cobertura local. No contratar ni desplegar otra plataforma ahora |

## Evidencia local y límites

- `backend/trazas.py:79`: `Traza`, con `tool`, `freno`, `modelo`, `vuelta` y
  `guardar`; `:245` ya agrega costes, latencia media y frenos por negocio.
  La tarifa es aproximada; `:66` devuelve cero si no conoce el modelo.
- `backend/intents.py:128`: `sellos_del_tenant(cliente_id, ambitos=...)` y caché
  invalidada por huellas. Reutilizarlo; no crear otro sistema de versiones.
- `backend/reserva.py:374` y `backend/conversation_state.py:25`: carga/guardado
  con revisión CAS. Propuestas con ID, revisión de configuración y aceptación
  después de oferta acreditada (`reserva.py:256–329`). Ya existen, no reconstruir.
- `scripts/evaluar_asistente.py:338–405` comprueba efectos; `:466–479` separa
  resultados; `:535–555` identifica ejecución y exige aislamiento de la copia.
- `backend/agent.py:4032` tiene seis vueltas, que incluyen herramientas y
  correcciones: no son seis reescrituras. Muchos frenos se condicionan a que quede
  otra vuelta (`:4252`, `:4492`). Retorno normal en `:4507–4516`; cierre extra
  sin herramientas en `:4967–4985`. Este último no recorre esos validadores.
  **Hueco de validación observado, pendiente de reproducción causal; no incidente
  nuevo confirmado.**
- `backend/intents.py:406–434,644–676` usa JSON y comprobaciones parciales.
  `backend/agent.py:4533–4541` parsea argumentos sin exigir objeto antes de `.get`.
  JSON sintácticamente válido no garantiza forma, tipos o autorización.
- La llamada final adicional no suma uso mediante `traza.modelo` en el camino
  inspeccionado; sí lo hace la llamada del bucle (`agent.py:4160–4166`). Las llamadas
  propias de `intents` tampoco registran uso en ese archivo. No se ha auditado toda
  la facturación: esto muestra cobertura incompleta, no un porcentaje de infracoste.
- `backend/inbox.py:74–95,148` ya configura paso a persona y contempla canales
  sin retorno; `reserva.py:110` y `agent.py:4852` ya contemplan repetición sin progreso.

## Qué merece entrar ahora

Estimaciones orientativas de esfuerzo técnico, no presupuesto cerrado ni plazo
garantizado. No incluyen esperas de revisión o ejecución de banco. No requieren
licencias ni servidores nuevos; consumen desarrollo, tests, almacenamiento y, al
medir, API del modelo. No se puede calcular ahorro en euros sin una base de uso.

| Bloque | Esfuerzo estimado | Coste recurrente incremental | Valor/riesgo | Decisión |
| --- | --- | --- | --- | --- |
| A. Validación también en última vuelta y cierre | 4–8 h | Sin nueva llamada al modelo; posible ahorro al evitar cierre inútil, a medir | Alto valor de integridad; riesgo medio si se retiran respuestas válidas | Sí, primero reproducir |
| B. Contrato JSON local de entradas | 3–6 h | Validación local, sin llamada adicional | Evita errores por formas/tipos inesperados; riesgo bajo-medio de rechazar entradas válidas | Sí, cambio separado |
| C. Completar consumo y contexto de trazas | 3–6 h | Un poco de escritura/almacenamiento; sin modelo adicional | Permite localizar costes y frenos; cambio de comportamiento mínimo | Sí, reutilizando panel e informe |
| D. Selección estructurada de servicios | 2–4 jornadas para piloto | Objetivo: reutilizar llamada actual; incremento posible a medir | Ataca el problema de fondo, pero afecta reservas y no es un parche pequeño | Diseñar ahora; activar después de validar A–C |
| Nueva plataforma Rasa/LangGraph/Langfuse, varios agentes, fine-tuning | No estimado | Dependencias, operación y posible API/licencias | Beneficio incremental no demostrado aquí | No ahora |

### Fase A — una respuesta final siempre validada

Copiar los patrones de simulación de modelo de
`tests/test_freno_de_precio_tras_rechazar_el_diagnostico.py` y los verificadores
existentes de `agent`; no incorporar otro modelo supervisor.

1. Reproducir salida con precio prohibido o cita inexistente en última vuelta y
   cierre, junto a respuestas válidas de control. Si no se reproduce un recorrido,
   documentarlo y no fabricar un arreglo.
2. Separar comprobar una infracción de decidir si queda presupuesto para corregir.
   Reutilizar la misma comprobación en ambos retornos; no duplicar listas de frases.
3. Si no queda presupuesto y la respuesta incumple, producir una salida basada en
   el estado comprobado. Si hubo una operación ejecutada, conservar su resultado;
   nunca decir que no se reservó simplemente por agotar llamadas.
4. Verificar que no aumenta el máximo de llamadas y que no se pierden avisos de
   negocio, confirmaciones reales ni vías de recuperación. Registrar el motivo.

### Fase B — contratos pequeños en las fronteras

Reutilizar modelos/validación ya usados en el repositorio y el patrón de tipos
finitos de `reserva._estado_desde_snapshot`; interfaces reales: `intents.classify`
y parser de tools en `agent`. Definir campos permitidos para cada entrada, no un
esquema universal que rechace parámetros válidos de herramientas distintas.

Probar objeto válido, `[]`, `null`, tipos incorrectos, enum desconocido, NaN/infinito,
campos extra y límites. La recuperación debe pedir el dato o producir un error
controlado, sin ejecutar ni mutar una reserva. No sustituir autorizaciones del
núcleo por validación de formato. No asumir soporte de esquema estricto del
proveedor: no es necesario para este primer cambio local.

### Fase C — gasto y diagnóstico completos, sin otra plataforma

Extender `Traza.modelo`/`guardar`, `resumen_del_dia` e informe existente. Contabilizar
cierre e interpretación una sola vez; distinguir herramientas/correcciones de
reintentos de transporte. Modelo desconocido = coste desconocido, no gratis.
Mantener coste aproximado claramente etiquetado y tarifa/version identificable.
Adjuntar huellas ya disponibles sin recalcular todas las tablas en cada llamada.

Casos: varias llamadas suman una vez; cierre cuenta; sin usage se declara faltante;
tarifa desconocida no reduce artificialmente el promedio. Mostrar cobertura de
consumo junto al total, p95 de latencia, distribución de vueltas y frenos repetidos.
No añadir contenido personal nuevo ni exportar conversaciones a terceros.

### Fase D — piloto del patrón Rasa sin migración de plataforma

Aplicar `PLAN_TECNICO_POSTDESPLIEGUE.md` solo a añadir/quitar/sustituir servicios:
propuesta estructurada del modelo, validación por tenant/catálogo, transición única
en `reserva`, resumen explícito y aceptación posterior. Reutilizar propuestas y CAS.
Una mención o inferencia ambigua no autoriza quitar servicios. La confianza que el
modelo se asigna no sustituye la evidencia ni la autorización del usuario.

Comparar en copia contra el mecanismo actual usando los mismos casos de negación,
sustitución, ordinales, preguntas y cambio de profesional. Si mejora sin perder
seguridad, retirar el decisor reemplazado en ese alcance. No mantener dos motores
activos ni empezar por reescribir creación/cancelación/reprogramación.

## Puerta de decisión y verificación

Usar base desplegada identificada y casos del banco existente; no inventar otro
benchmark para favorecer el cambio. Por candidato: regresiones causales y controles,
pruebas dirigidas, una suite completa estable, revisión del SHA exacto y, si cambia
conversación, banco comparable de Alicia/otro negocio con críticos repetidos.

Exigir cero nuevas escrituras no autorizadas, citas duplicadas o confirmaciones
falsas en los casos comprobados. Conservar primer intento, reintentos, fallos y no
medidos; comparar también preguntas adicionales, llamadas y latencia. No vender
una muestra verde como 100% de fiabilidad futura.

No prometer ahorro porcentual. Medir consumo por conversación/caso resuelto con
cobertura suficiente; un fallback que evita atender a todas las clientas es barato
pero fracasa. Si el piloto no mejora errores/repeticiones sin degradar éxito o coste,
no se activa. Cambios de medición solos no exigen repetir el banco conversacional
ya validado, salvo que alteren su ejecución.

## Recomendación

Sí merece la pena empezar A y B ahora en ramas aisladas, y completar C antes de
decidir gastar en infraestructura o un modelo más caro. D es el siguiente trabajo
arquitectónico, primero piloto. El mayor beneficio inmediato procede de cerrar
recorridos existentes y medirlos bien, no de comprar más piezas.

Este documento no inicia implementación, pruebas, suscripciones, monitorización
ni despliegues. Coordinar un propietario por bloque con Claude; producción queda
en la referencia aceptada hasta una nueva entrega autorizada por Pablo.
