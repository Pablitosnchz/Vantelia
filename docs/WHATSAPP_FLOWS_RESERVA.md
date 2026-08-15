# Reserva como formulario dentro de WhatsApp (Flows)

El flujo por mensajes llegaba a **nueve interacciones** para pedir hora. Con
WhatsApp Flows el cliente recibe **un solo mensaje**, abre un formulario dentro de
WhatsApp y elige servicio, profesional y hora sin salir de esa pantalla.

Apagado por defecto: sin `WHATSAPP_BOOKING_FLOW_ID` y sin clave privada, el canal
sigue con el flujo por mensajes de siempre. Si Meta rechaza el envío del
formulario, el código **cae solo** al flujo antiguo y el cliente no nota nada.

---

## Cómo funciona

| Pieza | Dónde |
| --- | --- |
| Cifrado, token de conversación y pantallas | `backend/wa_flows.py` |
| Endpoint de datos `POST /whatsapp/flow` | `backend/routers/whatsapp_webhooks.py` |
| Envío del formulario y alta de la cita | `whatsapp._wa_send_booking_form` / `_wa_handle_flow_reply` |
| Definición de pantallas | `scripts/wa_flow_booking.json` |
| Alta en Meta (claves, creación, publicación) | `scripts/wa_flow_setup.py` |
| Tests | `tests/test_wa_flows.py` |

**Las pantallas no tienen lógica propia**: reutilizan el mismo catálogo, los mismos
profesionales y los mismos huecos que el flujo por mensajes, para que no puedan
divergir. Y la cita la crea el mismo `_wa_create_booking` de siempre: el formulario
solo cambia *cómo* se recogen los datos.

### Cifrado

Meta manda cada petición cifrada: una clave AES-128 envuelta con nuestra clave
pública RSA (OAEP SHA-256) y el cuerpo en AES-128-GCM. La respuesta va cifrada con
esa misma clave AES y el **IV invertido** (XOR 0xFF). Un fallo al descifrar debe
responder **421**, no 500: así el cliente refresca nuestra clave pública.

### Token de conversación

El `flow_token` lleva firmado (HMAC-SHA256) a qué negocio y a qué teléfono
pertenece, y caduca a las 6 horas. Sin token válido no se listan servicios ni se
crea ninguna cita: es lo que impide que una respuesta manipulada reserve en el
negocio de otro.

---

## Estado a 15-ago-2026

Flow creado y en **borrador** (`1074131035040246`) sobre la WABA de pruebas, con el
endpoint apuntando a `https://app.vantelia.es/whatsapp/flow` y **sin errores de
validación**. Diagnóstico de Meta:

```
FLOW      AVAILABLE
APP       AVAILABLE
WABA      BLOCKED   141006 · falta método de pago
BUSINESS  LIMITED   141010 · verificación del negocio en revisión
```

Nuestro lado está correcto. Para **publicar** el flow (hoy da *"Blocked by
Integrity"*) hacen falta las dos cosas de Meta:

1. **Añadir un método de pago a la WhatsApp Business Account.**
2. **Que pase la verificación del negocio** (enviada el 14-ago).

Mientras tanto se puede probar con `WHATSAPP_FLOW_DRAFT=true`: los flows en
borrador se envían solo a quien tenga rol en la app de Meta.

## Puesta en marcha

```bash
# 1. Claves + creación + subida de pantallas + publicación
python scripts/wa_flow_setup.py --waba-id <WABA> --phone-number-id <PHONE_NUMBER_ID>

# 2. Solo re-subir pantallas tras editar el JSON
python scripts/wa_flow_setup.py --flow-id <FLOW> --update-json
```

Variables de entorno:

```bash
WHATSAPP_BOOKING_FLOW_ID=<id del flow>
WHATSAPP_FLOW_PRIVATE_KEY_B64=<clave privada PEM en base64>
WHATSAPP_FLOW_DRAFT=true   # solo mientras el flow esté sin publicar
```

La app debe estar suscrita al campo de webhook **`flows`** además de `messages`, o
Meta marca el flow como LIMITED.

## Trampas encontradas

- **`visible` exige booleano**: `"visible": "${data.aviso}"` con un string falla la
  validación. Hay que pasar un campo booleano aparte (`hay_aviso`).
- **La clave privada no se puede recuperar**: si el script muere antes de
  imprimirla, hay que regenerar el par y volver a subir la pública.
- **Publicar exige negocio verificado**. Un flow válido en borrador funciona para
  probar, pero no se puede publicar sin eso.
