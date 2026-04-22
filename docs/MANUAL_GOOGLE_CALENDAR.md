# Manual de Google Calendar

Esta guia explica como conectar un cliente de Vantelia con Google Calendar para que las citas se creen de verdad.

## Objetivo

Con esta integracion, cuando un usuario completa el formulario de cita:

- Vantelia valida la disponibilidad.
- Vantelia crea el evento real en Google Calendar.
- La reserva tambien queda registrada dentro de Vantelia.
- Los datos del cliente quedan dentro del evento, aunque Google no envie invitacion automatica al asistente en el modo simple.

## Requisitos

Necesitas:

- una cuenta de Google
- acceso a Google Calendar
- acceso a Google Cloud Console
- acceso al panel admin de Vantelia

## Paso 1. Crear o elegir el calendario

Puedes usar:

- tu calendario principal
- o un calendario secundario solo para citas

Para encontrar el `Calendar ID`:

1. Abre Google Calendar.
2. En la columna izquierda, localiza el calendario.
3. Entra en `Configuracion y uso compartido`.
4. Baja a `Integrar calendario`.
5. Copia `ID del calendario`.

Ejemplo:

```text
acb1aaccbe43320664e9a7529fd96332b84bef91d18ad0b4ed0e99f2979dbc9e@group.calendar.google.com
```

## Paso 2. Activar la Google Calendar API

1. Abre Google Cloud Console.
2. Crea o selecciona un proyecto.
3. Ve a `APIs y servicios`.
4. Entra en `Biblioteca`.
5. Busca `Google Calendar API`.
6. Pulsa `Activar`.

## Paso 3. Crear la service account

1. En Google Cloud, entra en `IAM y administracion`.
2. Abre `Cuentas de servicio`.
3. Pulsa `Crear cuenta de servicio`.
4. Ponle un nombre reconocible, por ejemplo `vantelia-citas`.
5. Entra en esa cuenta.
6. Abre la pestaña `Claves`.
7. Crea una clave nueva tipo `JSON`.
8. Descarga el archivo JSON.

Ese JSON es la credencial que Vantelia usara para crear eventos.

## Paso 4. Compartir el calendario con la service account

Este paso es obligatorio.

1. Abre el JSON descargado.
2. Busca el campo `client_email`.
3. Copia ese correo.
4. Vuelve a Google Calendar.
5. Entra en la configuracion del calendario.
6. En `Compartir con personas y grupos`, añade ese `client_email`.
7. Dale permiso `Hacer cambios en eventos`.

Si no haces esto, Google devolvera `403 Forbidden`.

## Paso 5. Configurar el cliente en Vantelia

En el panel admin del cliente:

- `Proveedor real`: `google_calendar`
- `Google Calendar ID directo`: pega el `Calendar ID`
- `Google service account JSON`: pega el JSON completo

Ese es el modo facil.

No hace falta usar:

- `Google Calendar ID env`
- `Google service account env`

Esos campos solo se usan si prefieres un modo avanzado con variables de entorno.

## Paso 6. Guardar el cliente

Cuando guardas:

- Vantelia valida el JSON
- Vantelia guarda la credencial en el servidor
- Vantelia actualiza la configuracion del cliente
- Vantelia reindexa si esa opcion esta activada

## Paso 7. Probar una cita real

Haz la prueba en:

- la demo compartible del cliente
- o la web real si el snippet ya esta instalado

Rellena una cita de prueba y confirma.

Si todo esta bien:

- la cita se crea en Google Calendar
- el chat devuelve mensaje de confirmacion
- la reserva queda registrada tambien en Vantelia

## Como funciona en el modo simple

La integracion simple de Vantelia con Google Calendar crea el evento directamente en tu calendario usando la service account.

Esto esta pensado para:

- calendarios compartidos
- cuentas personales de Gmail
- configuraciones sencillas sin Google Workspace avanzado

Importante:

- Vantelia crea el evento en tu calendario
- los datos del cliente van en la descripcion del evento
- no se envia invitacion de Google Calendar al cliente como asistente

Si algun dia quieres invitaciones reales al asistente desde Google Calendar, normalmente hace falta una configuracion mas avanzada de Google Workspace con delegacion de dominio.

## Errores tipicos

### `403 Forbidden`

La service account no tiene permiso sobre el calendario.

Solucion:

- compartir el calendario con el `client_email`
- dar permiso `Hacer cambios en eventos`
- comprobar que la `Google Calendar API` sigue activada en el proyecto correcto

Senal clara:

- si en los logs ves que Vantelia hace `POST` contra Google Calendar y Google responde `403 Forbidden`, la autenticacion esta funcionando pero el calendario no ha dado permiso de escritura a la service account
- si cambias el `Calendar ID` y sigue dando `403`, normalmente sigues teniendo un problema de permisos, no de codigo

### `accessNotConfigured`

La service account pertenece a un proyecto de Google Cloud donde la `Google Calendar API` no esta activada.

Ejemplo real de error:

```text
Google Calendar ha rechazado la cita (403). Detalle: accessNotConfigured: Google Calendar API has not been used in project 679185370499 before or it is disabled.
```

Solucion:

1. Copia el `project` que aparece en el error.
2. Abre el enlace que devuelve Google o entra manualmente en Google Cloud Console.
3. Activa la `Google Calendar API` exactamente en ese proyecto.
4. Espera unos minutos.
5. Vuelve a probar la cita.

Importante:

- el proyecto correcto es el de la service account que esta usando Vantelia
- no siempre coincide con el proyecto que tienes abierto en Google Cloud
- si acabas de activarla, puede tardar un poco en propagarse

### `404 Not Found`

El `Calendar ID` es incorrecto o el calendario no existe.

### `No se ha podido crear la cita en el proveedor de calendario`

Vantelia esta intentando crear la cita en Google Calendar, pero Google la ha rechazado.

Hay que mirar logs del backend.

### `El JSON de la service account de Google no es valido`

El JSON pegado en el panel no es correcto o esta incompleto.

## Comprobacion rapida en el VPS

Si una cita falla:

```bash
docker logs vantelia-app --tail 120
```

Si ves `403 Forbidden`, casi siempre falta compartir el calendario con la service account.

Si ves `accessNotConfigured`, la API no esta activada en el proyecto correcto de Google Cloud.
