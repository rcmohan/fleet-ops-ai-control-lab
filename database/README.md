# Database Bootstrap

Master-data migrations are owned by their corresponding folders under `services/`. The `database/init` scripts only bootstrap logical PostgreSQL databases for local Compose. Transactional-domain migrations that have not yet been implemented remain here.

Example for a development environment:

```powershell
psql -d fleetops_maintenance_history -f database/maintenance-history/001_create_schema.sql
```

Each implemented master service applies its own ordered migrations during startup. Do not add cross-database foreign keys.
