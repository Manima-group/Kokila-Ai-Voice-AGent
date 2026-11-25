#!/bin/sh
# Creates the least-privilege application role (NOBYPASSRLS). Runs once on an empty data volume.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE kokila_app LOGIN PASSWORD '${KOKILA_APP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
CREATE EXTENSION IF NOT EXISTS vector;
SQL
