# Entrega a Alicia Rincón Estilistas: de la candidata al uso real

Bloque 5 de [CIERRE_ALICIA_16SEP.md](CIERRE_ALICIA_16SEP.md). Escrito el 16-sep-2026.
Este documento **no autoriza** desplegar ni conectar nada: cada paso marcado con
«Pablo» necesita su orden.

## Candidata

- Rama `claude/servicio-y-titular`, candidata **30c5e15** sobre producción 311b58e.
- Evidencia y rondas de revisión: [REGISTRO_CONSOLIDACION.md](REGISTRO_CONSOLIDACION.md)
  (entradas del 16-sep). Medición y revisión OK terminadas; desplegado `c110bd9`
  (mismo código) el 16-sep a las 21:35, según registro y relevo de Claude.
- Qué cambia para Alicia: el resumen no sale mientras el asistente le está preguntando
  algo a la clienta; cambiar de servicio («pues quiero…», «en vez de…») sin volver a
  preguntar lo descartado; no insiste en el diagnóstico rechazado; una cita para otra
  persona no renombra la ficha; «el primer hueco» no se confunde con un servicio.

## Pasos hasta el uso real, en orden

| # | Paso | Quién | Estado |
| --- | --- | --- | --- |
| 1 | Revisión de Astra del SHA exacto: OK | Astra | Terminada sobre 30c5e15 |
| 2 | Medición de la candidata sin fallos críticos ni casos no medidos (Alicia y segundo negocio) | Claude | Terminada: Alicia 45/45 y segundo negocio 16/16 al primer intento; 1 caso no aplica en Alicia |
| 3 | Orden de desplegar y despliegue (`deploy/deploy.ps1`: copia de la BD, imagen anterior guardada, humo) | Pablo / Claude | Desplegado c110bd9 por orden de Pablo, humo 5/5 |
| 4 | Comprobar en producción `VERSION.json`, health y su configuración | Claude | Verificado por Claude y registrado el 16-sep 21:30–21:40 |
| 5 | Alicia conecta su número desde su portal → pestaña **WhatsApp** → «Conectar mi WhatsApp» (Coexistence: sigue con su app en el móvil) | Alicia (con Pablo) | Botón disponible desde el 11-sep |
| 6 | Método de pago en su WhatsApp Manager (Meta cobra cada plantilla de recordatorio al negocio) | Alicia | Pendiente |
| 7 | Plantilla `vantelia_recordatorio_cita`: la da de alta y consulta su aprobación el propio sistema al conectar | Automático | Tras el paso 5 |
| 8 | Prueba corta con números de prueba: [QA_WHATSAPP_ALICIA.md](QA_WHATSAPP_ALICIA.md) | Pablo y Alicia | Pendiente |
| 9 | Empieza a contar la prueba de 10 días (`prueba` en su config) | Pablo | Pendiente |
| 10 | 48 h de observación: errores, citas duplicadas, preguntas repetidas y conversaciones sin cerrar | Claude / Astra | Pendiente |

## Datos que faltan de Alicia

- Lista de servicios de los que el asistente **sí** puede dar precio. Hoy no da ninguno
  (antes daba, por ejemplo, el corte de señora).
- Pack elumen largo: sus tiempos coinciden con el corto; se le ha repreguntado. Hoy aparta
  140 min (más de lo que dice, no menos).
- Alisados: si quiere los pasos detallados o se quedan pintados en bloque (el total ya es
  correcto).
- Sin respuesta desde agosto: fianza en servicios de menos de 50 € y el pack grey
  blending largo (8,8 h).

## Limitaciones que conoce antes de empezar

- «Es para mi hija» sin nombre: el resumen sale a nombre de quien escribe (se ve antes de
  confirmar).
- «No quiero el corte tan corto, quiero un elumen»: vuelve a preguntar, a propósito.
- La ficha de un teléfono toma el nombre de su primera cita, aunque sea para otra persona
  (decisión de Pablo del 16-sep); se corrige editando la ficha.
- Recordatorios por WhatsApp sin probar con Meta de verdad hasta los pasos 5 a 7.
- Fianza: Stripe sin cobros activados; se reserva sin cobrarla.

## Si algo va mal

- **Volver al código anterior:** `.\deploy\deploy.ps1 -Rollback` (vuelve a la imagen
  previa; los datos no se tocan).
- **Callar al asistente en una conversación:** responder desde su app de WhatsApp Business
  (se calla 1 h) o «Atender yo» en Conversaciones.
- **Datos:** cada cambio en producción deja copia en `/srv/vantelia-backups/` (la última
  de hoy: `pre-pack-maquillaje-20260916-110651.db`).
- **Soporte:** Pablo; Claude y Astra revisan conversaciones y trazas (`agent_turns`).
