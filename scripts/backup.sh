#!/bin/sh
# ---------------------------------------------------------------------------
# Parlo backup: database dump + audio cache + voice recordings → ./backups,
# keeping the newest $BACKUP_KEEP of each (default 7).
#
#   ./scripts/backup.sh
#
# Nightly from the host's crontab (crontab -e):
#   15 3 * * * cd /home/deploy/parlo && ./scripts/backup.sh >> backups/backup.log 2>&1
#
# Set BACKUP_PASSPHRASE (in the environment or .env) to encrypt every file
# with gpg (AES-256) — recommended before copying backups off the server.
# Alternative to cron: `docker compose --profile backup up -d` runs the same
# job inside a container (scripts/backup-loop.sh).
# ---------------------------------------------------------------------------
set -eu
cd "$(dirname "$0")/.."

[ -f .env ] && BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-$(grep -E '^BACKUP_PASSPHRASE=' .env | cut -d= -f2- || true)}"
KEEP="${BACKUP_KEEP:-7}"
STAMP="$(date +%Y%m%d-%H%M%S)"
# volume names are prefixed with the compose project name (`name: parlo`)
PROJECT="parlo"
mkdir -p backups

encrypt() {
  if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
    gpg --batch --yes --quiet --pinentry-mode loopback --passphrase "$BACKUP_PASSPHRASE" \
      --symmetric --cipher-algo AES256 -o "$1.gpg" "$1" && rm -f "$1"
  fi
}

echo "[$STAMP] dumping database"
docker compose exec -T db pg_dump -U parlo -d parlo --format=custom > "backups/db-$STAMP.dump"
encrypt "backups/db-$STAMP.dump"

for vol in recordings audio_cache; do
  echo "[$STAMP] archiving $vol"
  docker run --rm -v "${PROJECT}_${vol}:/data:ro" -v "$PWD/backups:/backups" alpine:3 \
    tar czf "/backups/$vol-$STAMP.tar.gz" -C /data .
  encrypt "backups/$vol-$STAMP.tar.gz"
done

for prefix in db recordings audio_cache; do
  ls -1t backups/"$prefix"-* 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; done
done
echo "[$STAMP] done — $(ls -1 backups | wc -l | tr -d ' ') files in ./backups"
