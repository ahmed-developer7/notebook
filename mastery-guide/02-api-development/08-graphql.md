# GraphQL

> [Mastery Guide](../README.md) › [API Development](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | Medium | Phase 8 — Microservices & Messaging | 2026-08-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Schema, queries, mutations, subscriptions](#schema-queries-mutations-subscriptions)
  - [Scalars, and modelling money and time](#scalars-and-modelling-money-and-time)
  - [Nullability comes from your C# types](#nullability-comes-from-your-c-types)
  - [Interfaces, unions, and inline fragments](#interfaces-unions-and-inline-fragments)
  - [Global object identification and the Node interface](#global-object-identification-and-the-node-interface)
  - [Resolvers](#resolvers)
  - [The N+1 problem and DataLoader](#the-n1-problem-and-dataloader)
  - [Mutation payloads and errors as data](#mutation-payloads-and-errors-as-data)
  - [Incremental delivery with @defer and @stream](#incremental-delivery-with-defer-and-stream)
  - [File uploads](#file-uploads)
  - [GraphQL vs REST](#graphql-vs-rest)
  - [Schema evolution (no versioning)](#schema-evolution-no-versioning)
  - [Federation in the .NET stack: Fusion and Composite Schemas](#federation-in-the-net-stack-fusion-and-composite-schemas)
  - [What introspection gives away](#what-introspection-gives-away)
  - [Aliases, batching, and the limits that catch them](#aliases-batching-and-the-limits-that-catch-them)
  - [CSRF once you serve GraphQL over GET](#csrf-once-you-serve-graphql-over-get)
  - [Observability for a single-endpoint API](#observability-for-a-single-endpoint-api)
  - [Testing a GraphQL service](#testing-a-graphql-service)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--n1-takes-down-the-dashboard)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

GraphQL was Facebook's answer to a specific problem: mobile clients with limited bandwidth fetching from REST APIs that always return more (or less) than they need. Instead of "the server decides what to return," GraphQL flips it: "the client asks for exactly the fields it wants, no more no less." A single endpoint, a typed schema, and resolvers that produce the requested shape on demand.

In 2026, GraphQL is dominant in two niches: **Backends-for-Frontends (BFF)** that aggregate multiple downstream services into one shape for a UI, and **public APIs with diverse consumers** (GitHub, Shopify, Linear). It has *not* replaced REST — most service-to-service traffic is still REST or gRPC because the schema-discipline and tooling cost don't pay back internally.

Why interviewers ask: GraphQL knowledge separates engineers who've shipped consumer-facing products (where over-fetching matters) from those who've only built service APIs. Knowing N+1 mitigation and persisted queries is a senior signal.

When NOT to choose GraphQL: simple CRUD APIs, service-to-service traffic, public APIs where caching at the HTTP layer matters, teams without the tooling to manage schema evolution.

## Core concepts

### Schema, queries, mutations, subscriptions

A GraphQL service is defined by a **schema** — a typed contract describing every operation a client can perform.

```graphql
type Query {
  order(id: ID!): Order
  orders(customerId: ID, limit: Int = 50): [Order!]!
}

type Mutation {
  createOrder(input: CreateOrderInput!): Order!
  cancelOrder(id: ID!): Order!
}

type Subscription {
  orderUpdated(id: ID!): Order!
}

type Order {
  id: ID!
  status: OrderStatus!
  customer: Customer!         # nested resolver — fetched on demand
  items: [OrderItem!]!
  total: Float!
  createdAt: DateTime!
}

enum OrderStatus { Pending Paid Shipped Cancelled }
```

**Three operation types:**
- **Query:** read (idempotent, cacheable in theory).
- **Mutation:** write (executed serially within one request to ensure ordering).
- **Subscription:** real-time stream (typically over WebSocket).

A single `POST /graphql` endpoint handles all three. The body distinguishes operation:

```graphql
query GetOrderWithCustomer {
  order(id: "42") {
    id
    total
    customer {
      name
      email
    }
  }
}
```

The response matches the query shape exactly:

```json
{
  "data": {
    "order": {
      "id": "42",
      "total": 99.50,
      "customer": { "name": "Ahmed", "email": "ahmed@example.com" }
    }
  }
}
```

### Scalars, and modelling money and time

The GraphQL specification defines exactly five built-in scalars: `Int`, `Float`, `String`, `Boolean` and `ID` (spec section 3.5, Scalars). `Int` is a signed 32-bit non-fractional value. `Float` is a signed double-precision value as defined by IEEE 754. `ID` is a unique identifier that serialises the same way as a `String` but, in the spec's own words, "is not intended to be human-readable". Everything else — dates, decimals, URLs, UUIDs, email addresses — is a **custom scalar** that either your server library defined for you, or that you define yourself.

That matters for the schema at the top of this chapter. It declares `total: Float!`, which is a double, and a double cannot represent 0.10 exactly. Sum enough order totals and the arithmetic drifts. It also declares `createdAt: DateTime!`, and `DateTime` is not in the specification at all — it works because Hot Chocolate defines it, and the same SDL pasted into a server that does not define it would fail to build.

There are two defensible fixes for money. Store minor units in an integer field, plus a separate currency field: exact, no custom scalar needed, but the scale now lives in documentation rather than in the type. Or use a decimal scalar — Hot Chocolate ships `Decimal` mapped to C# `decimal`, alongside `DateTime`, `Date`, `UUID` and `URI`, so changing the CLR property type changes the schema. Either way, check what the client does with the value: a JavaScript client that runs a JSON number through `JSON.parse` lands back on a double no matter what the schema called the field, which is why several public APIs send money as a string and let the client choose its own decimal library.

Writing your own scalar means subclassing `ScalarType<TRuntimeType, TLiteral>` and registering it with `AddType<T>()`. A scalar has three jobs: parse a literal written inline in the query document, parse a value arriving through variables as JSON, and serialise the resolver's output back out. The names of those overrides have changed between Hot Chocolate versions, so read the docs for the version you are on rather than copying an old sample.

> 🌍 **In the real world**: a payments team shipped `amount: Float!`. Reconciliation against the ledger failed on a handful of orders a day, always by a fraction of a penny, and always on orders with many line items. The schema change was one word. The migration was not, because every generated client had already typed it as a JavaScript `number`, and the deprecation had to run for a full mobile release cycle.

### Nullability comes from your C# types

Hot Chocolate infers GraphQL nullability from CLR nullability. With `<Nullable>enable</Nullable>` set in the project, a `string` property becomes `String!` and a `string?` property becomes `String`; value types already behaved this way, with `int` mapping to `Int!` and `int?` to `Int`. Without nullable reference types enabled, every reference type is nullable in the schema and you end up annotating by hand. Attributes and the descriptor API can override the inference where you need something different.

The consequence is worth saying out loud: adding or removing a single `?` in a C# class changes the published contract. And the two directions are not symmetric. For an **output** field, going from nullable to non-null is safe for existing clients — anything that coped with a null still copes — while going from non-null to nullable is breaking, because clients were entitled to assume a value was always there. For an **input** field or argument the rule inverts: making it nullable, or giving it a default, is safe; making it required is breaking.

This is the concrete mechanism behind the general warning in the code-first drill later in this chapter — that in code-first the schema is a side effect of the implementation. The mitigation is the one that drill prescribes: export the SDL and diff it in CI, so a stray `?` shows up as a schema change during review rather than as a client bug in production.

> 🌍 **In the real world**: a developer silenced a compiler warning by changing `Customer Customer` to `Customer? Customer` on the `Order` entity. Nothing about the C# review looked risky. The schema field flipped from `Customer!` to `Customer`, the next codegen run made `customer` optional in the generated TypeScript types, and the web build failed across a hundred call sites. That is the good outcome. The bad one is a client already compiled against the old shape that now dereferences a null at runtime.

### Interfaces, unions, and inline fragments

There are two ways to say "this field returns one of several types". An **interface** is a set of fields that every implementing type must declare, so a client can select the shared fields directly and drop into an inline fragment only for the type-specific ones. A **union** has no shared fields at all — every selection must sit inside `... on SomeType`. Both are told apart at runtime by `__typename`, which is what clients request and what normalised caches key on.

In Hot Chocolate's code-first model a union is a marker interface carrying `[UnionType("Name")]`, with each member type registered through `AddType<T>()`. A member the schema has never been told about cannot be returned — that is a schema-build error rather than a runtime surprise.

Enums are the third variant-shaped thing, and the one that catches people during evolution. Adding a value to an enum breaks no existing query, because every document that parsed before still parses. It can still break clients at runtime, because generated clients often switch exhaustively over the values that existed when they were generated. GitHub's GraphQL API documents exactly this split: removing a field is a *breaking change*, whereas adding an enum value is a *dangerous change* that "won't break existing queries but could affect the runtime behavior of clients". GitHub gives at least three months' notice for breaking changes and lands them on the first day of a quarter. GraphQL Inspector classifies `ENUM_VALUE_ADDED` as dangerous for the same reason. Note the inversion for enums used as **input**: adding a value there is harmless, since no existing client sends it, but removing one is breaking.

```graphql
# Interface — shared fields selectable directly
interface Payment { id: ID!  amount: Decimal! }
type CardPayment implements Payment { id: ID!  amount: Decimal!  last4: String! }

# Union — everything goes through inline fragments
union SearchResult = Order | Customer | Product

query {
  search(term: "ahmed") {
    __typename
    ... on Order { id total }
    ... on Customer { name }
  }
}
```

> 🌍 **In the real world**: a payments provider added `PartiallyRefunded` to an order-status enum. No query changed and no CI check fired. The iOS app's generated enum had no case for it, its decoder threw, and order history showed an error screen for every customer with a partial refund — on a shipped build that could not be patched for a week. The prevention is not a schema rule; it is either a union in place of the enum, or codegen configured to emit an "unknown" case.

### Global object identification and the Node interface

A Relay-style client needs to refetch a single object after it changes, without knowing which root field originally produced it. That requires two things: identifiers that are unique across the whole schema rather than just within a table, and one root field that turns such an identifier back into an object.

```graphql
interface Node { id: ID! }

type Query {
  node(id: ID!): Node
  nodes(ids: [ID!]!): [Node]!
}
```

Worth knowing which half of that is mandated: Relay's object-identification spec requires only the `Node` interface and the singular `node` root field. The plural `nodes` is a widely-followed convention rather than a spec requirement. In Hot Chocolate, `AddGlobalObjectIdentification()` adds the interface and both root fields. `[Node]` marks a type as a node — the library then looks for a resolver by naming convention (`Get`, `GetAsync`, `Get{TypeName}`, `Get{TypeName}Async`) — and `[NodeResolver]` names one explicitly when the convention does not fit. `[ID]` opts an individual field into global-identifier behaviour: the field's type is rewritten to `ID` and the raw value is combined with the type name to produce something unique schema-wide.

This is also the machinery behind normalised client caches. Apollo Client and Relay key their store on `__typename` plus `id`, so `Order:42` is a single entry that every screen showing that order shares — which is why a mutation that returns the updated object can update six screens with no refetch. If your `id` is only unique per table, `Order:42` and `Invoice:42` collide in that store. It is the same argument the pagination drill makes for opaque cursors, applied to identity: the client should treat the value as a token, not parse it.

> 🌍 **In the real world**: a team wired a "mark as read" mutation that returned `Boolean!`. Every screen showing that notification had to be refetched by hand, and the unread badge went stale whenever somebody forgot one. Returning the updated notification node instead — with a global ID the cache recognised — deleted the refetch code entirely.

### Resolvers

A **resolver** is a function that produces the value for one field. The GraphQL engine walks the requested query tree and calls resolvers in order, passing parent objects down.

```csharp
// Using HotChocolate (the most popular .NET GraphQL library)
public class Query
{
    public async Task<Order?> GetOrder(string id, IOrderService svc)
        => await svc.GetByIdAsync(id);
}

public class OrderType : ObjectType<Order>
{
    protected override void Configure(IObjectTypeDescriptor<Order> descriptor)
    {
        descriptor.Field(o => o.Id).Type<NonNullType<IdType>>();
        descriptor.Field(o => o.Total).Type<FloatType>();
        // Customer resolver — runs only if client requested customer
        descriptor.Field("customer")
            .ResolveWith<OrderResolvers>(r => r.GetCustomer(default!, default!))
            .Type<NonNullType<CustomerType>>();
    }
}

public class OrderResolvers
{
    public async Task<Customer> GetCustomer([Parent] Order order, ICustomerService svc)
        => await svc.GetByIdAsync(order.CustomerId);
}
```

Setup:

```csharp
builder.Services
    .AddGraphQLServer()
    .AddQueryType<Query>()
    .AddMutationType<Mutation>()
    .AddType<OrderType>()
    .AddProjections()        // map GraphQL selections to EF Core projections
    .AddFiltering()           // generate WHERE filters from arguments
    .AddSorting();

app.MapGraphQL();             // /graphql endpoint + Nitro IDE
```

### The N+1 problem and DataLoader

The classic GraphQL trap. A query like:

```graphql
query {
  orders(limit: 50) {
    id
    customer { name }    # fetches customer per order
  }
}
```

If the customer resolver does `db.Customers.Find(order.CustomerId)`, you get **51 DB queries** (1 for orders + 50 for customers). At scale: instant outage.

**Solution: DataLoader.** Batch all customer lookups into one query with `WHERE Id IN (...)`. HotChocolate has built-in DataLoader support:

```csharp
public class CustomerByIdDataLoader : BatchDataLoader<int, Customer>
{
    private readonly ICustomerRepository _repo;
    public CustomerByIdDataLoader(
        ICustomerRepository repo, IBatchScheduler scheduler, DataLoaderOptions options)
        : base(scheduler, options) { _repo = repo; }

    protected override async Task<IReadOnlyDictionary<int, Customer>> LoadBatchAsync(
        IReadOnlyList<int> ids, CancellationToken ct)
        => (await _repo.GetByIdsAsync(ids, ct)).ToDictionary(c => c.Id);
}

// Resolver uses the DataLoader
public async Task<Customer> GetCustomer(
    [Parent] Order order,
    CustomerByIdDataLoader loader)
    => await loader.LoadAsync(order.CustomerId);
```

DataLoader collects all `LoadAsync(id)` calls within a tick of the request, fires one batched query, distributes results.

Alternative: **HotChocolate's projection** maps the GraphQL selection set into an `Include()`-aware EF Core query, eliminating N+1 at compile time:

```csharp
[UseProjection]
public IQueryable<Order> GetOrders(AppDbContext db) => db.Orders;
```

If the client asks for `customer { name }`, HotChocolate adds `.Include(o => o.Customer)`. Powerful but only works for EF-backed resolvers.

### Mutation payloads and errors as data

The top-level `errors` array covered later in this chapter is the transport-level channel. It is untyped — a message, a path, and a free-form `extensions` bag — it is not part of the schema, and a client cannot discover from the schema what might appear there. That is the right home for "the database was unreachable". It is the wrong home for "that SKU is out of stock", which is an ordinary outcome the UI has to render, and which the client ought to be able to handle exhaustively.

The pattern is to make expected failures part of the return type. Each mutation returns a **payload** type carrying the result plus a typed list of domain errors:

```graphql
type Mutation {
  createOrder(input: CreateOrderInput!): CreateOrderPayload!
}

type CreateOrderPayload {
  order: Order                    # null when the mutation failed
  errors: [CreateOrderError!]
}

union CreateOrderError = OutOfStockError | PaymentDeclinedError
interface Error { message: String! }
```

The client selects `... on OutOfStockError { message sku }` and gets a closed set of failure modes it can switch over — and when you add a third one, codegen tells the client team. Note that `order` has to be nullable here, because the mutation can fail. That is the nullability trade-off from the error-model drill, made deliberately rather than by accident.

Hot Chocolate generates the whole shape. `AddMutationConventions()` rewrites each mutation into a generated input type and a generated payload type. `[Error(typeof(OutOfStockException))]` on the resolver adds that exception to the payload's error union: a middleware catches the declared exception types and rewrites them into error objects, replacing the `Exception` suffix with `Error` in the schema name, so `OutOfStockException` surfaces as `OutOfStockError`. The generated error types implement an `Error` interface that requires a `message` field; `AddErrorInterfaceType<T>()` swaps in your own interface when `message` alone is not enough — a machine-readable code, say, or a field path for form validation.

The discipline this demands is deciding, per exception, which channel it belongs in. An exception you did not declare still lands in the top-level `errors` array, which is correct — undeclared means unexpected. If everything ends up declared, you have rebuilt the untyped array with extra ceremony.

> 🌍 **In the real world**: a checkout mutation returned HTTP 200 with `data.createOrder` null and a top-level error reading "Insufficient stock for SKU ABC-1". The web client string-matched that message to show a useful error. Someone reworded it for clarity, the match stopped working, and customers got a generic "something went wrong" on the highest-value screen in the product. A typed `OutOfStockError` carrying a `sku` field would have made the reword a non-event.

### Incremental delivery with @defer and @stream

`@defer` marks a fragment the server is allowed to send after the initial response; `@stream` does the same for the items of a list. The first payload contains everything else — deferred fragments absent, streamed lists holding only their initial items — and the remainder arrives on later payloads within the same HTTP response. It attacks the problem raised in the HTTP-batching drill from the other side: instead of the fast fields waiting on the slow one, the slow one is allowed to arrive late.

The response therefore stops being a single JSON object. Each payload carries `hasNext`, true on every payload but the last; `pending` entries announcing what is still to come, with the `path` and `label` of the directive that produced them; and `incremental` entries carrying delivered data — a `data` field for `@defer`, an `items` field for `@stream`. Transport is negotiated through `Accept`: `multipart/mixed`, `text/event-stream`, or JSON Lines. Hot Chocolate implements all three and selects on the `Accept` header. That same content negotiation is where `application/graphql-response+json` comes from — the media type the GraphQL over HTTP specification defines for ordinary single-payload responses.

Two things a senior candidate is expected to know. First, this is not ratified GraphQL. `@defer` and `@stream` live in a GraphQL working-group RFC that is still a working draft, the payload format has been revised more than once, and Hot Chocolate 16 changed its default wire format from the older path-based encoding to a newer id-based one. Both ends have to agree; a client that does not implement incremental delivery will not parse the response at all, which is why Hot Chocolate has treated the directives as opt-in since version 13.

Second, the error model shifts. Status line and headers are committed the moment the first payload is flushed, so a deferred fragment that fails afterwards cannot change the status code — the failure arrives inside a later payload's errors. Anything between client and server that decides from the status line without reading the whole body — retry middleware, a CDN, an API gateway — sees a success it has no chance to revise.

> 🌍 **In the real world**: a product page needed price and stock immediately and personalised recommendations eventually, and recommendations was the slow service. Deferring that fragment let the page paint on the first payload. The catch was operational: the latency dashboard measured time to last byte, which now included the slow fragment by design, so the improvement registered as a regression until the metric was split into time-to-first-payload and time-to-complete.

### File uploads

The GraphQL specification has nothing to say about uploading bytes. The usual in-band answer is the community **GraphQL multipart request specification**, which defines a `multipart/form-data` body carrying the operation, a map from file parts to variable paths, and the parts themselves. Hot Chocolate implements it: register `AddType<UploadType>()` and you get an `Upload` scalar whose runtime type is `IFile`. `Upload` is input-only — a resolver cannot return one. Request size is then bounded by ASP.NET Core's form limits (`FormOptions.MultipartBodyLengthLimit`) and by whatever Kestrel or IIS enforces in front of that. Since Hot Chocolate 13.2 a multipart request must also carry a `GraphQL-preflight: 1` header, for the CSRF reason described below: `multipart/form-data` is one of the content types a browser will send cross-origin without a preflight.

The out-of-band alternative keeps bytes out of GraphQL entirely, and it is what most large systems settle on. One mutation returns a short-lived pre-signed URL from the storage provider plus an opaque object key; the client `PUT`s the bytes straight to blob storage over ordinary HTTP; a second mutation attaches the key to the entity. The authorization decision still happens in a resolver — you refuse to issue the URL — but the payload never traverses your application server, so upload size stops being a Kestrel tuning exercise and a stalled upload cannot hold a GraphQL execution open. The mirror image applies on the way out, and it is what Hot Chocolate's own documentation recommends for reads: expose a URL field rather than base64 bytes, because bytes embedded in JSON cannot be cached by a CDN and cannot be range-requested for video playback.

> 🌍 **In the real world**: a document-management feature shipped with multipart uploads and worked fine until customers started attaching scans from an office copier. Requests then began failing at the reverse proxy, whose body limit nobody had touched, with an error that never reached a resolver and therefore never reached the GraphQL error array — the client just saw a broken response. Moving to pre-signed URLs took the proxy out of the path entirely.

### GraphQL vs REST

| Concern | REST | GraphQL |
|---|---|---|
| Endpoints | Many, resource-oriented | One (`/graphql`) |
| Response shape | Server-defined | Client-defined |
| Over/under-fetching | Common | Rare |
| Caching | HTTP caching (mature) | Custom (Apollo Cache, persisted queries) |
| File uploads | Native | Awkward (`multipart/form-data` extension) |
| Versioning | URL/header | Schema evolution (deprecated fields) |
| Typing | OpenAPI optional | Schema is mandatory |
| Tooling | Swagger UI, Postman | GraphiQL, Apollo GraphOS |
| Real-time | SignalR / WebSocket sidecar | Subscriptions built in |
| Learning curve | Low | Higher (resolvers, N+1, schema design) |

REST wins for: simple CRUD, public APIs with HTTP caching, internal service-to-service.
GraphQL wins for: aggregating multiple sources, mobile/SPA frontends with many shapes, public APIs with diverse consumers.

### Schema evolution (no versioning)

GraphQL discourages versioning (`/v1/`, `/v2/`). Instead:

- **Add fields freely.** Old clients ignore them.
- **Deprecate, don't remove.** Mark old fields with `@deprecated(reason: "Use newField instead")`. They stay queryable but tooling warns.
- **Track usage.** Apollo GraphOS, GraphQL Hive can tell you when a deprecated field has hit zero traffic — *then* remove it.

```graphql
type Order {
  id: ID!
  status: String! @deprecated(reason: "Use orderStatus enum instead")
  orderStatus: OrderStatus!
}
```

Schema changes are still possible to break (renaming a type, narrowing a return). Use a schema-comparison CI step (`graphql-inspector`) to catch them.

### Federation in the .NET stack: Fusion and Composite Schemas

The federation drill later in this chapter covers the concept in Apollo's vocabulary. The follow-up a .NET interview reaches for is: what do you actually run?

The gateway is a different product from the subgraph server. Hot Chocolate is the subgraph. For the gateway you are choosing between Apollo's router and ChilliCream's **Fusion**. Fusion composes the source schemas ahead of time into a Fusion archive — a `.far` file holding the composite schema and the gateway configuration — rather than composing at runtime, so a composition failure is a red build rather than a bad deploy.

Fusion implements the **GraphQL Composite Schemas specification**, an open standard being drafted under the GraphQL Foundation to standardise composition and distributed execution across collaborating services: the problem Apollo Federation solved proprietarily first. It is a working draft, so treat it as a direction of travel rather than a settled contract. Its vocabulary differs from Apollo's. An entity is fetched through a field marked `@lookup` rather than through a magic `_entities` field; `@is` maps a lookup's arguments onto the entity's fields when the names do not line up; and Apollo's `@requires` is spelled `@require`. In C# you annotate with `[Lookup]` and `[Internal]` from the `HotChocolate.Fusion.SourceSchema` package. Fusion also ships an Apollo Federation connector that translates Apollo's directives at composition time and speaks Apollo's `_entities` protocol at runtime, so both kinds of subgraph can sit in one composed schema during a migration.

Licensing is a real part of this decision and a fair thing to be asked about. The Apollo Router Core is source-available under the **Elastic License v2**, not an OSI-approved open-source licence: you may use, modify and redistribute it, but not offer it to third parties as a hosted service. ChilliCream publishes its own ChilliCream License covering its platform products. Neither is a reason to avoid federating; both are a reason to read the terms before a platform team standardises on a gateway.

> 🌍 **In the real world**: the reason organisations federate is rarely technical. Four teams want one schema for the client and independent deploy cadences for themselves. What it costs is a new class of failure — a subgraph deploy that is perfectly valid on its own can break the *composed* schema, which is why composition checks belong in CI on every subgraph, not just at the gateway — and a new class of argument, because "which team owns the `User` type" is an organisational question that no directive answers.

### What introspection gives away

Introspection is the meta-query built into every spec-compliant server. `__schema` and `__type` return the type system itself: every type, field, argument, default value, deprecation reason and description. It is what powers Nitro, GraphiQL, client codegen and schema diffing, and for a deliberately public API it *is* the documentation — which is why GitHub and Shopify leave it on.

For a private API it is a map drawn for whoever asks. Hot Chocolate turns it off with `AllowIntrospection(false)`, usually wired to the hosting environment. When you need it selectively, a subclass of `DefaultHttpRequestInterceptor` can call `AllowIntrospection()` on the individual request when a header or claim is present, and `SetIntrospectionNotAllowedMessage(...)` controls what everyone else is told. There is a performance argument alongside the security one: introspecting a large schema is an expensive recursive query, and that is ChilliCream's own stated reason for offering the switch.

Turning it off is not the whole job. Many servers answer a misspelled field name with "Did you mean ...?", and those suggestions leak the schema one guess at a time. The open-source tool **Clairvoyance** automates precisely this — run a wordlist at the endpoint, harvest the suggestions, and rebuild a usable schema from a server whose introspection is disabled. So suppress the suggestions too. Apollo Server exposes `hideSchemaDetailsFromClientErrors`; GraphQL Armor ships a field-suggestion blocking plugin for the JS stack. Check what your server does by default rather than assuming it does the careful thing.

> 🌍 **In the real world**: a partner integration went live with introspection disabled and a security review signed off. A tester then pointed a suggestion-scraper at it and had most of the mutation names inside an hour, including an internal impersonation mutation that authorization did correctly protect but that nobody had intended to advertise. The finding was not "we forgot to disable introspection". It was "we thought disabling introspection was the control".

### Aliases, batching, and the limits that catch them

An alias renames a field in the response, so `a: order(id: "1")` and `b: order(id: "2")` are two results from one field. Nothing in the language stops a client aliasing the same field a thousand times in one document. Such a query is two levels deep, so a depth limit never fires. It is one HTTP request, so a rate limiter that counts requests scores it as one. And it names one root field, so anything reasoning about "which operation is this" sees a single operation.

That is a documented attack, not a theoretical one. PortSwigger's Web Security Academy has a lab whose entire point is brute-forcing a login by aliasing many `login` mutations into a single request, precisely because the rate limiter counted HTTP requests rather than operations. Array-form HTTP batching — the client-side batching the batching drill recommends for its round-trip savings — stacks on top: one request can now carry many operations, each carrying many aliases.

The controls sit at three levels, and they are not substitutes for each other.

- **Before validation**, document limits reject a hostile document during parsing, when rejection is cheapest. Hot Chocolate's `ModifyParserOptions` exposes `MaxAllowedFields`, `MaxAllowedNodes`, `MaxAllowedTokens` and `MaxAllowedDirectives`. Worth knowing that Hot Chocolate documents `MaxAllowedNodes` and `MaxAllowedTokens` as unlimited by default, so these are opt-in rather than free.
- **At validation**, cost analysis prices fields and lists, as described in the complexity drill.
- **At the rate limiter**, count operations or cost units rather than HTTP requests. This is the control that actually stops an aliased brute force, because the first two only bound the size of one document — they do not care what that document is trying to guess.

On the JS side, GraphQL Armor's `maxAliases` plugin caps aliases directly — its documented default is 15 — with `maxDirectives` and `maxTokens` beside it.

> 🌍 **In the real world**: a team added a strict per-IP request limit to its login endpoint after a credential-stuffing attempt and considered the matter closed. The same attacker returned through the GraphQL endpoint with a couple of hundred aliased login mutations per request and stayed comfortably under the limit. The fix was not a lower request limit; it was counting attempts inside the resolver, where an attempt is an attempt regardless of how the document was shaped.

### CSRF once you serve GraphQL over GET

A browser sends some cross-origin requests without asking permission first. A request counts as "simple" — no CORS preflight — when it uses a safe method and sets only headers a plain HTML form could have produced. `Content-Type: application/json` is not one of those. That is why `POST /graphql` with a JSON body is incidentally CSRF-resistant: the browser has to preflight it, and your CORS policy gets a veto before the request is ever executed.

A GET request has no body and therefore no `Content-Type`, so it is simple by default. The moment you flip persisted queries to GET so a CDN can cache them — advice this chapter repeats in the persisted-query and caching drills — you have created an endpoint that any page on the internet can make a logged-in user's browser call, with cookies attached. CORS still stops the attacker reading the response. If the operation has side effects, they may not need to read it.

Two independent controls, and you want both:

- **Never let a GET execute a mutation.** Hot Chocolate defaults `AllowedGetOperations` to `AllowedGetOperations.Query`; leave it there. It is a `GraphQLServerOptions` property, set globally with `ModifyServerOptions` or per endpoint with `WithOptions`. Combined with a registered persisted-operation allowlist, the only thing a GET can then run is a pre-vetted read.
- **Require a header a simple request cannot carry.** Apollo Server and the Apollo Router refuse to execute unless the request carries at least one of: a `Content-Type` that forces a preflight (`application/json` qualifies), a non-empty `X-Apollo-Operation-Name`, or a non-empty `Apollo-Require-Preflight`. Any of them makes the request non-simple, so the browser preflights and CORS is back in charge. Hot Chocolate applies the same idea to multipart uploads with its `GraphQL-preflight: 1` requirement.

What makes this exploitable is ambient credentials. A bearer token in an `Authorization` header is not attached automatically by the browser, so a cookie-authenticated GraphQL API carries this risk in a way a token-authenticated one does not — which is the honest answer when someone asks whether an API needs CSRF protection at all.

> 🌍 **In the real world**: a team enabled GET for persisted queries to get CDN caching, and months later added a persisted operation whose "read" also recorded a view and decremented a promotional counter. As far as the schema was concerned this was a query, so the allowlist saw nothing wrong, the CDN cached the response, and any page on the web could trigger the side effect. `AllowedGetOperations = Query` does not help when a write is dressed as a read. The control that would have caught it is the rule from the operation-types drill: writes go in `Mutation`, even when the API feels nicer without.

### Observability for a single-endpoint API

Every operation is `POST /graphql`. Everything keyed on method and path therefore collapses into one row: access logs, APM route grouping, WAF rules, gateway rate limits, latency dashboards. The p99 for `/graphql` is the p99 of a mixture, and a trivial header query is indistinguishable from an analytics export that scans a year of orders.

The fix starts in the document. Require every operation to be named, and treat an anonymous operation as a lint failure, because the operation name is the dimension everything downstream groups by. OpenTelemetry's semantic conventions for GraphQL define `graphql.operation.name`, `graphql.operation.type` (`query`, `mutation` or `subscription`) and `graphql.document`. Note that the convention names the span after the operation *type*, not the operation name — a client-supplied name is high-cardinality, so the convention explicitly advises against putting it in the span name by default and leaves it as an attribute you group by. Those attributes are still marked development-status in the conventions, so pin your versions and expect churn. Hot Chocolate emits them: add the `HotChocolate.Diagnostics` package and call `AddInstrumentation()`, where `ActivityScopes` controls how deep the instrumentation goes and `RequestDetails` controls whether the operation name and the document text land on the root activity. Per-resolver spans are what actually reveal an N+1, but a span per field on a wide query is a great many spans — turn the detail up while investigating rather than leaving it on.

`graphql.document` is opt-in for a reason: a document carries inline argument literals, so it can move customer data into your tracing backend, and the convention itself recommends redaction. Persisted operations sidestep this neatly — the hash identifies the operation without shipping its text.

Then errors. Hot Chocolate does not include exception details in the response by default; `IncludeExceptionDetails` is off unless a debugger is attached, so a resolver that throws yields a generic error rather than a stack trace. Leave that setting alone in production, and register an `IErrorFilter` to map known exceptions onto stable, documented values in `extensions.code`. The code is what a client switches on and what you alert on. The stack trace belongs in your logs next to a correlation id, not in an `errors` array a browser devtools panel will happily render.

> 🌍 **In the real world**: an on-call engineer was paged at 2 a.m. by "p99 on /graphql exceeded three seconds". The dashboard had one line and the line was useless. Tagging spans with the operation name showed the whole of that p99 belonged to one nightly export run by an internal reporting job; every customer-facing operation was unchanged. The alert had been firing on a mixture for months, and the first real fix was splitting the dashboard by operation name rather than making anything faster.

### Testing a GraphQL service

Three layers, and candidates usually name only the last.

**The schema.** Export the SDL and diff it. This chapter already prescribes that as a CI step; the point worth adding is that it is a test, not a build chore, because it is what turns an accidental `?` into a review comment.

**Operations against an in-memory executor.** You do not need a web server to execute GraphQL. Build the executor from the service collection with `BuildRequestExecutorAsync()` and call `ExecuteAsync` with an operation; you get back the same result object the HTTP layer would have serialised. Snapshot the JSON — ChilliCream's own test suite uses the CookieCrumble snapshot library for exactly this. "This operation returns this payload" is a stronger assertion than a pile of per-field checks, because it also fails on the shape change you did not intend: a field that started returning null, an error that appeared, a deprecation removed too early. This is the layer where resolver logic, field-level authorization and error payloads belong.

**The HTTP surface.** ASP.NET Core's `WebApplicationFactory` and `TestServer` for what the executor cannot see: content negotiation, the GET and CSRF rules above, authentication middleware, and the WebSocket upgrade for subscriptions.

There is a fourth thing that almost nobody sets up until it bites: validating real client operations against the candidate schema before deploying it. This chapter's evolution advice — remove a deprecated field once usage hits zero — is only as safe as your knowledge of what clients are actually sending. Tooling in this space validates a stored set of client documents against a proposed schema and reports schema coverage; GraphQL Inspector does both. Running that check against the operations recorded over the last N days is what converts "usage is zero" from a dashboard reading into a gate.

> 🌍 **In the real world**: the field had zero traffic for ninety days, the dashboard was green, and it was removed. What the dashboard could not see was an iOS build from fourteen months earlier, still on the App Store and still installed, whose users simply did not open that screen often. The first support tickets arrived a week later, from customers who could not be force-upgraded. Web clients let you reason about "the current version". Mobile does not, and the honest rule is that your removal window is set by the oldest build you are willing to break.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Query → Resolver execution flow

```
Client query:                      Server resolver tree:
{
  orders(limit: 2) {               1. Query.orders(limit=2) → [Order, Order]
    id                                    │
    customer {                            ├─ Order.id           (trivial getter)
      name                                ├─ Order.customer     (resolver → DataLoader)
    }                                     │       │
  }                                       │       └─ Customer.name (trivial getter)
}                                         │
                                          └─ Order.id, Order.customer.name
                                                  (same per order)

DataLoader batches customer fetches:
   GET orders → 1 DB query
   Customer.id IN (10, 17) → 1 DB query (instead of 2)
```

### N+1 vs batched: timing

```
WITHOUT DataLoader (50 orders, customer per order):
  ┌────────────────────────────────────────────────┐
  │ Order query   ████ 20ms                        │
  │ Customer 1   ██ 10ms                           │
  │ Customer 2   ██ 10ms                           │
  │ ...          ████ 50 × 10ms = 500ms             │
  │ Customer 50  ██ 10ms                           │
  │ TOTAL: 520ms                                   │
  └────────────────────────────────────────────────┘

WITH DataLoader:
  ┌────────────────────────────────────────────────┐
  │ Order query        ████ 20ms                   │
  │ Customers (batch)  ██ 15ms                     │
  │ TOTAL: 35ms                                    │
  └────────────────────────────────────────────────┘
```

### Mutation example

```graphql
mutation {
  createOrder(input: { customerId: "7", items: [{ productId: "P1", quantity: 2 }] }) {
    id
    status
    total
  }
}
```

```csharp
public class Mutation
{
    public async Task<Order> CreateOrderAsync(
        CreateOrderInput input,
        IOrderService svc)
        => await svc.CreateAsync(input);
}

public record CreateOrderInput(string CustomerId, IReadOnlyList<OrderItemInput> Items);
public record OrderItemInput(string ProductId, int Quantity);
```

### Subscription with WebSocket

```graphql
subscription {
  orderUpdated(id: "42") {
    status
    updatedAt
  }
}
```

```csharp
public class Subscription
{
    [Subscribe]
    [Topic("Order_{id}")]
    public Order OrderUpdated([EventMessage] Order order, string id) => order;
}

// Publisher
await _eventSender.SendAsync($"Order_{order.Id}", order);
```

HotChocolate auto-bridges to WebSocket transport.

</details>

## Common pitfalls

1. **N+1 queries.** Naive resolvers issue one DB query per parent. Use DataLoader or projections.
2. **Returning everything by default.** A `getOrders` resolver that fetches 100k orders and lets the client filter client-side. Use `@filter` or pagination.
3. **No depth/complexity limits.** Malicious clients send `{ orders { customer { orders { customer { ... } } } } }` to exhaust the DB. Use complexity scoring + max depth.
4. **No persisted queries.** Public GraphQL servers accept arbitrary queries — easy DoS. Persisted queries (whitelist of pre-registered queries) eliminate this for production clients.
5. **Mutations that should be one are split into many.** Each mutation is a transaction boundary. Don't have the client call 5 mutations in sequence to "create an order"; have one `createOrder` mutation that does all writes.
6. **Authorization at the wrong layer.** Field-level authorization is GraphQL's superpower — different fields have different permissions. Don't rely on endpoint-level auth alone.
7. **Treating HTTP status codes as the error mechanism.** GraphQL responses are usually 200 even on errors; errors live in the `errors` array. Coexisting with REST middleware that expects 4xx/5xx requires care.
8. **Caching with REST mental model.** GraphQL queries change shape; HTTP caching by URL doesn't work. Use persisted queries to make URLs cacheable, or accept that caching lives in the client (Apollo Cache).
9. **Schema sprawl.** Without governance, the schema grows hundreds of types — duplicates, near-duplicates, dead types. Apply linters and ownership.
10. **Big single resolver instead of small composable ones.** `getOrderWithEverything` resolver that fetches order + customer + items + payments is anti-GraphQL. Let the client compose.
11. **Forgetting subscriptions are expensive.** Each subscriber is a long-lived WebSocket. Cap concurrent subscriptions per user.
12. **Mixing GraphQL and REST in the same auth flow.** Token rules differ. Either keep them separate or unify the auth middleware carefully.

## Interview-ready summary

- **GraphQL = client-defined response shape over a typed schema.** Single endpoint, three operation types (query, mutation, subscription).
- **Resolvers** produce values per field. The engine walks the query tree and calls them.
- **N+1 problem** is the canonical pitfall. **DataLoader** batches; **projections** push selection into the DB query.
- **No versioning** — evolve via additive changes and `@deprecated`.
- **Wins** in BFF and consumer-facing APIs with diverse needs. **Loses** to REST/gRPC for service-to-service and simple CRUD.

**Expected interview questions:**

1. *"Walk me through resolver execution for a nested query."* — Engine receives query → starts at root → calls `Query.orders` → for each result, walks requested sub-fields → calls each resolver → assembles response shape.
2. *"What's the N+1 problem in GraphQL?"* — One root query produces N parents; each parent's nested resolver does its own DB call → N+1 queries. Fix: DataLoader batches by tick; projections fold selection into a single SQL `JOIN`.
3. *"GraphQL vs REST?"* — REST: server-defined responses, mature HTTP caching, simpler. GraphQL: client-defined responses, no over/under-fetching, harder to cache at HTTP layer.
4. *"How do you secure a GraphQL endpoint?"* — Auth at endpoint + field-level authorization in resolvers. Query-complexity limits. Persisted queries in production. Rate limit by query cost, not just request count.
5. *"How do you version a GraphQL schema?"* — You don't, traditionally. Add fields freely, deprecate old ones with `@deprecated`, track usage, remove when usage hits zero.
6. *"How do GraphQL subscriptions work?"* — WebSocket connection; client sends a subscription operation; server pushes events on a topic. HotChocolate uses `[Topic]` + `IEventSender` for pub/sub.
7. *"What's a persisted query?"* — Pre-registered query identified by a hash. Client sends only the hash + variables. Server runs the corresponding stored query. Enables HTTP caching and prevents DoS via arbitrary queries.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — The N+1 problem

> **Q**: What is the N+1 problem in GraphQL and how does DataLoader fix it?
>
> **A**: A root resolver returns N parents (e.g., 50 orders), and each parent has a nested resolver (`customer { name }`) that issues its own DB query → 1 + N queries. DataLoader collects all `LoadAsync(id)` calls within an execution tick, fires one batched query (`WHERE Id IN (...)`), and dispatches results back to each waiting resolver. 51 queries collapse to 2.
>
> **Cross-Q**: What's the difference between DataLoader and HotChocolate's `[UseProjection]`?
>
> **A**: DataLoader is **data-source agnostic** — works for EF, REST APIs, gRPC, Redis. It batches by key. `[UseProjection]` is **EF-only**: it inspects the GraphQL selection and folds it into one SQL query with the right `Include`/`Select`. Projection is more efficient when the whole subtree is EF-backed; DataLoader is needed when you cross sources. They compose — project the EF subtree, DataLoader the cross-source fields.
>
> **Cross-Q²**: A DataLoader is used but N+1 still happens. What's the most common cause?
>
> **A**: Per-request scope is wrong. DataLoader must be **scoped to one GraphQL execution** — if registered as a singleton, every concurrent request shares cached keys (correctness bug) and batching windows collide. If registered as transient, each resolver call gets a fresh DataLoader and batching never happens (perf bug). HotChocolate scopes DataLoaders to the execution automatically — declare the DataLoader as a resolver parameter and the framework hands you the per-request instance. Manual `new CustomerByIdDataLoader(...)` in a resolver defeats the framework's batching.

### Drill 2 — Query vs Mutation vs Subscription

> **Q**: What's the semantic difference between the three operation types, and how does the runtime enforce it?
>
> **A**: **Query** = read-only, idempotent, runs resolvers in **parallel**. **Mutation** = write, runs roots **serially** (spec-mandated) so clients can chain side effects. **Subscription** = long-lived stream (one operation, many emissions) typically over WebSocket.
>
> **Cross-Q**: Why are mutations serial but queries parallel?
>
> **A**: Queries have no observable order dependency — reading order A and order B in parallel produces the same result either way. Mutations are state changes; clients depend on ordering (`createUser → updateProfile → sendInvite`). If the spec allowed parallel mutations, identical client code would produce different outcomes depending on resolver timing. Serial mutations make the contract deterministic across implementations.
>
> **Cross-Q²**: Can I cheat and do writes inside a query resolver?
>
> **A**: The engine won't stop you, but you've broken the contract clients rely on. Caches (Apollo Cache, HTTP-level persisted-query CDN) treat queries as safe-to-replay; writes inside queries get double-executed. Idempotent reads can be GET-cached and prefetched. Anything mutating belongs in `Mutation` — even if it makes the API "feel" worse, the contract integrity is worth more than the elegance.

### Drill 3 — Schema federation vs schema stitching

> **Q**: Apollo Federation vs schema stitching — what's the difference?
>
> **A**: **Stitching** (older) — a gateway pulls multiple schemas and merges them, with manual conflict resolution and link-field hooks. **Federation** (newer) — each subgraph declares ownership via directives (`@key`, `@external`, `@requires`, `@provides`); a federated gateway plans queries across subgraphs automatically. Federation is the production pattern in 2026.
>
> **Cross-Q**: In Federation, what does `@key(fields: "id")` actually do?
>
> **A**: It marks `id` as the entity's primary identifier for cross-subgraph resolution. When subgraph A returns an `Order` and subgraph B extends `Order` with a `payment` field, the gateway issues a follow-up call to subgraph B with `_entities(representations: [{ __typename: "Order", id: "42" }])`. B's `__resolveReference` then loads its `Order` slice using just the key. Without `@key`, the gateway has no way to ask "give me this entity by ID across boundaries."
>
> **Cross-Q²**: Why does Federation suffer from the N+1 problem at the gateway, and how is it fixed?
>
> **A**: For each parent entity returned by subgraph A, the gateway calls B's `_entities`. Naive implementation = one call per entity. Federation v2 uses **representation arrays** — the gateway batches all keys into a single `_entities` call: `representations: [{__typename:"Order", id:"1"}, {__typename:"Order", id:"2"}, ...]`. B's `__resolveReference` receives the batch and must DataLoader-batch internally too. Both layers (gateway-to-subgraph and subgraph-to-DB) need batching; missing either reintroduces N+1.

### Drill 4 — Persisted queries

> **Q**: What problem do persisted queries solve?
>
> **A**: Two at once: **performance** (clients send a short hash instead of a full query body — smaller payloads, GET-cacheable URLs, CDN-friendly) and **security** (server rejects any query whose hash isn't in the registry — eliminates arbitrary-query DoS and limits the attack surface to known-vetted operations).
>
> **Cross-Q**: How does APQ (Automatic Persisted Queries) differ from manually registered persisted queries?
>
> **A**: **APQ** is opportunistic — the client sends a hash first; on a miss the server replies "PersistedQueryNotFound," the client re-sends with the full query body, server caches it under the hash. Good for dev velocity, but the cache is best-effort and arbitrary queries still execute. **Registered** persisted queries are part of the build — the client bundle ships with a hash manifest, the server has a fixed allowlist, anything outside it is rejected. Registered is the security control; APQ is the convenience optimization.
>
> **Cross-Q²**: Persisted queries are deployed but a CDN still caches nothing. Why?
>
> **A**: The client is still sending `POST /graphql` with the hash in the body, and CDNs don't cache POSTs by default. The fix is to flip to **GET requests** with the hash + variables in the query string (`GET /graphql?id=abc123&variables={...}`). Now the URL is the cache key; the CDN happily caches. Trade-off: variables in the URL leak into logs, so don't put PII there. Combine with `Cache-Control: max-age=...` from the resolver layer.

### Drill 5 — Query depth & complexity limiting

> **Q**: Why is query depth or complexity limiting non-optional in production?
>
> **A**: GraphQL exposes the full graph through one endpoint; a single request can express enormous server work. `{ user { posts { author { posts { author { posts { ... } } } } } } }` recursively explodes — without limits, one malicious or buggy client takes down the DB.
>
> **Cross-Q**: Depth-limiting alone isn't enough. Why?
>
> **A**: Depth is one dimension. A shallow query `{ orders(limit: 10000) { id customer { id } } }` is depth 3 but issues 10001 DB queries (without DataLoader) or fetches 10k rows × 2 fields. Complexity scoring assigns cost per field with **list multipliers** — `orders(limit: 10000)` costs `field_cost × 10000`. The threshold is a single budget that captures both depth and breadth.
>
> **Cross-Q²**: How do you decide the complexity threshold?
>
> **A**: Empirically. Capture the cost score for every production query over a week (HotChocolate's cost analysis computes a field cost and a type cost per operation), plot the distribution. Pick a threshold at p99 or p99.9 of legitimate traffic — high enough to never reject real users, low enough to block obvious abuse, and set it via `ModifyCostOptions(o => o.MaxFieldCost = ...)`. Combine with **rate-limit-by-cost**: instead of "1000 requests/min," do "1000 cost-units/min" — a single expensive query consumes more budget than a cheap one.

### Drill 6 — REST vs GraphQL

> **Q**: When do you pick GraphQL over REST in 2026?
>
> **A**: GraphQL wins when (1) clients have diverse shape requirements (mobile + web + watch all want different fields), (2) one operation needs to aggregate across services (BFF pattern), (3) over-fetching meaningfully hurts (mobile bandwidth, payload size). REST wins for simple CRUD, service-to-service, public APIs where HTTP caching matters, or teams without the tooling to manage schema evolution.
>
> **Cross-Q**: A team migrates a REST API to GraphQL and immediately misses HTTP caching. What changed?
>
> **A**: REST URLs (`/orders/42`) are stable cache keys; every layer of the HTTP stack (browser, CDN, reverse proxy) caches them for free. GraphQL is `POST /graphql` with query in body — every distinct query is a different "resource," and POSTs aren't cached. Workarounds: persisted queries flipped to GET, Apollo Cache client-side, response cache at the resolver layer. The loss is real and is the strongest reason REST still wins for high-cache-ratio public APIs.
>
> **Cross-Q²**: A REST team writes a GraphQL gateway that just wraps existing REST endpoints. Smell or pattern?
>
> **A**: Smell, if the gateway just translates one-to-one — you've added GraphQL complexity without solving over-fetching (the gateway still over-fetches from REST, then trims). Pattern, if the gateway **aggregates** multiple REST calls behind one resolver tree (BFF), or **DataLoader-batches** them so the client gets one round-trip for what was 5 sequential REST calls. The litmus: would the client be making fewer HTTP round-trips or fetching less data? If no, you've added a layer for nothing.

### Drill 7 — Pagination — Relay cursor connections

> **Q**: How does Relay-style cursor pagination work and why is it preferred over offset?
>
> **A**: Each list field returns a `Connection` type with `edges { node, cursor }` and `pageInfo { hasNextPage, endCursor }`. The client passes `first: N, after: $cursor` to fetch the next page. Cursors are opaque (typically base64-encoded `(timestamp, id)` tuples). Preferred over offset because (1) it's stable under concurrent inserts (offset 100 changes meaning as rows are added), (2) it scales to billion-row datasets (offset 100000 forces the DB to scan and skip), (3) it matches keyset pagination at the SQL layer.
>
> **Cross-Q**: Why are cursors opaque rather than just exposing `id` directly?
>
> **A**: Opacity preserves the server's freedom to change the sort. If you expose `id` as the cursor, clients hardcode "next page = id > 42" and your sort is permanently `ORDER BY id`. Opaque cursors let the server encode `(score, created_at, id)` for relevance sorting today and switch to `(rank, id)` tomorrow without breaking clients. Same reason JWTs are opaque to non-issuers — implementation detail, not contract.
>
> **Cross-Q²**: A client jumps to page 50 — how would you support that with cursors?
>
> **A**: You don't, directly — cursors are sequential. The honest answer is "Relay pagination doesn't support deep random access; use search/filter to narrow the set, not deep pagination." If product demands it, expose offset pagination as a separate field (e.g., `ordersByPage(page: 50, size: 20)`) with a documented performance cliff, or build a precomputed index of cursor-checkpoints every Nth row. The right product fix is usually "remove the page numbers from the UI" — Twitter, GitHub, Stripe all did this.

### Drill 8 — HTTP-level batching with `@batched`

> **Q**: A page renders 10 widgets, each firing its own GraphQL query. How do you batch them into one HTTP request?
>
> **A**: Use HTTP-layer batching — Apollo Client's `BatchHttpLink` collects queries fired within a tick (~10ms) into a single `POST /graphql` whose body is a JSON array of operations. The server splits the array, runs each operation, returns an array of responses in order. One TCP round-trip, ten resolver trees executed.
>
> **Cross-Q**: How is HTTP batching different from DataLoader batching?
>
> **A**: HTTP batching collapses **client requests** into one network round-trip — purely a transport optimization, no DB savings. DataLoader collapses **resolver-level fetches** within one operation into one DB call. They're orthogonal: HTTP batching saves round-trips when one *page* fires many queries; DataLoader saves DB load when one *query* fans out to many parents. Use both — HTTP batch the 10 widget queries, then each query DataLoader-batches its nested resolvers.
>
> **Cross-Q²**: What's the failure-isolation risk of HTTP batching?
>
> **A**: One slow operation in the batch stalls the whole HTTP response — all 10 widgets wait on the slowest. The server has to wait for every operation to complete before returning the array. Mitigation: cap the batch size, set a per-operation timeout that doesn't block the array, or use **`@defer`/`@stream`** directives that let the server start streaming partial results (multipart response) so fast queries don't pay the slow query's tax.

### Drill 9 — Error model (partial success)

> **Q**: A query selects `order` and `recommendations` — `order` succeeds, `recommendations` resolver throws. What does the response look like?
>
> **A**: HTTP 200 with both `data` and `errors`. `data.order` populated, `data.recommendations` is `null`, and `errors` is an array describing what failed and where (`path: ["recommendations"]`). The client gets a usable partial result *and* knows which fields failed. This is GraphQL's "partial success" model — a single response can mix success and failure per field.
>
> **Cross-Q**: How does nullability interact with errors?
>
> **A**: If the failed field is **nullable**, the null bubbles up to that field only and the rest of the response is intact. If it's **non-null** (`recommendations: [Recommendation!]!`), the null can't legally fill the slot — the error bubbles up to the **nearest nullable ancestor** and nullifies it. Worst case: every field on the path is non-null up to the root → the entire `data` becomes `null`. This is why field-by-field nullability is a critical schema design decision — making everything `!` for cleanliness causes one failed leaf to nuke the whole response.
>
> **Cross-Q²**: HTTP middleware retries on non-2xx. How does that interact with GraphQL's 200-on-error model?
>
> **A**: Badly, if the middleware is REST-shaped. A GraphQL response with `errors` is HTTP 200 — retry middleware sees "success" and doesn't retry, even if the failure is transient. Conversely, replaying a 200 partial-success response replays the success side too, potentially double-billing for mutations. Fix: GraphQL-aware retry logic that inspects `body.errors[].extensions.code` to decide. Apollo Client's error link does this; raw `fetch()` callers must do it manually.

### Drill 10 — Why caching GraphQL is hard

> **Q**: HTTP caching is mature and free. Why is it hard to apply to GraphQL?
>
> **A**: HTTP caches key on URL + method. GraphQL is `POST /graphql` with the query in the body — every distinct query is the same URL but different content. HTTP caches don't read POST bodies. Even if they did, hashing a query body changes with every whitespace tweak. So out-of-the-box HTTP caching does nothing for GraphQL.
>
> **Cross-Q**: What can't HTTP caching do that resolver-layer or client-layer caching can?
>
> **A**: HTTP caches treat responses as opaque blobs; they can't invalidate by entity. If a `Customer` is updated, you must invalidate every cached response that mentioned that customer — impossible by URL alone. **Resolver-layer cache** (Redis keyed by resolver args) can invalidate by entity ID. **Client-layer cache** (Apollo, Relay) normalizes responses by `__typename:id`, so a single `Customer:42` update propagates to every screen showing that customer. HTTP caching can do "this URL is fresh for N seconds"; only entity-aware caches can do "this customer changed, invalidate everywhere."
>
> **Cross-Q²**: A team wants a CDN to cache GraphQL responses anyway. What's the path?
>
> **A**: (1) Persisted queries flipped to GET — URL becomes the hash + variables, CDN caches it. (2) `@cacheControl(maxAge: N)` directives on fields, with HotChocolate's response cache plugin emitting `Cache-Control` headers — but only for queries where every selected field has a `maxAge`. (3) Vary the cache key by auth header so private data doesn't leak across users. The whole flow only works for **public, infrequently-changing** data — personalized responses or post-mutation data fall through to origin every time. CDN caching works in narrow slices, not broadly.

### Drill 11 — HotChocolate vs GraphQL.NET

> **Q**: When would you pick HotChocolate over GraphQL.NET (or vice versa)?
>
> **A**: **HotChocolate** is the dominant .NET GraphQL server in 2026 — code-first with attribute-driven schemas, built-in DataLoader, `[UseProjection]` for EF integration, federation support, the Nitro IDE (renamed from Banana Cake Pop). Use it for new projects. **GraphQL.NET** is older, more schema-first oriented, still maintained but less feature-rich; the only reason to choose it is if you're maintaining an existing GraphQL.NET service or you need its specific schema-first ergonomics.
>
> **Cross-Q**: HotChocolate's `[UseProjection]` is impressive. Where does it stop working?
>
> **A**: Non-EF resolvers (REST-backed types, computed fields, gRPC sources) — projection only works on `IQueryable<T>` returned from EF. Custom resolvers that don't return `IQueryable` fall back to in-memory execution after the projection point. Also breaks with complex authorization that needs row-level filtering applied after EF translation — the projection runs at SQL level before C# auth filters can rule out rows. You then either pre-filter via `Where`, or accept that some authz happens post-projection.
>
> **Cross-Q²**: Nitro is shipped with HotChocolate. Should you expose it in production?
>
> **A**: No. Same logic as exposing Swagger UI in production — fingerprints the schema for attackers, surfaces internal types, makes DoS easier (point-and-click query crafting). Expose it in dev/staging behind auth, disable in prod via `app.MapGraphQL().WithOptions(new GraphQLServerOptions { Tool = { Enable = !env.IsProduction() } })`. The introspection endpoint should also be disabled or auth-gated in production unless the schema is intentionally public (GitHub, Shopify).

### Drill 12 — Subscription transports

> **Q**: GraphQL subscriptions over WebSocket vs SSE — when each?
>
> **A**: **WebSocket** is the historical default — full duplex, low overhead post-handshake, multiple subscriptions multiplexed over one connection (over the `graphql-transport-ws` protocol, implemented by the `graphql-ws` library, or the legacy protocol from the `subscriptions-transport-ws` library). **SSE** is the rising alternative — simpler (just HTTP), works through restrictive proxies that block WS, browser-native auto-reconnect. WS for chat-like high-frequency scenarios; SSE for notifications, dashboard updates, LLM-style token streaming.
>
> **Cross-Q**: Why does the GraphQL spec not mandate a transport for subscriptions?
>
> **A**: The spec defines the operation semantics (one subscription = stream of payloads) but stays transport-agnostic — same way it doesn't mandate JSON or HTTP for queries. This lets the ecosystem pick the right transport for each context: WS in browsers with libraries, SSE for proxy-hostile networks, even MQTT for IoT-grade. The downside is **client/server transport handshake confusion** — clients must agree with servers on the WebSocket subprotocol: `graphql-transport-ws`, the modern one, implemented by the `graphql-ws` library, versus the legacy subprotocol — which is itself named `graphql-ws` and is implemented by the `subscriptions-transport-ws` library. The names cross over, which is why mismatched libraries fail with cryptic errors.
>
> **Cross-Q²**: A subscription server hits 10K concurrent connections and CPU saturates. What's the bottleneck?
>
> **A**: Almost always **per-subscriber serialization**. Each emit on a topic with N subscribers serializes N times. Same fix as the WebSocket walkthrough: serialize once into a `ReadOnlyMemory<byte>`, fan out to each subscriber's bounded channel, each connection's write loop just sends the pre-serialized bytes. Backplane (Redis pub/sub for SignalR-style, NATS for graph-friendly) handles cross-pod fan-out so each pod only fans out to its locally-connected clients.

### Drill 13 — Schema-first vs code-first in HotChocolate

> **Q**: HotChocolate supports both schema-first (SDL) and code-first (attributes). When each?
>
> **A**: **Code-first** is HotChocolate's default and recommended path in 2026 — C# attributes (`[Query]`, `[UsePaging]`, `[UseFiltering]`) drive the schema; refactoring tools work; IDE autocomplete; impossible to drift from C# types. **Schema-first** is useful when (1) the schema is owned by a contracts team separate from the implementer (mirror of OpenAPI-first), (2) you're porting an existing SDL from another stack, (3) the schema is the source of truth for cross-language consumers.
>
> **Cross-Q**: What's the downside of code-first?
>
> **A**: Schema becomes a side-effect of implementation — easy to accidentally break consumers with a refactor. Mitigation: snapshot the generated SDL into version control (`schema.graphql`), diff it in CI, fail the build on breaking changes. HotChocolate has `dotnet-graphql schema export` for this. The schema-first equivalent (SDL in repo, codegen produces stubs) gets this for free at the cost of the codegen step.
>
> **Cross-Q²**: Can you mix the two — schema-first base with code-first extensions?
>
> **A**: Yes. HotChocolate allows merging — define base types in SDL, extend them with C# resolvers via `descriptor.Extend()`. Useful when the contract is fixed (e.g., federated subgraph schemas mandated by gateway) but you want the resolver code to live in idiomatic C#. The risk is fragmentation — split definitions across SDL and C# make it harder to reason about which fields exist. Pick one as primary and use the other only at clear boundaries.

### Drill 14 — Authorization (resolver-level vs schema-level)

> **Q**: Where do you put authorization in a GraphQL server — resolvers or schema?
>
> **A**: **Both layers, intentionally.** Coarse-grained authz (this user can reach the orders mutation at all) at the schema level via `[Authorize(Roles = "...")]` attributes on type/field. Fine-grained authz (this user can only see their own orders, this admin can see all) inside resolvers using the `ClaimsPrincipal` and the query arguments. Schema-level rejects early at the gateway; resolver-level enforces row-level rules.
>
> **Cross-Q**: A resolver authz check is "user can read this Order if user.id == order.customerId" — where does the check go and why?
>
> **A**: Inside the resolver, after the data is loaded enough to know `order.customerId`. Schema-level can't do it (doesn't have access to row data). DataLoader-batched loads complicate it — the DataLoader fetches all keys at once; you must check ownership for each returned row before exposing to the resolver. Pattern: DataLoader returns the row, resolver compares `principal.UserId` to `row.CustomerId`, returns the row or null/throws. This works but is easy to forget — consider an interceptor/middleware (HotChocolate's `IRequestExecutorBuilder.UseField` / Apollo's directives) that applies it automatically based on a `@requires(field: "customerId")` directive.
>
> **Cross-Q²**: How does field-level authz interact with the nullability error model?
>
> **A**: If the field is **nullable**, "denied" returns `null` and `errors[].extensions.code: "FORBIDDEN"` — the client sees a partial response. If **non-null**, the null bubbles to the nearest nullable ancestor (potentially the whole `data` becomes null). For authz-protected fields, lean toward making them **nullable** in the schema so the error stays scoped. The exception: fields that must exist for the response to mean anything — then non-null is correct and the whole query fails, which is the right outcome.

### Drill 15 — GraphQL vs OData

> **Q**: GraphQL and OData both let clients query a typed schema. What's the actual difference?
>
> **A**: **OData** = REST-style URL syntax for querying entity sets (`/Orders?$filter=Status eq 'Pending'&$expand=Customer&$select=Id,Total`). Standard from Microsoft, widely used in enterprise (Dynamics, SAP). **GraphQL** = single endpoint, JSON query language in the body, ecosystem-driven, type system designed for graph traversal. OData is more aligned with relational/CRUD; GraphQL is more aligned with arbitrary graph shapes (BFF aggregation, multi-source).
>
> **Cross-Q**: Which has better tooling for .NET teams in 2026?
>
> **A**: OData has deeper Microsoft-stack tooling (`Microsoft.AspNetCore.OData` package, automatic mapping from EF Core, `$filter` translated to LINQ via expression trees, no need to write resolvers). GraphQL has broader ecosystem tooling (Apollo, HotChocolate, codegen for TS/Swift/Kotlin clients). For a .NET-only API consumed by .NET clients, OData often wins on cost. For an API consumed by web/mobile teams using JS/TS, GraphQL wins because the client tooling is dominant there.
>
> **Cross-Q²**: When would you genuinely combine both?
>
> **A**: Almost never in one service. The legitimate case is a **gateway pattern**: external API surface is GraphQL (consumer-friendly), internal services expose OData (admin/analytics-friendly, EF-friendly). The GraphQL gateway calls OData internally because OData's `$filter`/`$expand` translates straight to EF — saves writing resolvers for every internal entity. Don't expose both protocols on the same service; pick one for each layer and bridge between layers.

</details>

## Cheat Sheet

- **Single endpoint** `POST /graphql`; client picks shape via the query, not the URL.
- **Three operation types**: query (read), mutation (write, serial), subscription (WebSocket stream).
- **N+1 = the trap** — a parent list with a nested resolver triggers per-item DB calls; **DataLoader** batches.
- **Projections** push the GraphQL selection into one EF Core `Include`/`Select` — no N+1 by construction.
- **HotChocolate** is the dominant .NET GraphQL server; Nitro (ex-Banana Cake Pop) ships as the IDE.
- **No versioning** — schema evolves additively; `@deprecated(reason: "...")` on retired fields.
- **Field-level authz** in resolvers — different fields on the same type can have different permissions.
- **Persisted queries**: client sends a hash + variables; server runs the registered query; defeats DoS.
- **Errors live in the `errors` array**, not HTTP status — most servers return `200` even on partial failure.
- **Query complexity / max depth** caps prevent malicious nested queries from exhausting the DB.

## Walkthrough — N+1 takes down the dashboard

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: New "Account Dashboard" feature ships; first hour, p99 jumps from 80ms to 4 seconds and DB CPU pegs at 100%. Rolling back fixes it. Engineers blame "the new ORM," but the change was a single GraphQL field addition.

**Diagnosis**: Open Nitro / Apollo GraphOS and run the dashboard query against staging with `tracing` extension enabled. The `account.recentOrders` resolver returns 50 orders in 12ms. Each order has `customer { name }` and `shippingAddress { city }` — those resolvers fire 50 + 50 = 100 times. Open SQL Server Profiler / `dotnet-trace`: 101 SELECT statements per request, one for orders + 50 customers + 50 addresses. Classic N+1. The PR added the nested resolvers without a DataLoader.

**Fix**: Add a `BatchDataLoader<TKey, T>` per child relationship:

```csharp
public class CustomerByIdDataLoader(
    ICustomerRepository repo, IBatchScheduler scheduler, DataLoaderOptions options)
    : BatchDataLoader<int, Customer>(scheduler, options)
{
    protected override async Task<IReadOnlyDictionary<int, Customer>> LoadBatchAsync(
        IReadOnlyList<int> ids, CancellationToken ct)
        => (await repo.GetByIdsAsync(ids, ct)).ToDictionary(c => c.Id);
}

public Task<Customer> GetCustomer([Parent] Order order, CustomerByIdDataLoader loader)
    => loader.LoadAsync(order.CustomerId);
```

For EF-backed types where the selection maps cleanly, switch to `[UseProjection]` so HotChocolate folds the GraphQL selection into a single SQL `JOIN`. Then revisit the cost limits (`ModifyCostOptions`) so future regressions trip a 400 instead of a stampede.

**Why it works**: DataLoader collects all `LoadAsync(id)` calls within the same execution tick, fires one `WHERE Id IN (10, 17, 22, ...)` query, distributes results to the waiting resolvers. 101 queries collapse to 3 (orders + customers-batch + addresses-batch). Latency drops to ~30ms; DB CPU normalizes.

</details>

## Self-test

<details>
<summary>1. A REST team migrates to GraphQL and immediately misses HTTP caching. What changed?</summary>

REST URLs `/orders/42` are stable cache keys; HTTP caches (browsers, CDNs, proxies) work out of the box. GraphQL uses `POST /graphql` with the query in the body — every distinct query body is a different "resource," and POSTs aren't cached at the HTTP layer at all. Workarounds: (a) persisted queries — server registers known queries by hash, client sends hash via GET, response becomes cacheable; (b) Apollo Cache / Relay client-side cache; (c) at the resolver layer, cache the data sources themselves. The HTTP-cache loss is real and a strong reason REST still wins for high-cache-ratio public APIs.
</details>

<details>
<summary>2. Why are mutations executed serially within a single request, but queries in parallel?</summary>

Queries are read-only and idempotent — running 5 query roots in parallel is safe and faster. Mutations cause state changes; the spec mandates serial execution because clients commonly depend on ordering ("create user, then update profile, then send invite"). If they ran in parallel, the second mutation might race the first's writes. Serial mutations let clients chain side effects predictably without coordinating across endpoints.
</details>

<details>
<summary>3. A client sends `query { posts { author { posts { author { posts { ... } } } } } }`. What server-side defenses kick in?</summary>

(a) **Max depth** — set in HotChocolate via `AddMaxExecutionDepthRule(N)`; rejects queries deeper than N levels with 400. (b) **Query complexity** — assign cost weights per field (lists multiplied by limit), reject queries above a threshold. (c) **Persisted queries** — only pre-registered query hashes accepted in production; arbitrary queries blocked. (d) **Rate limit by query cost** — instead of one limit per request, multiply by computed complexity. Without these, malicious or buggy clients trivially DoS the database.
</details>

<details>
<summary>4. Compare DataLoader to HotChocolate's `[UseProjection]`. When does each fit?</summary>

DataLoader works for any data source — EF Core, REST APIs, gRPC, Redis — by batching key lookups within a tick. Use it when nested resolvers fan out to multiple sources or when the parent type isn't an EF entity. `[UseProjection]` only works for `IQueryable<T>` (EF Core); it inspects the GraphQL selection and folds it into a single SQL query with the right `Include` and `Select`, so even nested traversal becomes one round-trip. Use projection when the entire subtree is EF-backed; DataLoader for cross-source aggregation. They compose: project the EF subtree, DataLoader the cross-cutting fields.
</details>

<details>
<summary>5. Why do GraphQL responses usually return HTTP 200 even on errors, and what's the consumer-side impact?</summary>

The spec separates transport-level errors (HTTP 4xx/5xx for parse failure, malformed JSON, transport faults) from *execution* errors (a resolver threw, a field couldn't be computed) — the latter live in the `errors` array of the JSON body alongside `data`. A response can be "partial success": some fields resolved, others errored. HTTP 200 makes the response body authoritative, so middleware that retries on non-2xx doesn't double-charge for partial successes. Consumer impact: code that checks `response.ok` is wrong for GraphQL; you must inspect `body.errors` and decide per-error whether to retry, surface, or ignore.
</details>

## Cross-references

- [REST & Web API](./01-rest-and-web-api.md) — REST is the default for many cases.
- [API Versioning](./05-api-versioning.md) — versioning strategies and how GraphQL deviates.
- [API Documentation](./07-api-documentation.md) — GraphQL schema is itself documentation; introspection is built in.
- [Authentication & Authorization](./02-authentication-and-authorization.md) — field-level auth in GraphQL.
- [WebSockets](./10-websockets.md) — transport for subscriptions.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- HotChocolate — [chillicream.com/docs/hotchocolate](https://chillicream.com/docs/hotchocolate) — the dominant .NET GraphQL library.
- GraphQL official spec — [spec.graphql.org](https://spec.graphql.org/).
- *Production Ready GraphQL* by Marc-André Giroux (2020) — practical, includes performance and security.
- Apollo GraphOS docs — language-agnostic but excellent for design patterns.
- GitHub GraphQL API — [docs.github.com/en/graphql](https://docs.github.com/en/graphql) — large-scale public GraphQL example.

<!-- nav-footer-start -->

---

[← Previous: API Documentation](07-api-documentation.md) · [↑ Back to top](#graphql) · [Next: Webhooks →](09-webhooks.md)

<!-- nav-footer-end -->

</details>
