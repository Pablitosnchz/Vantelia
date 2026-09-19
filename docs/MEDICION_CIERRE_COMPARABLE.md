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
