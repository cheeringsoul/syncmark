# Bodhi DSL — Code + DSL Co-generation Rules

## CRITICAL: DSL-First Workflow — ALWAYS Design Before Coding

**This is the single most important rule.** When the user asks you to implement a new feature, API endpoint, or event-driven workflow — whether via `/bodhi design` or a direct request — you MUST produce the YAML skeleton FIRST and get user confirmation BEFORE writing any source code.

### How to detect "new feature" requests

If the user's message describes any of the following, it is a new feature and triggers the DSL-First workflow:
- A new API endpoint, RPC method, or WebSocket handler
- A new event being published or consumed
- A new database table or entity
- A new cross-service integration
- A new business flow (e.g., "after user places an order, deduct inventory, hold payment, emit event")

If the user explicitly uses `/bodhi design`, follow that command's rules. If the user describes a feature directly without using the command, you MUST still execute the same design-first workflow automatically.

### DSL-First steps

1. **Analyze** — identify entry points, data reads/writes, cross-service calls, events, error scenarios, state transitions. Present this analysis to the user for confirmation
2. **Design the flow** — create/update `.bodhi/flows/<name>.yaml` with entry point, steps, entities, events. For cross-service calls, mark steps with `remote`, `protocol`, `api`, `flow_ref`
3. **Define entities** — create/update `.bodhi/entities/<table>.yaml` for any new tables
4. **Define events** — create/update `.bodhi/events/<name>.yaml` for any new events
5. **Define channels** (if bidirectional protocol) — create/update `.bodhi/channels/<name>.yaml`
6. **Confirm** — present the YAML skeleton to the user and ask: "YAML skeleton is ready. Should I proceed to implement the code?" Do NOT proceed without confirmation
7. **Implement** — write each method with inline tags + code together (see Co-generation below)
8. **Update service manifest** — if you added/changed APIs, events, or dependencies, update `.bodhi/services/<name>.yaml`
9. **Validate** — the post-edit hook will verify completeness automatically

**When to use DSL-first:** new features, new API endpoints, new event workflows, new service integrations.
**When to skip (just co-generate):** bug fixes, refactoring without behavior change, adding a field, performance optimization.

---

## MANDATORY: Every Public Method MUST Have @bodhi.intent

**This is a hard rule, not a suggestion.** When you write or modify any public/exported function or method, you MUST add `@bodhi.intent` in its doc comment BEFORE moving on to the next task. Do NOT batch this — tag each method immediately as you write it.

**Exceptions (no tags needed):**
- Simple getters / setters / toString / hashCode / equals
- Constructors
- Pure utility functions (string formatting, logging wrappers)
- Test code
- Configuration / startup boilerplate (e.g., `main()`, `@Configuration` classes)

**If you forget:** A post-edit hook will block you and list the methods missing tags. Fix them before continuing.

---

## Self-Check: 6 Questions Before Moving to Next Method

After writing each method, answer these questions. If the answer is "yes" but the tag is missing, add it NOW:

1. Does this method read external input (request, DB, cache)? → Need `@bodhi.reads`
2. Does this method write to storage (DB, cache, file)? → Need `@bodhi.writes`
3. Does this method call another service or key internal method? → Need `@bodhi.calls`
4. Does this method publish an event (MQ, EventBus, WebSocket)? → Need `@bodhi.emits`
5. Does this method consume an event? → Need `@bodhi.consumes`
6. Can this method fail in a business-meaningful way? → Need `@bodhi.on_fail`

---

## What Complete DSL Looks Like (vs Incomplete)

❌ **WRONG — intent only, everything else missing:**

```java
/**
 * @bodhi.intent Create order
 */
public OrderResponse create(CreateOrderRequest req) {
    Order order = new Order(req.getUserId(), req.getItems());
    orderRepository.save(order);
    inventoryService.deduct(order.getItems());
    paymentService.hold(order.getTotalAmount());
    kafkaTemplate.send("order-events", new OrderCreatedEvent(order));
    return new OrderResponse(order.getId());
}
```

This method reads request body, writes to DB, calls two services, emits an event, and can fail — but only has `@bodhi.intent`. The deriver gets almost nothing useful.

✅ **CORRECT — all relevant tags present:**

