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

exit 0
