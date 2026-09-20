# Contrato de evidencia del cierre

Base examinada: `e43baca`; la evidencia de despliegue de `0cb61de` no sustituye
la medición del candidato final. D permanece apagado. Este documento no ejecuta
modelo, pruebas, envíos ni acceso a producción.

## Candidato, entradas y calendario

- Congelar SHA y árbol limpio, modelo efectivo y parámetros, hashes del banco,
  arnés, configuración, RAG y snapshot SQLite; guardar inicio/fin UTC y Madrid.
- Usar una campaña serializada sobre el candidato final. Una comparación requiere
  referencia y candidato con el MISMO instrumento; sin referencia compatible,
  presentar aceptación del candidato, no mejora porcentual.
- Conservar entradas inmutables y destinos de trabajo distintos por instrumento
  y tenant. Verificar origen/destino/WAL/SHM: nunca pueden ser el mismo archivo.
  Preparar las rutas `VANTELIA_CONFIG_PATH`, `VANTELIA_DATA_DIR` y
  `VANTELIA_STORAGE_DIR` aisladas antes de importar backend; `DB_PATH` solo no basta.
- Medir Alicia y `metareview`, cuyos servicios de prueba están declarados en
  `evals/negocios.py`. Exigir sus datos; comparar solo la intersección aplicable
  del mismo banco, conservando resultados específicos y los motivos de exclusión.
- Dependencia pendiente: Claude comunica en buzón `20260919T173955011323-claude-c6119d`
  que NO existe snapshot saneado actual; retiró las copias del 17-sep por datos reales.
  Solo declara catálogo de 186 servicios y packs 230/350/430 alineados el 19-sep en
  BD local de desarrollo, sin bookings ni crm_contacts; no se ha leído ni copiado.
  Falta un artefacto autorizado verificado. Una futura agenda/base sintética debe
  declararse sintética, sin atribuirle reproducción ni evidencia de producción.
- Respetar `solo_si`; no importar políticas del salón al otro tenant. Registrar
  cerebro, catálogo y configuración efectivos, incluidos precios, horarios y D.
- `evals/calendario.py` busca fechas futuras válidas en la zona del negocio;
  guardar mensajes y fechas resueltos. Ambos intentos de un caso usan esas fechas.
  Sin huecos, RAG, servicio declarado o cita previa: NO MEDIDO.

## Comandos existentes, para la orden posterior a Claude

Las rutas entre ángulos son placeholders pendientes de concretar; no son rutas reales.

```text
python scripts/evaluar_asistente.py --cliente alicia_rincon_estilistas --db-origen "<BD_BASE_INMUTABLE>" --db-copia "<BD_TRABAJO_ALICIA>" --guardar "<INFORME_ALICIA_JSON>" --detalle
python scripts/evaluar_asistente.py --cliente metareview --db-origen "<BD_BASE_INMUTABLE>" --db-copia "<BD_TRABAJO_METAREVIEW>" --guardar "<INFORME_METAREVIEW_JSON>" --detalle
```

El banco admite `--caso`; no tiene flags de semilla, repeticiones o desactivar
reintentos. El arnés `botones-emitidos-v2` intercepta salidas, conserva IDs emitidos
y no convierte texto libre en pulsaciones. Flows se simula rechazado, no entregado.
No acredita entrega real de Meta, email o SMS; una ruta no interceptada no se mide.

## Cobertura de entradas comprobada el 19-sep

`evaluar_asistente.py`, `humo.py` y `medir_portal_y_reinicio.py` invocan directamente
`whatsapp._handle_whatsapp_message`. Por tanto, el banco conserva valor para las
reglas y la conversación, pero omite `_handle_whatsapp_webhook`: no acredita
resolución demo, captura original del evento, firma, timestamp, deduplicación de
entrada, audio previo ni lotes con ecos/estados. Tampoco recorre `/chat` HTTP: ese
canal usa su propio procesador y motor RAG, no el bucle multiherramientas del agente
que usa WhatsApp. Un resultado de esos bancos no valida el nuevo motor HTTP.