```java
/**
 * @bodhi.intent Create order, deduct inventory, hold payment, publish event
 * @bodhi.reads request.body(userId, items, address)
 * @bodhi.writes orders(id, userId, totalAmount, status=PENDING) via INSERT
 * @bodhi.calls InventoryService.deduct via grpc:InventoryService/Deduct
 * @bodhi.calls PaymentService.hold via http:POST /api/payments/hold
 * @bodhi.emits order_created(orderId, userId, totalAmount) to kafka:order-events
 * @bodhi.on_fail inventory_insufficient → reject 400
 * @bodhi.on_fail payment_timeout → circuit_breaker(threshold=5, window=60s) → reject 503
 */
public OrderResponse create(CreateOrderRequest req) {
    // implementation...
}
```

---

## Layer 1: Inline Tags

Add `@bodhi.*` tags in the doc comment of each function/method.

### Required Tags

| Tag | When to Add | Description |
|-----|-------------|-------------|
| `@bodhi.intent` | **Every function** | One-line business intent in business language, don't restate the code |
| `@bodhi.reads` | When reading data | What is read: `request.body(fields)`, `table(fields)`, `cache:key(fields)` |
| `@bodhi.writes` | When writing data | What is written: `table(fields) via INSERT/UPDATE/DELETE`, `response(code, fields)` |
| `@bodhi.calls` | When making key calls | Only list business-critical calls. Format: `ClassName.method [via protocol]`. Remote calls must add `via http:POST /path` or `via grpc` |
| `@bodhi.emits` | When publishing events | `event_name(payload_fields) [to destination]` — don't miss MQ/EventBus/WebSocket |
| `@bodhi.consumes` | When consuming events | `event_name(payload_fields) [from source]` — declare what event triggers this function |
| `@bodhi.on_fail` | When handling errors | `condition → action`, chainable: `retry 3 → reject 500`. Supports `circuit_breaker(...)`, `degrade(...)` for microservice resilience |

### Optional Tags (add when applicable)

- `@bodhi.auth required|public|required(role=X)`
- `@bodhi.validate <rule>`
- `@bodhi.implements <InterfaceName>` — on implementation classes, back-link to the interface
- `@bodhi.log.success "<pattern>"`
- `@bodhi.log.error "<pattern>" [severity=level]`
- `@bodhi.metric <name> [threshold]`
- `@bodhi.idempotent key=<fields>`
- `@bodhi.ratelimit <rate> per <scope>`

### Language Adaptation

**Java/Kotlin/TypeScript**: Place in `/** */` JSDoc/Javadoc
**Python**: Place in `"""` docstring
**Go**: Place in `//` line comments

---

## Layer 2: System Files

Layer 2 files live in `.bodhi/` and fall into two categories:

### Written alongside code (manual)

These are created/updated when you write the corresponding code:

- `.bodhi/bodhi.yaml` — project metadata, including `distributed` block for microservices (create once on init)
- `.bodhi/entities/<table>.yaml` — database table schemas (when you add/modify ORM models or DDL)
- `.bodhi/concepts/glossary.yaml` — business term definitions (when domain terms appear in code)
- `.bodhi/channels/<name>.yaml` — bidirectional channel definitions for WebSocket/Socket/SSE (when you add a bidirectional endpoint)
- `.bodhi/topology/<name>.yaml` — cross-service event chain definitions (when events cross service boundaries)

### Derived from inline tags (automatic via `/bodhi`)

These are NOT maintained during coding. Run `/bodhi flows` or `/bodhi scan` to generate them from inline tags:

- `.bodhi/flows/<name>.yaml` — derived from `@bodhi.calls` chains starting at entry points
- `.bodhi/states/<name>.yaml` — derived from `@bodhi.writes table(status)` + transition logic
- `.bodhi/events/<name>.yaml` — derived from `@bodhi.emits` + `@bodhi.consumes` pairs
- `.bodhi/services/<name>.yaml` — derived from `@bodhi.calls ... via http/grpc` across services

**Do NOT manually create or update flows, states, events, or services YAML files while writing code.** They will be regenerated from inline tags and will overwrite manual edits.

### Entity File — `.bodhi/entities/<table>.yaml`

When you create a database table / ORM model:

