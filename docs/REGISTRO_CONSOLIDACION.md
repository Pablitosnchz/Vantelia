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

## 2026-09-13 01:26 +0200 - revision independiente del banco

- Primera entrega: 3 regresiones rojas y 1 control verde contra originales; 20 dirigidos verdes con el cambio. No es una medicion real.
- Revision detecta que no poder preparar una cita fixture se contaba como fallo del asistente sin conversar. Se corrige como NO MEDIDO, separado de conversaciones que fallan.
- Se pide validar destino del informe antes de gastar modelo y guardar evidencia parcial atomicamente por caso. El manifiesto sigue siendo resumido; no acredita por si solo comparabilidad total ni anonimiza respuestas.
- QA del portal: arreglo del dia revisado por otro agente, nueva ejecucion aislada en marcha sobre rama gestion con cambios sin commit, registrada en portal-gestion.*. No se presenta como validacion de un SHA limpio.

## 2026-09-13 01:27 +02:00 — QA corregida, recorrido completo verde

- Revisado el cambio mínimo: avanzar al día abierto sembrado antes de Nueva
  cita y comprobar su fecha; no desactiva cierres ni elimina comprobaciones.
- Nueva ejecución autorizada en gestión: 01:25:59–01:27:14, exit 0. Base f317e06
  con árbol sucio y concurrente, no candidato exacto. Evidencia `portal-gestion*`.
- Pasa todo el guion; cita arrastrada de 20 a 45 min con altura y persistencia
  comprobadas. Se conserva el fallo anterior; no se repite este verde.
- Inventariados dos casos de recordatorios aún NO REPRODUCIDOS: omitido+fallido
  que marca enviado y duplicación entre ejecutores/reinicio. Detalle en aceptación.

## 2026-09-13 01:38 +0200 - commits y trabajo independiente

- e49f29d guarda correccion del domingo en QA; 44ac6de guarda banco revisado con checkpoints por intento y precondiciones NO MEDIDO. Ultimo cierre del informe: 10 pruebas verdes, tras 25 de informe/calendario (selecciones solapadas).
- Cancelacion: 5 regresiones iniciales, 4 de resultado desconocido, mutacion de precondicion y 2 de perdida por menu fallan antes del arreglo. 86, 13 y 69 dirigidos verdes en grupos solapados; ultima revision detecta bypass tras intervencion humana, en correccion. Todavia sin suite completa nueva.
- Auxiliar inicia reproduccion/arreglo de recordatorio marcado enviado cuando email se omite y WhatsApp falla, en worktree separado astra/recordatorios-fiables base44ac6de. Concurrencia queda pendiente, no resuelta por este arreglo.
- Claude avisado por Sincronia; referencia real y copia saneada/configuracion de dos negocios solicitadas formalmente, esperan su disponibilidad.

## 2026-09-13 01:44 +0200 - recordatorios reproducidos

- 3 regresiones rojas demuestran marca de enviado sin aceptacion cuando email se omite y WA falla. Corregido en worktree independiente; 31 pruebas verdes y 1 xfail estricto, revision/integracion pendientes.
- Xfail reproduce dos ejecutores enviando antes de escribir timestamp. No esta arreglado; exige registro duradero por aviso/canal y tratamiento de resultado desconocido.
- No ha habido ninguna entrega Meta ni conversacion de modelo real; el objetivo de mejora comparada sigue pendiente.

## 2026-09-13 01:52 +0200 - candidato integrado para suite

- Cancelación 9ede4f9: último hallazgo de saludo tras atención humana cerrado, 1 rojo previo + control verde, 57 dirigidos verdes y revisión independiente OK.
- ff59b06 de recordatorios revisado e integrado mediante merge limpio a83021c. La carrera entre ejecutores permanece como xfail explícito.
- Banco revisado en 44ac6de y guarda de rutas f4ad515; QA guardada en e49f29d. Sin push ni despliegue.
- Se prepara una sola suite completa mediante validar-gestion.py; el SHA exacto, horas y resultado quedarán en gestion-suite.result.json, junto al .log, en C:/Users/pabli/.codex/vantelia-coordination/. Solo se pide revisión automática tras verde y árbol intacto. Este registro previo no afirma que la suite haya terminado.
- Siguiente trabajo independiente: reclamar recordatorios por generación/aviso/canal antes de enviar, preservar aceptaciones y tratar incertidumbre. El candidato de gestión se conservará estable para validar.
