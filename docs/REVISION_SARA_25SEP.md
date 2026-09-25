# Revisión de Sara — 25-sep-2026, 17:22 Europe/Madrid

**Astra. VEREDICTO: CAMBIOS en los tres SHA.** Revisión de solo lectura de código,
con reproducciones externas: no se modifica la implementación ni se despliega.
Los tres veredictos y las rutas de reproducción se han enviado directamente a Claude
por Sincronía. Siguiente: corregir los casos y revisar los SHA resultantes.

## Alcance y evidencia

| Código exacto | Copia aislada | Pruebas ejecutadas | Resultado |
| --- | --- | --- | --- |
| `3a33f02c9019d7cac97a77f430d7cb8b1463c482` | `E:/Vantelia-copias/astra/rev-arreglos-25sep` | Repros anteriores del lanzador | 13 verdes, 6,379 s |
| mismo SHA | misma copia | Repros anteriores de cuentas | 9 verdes, 3,681 s |
| mismo SHA | misma copia | Límites de recuperación | 2 fallos reproducidos, 1 control verde, 1,742 s |
| `5e2c8414f295c37bbb43083691a3dcc881d0e4fc` | `E:/Vantelia-copias/astra/rev-responsable-25sep` | Rellamadas | 3 fallos reproducidos, 5 controles verdes, 3,610 s |
| `246bdce22abc4a67e13f6a861cffb9687533c40b` | `E:/Vantelia-copias/astra/rev-transcripciones-25sep` | Transcripciones | 4 fallos reproducidos, 3 controles verdes, 4,18 s |

Total: 40 casos, 31 verdes y 9 fallos de comportamiento, sin errores de montaje.
Los ocho hallazgos originales quedan corregidos en sus 22 reproducciones y controles;
los casos adicionales señalan límites que faltan, no anulan ese progreso.

Los scripts cargan los módulos de cada copia exacta y usan SQLite temporal,
configuración ficticia y proveedores simulados; las conexiones de red están bloqueadas.
No leen secretos ni datos de producción. Las llamadas registradas en estas pruebas
son POST a un objeto Twilio ficticio, nunca a teléfonos reales.

No se ejecutó pytest ni otra suite completa: al comenzar había una suite ajena activa.
Se leyeron los tests nuevos, pero no se presenta su ejecución como validación propia.
`repro_e535.py` se conserva intacto. Para `repro_1c4.py` se usa un adaptador que añade
únicamente cuenta sana simulada y tabla `events`, sin cambiar sus 13 aserciones.

## `3a33f02`: rotación y recuperación

1. **Crítico / P1 — La vuelta atrás deja un agente nuevo que acaba de borrar.**
   `backend/cuenta_elevenlabs.py:258-263` y `:305-308`.
   Un negocio tiene agente web pero no telefónico. La sincronización crea ambos en
   la cuenta nueva y falla al pasar al segundo negocio. `_restaurar_ids` restaura
   solo campos que ya tenían valor: conserva el ID telefónico nuevo en memoria y
   configuración persistida; acto seguido lo borra del proveedor y recupera la clave
   vieja. El teléfono queda apuntando a un agente inexistente. La reproducción usa
   `sincronizar_agentes`, `sincronizar_agente`, `publicar_agente` y `guardar_en_voz`
   reales. **Arreglo:** restaurar también ausencia y valores vacíos de campos creados,
   sin borrar datos ajenos. **Cobertura actual:** el test del commit cambia un ID
   existente; no añade un campo. El control con ambos IDs previos sí pasa.

2. **Importante / P2 — La principal fuera de la reserva vuelve a perderse al reiniciar.**
   `backend/cuenta_elevenlabs.py:295-298`, con `aplicar_activa_guardada` en `:169-180`.
   Entorno ficticio: principal A, reserva B/C. Tras rotar a B, un reinicio recarga esos
   valores y aplica la huella persistida de B. Sobrescribe A sin incorporarla al conjunto
   de claves: aunque A recupere saldo, el vigilante no la consulta ni vuelve a ella.
   **Arreglo:** conservar la principal también al restaurar la activa al arrancar, sin
   persistir secretos. **Cobertura actual:** comprueba volver sin reinicio; ese caso
   pasa. No comprueba volver tras recargar el entorno.