```yaml
table: orders
description: Core orders table
database: mongodb          # mysql | postgresql | mongodb | redis
datasource: order-db       # Optional: datasource identifier, maps to connection/bean name in code

fields:
  - name: id
    type: bigint
    description: Order primary key
    primary_key: true
  - name: status
    type: int
    description: Order status
    state_machine: order_lifecycle
    enum:
      0: INIT
      1: PAID
      3: SHIPPED
      4: COMPLETED
      5: CANCELLED
  - name: phone
    type: string
    description: User contact phone
    sensitive: true

indexes:
  - name: idx_user_status
    fields: [ user_id, status ]
    description: User order list query

relations:
  - target: order_items
    type: one_to_many
    join: orders.id = order_items.order_id
  - target: users
    type: many_to_one
    join: orders.user_id = users.id
```

**Multiple datasources:** When a service connects to multiple databases (e.g., MySQL for business data, Redis for cache, ES for search), use `datasource` to identify which connection each entity belongs to. The value should match the connection name in code (e.g., Spring bean name, Go config key). If table names collide across datasources, disambiguate in inline tags with a prefix: `@bodhi.reads mysql:orders(...)` vs `@bodhi.reads es:orders(...)`.

### Project Metadata — `.bodhi/bodhi.yaml`

Create once on project initialization:

```yaml
version: "0.1.1"
project:
  name: "your-project-name"
  description: "Project description"
  languages: [java]
  frameworks: [spring-boot, mybatis]

# Optional: runtime config for log diagnosis
runtime:
  logs:
    - name: app-log
      type: file                   # file, elasticsearch, loki, cloudwatch
      path: logs/app.log
      format: json                 # json, text, logfmt
      timestamp_field: timestamp
      message_field: message
  time_window: 30s
  default_trace_field: traceId
```

---

## Distributed / Multi-Service Projects

> Skip this section if your project is a monolith.

### Service Identity — `.bodhi/bodhi.yaml`

Every service repo MUST declare its identity in `bodhi.yaml`:

```yaml
version: "0.1.1"
project:
  name: "order-service"
  description: "Core order service"
  languages: [java]
  frameworks: [spring-boot, mybatis, kafka]

distributed:
  system: "ecommerce-platform"           # System name — all services in the same system share this
  service: "order-service"               # This service's name (must match registry entry)
  registry: "git@github.com:org/bodhi-registry.git"  # Central registry repo
```

The `distributed` block tells tooling: this repo is part of a larger system, and cross-service references should resolve against the registry.

### Multi-Protocol API Declaration — `.bodhi/services/<name>.yaml`

Services don't always expose HTTP. Declare ALL protocols this service exposes using the `protocol` field:

```yaml
name: order-service
description: Core order service
tech_stack: [spring-boot, mysql, kafka]

apis:
  # HTTP / REST
  - protocol: http
    method: POST
    path: /api/orders
    flow: create_order
    description: Create order

  # gRPC
  - protocol: grpc
    service: OrderService
    method: CreateOrder
    flow: create_order
    description: Create order via gRPC

  # WebSocket — reference a channel definition
  - protocol: websocket
    channel: order_status_ws
    description: Real-time order status push

  # JSON-RPC
  - protocol: jsonrpc
    transport: http                       # http | websocket | tcp
    method: order.create
    flow: create_order

  # Raw TCP / Socket
  - protocol: tcp
    port: 9090
    codec: protobuf                       # protobuf | msgpack | json | custom
    commands:
      - name: CREATE_ORDER
        flow: create_order

depends_on:
  - service: payment-service
    protocol: grpc
    apis:
      - PaymentService/HoldPayment
    resilience:
      timeout: 3s
      retry: 2
      circuit_breaker: threshold=5, window=60s

  - service: kafka
    type: mq
    topics:
      - order-events
```

**Rules:**
- `protocol` is required on every API entry — never assume HTTP
- For gRPC: use `service` + `method` (matching `.proto` definitions)
- For WebSocket: reference a `channel` definition (see below)
- For JSON-RPC: specify `transport` to clarify how the RPC is carried
- For TCP/Socket: specify `port` and `codec`
- `depends_on[].protocol` must match how you actually call the upstream

### Channels — `.bodhi/channels/<name>.yaml`

For bidirectional protocols (WebSocket, raw Socket, SSE with command channel), define a channel:

