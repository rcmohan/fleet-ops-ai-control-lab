# Master Data Database Migrations

Each child directory is owned by one service and must be applied to a separate PostgreSQL database. The identical `master_data` schema name is intentional because database isolation, rather than schema naming, establishes the boundary.

Example for a development environment:

```powershell
psql -d fleetops_vehicle_master -f database/vehicle-master/001_create_schema.sql
psql -d fleetops_telematics_unit_master -f database/telematics-unit-master/001_create_schema.sql
psql -d fleetops_fleet_master -f database/fleet-master/001_create_schema.sql
psql -d fleetops_maintenance_history -f database/maintenance-history/001_create_schema.sql
psql -d fleetops_service_provider_master -f database/service-provider-master/001_create_schema.sql
```

Do not apply all scripts to one database in production and do not add cross-database foreign keys. Later changes should be added as ordered migrations rather than editing a migration that has already been deployed.

