# Evidencia de aceptación del candidato IA

Estado: **pendiente**. Un resultado local verde no acredita mejora con el modelo
ni funcionamiento de Meta en un número conectado. Mantener este informe junto
al plan y al registro horario; no completar casillas por inferencia.

## Referencias

- Último candidato medido: 2cb8a029, suite roja (2442 passed, 1 skipped, 1 failed),
  fin 13-sep 03:23:06.385 +02:00. Único fallo:
  test_banco_sin_meta::test_instalar_captura_cierra_la_salida_de_payload,
  en contraste frente a c9f19e6. No se pidió revisión exacta nueva.
- Antecedente de3d6d0: 2401 passed, 1 skipped, 1 failed documental; c4d4f6a
  corrige arquitectura/mapa con 5 dirigidos, sin modificar la suite histórica.
- Antecesor local: 7ab7775, 2297 passed y 1 skipped; revisión pendiente.
- Hijo actual: astra/condiciones-confirmadas, arnés v2 c9f19e6 revisado; términos
  en 6c3ad4f con 112 dirigidos verdes (126,70 s) y revisión OK. 68c1fac añade
  recuperación de checkout con clave persistida; 23 dirigidos de condiciones y
  dos regresiones checkout/Bizum verdes. Sin suite nueva del hijo. Base formulario99fdaf1, UI23139ca,
  mapa c4d4f6a y fixtures891a730 medidos en 2cb8a029.
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
| Cancelar/reprogramar | ca8e626 cierra los dos tests de contrato de 2235d25: 34 dirigidos verdes; pendiente nueva suite | Efecto exacto, sin cita duplicada ni acción por respuesta ambigua |
| Cambios del portal | Invalidación/revalidación cubiertas localmente | Cambiar regla, servicio, horario o vacaciones durante conversación |
| Aislamiento de negocio | Pruebas deterministas por tenant | Mismo banco con segundo negocio y políticas diferentes |
| Reinicio/repetición | Estado y creación recuperable probados | Resto de gestión, entregas y resultado incierto |
| Recordatorios | Suite exacta de3d6d0 sin xfail y único rojo documental corregido en c4d4f6a; no es suite global verde | Plantilla, envío autorizado, cancelación/reprogramación, duplicación |
| Agenda visual | QA exacta 2cb8a029 exit0: etiqueta45=BD45, precio18, geometría de cuartos y recorrido completo; captura revisada | Tipografía externa no medida (Fonts bloqueado); no acredita cambios posteriores |
| Revisión | Solicitada sobre 7ab7775 | OK del SHA exacto del candidato final |

No se activa una regla de diagnóstico/foto para Alicia sin configuración acordada.
Ese bloqueo de producto se aísla; no autoriza a elegir un servicio por la clienta.
El despliegue y el push requieren una orden posterior de Pablo incluso si se
cumplen todas las puertas anteriores.

Trabajo del hijo aún sin aceptación global: transporte c1db689 revisado con 29
pruebas propias y 56 relacionadas (selecciones solapadas); no acredita entrega.
Ledger: 66 dirigidas y 2 de plantilla previas, 16 finales verdes y revisión local
OK en b5fa459; suite integrada de3d6d0 con único rojo documental. Aceptación y evento del tope se guardan
juntos; queda pendiente reconciliación, cupo entre citas distintas, ventana de
cambio durante la red y fallback interno de email. Protección de copia/informe
09aebfc revisada, 27 dirigidas verdes;
rechaza alias de DB/WAL/SHM antes de cualquier escritura. Guardar un ID de Meta o una
fila de cita no equivale a recibir el mensaje en el teléfono.

Los instrumentos tampoco cierran fase 5: 2533fe9 corrige el ID legacy y exige
acción explícita, con efecto de agenda sintético comprobado. Pero opciones()
depende de la API/estado de propuesta del producto y filtra botones emitidos
obsoletos antes de probar su rechazo productivo. Compatibilidad con una baseline
anterior sin esa API/protocolo **NO DEMOSTRADA**. Próxima rama: observar transporte
explícito y efectos, dejando al producto validar autorización; sin clicks
deducidos del texto. El caso crítico del banco que acepta «Resumen» o
«Confirmamos» sigue sin acreditar creación final real. No hay comparación real
antes/después; compartir versión del instrumento no basta para acreditarla.

Otro próximo bloque: propuesta/huella no sellan términos efectivos de
duración/precio/fianza/política. Cambio entre oferta y click identificado por
lectura; pendiente regresión antes y preparación compartida, sin doble cálculo.

La agenda ya implementa el eje y las marcas de quince minutos: coordinación
verificó `app_ui/index.html`, `CD_AXIS_STEP=15` (8479), ticks laterales
(8784–8786), líneas del cuerpo (8810) y CSS `.cd-tick`/`.hour` (812–813),
con escala común de 2,2 px/min. QA externa exacta de3d6d0 verificó 37 marcas,
tres cuartos interiores y alineación con horas/líneas (02:36:26–02:37:51, exit 0,
árbol limpio antes/después; portal-ledger.*). Fonts bloqueado con CSS vacío:
tipografía de sistema. Reveló etiqueta20 sobre bloque/BD45; UI23139ca la corrige
usando cdDur. Nueva QA exacta 2cb8a029, 03:05:16–03:06:56 Europe/Madrid,
exit 0 y SHA/árbol limpios antes/después: etiqueta45 coincide con BD45 y mantiene
precio18; geometría y recorrido completo pasan. Captura inspeccionada también
por coordinación. Evidencia portal-formularios.* externa, Fonts bloqueado con
CSS vacío. Sin modelo/Meta ni suite repetida. La captura anterior no acredita
el arreglo; esta ejecución nueva sí lo verifica. No repetir las QA verdes.

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