```yaml
name: order_status_ws
protocol: websocket
path: /ws/orders
description: Real-time order status updates

inbound_events:                           # client → server
  - name: subscribe
    description: Client subscribes to order status updates
    schema:
      - field: orderId
        type: string
    triggers_flow: subscribe_order_updates

outbound_events:                          # server → client
  - name: order_status_changed
    description: Push order status change to client
    schema:
      - field: orderId
        type: string
      - field: fromStatus
        type: string
      - field: toStatus
        type: string
    triggered_by:
      - event: order_status_updated
        from: kafka:order-events
```

**Rules:**
- One channel per `.yaml` file
- `inbound_events` = messages the server receives from the client
- `outbound_events` = messages the server pushes to the client
- `triggers_flow` links inbound events to internal processing flows
- `triggered_by` links outbound events to internal events that cause the push

**Inline tags for channel handlers:**

```java
/**
 * @bodhi.intent Handle WebSocket subscription for order status
 * @bodhi.consumes ws:subscribe(orderId) from channel:order_status_ws
 * @bodhi.reads orders(id, status) WHERE id = orderId
 */
public void onSubscribe(WebSocketSession session, SubscribeMessage msg) { ... }

/**
 * @bodhi.intent Push order status change to subscribed WebSocket clients
 * @bodhi.consumes order_status_updated(orderId, newStatus) from kafka:order-events
 * @bodhi.emits ws:order_status_changed(orderId, fromStatus, toStatus) to channel:order_status_ws
 */
public void pushStatusChange(OrderStatusUpdatedEvent event) { ... }
```

Use `ws:<event_name>` prefix and `channel:<channel_name>` destination for WebSocket events to distinguish them from MQ events.

### Cross-Service Flows

When a flow crosses service boundaries, mark the remote step explicitly:

```yaml
# .bodhi/flows/create_order.yaml
steps:
  - fn: OrderController.create
    intent: Receive request, orchestrate order creation
    reads:
      - request.body(userId, items, address)
    calls:
      - InventoryService.deduct
      - PaymentService.hold

  - fn: InventoryService.deduct
    remote: inventory-service              # ← this step executes in another service
    protocol: grpc
    api: InventoryService/DeductStock
    flow_ref: inventory-service:deduct_stock  # ← pointer to the remote flow
    intent: Deduct product inventory
    on_fail:
      - inventory_insufficient → reject 400

  - fn: PaymentService.hold
    remote: payment-service
    protocol: http
    api: POST /api/payments/hold
    flow_ref: payment-service:hold_payment
    intent: Hold payment amount
    on_fail:
      - payment_timeout → circuit_breaker(threshold=5, window=60s) → reject 503
```

**Rules:**
- `remote: <service-name>` — marks the step as a cross-service call
- `protocol` + `api` — how this service actually calls the remote
- `flow_ref: <service>:<flow>` — pointer to the detailed flow in the remote service's `.bodhi/flows/`
- Local steps have NO `remote` field — absence of `remote` means "runs in this process"

**Corresponding inline tags:**

```java
/**
 * @bodhi.intent Deduct inventory for order items
 * @bodhi.calls InventoryService.deduct via grpc:InventoryService/DeductStock
 * @bodhi.on_fail inventory_insufficient → reject 400
 */
private void deductInventory(List<OrderItem> items) {
    inventoryClient.deduct(items);  // gRPC call to inventory-service
}
```

The `via grpc:InventoryService/DeductStock` in the inline tag is the source from which the flow's `remote` + `protocol` + `api` are derived.

### Event Topology — `.bodhi/topology/<name>.yaml`

Describes cross-service event chains — how events flow across the entire system:

```yaml
name: order_fulfillment
description: End-to-end event chain from order creation to delivery

chains:
  - event: order_created
    channel: kafka:order-events
    producer: order-service
    consumers:
      - service: payment-service
        fn: PaymentHandler.onOrderCreated
        action: Initiate payment collection
        emits: payment_completed

      - service: notification-service
        fn: NotificationHandler.onOrderCreated
        action: Send order confirmation email

  - event: payment_completed
    channel: kafka:payment-events
    producer: payment-service
    consumers:
      - service: order-service
        fn: OrderHandler.onPaymentCompleted
        action: Update order status to PAID
        emits: order_paid
```

