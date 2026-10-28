#!/bin/sh
# Runs inside the optional `backup` compose service (postgres:18-alpine image):
# once a day at $BACKUP_HOUR (container clock, UTC) it writes a pg_dump and
# tarballs of the audio cache and recordings to /backups, keeping $BACKUP_KEEP.
set -eu
KEEP="${BACKUP_KEEP:-7}"
HOUR="${BACKUP_HOUR:-3}"

run_backup() {
  STAMP="$(date +%Y%m%d-%H%M%S)"
  echo "[$STAMP] backup starting"
  pg_dump --format=custom > "/backups/db-$STAMP.dump"
  for vol in recordings audio_cache; do
    tar czf "/backups/$vol-$STAMP.tar.gz" -C "/volumes/$vol" .
  done
  for prefix in db recordings audio_cache; do
    ls -1t /backups/"$prefix"-* 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; done
  done
  echo "[$STAMP] backup done"
}

while true; do
  now_h=$(date +%H | sed 's/^0//')
  now_m=$(date +%M | sed 's/^0//')
  wait_min=$(( ((HOUR - ${now_h:-0} + 24) % 24) * 60 - ${now_m:-0} ))
  [ "$wait_min" -le 0 ] && wait_min=$((wait_min + 1440))
  echo "next backup in ${wait_min} min"
  sleep $((wait_min * 60))
  run_backup || echo "backup failed"
done
