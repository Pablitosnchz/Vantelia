# Evidencia de aceptación del candidato IA

Estado: **pendiente**. Un resultado local verde no acredita mejora con el modelo
ni funcionamiento de Meta en un número conectado. Mantener este informe junto
al plan y al registro horario; no completar casillas por inferencia.

## Referencias

- Candidato local comprobado: 7ab7775, 2297 passed y 1 skipped; revisión pendiente.
- Referencia anterior con modelo real: pendiente de identificar SHA y artefactos.
- Datos: solo copias saneadas autorizadas. No usar por defecto la BD del negocio.
- Mantener separados los casos no aplicables y los que no se pudieron medir.

## Comparación de conversaciones completas

| Negocio y versión | Previstos | No aplican | No medidos | OK primer intento | OK tras reintento | Fallos finales | Artefacto |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Alicia, referencia | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no recibido |
| Alicia, candidato | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no ejecutado |
| Segundo negocio, referencia | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no identificado |
| Segundo negocio, candidato | pendiente | pendiente | pendiente | pendiente | pendiente | pendiente | no ejecutado |

El denominador del éxito inicial es `primer_intento_medido`. Si falla la
preparación del reintento, el primer fallo sigue contado aunque el caso completo
quede no medido. Publicar además el total previsto, los no aplicables y todos los
no medidos con motivo; nunca convertirlos en éxitos. Separar fallos
críticos/importantes/deseables y conservar cada intento,
también el fallido anterior a un reintento que pasa. El resultado final se apoya
en el efecto de agenda y estado, no solo en lo que redacta el asistente.

Para comparar, guardar SHA de producto e instrumento, modelo/configuración sin
credenciales, hash de copia y catálogo/configuración relevantes, fechas resueltas
y resultados completos por caso. Restaurar la misma copia inicial por tirada;
si cambian calendario, reglas o modelo, indicar que no son condiciones iguales.
Las políticas distintas entre negocios son deliberadas; deben permanecer iguales
entre el antes y el después de cada negocio.

Instrumento disponible en 44ac6de: `evaluar_asistente.py --guardar <informe.json>`
conserva intentos completos, resultados iniciales y reintentos, fechas y estado
incompleto. Comprueba escritura antes de preparar la BD y guarda atómicamente
después de cada intento/caso. SHA/árbol sucio y ficha resumida no sustituyen el
modelo exacto ni el hash de copia/configuración necesarios para comparar. El JSON
no anonimiza respuestas: usar únicamente datos de prueba saneados autorizados.

## Puertas de aceptación

| Recorrido | Prueba local | Evidencia real pendiente |
| --- | --- | --- |
| Crear y aceptar explícitamente | Cubierto en candidato 7ab7775 | Conversación y fila creada, primer intento y reintentos |
| Cancelar/reprogramar | Cancelación guiada/botones en 9ede4f9: 57 dirigidos verdes; resto de gestión pendiente | Efecto exacto, sin cita duplicada ni acción por respuesta ambigua |
| Cambios del portal | Invalidación/revalidación cubiertas localmente | Cambiar regla, servicio, horario o vacaciones durante conversación |
| Aislamiento de negocio | Pruebas deterministas por tenant | Mismo banco con segundo negocio y políticas diferentes |
| Reinicio/repetición | Estado y creación recuperable probados | Resto de gestión, entregas y resultado incierto |
| Recordatorios | ff59b06 integrado: 31 dirigidos verdes y un xfail estricto de duplicación | Plantilla, envío autorizado, cancelación/reprogramación, duplicación |
| Agenda visual | 7ab7775 parcial; QA corregida en árbol de gestión pasó, duración persistida 20→45 min | Revalidación del candidato final exacto; horas/cuartos no tienen aserción visual específica en este guion |
| Revisión | Solicitada sobre 7ab7775 | OK del SHA exacto del candidato final |

No se activa una regla de diagnóstico/foto para Alicia sin configuración acordada.
Ese bloqueo de producto se aísla; no autoriza a elegir un servicio por la clienta.
El despliegue y el push requieren una orden posterior de Pablo incluso si se
cumplen todas las puertas anteriores.

## Recorrido visual aislado: 13-sep, 01:22 Europe/Madrid

SHA antes/después: 7ab7775. Un primer intento terminó durante la importación de
API por una descarga redundante de NLTK; no abrió navegador. El único reintento
de arranque validó el recurso ya instalado, mantuvo deshabilitadas las descargas
y terminó con exit 1 en `scripts/qa_portal_browser.py:290`.

