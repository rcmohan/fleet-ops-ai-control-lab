-- One database and one login role per service. A role owns only its own database and
-- PUBLIC cannot connect to any of them, so a service cannot read another service's data.
-- Safe to re-run: existing roles and databases are left as they are.
--
--   psql -U <admin> -d postgres -v password='<service password>' -f create_service_databases.sql
--
-- Compose runs this automatically on a fresh volume (database/docker-init/).
--
-- Each service applies its own migrations from database/<service>/ when it starts.

\set ON_ERROR_STOP on

CREATE TEMP TABLE fleetops_services (name text PRIMARY KEY);
INSERT INTO fleetops_services (name) VALUES
    ('fleetops_vehicle_master'),
    ('fleetops_telematics_unit_master'),
    ('fleetops_fleet_master'),
    ('fleetops_maintenance_history'),
    ('fleetops_service_provider_master'),
    ('fleetops_telematics_event'),
    ('fleetops_digital_twin_context'),
    ('fleetops_policy_playbook'),
    ('fleetops_incident_search'),
    ('fleetops_case_management'),
    ('fleetops_notification'),
    ('fleetops_approval'),
    ('fleetops_audit_observability'),
    ('fleetops_signal_correlation');

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', name, :'password')
FROM fleetops_services
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = name)
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', name, name)
FROM fleetops_services
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = name)
\gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', name)
FROM fleetops_services
\gexec
