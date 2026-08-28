from fleetops_runtime import Operation, Parameter, ServiceContract


PROVIDER = {
    "providerId": "sp_demo_001",
    "providerName": "Synthetic Service Network East",
    "lifecycleStatus": "active",
    "averageResponseMinutes": 45,
    "dailyCapacity": 20,
    "regions": ["us-east"],
    "capabilities": ["battery", "diagnostics"],
    "sourceVersion": 1,
}

CONTRACT = ServiceContract(
    slug="service-provider-master",
    title="Service Provider Master Service",
    description="Authoritative synthetic provider directory, coverage, capabilities, and capacity.",
    operations=(
        Operation(
            method="GET",
            path="/v1/service-providers/{provider_id}",
            operation_id="getServiceProvider",
            summary="Get a service provider",
            response={**PROVIDER, "providerId": "{provider_id}"},
        ),
        Operation(
            method="GET",
            path="/v1/service-providers",
            operation_id="listServiceProviders",
            summary="List matching service providers",
            response={"items": [PROVIDER], "nextCursor": ""},
            parameters=(
                Parameter("region"),
                Parameter("capability"),
                Parameter("cursor"),
                Parameter("limit", schema_type="integer"),
            ),
        ),
        Operation(
            method="POST",
            path="/v1/service-providers",
            operation_id="createServiceProvider",
            summary="Create a synthetic service provider",
            response=PROVIDER,
            request={
                "providerName": "Synthetic Service Network East",
                "regions": ["us-east"],
                "capabilities": ["battery", "diagnostics"],
            },
        ),
        Operation(
            method="PATCH",
            path="/v1/service-providers/{provider_id}",
            operation_id="updateServiceProvider",
            summary="Update provider-owned fields",
            response={**PROVIDER, "providerId": "{provider_id}", "sourceVersion": 2},
            request={"dailyCapacity": 25},
        ),
        Operation(
            method="PUT",
            path="/v1/service-providers/{provider_id}/status",
            operation_id="setServiceProviderStatus",
            summary="Set provider lifecycle status",
            response={
                **PROVIDER,
                "providerId": "{provider_id}",
                "lifecycleStatus": "at_capacity",
                "sourceVersion": 2,
            },
            request={"status": "at_capacity"},
        ),
        Operation(
            method="PUT",
            path="/v1/service-providers/{provider_id}/coverage",
            operation_id="replaceServiceProviderCoverage",
            summary="Replace provider coverage and capabilities",
            response={
                "providerId": "{provider_id}",
                "regions": ["us-east"],
                "capabilities": ["battery", "diagnostics"],
                "sourceVersion": 2,
            },
            request={
                "regions": ["us-east"],
                "capabilities": ["battery", "diagnostics"],
            },
        ),
    ),
)
