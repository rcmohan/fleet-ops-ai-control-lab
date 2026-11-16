#!/bin/sh
# Runs once, when the db container starts with an empty data volume.
# Creates one database and login role per service (see database/bootstrap/).
# No `set -eu`: the entrypoint sources this file when it is not executable (as on a
# Windows bind mount), and those options would leak into the entrypoint itself.
psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname postgres \
    -v password="$POSTGRES_PASSWORD" \
    -f /fleetops-bootstrap/create_service_databases.sql
