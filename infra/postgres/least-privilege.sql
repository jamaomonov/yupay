-- Move the application off the Postgres superuser (audit 2026-11-10).
--
-- `yupay_app` is the image's bootstrap superuser (OID 10): Postgres will not
-- strip its SUPERUSER, so the app moves to a new role instead.
--
--   yupay_api      LOGIN, no SUPERUSER/CREATEDB/CREATEROLE; owns the database,
--                  the public schema and every object in it, so migrations
--                  (ALTER TABLE, CREATE INDEX, trusted CREATE EXTENSION) work.
--   yupay_monitor  LOGIN, pg_monitor only — for postgres-exporter.
--   yupay_app      stays the superuser, for `docker compose exec postgres psql`
--                  (local socket, trust) and emergencies; nothing connects as
--                  it over the network once the env files are switched.
--
-- Idempotent. Run as yupay_app with psql variables:
--   :step    'roles' (create roles, set passwords, database + schema owner)
--            or 'owners' (one pass of the object ownership change)
--   :api_pw  :mon_pw  (passwords, hex — no URL escaping needed; 'roles' only)
--   :dbname  (the application database)
-- See infra/postgres/least-privilege.sh and docs/runbooks/postgres-roles.md.
--
-- The ownership change runs one object per transaction under a 2 s
-- lock_timeout, and never as one big transaction. ALTER ... OWNER takes an
-- ACCESS EXCLUSIVE lock; inside a single transaction each lock is held to
-- COMMIT, so one table held by a long scheduler transaction queued every
-- request behind the script and took prod down for ~3 minutes on 2026-11-10.
-- A busy object is skipped and the wrapper runs another pass.

\set ON_ERROR_STOP on
SET lock_timeout = '2s';
SELECT :'step' = 'roles' AS do_roles \gset

\if :do_roles
SELECT format('CREATE ROLE yupay_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'api_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'yupay_api') \gexec
SELECT format('ALTER ROLE yupay_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'api_pw') \gexec

SELECT format('CREATE ROLE yupay_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'mon_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'yupay_monitor') \gexec
SELECT format('ALTER ROLE yupay_monitor PASSWORD %L', :'mon_pw') \gexec
GRANT pg_monitor TO yupay_monitor;

SELECT format('ALTER DATABASE %I OWNER TO yupay_api', :'dbname') \gexec
ALTER SCHEMA public OWNER TO yupay_api;
\else
-- Autocommit: every \gexec statement is its own transaction. A lock timeout
-- on one object must not stop the pass.
\set ON_ERROR_STOP off
-- Tables, views, matviews (their indexes and owned sequences follow).
SELECT format('ALTER TABLE public.%I OWNER TO yupay_api', c.relname)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND pg_get_userbyid(c.relowner) <> 'yupay_api'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e') \gexec
-- Sequences not owned by a column.
SELECT format('ALTER SEQUENCE public.%I OWNER TO yupay_api', c.relname)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind = 'S'
  AND pg_get_userbyid(c.relowner) <> 'yupay_api'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a', 'i', 'e')) \gexec
-- Enum/domain/composite types and functions, should any appear.
SELECT format('ALTER TYPE public.%I OWNER TO yupay_api', t.typname)
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
  AND t.typtype IN ('e', 'd')
  AND pg_get_userbyid(t.typowner) <> 'yupay_api'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = t.oid AND d.deptype = 'e') \gexec
SELECT format('ALTER ROUTINE %s OWNER TO yupay_api', p.oid::regprocedure)
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND pg_get_userbyid(p.proowner) <> 'yupay_api'
  AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e') \gexec

-- The last line of output: objects still on another owner (extension members
-- excepted). The wrapper switches nothing until this is 0.
SELECT
  (SELECT count(*)
   FROM pg_class c
   JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public'
     AND pg_get_userbyid(c.relowner) <> 'yupay_api'
     AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
     AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype = 'e'))
  + (SELECT count(*)
     FROM pg_type t
     JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname = 'public'
       AND t.typtype IN ('e', 'd')
       AND pg_get_userbyid(t.typowner) <> 'yupay_api'
       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = t.oid AND d.deptype = 'e'))
  + (SELECT count(*)
     FROM pg_proc p
     JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND pg_get_userbyid(p.proowner) <> 'yupay_api'
       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e'))
  AS left_on_other_owner;
\endif
