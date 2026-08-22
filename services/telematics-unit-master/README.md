# Telematics Unit Master Service

Owns telematics hardware identity, activation metadata, installed firmware inventory, supported capabilities, and remote-command eligibility policy flags.

Planned operations:

- `get_telematics_unit(unit_id)`
- `create_telematics_unit(unit)`
- `update_firmware_inventory(unit_id, firmware_version)`
- `set_unit_lifecycle_status(unit_id, status)`
- `set_remote_command_eligibility(unit_id, eligibility)`

Live connectivity and heartbeat observations belong to the Telematics Event or Digital Twin domains.

