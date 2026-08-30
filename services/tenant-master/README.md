# Tenant Master Service

Owns tenant identity and lifecycle. Other master-data services receive the opaque tenant ID through the required `X-Tenant-ID` header and never read this database directly.

The service owns its FastAPI application, validation models, PostgreSQL migration, generated OpenAPI document, and tests.
