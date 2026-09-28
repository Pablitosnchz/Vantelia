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
   - `CAPTACION_SIP_HOST=pbx.zadarma.com` (la extensión de la centralita, **no** la cuenta
     SIP `sip.zadarma.com`: ver «Lo medido el 28-sep»)
   - `CAPTACION_SIP_TRANSPORTE=tcp`
   - `CAPTACION_SIP_USUARIO` y `CAPTACION_SIP_CLAVE` (los de la extensión, `594819-100`)
   - `CAPTACION_LLAMADAS_ENABLED=true` cuando Pablo lo diga

   Después, recrear el contenedor.
4. `POST /admin/captacion/voz/agente` (token admin) crea el aviso, actualiza a Sara e
   importa el número. Devuelve `agent_id`, `numero_sip` y `aviso`.
5. Panel «Llamadas»: sin bloqueos, salvo el interruptor.
6. **Llamadas de prueba** a Pablo (`POST /admin/captacion/voz/llamada-prueba`):
   - Una cogiéndola: tiene que ver el 91, oírse bien y aparecer la transcripción.
   - Otra dejando que suene: tiene que quedar «No contesta».
7. Encender «Llamar automáticamente».

## Lo medido el 28-sep-2026

- **Por la cuenta SIP (`sip.zadarma.com`) el audio del negocio no llegaba a Sara** en 3 de
  cada 4 llamadas: en la grabación, silencio digital exacto entre sus frases. El negocio la
  oía a ella. Por la centralita (`pbx.zadarma.com`), el eco de Zadarma (llamar al `4444`)
  vuelve desde el segundo 4. Por eso va la extensión.
- **Durante una hora Zadarma no aceptó conexiones desde las IP de ElevenLabs** (`connect:
  connection timed out` contra 185.45.155.14 y .17; desde el VPS sí conectaban). Ticket
  #892773; después volvió a aceptar. Las IP de ElevenLabs cambian en cada llamada (Google
  Cloud 34.x / 35.x) y solo son fijas en su plan Enterprise: no se pueden autorizar por IP.
- **ElevenLabs sigue el NAPTR del DNS**: `pbx.zadarma.com` le lleva a `pbxfr1`
  (185.45.155.14), no a la IP que da una consulta normal. Para probar a mano, usar la IP que
  sale en `remote_address` de los mensajes SIP.
- **La API de marcar no contesta hasta que descuelgan** (27 s cuando saltó un buzón). Por eso
  `ESPERA_AL_MARCAR_SIP_S` (120 s) en lugar de los 30 s de Twilio.
- El buzón del móvil lo detecta Sara: la llamada queda con desenlace `buzon`.

Cómo diagnosticar: activar «Mensajes SIP» en la página del número (Agents → Phone
Numbers) y leer `GET /v1/convai/conversations/{id}/sip-messages` (tarda ~1 min) y la
grabación `GET /v1/convai/conversations/{id}/audio`. Para probar sin molestar a nadie,
llamar al `4444` de Zadarma con un agente temporal de 60 s como máximo.

## Pendiente de medir en real

- Si ElevenLabs devuelve el `conversation_id` antes de que llegue un «comunicaba» muy
  rápido. Si el aviso llega antes, la llamada se queda sin resultado y no se reintenta.
  Es lo conservador.
- Con SIP, el buzón de voz lo detecta Sara dentro de la conversación: esa llamada no se
  reintenta (con Twilio sí, porque colgaba antes de conectar).
- **El saludo se solapa con el «dígame» del negocio.** Por SIP la llamada llega a Sara
  justo al descolgar (Twilio tardaba unos segundos en decidir si era un contestador) y
  empieza a hablar en el segundo 0. Se probó el 28-sep dejar vacío el primer mensaje
  (ElevenLabs espera a que hablen; `turn.initial_wait_time` = 4 s) y poner la presentación
  literal en el paso 1 del guion: esperó bien, pero **se presentó dos veces**, porque el
  guion decía «si ya han dicho que son el negocio, di solo "Hola, buenas, soy Sara…" y
  sigue» y tomó el «sí» de Pablo por esa confirmación. Pablo pidió quitarlo. Si se
  reintenta, sin esa frase y con la presentación una sola vez.
