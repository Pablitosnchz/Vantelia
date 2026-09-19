# Estabilización operativa — 19 septiembre 2026

Orden de Pablo: planificar y ejecutar lo independiente de Alicia y Cap Rocat para
dejar una versión estable. Base local `60993b7`; estabilización desplegada por
Claude por orden de Pablo como `0cb61de` (registro `ef8f2b4`, humo 5/5).
Astra coordina e integra; Claude auxilia con interpretación y revisión final.
No tocar secretos, producción, datos del catálogo ni desplegar/push. D aparcado.

| Bloque | Dueño | Entrega y puerta |
| --- | --- | --- |
| Interpretación de apuntes | Claude entrega; Astra revisa y completa | `93416aa` integrado una sola vez. Tras revisión CAMBIOS de `f2003ec`, `1caa5af` conserva tallas alternativas y evita ocultar packs largos; cuatro repros causales. Dirigidos finales con shim y recordatorios: 41 verdes (131.32s). Una sola autoridad, sin modelo añadido. |
| Recordatorios F4 y email F2 | Astra | F4 corregido en `83e5c56`, 48 dirigidos verdes y revisión independiente OK acotado. F2 revisado sin hallazgos nuevos. El contador acredita aceptación conocida, no recepción del teléfono ni llamadas nuevas al transporte. |
| CRM y reparto | Revisión independiente coordinada por Astra | `73f3302`/`c484131`: OK acotado, 66 dirigidos y 5 casos adicionales verdes; cobertura integrada en `ff45f3a`. |
| Pausa/aislamiento de negocios | Revisión independiente coordinada por Astra | Cinco casos de aislamiento verdes (45.59s). Diseño técnico `6a43942` preparado; siguiente implementación: autoridad persistida, transición por versión y pruebas de reinicio/aislamiento. La pausa conjunta sigue pendiente. |
| Candidato integrado y desplegado | Claude revisa/despliega; Astra registra | `19ad09e`: OK y suite 3025 passed, 1 skipped, 26m32s. Código idéntico integrado/desplegado como `0cb61de`, humo comunicado 5/5; sonda con catálogo actualizado, pack medio 350. Sin banco comparable completo nuevo; pausa pendiente. |
| Relevo | Astra | Estado vigente y acta con primer intento/reintentos/fallos/no medidos, límites y pendientes externos. |

Pruebas con fixtures aisladas y transportes interceptados. No duplicar procesos
de Claude. Integrar pequeños commits; cada avance incluye hora Europe/Madrid,
SHA, evidencia y siguiente paso. Cerrar el trabajo técnico comprobable ahora;
conexión real WhatsApp/Stripe, datos pendientes y documentos firmados no se
declaran completados por tener tests verdes. No añadir automatizaciones ni
compromisos nuevos de producto para aparentar cierre.

Selector del portal: `b417618` revisado con un caso adicional del manejador real
de teclado, 301 servicios y filtrado; verde e integrado en `eb74dc7`.
