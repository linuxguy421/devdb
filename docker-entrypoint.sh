#!/bin/sh
set -e
# Named volumes often mount as root; fix ownership so USER devdb can write avatars.
if [ -d /app/data/avatars ] || mkdir -p /app/data/avatars 2>/dev/null; then
  chown -R devdb:devdb /app/data/avatars 2>/dev/null || true
fi
exec gosu devdb "$@"
