# Service Provider Master Service

Owns provider identity, regional coverage, service capabilities, response-time targets, and capacity profile.

This directory owns its FastAPI application, domain models, synthetic seed data, generated OpenAPI document, and boundary documentation. It does not use the legacy contract-stub runtime.

Implemented operations:

- `get_service_provider(provider_id)`
- `list_service_providers(region, capability)`
- `create_service_provider(provider)`
- `update_service_provider(provider_id, changes)`
- `set_provider_status(provider_id, status)`
- `replace_provider_coverage(provider_id, regions, capabilities)`

Fleet and maintenance domains store only `service_provider_id` references.