Hay un segundo límite del instrumento: `evals/arnes.py` sustituye los emisores
`_send_whatsapp_*` y hace que email/SMS devuelvan éxito simulado. Eso es útil para
la conversación, pero evita la admisión final de los wrappers reales. El nuevo
adaptador debe conservarlos e interceptar debajo, en HTTP de proveedor y SMTP.
Reutilizar capturas y veredictos, no esos reemplazos de alto nivel.

Puertas adicionales antes de afirmar cierre operativo:

- Adaptador de banco por el webhook real, con petición local autenticada de
  prueba, ID completo/fecha/origen estables y transportes interceptados. Usar el
  mismo instrumento sobre referencia y candidato; guardar qué capturador se
  recorrió. Los casos de pausa, reentrega, cambio de tenant y reinicio deben
  comprobar también los hechos persistidos, no solo el texto del modelo.
  Firmar bytes exactos con secreto sintético y mantener ID/fecha del evento al
  reentregar. Un HTTP 200 del webhook solo es ACK; recoger salidas del proveedor
  falso. Denegar cualquier egress no catalogado y marcar capturas ausentes o
  subcasos sin soporte como NO_MEDIDO. Mantener un loop por caso y esperar sus
  avisos conocidos, sin cancelarlos al terminar cada turno con asyncio.run.
- Campaña separada para HTTP con modelo real e historial persistido: preguntas
  consecutivas, digresión y vuelta a la reserva, Q&A/precio/horario cambiado desde
  portal y segunda sesión/tenant. Entrar por `/chat` con el middleware, sin
  sustituirlo por una llamada directa a `_process_chat_message`. Conservar las
  mismas fuentes/modelo/calendario para referencia y candidato.
- Identificar reinicio de módulos o memoria frente a proceso nuevo. Las pruebas
  nuevas de pago comprueban persistencia/guardia en otro intérprete; todavía no
  equivalen a caída y recuperación E2E del servidor ni a entrega en Meta.

Estos adaptadores/campañas están pendientes, no ejecutados. No se suman a los
resultados históricos del banco ni a pytest; tampoco autorizan acceso a datos
reales o mensajes a destinatarios no autorizados.

## Cierre del bloque de atención, 21-sep-2026: solo instrumentos sin coste

Decisión de Pablo del 21-sep: cerrar con los instrumentos que no gastan modelo.
El banco de casos y el simulador quedan SIN EJECUTAR, y con ellos la comparación
referencia/candidato que pide este contrato. Lo que sigue es aceptación del
candidato, no mejora medida, y no se presenta ningún porcentaje.

Instrumentos ejecutados sobre el árbol congelado (`claude/atencion-whatsapp-20sep`):

| Instrumento | Resultado | Qué acredita |
| --- | --- | --- |
| `python -m pytest` | 3320 passed, 1 skipped, 0 failed, 2251.58s | El mecanismo, en todos los módulos |
| 22 mutaciones causales | 22 rojas | Que cada prueba nueva falla sin su arreglo |
| `python scripts/qa_e2e.py` | PASS 94, WARN 0, BUG 0, salida 0 | El portal entero y la reserva por WhatsApp de punta a punta, en entorno aislado |
| `npm run test:widget` | 16 pass, 0 fail | El widget con la atención cortada |
| `py_compile` + `pyflakes` | limpio | Entradas e imports |

Lo que NO se ha medido, y por qué importa decirlo:

- **El banco de casos y el simulador de 100 clientas**: gastan saldo y necesitan
  una copia saneada de producción que sigue sin existir autorizada. Sin ellos no
  hay comparación con la referencia.
- **El humo de cinco conversaciones**: también habla con el modelo, y existe
  precisamente porque la suite comprueba el MECANISMO y no el CAMINO. Las dos
  regresiones del 26-ago pasaron 1.373 tests. Este cierre no tiene esa red.
- **Proveedores reales**: Meta, Twilio, OpenAI Realtime y Stripe van
  interceptados. No acredita entrega real, ni el silencio de una sesión de voz
  ya abierta, ni el comportamiento de los reintentos de Meta.
