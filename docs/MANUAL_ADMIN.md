# Manual de Administracion

Guia practica para gestionar Vantelia Embedded Chat desde el panel admin.

Este manual esta pensado para una persona administradora que necesita dar de alta empresas, mantener sus cerebros actualizados y dejar cada chat listo para instalar sin tocar codigo.

## Chuleta rapida de uso diario

Esta es la parte mas practica del manual. Si vas con prisa, normalmente esto es lo que mas vas a usar.

### URLs que usaras mucho

- Portal de acceso: `https://app.vantelia.es/acceso`
- Panel admin: `https://app.vantelia.es/dashboard`
- Raiz API: `https://app.vantelia.es/`
- Salud del sistema: `https://app.vantelia.es/health`
- Demo de un cliente: `https://app.vantelia.es/demo/cliente_id`

Ejemplo:

- `https://app.vantelia.es/demo/clinica_saga`

### Flujo rapido para operar un cliente

1. Entrar al portal o al panel.
2. Crear o abrir cliente.
3. Revisar cerebro y dominios.
4. Guardar.
5. Reindexar si has tocado el cerebro.
6. Abrir demo.
7. Copiar snippet cuando este aprobado.

### Comandos que mas usaras en tu equipo

Script recomendado para actualizar casi todo el proyecto:

```powershell
cd E:\Vantelia
powershell -ExecutionPolicy Bypass -File .\deploy\deploy.ps1
```

Este script:

- empaqueta el proyecto limpio
- sube la nueva version al VPS
- conserva `.env`, `config.json`, `data` y `storage`
- reconstruye Docker
- comprueba la salud de la app
- reintenta el `healthcheck` si la app tarda unos segundos en arrancar

Configuracion recomendada en `.env` para ejecutar sin preguntas usando clave SSH:

```env
DEPLOY_SERVER_HOST=root@72.62.188.104
DEPLOY_REMOTE_BASE=/srv
DEPLOY_REMOTE_PROJECT=/srv/vantelia
DEPLOY_ARCHIVE_NAME=vantelia-deploy.tar.gz
DEPLOY_SSH_KEY_PATH=C:\Users\TU_USUARIO\.ssh\vantelia_deploy
DEPLOY_DEMO_CLIENT=clinica_saga
```

Importante:

- No es buena idea guardar la password del VPS en `.env`.
- `ssh` y `scp` no trabajan bien con password automatizada desde `.env`.
- Lo profesional es usar una clave SSH y dejar que el script la lea.

Generar una clave SSH nueva en tu equipo:

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\vantelia_deploy
```

Copiar la clave publica al VPS:

```powershell
type $HOME\.ssh\vantelia_deploy.pub | ssh root@72.62.188.104 "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys"
```

Probar acceso sin password:

```powershell
ssh -i $HOME\.ssh\vantelia_deploy root@72.62.188.104
```

Si quieres omitir las comprobaciones locales:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy.ps1 -SkipLocalChecks
```

Uso recomendado de `-SkipLocalChecks`:

- cuando acabas de desplegar hace poco
- cuando has cambiado poco codigo
- cuando quieres iterar mas rapido

Nota importante:

- durante un redeploy es normal que el primer `healthcheck` falle una vez justo al reiniciar el contenedor
- si el script espera, reintenta y termina con `Despliegue completado`, el despliegue ha salido bien

Entrar por SSH al VPS:

```bash
ssh root@72.62.188.104
```

Subir `api.py`:

```powershell
scp "E:\Vantelia\api.py" root@72.62.188.104:/srv/vantelia/
```

Subir panel admin:

```powershell
scp -r "E:\Vantelia\admin_ui" root@72.62.188.104:/srv/vantelia/
```

Subir widget:

```powershell
scp -r "E:\Vantelia\widget" root@72.62.188.104:/srv/vantelia/
```

Subir manual:

```powershell
scp "E:\Vantelia\docs\MANUAL_ADMIN.md" root@72.62.188.104:/srv/vantelia/docs/
```

Subir una version completa del proyecto:

```powershell
cd E:\
tar --exclude="Vantelia/.git" `
    --exclude="Vantelia/.venv" `
    --exclude="Vantelia/node_modules" `
    --exclude="Vantelia/storage" `
    --exclude="Vantelia/__pycache__" `
    --exclude="Vantelia/Identidad Visual" `
    -czf vantelia-deploy.tar.gz Vantelia

scp .\vantelia-deploy.tar.gz root@72.62.188.104:/srv/
```

Cuando usar este metodo:

- Si has creado carpetas nuevas.
- Si has cambiado muchos archivos.
- Si no quieres ir subiendo pieza por pieza.
- Si quieres actualizar casi todo el proyecto de una vez.

### Comandos que mas usaras dentro del VPS

Ir al proyecto:

```bash
cd /srv/vantelia
```

Reconstruir y levantar la app:

```bash
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
```

Ver contenedores:

```bash
docker ps
```

Comprobar salud local:

```bash
curl http://127.0.0.1:8000/health
```

Ver logs de la app:

```bash
docker logs vantelia-app --tail 80
```

Crear carpeta `docs` si falta:

```bash
mkdir -p /srv/vantelia/docs
```

Actualizar el proyecto completo desde un paquete:

```bash
cd /srv
rm -rf /srv/vantelia_new
mkdir -p /srv/vantelia_new
tar -xzf /srv/vantelia-deploy.tar.gz -C /srv/vantelia_new --strip-components=1

cp /srv/vantelia/.env /srv/vantelia_new/.env

mv /srv/vantelia /srv/vantelia_prev
mv /srv/vantelia_new /srv/vantelia

cd /srv/vantelia
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
docker ps
curl http://127.0.0.1:8000/health
```

Limpieza opcional cuando todo va bien:

```bash
rm -rf /srv/vantelia_prev
rm -f /srv/vantelia-deploy.tar.gz
```

### Comprobaciones rapidas tras una actualizacion

En navegador:

- `https://app.vantelia.es/`
- `https://app.vantelia.es/dashboard`
- `https://app.vantelia.es/demo/clinica_saga`

En el VPS:

```bash
docker ps
curl http://127.0.0.1:8000/health
```

### Regla rapida para no liarte

- Si cambias clientes desde el panel: guardar, reindexar y probar demo.
- Si cambias codigo: subir archivos al VPS y hacer `docker compose ... up -d --build`.
- Si has cambiado mucho o has creado carpetas nuevas: usa el paquete completo `vantelia-deploy.tar.gz`.

### Booking real con proveedor

Ahora Vantelia puede trabajar de una formaa:

- `internal`: guarda la solicitud en Vantelia y la manda por webhook si existe.

Campos importantes del panel admin:

- `Proveedor real`
- `Google service account JSON`

Ejemplo para Calendly en `.env` del VPS:

```env
CALENDLY_API_TOKEN=tu_token_real
CALENDLY_USER_URI_CLINICA_SAGA=https://api.calendly.com/users/XXXXXXXX
CALENDLY_EVENT_TYPE_URI_CLINICA_SAGA=https://api.calendly.com/event_types/YYYYYYYY
```

Y en el panel del cliente:

- `Proveedor real`: `calendly`
- `Calendly user env`: `CALENDLY_USER_URI_CLINICA_SAGA`
- `Calendly event type env`: `CALENDLY_EVENT_TYPE_URI_CLINICA_SAGA`
- `Calendly location kind`: solo si tu event type lo necesita, por ejemplo `zoom_conference`

Notas practicas:

- Con `google_calendar`, la disponibilidad sigue saliendo de la configuracion horaria del cliente y el evento se crea de verdad en Google.
- Con `calendly`, la disponibilidad del formulario se consulta contra Calendly y la cita se crea alli.
- Si falta una credencial o un permiso del proveedor, la reserva no se confirmara.
- Para enviar recuperaciones de acceso y correos operativos desde `info@vantelia.es`, configura `SMTP_USERNAME`, `SMTP_PASSWORD` y `SMTP_FROM_EMAIL`.
- Para centralizar respuestas humanas en `soporte@vantelia.es`, configura `SMTP_REPLY_TO` y `PORTAL_SUPPORT_EMAIL`.
- Para ajustar la caducidad del enlace de reset, usa `PASSWORD_RESET_TOKEN_HOURS`.

## 1. Que es lo que administras

Cada empresa cliente tiene su propio entorno dentro de Vantelia. A efectos practicos, cada cliente tiene:

- Un identificador interno.
- Un nombre comercial.
- Un cerebro, que es el contenido de `info.txt`.
- Unos dominios autorizados donde puede mostrarse el chat.
- Una configuracion visual y comercial.
- Un snippet de instalacion para poner el chat en su web.
- Una URL de demo para revisarlo antes de instalarlo.

La idea principal es simple:

1. Das de alta una empresa.
2. Generas o revisas su cerebro.
3. Guardas.
4. Reindexas si hace falta.
5. Revisas la demo compartible.
6. Copias el snippet y el chat queda listo para instalar.

## 2. Acceso al panel

Ahora Vantelia tiene dos puertas de entrada:

- `acceso`: portal profesional con login por sesion para admin y clientes.
- `dashboard`: panel tecnico interno del admin.

Ejemplo de acceso real:

- `app.vantelia.es/acceso`
- `app.vantelia.es/dashboard`

Flujo recomendado:

1. El admin entra por `acceso`.
2. Desde ahi abre `dashboard` cuando necesita mantenimiento profundo.
3. Los clientes entran por `acceso` y solo ven sus reservas.

El token admin sigue existiendo como respaldo tecnico, pero el acceso normal ya debe hacerse por sesion.

## 3. Mapa rapido del panel

Cuando entras al panel, normalmente trabajas en estas zonas:

- Zona de acceso: sirve para validar el token admin.
- Estadisticas: da una vision general de clientes, indices y estado de la plataforma.
- Listado de clientes: permite localizar y abrir un cliente existente.
- Editor de cliente: sirve para ajustar nombre, bienvenida, dominios autorizados y cerebro.
- Alta express: crea un cliente nuevo a partir de la web de la empresa.
- Snippet de instalacion: te da el bloque final para insertar el chat en una web.

## 3.1 Portal y accesos de cliente

El portal permite profesionalizar la relacion con cada empresa.

Que gana Vantelia con esto:

- Un acceso propio para el admin.
- Un acceso privado para cada cliente.
- Un sitio unico desde el que revisar y operar reservas.
- Una base clara para unir `vantelia.es` con `app.vantelia.es`.

Como crear un acceso cliente:

1. Entra como admin en `acceso`.
2. Usa el bloque `Crear acceso de cliente`.
3. Indica nombre visible, email, contraseña inicial y `cliente_id`.
4. El cliente podra iniciar sesion y vera solo las reservas de su empresa.

Buenas practicas:

- Crear un acceso por empresa, aunque luego anadas mas.
- Usar un email operativo real del cliente.
- Pedir al cliente que cambie la contrasena inicial en cuanto entre al portal.
- Si la olvida, puede usar `He olvidado mi contrasena` y recuperar el acceso por correo.

## 4. Flujo recomendado de trabajo

Para mantener orden y velocidad, este es el proceso recomendado:

1. Revisar si el cliente ya existe.
2. Si no existe, usar Alta express con la web corporativa.
3. Leer el cerebro generado y corregir errores o ausencias.
4. Confirmar dominios autorizados.
5. Guardar cliente.
6. Verificar que el snippet corresponde a la web donde se va a instalar.
7. Hacer una prueba real del chat.

## 4.1 Gestion diaria de reservas

El panel ya permite operar reservas sin salir del dashboard.

Que puedes hacer:

- Ver las reservas del cliente activo.
- Filtrar por estado.
- Reenviar el email de confirmacion o cancelacion.
- Abrir la pagina segura de gestion del cliente.
- Abrir la URL del proveedor externo si existe.
- Cancelar una cita.
- Reprogramar una cita.
- Lanzar recordatorios manualmente.

Flujo recomendado cuando entra una cita:

1. Abrir el cliente en el panel.
2. Bajar a la tabla de `Reservas`.
3. Revisar fecha, hora, servicio, proveedor y estado del email.
4. Si todo esta correcto, no hace falta hacer nada mas.
5. Si el cliente llama para cambiar la cita, usar `Reprogramar`.
6. Si el cliente cancela, usar `Cancelar`.
7. Si dice que no ha recibido nada, usar `Reenviar email`.

Estados principales:

- `confirmed`: cita confirmada y activa.
- `pending_review`: solicitud guardada pendiente de revision manual.
- `cancelled`: cita cancelada.

Campos utiles en la tabla:

- `provider_name`: indica si la reserva vive en `internal`, `google_calendar` o `calendly`.
- `provider_booking_id`: identificador externo de la cita.
- `customer_email_status`: ultimo resultado del correo al cliente.
- `manage_url`: enlace seguro para que el cliente gestione su propia cita.

Notas importantes:

- Las reservas de `Calendly` normalmente se gestionan mejor desde la URL del proveedor.
- Las de `Google Calendar` pueden cancelarse y reprogramarse desde Vantelia.
- Los recordatorios pueden lanzarse a mano desde el boton `Enviar recordatorios`, aunque el sistema tambien puede hacerlo automaticamente si esta configurado.
- Si `SMTP` no esta configurado, la cita se guardara igual, pero no saldran correos de confirmacion ni recordatorios.
- Las citas ya pasadas no conviene borrarlas sin mas: es mejor archivarlas como historial para mantener control y trazabilidad.

### Escalado y volumen de citas

Si el volumen crece, la regla recomendada es esta:

- `Proximas`: las que aun requieren accion o seguimiento.
- `Historial`: las ya pasadas, canceladas o completadas.

Vantelia ya esta preparado para trabajar asi:

- el portal cliente separa proximas e historicas
- las citas confirmadas pueden marcarse como completadas automaticamente cuando ya han pasado
- el historico sigue accesible, pero no ensucia la operativa diaria

Variable util en `.env`:

```env
BOOKING_AUTO_COMPLETE_HOURS=6
```

Ejemplo practico:

- si una cita termino hace mas de 6 horas, el sistema puede pasarla a `completed`
- sigue visible en historial
- deja de aparecer como cita editable

## 5. Alta de un cliente nuevo

Tienes dos formas de crear un cliente.

### Opcion A. Alta express

Es la opcion recomendada para la mayoria de empresas.

Que hace:

- Lee la web publica de la empresa.
- Resume y reorganiza la informacion.
- Genera un cerebro inicial bien estructurado.
- Puede guardar el cliente en un clic.
- Puede dejar el snippet listo para copiar.

Cuando usarla:

- Cuando el cliente ya tiene web corporativa.
- Cuando quieres ir rapido.
- Cuando necesitas una primera version profesional en pocos minutos.

Que revisar despues:

- Que el nombre comercial sea correcto.
- Que no falten servicios clave.
- Que los precios, horarios y ubicacion sean reales.
- Que la propuesta de valor no este inventada ni demasiado generica.
- Que el tono encaje con la marca del cliente.

### Opcion B. Alta manual

Es la mejor opcion cuando:

- La web del cliente es pobre.
- La empresa aun no tiene web.
- Tienes documentacion interna mejor que la web.
- El sector exige mucha precision.

En este caso, rellenas el cliente directamente y pegas el cerebro a mano en el editor.

## 6. Como debe quedar un cliente bien configurado

Un cliente esta bien configurado cuando cumple estas condiciones:

- El nombre comercial coincide exactamente con la marca.
- El identificador interno es claro y estable.
- Los dominios autorizados incluyen la web real donde se va a instalar.
- El mensaje de bienvenida suena natural y profesional.
- El cerebro responde bien sobre servicios, precios, dudas y contacto.
- El snippet apunta al cliente correcto.

## 7. Que significa cada campo importante

### Identificador del cliente

Es el nombre interno del cliente dentro del sistema.

Buenas practicas:

- Usar un nombre corto y estable.
- Evitar cambiarlo una vez el cliente ya esta instalado.
- Mantener una convencion clara entre todos los clientes.

Ejemplos buenos:

- `clinica_saga`
- `vantelia_demo`
- `reformas_norte`

### Nombre comercial

Es el nombre que ve la persona usuaria y el que usa el asistente al presentarse o hablar de la empresa.

Debe coincidir con la marca real.

### Dominios autorizados

Son las webs donde se permite cargar el chat.

Buenas practicas:

- Incluir la version principal del dominio.
- Incluir la version con `www` si el cliente la usa.
- Incluir subdominios si el chat va en microsites o landings.

Ejemplo conceptual:

- Dominio principal de la empresa.
- Version con `www`.
- Landing de campaÃ±as si existe.

### Mensaje de bienvenida

Es la primera impresion del chat.

Debe:

- Explicar para que sirve el asistente.
- Invitar a preguntar.
- Sonar cercano y profesional.
- Ajustarse al sector.

Ejemplo de enfoque correcto:

- En una clinica, priorizar ayuda, confianza y reserva.
- En una agencia, priorizar claridad, diagnostico y contacto comercial.
- En un negocio local, priorizar servicios, horarios y ubicacion.

### Cerebro o contenido base

Es la parte mas importante de todo el sistema. Si el cerebro esta mal, el chat respondera mal aunque todo lo demas este perfecto.

## 8. Como debe estar organizado el cerebro

El cerebro debe estar escrito para que la IA entienda la empresa con rapidez y sin ambiguedad.

La estructura ideal incluye:

- Presentacion de la empresa.
- Servicios principales.
- Servicios secundarios.
- Publico objetivo.
- Diferenciadores.
- Precios o forma de presupuestar.
- Proceso comercial o de trabajo.
- Horarios.
- Ubicacion y zonas de servicio.
- Preguntas frecuentes.
- Objeciones habituales.
- Politicas relevantes.
- Datos de contacto y vias de derivacion humana.

SeÃ±ales de un cerebro bueno:

- Es concreto.
- No repite lo mismo en exceso.
- No mezcla informacion contradictoria.
- Usa lenguaje empresarial claro.
- Responde las dudas reales que tendria una persona interesada.

SeÃ±ales de un cerebro flojo:

- Texto vago y genÃ©rico.
- Frases publicitarias sin datos utiles.
- Servicios mal definidos.
- Falta de precios, proceso o condiciones.
- Preguntas frecuentes inexistentes.

## 9. Como revisar un cerebro generado por Alta express

Antes de dar por bueno un cliente nuevo, revisa siempre:

- Empresa: nombre, sector, ubicacion.
- Servicios: que esten todos los importantes.
- Conversion: que se entienda que puede pedir informacion, presupuesto o cita.
- Contacto: que haya una salida clara a humano.
- Politicas: cancelaciones, plazos, cobertura geografica, condiciones.
- Errores: frases inventadas, datos dudosos o mezclas raras.

Regla sencilla:

- Si algo es critico para vender o atender, debe aparecer de forma explicita en el cerebro.

## 10. Cuando guardar y cuando reindexar

Guardar y reindexar no son exactamente lo mismo.

### Guardar

Sirve para almacenar los cambios del cliente.

Debes guardar cuando:

- Creas un cliente nuevo.
- Cambias nombre, bienvenida o dominios.
- Editas el cerebro.

### Reindexar

Sirve para reconstruir el indice que usa la IA para consultar la informacion del cliente.

Debes reindexar cuando:

- Cambias el cerebro.
- Corriges informacion importante.
- Actualizas servicios o politicas.
- AÃ±ades mucho contenido nuevo.

No hace falta reindexar si solo haces cambios menores puramente visuales, salvo que el panel lo haga automaticamente dentro del flujo.

## 11. Instalacion del chat en la web del cliente

Una vez el cliente esta bien configurado, el panel genera un snippet de instalacion.

Como administradora o administrador, tu trabajo aqui es confirmar tres cosas:

- Que el cliente seleccionado es el correcto.
- Que el dominio donde va a instalarse esta autorizado.
- Que la persona que instala el chat usa el snippet exacto de ese cliente.

Error tipico:

- Instalar el snippet de un cliente en la web de otro.

## 12. Demo compartible para cliente

Cada cliente puede tener una URL de demo publica para validacion previa.

Formato recomendado:

- `app.vantelia.es/demo/cliente_id`

Ejemplo:

- `app.vantelia.es/demo/clinica_saga`

Para que sirve:

- EnseÃ±ar el chat al cliente antes de instalarlo.
- Validar tono, respuestas y flujo comercial.
- Recoger feedback rapido sin tocar la web final.

Uso recomendado:

1. Creas o actualizas el cliente.
2. Revisas el cerebro.
3. Abres la demo.
4. Haces preguntas reales.
5. Si hace falta, corriges y reindexas.
6. Cuando este aprobado, instalas el snippet en la web final.