**Rules:**
- One topology file per major business flow (order fulfillment, user registration, etc.)
- Each chain entry describes one event and ALL its consumers across all services
- `emits` on a consumer shows what downstream event it triggers — this is how chains link together
- When you add a new `@bodhi.emits` or `@bodhi.consumes` that crosses service boundaries, check if a topology file needs updating

### Registry Sync Protocol

The **bodhi-registry** is a standalone repo that aggregates `.bodhi/` metadata from all services:

```
bodhi-registry/
├── bodhi.yaml                    # System-level metadata
├── services/
│   ├── order-service.yaml        # Copied from order-service repo
│   ├── payment-service.yaml
│   └── inventory-service.yaml
├── events/
│   ├── order_created.yaml        # Merged: producers from order-service, consumers from all
│   └── payment_completed.yaml
├── topology/
│   └── order_fulfillment.yaml    # Cross-service event chain
└── channels/
    └── order_status_ws.yaml      # Copied from the service that owns it
```

**When to flag registry sync:**

Add `# REGISTRY_SYNC_NEEDED` as the first line of any `.bodhi/` file when you:
- Add, remove, or change an API endpoint (any protocol)
- Add, remove, or change an event (producer or consumer)
- Add or change a service dependency (`depends_on`)
- Add or change a channel definition
- Change the service's protocol or port

**Do NOT flag registry sync for:**
- Internal flow changes that don't affect the service boundary
- Entity schema changes (internal to the service)
- Adding inline tags to existing methods

### Distributed Self-Check: Extra Questions

In addition to the 6 standard questions, ask these for every method in a distributed project:

7. Does this method call a remote service? → `@bodhi.calls` MUST have `via <protocol>` — never omit the protocol for remote calls
8. Does this method expose an endpoint that other services call? → Ensure it's declared in `.bodhi/services/<name>.yaml` under `apis`
9. Does this event cross service boundaries? → Check that `.bodhi/topology/*.yaml` reflects the producer/consumer pair
10. Is this a WebSocket/Socket handler? → Use `ws:<event>` prefix and reference the channel definition

---

## AI-Friendly Code Conventions

The core principle: **code should be statically traceable from source text alone.** If AI cannot determine the execution path, data flow, or call target by reading the source, the code is not AI-friendly. `@bodhi.*` tags are a remediation for unavoidable indirection — not a substitute for writing traceable code in the first place.

### Pre-Implementation: Identify Design Pattern Opportunities

**Before writing code**, scan the requirements for these signals and apply the corresponding pattern. Do not over-engineer — only use a pattern when the scenario clearly matches. If none match, write plain functions.

| Signal in Requirements | Pattern | When to Use |
|------------------------|---------|-------------|
| Complex object with many optional fields | **Builder** | 4+ optional parameters, or construction has steps/validation |
| Multiple steps that follow a fixed sequence, but individual steps vary | **Template Method** | Processing pipelines, lifecycle hooks, report generation |
| Need a clean entry point that orchestrates multiple subsystems | **Facade** | Simplifying a complex internal API for external callers |
| Object behaves differently based on its state, with defined transitions | **State** | Order lifecycle, connection states, approval workflows |
| A request passes through a series of checks/transformations in order | **Chain of Responsibility** | Validation chains, middleware pipelines, approval chains |
| Wrap an incompatible interface to match what the caller expects | **Adapter** | Integrating third-party SDKs, legacy system wrappers |
| Encapsulate an operation as an object (undo, queue, log) | **Command** | Task queues, undo/redo, operation logging |
| Add behavior to an object without changing its class (2-3 layers max) | **Decorator** | Logging, caching, retry wrappers around a core function |
| Multiple algorithms/strategies selected by explicit condition | **Strategy (explicit routing)** | Payment channels, notification methods, pricing rules — **must use `switch`/`if` at call site** |
| One event triggers reactions in multiple independent components | **Observer (with `@bodhi` tags)** | Domain events — **must add `@bodhi.emits`/`@bodhi.consumes`** |

**Rules:**
- Only apply a pattern when the code **already has** the complexity that the pattern addresses — never "in case we need it later"
- Prefer the simplest pattern that fits. If a plain `if`/`switch` is clear enough, skip the pattern
- Strategy and Observer must follow the traceability rules below (explicit routing, `@bodhi` tags)
- Avoid: Visitor (double dispatch), dynamic Proxy, Mediator with reflection — these break static traceability

