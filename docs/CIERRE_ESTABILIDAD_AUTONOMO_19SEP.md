# Cierre de estabilidad: trabajo independiente de los clientes

19-sep-2026. Orden de Pablo: cerrar todo lo posible por nuestra parte.
Base `e43baca`, código desplegado `0cb61de`. No repetir su suite de 3025 aprobados
ni su humo 5/5. Es evidencia del bloque anterior, no del código que se añada aquí.

## Reparto y alcance

Astra coordina en `astra/cierre-estable-19sep` (`E:/Vantelia-astra-cierre`).
Un agente implementa la autoridad persistida en `astra/pausa-atencion-19sep`
(`E:/Vantelia-astra-pausa`); otros revisan fronteras y contrato de medición.
Claude recibe el candidato exacto para revisión/medición cuando esté preparado;
no duplica estos módulos. Sin push, despliegue, secretos, operaciones en producción
ni mensajes a clientas. Las copias para modelo deben tener procedencia conocida y
transportes interceptados. D continúa aparcado, sin habilitarlo para aparentar cierre.

La guía de ejecución por fases se usa para implementar y revisar por separado.
La indicación genérica de hacer push entre fases no se aplica: prevalece la orden
de Pablo de no hacerlo sin autorización. Una sola persona/proceso ejecuta cada
grupo de pruebas y la suite completa del candidato estable.

## Entregas y puertas

| Fase | Entrega | Cómo se acepta |
| --- | --- | --- |
| 1 — en implementación | Autoridad persistida de atención, migración, lectura sin caché, transición CAS y auditoría. No hay control público de pausa efectiva todavía. | Aislamiento de tenants, ausencia de fila, errores de DB, reinicio, concurrencia, valores inválidos e idempotencia. Revisión independiente antes del commit. |
| 2 — pendiente | Admisión de trabajo/envíos por versión y conexión de chat/WhatsApp; respuesta humana autenticada conservada. | Pausar antes del modelo y durante su respuesta; pausa/reactivación no revive trabajo viejo; fragmentos y callbacks cubiertos; dos tenants. |
| 3 — pendiente | Avisos, recordatorios y otros automatismos; voz y estado de operaciones en tránsito. | No enviar por canal alternativo al suprimir; no contar una supresión como entrega; resultados conocidos/desconocidos diferenciados. No prometer silencio de una sesión que no pueda revocarse. |
| 4 — pendiente | Operación administrativa de pausa y reactivación con estado visible y cobro separado. | Solo habilitar la operación completa cuando las fronteras de los canales estén cubiertas. Preservar acceso humano, cuenta, configuración y datos; no inventar reglas de facturación. |
| 5 — pendiente | Candidato integrado y aceptación comparable. | Dirigidos y revisión por fase, una suite completa estable y revisión exacta; banco con modelo para Alicia y otro negocio sobre condiciones/copia comparables. |

La primera fase por sí sola no significa que ya funcione la pausa. Una tabla
sin canales conectados es infraestructura; se registra como tal. El diseño de
detalle está en [PAUSA_TEMPORADA_DISENO.md](PAUSA_TEMPORADA_DISENO.md).

## Evidencia y cierre

- Registrar por avance hora Europe/Madrid, rama/SHA, archivos, comando/resultados
  y siguiente paso en ESTADO_ACTUAL y REGISTRO_CONSOLIDACION.
- Comprobar comportamiento causal antes/después cuando se corrige un fallo.
  No cambiar un test de regla para ocultar una regresión ni validar por texto del diff.
- La medida registra fuente y fecha de la copia, configuración, banco, modelo,
  calendario y código. Separar primer intento, reintentos, fallos, no medidos y
  no aplicables. No mezclar muestras del catálogo antiguo y el actualizado.
- Conectar y recibir en Meta real, datos pendientes de Alicia y autorización
  de cobro son dependencias externas. La falta de esos datos no impide cerrar
  código/contratos y pruebas aisladas, pero no se marca como operación verificada.
- No cerrar el objetivo por pytest verde: queda la evidencia operativa y del
  modelo. Si solo quedan bloqueos externos, documentarlos y dejar claro que no
  hay procesos trabajando. Cada fase interna pendiente mantiene su dueño y alcance.

## Registro inicial

19-sep 19:33 Europe/Madrid: fase 1 en implementación sobre `e43baca`; auditoría
de fronteras y contrato de medidas en paralelo. Ninguna suite completa ni banco
con modelo activo. Claude tiene el reparto y la consulta sobre copias existentes.
