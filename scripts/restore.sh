#!/bin/sh
# ---------------------------------------------------------------------------
# Restore a Parlo backup made by scripts/backup.sh.
#
#   ./scripts/restore.sh 20261028-031500
#
# Restores the database dump and, if present, the recordings and audio-cache
# tarballs with that timestamp. The API and worker are stopped meanwhile.
# Decrypts .gpg files with BACKUP_PASSPHRASE when needed.
# ---------------------------------------------------------------------------
set -eu
cd "$(dirname "$0")/.."
STAMP="${1:?usage: restore.sh <timestamp>  (see ls backups/)}"
PROJECT="parlo"

decrypt() {
  if [ -f "$1.gpg" ] && [ ! -f "$1" ]; then
    gpg --batch --quiet --pinentry-mode loopback --passphrase "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE}" -o "$1" -d "$1.gpg"
  fi
}

decrypt "backups/db-$STAMP.dump"
[ -f "backups/db-$STAMP.dump" ] || { echo "backups/db-$STAMP.dump not found"; exit 1; }

printf "This replaces the current database and recordings with the %s backup. Continue? [y/N] " "$STAMP"
read -r answer
[ "$answer" = "y" ] || exit 1

docker compose stop api worker
docker compose exec -T db pg_restore -U parlo -d parlo --clean --if-exists --no-owner < "backups/db-$STAMP.dump"
for vol in recordings audio_cache; do
  decrypt "backups/$vol-$STAMP.tar.gz"
  if [ -f "backups/$vol-$STAMP.tar.gz" ]; then
    docker run --rm -v "${PROJECT}_${vol}:/data" -v "$PWD/backups:/backups:ro" alpine:3 \
      sh -c "rm -rf /data/* && tar xzf /backups/$vol-$STAMP.tar.gz -C /data && chown -R 1000:1000 /data"
  fi
done
docker compose start api worker
echo "restored $STAMP"