**Self-check before implementing:** "Does this code have repeated structure, complex branching, state transitions, or multi-step orchestration?" If yes, pick the matching pattern from the table above. If no, write plain functions.

### Prefer Functions + Modules Over Classes + Inheritance

Write code as **direct function calls** with **explicit data flow**. Avoid introducing indirection layers unless the problem genuinely requires runtime polymorphism.

**General rules (all languages):**

- **Direct calls over dispatch**: `create_order(req)` is traceable; `service.handle(req)` dispatched through an interface with 3 implementations is not
- **Data structures over objects with behavior**: use records / dataclasses / structs / plain objects for data; keep behavior in standalone functions
- **Explicit routing over polymorphism**: when multiple implementations exist, use `if`/`switch`/`match` at the call site — every branch visible in source
- **Explicit dependencies over injection**: pass dependencies as function parameters or struct fields; avoid container-managed auto-wiring where possible
- **Explicit side effects over hidden magic**: no AOP, no implicit interceptors, no monkey-patching for business logic

### Language-Specific Rules

**Java:**
- Use `record` for data, `static` methods for pure logic; avoid JavaBeans and stateful `@Component` utility classes
- Avoid `@Transactional` (AOP-invisible); prefer explicit `TransactionTemplate.execute()`
- Avoid Spring Data magic method-name queries; write explicit SQL (MyBatis, JdbcTemplate)
- Avoid Lombok `@Data`/`@Builder` (generated methods invisible in source); prefer `record`
- Never use reflection (`Method.invoke`, `BeanUtils.copyProperties`) in business logic
- Minimize auto-configuration; explicitly configure what you can

