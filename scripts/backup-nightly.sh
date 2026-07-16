#!/bin/bash
# Backup nocturno Vantelia.
# - Snapshot atomico de SQLite (.backup, no copia el WAL en sucio).
# - Empaqueta config.json + DB + data/<cliente>/info.txt + indices RAG (storage/<cliente>).
# - Rotacion 14 dias.
# - Email a admin si falla, log siempre.

set -euo pipefail

PROJECT="/srv/vantelia"
BACKUP_ROOT="/srv/vantelia-backups"
LOG_FILE="/var/log/vantelia-backup.log"
RETENTION_DAYS=14
TS=$(date +%Y%m%d-%H%M%S)
STAGE="$BACKUP_ROOT/_stage-$TS"
ARCHIVE="$BACKUP_ROOT/vantelia-$TS.tar.gz"

mkdir -p "$BACKUP_ROOT"
mkdir -p "$STAGE"

trap 'rm -rf "$STAGE"' EXIT

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

email_admin() {
  local subject="$1"
  local body="$2"
  docker exec vantelia-app python3 -c "
import sys
sys.path.insert(0, '/app')
from api import _send_email_message, CONSULTA_NOTIFICATION_EMAIL
if CONSULTA_NOTIFICATION_EMAIL:
    _send_email_message(
        CONSULTA_NOTIFICATION_EMAIL,
        '''$subject''',
        '''$body''',
        '<pre>' + '''$body'''.replace('<','&lt;') + '</pre>',
    )
" >> "$LOG_FILE" 2>&1 || log "WARN: no se pudo enviar email admin"
}

on_error() {
  log "ERROR backup linea $1"
  email_admin "Backup Vantelia FALLO" "Backup nocturno fallo a las $(date). Revisa $LOG_FILE en el VPS."
  exit 1
}
trap 'on_error $LINENO' ERR

# 1. config.json
cp "$PROJECT/config.json" "$STAGE/config.json"

# 2. SQLite snapshot atomico
sqlite3 "$PROJECT/storage/vantelia.db" ".backup '$STAGE/vantelia.db'"

# 3. data/ (info.txt por cliente, ligero)
if [ -d "$PROJECT/data" ]; then
  cp -a "$PROJECT/data" "$STAGE/data"
fi

# 4. storage/ (indices RAG por cliente, sin .db ni WAL)
mkdir -p "$STAGE/storage"
for d in "$PROJECT"/storage/*/; do
  [ -d "$d" ] || continue
  name=$(basename "$d")
  case "$name" in
    provider_secrets) continue ;;
  esac
  cp -a "$d" "$STAGE/storage/$name"
done

# 5. Comprimir
tar -czf "$ARCHIVE" -C "$BACKUP_ROOT" "$(basename "$STAGE")"

SIZE=$(du -h "$ARCHIVE" | cut -f1)
log "OK $ARCHIVE ($SIZE)"

# 6. Rotar > N dias
find "$BACKUP_ROOT" -maxdepth 1 -name 'vantelia-*.tar.gz' -type f -mtime +$RETENTION_DAYS -delete

COUNT=$(find "$BACKUP_ROOT" -maxdepth 1 -name 'vantelia-*.tar.gz' -type f | wc -l)
log "Retenidos $COUNT backups (rotacion $RETENTION_DAYS dias)"

# 7. Copia OFFSITE cifrada (FTP de Hostinger, otra maquina).
#    - Clave AES en /root/.vantelia-backup.key (fuera del proyecto: sobrevive deploys).
#    - Credenciales FTP en /root/.vantelia-ftp.env (chmod 600).
#    - Rotacion: 7 huecos por dia de la semana (sobrescribe el del mismo dia).
#    - Un fallo offsite NO invalida el backup local: WARN + email y exit 0.
offsite() {
  local key_file="/root/.vantelia-backup.key"
  local ftp_env="/root/.vantelia-ftp.env"
  if [ ! -f "$ftp_env" ]; then
    log "WARN offsite: falta $ftp_env; solo backup local"
    return 0
  fi
  # shellcheck disable=SC1090
  . "$ftp_env"   # define FTP_HOST, FTP_USER, FTP_PASSWORD
  if [ ! -f "$key_file" ]; then
    openssl rand -hex 32 > "$key_file"
    chmod 600 "$key_file"
    log "WARN offsite: clave nueva generada en $key_file — guardala tambien fuera del VPS"
    email_admin "Backup Vantelia: clave de cifrado nueva" "Se genero una clave nueva en $key_file. Copiala a un gestor de contrasenas: sin ella los backups offsite no se pueden restaurar."
  fi
  local dow
  dow=$(date +%u)   # 1=lunes ... 7=domingo
  local remote_name="vantelia-dia${dow}.tar.gz.enc"
  local enc_file="$BACKUP_ROOT/$remote_name"
  openssl enc -aes-256-cbc -pbkdf2 -salt -in "$ARCHIVE" -out "$enc_file" -pass "file:$key_file"
  if curl -sS --fail --connect-timeout 20 --max-time 900 --ftp-create-dirs \
      -T "$enc_file" "ftp://$FTP_HOST/domains/vantelia.es/backups_privados/$remote_name" \
      --user "$FTP_USER:$FTP_PASSWORD" >> "$LOG_FILE" 2>&1; then
    log "OK offsite $remote_name ($(du -h "$enc_file" | cut -f1))"
  else
    log "WARN offsite: fallo la subida FTP"
    email_admin "Backup Vantelia: fallo la copia offsite" "El backup local se creo bien pero la subida FTP fallo a las $(date). Revisa $LOG_FILE."
  fi
  rm -f "$enc_file"
}
offsite || log "WARN offsite: error inesperado (backup local intacto)"

exit 0
