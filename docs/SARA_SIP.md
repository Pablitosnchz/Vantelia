# Sara por SIP: un 91 de un proveedor español (Zadarma)

## Por qué

27-sep-2026: Twilio aprobó el bundle español, pero no tiene números españoles y desde el
17-oct-2026 no deja usar los locales para llamadas comerciales. Primero se eligió
Netelip, pero pedía firma con certificado FNMT y una factura de suministros a nombre de
Pablo, y no tenía ninguna de las dos. Se pasó a **Zadarma**: 91 de Madrid con DNI y
dirección, [1,7 €/mes](https://zadarma.com/en/tariffs/numbers/spain/madrid/) y
[guía oficial para ElevenLabs](https://zadarma.com/en/support/instructions/elevenlabs/).
El código no depende del proveedor: cambiarlo son variables de entorno.

Marco legal que se revisó ese día:

- **Prefijo 400** (BOE-A-2026-8409, obligatorio desde el 17-oct-2026): obliga solo a
  las empresas de la Ley 10/2025, es decir, grandes empresas y servicios básicos. Un
  autónomo queda fuera; conviene que lo confirme el gestor. Zadarma también vende números
  400 si algún día hicieran falta.
- **Orden TDF/149/2025** (desde jun-2025): se bloquean las llamadas que entran desde el
  extranjero con número español. No se ha podido confirmar desde dónde saca las llamadas
  Zadarma: la primera llamada de prueba lo dirá. Si llega sin número o no llega, se
  cambia de proveedor.

## Cómo funciona (`CAPTACION_VOZ_VIA=sip`)

- El 91 se importa en la cuenta de ElevenLabs activa como SIP Trunk (salida a
  `CAPTACION_SIP_HOST` por TCP, sin cifrado de medios, con usuario y clave de una
  extensión de la centralita de Zadarma). Se asigna a Sara. Al rotar de cuenta se
  importa solo en la nueva: `sincronizar_agente`.
- Sara marca por `POST /v1/convai/sip-trunk/outbound-call` con las mismas variables del
  guion que por Twilio (`captacion_voz._variables`).
- Cuando la llamada no se coge o comunica, ElevenLabs lo avisa con el evento
  `call_initiation_failure` en `/voice/el-captacion/fin`. Queda igual que con Twilio:
  `ocupado`, `no_contesta` o `fallida` y sin `conversation_id`, así que el lanzador
  reintenta con las mismas reglas.
- Cada cuenta de ElevenLabs lleva su propio aviso (webhook HMAC). Su secreto se guarda en
  `storage/elevenlabs_avisos.json`, fuera de git. Sin aviso, el lanzador no llama.
- La llamada se cierra con su transcripción. Si se pierde el aviso, la recogida horaria
  también encuentra las que siguen «en curso».
- La vía Twilio sigue igual y es la de serie.

Código: `backend/captacion_voz.py` (sección «Marcar por SIP»). Tests:
`tests/test_sara_por_sip.py`.

## Puesta en marcha con Zadarma

1. **Pablo:** cuenta en zadarma.com, saldo, y **número de Madrid (91)** verificado con el
   DNI (las dos caras) y la dirección de Torrejón.
2. **Centralita de Zadarma** (gratis):
   - Crear una extensión (por ejemplo, la 100) y apuntar su usuario SIP y su contraseña.
   - Como identificador de llamada (CallerID) de esa extensión, poner el 91: es el número
     que verá el negocio.
   - Las llamadas que entren al 91 (negocios que devuelven la llamada) se desvían al
     móvil de Pablo. Sara no atiende llamadas entrantes: su guion es para llamar ella.
3. **En el `.env` del VPS** (copia previa en `/srv/vantelia-backups/`):
   - `CAPTACION_VOZ_VIA=sip`
   - `CAPTACION_SIP_NUMERO=+3491…`
   - `CAPTACION_SIP_HOST=sip.zadarma.com` (cuenta SIP; con una extensión de centralita sería `pbx.zadarma.com`)
   - `CAPTACION_SIP_TRANSPORTE=tcp`
   - `CAPTACION_SIP_USUARIO` y `CAPTACION_SIP_CLAVE` (los de la extensión)
   - `CAPTACION_LLAMADAS_ENABLED=true` cuando Pablo lo diga

   Después, recrear el contenedor.
4. `POST /admin/captacion/voz/agente` (token admin) crea el aviso, actualiza a Sara e
   importa el número. Devuelve `agent_id`, `numero_sip` y `aviso`.
5. Panel «Llamadas»: sin bloqueos, salvo el interruptor.
6. **Llamadas de prueba** a Pablo (`POST /admin/captacion/voz/llamada-prueba`):
   - Una cogiéndola: tiene que ver el 91, oírse bien y aparecer la transcripción.
   - Otra dejando que suene: tiene que quedar «No contesta».
7. Encender «Llamar automáticamente».

## Pendiente de medir en real

- Si ElevenLabs devuelve el `conversation_id` antes de que llegue un «comunicaba» muy
  rápido. Si el aviso llega antes, la llamada se queda sin resultado y no se reintenta.
  Es lo conservador.
- Con SIP, el buzón de voz lo detecta Sara dentro de la conversación: esa llamada no se
  reintenta (con Twilio sí, porque colgaba antes de conectar).
