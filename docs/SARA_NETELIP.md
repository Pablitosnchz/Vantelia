# Sara por SIP: el 91 de Netelip

## Por qué

27-sep-2026: Twilio aprobó el bundle español pero no tiene números españoles, y desde
el 17-oct-2026 no deja usar los locales para llamadas comerciales. Pablo eligió
**Netelip** (91 de Madrid, SIP Trunk con guía propia para ElevenLabs).

Marco legal que se revisó ese día:

- **Prefijo 400** (BOE-A-2026-8409, obligatorio desde el 17-oct-2026): obliga solo a
  las empresas de la Ley 10/2025, es decir, grandes empresas y servicios básicos (luz,
  agua, transporte, telecos, banca). Un autónomo queda fuera; conviene que lo confirme
  el gestor. Si el 91 diera problemas, Netelip tiene números 400 al mismo precio.
- **Orden TDF/149/2025** (desde jun-2025): se bloquean las llamadas que entran desde el
  extranjero con número español. Por eso no vale verificar en Twilio un 91 ajeno como
  identificador de llamada: hace falta un operador que llame desde España.

## Cómo funciona (`CAPTACION_VOZ_VIA=sip`)

- El 91 se importa en la cuenta de ElevenLabs activa como SIP Trunk, con estos datos:
  servidor `elevenlabs.netelip.com`, TCP y sin cifrado de medios. Se asigna a Sara. Al
  rotar de cuenta, se importa solo en la nueva: `sincronizar_agente` lo hace.
- Sara marca por `POST /v1/convai/sip-trunk/outbound-call` con las mismas variables del
  guion que por Twilio (`captacion_voz._variables`).
- Cuando la llamada no se coge o comunica, ElevenLabs lo avisa con el evento
  `call_initiation_failure` en `/voice/el-captacion/fin`. Queda igual que con Twilio:
  resultado `ocupado`, `no_contesta` o `fallida` y sin `conversation_id`, así que el
  lanzador reintenta con las mismas reglas.
- Cada cuenta de ElevenLabs lleva su propio aviso (webhook HMAC). Su secreto se guarda en
  `storage/elevenlabs_avisos.json`, fuera de git. Sin aviso, el lanzador no llama.
- La llamada se cierra con su transcripción. Si se pierde el aviso, la recogida horaria
  también encuentra las que siguen «en curso».
- La vía Twilio sigue igual y es la de serie.

Código: `backend/captacion_voz.py` (sección «Marcar por SIP»). Tests:
`tests/test_sara_por_sip.py`.

## Puesta en marcha

1. **Pablo:** cuenta en Netelip, **SIP Trunk** + **número virtual de Madrid (91)**,
   verificado con el certificado censal y la dirección de Torrejón. El número se configura
   en Netelip según su guía (identificador E.164, servidor `sip.rtc.elevenlabs.io`).
2. **En el `.env` del VPS** (copia previa en `/srv/vantelia-backups/`):
   `CAPTACION_VOZ_VIA=sip`, `CAPTACION_SIP_NUMERO=+3491…`, `CAPTACION_SIP_USUARIO`,
   `CAPTACION_SIP_CLAVE`, y `CAPTACION_LLAMADAS_ENABLED=true` cuando Pablo lo diga.
   Recrear el contenedor.
3. `POST /admin/captacion/voz/agente` (token admin) crea el aviso, actualiza a Sara y
   importa el número. Devuelve `agent_id`, `numero_sip` y `aviso`.
4. Panel «Llamadas»: sin bloqueos, salvo el interruptor.
5. **Llamada de prueba** a Pablo (`POST /admin/captacion/voz/llamada-prueba`): comprobar
   que ve el 91, que se oye bien y que la transcripción aparece en el panel. Otra dejando
   que suene sin cogerla: tiene que quedar «No contesta».
6. Encender «Llamar automáticamente».

## Pendiente de medir en real

- Si ElevenLabs devuelve el `conversation_id` antes de que llegue un «comunicaba» muy
  rápido. Si el aviso llega antes, la llamada se queda sin resultado y no se reintenta.
  Es lo conservador.
- Con SIP, el buzón de voz lo detecta Sara dentro de la conversación: esa llamada no se
  reintenta (con Twilio sí, porque colgaba antes de conectar).
