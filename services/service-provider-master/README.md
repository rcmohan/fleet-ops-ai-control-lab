# Service Provider Master Service

Owns provider identity, regional coverage, service capabilities, response-time targets, and capacity profile.

Planned operations:

- `get_service_provider(provider_id)`
- `list_service_providers(region, capability)`
- `create_service_provider(provider)`
- `update_service_provider(provider_id, changes)`
- `set_provider_status(provider_id, status)`

Fleet and maintenance domains store only `service_provider_id` references.

