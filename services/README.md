# Application Service Contracts

Each child folder is an independently owned application/domain boundary. The `API.md` files contain language-neutral signatures only; they are not runtime implementations, generated clients, transport bindings, or persistence code.

## Contract notation

```text
Operation(request: RequestType, context: RequestContext) -> Result<ResponseType, ServiceError>

type RequestContext = {
  correlationId: string
  actorId: string
}

type PageRequest = { cursor?: string, limit?: integer }
type Page<T> = { items: T[], nextCursor?: string }
type TimeWindow = { from: timestamp, to: timestamp }
type ServiceError = NotFound | InvalidRequest | Conflict | Forbidden | DependencyUnavailable
```

Identifiers are opaque strings issued by the owning service. A signature containing another domain's ID does not create data ownership or a database foreign key.

## Service catalog

| Domain folder | Responsibility |
| --- | --- |
| `vehicle-master` | Vehicle identity and lifecycle |
| `telematics-unit-master` | Telematics device inventory |
| `fleet-master` | Fleet/customer, contract, SLA, region, and contact data |
| `maintenance-history` | Vehicle maintenance records |
| `service-provider-master` | Service-provider directory |
| `vehicle-context-facade` | Read-only composition of vehicle context |
| `telematics-event` | Telemetry events and alerts |
| `digital-twin-context` | Derived operational state and dependencies |
| `policy-playbook` | Policy, playbook, eligibility, and approval rules |
| `incident-search` | Prior-incident retrieval and aggregate patterns |
| `risk-scoring` | Safety, SLA, customer-impact, and priority scoring |
| `case-management` | Operational service cases |
| `notification` | Drafted and delivered notifications |
| `approval` | Human approval workflow |
| `audit-observability` | Agent, policy, tool, recommendation, and decision traces |

## Boundary rules

- Each service owns its contracts and data; no service reads another service's database.
- Cross-domain composition occurs through service calls or event-driven projections.
- Mutating operations require an idempotency key when exposed over a transport.
- Transport-specific HTTP, gRPC, event, and MCP mappings will be designed later.
- Authentication, authorization, validation, pagination, and error payload details remain contract-design work.