**Go:**
- Functions + struct methods (Go's natural style is already AI-friendly)
- Avoid `init()` for registering global state — pass dependencies explicitly
- Avoid `interface{}` / `any` — use concrete types or small interfaces defined at the consumer
- Do not put business data in `context.Value` — it creates invisible data channels
- Commit `go:generate` output to the repo so AI can read it

**Python:**
- Prefer top-level functions + modules over classes; only use classes when you need state
- Use `dataclass` / `TypedDict` — never pass untyped `dict` as business data
- Always add type annotations on function signatures
- Avoid `__getattr__` / metaclass / `importlib.import_module` for business logic
- Avoid deep decorator stacks that obscure the original function signature
- Django signals, Celery `@task`, SQLAlchemy lazy loading all break traceability — tag with `@bodhi.emits`/`@bodhi.consumes`/`@bodhi.calls` when using them

**Kotlin:**
- Use `sealed class` / `sealed interface` for polymorphism — all subtypes are enumerable at compile time
- Use `data class` for data; top-level functions over `companion object` statics
- Use `when` expressions for routing (compiler enforces exhaustive matching)
- Avoid extension functions for core business logic — definitions are scattered and hard to trace

**TypeScript / Node.js:**
- `export function` + modules over class hierarchies
- Explicit types (`interface` / `type`) — never `any` in business code
- Direct `import` — never dynamic `require()` / `import()` with string variables
- Avoid NestJS-style decorator + DI when simpler frameworks (Fastify, Hono) suffice
- Never use `Proxy` objects for business logic

**Rust:**
- `enum` + `match` for dispatch (compiler-enforced exhaustive matching) — prefer over `dyn Trait`
- Commit `cargo expand` output or document complex proc macros
- Use `Result<T, E>` — avoid `unwrap()` / `panic!` in business logic

**C#:**
- Use `record` for data; top-level statements / static methods for stateless logic
- Minimal API (explicit route registration) over Controller auto-discovery
- Explicit DI registration over assembly scanning
- Avoid `dynamic` type; prefer `switch` expression + pattern matching over virtual/override chains

**C:**
- Functions + structs (C's natural style is inherently AI-friendly)
- Avoid function pointers for business-logic dispatch — use explicit `if`/`switch` on a type tag instead
- Keep macros (`#define`) simple; avoid multi-line macros that hide control flow or generate function definitions
- Avoid `void *` for business data — use concrete struct types so fields are visible and grepable
- Header files (`.h`) are your module interface — keep them minimal and treat `#include` as your explicit dependency graph

**C++:**
- Use `struct` / plain classes with public fields for data; avoid deep class hierarchies
- Prefer free functions and namespaces over class methods — `namespace order { Response create(Request req); }` is more traceable than `OrderService::create()`
- Prefer `std::variant` + `std::visit` over virtual dispatch — all types enumerable at compile time, exhaustive matching
- Avoid template metaprogramming for business logic — heavy templates produce unreadable error messages and invisible code paths; use concrete types when possible
- Avoid CRTP (Curiously Recurring Template Pattern), multiple inheritance, and mixin-style base classes — they create hidden behavior inheritance
- Avoid operator overloading for business semantics — `order + item` is not traceable; `order.addItem(item)` is
- Avoid `dynamic_cast` / RTTI for dispatch — it means your type hierarchy is doing too much; use `std::variant` or explicit tag-based switching
- Keep macros minimal (same as C); prefer `constexpr` functions and `inline` over `#define`

### Refactoring Rules

Refactoring must not break static traceability. The goal is **simpler, more modular code** — not more abstract code.

**Core principle: extract into modules and functions, not into class hierarchies.**

When refactoring, ask: "Can AI still follow every call path by reading the source?" If the answer is no, the refactoring is wrong.

**DO — these preserve or improve traceability:**

- **Extract function**: pull a block of code into a named function in the same module — call site becomes a direct, grepable call
- **Extract module**: move related functions into a new file/module — import graph stays explicit
- **Inline indirection**: if a class/interface exists only to "abstract" a single implementation, collapse it into direct function calls
- **Replace inheritance with composition**: turn a base class + overrides into a struct/dataclass holding function references or explicit delegates
- **Replace generic with concrete**: if a type parameter `T` is always used as one type, remove the generic — concrete types are easier to trace
- **Flatten decorator/wrapper stacks**: if 3 decorators wrap a function, consider merging them into one or inlining the logic
- **Make implicit explicit**: replace framework magic (auto-wiring, auto-discovery, AOP) with direct calls when possible

**DO NOT — these reduce traceability:**

- **Extract interface for a single implementation**: adds an indirection layer with zero benefit — keep the concrete class
- **Introduce Strategy/Factory/Observer pattern "for flexibility"**: only use patterns when there are already multiple concrete branches in the code today, not "in case we need it later"
- **Replace `if`/`switch` with polymorphic dispatch**: explicit routing is more traceable than vtable dispatch — keep the branches visible
- **Add DI container where direct construction works**: `new OrderService(repo, client)` is more traceable than `@Inject OrderService`
- **Create abstract base class to "share code"**: prefer standalone utility functions that both callers import — no hidden inherited state
- **Wrap simple calls in "service" classes**: `OrderService.create()` that just calls `order_repo.save()` adds noise — call the repo directly if that's all it does

**Refactoring decision flow:**

1. Is there duplicated logic? → Extract into a **function** (not a base class)
2. Is a file too large? → Split into **modules** by business domain (not by layer/pattern)
3. Is a function too long? → Extract **named sub-functions** in the same module
4. Are there too many parameters? → Group into a **data structure** (record/dataclass)
5. Is there an interface with one implementation? → **Inline it** — remove the interface
6. Is there a class with no state? → Convert to **module-level functions**

### No Method Overloading

Do not use method overloading. Bodhi DSL uses `ClassName.methodName` as the unique identifier — overloaded methods cause ambiguity.

- Bad: `create(Order)`, `create(BatchOrder)`
- Good: `createOrder(Order)`, `createBatchOrder(BatchOrder)`

`bodhi validate` detects this automatically (`method-overloading` rule) and warns when two tagged methods share the same `ClassName.methodName`.

### Structure Stability

AI's ability to work on a codebase degrades quickly when structural identifiers churn. The names and locations that appear in `@bodhi.*` tags, flow YAML, and call chains act as the project's shared vocabulary — every rename is a cache invalidation for every AI session that has seen the code.

**Rules:**

- **Rename atomically**: when you rename a public function, class, or module, update all `@bodhi.calls` references, `.bodhi/flows/*.yaml` `fn:` fields, and `.bodhi/events/*.yaml` producer/consumer entries **in the same commit**. `bodhi check` will catch the dangling references, but only if you run it before committing.
- **Prefer additive changes**: when the change is not behavioral (e.g. you want a clearer name), add the new name and deprecate the old one instead of renaming in place. The old identifier remains a valid grep target until all callers migrate.
- **Stable directory layout**: do not reorganize `src/` directories just because a new pattern looks cleaner. Directory paths show up in `file_path` fields throughout the knowledge graph and in human memory. Move files only when the business domain actually changed.
- **API stability over API elegance**: once an endpoint, event name, or entity field appears in `.bodhi/services/*.yaml` or `.bodhi/events/*.yaml`, treat it as published. Renaming it for aesthetic reasons invalidates downstream consumers' mental model and their tags. Add a new one and deprecate the old instead.
- **Churn budget**: if a refactor would rename more than ~5 public identifiers at once, stop and ask the user whether the churn is justified. Large sweeps are usually a sign that the refactor is conflating a behavioral change with a naming cleanup — separate them into two commits.

### Keep Call Chains Traceable

The goal: anyone (human or AI) reading the code can follow the full flow from entry point to every downstream call without guessing which implementation runs.

**Rule: Do not hide business-critical branching behind interface polymorphism.**

If a method dispatches to different implementations based on runtime conditions (strategy pattern, multi-tenant adapters, payment channels, etc.), make the routing explicit in the caller:

❌ Bad — AI sees `payService.pay()` but can't tell which implementation runs:

```java
// payService is injected as PayService interface — 3 implementations exist
public OrderResponse create(CreateOrderRequest req) {
    payService.pay(req.getPayment());
}
```

✅ Good — routing logic is visible, each branch is a concrete call:

```java
/**
 * @bodhi.calls WechatPayService.pay via http:POST /v3/pay/transactions
 * @bodhi.calls AlipayPayService.pay via http:POST /gateway.do
 */
public OrderResponse create(CreateOrderRequest req) {
    switch (req.getChannel()) {
        case WECHAT -> wechatPayService.pay(req.getPayment());
        case ALIPAY -> alipayPayService.pay(req.getPayment());
    }
}
```

**When interface polymorphism is acceptable:**
- Repository / DAO interfaces (Spring Data, MyBatis) — only one implementation, framework-generated
- Pure infrastructure (logging, metrics, caching) — not part of business flow
- Single implementation behind an interface for testability

For these cases:
- Place `@bodhi.*` tags on the interface method
- Add `@bodhi.implements` on the implementation class to create a back-link
- Name implementation classes as `XxxImpl` or `DefaultXxx` (consistent naming convention)

```java
// OrderService.java (interface — tags go here)
/**
 * @bodhi.intent Create order, deduct inventory, publish event
 * @bodhi.reads request.body(userId, items, address)
 * @bodhi.writes orders(id, userId, totalAmount, status=PENDING) via INSERT
 * @bodhi.calls InventoryService.deduct
 */
OrderResponse create(CreateOrderRequest req);

// OrderServiceImpl.java (implementation — back-link only)
/**
 * @bodhi.implements OrderService
 */
@Service
public class OrderServiceImpl implements OrderService {
    @Override
    public OrderResponse create(CreateOrderRequest req) {
        // actual logic here, no @bodhi.* tags needed on methods
    }
}
```

This gives bidirectional traceability: interface → Impl via naming convention, Impl → interface via `@bodhi.implements`.

**In short: if there's only one implementation, interface is fine — tag the interface, back-link the Impl. If there are multiple, make the routing explicit.**

### Make Event Chains Explicit

Framework-managed event dispatch breaks static call chains. Always use `@bodhi.emits` and `@bodhi.consumes`:

```java
// Publisher
/** @bodhi.emits order_created(orderId) to internal */
public void create(...) {
    eventPublisher.publishEvent(new OrderCreatedEvent(...));
}

// Consumer
/** @bodhi.consumes order_created(orderId) from internal */
@EventListener
public void onOrderCreated(OrderCreatedEvent event) { ... }
```

Use `to internal` / `from internal` for in-process event buses, and `to kafka:<topic>` / `from kafka:<topic>` for message queues.

---

## Decision Tree

1. Did you write or modify a function? → Add Layer 1 inline tags (`@bodhi.intent` + relevant tags)
2. Did you create or modify a database table / ORM model? → Update `.bodhi/entities/`
3. Did you introduce a new business term? → Update `.bodhi/concepts/`

**What does NOT need DSL:**
- Pure utility functions (format, log wrapper, string utils)
- Simple getters/setters
- Test code
- Configuration / startup classes