## 13. Como actualizar la plataforma

No todas las actualizaciones son iguales. Lo primero es identificar que tipo de cambio has hecho.

### Actualizacion de contenido

Es cuando cambias cosas como:

- El cerebro del cliente.
- La bienvenida.
- Los dominios autorizados.
- Datos de contacto.
- Configuracion comercial o de booking.

En este caso, normalmente no hace falta tocar el servidor a nivel tecnico si lo haces desde el panel admin.

Flujo recomendado:

1. Entras al panel.
2. Abres el cliente.
3. Editas lo necesario.
4. Guardas.
5. Reindexas si has tocado el cerebro.
6. Pruebas la demo compartible.

Esto es la forma normal de operar clientes en el dia a dia.

### Actualizacion de software

Es cuando cambias cosas como:

- El backend.
- El widget.
- El panel admin.
- Nuevas rutas como demos, nuevas funciones o mejoras visuales.
- Cambios de seguridad, rendimiento o integraciones.

En este caso si hace falta actualizar la instancia desplegada en el VPS.

## 14. Flujo recomendado para subir cambios al VPS

Cuando haces cambios de software, el proceso correcto es este:

1. Haces los cambios en tu proyecto local.
2. Compruebas que todo funciona localmente.
3. Subes la nueva version del proyecto al servidor, dentro de la misma carpeta del despliegue.
4. Reconstruyes la aplicacion en Docker.
5. Verificas que la web, el panel y las demos siguen funcionando.

Tu carpeta de despliegue en produccion deberia seguir siendo:

- `/srv/vantelia`

Comandos base para entrar al VPS:

```bash
ssh root@TU_IP_DEL_VPS
```

Una vez dentro, el proyecto debe estar en:

```bash
cd /srv/vantelia
```

## 15. Dos formas practicas de actualizar

### Opcion A. Actualizacion manual por subida de archivos

Es la opcion mas simple si estas operando tu mismo el proyecto.

Consiste en:

1. Reemplazar en el VPS los archivos modificados del proyecto.
2. Volver a construir el contenedor.
3. Levantar la nueva version.

Es una buena opcion cuando:

- Aun estas en fase de crecimiento.
- Haces cambios frecuentes.
- No quieres montar todavia un flujo mas avanzado con repositorio y despliegue automatico.

#### Variante 1. Subir solo los archivos cambiados

Es la forma mas rapida cuando has tocado pocos archivos.

Ejemplo desde tu ordenador Windows:

```powershell
scp "E:\Vantelia\api.py" root@TU_IP_DEL_VPS:/srv/vantelia/
scp "E:\Vantelia\requirements.txt" root@TU_IP_DEL_VPS:/srv/vantelia/
scp -r "E:\Vantelia\admin_ui" root@TU_IP_DEL_VPS:/srv/vantelia/
scp -r "E:\Vantelia\widget" root@TU_IP_DEL_VPS:/srv/vantelia/
```

Despues, dentro del VPS:

```bash
cd /srv/vantelia
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
docker ps
curl http://127.0.0.1:8000/health
```

Cuando usar esta variante:

- Si has cambiado `api.py`
- Si has cambiado el panel `admin_ui`
- Si has cambiado el `widget`
- Si has tocado `requirements.txt`

#### Variante 2. Subir una version completa empaquetada

Es mas ordenada cuando has cambiado bastantes cosas.

Desde tu ordenador Windows:

```powershell
cd E:\
tar --exclude="Vantelia/.git" `
    --exclude="Vantelia/.venv" `
    --exclude="Vantelia/node_modules" `
    --exclude="Vantelia/storage" `
    --exclude="Vantelia/__pycache__" `
    --exclude="Vantelia/Identidad Visual" `
    -czf vantelia-deploy.tar.gz Vantelia

scp .\vantelia-deploy.tar.gz root@TU_IP_DEL_VPS:/srv/
```

Despues, dentro del VPS:

```bash
cd /srv
rm -rf /srv/vantelia_new
mkdir -p /srv/vantelia_new
tar -xzf /srv/vantelia-deploy.tar.gz -C /srv/vantelia_new --strip-components=1

cp /srv/vantelia/.env /srv/vantelia_new/.env

mv /srv/vantelia /srv/vantelia_prev
mv /srv/vantelia_new /srv/vantelia

cd /srv/vantelia
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
docker ps
curl http://127.0.0.1:8000/health
```

