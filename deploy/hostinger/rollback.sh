#!/bin/bash
# Vuelta atras al arbol anterior del VPS, en segundos y sin reconstruir.
#
# Existe porque el deploy dejaba la app rota si el healthcheck fallaba: te decia
# "haz git revert y vuelve a desplegar", y eso son minutos de reconstruccion con
# los clientes del negocio escribiendo por WhatsApp. Aqui la imagen anterior ya
# esta etiquetada (vantelia:prev), asi que volver es levantar un contenedor.
#
# REGLA QUE NO SE PUEDE ROMPER: se revierte el CODIGO, nunca los DATOS. El arbol
# _prev lleva dentro copias de storage/ y data/ del deploy anterior; si se
# cambiara sin mas, se perderian las citas, los chats y los pagos entrados desde
# entonces. Por eso el estado vivo VIAJA desde el arbol que falla al restaurado.
#
# ORDEN DELIBERADO: primero los movimientos que pueden fallar (renombrar arboles)
# y solo despues se toca el estado. Al reves -probado y descartado- un fallo del
# mv dejaba la base de datos viva fuera de produccion: la red de seguridad
# empeorando el incidente en vez de arreglarlo.
#
# Uso:  bash rollback.sh [PROYECTO] [COMPOSE] [IMAGEN] [CONTENEDOR] [PUERTO]
#
# Todos los argumentos tienen por defecto los de PRODUCCION, asi que la llamada
# de siempre -sin argumentos, o solo con la ruta- se comporta exactamente igual
# que antes de existir el entorno de pruebas.
set -euo pipefail

REMOTE_PROJECT="${1:-/srv/vantelia}"
COMPOSE_FILE="${2:-deploy/hostinger/docker-compose.yml}"
IMAGE_BASE="${3:-vantelia}"
CONTENEDOR="${4:-vantelia-app}"
PUERTO="${5:-8000}"

PREV_DIR="${REMOTE_PROJECT}_prev"
TS="$(date +%Y%m%d-%H%M%S)"
FAILED_DIR="${REMOTE_PROJECT}_failed-${TS}"
IMAGE_CURRENT="${IMAGE_BASE}:current"
IMAGE_PREV="${IMAGE_BASE}:prev"

# Lo que pertenece al negocio y jamas se revierte con el codigo.
ESTADO_DIRS="storage data secrets client_sites"
ESTADO_FILES="config.json .env"

if [ ! -d "$PREV_DIR" ]; then
  echo "No hay version anterior en $PREV_DIR: nada que restaurar." >&2
  echo "Arregla el codigo y vuelve a desplegar." >&2
  exit 1
fi

echo "==> Rollback a la version anterior ($PREV_DIR)"

# 1. Apartar el arbol que falla. Es la operacion que puede romper, asi que va
#    primero: si falla aqui, no se ha tocado nada y produccion sigue como estaba.
if ! mv "$REMOTE_PROJECT" "$FAILED_DIR"; then
  echo "No se pudo apartar $REMOTE_PROJECT. No se ha tocado nada." >&2
  exit 1
fi

# 2. El arbol anterior pasa a ser produccion.
if ! mv "$PREV_DIR" "$REMOTE_PROJECT"; then
  echo "No se pudo restaurar $PREV_DIR. Deshaciendo..." >&2
  mv "$FAILED_DIR" "$REMOTE_PROJECT" || \
    echo "!! CRITICO: el proyecto quedo en $FAILED_DIR. Muevelo a mano." >&2
  exit 1
fi

# 3. El estado vivo viaja del arbol que fallo al restaurado, pisando las copias
#    viejas que ese arbol traia de su dia.
for stateful in $ESTADO_DIRS; do
  if [ -d "${FAILED_DIR}/${stateful}" ]; then
    rm -rf "${REMOTE_PROJECT:?}/${stateful}"
    mv "${FAILED_DIR}/${stateful}" "${REMOTE_PROJECT}/${stateful}"
    echo "    estado conservado: ${stateful}"
  fi
done
for stateful in $ESTADO_FILES; do
  if [ -f "${FAILED_DIR}/${stateful}" ]; then
    cp "${FAILED_DIR}/${stateful}" "${REMOTE_PROJECT}/${stateful}"
    echo "    estado conservado: ${stateful}"
  fi
done

# 4. Antes de arrancar: comprobar que la base de datos viva esta en su sitio.
#    Arrancar sin ella no da error, crea una vacia: el negocio veria su agenda
#    borrada y no habria ni un aviso.
if [ ! -f "${REMOTE_PROJECT}/storage/vantelia.db" ] && [ -f "${FAILED_DIR}/storage/vantelia.db" ]; then
  echo "!! La base de datos no llego al arbol restaurado. NO se arranca." >&2
  echo "!! Esta intacta en ${FAILED_DIR}/storage/vantelia.db" >&2
  exit 1
fi

echo "    arbol que fallaba guardado en $FAILED_DIR"
# Solo se guardan los dos ultimos arboles fallidos: son copias enteras del
# proyecto y el disco del VPS no es infinito.
ls -1dt "${REMOTE_PROJECT}_failed-"* 2>/dev/null | tail -n +3 | xargs -r rm -rf

cd "$REMOTE_PROJECT"

# 5. La imagen anterior ya esta construida y etiquetada: volver son segundos.
if docker image inspect "$IMAGE_PREV" >/dev/null 2>&1; then
  docker tag "$IMAGE_PREV" "$IMAGE_CURRENT"
  echo "    imagen anterior restaurada (sin reconstruir)"
  docker compose -f "$COMPOSE_FILE" up -d --force-recreate 2>&1
else
  echo "    no hay imagen anterior etiquetada: toca reconstruir (mas lento)"
  docker compose -f "$COMPOSE_FILE" up -d --build 2>&1
fi

# 6. Verificar que la version restaurada responde de verdad.
attempt=1
while true; do
  if health_response="$(curl --fail --silent --max-time 5 http://127.0.0.1:${PUERTO}/health 2>/dev/null)"; then
    echo "$health_response"
    echo "==> Rollback completado: la version anterior responde."
    exit 0
  fi
  if [ "$attempt" -ge 40 ]; then
    echo "" >&2
    echo "!! LA VERSION ANTERIOR TAMPOCO RESPONDE. Ultimos logs:" >&2
    docker logs "$CONTENEDOR" --tail 120 >&2 || true
    exit 1
  fi
  echo "    esperando a la version anterior... intento $attempt/40"
  attempt=$((attempt + 1))
  sleep 3
done
