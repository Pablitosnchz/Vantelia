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

## Lo que falta, y es en Meta, no en el código

El botón **no aparece** mientras falten estas tres variables de entorno:

```bash
WHATSAPP_APP_ID=<id de la app "Vantelia">
WHATSAPP_ES_CONFIG_ID=<id de la Login configuration>
WHATSAPP_ES_PIN=<PIN de 6 dígitos para registrar números>
```

`WHATSAPP_APP_SECRET` ya está configurada.

Para obtener el `config_id` hay que, en el panel de Meta:

1. **Verificar el negocio** (Business Verification) en el portfolio empresarial.
2. Configurar la app como **Tech Provider / Solution Partner** de WhatsApp. Comprobado
   el 14-ago-2026: la API responde *"This action requires that the Business that owns
   this App is a Business Solution Provider for WhatsApp"*, así que **hoy no lo somos**
   y este paso es el bloqueante real.
3. Crear una **Login configuration** de tipo *WhatsApp Embedded Signup* (Facebook Login
   for Business) y copiar su id.
4. Añadir `https://app.vantelia.es` a los dominios permitidos de la app.

Sin el paso 2 el flujo no se puede usar para dar de alta números de OTRAS empresas,
que es justo lo que necesitamos para vender.

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
