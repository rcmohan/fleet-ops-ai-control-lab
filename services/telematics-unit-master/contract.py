from fleetops_runtime import Operation, ServiceContract


UNIT = {
    "unitId": "tcu_demo_001",
    "serialNumber": "TCU-SYNTH-0001",
    "hardwareModel": "NX-5G",
    "firmwareVersion": "3.4.1",
    "activationDate": "2026-01-15",
    "networkCarrier": "Synthetic Wireless",
    "lifecycleStatus": "active",
    "remoteCommandEligibility": "approval_required",
    "capabilities": ["diagnostics", "location", "remote_command"],
    "sourceVersion": 1,
}

CONTRACT = ServiceContract(
    slug="telematics-unit-master",
    title="Telematics Unit Master Service",
    description="Authoritative telematics hardware inventory and capability metadata.",
    operations=(
        Operation("GET", "/v1/telematics-units/{unit_id}", "getTelematicsUnit", "Get a telematics unit", {**UNIT, "unitId": "{unit_id}"}),
        Operation("POST", "/v1/telematics-units", "createTelematicsUnit", "Create a synthetic telematics unit", UNIT, {"serialNumber": "TCU-SYNTH-0001", "hardwareModel": "NX-5G", "firmwareVersion": "3.4.1"}),
        Operation("PUT", "/v1/telematics-units/{unit_id}/firmware", "updateFirmwareInventory", "Update installed firmware inventory", {**UNIT, "unitId": "{unit_id}", "firmwareVersion": "3.5.0", "sourceVersion": 2}, {"firmwareVersion": "3.5.0"}),
        Operation("PUT", "/v1/telematics-units/{unit_id}/lifecycle-status", "setTelematicsUnitLifecycleStatus", "Set telematics unit lifecycle status", {**UNIT, "unitId": "{unit_id}", "lifecycleStatus": "suspended", "sourceVersion": 2}, {"status": "suspended"}),
        Operation("PUT", "/v1/telematics-units/{unit_id}/remote-command-eligibility", "setRemoteCommandEligibility", "Set remote-command eligibility", {**UNIT, "unitId": "{unit_id}", "sourceVersion": 2}, {"eligibility": "approval_required"}),
        Operation("PUT", "/v1/telematics-units/{unit_id}/capabilities", "replaceTelematicsUnitCapabilities", "Replace unit capabilities", {"unitId": "{unit_id}", "capabilities": ["diagnostics", "location"], "sourceVersion": 2}, {"capabilities": ["diagnostics", "location"]}),
    ),
)

