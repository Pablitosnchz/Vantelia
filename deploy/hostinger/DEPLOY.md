# Despliegue en Hostinger para `vantelia.es`

## Recomendacion

La opcion mas limpia es esta:

- `vantelia.es` y `www.vantelia.es`: tu web comercial actual
- `app.vantelia.es`: panel admin, API y widget

Asi no rompes tu web principal y centralizas toda la parte operativa del chatbox en un subdominio separado.

## Importante

Hostinger indica que Python necesita acceso root y que en sus planes Web y Cloud no hay root, por lo que la alternativa es un VPS:

- Python en Hostinger: https://www.hostinger.com/es/support/3648030-es-python-compatible-con-hostinger/

Si tu `vantelia.es` esta hecho con Hostinger Website Builder o Horizons, Hostinger recomienda crear el subdominio como un sitio independiente:

- Subdominios en Hostinger: https://www.hostinger.com/support/1583405-how-to-create-and-delete-subdomains-in-hostinger/

## Arquitectura recomendada

1. Mantener `vantelia.es` donde ya esta.
2. Crear un VPS en Hostinger.
3. Crear `app.vantelia.es` apuntando a la IP del VPS.
4. Desplegar este proyecto en el VPS.
5. Poner HTTPS delante con Nginx Proxy Manager o Nginx.

## Paso 1. Crear el subdominio

Opcion recomendada:

- `app.vantelia.es`

Si usas DNS en Hostinger, crea o edita el registro A del host `app` apuntando a la IP del VPS.

Guia oficial:

- A records: https://www.hostinger.com/support/4468886-how-to-manage-a-records-at-hostinger/

## Paso 2. Preparar el servidor

Sube este repo al VPS, por ejemplo en:

```bash
/srv/vantelia
```

Después copia y ajusta tu `.env` real.

Minimo recomendado en produccion:

```env
OPENAI_API_KEY=tu_clave_real
ADMIN_API_TOKEN=un_token_largo_y_seguro
WEBHOOK_DEFAULT=https://tu-webhook-real
EXTRA_CORS_ORIGINS=https://vantelia.es,https://www.vantelia.es,https://app.vantelia.es
PORT=8000
LOG_LEVEL=INFO
```

## Paso 3. Ajustar `config.json`

Para tu cliente principal o demo, añade los dominios reales:

```json
"allowed_origins": [
  "https://vantelia.es",
  "https://www.vantelia.es",
  "https://app.vantelia.es"
]
```

## Paso 4. Levantar la app con Docker

Desde la raiz del repo:

```bash
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
```

La API quedara escuchando en:

```text
http://TU_IP_DEL_VPS:8000
```

## Paso 5. Poner HTTPS delante

La forma mas sencilla en Hostinger VPS es usar Nginx Proxy Manager.

Guia oficial:

- https://www.hostinger.com/support/how-to-set-up-nginx-proxy-manager-using-hostinger-docker-manager/

Configura un Proxy Host:

- Domain Names: `app.vantelia.es`
- Forward Hostname / IP: IP del VPS
- Forward Port: `8000`
- SSL: Let’s Encrypt activado

## Paso 6. URLs finales

Cuando quede desplegado:

- Dashboard admin: `https://app.vantelia.es/dashboard`
- Widget script: `https://app.vantelia.es/widget/widget.min.js`
- API base: `https://app.vantelia.es`

Snippet final:

```html
<script
  src="https://app.vantelia.es/widget/widget.min.js"
  data-api="https://app.vantelia.es"
  data-client="demo"
  data-position="right"
></script>
```

## Paso 7. Integrarlo en `vantelia.es`

En tu web principal inserta el snippet anterior.

Si `vantelia.es` usa Website Builder, normalmente deberas pegarlo en el bloque o zona de custom code del sitio.

## Lo que puedo hacer yo por ti

Puedo dejarte preparado en el proyecto:

- configuracion para `app.vantelia.es`
- `config.json` y `.env.example` orientados a produccion
- snippets finales para tu propia web
- una version del widget ya lista para incrustar en `vantelia.es`
- una checklist exacta para Hostinger hPanel paso a paso

Lo que no puedo hacer directamente desde aqui:

- entrar en tu cuenta de Hostinger
- crear el VPS
- tocar DNS reales
- pulsar botones en hPanel por ti

## Vuelta atras (rollback)

Antes, si un despliegue salia mal la app se quedaba rota y el mensaje era "haz
git revert y vuelve a desplegar": minutos de reconstruccion con los clientes del
negocio escribiendo. Ahora el despliegue lleva red propia.

### Lo que hace solo cada `deploy.ps1`

1. **Foto de la base de datos antes de tocar nada**, con `.backup` de SQLite (no
   `cp`: copiar el fichero a pelo deja el WAL fuera). Va a
   `/srv/vantelia-backups/pre-deploy-<fecha>.db` y se guardan las 10 ultimas.
   Esto tapa el hueco del backup nocturno, que puede llevar 24 h encima.
2. **Etiqueta la imagen que funciona** como `vantelia:prev` antes de reconstruir.
   Por eso volver atras son segundos y no una reconstruccion.
3. **Vuelve atras solo** si falla la construccion, si la app no responde al
   healthcheck, o si el humo detecta una conversacion rota. No hay que decidir
   nada a las tantas: produccion queda en la ultima version que funcionaba.

El healthcheck publico (`https://app.vantelia.es/health`) NO dispara rollback a
proposito: el local ya dijo que la app esta viva, asi que un fallo ahi apunta al
proxy o a tu conexion, y revertir produccion por un corte de wifi seria peor.

### Volver atras a mano

```powershell
.\deploy\deploy.ps1 -Rollback
```

Restaura `/srv/vantelia_prev`, conserva los datos vivos y verifica el health.

### La regla que no se puede romper

**El rollback revierte el CODIGO, nunca los DATOS.** El arbol `_prev` lleva
dentro copias de `storage/` y `data/` del despliegue anterior; restaurarlo tal
cual borraria las citas, chats y pagos entrados desde entonces. Por eso el
estado vivo (`storage`, `data`, `secrets`, `client_sites`, `config.json`, `.env`)
VIAJA desde el arbol que falla al restaurado, y si la base de datos no llega a su
sitio el script **no arranca la app**: arrancar sin ella no da error, crea una
vacia, y el negocio veria su agenda borrada sin un solo aviso.

Lo vigila `tests/test_rollback_conserva_los_datos.py`. La primera version del
script hacia esto al reves -movia el estado antes de intercambiar los arboles- y
un `mv` fallido dejaba la base de datos viva fuera de produccion: la red de
seguridad empeorando el incidente.

Solo se guarda **una** generacion hacia atras (`_prev`). Para ir mas atras, el
backup nocturno de `/srv/vantelia-backups`.
