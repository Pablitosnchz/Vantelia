# Operacion minima antes de vender agresivamente

Este documento deja una base practica para operar Vantelia con mas tranquilidad antes de acelerar ventas.

## 1. Tests minimos

Ejecutar antes de cada despliegue:

```powershell
python -V
python -m pytest
npm run build
python -m py_compile api.py auto_onboarding.py onboarding_utils.py
```

La version local debe ser Python 3.11 o superior, alineada con el Dockerfile de produccion.

Que cubren ahora mismo:

- `/health` responde y comprueba configuracion, storage y base de datos.
- Los endpoints publicos respetan dominios autorizados.
- El panel admin exige token o sesion.
- El login crea sesion de portal.
- La disponibilidad de citas funciona sin depender de OpenAI.
- El chat guarda conversaciones cuando detecta una solicitud de cita.
- El admin puede consultar sesiones y mensajes guardados.

## 2. Backups

Backup local recomendado:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1
```

Por defecto copia:

- `config.json`
- `data/`
- `storage/`
- `manifest.json` con hashes SHA256

Si necesitas incluir `.env`, usa:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1 -IncludeEnv
```

Notas:

- `.env` contiene secretos. No compartas backups con `.env` por canales inseguros.
- `backups/` esta ignorado por Git.
- Antes de cambios grandes en produccion, genera un backup y verifica que el ZIP existe.

## 3. Monitorizacion

Endpoint principal:

```text
https://app.vantelia.es/health
```

El campo `status` debe ser `ok`. Si aparece `degraded`, revisa `checks`.

Checks incluidos:

- `config`: existe `config.json`.
- `data_dir`: existe la carpeta de cerebros.
- `storage_dir`: existe la carpeta de almacenamiento.
- `database`: SQLite responde.
- `widget_bundle`: existe `widget/widget.min.js`.

Comprobacion rapida desde servidor:

```bash
curl --fail http://127.0.0.1:8000/health
docker logs vantelia-app --tail 120
```

## 4. Legal basico

Rutas publicas:

- `/legal/privacidad`
- `/legal/terminos`
- `/legal/cookies`
- `/legal/ia`

Los textos viven en:

```text
docs/legal/
```

Importante: son plantillas iniciales, no sustituyen revision legal. Antes de publicar de forma comercial, revisar responsable real, CIF/NIF, direccion, bases juridicas, proveedores, plazos de conservacion, cookies reales y contratos con clientes.

## 5. Rutina antes de vender a volumen

1. Ejecutar tests.
2. Crear backup.
3. Desplegar.
4. Revisar `/health`.
5. Probar una demo real.
6. Probar una reserva.
7. Confirmar que las paginas legales estan visibles.