Consejo importante:

- No sobrescribas `.env` de produccion por accidente.
- No borres `storage` si no sabes exactamente por que.
- Si vas a hacer este metodo, comprueba antes que el paquete contiene lo que realmente quieres subir.

### Opcion B. Actualizacion desde repositorio

Es la opcion mas profesional a medio plazo.

Consiste en:

1. Guardar los cambios en un repositorio.
2. Descargar la ultima version en el VPS.
3. Reconstruir el contenedor.
4. Verificar la plataforma.

Es mejor cuando:

- Ya trabajas con versiones.
- Quieres dejar trazabilidad.
- Quieres evitar errores al copiar archivos a mano.

Comandos tipicos dentro del VPS:

```bash
cd /srv/vantelia
git pull
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
docker ps
curl http://127.0.0.1:8000/health
```

Si cambias dependencias y quieres forzar reconstruccion limpia:

```bash
cd /srv/vantelia
docker compose -f deploy/hostinger/docker-compose.yml build --no-cache
docker compose -f deploy/hostinger/docker-compose.yml up -d
docker ps
curl http://127.0.0.1:8000/health
```

## 16. Que revisar despues de cada actualizacion

Despues de actualizar el software, revisa siempre:

- Que la raiz del dominio responde.
- Que el panel admin abre bien.
- Que una demo por cliente carga correctamente.
- Que el widget aparece.
- Que el chat responde.
- Que el guardado de clientes sigue funcionando.

Checklist minima de validacion:

- `app.vantelia.es`
- `app.vantelia.es/dashboard`
- `app.vantelia.es/demo/cliente_de_prueba`
- Un cliente real del listado

Pruebas rapidas utiles:

```bash
curl http://127.0.0.1:8000/health
docker ps
docker logs vantelia-app --tail 80
```

## 17. Cuando no hace falta redeplegar

No hace falta actualizar el servidor completo cuando solo cambias:

- El `info.txt` de un cliente desde el panel.
- La bienvenida.
- El color.
- Los dominios autorizados.
- Los datos comerciales o de contacto.

En esos casos, el trabajo correcto es:

1. Guardar.
2. Reindexar si aplica.
3. Probar demo.
4. Entregar.

## 18. Cuando si hace falta redeplegar

Si has tocado cualquiera de estas partes, si debes actualizar el VPS:

- `api.py`
- `admin_ui`
- `widget`
- `Dockerfile`
- `requirements.txt`
- `onboarding_utils.py`
- cualquier logica nueva de producto

Regla facil:

- Si cambia el funcionamiento del sistema, hay que redeplegar.
- Si solo cambia la configuracion o contenido de un cliente, no hace falta redeplegar.

Ejemplos de redeploy necesario:

- Nueva ruta como `demo/cliente`
- Cambios en el dashboard
- Cambios en la logica del widget
- Cambios en el Dockerfile
- Cambios de dependencias

## 19. Buen criterio para trabajar sin errores

Antes de subir cambios al VPS, conviene seguir esta disciplina:

1. No mezclar cambios tecnicos con cambios urgentes de clientes si no hace falta.
2. Probar primero con un cliente demo.
3. Verificar una demo compartible antes de avisar a nadie.
4. Hacer el cambio en horas tranquilas si afecta a muchos clientes.
5. Tener claro que version estas subiendo.

## 20. Caso practico

### Caso: alta de una clinica nueva

Empresa:

- Clinica Dental Aurora

Objetivo:

- Tener un chat que responda dudas, explique tratamientos y ayude a pedir cita.

Proceso ideal:

1. Entras al panel.
2. Vas a Alta express.
3. Pegas la web de la clinica.
4. Generas el cliente en un clic.
5. Revisas el cerebro.
6. Confirmas que aparezcan implantes, ortodoncia, higiene, blanqueamiento y urgencias.
7. Compruebas horarios, direccion y telefono.
8. Ajustas el mensaje de bienvenida para que invite a resolver dudas o pedir cita.
9. Revisas dominios autorizados.
10. Guardas y dejas el snippet listo.
11. Pruebas el chat como si fueras un paciente.

