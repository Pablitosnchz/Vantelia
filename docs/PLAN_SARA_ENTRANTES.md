# Sara atiende las devoluciones de llamada al 91 (fase 2)

Pablo, 30-sep-2026: «si llaman de vuelta, que llamen al asistente y que atienda Sara»,
y que no se desvíe a su móvil. Hoy Zadarma desvía la extensión 100 al móvil de Pablo y
nuestro puente rechaza las entrantes (`desde-zadarma` → `Hangup(17)`).

## Cómo

1. **Puente** (`deploy/sara-puente/`): `desde-zadarma` marca a ElevenLabs
   `sip:+34919934321@sip.rtc.elevenlabs.io:5060;transport=tcp` (endpoint nuevo
   `elevenlabs_entrada`, sin credenciales: el número admite `0.0.0.0/0`), con la
   cabecera `X-Caller-ID` = número de quien llama (ElevenLabs la da como
   `system__caller_id`). Mismo tope de 3 llamadas a la vez que las salientes.
2. **Agente de entrada** «Sara - devoluciones», asignado al 91 (las salientes siguen
   usando la Sara de siempre porque la llamada dice qué agente usar). Primer mensaje
   fijo: «Hola, soy Sara, la asistente con inteligencia artificial de Vantelia. Te hemos
   llamado antes, ¿verdad? ¿En qué te puedo ayudar?». Mismo guion desde la pregunta
   (pasos 2-7), sin el aviso de «llamada comercial» (llaman ellos).
3. **Su ficha**: las herramientas llevan `system__caller_id` en vez del id de la
   llamada; el servidor busca la última llamada nuestra a ese número y crea una fila
   `origen='entrante'` con el mismo negocio, sector y email (o una ficha sin negocio si
   no le habíamos llamado). Requisito de Astra: sin esto, las herramientas responden
   «No encuentro esta llamada».
4. **Transcripción**: si la entrante no usó ninguna herramienta, el aviso de fin de
   llamada crea igual su fila (por el agente y el número de la conversación), para que
   aparezca en el panel.
5. **Pablo** quita el desvío a su móvil en Zadarma **cuando esto esté desplegado y
   probado** (una llamada suya al 91).

## Tabla de fallos

| Caso | Riesgo | Regla |
|---|---|---|
| El puente o ElevenLabs no contestan | Suena y nadie coge | `Dial` con 30 s; si falla, colgar con «ocupado». Pablo se entera por el panel de llamadas |
| Número oculto | Sin número para buscar la ficha | Ficha `entrante` sin negocio; enviar solo por email si lo dicta |
| Llama alguien a quien no llamamos (cliente, otro) | Sara cree que es una devolución | El saludo pregunta «¿en qué te puedo ayudar?» sin dar por hecho nada |
| Dos herramientas en la misma entrante | Dos fichas | Se reutiliza la ficha `entrante` del mismo número de los últimos 30 min |
| Pidió «no me llaméis» y ahora llama él | Contradicción | Se le atiende; la baja sigue en pie para las salientes |
| Lanzador | Llamarle otra vez en frío | Ya excluido: tiene conversación |
| Segunda oportunidad | Correo «os pillamos en mal momento» a quien nos llamó | Excluir `origen='entrante'` |
| Más de 3 llamadas a la vez | Saturar el puente | Mismo tope `GROUP_COUNT` que las salientes; si no cabe, «ocupado» |
| Rotación de cuenta | La Sara de entrada no existe en la nueva | Se crea en `sincronizar_agentes` como las demás (su id empieza por `elevenlabs_agent`) |
