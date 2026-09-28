#!/usr/bin/env bash
# Monta (o rehace) el puente SIP de Sara en el VPS: ElevenLabs -> este Asterisk -> Zadarma.
# Por que existe y como se comprueba: docs/SARA_SIP.md, "El puente".
#
# Uso, como root en el VPS:   bash /srv/vantelia/deploy/sara-puente/montar.sh
#
# Lee del .env de la app las credenciales de la extension de Zadarma
# (ZADARMA_EXTENSION_USUARIO / _CLAVE). La clave con la que entra ElevenLabs se genera la
# primera vez y se guarda en /srv/sara-puente/clave_elevenlabs (va tambien en el .env de la
# app como CAPTACION_SIP_CLAVE). Nada de esto va a git.
#
# Rehacerlo corta las llamadas en curso. Si el puente nuevo no queda registrado en Zadarma,
# vuelve solo a la configuracion y la imagen de antes y sale con error.
set -euo pipefail

ORIGEN="$(cd "$(dirname "$0")" && pwd)"
DESTINO=/srv/sara-puente
ENV_APP=/srv/vantelia/.env
# Imagen fijada por su huella: con "latest", una version nueva podia cambiar el puente sin
# que nadie lo decidiera (revision de Astra, 28-sep-2026). Asterisk 22.10.1.
IMAGEN="${SARA_PUENTE_IMAGEN:-andrius/asterisk@sha256:6ef1eb2dd14f34c4b5d226cd05a98aeda000bcaf4ac05f49c6c199a09249f8b7}"
FICHEROS="pjsip.conf extensions.conf modules.conf rtp.conf"

val() { grep "^$1=" "$ENV_APP" | tail -1 | cut -d= -f2- | tr -d '"\r'; }
ZU=$(val ZADARMA_EXTENSION_USUARIO)
ZP=$(val ZADARMA_EXTENSION_CLAVE)
if [ -z "$ZU" ] || [ -z "$ZP" ]; then
  echo "Faltan ZADARMA_EXTENSION_USUARIO / ZADARMA_EXTENSION_CLAVE en $ENV_APP" >&2
  exit 1
fi

mkdir -p "$DESTINO/anterior" "$DESTINO/sonidos"
chmod 700 "$DESTINO"
[ -s "$DESTINO/clave_elevenlabs" ] || openssl rand -hex 16 > "$DESTINO/clave_elevenlabs"
chmod 600 "$DESTINO/clave_elevenlabs"
CL=$(cat "$DESTINO/clave_elevenlabs")

# Lo que hay ahora, por si hay que volver.
IMAGEN_ANTERIOR=$(docker inspect -f '{{.Config.Image}}' sara-puente 2>/dev/null || true)
for f in $FICHEROS; do
  if [ -f "$DESTINO/$f" ]; then cp -p "$DESTINO/$f" "$DESTINO/anterior/$f"; fi
done

arrancar() {  # $1 = imagen
  docker rm -f sara-puente >/dev/null 2>&1 || true
  # Red del host: el audio va por 10000-10100/udp y mapear ese rango en docker no aporta nada.
  docker run -d --name sara-puente --network host --restart unless-stopped \
    -v "$DESTINO/pjsip.conf:/etc/asterisk/pjsip.conf:ro" \
    -v "$DESTINO/extensions.conf:/etc/asterisk/extensions.conf:ro" \
    -v "$DESTINO/modules.conf:/etc/asterisk/modules.conf:ro" \
    -v "$DESTINO/rtp.conf:/etc/asterisk/rtp.conf:ro" \
    -v "$DESTINO/sonidos:/var/lib/asterisk/sounds/vantelia:ro" \
    "$1" >/dev/null
}

registrado() {  # espera hasta 60 s a que la extension quede "Registered" en Zadarma
  for _ in $(seq 1 20); do
    sleep 3
    if docker exec sara-puente asterisk -rx "pjsip show registrations" 2>/dev/null | grep -q "Registered"; then
      return 0
    fi
  done
  return 1
}

docker pull -q "$IMAGEN" >/dev/null
# Asterisk baja a su usuario 'asterisk': si pjsip.conf es solo de root no lo lee y el puente
# arranca sin SIP ("Permission denied", 28-sep-2026). Sigue siendo 600: nadie mas lo lee.
UID_A=$(docker run --rm --entrypoint id "$IMAGEN" -u asterisk)
GID_A=$(docker run --rm --entrypoint id "$IMAGEN" -g asterisk)

# Las claves son alfanumericas (Zadarma) y hex (la nuestra): sed con '|' no las rompe.
sed -e "s|__ZADARMA_USUARIO__|$ZU|g" -e "s|__ZADARMA_CLAVE__|$ZP|g" -e "s|__CLAVE_ELEVENLABS__|$CL|g" \
  "$ORIGEN/pjsip.conf.plantilla" > "$DESTINO/pjsip.conf"
cp "$ORIGEN/extensions.conf" "$ORIGEN/modules.conf" "$ORIGEN/rtp.conf" "$DESTINO/"
chown "$UID_A:$GID_A" "$DESTINO/pjsip.conf"
chmod 600 "$DESTINO/pjsip.conf"

arrancar "$IMAGEN"
if ! registrado; then
  echo "!! El puente nuevo no se ha registrado en Zadarma en 60 s." >&2
  if [ -n "$IMAGEN_ANTERIOR" ] && [ -f "$DESTINO/anterior/pjsip.conf" ]; then
    for f in $FICHEROS; do cp -p "$DESTINO/anterior/$f" "$DESTINO/$f"; done
    arrancar "$IMAGEN_ANTERIOR"
    if registrado; then
      echo "!! Vuelto a la version anterior ($IMAGEN_ANTERIOR), que si se registra." >&2
    else
      echo "!! La version anterior tampoco se registra: revisar Zadarma y el .env." >&2
    fi
  fi
  exit 1
fi

docker exec sara-puente asterisk -rx "pjsip show registrations" | grep -E "Registered|Rejected|Unregistered"
echo "Puertos del puente (solo deberia salir 5099, mas algun puerto alto de consultas DNS):"
ss -lntup | grep -i asterisk | awk '{print $1, $5}' | sort -u
