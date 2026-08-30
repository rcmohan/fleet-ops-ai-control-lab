# Telematics Unit Master Service

Owns telematics hardware identity, activation metadata, installed firmware inventory, supported capabilities, and remote-command eligibility policy flags.

This directory owns its FastAPI application, domain models, synthetic seed data, generated OpenAPI document, and boundary documentation. It does not use the legacy contract-stub runtime.

Implemented operations:

- `get_telematics_unit(unit_id)`
- `list_telematics_units(filters)`
- `create_telematics_unit(unit)`
- `update_telematics_unit(unit_id, changes)`
- `update_firmware_inventory(unit_id, firmware_version)`
- `set_unit_lifecycle_status(unit_id, status)`
- `set_remote_command_eligibility(unit_id, eligibility)`

Live connectivity and heartbeat observations belong to the Telematics Event or Digital Twin domains.
