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
        Operation(
            method="GET",
            path="/v1/telematics-units/{unit_id}",
            operation_id="getTelematicsUnit",
            summary="Get a telematics unit",
            response={**UNIT, "unitId": "{unit_id}"},
        ),
        Operation(
            method="POST",
            path="/v1/telematics-units",
            operation_id="createTelematicsUnit",
            summary="Create a synthetic telematics unit",
            response=UNIT,
            request={
                "serialNumber": "TCU-SYNTH-0001",
                "hardwareModel": "NX-5G",
                "firmwareVersion": "3.4.1",
            },
        ),
        Operation(
            method="PUT",
            path="/v1/telematics-units/{unit_id}/firmware",
            operation_id="updateFirmwareInventory",
            summary="Update installed firmware inventory",
            response={
                **UNIT,
                "unitId": "{unit_id}",
                "firmwareVersion": "3.5.0",
                "sourceVersion": 2,
            },
            request={"firmwareVersion": "3.5.0"},
        ),
        Operation(
            method="PUT",
            path="/v1/telematics-units/{unit_id}/lifecycle-status",
            operation_id="setTelematicsUnitLifecycleStatus",
            summary="Set telematics unit lifecycle status",
            response={
                **UNIT,
                "unitId": "{unit_id}",
                "lifecycleStatus": "suspended",
                "sourceVersion": 2,
            },
            request={"status": "suspended"},
        ),
        Operation(
            method="PUT",
            path="/v1/telematics-units/{unit_id}/remote-command-eligibility",
            operation_id="setRemoteCommandEligibility",
            summary="Set remote-command eligibility",
            response={**UNIT, "unitId": "{unit_id}", "sourceVersion": 2},
            request={"eligibility": "approval_required"},
        ),
        Operation(
            method="PUT",
            path="/v1/telematics-units/{unit_id}/capabilities",
            operation_id="replaceTelematicsUnitCapabilities",
            summary="Replace unit capabilities",
            response={
                "unitId": "{unit_id}",
                "capabilities": ["diagnostics", "location"],
                "sourceVersion": 2,
            },
            request={"capabilities": ["diagnostics", "location"]},
        ),
    ),
)
