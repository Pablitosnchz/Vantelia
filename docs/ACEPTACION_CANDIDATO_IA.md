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

El denominador del éxito inicial son los casos medidos. Publicar además el total
previsto, los no aplicables y todos los no medidos con motivo; nunca convertirlos
en éxitos. Separar fallos críticos/importantes/deseables y conservar cada intento,
también el fallido anterior a un reintento que pasa. El resultado final se apoya
en el efecto de agenda y estado, no solo en lo que redacta el asistente.

Para comparar, guardar SHA de producto e instrumento, modelo/configuración sin
credenciales, hash de copia y catálogo/configuración relevantes, fechas resueltas
y resultados completos por caso. Restaurar la misma copia inicial por tirada;
si cambian calendario, reglas o modelo, indicar que no son condiciones iguales.
Las políticas distintas entre negocios son deliberadas; deben permanecer iguales
entre el antes y el después de cada negocio.

## Puertas de aceptación

| Recorrido | Prueba local | Evidencia real pendiente |
| --- | --- | --- |
| Crear y aceptar explícitamente | Cubierto en candidato 7ab7775 | Conversación y fila creada, primer intento y reintentos |
| Cancelar/reprogramar | Cobertura existente; migración de confirmaciones en curso | Efecto exacto, sin cita duplicada ni acción por respuesta ambigua |
| Cambios del portal | Invalidación/revalidación cubiertas localmente | Cambiar regla, servicio, horario o vacaciones durante conversación |
| Aislamiento de negocio | Pruebas deterministas por tenant | Mismo banco con segundo negocio y políticas diferentes |
| Reinicio/repetición | Estado y creación recuperable probados | Resto de gestión, entregas y resultado incierto |
| Recordatorios | Pendiente de inventario actual | Plantilla, envío autorizado, cancelación/reprogramación, duplicación |
| Agenda visual | QA de 7ab7775 parcial, exit 1 por fecha del instrumento en domingo | NO MEDIDO: horas y cuartos, arrastre y persistencia de duración; completar con fecha abierta explícita |
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
