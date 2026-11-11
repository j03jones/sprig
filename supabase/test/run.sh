#!/usr/bin/env bash
# Tests supabase/schema.sql against a throwaway local PostgreSQL (needs the postgres server binaries).
#   bash supabase/test/run.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)"
DIR="$(mktemp -d)"; PORT=54329
run() { if [ "$(id -u)" = 0 ]; then chown -R postgres "$DIR"; su postgres -c "$*"; else bash -c "$*"; fi; }
trap 'run "$BIN/pg_ctl -D $DIR/data stop -m immediate >/dev/null 2>&1 || true"; rm -rf "$DIR"' EXIT
chmod 755 "$DIR"; [ "$(id -u)" = 0 ] && chown postgres "$DIR"
run "$BIN/initdb -D $DIR/data -A trust >/dev/null"
run "$BIN/pg_ctl -D $DIR/data -o '-p $PORT -k $DIR' -l $DIR/log -w start >/dev/null"
P="$BIN/psql -h $DIR -p $PORT -U postgres -v ON_ERROR_STOP=1 -X -q"
SCHEMA="$(mktemp)"; sed "s/CHANGE-ME@example.com/admin@x.test/" "$HERE/../schema.sql" > "$SCHEMA"; chmod 644 "$SCHEMA"
run "$P -f $HERE/stubs.sql postgres"
run "$P -f $SCHEMA postgres"
run "$P -f $HERE/test.sql postgres" | tee "$DIR/out.txt" || true
grep -q "FAIL" "$DIR/out.txt" && { echo "SOME CHECKS FAILED"; exit 1; } || true