Preguntas de prueba recomendadas:

- Que tratamientos ofrecÃ©is.
- Cuanto cuesta una primera valoracion.
- Teneis urgencias.
- Donde estais.
- Quiero pedir cita.

Si el chat responde bien a esas preguntas, el cliente ya esta muy cerca de estar listo para produccion.

## 21. Checklist antes de entregar un cliente

- El nombre comercial es correcto.
- El identificador interno es definitivo.
- Los dominios autorizados estan completos.
- El mensaje de bienvenida encaja con la marca.
- El cerebro contiene servicios, FAQs, proceso y contacto.
- El indice esta actualizado.
- La demo compartible funciona y se ha validado.
- El snippet corresponde al cliente correcto.
- Se ha hecho una prueba real de conversacion.
- Se han revisado citas o derivacion a contacto humano si aplica.

## 22. Mantenimiento diario, semanal y mensual

### Tareas diarias

- Revisar que el panel carga bien.
- Comprobar que los clientes principales responden.
- Detectar errores evidentes reportados por clientes.

### Tareas semanales

- Revisar si algun cliente ha cambiado servicios, horarios o promos.
- Actualizar cerebros cuando haya nueva informacion.
- Verificar que los dominios autorizados siguen siendo correctos.
- Probar una conversacion real en varios clientes.

### Tareas mensuales

- Auditar calidad de respuestas.
- Limpiar clientes de prueba que ya no sirvan.
- Revisar si conviene mejorar prompts o bienvenida.
- Comprobar que el flujo de reserva y contacto sigue teniendo sentido.

## 23. Buenas practicas para operar muchas empresas

- Mantener una convencion unica de nombres internos.
- No duplicar clientes para hacer pruebas rapidas sin control.
- Separar claramente demos, pruebas y clientes reales.
- Documentar cualquier cambio importante en el cerebro.
- Revisar siempre el cliente seleccionado antes de guardar.
- Diferenciar claramente entre actualizar contenido y actualizar software.
- Hacer una prueba final desde la web real del cliente.

## 24. Errores frecuentes y como evitarlos

### Error: el chat no aparece en la web

Posibles causas:

- El dominio no esta autorizado.
- El snippet pertenece a otro cliente.
- La web donde se instala no es la prevista.

### Error: el chat responde cosas incompletas

Posibles causas:

- El cerebro es pobre.
- Faltan preguntas frecuentes.
- No se reindexo despues de editar.

### Error: el chat suena demasiado generico

Posibles causas:

- Bienvenida muy neutra.
- Contenido base poco especifico.
- Falta de diferenciadores y contexto comercial.

### Error: la empresa dice que hay datos incorrectos

Posibles causas:

- Alta express genero una inferencia imperfecta.
- La web del cliente estaba desactualizada.
- Nadie reviso el cerebro antes de publicar.

### Error: he hecho cambios pero no se ven en produccion

Posibles causas:

- Solo has guardado los cambios en tu equipo local.
- Aun no has actualizado el VPS.
- Falta reconstruir la aplicacion.
- Estas mirando una demo o pagina cacheada.

## 25. Seguridad y control

Puntos clave para cualquier administrador:

- El token admin es privado.
- No se comparte acceso global con clientes finales.
- Los secretos de produccion no se mandan por canales inseguros.
- Si una credencial se expone, se rota.
- Los dominios autorizados deben revisarse con cuidado.

## 26. Estandar de calidad Vantelia

Antes de considerar un cliente como entregable, el chat debe ser:

- Claro.
- Util.
- Coherente con la marca.
- Correcto en datos importantes.
- Facil de instalar.
- Facil de mantener.

## 27. Resumen operativo

Si una persona nueva se incorpora a administrar la plataforma, debe recordar solo esto:

1. Crear o localizar el cliente.
2. Revisar el cerebro con criterio humano.
3. Confirmar dominios y bienvenida.
4. Guardar y reindexar cuando toque.
5. Probar la demo compartible.
6. Copiar el snippet correcto.
7. Si hay cambios de software, actualizar el VPS.
8. Hacer una prueba real antes de entregar.

Con eso ya puede operar la plataforma con seguridad y buen nivel profesional.
