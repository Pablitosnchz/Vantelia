# Registro de consolidación de Vantelia

Horas locales Europe/Madrid. Cada entrada distingue hechos verificados, trabajo
activo y esperas. No es un registro de producción ni acredita aceptación final.
No guardar conversaciones, teléfonos, credenciales o datos personales.

## 2026-09-13 01:15 +02:00 — inicio de continuación nocturna

- Pablo autoriza continuar autónomamente el plan y registrar avances con hora.
- Candidato 7ab7775: suite finalizada con 2297 passed, 1 skipped, duración 18 min 55 s; fin 13-sep 01:04 Europe/Madrid; revisión
  solicitada automáticamente. Evidencia: `integrado-wa-suite.result.json` y
  `integrado-wa-suite.log` en C:/Users/pabli/.codex/vantelia-coordination/.
- Claude está sin cuota hasta las 04:00; revisión y calendario esperan. Avisado
  por Sincronía del reparto para evitar duplicados. No implica revisión aprobada.
- Nueva rama astra/gestion-confirmada en E:/Vantelia-astra-gestion; se conserva
  astra/whatsapp-recuperable intacta y no se tocan cambios ajenos.
- En ejecución: agente auxiliar implementa confirmación persistida de cancelación
  WhatsApp; otro inventaría evidencia de banco y requisitos de QA aislada.
- Seguimiento existente actualizado cada 30 minutos para retomar este registro;
  no duplica tareas activas ni consulta repetidamente las suites.
- Pendiente: resto de gestión/canales, recordatorios, entregas y reconciliación,
  banco comparable Alicia/otro, revisión exacta y aceptación real. Sin push ni
  despliegue; no se inventa la política particular de foto/diagnóstico de Alicia.

## 2026-09-13 01:18 +02:00 — referencia real y siguiente prueba

- Auditoría de artefactos saneados: los 42/43 y 43/43 históricos no contienen
  juntos SHA, configuración, calendario y ambos intentos; no se adoptan como
  referencia comparable. No se localizó copia saneada autorizada ni segundo tenant.
- El banco sobrescribe el primer fallo al reintentar. Se encarga conservar ambos
  intentos en salida JSON opcional y verificar el corte existente de envíos externos,
  sin modificar calendario ni criterios de evaluación que trabaja Claude.
- QA de navegador aislada preparada: dependencias verificadas, tenant temporal y
  comunicaciones desactivadas. Se ejecutará una vez sobre 7ab7775; aún sin resultado.
- Caso de cancelación identificado: un recordatorio contiene el id estable de la
  cita; si el portal la mueve, el botón antiguo puede cancelar la nueva fecha sin
  mostrarla. La propuesta nueva mostrará la cita actual y vinculará la aceptación
  al snapshot consultado. No es una regla particular del negocio.

## 2026-09-13 01:22 +02:00 — QA visual parcial sobre 7ab7775

- Primer arranque 01:19:21–01:19:34, exit 1: llama_index intentaba descargar
  punkt_tab ya instalado al buscar el recurso antiguo punkt. Sin navegador.
- Único reintento autorizado de arranque: 01:20:59–01:22:46, exit 1, SHA intacto.
  El lanzador externo resuelve únicamente esa comprobación con el recurso local;
  dotenv y conexiones Python externas siguen desactivados.
- Pasan acceso, resumen, servicio de retención y centros, Ventas, Informes,
  filtros/gráficos/modal, responsive y apertura de Nueva cita con autocompletado.
- Falla el instrumento al esperar franjas del domingo cerrado antes de avanzar
  al lunes. No se mide selección de hora, arrastre ni persistencia de duración.
  No se cambió código ni se repitió el escenario tras el fallo del navegador.
- Evidencia y límites completos en ACEPTACION_CANDIDATO_IA.md; logs y resultados
  `portal-7ab7775*` en la carpeta externa de coordinación. Pendiente corregir
  explícitamente la fecha del instrumento y validar el recorrido restante.
