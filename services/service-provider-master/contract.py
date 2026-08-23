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
        Operation("GET", "/v1/service-providers/{provider_id}", "getServiceProvider", "Get a service provider", {**PROVIDER, "providerId": "{provider_id}"}),
        Operation("GET", "/v1/service-providers", "listServiceProviders", "List matching service providers", {"items": [PROVIDER], "nextCursor": ""}, parameters=(Parameter("region"), Parameter("capability"), Parameter("cursor"), Parameter("limit", schema_type="integer"))),
        Operation("POST", "/v1/service-providers", "createServiceProvider", "Create a synthetic service provider", PROVIDER, {"providerName": "Synthetic Service Network East", "regions": ["us-east"], "capabilities": ["battery", "diagnostics"]}),
        Operation("PATCH", "/v1/service-providers/{provider_id}", "updateServiceProvider", "Update provider-owned fields", {**PROVIDER, "providerId": "{provider_id}", "sourceVersion": 2}, {"dailyCapacity": 25}),
        Operation("PUT", "/v1/service-providers/{provider_id}/status", "setServiceProviderStatus", "Set provider lifecycle status", {**PROVIDER, "providerId": "{provider_id}", "lifecycleStatus": "at_capacity", "sourceVersion": 2}, {"status": "at_capacity"}),
        Operation("PUT", "/v1/service-providers/{provider_id}/coverage", "replaceServiceProviderCoverage", "Replace provider coverage and capabilities", {"providerId": "{provider_id}", "regions": ["us-east"], "capabilities": ["battery", "diagnostics"], "sourceVersion": 2}, {"regions": ["us-east"], "capabilities": ["battery", "diagnostics"]}),
    ),
)

