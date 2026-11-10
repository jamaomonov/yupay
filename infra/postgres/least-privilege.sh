#!/usr/bin/env bash
# Move the app, backups and the exporter off the Postgres superuser.
# See docs/runbooks/postgres-roles.md. Run on the prod host from ~/opt/yupay:
#
#   bash infra/postgres/least-privilege.sh
#
# Prints no secret. Keeps the old env files as secrets/*.env.bak-<stamp>;
# rolling back is restoring those and recreating the same services.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"
STAMP=$(date -u +%Y%m%d%H%M%S)
DB=yupay

# The tag the stack runs now: a plain `up -d` would fall back to :main.
IMAGE_TAG=$(docker inspect -f '{{.Config.Image}}' yupay-prod-api-1 | sed 's/.*://')
export IMAGE_TAG
echo "running tag: $IMAGE_TAG"

for f in api backup postgres-exporter; do
  cp -p "secrets/$f.env" "secrets/$f.env.bak-$STAMP"
done

# Reuse the passwords from a previous partial run, so a re-run never strands a
# service on a password the role no longer has.
API_PW=$(grep -oE '^DATABASE_URL=[^:]+://yupay_api:[0-9a-f]+@' secrets/api.env | sed -E 's/.*yupay_api:([0-9a-f]+)@/\1/' || true)
API_PW=${API_PW:-$(openssl rand -hex 32)}
MON_PW=$(grep -oE '^DATA_SOURCE_NAME=[^:]+://yupay_monitor:[0-9a-f]+@' secrets/postgres-exporter.env | sed -E 's/.*yupay_monitor:([0-9a-f]+)@/\1/' || true)
MON_PW=${MON_PW:-$(openssl rand -hex 32)}
export API_PW MON_PW

# Passwords travel on stdin, never in a command line.
{
  printf "\\\\set step roles\n\\\\set api_pw '%s'\n\\\\set mon_pw '%s'\n\\\\set dbname '%s'\n" "$API_PW" "$MON_PW" "$DB"
  cat infra/postgres/least-privilege.sql
} | $COMPOSE exec -T postgres psql -q -U yupay_app -d "$DB" >/dev/null
echo "roles: done"

# Ownership, in passes: one object per transaction, 2 s lock timeout, busy
# objects retried on the next pass. Nothing below runs until all are moved.
LEFT=unknown
for pass in $(seq 1 30); do
  LEFT=$({
    printf "\\\\set step owners\n\\\\set dbname '%s'\n" "$DB"
    cat infra/postgres/least-privilege.sql
  } | $COMPOSE exec -T postgres psql -q -At -U yupay_app -d "$DB" 2>/dev/null | tail -n 1)
  echo "ownership pass $pass: $LEFT left"
  [ "$LEFT" = "0" ] && break
  sleep 10
done
if [ "$LEFT" != "0" ]; then
  echo "ownership not finished ($LEFT left) — env files untouched, safe to re-run later" >&2
  exit 1
fi

# Credentials from the environment, so they are not in any argv either.
perl -pi -e 's#^(DATABASE_URL=[^:]+://)[^:@/]+:[^@]*@#${1}yupay_api:$ENV{API_PW}\@#' secrets/api.env
perl -pi -e 's#^PGUSER=.*#PGUSER=yupay_api#; s#^PGPASSWORD=.*#PGPASSWORD=$ENV{API_PW}#' secrets/backup.env
perl -pi -e 's#^(DATA_SOURCE_NAME=[^:]+://)[^:@/]+:[^@]*@#${1}yupay_monitor:$ENV{MON_PW}\@#' secrets/postgres-exporter.env
grep -q '^DATABASE_URL=[^:]*://yupay_api:' secrets/api.env
grep -q '^PGUSER=yupay_api$' secrets/backup.env
grep -q '^DATA_SOURCE_NAME=[^:]*://yupay_monitor:' secrets/postgres-exporter.env
echo "env files: switched (backups: secrets/*.env.bak-$STAMP)"

$COMPOSE up -d --no-deps --force-recreate api worker scheduler bot backup postgres-exporter
echo "services: recreated"

for _ in $(seq 1 30); do
  if $COMPOSE exec -T api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).status==200 else 1)" 2>/dev/null; then
    echo "api readyz: ok"
    $COMPOSE exec -T postgres psql -U yupay_app -d "$DB" -At \
      -c "select usename, count(*) from pg_stat_activity where datname='$DB' group by 1 order by 1"
    exit 0
  fi
  sleep 2
done
echo "api did not become ready — restore secrets/*.env.bak-$STAMP and recreate the same services" >&2
exit 1