Pasaron los pasos anteriores: acceso, resumen, crear/editar servicio de retención,
dos centros, Ventas, Informes con filtros y gráficos, modal, responsive de 390 px,
abrir Nueva cita y autocompletado inicial. El guion espera franjas del día actual
antes de avanzar a la cita sembrada el lunes; ese día actual es domingo y el
tenant temporal cierra los domingos. El código del portal muestra el cierre.
No acredita regresión del producto ni aceptación visual completa. No se alcanzan
selección de hora, arrastre, persistencia de duración ni comprobación final de
errores de consola. No se relanzó para sustituir este fallo por un verde.

Artefactos fuera del repo: `C:/Users/pabli/.codex/vantelia-coordination/portal-7ab7775.log`
y `.result.json` (arranque), `portal-7ab7775.attempt2.log` y `.result.json` (navegador).
El lanzador `.run.py` conserva comando y aislamiento: entorno sin credenciales,
dotenv desactivado en ambos procesos, conexiones Python solo a loopback, tenant,
datos, almacenamiento y configuración temporales. No se tocaron producción ni
el código del candidato estable.

## Recordatorios: inspección inicial y reproducción posterior

El inventario siguiente conserva lo observado antes de ejecutar las regresiones;
la actualización posterior indica qué se reprodujo y qué sigue pendiente.

- **Importante — envío omitido más envío fallido se registra como enviado.**
  `backend/booking.py`, `_send_booking_reminder_by_kind`, condición
  `if sent_channels or skipped_channels` (línea 4222 en la rama de
  gestión). Caso: email y WhatsApp activos, cita sin email y WhatsApp devuelve
  False. Queda email omitido y WA fallido, pero se rellena `reminder_24h_sent_at`
  sin un envío y no se reintenta. Falta regresión determinista; los tests leídos
  de plantillas/cancelación previa no cubren esa combinación.
- **Importante — dos ejecutores o reinicio pueden repetir el aviso.**
  `backend/booking.py`, `_run_booking_reminders` (línea 5230), lee
  timestamps antes del I/O sin reclamar una operación de envío. Caso: worker
  automático y endpoint admin leen ambos `reminder_24h_sent_at` vacío; ambos
  envían antes de marcarlo. También hay ventana entre aceptación externa y
  persistencia local ante reinicio. Falta prueba con barrera/concurrencia y
  resultado externo desconocido. No se afirma que haya ocurrido en producción.

Actualización 13-sep 01:42 Europe/Madrid: **ambos casos reproducidos** en
astra/recordatorios-fiables, base 44ac6de. Tres regresiones fallan antes del arreglo
de contabilidad (rechazo, timeout y caller sin excepción). La corrección conserva
pendiente cuando ningún canal acepta y al menos uno falla; 31 pruebas verdes y
un xfail estricto, selección dirigida. Revisión local OK; ff59b06 integrado en
a83021c. Pendiente suite integrada y revisión de Claude.

El xfail reproduce dos ejecutores enviando antes de registrar la marca; **esa
carrera no está corregida**. Siguiente: reclamación duradera, recuperación y
resultado desconocido por canal. No acredita entrega de Meta ni ausencia global
de duplicación. Logs `recordatorios-falso-enviado-rojo.log` y `-verde.log` en la
carpeta externa de coordinación.

## QA corregida de gestión: 13-sep, 01:27 Europe/Madrid

Una nueva ejecución justificada tras corregir la fecha del instrumento termina
**exit 0** (01:25:59–01:27:14). Base f317e06 antes/después, con cambios sin commit
y otras implementaciones en curso: **no es validación de un SHA exacto estable**.
Conservados `portal-gestion.before.patch` y `.after.patch`, además del `.log`,
`.result.json` y `.run.py` en la carpeta externa de coordinación. Los diffs
difieren por trabajo concurrente; no atribuir este verde a la totalidad del árbol.

Pasa la aserción nueva de que Nueva cita usa el día abierto sembrado. El guion
completo pasa acceso, servicios/centros, Ventas, Informes/filtros/gráficos,
responsive móvil, búsqueda de servicio, conservar hora al elegir servicio,
legibilidad de cita corta y arrastre sin abrir el panel. Comprueba respuesta de
guardado 200, mayor altura visual y duración real guardada **45 min** frente a
20 min iniciales; también termina sin los errores de consola capturados.
No se repite después del verde. El fallo previo del domingo se conserva.
No mide modelo, Meta, canales reales ni la aceptación de cancelación nueva.
