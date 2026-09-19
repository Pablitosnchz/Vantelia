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
| 1 — integrada | Autoridad persistida de atención, migración, lectura sin caché, transición CAS y auditoría. `3fad6f2`, integrado en `b5fd11b`. No hay control público de pausa efectiva todavía. | Revisión independiente OK; 67 dirigidos aprobados, casos causales de IDs/fecha y mutación CAS acreditados. |
| 2 — parcial | 2a integrada en `6458b5`: tickets y admisión de envíos, 112 dirigidos y revisión OK. 2b integrada en `f6c16e1`/`25b84e4`: diario común, contexto y mutaciones de agenda, 108 dirigidos de integración y 78 finales, revisión OK. 2c-chat en preparación; WhatsApp e historial tras emisión pendientes. | Pausar antes del modelo y durante su respuesta; impedir efectos nuevos si gana la pausa, conservar los ya admitidos; pausa/reactivación no revive trabajo viejo; fragmentos y callbacks cubiertos; dos tenants. |
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

19-sep 19:56 Europe/Madrid: fase 1 integrada tras revisión y pruebas dirigidas;
evidencia en `E:/Vantelia-astra-pausa-evidencia/FASE1.md`. Fase 2a en implementación.
El instrumento del banco pasa a exigir una sola cita nueva activa: revisión pide
comparar la identidad con el estado anterior para no contar una cita antigua.
No hay suite completa ni medición con modelo iniciadas. Un solo ejecutor de pytest.

19-sep 20:18 Europe/Madrid: fase 2a revisada e integrada en `dfcc62b`; banco corregido
`e8a8b6` integrado en `08e541e`, 13 dirigidos y causales incluida la lectura SQL.
Claude confirma que no existe snapshot saneado actual; el contrato comparable
registra esa dependencia, sin acceder a storage. Fase 2b y propagación de contexto
en hilos se ejecutan en ramas separadas. Todavía ninguna conexión de canales ni
suite completa ni modelo real sobre estos cambios.

19-sep 21:01 Europe/Madrid: fase 2b integrada tras revisión exacta de diez archivos,
acta y hashes; 16 fallos causales corregidos y mutación de admisión 3 fallos →
3 aprobados, sin repetir suite completa. Continúa fase 2c-chat: backend en rama
de pausa, widget en rama propia y auditor de efectos auxiliares solo lectura.
Ningún capturador de canal integrado todavía, ni proceso de banco/modelo activo.

## Contrato del corte de chat — 19-sep 21:08 Europe/Madrid

- Conservar validaciones de tenant, origen, límite de peticiones y mensaje.
  Capturar el ticket antes de cuota y preparación; vigencia técnica de 120 s,
  explícita en el adaptador, no una política configurable del negocio.
- Comprobar la salida en ASGI antes del primer envío. Registrar respuesta y
  consumo tras el último cuerpo emitido; esto acredita emisión del servidor,
  nunca lectura del navegador. Una emisión incierta no se convierte en entrega.
- HTTP 409 `ATTENTION_STOPPED` para supresión conocida y 503
  `ATTENTION_UNAVAILABLE` si no puede verificarse. El widget presenta un estado
  accesible fuera del historial, sin burbuja de asistente, acciones ni reintento.
- El motor RAG del turno HTTP parte del historial persistido; no se restaura ni
  borra memoria compartida después de un fallo. El recorrido actual de WhatsApp
  mantiene su motor hasta su propio corte de integración.
- Extender el mismo diario con `pago/crear_enlace`: el refresh previo de Connect
  modifica capacidades, métodos y BD, y debe estar bajo la admisión antes de CRM
  y Checkout. Identidad estable y referencia `pay_` conocida tras commit; perder
  la respuesta del proveedor conserva incertidumbre, sin crear otro enlace.
- Los avisos de la operación ganadora tienen admisiones propias. Suprimir un
  aviso no debe interrumpir política, reembolso o CRM, ni iniciar canal alternativo.
  El origen de una cita puede elegir SMS aunque la petición llegue por chat.
- Estos son criterios de implementación/revisión, todavía sin veredicto ni
  pruebas terminadas de este corte. No habilitar una operación global de pausa.
