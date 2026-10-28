-- Read-only role the chatbot executor connects as (story 34).
-- Run after schema.sql and seed.sql. The password is a demo value; override it
-- outside the demo.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'a7_reader') THEN
        CREATE ROLE a7_reader LOGIN PASSWORD 'a7_reader';
    END IF;
END
$$;

ALTER ROLE a7_reader SET default_transaction_read_only = on;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO a7_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO a7_reader;
