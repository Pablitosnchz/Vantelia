# Cierre de Alicia: objetivo lunes 14 / martes 15 de septiembre

No hay nuevas reglas de Alicia. El único cambio visual solicitado ahora es el
lateral de agenda con la hora y cuatro intervalos de quince minutos.
La fecha objetivo no sustituye revisión ni pruebas reales.

| Imprescindible | Estado comprobado | Evidencia de cierre pendiente |
| --- | --- | --- |
| Crear, cancelar y reprogramar sin falsas confirmaciones | 0b6043f: 2216 tests, 1 omitido; correcciones de retirados y propuestas | Revisión exacta y banco real al primer intento |
| Reglas aisladas y editables | 550aafe: 2217 tests, 1 omitido; apellidos por tenant en Q&A | Revisión y completar auditoría de las demás reglas |
| Horarios, vacaciones, servicios y profesionales | Núcleo compartido y regresiones de cambios del portal | Recorridos reales con configuración de Alicia |
| Agenda con marcas de 15 minutos | Cambio visual implementado; coordenadas y sintaxis verificadas | Revisión visual del candidato |
| Recordatorios WhatsApp | Plantillas y respaldo existentes; estado visible implementado, 39 pruebas dirigidas verdes | Conexión, aprobación, facturación Meta y envío real autorizado a un destinatario de prueba |
| Reentregas, reinicios y errores externos | Hay tests específicos; propuestas aún en estado de proceso | Auditoría y pruebas de recuperación/idempotencia del recorrido integrado |
| Segundo negocio | Reglas configurables y pruebas de aislamiento | Banco comparable con un segundo tenant |
| Aceptación final | No completada | Sin críticos abiertos, resultados iniciales/reintentos/no medidos separados y revisión del SHA final |

Puede esperar: rediseño estético ajeno al eje solicitado, funciones nuevas sin
relación con reservas y cambiar proveedor/modelo sin evidencia de mejora.

Bloqueos externos: Claude sin créditos según último aviso; no se afirma ninguna
medición nueva ni envío real. Se continúa implementación y pruebas locales.
No hacer push ni desplegar sin orden de Pablo.
