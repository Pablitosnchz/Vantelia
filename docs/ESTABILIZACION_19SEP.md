# Estabilización operativa — 19 septiembre 2026

Orden de Pablo: planificar y ejecutar lo independiente de Alicia y Cap Rocat para
dejar una versión estable. Base local `60993b7`; producción según último registro `19b64ff`.
Astra coordina e integra; Claude auxilia con interpretación y revisión final.
No tocar secretos, producción, datos del catálogo ni desplegar/push. D aparcado.

| Bloque | Dueño | Entrega y puerta |
| --- | --- | --- |
| Interpretación de apuntes | Claude, encargo Sincronía | Pendiente: tres repros de `478ae58`, guardias comunes, prueba causal y SHA. Rama `claude/encargo-0b86b3`. Astra revisa antes de integrar. |
| Recordatorios F4 y email F2 | Astra | F4 corregido en `83e5c56`, 48 dirigidos verdes y revisión independiente OK acotado. F2 revisado sin hallazgos nuevos. El contador acredita aceptación conocida, no recepción del teléfono ni llamadas nuevas al transporte. |
| CRM y reparto | Revisión independiente coordinada por Astra | `73f3302`/`c484131`: OK acotado, 66 dirigidos y 5 casos adicionales verdes; cobertura integrada en `ff45f3a`. |
| Pausa/aislamiento de negocios | Revisión independiente coordinada por Astra | Borrador y pruebas integrados en `8671178`; los 5 casos de aislamiento pasan tras corregir la fixture de login (45.59s). No existe una pausa conjunta verificada de cobro, silencio y reactivación. |
| Candidato integrado | Astra y Claude | Una suite completa estable, revisión exacta y evidencia comparable necesaria. No repetir bancos ya válidos ni confundir transportes simulados con Meta real. |
| Relevo | Astra | Estado vigente y acta con primer intento/reintentos/fallos/no medidos, límites y pendientes externos. |

Pruebas con fixtures aisladas y transportes interceptados. No duplicar procesos
de Claude. Integrar pequeños commits; cada avance incluye hora Europe/Madrid,
SHA, evidencia y siguiente paso. Cerrar el trabajo técnico comprobable ahora;
conexión real WhatsApp/Stripe, datos pendientes y documentos firmados no se
declaran completados por tener tests verdes. No añadir automatizaciones ni
compromisos nuevos de producto para aparentar cierre.

Selector del portal: `b417618` revisado con un caso adicional del manejador real
de teclado, 301 servicios y filtrado; verde e integrado en `eb74dc7`.