## `5e2c841`: rellamada a la responsable

3. **Crítico / P1 — Marca después de que llegue un rechazo.**
   `backend/lanzador_llamadas.py:398-402`.
   La transcripción con `desenlace=rechazo` se guarda durante la consulta a Robinson,
   antes de responder. `_impedimento` se vuelve a comprobar, pero la elegibilidad del
   candidato no: el POST ficticio se realiza igualmente. **Arreglo:** revalidar el
   candidato, incluidos rechazo y preferencias actuales, inmediatamente antes de marcar.
   **Cobertura actual:** solo comprueba rechazo recibido antes de seleccionar. Los
   controles de rechazo previo y baja mediante la herramienta durante Robinson pasan.

4. **Importante / P2 — Llama antes de la hora que le indicaron.**
   `backend/lanzador_llamadas.py:224-231` y `:282-285`.
   «El jueves a partir de las cinco» se reduce a toda la franja de tarde: a las 16:30
   del jueves ya marca. **Arreglo:** conservar y validar el límite de las 17:00; si no
   se interpreta una condición, no convertirla en disponibilidad más amplia.
   **Cobertura actual:** prueba el índice de franja con «las cuatro», justo su inicio,
   y no detecta una hora posterior dentro de esa misma franja.

5. **Importante / P2 — Programa la rellamada sin saber cuándo está la responsable.**
   `backend/lanzador_llamadas.py:266-267` y `:282`.
   Empleado, responsable Marta y `responsable_cuando=''` bastan para marcar. El plan
   en `2d65220:docs/PLAN_HABLAR_CON_EL_RESPONSABLE.md` exige nombre y cuándo; sin dato
   de disponibilidad no se cumple esa condición. **Arreglo:** exigir disponibilidad
   utilizable; vacío no significa cualquier momento. **Cobertura actual:** no hay caso
   de nombre conocido y disponibilidad vacía.

Controles verdes: móvil excluido, Robinson positivo bloquea, baja durante Robinson
bloquea, rechazo previo bloquea y solo una rellamada válida. El guion contiene la
presentación completa a la persona nueva (IA, comercial y baja). No se ha validado
con voz real que el modelo la diga ni que espere correctamente en silencio.

## `246bdce`: transcripciones

