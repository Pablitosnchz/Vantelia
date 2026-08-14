# Número de demo de WhatsApp (Cloud API)

Un número propio al que **cualquier prospecto puede escribir sin permisos previos**,
y que atiende a todos: cada uno recibe un código y habla con SU asistente.

Sustituye al número de pruebas de Meta (`+1 555 643-6948`), que solo responde a
móviles autorizados de antemano y obliga a pedirle al prospecto el código de
verificación que le llega por WhatsApp — un patrón idéntico al del fraude de
suplantación de cuentas, inservible en un primer contacto comercial.

---

## Estado verificado de la cuenta Meta (14-ago-2026)

| Activo | Estado |
| --- | --- |
| App Meta "Vantelia" | `2434714980339087`, activa |
| Webhook de la app | `https://app.vantelia.es/whatsapp/webhook`, suscrito a `messages` ✓ |
| Token | System user "Vantelia API", permanente (`expires_at: 0`), con `whatsapp_business_management` + `whatsapp_business_messaging` |
| WABA actual | Solo la de pruebas: `1506537557807276` ("Test WhatsApp Business Account") |
| Número actual | Solo el de pruebas: `1003598042848216` (+1 555-643-6948, `code_verification_status: NOT_VERIFIED`) |

Es decir: **la mitad del trabajo ya está hecha** (app, webhook, token). Falta la
WABA real y el número.

## Qué número usar

- **Recomendado: un número español (+34) que controles.** Lo más simple y barato es
  una SIM prepago o una segunda línea eSIM. Un +34 vende infinitamente mejor a
  hoteles y clínicas españolas que un +1.
- El número **no puede estar registrado en WhatsApp** (ni en la app normal ni en
  Business). Si lo estuvo, hay que borrar esa cuenta antes.
- Solo tiene que recibir **una vez** un SMS o una llamada de verificación. Después
  la conversación va por la API, no por la SIM.
- Un fijo también sirve: la verificación se puede hacer por llamada de voz.
- El Twilio que ya tenéis (`+1 803 884 9920`) técnicamente podría verificarse, pero
  es estadounidense y arrastra el mismo problema de imagen que el de pruebas.

## Coste real de operarlo

Prácticamente cero: desde noviembre de 2024 Meta **no cobra las conversaciones de
servicio**, que son las iniciadas por el usuario — exactamente el caso de una demo.
Solo se paga la línea. Lo de pago son las plantillas de marketing/utility, que aquí
no se usan.

## Pasos en Meta

1. **Business Manager** → crear una WABA real (no la de pruebas).
2. **WhatsApp → API Setup → Add phone number**: alta del número, nombre visible
   ("Vantelia") y verificación por SMS o llamada.
3. Meta revisa el **nombre visible**; suele resolverse en horas.
4. **Asignar la WABA y el número al system user** "Vantelia API" con permiso de
   gestión y de mensajería, o el token dejará de valer para ese número.
5. **Suscribir la WABA a la app "Vantelia"**, para que los mensajes lleguen a
   `app.vantelia.es/whatsapp/webhook` (la de pruebas ya lo está; la nueva hay que
   suscribirla).
6. Copiar el `phone_number_id` del número nuevo.

La **verificación de empresa** no bloquea el arranque: sin ella se pueden atender
mensajes entrantes con normalidad. Hace falta para ampliar límites de mensajes
iniciados por el negocio, que aquí no se usan. Conviene lanzarla igualmente porque
tarda días.

## Encenderlo en Vantelia

Dos variables en el `.env` de producción y reiniciar:

```bash
WHATSAPP_DEMO_PHONE_NUMBER_ID=<phone_number_id del número nuevo>
WHATSAPP_DEMO_PUBLIC_NUMBER=+34XXXXXXXXX
```

Vacías = función apagada, que es como está ahora. El número de demo **no** se
configura como un tenant en `config.json`: se enruta por código.

## Cómo se usa en una venta

```bash
# 1. Generar el código del prospecto
curl -X POST https://app.vantelia.es/admin/whatsapp-demo/codes \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cliente_id":"caprocat","label":"Cap Rocat - Bianca","days":30}'
```

Devuelve el código y el enlace ya montado:

```
https://wa.me/34XXXXXXXXX?text=DEMO%20ABC123
```

Ese enlace es lo que va en el email. El prospecto lo pulsa, WhatsApp se abre con el
texto escrito, le da a enviar y **ya está hablando con su asistente**. Sin altas,
sin códigos que pedirle, sin fricción.

Otros endpoints (admin token): `GET /admin/whatsapp-demo/codes[?cliente_id=]` para
listar con contador de usos, `DELETE /admin/whatsapp-demo/codes/{code}` para
revocar (corta también las conversaciones abiertas con ese código).

## Reglas del enrutado

- Un código = un tenant. Aleatorio de 6 caracteres, sin 0/O ni 1/I para poder
  dictarlo por teléfono. Caduca a los 30 días por defecto.
- El teléfono queda atado a ese asistente **15 días**; los mensajes siguientes ya no
  necesitan código.
- **El id del tenant nunca sirve como código**: sin esto, cualquiera probando
  nombres entraría en el asistente de un cliente real.
- Un mismo móvil puede saltar de una demo a otra enviando otro código (útil para
  enseñar dos asistentes en una llamada).
- Sin código válido, el número responde con instrucciones y no molesta a ningún
  asistente.

Implementación en `backend/wa_demo.py`, enganche en el webhook de
`backend/whatsapp.py`, tests en `tests/test_wa_demo_hub.py`.
