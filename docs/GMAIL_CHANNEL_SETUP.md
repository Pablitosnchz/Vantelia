# Canal de envio Gmail

Vantelia puede enviar correos mediante Gmail API y usar SMTP como respaldo
automatico. La conexion se gestiona desde **Admin > Captacion > Canales de
envio**.

## Configuracion del servidor

Variables necesarias:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_GMAIL_REDIRECT_URI=https://app.vantelia.es/auth/google/gmail/callback
GMAIL_TOKEN_ENCRYPTION_KEY=...
EMAIL_SEND_PROVIDER=auto
```

Generar una clave de cifrado:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`EMAIL_SEND_PROVIDER` admite:

- `auto`: Gmail cuando esta conectado y SMTP como respaldo.
- `gmail`: solo Gmail; un fallo no cae a SMTP.
- `smtp`: solo SMTP.

Los access tokens y refresh tokens se guardan cifrados en
`storage/vantelia.db`. El access token se renueva automaticamente.

## Google Cloud

En el proyecto asociado a `GOOGLE_CLIENT_ID`:

1. Habilitar **Gmail API**.
2. Añadir `https://app.vantelia.es/auth/google/gmail/callback` como Authorized
   redirect URI del cliente OAuth web.
3. En Google Auth Platform, añadir la cuenta emisora como test user mientras
   la aplicacion este en Testing.
4. Para permitir conexiones de usuarios externos, publicar la aplicacion y
   completar la verificacion solicitada por Google para el scope
   `https://www.googleapis.com/auth/gmail.send`.

El login con Google y la conexion Gmail usan callbacks y permisos separados.
Conectar Gmail no cambia la cuenta con la que se inicia sesion en Vantelia.

## Operacion

1. Entrar en `/dashboard`.
2. Abrir **Captacion**.
3. Pulsar **Conectar Google** en Canales de envio.
4. Elegir la cuenta emisora y aceptar el permiso de envio.
5. Confirmar que el canal activo muestra **Gmail API**.

Al desconectar, Vantelia revoca el token en Google y elimina la copia local.