6. **Crítico / P1 — Leer una transcripción incompleta puede perder su rechazo definitivo.**
   `backend/transcripciones_llamadas.py:222`, `:203` y `:165-167`.
   El botón Leer recibe `status=processing` sin análisis y lo almacena como `done`.
   Si no llega el webhook final, el respaldo ya excluye esa fila por tener transcripción.
   Cuando el proveedor termina con un rechazo, no se vuelve a consultar: la reproducción
   recoge cero y deja una rellamada elegible. **Arreglo:** guardar solo estados terminales
   o mantener las transcripciones parciales pendientes de recuperación. **Cobertura
   actual:** prueba `processing` en el respaldo, pero no a través de Leer.
   El estado `processing` forma parte del [contrato oficial de conversaciones](https://elevenlabs.io/docs/api-reference/conversations/get).

7. **Importante / P2 — La clasificación puede pisar una anotación concurrente de la herramienta.**
   `backend/transcripciones_llamadas.py:130-136`, con lectura anterior en `:104-106`.
   Tras leer campos vacíos, llega `anotar_responsable` y escribe dueña/Ana. El guardado
   posterior usa la fila antigua y sustituye esos valores por empleado/Marta. El
   intercalado se reproduce con la herramienta real. **Arreglo:** actualización
   condicionada a que cada campo siga vacío en la propia escritura/transacción;
   recargar y escribir a ciegas seguiría teniendo carrera. **Cobertura actual:**
   conserva anotaciones previas en ejecución secuencial, no cambios concurrentes.

8. **Importante / P2 — Veinte llamadas irrecuperables bloquean toda la cola posterior.**
   `backend/transcripciones_llamadas.py:163-167`.
   Las primeras veinte conversaciones antiguas devuelven 404; la número 21 está disponible.
   Dos ciclos repiten 80 consultas a las antiguas y nunca consultan la 21. El mismo
   `ORDER BY ... LIMIT 20` se repite indefinidamente. **Arreglo:** avance de cola o
   reintentos diferidos que permitan progresar sin descartar los pendientes.
   **Cobertura actual:** no prueba una cola superior al límite con fallos al principio.

9. **Menor / P3 — Un timeout corta la búsqueda antes de la segunda clave.**
   `backend/transcripciones_llamadas.py:150-153`.
   Si la primera petición lanza `ReadTimeout` y la segunda cuenta puede responder 200,
   `_pedir` devuelve `None` sin probarla. Es una pérdida de recuperación en ese ciclo,
   no una afirmación de pérdida permanente. **Arreglo:** continuar de forma acotada
   con las claves restantes. **Cobertura actual:** sí prueba pasar a otra clave tras
   un 404, no tras un fallo de transporte.

Controles verdes: firma HMAC y cuerpo, tolerancia ±1800 s y rechazo a ±1801 s,
conversación ajena ignorada, rechazo ya recibido bloquea, idempotencia, exportación
de una llamada propia y segunda clave tras 404. La protección 503 sin secreto, 401
con firma inválida y autorización de exportación se revisó en código; no se ejecutó
el recorrido HTTP completo en esta revisión. No hay medición con proveedor real.
El formato HMAC se contrastó con el [SDK oficial de ElevenLabs](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/webhooks_custom.py);
no se presenta un posible espacio en la cabecera como defecto sin evidencia.

## Reproducción y relevo

Directorio base de evidencias: `E:/Vantelia-copias/astra/evidencias/`.
Cada script se ejecuta con `python <script> <worktree exacto>`.

| Script o log | SHA-256 |
| --- | --- |
| `revision-arreglos-3a33/repro_1c4_adaptado.py` | `e8d5222e9204a015cd0880b01f31f8fb4cec4fa91d5feb4cb847366c59f38290` |
| `revision-arreglos-3a33/repro_1c4.log` | `191a785410bf37958a158cc29c924ddcfecb17dd9fd661b7372d06b61e52d916` |
| `revision-arreglos-3a33/repro_e535.log` | `0ce7c3013b105b6297c782a68ee2400c3933a5a8309c74299613bb2aa52fa9b5` |
| `revision-arreglos-3a33/repro_limites.py` | `3c668bf2b165114c9a2a34e56d6db94bc76565726328611c1566cba505ceff7d` |
| `revision-arreglos-3a33/repro_limites.log` | `4806290619769479f73fd19975b599a23e0401e3d503d0cd6b7900db4c270848` |
| `revision-responsable-5e2/repro_5e2.py` | `8ea79df9fa8cfbbf191a641d09689125ca547a75198a9ca6ab785228c075b368` |
| `revision-responsable-5e2/repro_5e2.log` | `45a149c3cf4821f95c637b1de401bd75353b9992d34079bc941e525ff225b91e` |
| `revision-transcripciones-246/repro_246.py` | `960989e01f8b4dbfbd22b182f0a7998c3aa40803ac660fbfcfe787740d94acd1` |
| `revision-transcripciones-246/repro_246.log` | `31b94dbbc0091f4e410ad0704926d9c32eb28c6ccfffb19b5f9151007932468a` |

El script original de cuentas sigue en `revision-cuentas-e535/repro_e535.py` y
el montaje original del lanzador en `revision-lanzador-1c4/repro_1c4.py`; los nuevos
scripts los reutilizan sin sobrescribirlos. Los logs con fallos son evidencia de
los escenarios, no suites que sigan ejecutándose.

Al cerrar: reproducciones terminadas, implementación pendiente de Claude y posterior
revisión del SHA corregido. Esta revisión no autoriza push ni despliegue.