- **`npm run build`**: no aplica, `widget/` no se ha tocado en estas fases; su
  último cambio y su bundle son de `00d628a`.

Hallazgo del propio cierre: `scripts/qa_e2e.py` llevaba tiempo dando un BUG
falso y saliendo con código 1, así que su código de salida no significaba nada.
Comprobado en `0cb61de` (desplegado) y en `f11132c` antes de tocarlo: el fallo
era del instrumento, no del producto. Arreglado en `34dab9f`.

## Resultados, límites y cambio del criterio

- Separar previstos, aplicables, medidos, OK primer intento, primeros intentos
  fallidos, OK tras reintento, fallos persistentes por gravedad, NO MEDIDO y NO APLICA.
  El banco reintenta una vez; un reintento no medible conserva el primer fallo.
- `previstos = medidos + no_medidos + no_aplican`; los pendientes impiden declarar
  una campaña completa. Exit 0 no excluye fallos importantes/deseables: leer el JSON.
- Archivar consola, JSON con ambos intentos, trazas y referencia a BD resultante.
  Humo no tiene `--guardar`; sus cinco guiones no son todos comunes a otros negocios.
- Portal/reinicio cubre seis escenarios, con reinicio simulado vaciando memoria,
  no caída real del proceso. Reglas opuestas usa A/B sintéticos fijos, no metareview.
  Recordatorios, concurrencia e idempotencia detallada tienen pruebas deterministas;
  estos bancos no acreditan entrega real ni reconciliación externa.
- `reserva-completa-de-verdad` usa ahora `agenda: crea_unica`: exige exactamente
  una cita activa cuyo `bookings.id` no existiera antes para ese teléfono aislado.
  No basta aumentar las filas; `booking_code` puede estar vacío y no es identidad.
  Los demás casos y criterios se conservan.
  Activas: `confirmed`, `pending_review` y `pending_payment`, como la ocupación
  en `backend/agenda.py:_active_booking_rows_for_day`; una cancelada no cuenta.
  `booking._cancel_booking_core` también admite cancelar una pendiente de pago.
  Una sola pendiente de pago acredita cita activa, no cobro ni confirmación.
- Reproducción local determinista, 19-sep-2026, sobre el caso y veredicto reales:
  `python -m pytest tests/test_banco_cita_unica.py -q --tb=short`.
  Antes, 19:47:17–19:47:26 Madrid: 3 fallos y 5 aciertos (1,74 s); aceptaba dos
  confirmadas, confirmada + pendiente de pago y solo cancelada. Después,
  19:48:12–19:48:17: 8 aciertos (0,82 s), incluida una viva + otra cancelada.
  Logs externos: `%TEMP%/vantelia_banco_cita_unica_{rojo,verde}_20260919.log`.
  Backend sustituido en frontera y filas sintéticas: no mide modelo, BD ni canales.
- Control posterior de identidad, 20:13:30–20:13:37 Madrid: 2 fallos y 10 aciertos
  (1,74 s) sobre la variante anterior; admitía antigua viva + nueva cancelada y
  rechazaba nueva viva sin aumento del total. Tras exigir ID nuevo, 20:14:24–20:14:31:
  12 aciertos (0,84 s), incluidos códigos vacíos y antigua cancelada + nueva activa.
  Logs: `%TEMP%/vantelia_banco_cita_unica_identidad_{rojo,verde}_20260919.log`.
- Frontera SQLite temporal: retirar `id` del SELECT causa 1 fallo por `KeyError`
  (1,72 s), 20:16:32–20:16:40. Restauración byte a byte: 13 aciertos (0,90 s),
  20:17:02–20:17:09; el lector real devuelve IDs distintos con códigos vacíos.
  `backend.db` sustituido; logs `%TEMP%/vantelia_banco_cita_unica_select_{rojo,verde}_20260919.log`.
- Ese endurecimiento cambia el instrumento: futuras comparaciones ejecutan el
  mismo banco sobre referencia y candidato. No recalificar históricos sin sus
  datos de agenda, ni atribuir a producto una bajada causada por el nuevo juez.
