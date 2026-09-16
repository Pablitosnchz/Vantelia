# Aceptación operativa de Alicia

Preparado por Astra el 16-sep-2026. Bloque 5 de CIERRE_ALICIA_16SEP.md.
Este protocolo aún no se ha ejecutado. No autoriza despliegues, mensajes reales,
cambios de producción ni cobros. Claude mide la candidata `30c5e15`; sus resultados
pendientes no se sustituyen por resultados de `e81f010` u otra versión.

## Antes de probar

Registrar SHA ejecutado, fecha y hora Europe/Madrid, tenant, versión del banco y
huella de configuración sin secretos. Registrar quién ejecuta y qué números de
prueba están autorizados. Comprobar conexión efectiva del número de Alicia; la
última comprobación documentada del 16-sep lo encontraba sin conectar.

Usar citas identificables de prueba y huecos libres obtenidos de la agenda actual,
nunca «mañana» sin comprobar apertura. No modificar citas de clientas. Las pruebas
de cambios de portal y fallos se realizan en copia aislada; cualquier prueba real
requiere autorización de entorno y destinatario. Preparar limpieza de las citas
de prueba y restauración de los ajustes modificados.

## Recorridos y evidencias

| Caso | Acción | Resultado exigido | Evidencia que guardar |
| --- | --- | --- | --- |
| Conexión Meta | Mensaje desde número de prueba al número del negocio | Entrada visible y respuesta recibida en el teléfono | Hora, identificadores técnicos saneados y estado real de entrega |
| Crear | Servicio y profesional válidos; ver resumen y aceptarlo | Antes de aceptar, cero citas nuevas; después, una cita con los datos aceptados | Resumen recibido, código de cita y fila de agenda |
| Rechazo pendiente | Provocar una aclaración; responder «gracias»; después aclarar | Sin resumen mientras falte resolver; tras aclarar, resumen correcto y una sola cita | Conversación completa y citas antes/después |
| Cambiar servicio | Pedir mechas y sustituir explícitamente por grey blending | Resumen con lo finalmente solicitado, profesional habilitada y duración del catálogo | Servicios del resumen y ocupación de agenda |
| Diagnóstico opcional | Rechazar diagnóstico y pedir un tratamiento que permita reserva directa | Continúa con ese tratamiento sin insistir por el freno del precio | Conversación, regla vigente y resultado de reserva |
| Valoración obligatoria | Pedir extensiones sin valoración | Respeta la regla del tenant; no reserva directamente el tratamiento prohibido | Regla activa y ausencia de esa cita |
| Reprogramar | Elegir un nuevo hueco válido y aceptar el cambio | Conserva la cita original hasta aceptar; mueve una cita, sin duplicarla | Código y horas antes/después |
| Cancelar | Solicitar cancelación y confirmar | No cancela por una respuesta ambigua; tras aceptación queda cancelada | Estado antes/después y respuesta recibida |
| Duplicado | Repetir la confirmación en entorno aislado | No añade otra cita ni repite la operación | Número de citas y resultado de la operación |
| Portal | En copia, cambiar horario, vacaciones, profesional habilitada o servicio; aceptar una oferta anterior | Revalida contra datos nuevos; no crea en hueco cerrado ni servicio retirado | Cambio del portal, consulta posterior y resultado al aceptar |
| Aislamiento | Mismo recorrido en otro tenant con reglas distintas | No hereda valoración, precios o requisitos de Alicia | Configuraciones identificadas y ambos resultados |
| Agenda | Comparar cita con duración y pasos del servicio | Misma ocupación que usa disponibilidad; marcas de 15 min; sin precios visibles | Vista de agenda y datos del servicio |
| Reinicio / timeout | En copia, reiniciar después de aceptar o simular respuesta perdida | Recupera el resultado sin duplicar; no anuncia creación sin evidencia | Operación persistida, cita y respuesta final |

## Recordatorios: aceptación no equivale a entrega

Para una cita de prueba dentro de la ventana configurada, observar envío, respuesta
del proveedor y, si existe, evento de entrega. Una aceptación de Meta solo acredita
aceptación; sin evento o recepción verificada, anotar «entrega no verificada».
Un timeout se registra como desconocido, no como enviado ni fallido confirmado.

En copia aislada comprobar también: cancelar antes del envío; reprogramar antes del
envío; dos ejecutores compitiendo; reinicio tras aceptación del proveedor; respuesta
incierta y canal de respaldo. Exigir que el aviso corresponda al estado y hora
vigentes, sin duplicación. No provocar fallos ni reenvíos inciertos a clientas reales.

Referencias existentes, sin relanzarlas por rutina:
`tests/test_entregas_recordatorios.py` y
`tests/test_avisos_reintento_sin_duplicar.py`. Sus transportes simulados no sustituyen
la prueba Meta. Para portal y reinicio: `scripts/medir_portal_y_reinicio.py`.

## Excepciones y datos pendientes

Según registro y relevo de Claude del 16-sep, Pablo aplazó los siguientes casos;
deben figurar en la entrega, sin presentarlos como corregidos o como bloqueos nuevos:

- Ordinales no cubiertos y sustitución con «también»: pueden preguntar de más.
- Formulario nativo sin validar dos apellidos: limitación existente; Alicia tiene
  configurado un apellido. No acredita cumplimiento para otros negocios que exijan dos.
- Primera ficha con nombre de la persona para quien se reserva y «es para mi hija»
  sin nombre: limitaciones del titular. Revisar el resumen y corregir manualmente
  cuando corresponda; no declarar automatizado ese recorrido.
- Sustitución de servicios mediante patrones de texto: deuda del diseño, no cierre
  definitivo de la arquitectura. No ampliar su alcance por dar verde el banco.

Datos según `ALICIA_PENDIENTE.md` de main, actualizado el 16-sep: maquillaje y
recogido ya tiene 45 + 45 min; Elumen largo sigue pendiente de aclaración; los
alisados tienen duración total correcta pero pasos pendientes, se dibujan en bloque.
Los precios permanecen ocultos hasta otra decisión. Stripe figuraba sin capacidad
de cobro: no declarar verificadas fianzas/cobros hasta comprobar su estado y recorrido.
No corregir estos datos por inferencia ni sustituir la respuesta pendiente de Alicia.

## Acta de resultado (rellenar al ejecutar)

- Candidata / configuración / fecha / ejecutor: **pendientes**.
- Banco Alicia: primer intento __; tras reintento __; fallos __; no medidos __.
- Banco segundo negocio: primer intento __; tras reintento __; fallos __; no medidos __.
- Críticos repetidos: casos, intentos y resultado individual __.
- Revisión independiente del SHA exacto: __.
- Recorridos de la tabla: por caso, OK / fallo / no medido y enlace a evidencia __.
- Meta real y recordatorios: aceptación __; entrega __; desconocidos __.
- Excepciones conservadas y responsable de atenderlas: __.
- Autorización de despliegue de Pablo, versión instalada y vuelta atrás: __.

No convertir un caso no medido en OK. Mantener los fallos iniciales aunque un
reintento pase. Un fallo crítico nuevo reabre su análisis; no se elimina del informe.
La aceptación es de esta versión y este alcance, no una garantía de ausencia de fallos.
