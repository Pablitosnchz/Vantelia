# Alta de WhatsApp self-service (Embedded Signup + Coexistence)

Antes, cada número se daba de alta a mano por la Graph API y el negocio tenía que
**sacar su número de la app del móvil**. Con **Coexistence** (Meta, mayo 2025;
disponible en todos los países desde mayo 2026) eso ya no hace falta: el mismo
número puede estar en la app de WhatsApp Business **y** en la Cloud API a la vez.

Para el cliente: sigue atendiendo desde su móvil como siempre, el asistente
responde las consultas repetitivas, y cuando una persona del equipo escribe desde
la app **el asistente se calla solo** en esa conversación.

---

## Qué hace el código (ya implementado)

| Pieza | Dónde |
| --- | --- |
| Intercambio del `code` por el token del negocio, suscripción de su WABA y guardado cifrado | `backend/wa_onboarding.py` |
| Credenciales por tenant (token Fernet, `waba_id`, `phone_number_id`, modo) | tabla `client_whatsapp_accounts` |
| El token del negocio manda sobre el global al enviar | `messaging._whatsapp_access_token_for_client` |
| Su `phone_number_id` resuelve a su tenant | `whatsapp._whatsapp_phone_client_map` |
| Eco de lo que escribe su equipo desde el móvil → historial + silencia al bot | `whatsapp._handle_whatsapp_echoes` + `backend/inbox.py` |
| Endpoints `POST/DELETE /auth/app/whatsapp/connect` (owner) | `backend/routers/portal_app.py` |
| Botón "Conectar mi WhatsApp" (SDK de Meta) | `app_ui/index.html`, pestaña WhatsApp |

Tests: `tests/test_wa_embedded_signup.py` y `tests/test_inbox_takeover.py`.

## Estado (31-ago-2026)

**Verificación del negocio: APROBADA.** La **Revisión de la aplicación está
ENVIADA** y pendiente (Meta avisa de hasta 20 días). Hasta que resuelva no se
pueden dar de alta números de otras empresas.

Qué costó cuatro rechazos en la verificación, por si vuelve a pasar: Meta **no
acepta documentos fiscales autocumplimentados**, y el modelo 036 lo es; sí
acepta el **certificado de situación censal**, que emite la AEAT. Y un autónomo
va por la vía **"empresa no registrada aún"** (persona física), no por la de
empresa registrada, donde piden inscripción en un registro mercantil.

Datos ya obtenidos, listos para el `.env` del VPS:

```bash
WHATSAPP_APP_ID=2434714980339087
WHATSAPP_ES_CONFIG_ID=1080408011403320
WHATSAPP_ES_PIN=<6 digitos a elegir>
```

El `config_id` salió del enlace de **registro insertado alojado por Meta**: al
generarlo, Meta crea la Login configuration sola. No hay que crearla a mano.

**Pendiente cuando aprueben**, y esto no se puede olvidar: suscribir el webhook
de la app al campo **`smb_message_echoes`**. Sin él no llegan los ecos y el
asistente NO se calla cuando el negocio responde desde su móvil, que es la razón
de ser de Coexistence.

Las variables NO se ponen todavía en producción a propósito: en cuanto están,
aparece el botón de conectar en la pestaña WhatsApp del portal, y hoy fallaría
por falta de acceso avanzado. Un cliente pulsando un botón roto es peor que no
tener botón.

## Las dos formas de entrar

Las dos acaban en `_completar_alta_whatsapp` (`backend/routers/portal_app.py`),
punto ÚNICO que guarda credenciales y activa el canal:

1. **Navegador (SDK de JavaScript)** — `POST /auth/app/whatsapp/connect`. El
   `code` llega por JavaScript desde el botón del portal.
2. **Alojado por Meta** — `GET /whatsapp/signup/callback`. Se le manda al
   negocio un enlace y Meta lo devuelve ahí con `?code=`. El tenant sale de **su
   sesión del portal** (la cookie es `SameSite=lax`, así que viaja en la
   navegación de vuelta): la URL no lo trae y no se deduce del `code`. Cada
   forma de fallar pinta una página explicándolo, porque un `code` caduca en
   minutos y no hay segundo intento. Tests en `tests/test_wa_embedded_signup.py`.

El enlace alojado, con el redirect ya configurado:

```
https://business.facebook.com/messaging/whatsapp/onboard/
  ?app_id=2434714980339087
  &config_id=1080408011403320
  &extras={"version":"v4","sessionInfoVersion":"3","featureType":"whatsapp_business_app_onboarding"}
  &redirect_uri=https://app.vantelia.es/whatsapp/signup/callback
```

## Cómo se comporta

- **Coexistence** (el número sigue en la app): `mode = "coexistence"`. Requiere app
  2.24.17 o superior, que el negocio **abra la app al menos una vez cada 14 días** y que
  el móvil la mantenga instalada. Se pueden importar hasta 6 meses de historial al
  conectar (decisión permanente).
- **Número dedicado** (sin app): `mode = "api"`, el comportamiento de siempre.
- Limitaciones de Meta en coexistence, en chats 1:1: sin listas de difusión, mensajes
  temporales, "ver una vez" ni ubicación en tiempo real. Los grupos siguen en la app y no
  se sincronizan. Los mensajes escritos desde WhatsApp para Windows pueden no generar
  webhook.

## Alta manual (lo que se usó hasta ahora)

Sigue funcionando y es lo que hay detrás del número de demo: `request_code` →
`verify_code` → `register` → `subscribed_apps`, con el token global de Vantelia y el
`phone_number_id` en `config['whatsapp']`. Ver `docs/NUMERO_DEMO_WHATSAPP.md`.
