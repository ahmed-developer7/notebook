# HttpClient & Resilience (Polly)

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 6 — API Mastery | 2026-08-10 |

> 📘 **Single source of truth**: this is the one file for HttpClient lifecycle, `IHttpClientFactory`, and Polly v8 resilience. The former duplicate under `02-dotnet-runtime/` has been merged into this page and retired.

> **Difficulty:** Intermediate to Advanced | **Reading Time:** ~50 min | **Baseline:** .NET 10 (2025-11) / `Microsoft.Extensions.Http.Resilience` 10.x

---

## Why It Matters

Almost every modern .NET service is also an *HTTP client*. It calls a payment gateway, an identity provider, an internal microservice, an LLM, a third-party API. The default reflex — `new HttpClient()` per request — was a footgun that brought down production systems for the better part of a decade. The fixes are well-known now (`IHttpClientFactory`, `SocketsHttpHandler` pool tuning), but the *resilience* layer on top is where 2026 .NET shines: Polly v8's `ResiliencePipeline` + `Microsoft.Extensions.Http.Resilience` lets you express retry, circuit breaker, timeout, hedging, and fallback in a few declarative lines.

This guide treats HTTP outbound calls as a system: the lifecycle pitfalls of `HttpClient`, the factory pattern, the modern Polly v8 API, the .NET 8+ standard pipeline, the `DelegatingHandler` chain, and `SocketsHttpHandler` tuning. Each section comes with the trade-offs you actually hit in production.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Real-World Analogy](#real-world-analogy)
3. [HttpClient Lifecycle Pitfalls](#httpclient-lifecycle-pitfalls)
4. [IHttpClientFactory](#ihttpclientfactory) — including [BaseAddress and Relative URIs](#baseaddress-and-relative-uris)
5. [Typed, Named, and Basic Clients](#typed-named-and-basic-clients)
6. [Polly v8 ResiliencePipeline](#polly-v8-resiliencepipeline)
7. [Strategies in Detail](#strategies-in-detail) — including [Transient Fault Classification](#transient-fault-classification)
8. [Standard Resilience Pipeline (.NET 8+)](#standard-resilience-pipeline-net-8)
9. [DelegatingHandler Chain](#delegatinghandler-chain)
10. [SocketsHttpHandler Tuning](#socketshttphandler-tuning)
11. [Testing HttpClient](#testing-httpclient)
12. [Common Pitfalls](#common-pitfalls)
13. [Best Practices](#best-practices)
14. [Real-World Scenarios](#real-world-scenarios)
15. [Interview-Ready Summary](#interview-ready-summary)
16. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
17. [Cheat Sheet](#cheat-sheet)
18. [Walkthrough — Diagnosing Socket Exhaustion in Production](#walkthrough--diagnosing-socket-exhaustion-in-production)
19. [Self-Test](#self-test)
20. [Cross-References](#cross-references)
21. [Sources](#sources)

---

## Introduction

### The HttpClient Story

`HttpClient` is the .NET API for making HTTP requests. Underneath, it owns a `HttpMessageHandler` chain that ultimately reaches `SocketsHttpHandler` — the part that actually opens TCP/TLS connections. The handler is *expensive*; it caches DNS lookups, pools connections, and holds state. Creating one per request flushes that pool, leaks sockets into `TIME_WAIT`, and exhausts ephemeral ports under load.

Microsoft frames the choice as exactly two supported lifetime strategies, and everything else is a bug:

- **Long-lived client with `PooledConnectionLifetime` set.** A `static`/singleton `HttpClient` built over a `SocketsHttpHandler` whose `PooledConnectionLifetime` you configure. No socket churn, and connections are recycled so DNS is re-resolved.
- **Short-lived clients from `IHttpClientFactory`.** The factory pools and rotates `HttpMessageHandler` instances; each `CreateClient()` is a cheap wrapper. You additionally get named/typed configuration, DI, logging, and Polly composition.

The broken third option — `new HttpClient()` per request, or a static client with the handler left at its defaults — is what interviewers are probing for.

### Without vs With

```
WITHOUT IHttpClientFactory — new HttpClient per call
====================================================
for (var i = 0; i < 1000; i++)
{
    using var http = new HttpClient();   // new handler => new connection pool
    await http.GetAsync(url);
}

  TCP connections opened: one per iteration (no pool is shared)
  Socket state after close: TIME_WAIT, held by the KERNEL, not by .NET
  Ephemeral ports:        a finite per-machine pool (see below)
  Symptom:                SocketException: Only one usage of each
                          socket address is normally permitted

WITH IHttpClientFactory — handler pool reused
=============================================
for (var i = 0; i < 1000; i++)
{
    var http = factory.CreateClient("api");  // cheap wrapper, pooled handler
    await http.GetAsync(url);
}

  TCP connections opened: a handful, pooled and reused per origin
  DNS refresh:            handler rotates every HandlerLifetime (default 2 min)
  Symptom:                none — steady throughput
```

**The two numbers behind this, with sources — quote these, not folklore:**

| Quantity | Value | Source |
|---|---|---|
| Windows default dynamic (ephemeral) port range | 49152–65535, i.e. 16,384 ports | Microsoft, *The default dynamic port range for TCP/IP has changed in Windows Vista and Windows Server 2008* |
| Windows TIME_WAIT hold time | the `TcpTimedWaitDelay` registry parameter; Microsoft documents a default of 240 s, reducible to 30 s | Microsoft, *Settings that can be modified to improve network performance* |
| Why the socket is held at all | TCP TIME-WAIT is `2 × MSL`, so late-arriving segments from the closed connection can't be mistaken for a new one | RFC 9293 §3.3.2 (cited by Microsoft's own HttpClient guidelines) |

Linux and container images use different ranges and delays — check `sysctl net.ipv4.ip_local_port_range` on the actual host rather than quoting a Windows number at a Linux problem.

### Why It Matters in 2026

- Microservices and SaaS integrations multiply the number of outbound HTTP dependencies in any nontrivial app.
- Polly v8's `ResiliencePipeline` replaced the v7 policy classes with a builder-based API that is allocation-free on the success path. **Polly's release train is independent of .NET's** — v8 is the current major line and runs the same on .NET 8, 9, and 10. Saying "Polly v8 became stable in .NET 10" is a category error an interviewer who knows Polly will catch.
- `Microsoft.Extensions.Http.Resilience` (currently the 10.x line) ships a "standard pipeline" of five strategies with opinionated defaults, plus a standard hedging handler, in one line.
- HTTP/2 and HTTP/3 multiplexing change how connections behave — pool tuning matters more than ever.

---

## Real-World Analogy

```
HTTPCLIENT — The Pizza Driver
=============================
WITHOUT FACTORY:
  Every order, you HIRE a new driver, give them a car,
  fire them after one delivery, and the car sits in the parking lot
  for an hour before the city tow company removes it.
    -> Parking lot fills up. New drivers can't park. Orders fail.

WITH FACTORY:
  You keep a roster of drivers and a pool of cars.
  Each order grabs an available driver+car.
  The car returns to the pool when done.
  Cars are rotated every shift to refresh them.
    -> Steady throughput. No parking-lot crisis.

RESILIENCE — The Driver's Playbook
==================================
  Customer doesn't answer first ring (transient)        -> retry 3 times
  Whole apartment building is unreachable (broken)      -> stop trying for 1 min
  Order taking too long (slow)                          -> timeout, refund, move on
  Plan A's delivery fails (failure)                     -> dispatch from Plan B store
```

---

## HttpClient Lifecycle Pitfalls

### The Two Wrong Answers

```
+--------------------+--------------------+--------------------------+
| Approach           | Why people try it  | Why it breaks            |
+--------------------+--------------------+--------------------------+
| new HttpClient()   | "It's IDisposable, | Every instance carries   |
| per request        | so dispose it"     | its own connection pool. |
|                    |                    | Sockets pile up in       |
|                    |                    | TIME_WAIT; ports exhaust.|
+--------------------+--------------------+--------------------------+
| static HttpClient  | "Reuse handler,    | The handler NEVER closes |
| with the handler   | one per app"       | pooled connections, so   |
| left at defaults   |                    | DNS is never re-resolved.|
+--------------------+--------------------+--------------------------+
```

> ⚠️ **Say "static client with an untuned handler", not "static client".** A `static`/singleton `HttpClient` is one of the two lifetime strategies Microsoft explicitly recommends — *provided* you set `PooledConnectionLifetime` on its `SocketsHttpHandler`. `PooledConnectionLifetime` defaults to `Timeout.InfiniteTimeSpan`, which is exactly why the untuned static client pins one DNS resolution for the life of the process. Calling the static client categorically wrong is a mis-statement an interviewer can correct you on.

### What `IHttpClientFactory` Solves

```
+--------------------------------------------------------+
|  IHttpClientFactory Properties                          |
+--------------------------------------------------------+
|  ✓ Pools and reuses HttpMessageHandler instances        |
|  ✓ Rotates handlers every HandlerLifetime (default 2m) |
|  ✓ DNS changes picked up at rotation                    |
|  ✓ Polly handlers attach via fluent API                 |
|  ✓ Per-named-client configuration (BaseAddress, etc.)   |
|  ✓ Each CreateClient() returns a cheap wrapper          |
|  ✗ Does NOT set PooledConnectionLifetime — it rotates  |
|    the whole handler instead. Two different knobs.      |
|  ✗ Factory-created clients must stay SHORT-lived; a    |
|    typed client captured in a singleton defeats        |
|    rotation and reintroduces stale DNS.                |
|  ✗ Handler pooling shares CookieContainer — avoid the  |
|    factory if the app depends on cookies.              |
+--------------------------------------------------------+
```

```
LIFECYCLE
+-----------+   create   +---------+   reuse for    +---------+
| factory   |----------->| handler |--------------->| client1 |
| .CreateClient("api")   |  pool   |    handler     | client2 |
+-----------+            +---------+    instance    +---------+
                              |
                              | (every HandlerLifetime)
                              v
                       handler is "expired"
                              |
                              v
                  no longer handed to new clients
                              |
                              v
                  disposed when ref count = 0
```

---

## IHttpClientFactory

### Registration

```csharp
// 1) Basic — get a default client
builder.Services.AddHttpClient();

// 2) Named — addressable by string
builder.Services.AddHttpClient("payment", c =>
{
    c.BaseAddress = new Uri("https://payment.example.com/");
    c.Timeout = TimeSpan.FromSeconds(30);
    c.DefaultRequestHeaders.UserAgent.ParseAdd("MyApp/1.0");
});

// 3) Typed — strongly typed wrapper class (preferred)
builder.Services.AddHttpClient<PaymentClient>(c =>
{
    c.BaseAddress = new Uri("https://payment.example.com/");
});
```

### Resolution

```csharp
// Basic
public class A(HttpClient http) { ... }                 // requires AddHttpClient()

// Named
public class B(IHttpClientFactory f)
{
    public Task DoIt() => f.CreateClient("payment").GetAsync(...);
}

// Typed — gets a configured HttpClient via DI
public class PaymentClient(HttpClient http) { ... }
```

### BaseAddress and Relative URIs

One of the highest-frequency real bugs in this whole topic, and a favourite interview question, because the failure is *silent*: the request succeeds, it just goes to the wrong URL.

```csharp
// Registration
builder.Services.AddHttpClient<PaymentClient>(c =>
    c.BaseAddress = new Uri("https://payment.example.com/v2/"));

// Inside PaymentClient:

// CORRECT — trailing slash on BaseAddress, no leading slash on the path
await http.GetAsync("charges");    // -> https://payment.example.com/v2/charges

// WRONG — BaseAddress without a trailing slash
//   c.BaseAddress = new Uri("https://payment.example.com/v2");
await http.GetAsync("charges");    // -> https://payment.example.com/charges   (v2 dropped)

// WRONG — leading slash on the relative URI
await http.GetAsync("/charges");   // -> https://payment.example.com/charges   (v2 dropped)
```

**Why**, in one sentence you can say out loud: `HttpClient` resolves the relative reference against `BaseAddress` using the RFC 3986 §5.3 merge rule, which keeps everything in the base path *up to and including the last `/`* and discards the rest — so a base of `/v2` contributes only `/`, and a relative reference that itself starts with `/` is an absolute-path reference that replaces the base path entirely.

```
+-----------------------------------------------------+
|  BASEADDRESS RULES                                  |
+-----------------------------------------------------+
|  ✓ BaseAddress ALWAYS ends with '/'                |
|  ✓ Relative paths NEVER start with '/'             |
|  ✓ Passing an absolute Uri ignores BaseAddress     |
|    entirely — the escape hatch for one-off hosts    |
|  ✗ A missing slash fails silently, not loudly      |
+-----------------------------------------------------+
```

---

## Typed, Named, and Basic Clients

```
+-------------+--------------------------------------+----------------+
| Style       | When to use                          | Refactor cost  |
+-------------+--------------------------------------+----------------+
| Basic       | One-off, no per-endpoint config      | Highest later  |
| Named       | Multiple clients, dynamic selection  | Medium         |
| Typed       | A class encapsulates one API surface | Lowest — best  |
+-------------+--------------------------------------+----------------+
```

### Typed Client (the recommended baseline)

```csharp
public class PaymentClient(HttpClient http)
{
    public async Task<PaymentResult> ChargeAsync(decimal amount, CancellationToken ct)
    {
        var response = await http.PostAsJsonAsync("charge", new { amount }, ct);
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<PaymentResult>(ct))!;
    }
}

builder.Services.AddHttpClient<PaymentClient>(c =>
    c.BaseAddress = new Uri("https://payment.example.com/"));
```

### Consuming a Typed Client End to End

Registration is the half everyone shows. The half that gets asked about is *consumption* — the caller depends on the typed class, never on `IHttpClientFactory` or `HttpClient`.

```csharp
public class PaymentClient(HttpClient http)
{
    public async Task<PaymentResult> ChargeAsync(ChargeRequest req, CancellationToken ct = default)
    {
        var response = await http.PostAsJsonAsync("charge", req, ct);
        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<PaymentResult>(ct))!;
    }

    public async Task<bool> RefundAsync(string chargeId, CancellationToken ct = default)
    {
        var response = await http.PostAsJsonAsync($"charge/{chargeId}/refund", new { }, ct);
        return response.IsSuccessStatusCode;
    }
}

// Registration — note the trailing slash on the versioned base path
builder.Services.AddHttpClient<PaymentClient>(c =>
{
    c.BaseAddress = new Uri("https://payment.example.com/v2/");
    c.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
})
.AddStandardResilienceHandler();

// Consumption — inject PaymentClient, not IHttpClientFactory
public class OrderService(PaymentClient payments)
{
    public async Task<Order> CreateAsync(OrderRequest req, CancellationToken ct)
    {
        var charge = await payments.ChargeAsync(new ChargeRequest(req.Total), ct);
        return new Order(req, charge.Id);
    }
}
```

> ⚠️ `OrderService` here must not be a singleton. Typed clients are registered as **transient** and are meant to be short-lived; capturing one in a singleton pins its handler and defeats rotation — the same stale-DNS failure as the untuned static client. If you need HTTP from a singleton, inject `IHttpClientFactory` and use a named client, or configure `PooledConnectionLifetime` on the primary handler.

### Named Client (when you need to pick at runtime)

```csharp
builder.Services.AddHttpClient("primary",   c => c.BaseAddress = new(primaryUrl));
builder.Services.AddHttpClient("secondary", c => c.BaseAddress = new(secondaryUrl));

public class FailoverFetcher(IHttpClientFactory factory)
{
    public Task<HttpResponseMessage> Get(string region, string path, CancellationToken ct)
        => factory.CreateClient(region == "us" ? "primary" : "secondary").GetAsync(path, ct);
}
```

### Properties

```
+-----------------------------------------------------+
|  TYPED CLIENT                                       |
+-----------------------------------------------------+
|  ✓ Encapsulates one API surface in one class       |
|  ✓ Refactor-friendly — call sites are typed        |
|  ✓ Polly handlers attach to the registration       |
|  ✓ DI provides HttpClient, no factory lookups      |
|  ✗ One typed client = one HttpClient configuration |
|  ✗ For dynamic selection, use a named client       |
+-----------------------------------------------------+
```

---

## Polly v8 ResiliencePipeline

Polly v8 (the `Polly.Core` rewrite) replaced the v7 policy classes with a builder that produces a `ResiliencePipeline<T>`. It is allocation-free on the success path, telemetry-aware, and composable. Polly versions independently of .NET — v8 is not "a .NET 10 feature", it is simply the current major line of the library, and it runs the same on .NET 8, 9, and 10.

### Anatomy

```
+-----------------------------------------------------+
|  ResiliencePipelineBuilder<T>                       |
+-----------------------------------------------------+
|  .AddRetry(opts)                                    |
|  .AddCircuitBreaker(opts)                           |
|  .AddTimeout(TimeSpan)                              |
|  .AddFallback(opts)     (Polly.Core.Fallback)       |
|  .AddHedging(opts)      (Polly.Core.Hedging)        |
|  .AddRateLimiter(opts)                              |
|  .Build()                                           |
+-----------------------------------------------------+
```

### Standalone (not via HTTP factory)

```csharp
var pipeline = new ResiliencePipelineBuilder<HttpResponseMessage>()
    .AddRetry(new RetryStrategyOptions<HttpResponseMessage>
    {
        ShouldHandle = new PredicateBuilder<HttpResponseMessage>()
            .Handle<HttpRequestException>()
            .HandleResult(r => (int)r.StatusCode >= 500),
        MaxRetryAttempts = 3,
        Delay = TimeSpan.FromSeconds(1),   // base delay; the shipped standard handler uses 2s
        BackoffType = DelayBackoffType.Exponential,
        UseJitter = true
    })
    .AddCircuitBreaker(new CircuitBreakerStrategyOptions<HttpResponseMessage>
    {
        FailureRatio = 0.5,
        SamplingDuration = TimeSpan.FromSeconds(30),
        MinimumThroughput = 5,
        BreakDuration = TimeSpan.FromSeconds(15)
    })
    .AddTimeout(TimeSpan.FromSeconds(5))
    .Build();

var response = await pipeline.ExecuteAsync(
    async ct => await http.GetAsync("/things", ct),
    cancellationToken);
```

> 📌 **Builder order = nesting order.** The first strategy you add is the **outermost**; the callback you pass to `ExecuteAsync` is the innermost. In the pipeline above, retry wraps the breaker, which wraps the timeout, which wraps the HTTP call — so the timeout is per-attempt and the breaker is consulted on every attempt.

---

## Strategies in Detail

### Transient Fault Classification

Before you configure a single retry, you have to be able to say *which failures deserve one*. This is the classification the shipped `AddStandardResilienceHandler()` uses — and it is the answer to "which status codes do you retry?", because it is not a matter of taste, it is documented behaviour of the handler you are recommending.

**What the standard handler's retry and circuit breaker both handle** (Microsoft Learn, *Build resilient HTTP apps*):

- HTTP **500 and above** (server errors)
- HTTP **408** Request Timeout
- HTTP **429** Too Many Requests
- the exceptions `HttpRequestException` and Polly's `TimeoutRejectedException`

```csharp
// Retryable — the request may succeed if repeated
HttpStatusCode.RequestTimeout          // 408 — the request took too long
HttpStatusCode.TooManyRequests         // 429 — throttled; honour Retry-After
HttpStatusCode.InternalServerError     // 500 — may be a transient server fault
HttpStatusCode.BadGateway              // 502 — proxy saw a bad upstream response
HttpStatusCode.ServiceUnavailable      // 503 — overloaded or restarting
HttpStatusCode.GatewayTimeout          // 504 — upstream timed out
// HttpRequestException  — connection refused, DNS failure, TLS failure
// TimeoutRejectedException — Polly's own per-attempt timeout fired

// Not retryable — repeating the identical request returns the identical error
HttpStatusCode.BadRequest              // 400 — malformed request; a bug in your code
HttpStatusCode.Unauthorized            // 401 — credential problem, not a blip
HttpStatusCode.Forbidden               // 403 — authorization decision
HttpStatusCode.NotFound                // 404 — the resource is not there
HttpStatusCode.UnprocessableEntity     // 422 — semantic validation failure
// 409 Conflict — depends entirely on the API's semantics; classify it deliberately
```

> ⚠️ **The trap in the middle: 429.** It is a 4xx, so the "never retry 4xx" heuristic wants you to give up — but 429 means *"come back later"*, not *"never"*, and it usually carries a `Retry-After` header. `HttpRetryStrategyOptions.ShouldRetryAfterHeader` makes the retry strategy derive its delay from that header instead of from the backoff curve — and it **defaults to `true`**, so the standard handler already honours `Retry-After` for you. The interview-grade version of this answer is therefore "it's on by default, and you'd only set it to `false` if you had a reason to distrust the server's number", not "remember to switch it on". Never hard-code a delay for 429 when the server told you one.

### Retry

```
+-----------------------------------------------------+
|  RETRY                                              |
+-----------------------------------------------------+
|  ✓ Recovers from TRANSIENT failures                |
|  ✓ Exponential backoff + jitter spreads load       |
|  ✓ ShouldHandle filters errors that deserve retry  |
|  ✗ Retries are EXPENSIVE — multiply call cost      |
|  ✗ Don't retry non-idempotent POSTs blindly        |
|  ✗ Don't retry 4xx — except 408 and 429            |
+-----------------------------------------------------+
```

```csharp
.AddRetry(new HttpRetryStrategyOptions
{
    MaxRetryAttempts = 3,
    Delay = TimeSpan.FromSeconds(1),
    BackoffType = DelayBackoffType.Exponential,
    UseJitter = true,    // CRITICAL when many clients retry simultaneously
    ShouldHandle = new PredicateBuilder<HttpResponseMessage>()
        .Handle<HttpRequestException>()
        .HandleResult(r => r.StatusCode is HttpStatusCode.RequestTimeout        // 408
                                       or HttpStatusCode.TooManyRequests        // 429
                                       or HttpStatusCode.InternalServerError    // 500
                                       or HttpStatusCode.BadGateway             // 502
                                       or HttpStatusCode.ServiceUnavailable     // 503
                                       or HttpStatusCode.GatewayTimeout)        // 504
})
```

> 🚨 **The default that surprises people: the standard handler retries *every* HTTP method, POST included.** Microsoft's docs are explicit — "By default, the standard resilience handler is configured to make retries for all HTTP methods" — and they ship two extension methods to narrow it: `options.Retry.DisableFor(HttpMethod.Post, HttpMethod.Delete)` for a specific list, and `options.Retry.DisableForUnsafeHttpMethods()` for the whole unsafe set (POST, PATCH, PUT, DELETE, CONNECT). If you tell an interviewer "the standard handler only retries idempotent methods", you are wrong; the correct answer is "it retries everything unless you call `DisableForUnsafeHttpMethods()`, which is exactly why duplicate-order bugs show up after someone adds one line of resilience."

```csharp
builder.Services.AddHttpClient<PaymentClient>()
    .AddStandardResilienceHandler(options =>
    {
        options.Retry.DisableForUnsafeHttpMethods();   // POST/PATCH/PUT/DELETE/CONNECT
    });
```

> ⚠️ **"Unsafe" is not the same property as "non-idempotent" — and this is the follow-up question.** `DisableForUnsafeHttpMethods()` switches off retries for POST, PATCH, PUT, DELETE *and* CONNECT, because Microsoft selects on **safety** (read-only semantics, RFC 9110 §9.2.1), not on idempotency. But PUT and DELETE *are* idempotent (§9.2.2) and are usually perfectly safe to retry. So the blanket call is the conservative default, not the precise one: if you want to keep retrying PUT and DELETE while protecting your writes, name the methods yourself with `options.Retry.DisableFor(HttpMethod.Post, HttpMethod.Patch)`. Know which of the two properties you are actually selecting on.

### Circuit Breaker

When the downstream is *clearly* broken, hammering it with retries makes the situation worse and burns your latency budget. The circuit breaker watches a rolling window; once the failure ratio exceeds a threshold, it *opens* — failing fast for a cool-off period — then transitions to *half-open* to probe.

```
CIRCUIT BREAKER STATE MACHINE
=============================

      +-----------+
      |  CLOSED   |   ← all calls pass through
      +-----------+
            |
            |  failure ratio > threshold over window
            v
      +-----------+
      |   OPEN    |   ← every call short-circuits with
      +-----------+      BrokenCircuitException
            |
            |  break duration elapses
            v
      +-----------+
      | HALF-OPEN |   ← ONE probe call allowed
      +-----------+
            |
            |  probe succeeds      probe fails
            v                          v
      +-----------+              +-----------+
      |  CLOSED   |              |   OPEN    |
      +-----------+              +-----------+
```

```csharp
.AddCircuitBreaker(new HttpCircuitBreakerStrategyOptions
{
    FailureRatio = 0.5,
    SamplingDuration = TimeSpan.FromSeconds(30),
    MinimumThroughput = 5,
    BreakDuration = TimeSpan.FromSeconds(15)
})
```

```
+-----------------------------------------------------+
|  CIRCUIT BREAKER                                    |
+-----------------------------------------------------+
|  ✓ Stops cascades — fail fast when downstream dead |
|  ✓ Frees callers' threads/budgets to do other work |
|  ✓ Probes recovery automatically                   |
|  ✗ Per-instance state — N replicas, N breakers     |
|  ✗ Tuning thresholds takes empirical data          |
+-----------------------------------------------------+
```

### Timeout

```csharp
.AddTimeout(TimeSpan.FromSeconds(10))
```

```
+-----------------------------------------------------+
|  TIMEOUT                                            |
+-----------------------------------------------------+
|  ✓ Bounds time spent on a single attempt           |
|  ✓ Cooperates with CancellationToken               |
|  ✓ Two flavors: per-attempt and overall pipeline   |
|  ✗ Useless if downstream ignores cancellation      |
|  ✗ Should be SHORTER than caller's timeout         |
+-----------------------------------------------------+
```

```
TIMEOUT BUDGETS — keep them in order
====================================

     +---- caller (overall pipeline timeout) -----+
     |                                            |
     |   +-- per-attempt timeout (Polly) --+      |
     |   |                                  |      |
     |   |   downstream service timeout    |      |
     |   |                                  |      |
     |   +----------------------------------+      |
     |                                            |
     +--------------------------------------------+

  Inner timeouts must be SHORTER than outer timeouts,
  otherwise the outer timeout never fires meaningfully.
```

#### The Three Timeout Surfaces

There are three separate things called "timeout" here, and confusing them is the single most common way people accidentally disable their own retries.

| Mechanism | Scope | What to do with it |
|---|---|---|
| `HttpClient.Timeout` | The entire `SendAsync`, **including every Polly retry**. Default 100 seconds. | Set to `Timeout.InfiniteTimeSpan` once Polly owns timeouts |
| Polly per-attempt timeout (`AddTimeout`, innermost) | One individual attempt | Bounds a single hang so a retry can actually fire |
| Polly total timeout (`AddTimeout`, outermost) | The whole pipeline, all attempts and backoffs | The operation's hard deadline |

```csharp
// WRONG — HttpClient.Timeout cuts off the whole pipeline, retries included.
client.Timeout = TimeSpan.FromSeconds(5);   // attempt 1 takes 4.9s => retries 2 and 3 never run

// RIGHT — let Polly own both levels
client.Timeout = Timeout.InfiniteTimeSpan;
// ... .AddTimeout(totalDeadline)   outermost
// ... .AddRetry(...)
// ... .AddTimeout(perAttempt)      innermost
```

Polly's timeout cancels co-operatively through the `CancellationToken`, which flows into `HttpClient` and on into the response stream — so it only works if the code below it actually observes the token.

#### Retry Budget Arithmetic

Timeout ordering is not a vibe, it is an inequality you can compute before you ship:

```
((MaxRetryAttempts + 1) × PerAttemptTimeout) + sum(backoffDelays)  <  TotalTimeout
```

> 🚨 **Count the attempts correctly — this is where the arithmetic usually goes wrong.** Polly's `MaxRetryAttempts` is the number of retries *in addition to* the original call. So `MaxRetryAttempts = 3` means **four** attempts and **three** backoff delays, not three and two. Getting this off by one understates your worst case by a whole attempt plus a backoff, which is exactly the margin you thought you had.

Worked example — the shipped `AddStandardResilienceHandler()` defaults, which is the case worth having memorised:

```
MaxRetryAttempts = 3   ->   4 attempts, 3 backoffs

attempts : 4 × 10s  (AttemptTimeout)      = 40s
backoffs : 2s + 4s + 8s  (exp, 2s base)   = 14s
                                           -----
worst case                                 ~54s   (before jitter)

TotalRequestTimeout                         30s   <-- fires first
```

So the standard pipeline's own defaults do **not** fit inside its own total timeout: a maximally unlucky request is cut off by the 30 s total timeout partway through, and the last attempts never run. That is a deliberate design — the total timeout is the hard deadline and the retry count is a best-effort budget inside it — but you should be able to say it out loud, because "does the standard handler always make four attempts?" is a fair cross-question and the answer is "only when they fit in 30 seconds."

To make a budget fit fully, shorten the per-attempt timeout, drop the retry count, or raise the deadline — but do the arithmetic rather than discovering it in an incident.

### Bulkhead / Rate Limiter

The Polly v7 *bulkhead* is now expressed as a rate-limiter strategy backed by a concurrency limiter. It bounds how many concurrent calls can be in flight to a particular dependency, preventing one slow dependency from monopolizing your thread pool.

```csharp
// Simplest correct form: permitLimit 50, queueLimit 0
.AddConcurrencyLimiter(permitLimit: 50, queueLimit: 0)

// Equivalent via the options object, when you also want OnRejected telemetry
.AddRateLimiter(new RateLimiterStrategyOptions
{
    DefaultRateLimiterOptions = new ConcurrencyLimiterOptions
    {
        PermitLimit = 50,
        QueueLimit  = 0
    },
    OnRejected = args =>
    {
        // emit a metric — rejections are a capacity signal, not an error
        return default;
    }
})
```

> ⚠️ **Do not build the limiter inside the `RateLimiter` delegate.** `RateLimiterStrategyOptions.RateLimiter` is invoked *per execution*; constructing a fresh `ConcurrencyLimiter` in it gives every call its own private limiter with all permits free, so nothing is ever limited. Use `DefaultRateLimiterOptions` (or `AddConcurrencyLimiter`) so a single limiter instance is shared, and reach for the `RateLimiter` delegate only when you genuinely need to select among long-lived limiters — for example one per tenant, held in a dictionary.

### Fallback

```csharp
.AddFallback(new FallbackStrategyOptions<HttpResponseMessage>
{
    ShouldHandle = new PredicateBuilder<HttpResponseMessage>()
        .Handle<BrokenCircuitException>(),
    FallbackAction = args => Outcome.FromResultAsValueTask(
        new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(cachedJson, Encoding.UTF8, "application/json")
        })
})
```

```
+-----------------------------------------------------+
|  FALLBACK                                           |
+-----------------------------------------------------+
|  ✓ Returns a degraded but useful response          |
|  ✓ Stops failures from bubbling to the user        |
|  ✓ Often serves a cached or static value           |
|  ✗ Hides systemic problems — alert separately      |
|  ✗ Ensure fallback is genuinely cheaper to compute |
|  ✗ NOT a stage of AddStandardResilienceHandler()   |
|    — you only get it in a hand-built pipeline      |
+-----------------------------------------------------+
```

> 📌 Fallback belongs **outermost** in a hand-built pipeline — it must be able to catch everything inside it (open circuit, exhausted retries, blown total timeout). Adding it first in the builder puts it outermost. Note that this is a convention for pipelines *you* compose; the shipped standard handler has no fallback stage at all.

### Hedging

Hedging makes a *parallel* (or staggered) second attempt before the first one finishes — useful for tail-latency reduction in idempotent reads.

```csharp
.AddHedging(new HedgingStrategyOptions<HttpResponseMessage>
{
    MaxHedgedAttempts = 2,
    Delay = TimeSpan.FromMilliseconds(150),   // fire the second attempt after 150ms
    ActionGenerator = args => () => args.Callback(args.ActionContext)
})
```

**Hedging is not retry, and the distinction is a favourite interview probe:**

| | Retry | Hedging |
|---|---|---|
| Fires | *after* an attempt fails or times out | *before* the first attempt resolves |
| Solves | fault tolerance | tail-latency reduction |
| Steady-state cost | none (only pays on failure) | extra in-flight requests during every hedge window |
| Safe on | anything you have classified as retryable | idempotent operations only |

The cost is real: each hedged attempt is a full additional request to the dependency, so a hedging window that fires often multiplies both your egress and the downstream's load. Hedge cheap idempotent reads where p99 is the problem; do not hedge an expensive query to shave a median.

**Hedging a POST** is only legitimate when the endpoint is idempotent *by contract* — an `Idempotency-Key` header with server-side deduplication. A raw `POST /orders` hedged twice is a double-create with extra steps.

Microsoft also ships `AddStandardHedgingHandler()`, a five-stage pipeline (total timeout → hedging → per-endpoint rate limiter → per-endpoint circuit breaker → per-endpoint attempt timeout) that keeps a pool of circuit breakers keyed by URL authority so unhealthy endpoints aren't hedged against.

### Strategy Comparison

```
+----------------+----------------------------+-------------------+
| Strategy       | Best for                   | Cost              |
+----------------+----------------------------+-------------------+
| Retry          | Transient blips            | Multiplied calls  |
| Circuit Breaker| Sustained downstream fault | Per-instance state|
| Timeout        | Bounded latency budget     | Cancellation only |
| Rate Limiter   | Concurrency caps           | Queue or reject   |
| Fallback       | Graceful degradation       | Stale data risk   |
| Hedging        | Tail latency               | 2x bandwidth peak |
+----------------+----------------------------+-------------------+
```

---

## Standard Resilience Pipeline (.NET 8+)

`Microsoft.Extensions.Http.Resilience` ships a curated default that chains **five** strategies, outermost first: **Rate Limiter → Total Timeout → Retry → Circuit Breaker → Per-Attempt Timeout**.

Two things about that list are worth memorising precisely, because both are commonly mis-stated:

- **There are five stages and fallback is not one of them.** Fallback is something you add yourself in a custom pipeline. If you recite "Fallback → Rate Limiter → …" as the standard order, you have merged a hand-rolled convention into the shipped product.
- **The circuit breaker sits *inside* the retry.** That means the breaker is consulted on every single attempt, not once per retry block — which is what makes it able to cut a retry loop short with `BrokenCircuitException` the moment it opens.

### One-Liner

```csharp
builder.Services.AddHttpClient<PaymentClient>()
                .AddStandardResilienceHandler();
```

### Custom Order

```csharp
builder.Services.AddHttpClient<PaymentClient>()
    .AddResilienceHandler("payment-pipeline", builder =>
    {
        builder.AddRetry(new HttpRetryStrategyOptions
        {
            MaxRetryAttempts = 3,
            Delay = TimeSpan.FromSeconds(1),
            BackoffType = DelayBackoffType.Exponential,
            UseJitter = true,
            ShouldHandle = new PredicateBuilder<HttpResponseMessage>()
                .HandleResult(r => r.StatusCode == HttpStatusCode.ServiceUnavailable)
                .Handle<HttpRequestException>()
        });

        builder.AddCircuitBreaker(new HttpCircuitBreakerStrategyOptions
        {
            FailureRatio = 0.5,
            SamplingDuration = TimeSpan.FromSeconds(30),
            MinimumThroughput = 5,
            BreakDuration = TimeSpan.FromSeconds(15)
        });

        builder.AddTimeout(TimeSpan.FromSeconds(10));
    });
```

### Standard Pipeline Composition

```
Caller -> [Rate Limiter] -> [Total Request Timeout]
                              -> [Retry]
                                   -> [Circuit Breaker]
                                        -> [Per-Attempt Timeout]
                                             -> downstream
```

**Documented defaults** (Microsoft Learn, *Build resilient HTTP apps: Key development patterns*). Learn these as a set — an interviewer who asks "what does the one-liner actually give you?" is checking whether you know the shipped numbers or are guessing:

| Order | Stage | Defaults |
|---|---|---|
| 1 | Rate limiter | Permit `1_000`, queue `0` |
| 2 | Total timeout | 30 s |
| 3 | Retry | Max retries `3`, backoff `Exponential`, jitter `true`, base delay `2 s` |
| 4 | Circuit breaker | Failure ratio 10%, **min throughput `100`**, sampling duration 30 s, **break duration 5 s** |
| 5 | Attempt timeout | 10 s |

The two bolded values are the ones people leave out, and both change the story:

- **Min throughput 100.** The breaker will not open until it has seen at least 100 calls in the 30-second window. On a low-traffic client that means the shipped breaker may *never* trip; on a high-RPS one it is a sane floor. Any advice about `MinimumThroughput` being "too low" has to be measured against the real default, which is 100, not 5.
- **Break duration 5 s.** Short — the standard pipeline is tuned to probe for recovery quickly rather than to shed load for a long cool-off.

### When to Use Standard vs Custom

```
✅ Standard when:
   - You don't have empirical numbers yet
   - The dependency is "normal" (not real-time-critical)
   - You want one fewer thing to maintain

✅ Custom when:
   - SLA demands sub-second p99
   - Dependency has unusual semantics (e.g. webhook receivers)
   - You need fallbacks, hedging, or complex predicates
```

**Prefer overriding deltas to rebuilding the pipeline.** There is a middle ground between "take the defaults" and "hand-roll everything" — pass a configuration delegate and change only what your data justifies:

```csharp
builder.Services.AddHttpClient<PaymentClient>()
    .AddStandardResilienceHandler(options =>
    {
        options.Retry.MaxRetryAttempts        = 5;
        options.Retry.DisableForUnsafeHttpMethods();
        options.AttemptTimeout.Timeout        = TimeSpan.FromSeconds(4);
        options.CircuitBreaker.MinimumThroughput = 20;   // low-traffic client
    });
```

Spec the deltas, not a rewrite. And note the guidance that goes with it: **add one resilience handler, don't stack them.** If you need to replace an inherited configuration wholesale — for example a client that should hedge while everything else uses the standard handler — call `RemoveAllResilienceHandlers()` first rather than layering a second handler on top:

```csharp
services.ConfigureHttpClientDefaults(b => b.AddStandardResilienceHandler());

services.AddHttpClient("search")
    .RemoveAllResilienceHandlers()
    .AddStandardHedgingHandler();
```

---

## DelegatingHandler Chain

Every outbound call walks a chain of `DelegatingHandler`s — the same model as ASP.NET Core middleware, but on the *client* side. This is where you cleanly slot in concerns like auth, logging, header propagation, and chaos.

**The one rule that generates everything else:** registration order is pipeline order, first-registered outermost. Microsoft's wording is "Multiple handlers can be registered in the order that they should execute. Each handler wraps the next handler until the final `HttpClientHandler` executes the request." So the first `AddHttpMessageHandler<T>()` runs first on the way out and last on the way back.

The resilience handler is **just another handler at the position where you call it**. That single fact decides the whole layout:

```
handlers registered BEFORE the resilience handler  ->  run ONCE per logical request
handlers registered AFTER  the resilience handler  ->  run ONCE PER ATTEMPT
```

```
HttpClient.SendAsync
   |
   v
+----------------------+
| LoggingHandler       |  outermost — sees the whole operation, retries included
+----------------------+
            |
            v
+----------------------+
| CorrelationIdHandler |  one ID for the logical request, reused across attempts
+----------------------+
            |
            v
+----------------------+
| Resilience handler   |  retry / breaker / timeout  (AddStandardResilienceHandler)
+----------------------+
            |
            v            <-- everything below here re-executes on EVERY attempt
+----------------------+
| AuthHandler          |  stamps a fresh Authorization header per attempt
+----------------------+
            |
            v
+----------------------+
| SocketsHttpHandler   |  the real network I/O
+----------------------+
```

### Custom Handler Skeleton

```csharp
public sealed class CorrelationIdHandler(IHttpContextAccessor ctx) : DelegatingHandler
{
    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken ct)
    {
        if (ctx.HttpContext is { } http)
            request.Headers.TryAddWithoutValidation("X-Correlation-Id", http.TraceIdentifier);

        return await base.SendAsync(request, ct);   // pass down the chain
    }
}

builder.Services.AddTransient<CorrelationIdHandler>();
builder.Services.AddTransient<AuthHandler>();

builder.Services.AddHttpClient<PaymentClient>()
                .AddHttpMessageHandler<CorrelationIdHandler>()  // outside resilience — runs once
                .AddStandardResilienceHandler()
                .AddHttpMessageHandler<AuthHandler>();          // inside resilience — runs per attempt
```

Two details in that snippet are deliberate:

- **`TryAddWithoutValidation`, not `Add`.** `HttpHeaders.Add` validates the value and **throws** on anything it considers malformed — and `TraceIdentifier` is host-supplied, so a stray character turns a logging concern into a failed request. `TryAddWithoutValidation` returns `false` instead of throwing.
- **A per-attempt handler must *set*, not append.** Polly re-sends the same `HttpRequestMessage` instance on each attempt, so headers already on it are still there. An auth handler should assign `request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token)` — an assignment replaces — rather than calling `Add`, which would accumulate a second value on the retry.

Separately: `IHttpClientFactory` creates **a separate DI scope per handler instance**, and that scope is not the incoming-request scope and can outlive it. Do not cache request-scoped data (anything off `HttpContext`) in a handler's fields; read it per call through an accessor, as above.

### Handler Order Matters

```
+-----------------------------------------------------------+
|  HANDLER ORDER RULES                                       |
+-----------------------------------------------------------+
|  ✓ Registration order = pipeline order, first = outermost |
|  ✓ Logging FIRST so one log line covers all retries       |
|  ✓ Correlation ID early — one ID for the whole operation  |
|  ✓ Auth INSIDE the resilience handler, i.e. registered    |
|    AFTER it, so each attempt gets a fresh token           |
|  ✗ Don't register Auth before the resilience handler —    |
|    it would run once and replay a stale token on retry    |
|  ✗ Don't stack two resilience handlers                    |
+-----------------------------------------------------------+
```

> ⚠️ **The wording trap.** "Auth before retry" and "auth after retry" both get used to mean both things, so drop the words *before/after* and say what nests inside what: **the retry wraps the auth handler.** Concretely: `.AddStandardResilienceHandler().AddHttpMessageHandler<AuthHandler>()` — resilience registered first, auth registered second, therefore auth is inner, therefore auth re-runs on every retried attempt. That is the arrangement you want and the one to draw on a whiteboard.

---

## SocketsHttpHandler Tuning

`SocketsHttpHandler` is the bottom of the pipeline. Its defaults are reasonable for most apps, but a few knobs are worth knowing.

### Key Properties

```csharp
new SocketsHttpHandler
{
    PooledConnectionLifetime    = TimeSpan.FromMinutes(2),
    PooledConnectionIdleTimeout = TimeSpan.FromMinutes(1),
    MaxConnectionsPerServer     = 50,
    EnableMultipleHttp2Connections = true,
    AutomaticDecompression      = DecompressionMethods.All,
    ConnectTimeout              = TimeSpan.FromSeconds(10)
}
```

### What Each Knob Does

| Property | Documented default | Effect |
|---|---|---|
| `PooledConnectionLifetime` | **`Timeout.InfiniteTimeSpan`** | Max age of a pooled connection, measured from when it was established, regardless of idle or active time. Closing it forces the next request to re-resolve DNS. This is *the* DNS-refresh knob. |
| `PooledConnectionIdleTimeout` | 1 minute (.NET 6+); 2 minutes on .NET Core/.NET 5 | Closes connections sitting unused. Housekeeping, not correctness. |
| `MaxConnectionsPerServer` | unlimited | Caps parallel connections to one origin. |
| `EnableMultipleHttp2Connections` | off — opt in | Lets the pool open more than one HTTP/2 connection per origin. Microsoft notes this "explicitly goes against RFC 9113 §9.1", which is why it is not the default. |
| `AutomaticDecompression` | none | Transparent gzip / brotli / deflate. |
| `ConnectTimeout` | unbounded | Bounds the TCP + TLS handshake phase. |

> 🚨 **The default that catches people out: `PooledConnectionLifetime` is infinite.** Not two minutes. The two minutes belongs to a *different* mechanism — `IHttpClientFactory`'s `HandlerLifetime`, which throws away the whole handler (and with it, its entire pool) on a schedule. The factory never touches `PooledConnectionLifetime`. Two knobs, two owners:
>
> | | `PooledConnectionLifetime` | `HandlerLifetime` |
> |---|---|---|
> | Owned by | `SocketsHttpHandler` | `IHttpClientFactory` |
> | Default | `Timeout.InfiniteTimeSpan` | 2 minutes |
> | Recycles | one connection at a time | the entire handler and its pool |
> | Set via | `ConfigurePrimaryHttpMessageHandler` / `UseSocketsHttpHandler` | `SetHandlerLifetime(...)` |

### Wire It In

```csharp
builder.Services.AddHttpClient<PaymentClient>()
    .UseSocketsHttpHandler((handler, _) =>
    {
        handler.PooledConnectionLifetime = TimeSpan.FromMinutes(2);
        handler.EnableMultipleHttp2Connections = true;
        handler.MaxConnectionsPerServer = 50;
    })
    .SetHandlerLifetime(Timeout.InfiniteTimeSpan)   // <-- see note below
    .AddStandardResilienceHandler();
```

> 📌 **Why `SetHandlerLifetime(Timeout.InfiniteTimeSpan)` belongs in that snippet.** Once you configure `PooledConnectionLifetime` yourself, the handler recycles its own connections — so factory-level handler rotation is redundant work on a second, independent clock. Microsoft's guidance is explicit: "Since `SocketsHttpHandler` will handle connection pooling and recycling, handler recycling at the `IHttpClientFactory` level is no longer needed. You can disable it by setting `HandlerLifetime` to `Timeout.InfiniteTimeSpan`." Leaving both clocks running is not a correctness bug, but it does mean you tore down a healthy pool for no reason, and it is exactly the follow-up question an interviewer asks after you volunteer `PooledConnectionLifetime`.
>
> `.ConfigurePrimaryHttpMessageHandler(() => new SocketsHttpHandler { ... })` is the older equivalent and still fine; `UseSocketsHttpHandler` (.NET 5+) is preferred because it configures the handler rather than replacing whatever the pipeline already built.

The two minutes above is not a magic constant — pick the interval from how often you expect DNS or endpoint topology to change.

### Properties

```
+-----------------------------------------------------+
|  SOCKETSHTTPHANDLER                                 |
+-----------------------------------------------------+
|  ✓ Cross-platform managed implementation           |
|  ✓ HTTP/2 + HTTP/3 support                         |
|  ✓ Per-server connection pool                      |
|  ✓ Honors PooledConnectionLifetime for DNS         |
|  ✗ Defaults can leak resources without tuning      |
|  ✗ Pool is per-handler — shared via the factory    |
+-----------------------------------------------------+
```

---

## Testing HttpClient

"How do you unit-test a class that makes HTTP calls?" is asked constantly, and the answer is structural rather than clever: you never mock `HttpClient` (its methods aren't virtual in the way you'd want), you **substitute the handler underneath it**.

### Hand-Rolled Mock Handler

```csharp
public sealed class MockHttpHandler(Func<HttpRequestMessage, HttpResponseMessage> handler)
    : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken ct)
        => Task.FromResult(handler(request));
}

[Fact]
public async Task ChargeAsync_returns_result_on_200()
{
    var handler = new MockHttpHandler(_ =>
        new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(
                """{"chargeId":"ch_001","status":"succeeded"}""",
                Encoding.UTF8, "application/json")
        });

    var httpClient = new HttpClient(handler)
    {
        BaseAddress = new Uri("https://payment.example.com/v2/")
    };

    var client = new PaymentClient(httpClient);
    var result = await client.ChargeAsync(new ChargeRequest(99.99m));

    Assert.Equal("ch_001", result.ChargeId);
}
```

### Asserting That a Retry Actually Fired

The interesting test is not "does it parse a 200" — it is "does my resilience configuration do what I think". Make the mock **stateful** so it can fail once and then succeed, and assert on the call count:

```csharp
var callCount = 0;
var handler = new MockHttpHandler(_ =>
{
    callCount++;
    return callCount == 1
        ? new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
        : new HttpResponseMessage(HttpStatusCode.OK) { Content = /* ... */ };
});

// ...wire the retry pipeline over this handler, execute, then:
Assert.Equal(2, callCount);      // proves the retry ran, not just that the call succeeded
```

Keep the retry delay tiny in tests (`Delay = TimeSpan.FromMilliseconds(1)`) or the suite pays the real backoff.

### Choosing a Test Double

| Approach | Good for |
|---|---|
| Hand-rolled `HttpMessageHandler` | Unit tests; zero dependencies; full control including statefulness |
| `RichardSzalay.MockHttp` | Same, with fluent request matching and built-in assertions |
| `WireMock.Net` | A real local HTTP stub server — use when you need genuine HTTP semantics (status lines, headers, chunked bodies, delays) |
| `WebApplicationFactory` + `ConfigureTestServices` | Integration tests: re-register the client's handler for the whole host |

```csharp
// Intercepting an outbound dependency inside a WebApplicationFactory test
builder.ConfigureTestServices(services =>
{
    services.AddHttpClient<PaymentClient>()
            .AddHttpMessageHandler(() => new MockPaymentHandler());
});
```

### Fault Injection

Polly v8 absorbed the Simmy chaos library into the core package, so fault and latency injection are ordinary strategies on the same builder: `AddChaosFault`, `AddChaosLatency`, `AddChaosOutcome`, and `AddChaosBehavior`. Polly's guidance is to place the chaos strategy **last** in the pipeline — innermost, right next to the outbound call — so it subverts the request at the last moment and everything above it reacts as it would to a real fault. Gate it behind configuration so it is never enabled in production.

---

## Common Pitfalls

### 1. `new HttpClient()` Per Request

The classic. Symptom: random `SocketException: Only one usage of each socket address is normally permitted` after the app has been up a few hours. Fix: `IHttpClientFactory`.

### 2. `static HttpClient` Forever

Avoids socket exhaustion but pins one handler — and therefore one set of connections — for the lifetime of the process. Because `PooledConnectionLifetime` defaults to `Timeout.InfiniteTimeSpan`, those connections are never recycled and DNS is never re-resolved: a new IP for the dependency is missed until the process restarts. Fix: set `PooledConnectionLifetime` on the handler (this makes the static client a *supported* pattern, not a workaround), or move to `IHttpClientFactory` and let handler rotation do it.

### 3. Retrying Non-Idempotent POSTs

A POST that creates an order, retried after a timeout, may produce a duplicate order. Either:
- Make the operation idempotent (idempotency key header), then retry safely.
- Restrict retries to GET / HEAD / PUT / DELETE / OPTIONS.

### 4. No Jitter in Retry Delays

100 clients all hit a downstream simultaneously, all fail, all retry exactly 1 second later — the *thundering herd*. Always set `UseJitter = true`.

### 5. Inner Timeout > Outer Timeout

Polly's per-attempt timeout is 30s. The user-facing API's deadline is 5s. The outer cancels first; Polly never gets to fire its timeout meaningfully. Order timeouts so the *innermost* is the *shortest*.

### 6. Adding a Polly Retry On Top of `HttpClient.Timeout`

`HttpClient.Timeout` cancels the *whole* outer `SendAsync`, including retries. Use Polly's timeout strategy (per-attempt) and leave `HttpClient.Timeout = Timeout.InfiniteTimeSpan` if you want full control.

### 7. Reading Response Body Outside the Handler Scope

**First, the myth to unlearn:** handler rotation does *not* pull the rug out from under an in-flight read. An expired handler is only stopped from being lent to *new* clients; it stays alive until its reference count reaches zero, so requests already using it — including their response streams — drain normally.

The real failure with the same symptom is **disposing the response too early**. `HttpResponseMessage` owns the body; dispose it (or the `HttpClient` you own, if you own one) before the stream is consumed and the read fails or returns truncated data. Two concrete forms:

```csharp
// BROKEN — the using block disposes the response, and with it the stream
Stream GetBody(string url)
{
    using var response = _http.GetAsync(url).Result;
    return response.Content.ReadAsStream();     // caller reads a disposed stream
}

// BROKEN — Timeout also covers reading the body, not just receiving headers
_http.Timeout = TimeSpan.FromSeconds(5);
var r = await _http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct);
await SlowlyProcess(r.Content.ReadAsStream(), ct);   // clock is still running
```

Fix: either consume the body fully inside the scope that owns the response, or hand the *response* (not a bare stream) to whoever will consume it and let them dispose it. And when streaming with `HttpCompletionOption.ResponseHeadersRead`, remember `HttpClient.Timeout` spans the whole operation including the body read — which is another reason to set it to `Timeout.InfiniteTimeSpan` and let Polly and your own `CancellationToken` do the bounding.

### 8. Not Disposing `HttpRequestMessage`

`HttpClient.GetAsync(url)` is fine for simple cases, but if you build a `HttpRequestMessage` manually, `using` it (or `Dispose()`) prevents leaking buffers in long-running services.

### 9. Missing `EnableMultipleHttp2Connections`

A high-RPS client talking to an HTTP/2 dependency over one connection eventually hits the peer's concurrent-stream limit and its flow-control window; further streams queue instead of dispatching. Enabling multiple HTTP/2 connections lets the pool spread load across several TCP connections. It is opt-in — Microsoft notes that enabling it "explicitly goes against RFC 9113 §9.1", which is why it isn't on by default.

### 10. Treating 429 Like 503

429 *Too Many Requests* usually carries a `Retry-After` header. Honor it — `HttpRetryStrategyOptions.ShouldRetryAfterHeader` takes the delay from that header rather than the backoff curve, and defaults to `true`. The pitfall is the mirror image: hand-rolling a pipeline with a plain `RetryStrategyOptions<HttpResponseMessage>` instead of the HTTP-specific `HttpRetryStrategyOptions` loses that behaviour silently, and your retry storm extends the throttling window.

### 11. Putting Auth After Retry

*(Read the title as "auth nested outside the retry" — the before/after wording is exactly what makes this pitfall confusing, so state it as nesting.)*

A 401 prompts a token refresh. If the auth handler sits **outside** the resilience handler, it runs once per logical request and the retried attempt replays the same expired token — a retry loop that cannot succeed. Register the auth handler **after** the resilience handler so it nests **inside** it and re-runs per attempt: `.AddStandardResilienceHandler().AddHttpMessageHandler<AuthHandler>()`. Correct nesting: retry wraps auth.

### 12. Logging Bodies in Production

Logging request/response bodies leaks PII, secrets, and bloats log volumes. Log status, latency, and headers; gate body logging behind a flag. Use `RedactLoggedHeaders` on the `IHttpClientBuilder` so `Authorization` and friends don't reach the log sink either.

### 13. `BaseAddress` Without a Trailing Slash

The versioned path segment is silently dropped and every call goes to the wrong URL while still returning 200s from *something*. `BaseAddress` ends with `/`; relative paths never start with `/`. See [BaseAddress and Relative URIs](#baseaddress-and-relative-uris).

### 14. Logging Handler Registered Inside the Retry

The mirror image of pitfall 11. A logging handler nested inside the resilience handler emits one line per *attempt* with no notion of the operation, so you see three unrelated-looking failures instead of one operation that recovered. Register logging first — outermost.

### 15. Assuming the Standard Handler Won't Retry Your POST

It will. `AddStandardResilienceHandler()` retries all HTTP methods by default. Adding resilience to a service with non-idempotent POSTs and no idempotency keys converts transient faults into duplicate writes. Call `options.Retry.DisableForUnsafeHttpMethods()` unless you have deliberately made those calls safe to repeat.

---

## Best Practices

1. **Always use `IHttpClientFactory`.** Typed clients are the default; named clients are for dynamic selection.
2. **Use the standard resilience handler unless you have a reason not to.** `AddStandardResilienceHandler()` is a sensible baseline.
3. **Always enable jitter.** `UseJitter = true` is one line and prevents thundering herds.
4. **Order timeouts: inner shortest, outer longest.** Otherwise the outer dominates and the inner is moot.
5. **Make calls idempotent before retrying mutating operations.** Idempotency keys, `If-None-Match`, or unique request IDs.
6. **Set `PooledConnectionLifetime` when you own the handler** — its default is infinite, so nothing recycles until you say so. Pick the interval from your expected rate of DNS change, and pair it with `SetHandlerLifetime(Timeout.InfiniteTimeSpan)` so you aren't running two rotation clocks.
7. **Enable multiple HTTP/2 connections.** Especially for high-RPS inter-service calls; it is opt-in.
8. **Auth handler inside the resilience handler** — registered *after* it — so refreshed tokens reach the retried attempt. Assign `request.Headers.Authorization` rather than `Add`, since the same request object is reused across attempts.
9. **Honor `Retry-After`.** `HttpRetryStrategyOptions.ShouldRetryAfterHeader` reads it for you and defaults to `true` — so use the HTTP-specific options type and don't hard-code a delay for 429.
10. **Tune breaker thresholds against the shipped defaults, not folklore.** The standard handler's `MinimumThroughput` is 100 — high enough that a low-traffic client may never trip it, which is usually the problem you actually have.
11. **Use `HttpCompletionOption.ResponseHeadersRead`** for streaming responses so the body isn't buffered into memory — and keep the response alive until the stream is consumed.
12. **Add a correlation ID handler**, outermost, using `TryAddWithoutValidation` so a malformed identifier can't throw on the way out.
13. **Test resilience with Polly's chaos strategies** — `AddChaosFault`, `AddChaosLatency`, `AddChaosOutcome`, `AddChaosBehavior` (Simmy, absorbed into Polly v8). Place them innermost and gate them behind configuration.
14. **Log at the boundary.** A logging handler at the *outermost* position captures retries, breaker openings, and end-to-end latency in one place.
15. **`BaseAddress` ends with `/`, relative paths don't start with one.** Cheapest bug in the list to prevent and one of the most expensive to find.
16. **Decide explicitly whether unsafe methods retry.** `DisableForUnsafeHttpMethods()` or an idempotency-key contract — but make it a decision, not a default you didn't read. Note the blanket call also stops retrying PUT and DELETE, which are idempotent; use `DisableFor(...)` if you want to keep those.
17. **One resilience handler per client.** Stacking them multiplies attempts in ways nobody can reason about; use `RemoveAllResilienceHandlers()` when you need to replace an inherited configuration.

---

## Real-World Scenarios

### Scenario 1: Calling an Unreliable Third-Party API

```
+----------------------------------------------------------+
|  Requirement: a SaaS dependency drops 1-3% of calls      |
|  with 503s and occasionally hangs for 30s.               |
+----------------------------------------------------------+

Pipeline:
  AddStandardResilienceHandler with overrides:
    Per-attempt timeout : 5s   (kill hangs early)
    Retry               : 3, exp + jitter, on {503, 429, 5xx, RequestException}
    Circuit breaker     : 50% fail over 30s, break 15s
    Total timeout       : 20s (caller's outer budget)

Result:
  p99 latency stays bounded. Transient drops are absorbed.
  Outage triggers breaker, freeing threads for other work.
```

### Scenario 2: Dual-Region Failover

```
+----------------------------------------------------------+
|  Requirement: primary region in us-east, secondary in    |
|  us-west. Fail over when primary is broken; come back    |
|  automatically when it recovers.                         |
+----------------------------------------------------------+

Design:
  Two named clients: "primary" and "secondary".
  PrimaryPipeline = retry + breaker + per-attempt timeout
  Outer wrapper service:
    try primary
    catch BrokenCircuitException
       -> call secondary
  When primary's breaker re-closes (probe succeeds),
  traffic returns automatically.

Hint:
  Use AddHedging if you can afford to fire BOTH and take the winner.
```

### Scenario 3: Latency-Budget Enforcement

```
+----------------------------------------------------------+
|  Requirement: an aggregator endpoint must respond in     |
|  500ms p99. It calls 4 downstream services in parallel.  |
+----------------------------------------------------------+

Approach:
  - Caller-level CancellationTokenSource with 500ms deadline.
  - Per-call typed client with per-attempt timeout = 200ms,
    retry = 1, no breaker (the deadline IS the breaker).
  - Use Task.WhenAll with the shared token; partial failures
    return a degraded response.
  - Each typed client logs its own latency to inform tuning.

Anti-pattern avoided:
  Long retry chains > 500ms — the user has already given up.
  The retry budget must fit within the deadline, with margin.
```

---

## Interview-Ready Summary

- **Socket exhaustion.** `new HttpClient()` per request gives every call its own connection pool; closed sockets sit in kernel `TIME_WAIT` (2 × MSL, RFC 9293) and the machine's ephemeral port range runs out. `Dispose()` is doing its job — the kernel is the constraint.
- **Two supported lifetimes, not one.** Long-lived client with `PooledConnectionLifetime` set, *or* short-lived clients from `IHttpClientFactory`. The bug is an untuned handler, not the word "static".
- **`IHttpClientFactory`.** Pools and rotates `HttpMessageHandler` instances every `HandlerLifetime` (default 2 min); `CreateClient()` is a cheap wrapper; expired handlers drain before disposal. It does **not** set `PooledConnectionLifetime`.
- **Client styles.** Typed by default (one class, one API surface); named for runtime selection; basic for one-offs. Typed clients are transient — never capture one in a singleton.
- **`BaseAddress`.** Trailing slash on the base, no leading slash on the relative path, per the RFC 3986 §5.3 merge rule. Absolute `Uri` arguments bypass `BaseAddress` entirely.
- **`DelegatingHandler`s.** Registration order is pipeline order, first outermost. Handlers registered after the resilience handler nest inside it and re-run per attempt — which is exactly why auth goes there and logging goes outermost.
- **Polly v8.** `ResiliencePipelineBuilder<T>` replaces v7's policy classes; allocation-free on the success path; builder order is nesting order, first added is outermost. Versions independently of .NET.
- **Retry.** Exponential backoff plus jitter, or you build a thundering herd. Retry 408/429/5xx and `HttpRequestException`; never 400/401/403/404/422.
- **Circuit breaker.** Closed → open → half-open probe → closed or open. In-process and per-replica; no cross-instance coordination without an external store.
- **Timeouts.** Three surfaces: `HttpClient.Timeout` (whole call, default 100 s — set to infinite under Polly), Polly per-attempt, Polly total. Inner must be shorter than outer, and `(attempts × perAttempt) + backoffs < total`.
- **Hedging.** Fires *before* the first attempt resolves; buys tail latency at the cost of extra in-flight requests. Idempotent operations only.
- **The standard handler.** Five stages — rate limiter (1000/0) → total timeout (30 s) → retry (3, exponential, jitter, 2 s base) → circuit breaker (10%, min throughput 100, 30 s sampling, 5 s break) → attempt timeout (10 s). No fallback stage. Retries every HTTP method until you call `DisableForUnsafeHttpMethods()`.
- **Testing.** Substitute the `HttpMessageHandler`, not the `HttpClient`. Assert on call counts to prove a retry actually fired.

---

## 25. HttpClient & Resilience (Polly)

> 🔗 **This heading exists to keep the legacy anchor `#25-httpclient--resilience-polly` alive** for documents that link to it (notably `01-net-core-deep-dive/README.md`). The content it used to hold was a duplicate of material earlier in this file; rather than maintain two copies that can drift apart, it now points at the canonical sections.

Jump to the real thing:

- Registering basic, named, and typed clients → [IHttpClientFactory § Registration](#registration)
- The recommended typed-client baseline → [Typed Client (the recommended baseline)](#typed-client-the-recommended-baseline)
- Getting the URL right → [BaseAddress and Relative URIs](#baseaddress-and-relative-uris)

### Polly Resilience (.NET 8+)

- The one-liner and what it actually configures → [Standard Resilience Pipeline (.NET 8+)](#standard-resilience-pipeline-net-8)
- Hand-composing a pipeline → [Custom Order](#custom-order)
- Per-strategy detail, with the trade-offs → [Strategies in Detail](#strategies-in-detail)
- Which failures deserve a retry at all → [Transient Fault Classification](#transient-fault-classification)
- The circuit-breaker state machine → [Circuit Breaker](#circuit-breaker)

---

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Socket exhaustion

> **Q**: Why is `using var http = new HttpClient(); await http.GetAsync(...)` per request wrong?
>
> **A**: Each `new HttpClient()` creates a new `HttpMessageHandler` with its own connection pool, so nothing is reused and every call opens a fresh TCP connection. When it closes, the kernel holds the socket in `TIME_WAIT` — on Windows for the `TcpTimedWaitDelay` interval, which Microsoft documents as defaulting to 240 seconds. The machine's ephemeral port range is finite (Windows default 49152–65535, i.e. 16,384 ports), so under sustained load you exhaust it and get `SocketException: Only one usage of each socket address is normally permitted`. The symptom appears minutes-to-hours into a load run, never in dev.
>
> **Cross-Q**: Why doesn't `using` solve the leak — isn't that what dispose is for?
>
> **A**: Because the *socket itself* doesn't immediately close on `Dispose`. TCP keeps the 4-tuple in TIME-WAIT for `2 × MSL` (RFC 9293 §3.3.2) so that a late-arriving segment from the old connection can't be mistaken for data on a new one reusing the same tuple. Disposing the C# object releases the managed handle; the kernel's state machine runs independently. **`Dispose` is correct; the protocol is the bottleneck.** The fix isn't disposing harder, it's opening fewer connections.
>
> **Cross-Q²**: So is `static readonly HttpClient` the fix, or is it also wrong?
>
> **A**: Careful — this is where the question is usually asked badly. A static client is one of the **two lifetime strategies Microsoft explicitly recommends**, *provided* you construct it over a `SocketsHttpHandler` with `PooledConnectionLifetime` configured. What's wrong is the static client with the handler left at defaults: `PooledConnectionLifetime` defaults to `Timeout.InfiniteTimeSpan`, so connections are never recycled, DNS is never re-resolved, and a rolling restart or cloud failover leaves you talking to a dead IP until the process restarts. `IHttpClientFactory` is the other supported strategy — pooled handlers plus rotation every `HandlerLifetime` — and it additionally buys you named/typed configuration, DI, logging, and Polly composition.

### Drill 2 — `IHttpClientFactory`

> **Q**: What does `IHttpClientFactory` actually manage?
>
> **A**: A pool of `HttpMessageHandler` instances keyed by named client. Each `CreateClient(name)` returns a lightweight `HttpClient` wrapper around a borrowed handler. Handlers rotate every `HandlerLifetime` (default 2 min) — old handlers are disposed once no client still holds them. **The factory owns the lifecycle; you don't `using` the client.**
>
> **Cross-Q**: What happens to in-flight requests when a handler rotates?
>
> **A**: The handler isn't immediately disposed — it stays alive until its reference count drops to zero (all clients borrowing it have completed their requests). New clients get the new handler; old clients drain naturally. Rotation is graceful.
>
> **Cross-Q²**: If I `factory.CreateClient("payment")` 1000 times in a tight loop, am I leaking?
>
> **A**: No — `CreateClient` returns a cheap wrapper, not a new handler. The wrapper is GC'd normally; the underlying handler is shared. Some teams cache the client (`var c = factory.CreateClient(); /* hold for many calls */`), which is fine within a scope but **wrong as a singleton** because you'd defeat handler rotation. **Rule**: get a client per logical operation; the factory makes that cheap.

### Drill 3 — Named vs typed clients

> **Q**: When do you use a named client vs a typed client?
>
> **A**: **Typed** when one class owns calls to one API surface — `PaymentClient`, `EmailClient`. DI gives the class its `HttpClient` directly, and Polly handlers register on the type. **Named** when you need to pick at runtime — "primary" vs "secondary" for failover, "us-east" vs "eu-west" for geo routing — and a static class doesn't fit. **Typed is default; named is escape hatch.**
>
> **Cross-Q**: Can I have a typed client that internally selects between named clients?
>
> **A**: Yes — inject `IHttpClientFactory` into the typed-client class, and have it call `factory.CreateClient("primary"|"secondary")` based on a strategy. You get the best of both: a strongly-typed class boundary at the call site, dynamic selection at the implementation. This is a common failover pattern.
>
> **Cross-Q²**: Can two typed clients share one `HttpClient` configuration?
>
> **A**: Not directly — each typed-client registration creates its own configuration. You can share configuration logic via an extension method: `static IHttpClientBuilder AddSharedConfig(this IHttpClientBuilder b) => b.ConfigureHttpClient(...)`. Then both `AddHttpClient<A>().AddSharedConfig()` and `AddHttpClient<B>().AddSharedConfig()` apply the same setup. **DRY without coupling**.

### Drill 4 — Polly v8 composition order

> **Q**: In a `ResiliencePipelineBuilder`, what order do you compose retry, circuit breaker, and timeout?
>
> **A**: From the **caller** inward: **Rate Limiter → Total Timeout → Retry → Circuit Breaker → Per-Attempt Timeout → downstream**. That is exactly what `AddStandardResilienceHandler()` composes. Reason: rate limiter is the outermost guard against overload; total timeout is the absolute budget; retries happen inside that budget; the breaker is consulted per attempt (open = fail fast); per-attempt timeout bounds each individual attempt so a retry can actually fire.
>
> **Cross-Q**: What actually changes if I swap retry and circuit breaker?
>
> **A**: How many failures the breaker gets to count. **Breaker inside retry** (the standard order) means the breaker is entered on *every attempt*, so a single logical call that retries three times feeds it three failures — it accumulates faster and can cut the retry loop short mid-flight with `BrokenCircuitException`. **Breaker outside retry** means it is entered once per logical call and sees only the final outcome of the whole retry block, so it accumulates more slowly but each sample represents "we genuinely could not get through". The standard pipeline nests the breaker inside, which is why it can abandon a doomed retry sequence immediately instead of burning the remaining attempts and backoffs.
>
> **Cross-Q²**: Where does fallback go in the order?
>
> **A**: **Outermost** — first in the builder — so it can catch everything inside it: an open circuit, exhausted retries, a blown total timeout. Putting fallback inside retry would make retry fire against the fallback path, which is meaningless. One caveat to state before you're corrected: **fallback is not a stage of `AddStandardResilienceHandler()`.** The shipped handler has exactly five stages and fallback isn't one of them; the outermost-fallback rule applies to pipelines you compose yourself.

### Drill 5 — Retry strategy

> **Q**: What's the right combination of MaxRetryAttempts, Delay, and BackoffType for an unreliable third-party API?
>
> **A**: Typically: `MaxRetryAttempts = 3`, `Delay = TimeSpan.FromSeconds(1)`, `BackoffType = Exponential`, `UseJitter = true`. That is **four attempts in total** — `MaxRetryAttempts` counts retries *in addition to* the original call — at roughly 0s, 1s, 2s, and 4s. Tune based on the dependency's recovery behavior: faster backoff if the API recovers in <1s, slower if recovery is multi-second.
>
> Be careful quoting a jitter figure: Polly's **±25%** jitter applies to `Constant` and `Linear` backoff. With `Exponential` + `UseJitter` it instead uses the decorrelated-jitter algorithm (`DecorrelatedJitterBackoffV2`, from Polly.Contrib.WaitAndRetry), whose delays are *not* a tidy ±25% band around the exponential curve and can land above it. Say "jitter randomises the delay so clients de-synchronise", not a specific percentage, unless you know which backoff type is in play.
>
> **Cross-Q**: Why is jitter critical?
>
> **A**: Without jitter, N clients failing simultaneously all retry exactly 1s later, then 2s, then 4s — a **thundering herd**. The downstream recovers, gets slammed again, fails, and the cycle repeats. Jitter spreads the retries randomly across the delay window, smoothing the load. `UseJitter = true` is one line; the cost of forgetting it is a cascading outage.
>
> **Cross-Q²**: When should I retry a non-idempotent POST?
>
> **A**: Only when the operation has an **idempotency key** — a unique ID the server uses to deduplicate — and it's common for payment and order APIs to offer or require one. Pattern: the client generates a GUID per logical operation and sends it as an `Idempotency-Key` header; the server stores `(key, result)` for a bounded window, so a retry with the same key returns the original result without re-executing. **Without an idempotency mechanism, retrying a POST is a duplicate-order bug waiting to happen** — and remember `AddStandardResilienceHandler()` retries POSTs by default, so this is on by accident unless you turn it off.

### Drill 6 — Circuit breaker

> **Q**: Walk me through the three circuit breaker states.
>
> **A**: **Closed**: all calls pass through; the breaker counts failures in a rolling window. **Open**: calls short-circuit with `BrokenCircuitException` (no downstream call); after `BreakDuration` elapses, transition to half-open. **Half-Open**: a single probe call is allowed; success → closed, failure → open again. The state machine prevents you from hammering a dead dependency and lets it recover.
>
> **Cross-Q**: What's the right `FailureRatio` and `SamplingDuration`?
>
> **A**: Start by knowing what you're overriding: the shipped standard handler uses **10% failure ratio, minimum throughput 100, 30 s sampling, 5 s break**. `MinimumThroughput` is the statistical floor — the breaker won't open until it has seen that many calls inside the sampling window, which stops one failed call out of one from reading as a 100% failure ratio. Then adjust for traffic: a **low-traffic** client (single-digit RPS) will never accumulate 100 calls in 30 s, so the shipped breaker effectively never trips and you must lower the threshold or lengthen the window; a **high-traffic** client has samples to spare and can afford a shorter sampling duration to react faster. The failure mode runs both ways — set it too low on a busy endpoint and a single blip trips the breaker; leave it at 100 on a quiet one and the breaker is decorative.
>
> **Cross-Q²**: Where does the breaker state live in a horizontally scaled service?
>
> **A**: **Per-instance.** Polly's breaker is in-process — 10 replicas means 10 breakers, each tracking its own failure ratio. This is by design (cheap, no external coordination). The downside: one instance opens while others still try. For coordinated breakers across instances, you need an out-of-process state store (Redis-backed implementations exist) — much heavier, rarely worth it. Most teams accept per-instance and rely on aggregate effects.

### Drill 7 — Timeout cascades

> **Q**: I have a total pipeline timeout of 10s, retry with `MaxRetryAttempts = 3` and 1s exponential backoff, no per-attempt timeout. What's the worst-case latency?
>
> **A**: Up to **10s** — the total pipeline timeout caps everything. Without a per-attempt timeout, a single hung downstream can consume the whole 10s on the first attempt; the remaining attempts never happen because the total timeout fires first. **Lesson**: total timeout is the hard ceiling; per-attempt is what bounds *individual hangs* so retries can actually run.
>
> **Cross-Q**: Set per-attempt to 3s. Worst case now?
>
> **A**: First get the count right — `MaxRetryAttempts = 3` means **4 attempts** (the original plus three retries) and **3 backoffs**, which is the off-by-one most people make here. So 4 × 3s = 12s of attempts plus 1+2+4 = 7s of backoff ≈ **19s nominal**, and the 10s total timeout still cuts it off well before that. You'd get roughly two or three attempts and then a total-timeout fault. To fit fully inside 10s: `MaxRetryAttempts = 2` (3 attempts), per-attempt 2s, `Delay` 200ms — 3 × 2s + (0.2 + 0.4) ≈ 6.6s, with margin for jitter.
>
> **Cross-Q²**: Where should `HttpClient.Timeout` be set in this picture?
>
> **A**: To `Timeout.InfiniteTimeSpan` (i.e., disabled). `HttpClient.Timeout` is a hard cap on the whole `SendAsync` call **including retries** — it overrides Polly's timeout and breaks the cascade. Polly's per-attempt timeout is the strategy-aware version; leave `HttpClient.Timeout` infinite and let Polly enforce timeouts. **This is the #1 hidden-timeout gotcha** when adding resilience to existing code.

### Drill 8 — Bulkhead / rate limiter

> **Q**: What isolation does a bulkhead (rate limiter) provide?
>
> **A**: It caps **concurrent in-flight calls** to a dependency. If `PermitLimit = 50`, at most 50 requests are mid-flight; further requests are queued (if `QueueLimit > 0`) or rejected. This stops one slow dependency from monopolizing the thread pool — even if dependency X is timing out, you have at most 50 threads parked on it, not your entire pool.
>
> **Cross-Q**: How is this different from a circuit breaker?
>
> **A**: Breaker stops calls when *failure rate* spikes. Rate limiter caps concurrency *all the time*, regardless of failure rate. Used together: rate limiter prevents resource starvation under healthy-but-slow conditions; breaker fails fast under dependency-is-broken conditions. **Different problems, different tools.**
>
> **Cross-Q²**: What's `QueueLimit = 0` vs `QueueLimit = 100`?
>
> **A**: `0` means reject immediately when concurrency is at the cap — caller gets a `RateLimiterRejectedException`. `100` means queue up to 100 extra; the 101st gets rejected. Queueing trades latency for completion (callers wait their turn); zero-queue trades completion for latency (callers fail fast). For user-facing endpoints, zero-queue + fast user feedback. For background workers, large queue + acceptance.

### Drill 9 — `PooledConnectionLifetime`

> **Q**: Why does `SocketsHttpHandler.PooledConnectionLifetime` matter?
>
> **A**: It caps how long a TCP/TLS connection may stay in the pool, measured from when it was established, regardless of how much of that time it spent idle or active. When the connection is closed the next request opens a new one, which **re-resolves DNS**. Its default is **`Timeout.InfiniteTimeSpan`** — so out of the box nothing recycles, and a persistent connection can outlive a DNS change indefinitely.
>
> **Cross-Q**: You said the default is infinite, but I've read that `IHttpClientFactory` defaults it to 2 minutes. Which is it?
>
> **A**: Both statements are about different knobs and conflating them is the classic error. `SocketsHttpHandler.PooledConnectionLifetime` is infinite by default and **the factory never sets it**. What the factory has is `HandlerLifetime`, default 2 minutes, which expires the whole handler — the handler stops being lent to new clients, drains its in-flight requests, and is then disposed along with its entire connection pool. Connection-level recycling versus handler-level recycling; two mechanisms, two owners, one shared purpose.
>
> **Cross-Q²**: I'm using `static HttpClient` (legacy). Can I get DNS refresh without switching to the factory?
>
> **A**: Yes, and it isn't a hack — it's the other officially supported strategy. Construct it over a tuned `SocketsHttpHandler`:
> ```csharp
> static readonly HttpClient Http = new(new SocketsHttpHandler {
>     PooledConnectionLifetime = TimeSpan.FromMinutes(2)   // choose from your DNS change rate
> });
> ```
> The handler recycles connections on that schedule, so DNS is re-resolved. You give up named/typed configuration, DI, and the factory's Polly integration — though you can still attach a pipeline manually by wrapping the socket handler in a `ResilienceHandler`. **And the converse**: if you set `PooledConnectionLifetime` on a factory-registered client, also call `SetHandlerLifetime(Timeout.InfiniteTimeSpan)`, because otherwise two independent rotation clocks are recycling the same pool for no benefit.

### Drill 10 — `EnableMultipleHttp2Connections`

> **Q**: When does `EnableMultipleHttp2Connections = true` matter?
>
> **A**: HTTP/2 multiplexes streams over one TCP connection. Under high concurrency, the **flow-control window** on a single connection becomes a bottleneck — requests queue at the TCP layer waiting for window credits. Enabling multiple HTTP/2 connections lets the pool spread streams across multiple TCP connections, eliminating head-of-line blocking at the transport layer. Critical for high-RPS inter-service calls.
>
> **Cross-Q**: Why is the default `false`?
>
> **A**: Because HTTP/2's design intent is one connection per origin, and Microsoft's own documentation says enabling multiple connections "explicitly goes against RFC 9113 §9.1". The default is spec-conformant; the override is an informed throughput decision. For internal high-RPS service-to-service traffic it is usually the right call, but say "usually", not "always" — you are overriding a protocol recommendation and should be able to justify it.
>
> **Cross-Q²**: At what concurrency does a single HTTP/2 connection become the bottleneck, and how would you detect it?
>
> **A**: There is no universal number — the ceiling is whatever the **peer** advertises in `SETTINGS_MAX_CONCURRENT_STREAMS`, plus the TCP congestion window and RTT. Two anchors you can quote: RFC 9113 §6.5.2 recommends that value be no smaller than 100, and Kestrel's `Http2Limits.MaxStreamsPerConnection` defaults to 100 — so if your downstream is an ASP.NET Core service on defaults, roughly 100 concurrent in-flight requests per connection is where extra streams start queueing rather than dispatching. **The detection signal is the useful part**: rising p99 latency under load with *no* corresponding rise in error rate. Errors would point at the dependency; latency without errors points at your own transport queueing.
>
> **Cross-Q³**: How is this different from HTTP/1.1 connection pooling?
>
> **A**: HTTP/1.1: one request per connection at a time — the pool opens *N* connections for *N* concurrent requests. HTTP/2: many concurrent streams over one connection — the pool opens *one*. **`EnableMultipleHttp2Connections` lets HTTP/2 use multiple connections like HTTP/1.1 does**, sacrificing some of HTTP/2's elegance for throughput. HTTP/3 (QUIC) sidesteps transport-level head-of-line blocking entirely, since loss on one stream doesn't stall the others.

### Drill 11 — Polly v7 vs v8

> **Q**: What are the major API differences between Polly v7 (policies) and v8 (ResiliencePipeline)?
>
> **A**: v7: `Policy.Handle<...>().WaitAndRetryAsync(...)` → returns an `IAsyncPolicy<T>`; runtime allocates per call. v8: `new ResiliencePipelineBuilder<T>().AddRetry(...).Build()` → returns `ResiliencePipeline<T>`; allocation-free on success path, telemetry-aware, composable. v8 also unifies sync and async (`pipeline.Execute(...)` and `pipeline.ExecuteAsync(...)` on the same pipeline).
>
> **Cross-Q**: Why was v7 retired?
>
> **A**: Three reasons. (1) Allocation per execution hurt high-RPS scenarios. (2) The sync/async split forced duplicate policies. (3) Strategy composition was limited — v8's builder + options pattern is genuinely more expressive, and it made room for strategies v7 never had (hedging, and the Simmy chaos strategies folded into the core package). v7 still exists on NuGet, but `Microsoft.Extensions.Http.Resilience` builds on v8 — if you want `AddStandardResilienceHandler()`, you are on v8.
>
> **Cross-Q²**: How do I migrate v7 policies to v8 incrementally?
>
> **A**: v7 and v8 are separate packages (`Polly` vs `Polly.Core` + `Polly.Extensions`) — they coexist. Migrate file-by-file: replace `Policy.HandleResult<...>` with `new ResiliencePipelineBuilder<T>().AddRetry(new RetryStrategyOptions<T> { ShouldHandle = ... })`. The conceptual mapping is direct; the syntax is more verbose but more discoverable via IntelliSense. **Don't try to migrate in a single PR for a large codebase** — file-by-file behind a feature flag is safer.

### Drill 12 — Standard resilience pipeline

> **Q**: What does `AddStandardResilienceHandler()` give me out of the box?
>
> **A**: Five stages, outermost first: rate limiter (permit 1000, queue 0) → total timeout (30 s) → retry (3 *retries*, i.e. up to 4 attempts, exponential, jitter on, 2 s base delay) → circuit breaker (10% failure ratio, **minimum throughput 100**, 30 s sampling, **5 s break**) → per-attempt timeout (10 s). Retry and breaker both handle HTTP 500-and-above, 408, 429, plus `HttpRequestException` and `TimeoutRejectedException`. **No fallback stage** — that's a hand-built addition, not part of the standard handler.
>
> **Cross-Q**: Anything in that default set that would surprise a team adopting it?
>
> **A**: Two things. **It retries every HTTP method, POST included** — Microsoft's docs say so explicitly, and the remedy is `options.Retry.DisableFor(...)` or `options.Retry.DisableForUnsafeHttpMethods()` (POST, PATCH, PUT, DELETE, CONNECT). A team that adds one line of resilience to a payment service and doesn't read that has just built a duplicate-charge generator. And **the breaker's minimum throughput is 100**, which on a low-traffic client means it will realistically never open — people assume they're protected when they aren't.
>
> **Cross-Q²**: Can I add my own strategy to the standard pipeline?
>
> **A**: Not *to* it — the guidance is one resilience handler per client, don't stack them. Your options are: pass a delegate and override deltas — `AddStandardResilienceHandler(options => { options.Retry.MaxRetryAttempts = 5; })` — which is the cleanest and preserves everything you didn't touch; compose from scratch with `AddResilienceHandler("name", builder => ...)` when the shape itself is wrong for you; or call `RemoveAllResilienceHandlers()` first to drop an inherited configuration before adding a different one. **"Spec the deltas, not rewrite the whole policy."**

### Drill 13 — DelegatingHandler chain

> **Q**: I have CorrelationId, Auth, and Logging handlers. What's the right registration order?
>
> **A**: From outermost (closest to caller) inward: **Logging → CorrelationId → resilience handler → Auth → SocketsHttpHandler**, which is the registration order `.AddHttpMessageHandler<Logging>().AddHttpMessageHandler<CorrelationId>().AddStandardResilienceHandler().AddHttpMessageHandler<Auth>()`. Logging outermost so one log record covers the whole operation including every retry. CorrelationId next, so a single ID identifies the logical request rather than each attempt. Auth **inside** the resilience handler so a refreshed token is applied on each retried attempt.
>
> **Cross-Q**: Why must Auth be inside the resilience handler?
>
> **A**: Because only handlers *inside* it re-execute per attempt. If auth is outside, it stamps the token once; Polly then re-sends that same `HttpRequestMessage` with the same expired token, gets 401 again, and you have a retry loop that cannot possibly succeed. With auth inside, each attempt re-enters the auth handler and can attach a fresh token. **Say it as nesting, not as before/after: the retry wraps the auth handler.**
>
> **Cross-Q²**: How does `AddHttpMessageHandler<T>()` decide order?
>
> **A**: **Registration order = pipeline order, first registered is outermost.** Microsoft's wording: "Multiple handlers can be registered in the order that they should execute. Each handler wraps the next handler until the final `HttpClientHandler` executes the request." `AddStandardResilienceHandler` and `AddResilienceHandler` are *just more handlers* in that chain, sitting wherever you call them. So `.AddHttpMessageHandler<Auth>().AddStandardResilienceHandler()` puts Auth outside the resilience pipeline — it runs once, tokens never refresh on retry, **wrong** — while `.AddStandardResilienceHandler().AddHttpMessageHandler<Auth>()` puts Auth inside it, **right**.
>
> **Cross-Q³**: The auth handler runs on every attempt now. Any hazard in that?
>
> **A**: Two. First, the *same* `HttpRequestMessage` instance is reused across attempts, so a handler that calls `request.Headers.Add(...)` accumulates duplicate header values on retries — assign `request.Headers.Authorization` instead, since assignment replaces. Second, `IHttpClientFactory` gives each handler instance its own DI scope, separate from the incoming-request scope and potentially longer-lived, so a handler that cached a token (or anything else off `HttpContext`) in a field can leak it across unrelated requests. Resolve per call.

### Drill 14 — DNS resolution caching

> **Q**: How does .NET cache DNS resolutions?
>
> **A**: It mostly doesn't — `SocketsHttpHandler` resolves DNS lazily, per new connection. **But** the connection pool means resolutions are effectively cached for the *lifetime of a connection*. A long-lived HTTP/2 connection bypasses DNS for hours unless you cap it via `PooledConnectionLifetime`.
>
> **Cross-Q**: Why does `IHttpClientFactory` solve "stale DNS" then?
>
> **A**: Because handler rotation (every `HandlerLifetime`, default 2 min) retires the whole handler and, once it has drained, its entire pool — so subsequent requests open new connections that re-resolve DNS. Without any rotation, a pool can hold the same IP for the life of the process. Be precise about the bound, though: the factory doesn't make stale DNS *impossible*, it makes staleness *bounded* — worst case you keep using an old address for about one `HandlerLifetime` after the change.
>
> **Cross-Q²**: My app calls a Kubernetes service via DNS. Service IP changes after a rolling restart. What's the failure mode without rotation?
>
> **A**: Existing connections keep pointing at the old pod IP. The OS sends RST when the old pod's socket closes; .NET sees `IOException` / `HttpRequestException`; a new connection is opened. **Without** PooledConnectionLifetime, the new connection re-resolves DNS — usually finds the new IP. **But** in some load-balancer scenarios (sticky sessions, slow DNS propagation), connections can keep failing for minutes. **Combined fix**: PooledConnectionLifetime to force rotation + Polly retry to absorb the transient errors during rollout.

### Drill 15 — Idempotency on retry

> **Q**: Which HTTP methods are safe to retry blindly?
>
> **A**: RFC 9110 §9.2.2 defines the set exactly: **PUT, DELETE, and the safe methods — GET, HEAD, OPTIONS, TRACE**. Retrying those produces the same observable server state. **POST, PATCH, and CONNECT are not idempotent** (CONNECT is a common wrong answer — it is neither safe nor idempotent). Note "idempotent" is about *server state*, not about getting an identical response body: a retried GET is idempotent even if the resource changed underneath you.
>
> **Cross-Q**: Why is PUT idempotent but POST not?
>
> **A**: PUT means "make the resource at this URI be this representation" — a full-state assignment, so applying it twice lands on the same final state. POST means "process this representation according to the resource's own semantics", which is open-ended and typically creates a new subordinate resource each time. PATCH sits with POST rather than PUT because it describes a *delta* — "increment the balance by 10" applied twice increments by 20 — which is exactly why the standard resilience handler's `DisableForUnsafeHttpMethods()` covers PATCH as well as POST.
>
> **Cross-Q²**: My API has a POST `/orders` endpoint. How do I make it safe to retry?
>
> **A**: Add an idempotency-key contract. Client generates a UUID per logical create attempt, sends `Idempotency-Key: <uuid>`. Server stores `(key, response)` for a bounded window. First POST: process and store. Retry with same key: return the stored response, don't re-process. The server-side store can be Redis with a TTL. This is the conventional way to make POST retry-safe — and note it requires the *server* to cooperate, which is the whole difficulty (see Drill 17).

### Drill 16 — `BaseAddress` and relative URIs

> **Q**: `BaseAddress = new Uri("https://api.example.com/v2")` and `http.GetAsync("users")`. What URL is actually called?
>
> **A**: `https://api.example.com/users` — the `v2` segment is silently dropped. URI resolution follows the RFC 3986 §5.3 merge rule: the relative reference is merged against the base by keeping the base path *up to and including its last `/`* and discarding everything after it. `https://api.example.com/v2` has no trailing slash, so its usable base path is just `/`, and `users` is appended to that. Nothing throws; you simply call the wrong endpoint.
>
> **Cross-Q**: How do you fix it, and what's the second half of the rule?
>
> **A**: Give `BaseAddress` a trailing slash — `new Uri("https://api.example.com/v2/")` — and never start the relative path with a slash. A leading slash makes the reference an *absolute-path* reference, which replaces the base path entirely: `"/users"` resolves to `https://api.example.com/users` no matter what `BaseAddress` says. Both halves have to hold; getting one right and the other wrong still drops the prefix.
>
> **Cross-Q²**: I need to call one absolute URL from inside a typed client that has a `BaseAddress`. How?
>
> **A**: Pass an absolute `Uri`: `await http.GetAsync(new Uri("https://other.example.com/endpoint"), ct)`. When the argument is an absolute URI, `BaseAddress` is not consulted at all. `BaseAddress` only participates when the argument is a relative URI or a relative string. That's the clean escape hatch — no need for a second client just to reach one foreign host, though a second *named* client is better if the foreign host needs its own timeouts, auth, or resilience.

### Drill 17 — Retrying a POST when the server won't help

> **Q**: You need to retry a POST that creates a subscription. The vendor doesn't support idempotency keys and won't add them. What are your options?
>
> **A**: Ranked, best first. (1) **Push for server-side idempotency support** — it's the only real fix, and worth raising even if it lands next quarter. (2) **Don't retry the POST**: `options.Retry.DisableForUnsafeHttpMethods()`, and surface the failure to application logic (user-visible error, manual retry, an outbox with human review). (3) **Retry zero times but keep the circuit breaker and timeouts** — you still get fail-fast and bounded latency without duplication risk. (4) **Application-level check-then-act**: before creating, query whether a record with your unique business key (email, external order ID) already exists; retry the *read* freely and only create if absent. That's idempotency implemented on your side of the wire — extra round-trips, and a race window unless the business key is uniquely constrained server-side.
>
> **Cross-Q**: Option 4 has a race. When is it still the right answer?
>
> **A**: When the duplicate is *recoverable but expensive* rather than catastrophic, and when the business key has a real uniqueness constraint on the vendor's side so the second create fails loudly instead of succeeding twice. If the vendor enforces uniqueness, check-then-act plus "treat a duplicate-key error as success" is effectively idempotent. If it doesn't, you're only narrowing the window, and you should say so out loud rather than presenting it as a fix.
>
> **Cross-Q²**: Same vendor returns 500 both for genuine hiccups *and* for malformed requests. How do you configure retry?
>
> **A**: You can't distinguish them from the status code, so stop trying to. Three practical moves: (1) ask the vendor for a machine-readable error code in the body (`"error": "INVALID_CURRENCY"` vs `"error": "INTERNAL_ERROR"`); (2) parse the body inside `ShouldHandle` and filter on that code, since `ShouldHandle` sees the whole `HttpResponseMessage`; (3) keep the retry count low — one or two attempts — so an unretryable 500 costs little. Combined with an idempotency key where one exists, that's the pragmatic answer. Retrying a malformed request three times just triples the latency of a guaranteed failure.

### Drill 18 — Testing that resilience actually works

> **Q**: How do you test a typed client's HTTP behaviour without hitting the network?
>
> **A**: Substitute the `HttpMessageHandler`, not the `HttpClient`. Subclass `HttpMessageHandler`, override `SendAsync` to return a canned `HttpResponseMessage`, pass it to `new HttpClient(handler)`, and construct the typed client around that. For integration tests, `WebApplicationFactory` + `ConfigureTestServices` lets you re-register the client's handler for the whole host; `WireMock.Net` gives you a real local stub server when you need genuine HTTP semantics.
>
> **Cross-Q**: That proves parsing works. How do you prove the *retry* fired?
>
> **A**: Make the mock stateful and assert on the call count. A counter in the closure returns 503 on the first call and 200 on the second; the test then asserts both that the result is successful **and** that the handler was invoked exactly twice. Asserting only on the result is the classic false-positive — a pipeline with retry disabled and a mock that returns 200 immediately passes it. Keep the retry `Delay` down to a millisecond or two so the suite doesn't pay real backoff.
>
> **Cross-Q²**: How would you test that your circuit breaker opens?
>
> **A**: Drive the mock to fail enough times to satisfy both `FailureRatio` *and* `MinimumThroughput` inside `SamplingDuration`, then assert the next call throws `BrokenCircuitException` without the handler being invoked again — the call-count assertion is what proves it short-circuited rather than failed normally. This is where the shipped defaults bite: against `MinimumThroughput = 100` your test would need 100 calls, so configure a small breaker explicitly in the test rather than exercising the standard handler's defaults. For fault injection in a more realistic setup, Polly's chaos strategies (`AddChaosFault`, `AddChaosLatency`) do this at the pipeline level.

---

</details>

## Cheat Sheet

- **Socket exhaustion**: `new HttpClient()` per request → own pool per instance → sockets in kernel `TIME_WAIT` → ephemeral ports exhausted. Fix: reuse handlers.
- **Two supported lifetimes**: long-lived client + `PooledConnectionLifetime`, or short-lived clients from `IHttpClientFactory`. Nothing else.
- **`PooledConnectionLifetime` default = `Timeout.InfiniteTimeSpan`.** `HandlerLifetime` default = 2 minutes. Different knobs, different owners.
- **Set both and you have two clocks**: pair `PooledConnectionLifetime` with `SetHandlerLifetime(Timeout.InfiniteTimeSpan)`.
- **Typed client is the default**; named for runtime selection; typed clients are transient — never captured in a singleton.
- **`BaseAddress` ends with `/`; relative paths don't start with `/`.** RFC 3986 §5.3. Absolute `Uri` bypasses `BaseAddress`.
- **Handler order = registration order, first outermost.** Logging → CorrelationId → resilience → Auth → `SocketsHttpHandler`.
- **Inside the resilience handler = re-runs per attempt.** That's why auth goes there and logging doesn't.
- **`HttpClient.Timeout` default 100 s and covers all retries** → set `Timeout.InfiniteTimeSpan` under Polly.
- **Budget**: `(attempts × perAttemptTimeout) + sum(backoffs) < totalTimeout`.
- **Builder order = nesting order**: first strategy added is outermost.
- **Standard handler, 5 stages**: rate limiter 1000/0 → total timeout 30 s → retry 3 retries (= 4 attempts) / exponential / jitter / 2 s → breaker 10% / min 100 / 30 s / break 5 s → attempt timeout 10 s. **No fallback stage.**
- **`MaxRetryAttempts` counts retries, not attempts.** 3 ⇒ 4 attempts, 3 backoffs. Budget accordingly.
- **Standard handler retries every method** → `DisableForUnsafeHttpMethods()` unless the calls are idempotent.
- **Retry set**: 500+, 408, 429, `HttpRequestException`, `TimeoutRejectedException`. Never 400/401/403/404/422.
- **429 → `ShouldRetryAfterHeader`**, not a hard-coded delay.
- **Breaker is per-process, per-replica.** N replicas, N breakers.
- **Hedging ≠ retry**: fires before the first attempt resolves; buys tail latency; idempotent only.
- **`EnableMultipleHttp2Connections`** is opt-in and knowingly against RFC 9113 §9.1; the signal you need it is p99 rising with no error-rate rise.
- **Testing**: swap the `HttpMessageHandler`; assert call counts, not just results.
- **One resilience handler per client**; `RemoveAllResilienceHandlers()` to replace an inherited one.

## Walkthrough — Diagnosing Socket Exhaustion in Production

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Symptom.** A payment service that is fine in dev and staging starts throwing `SocketException: Only one usage of each socket address is normally permitted` roughly 45 minutes into each production traffic peak. It clears after a restart and comes back.

**Step 1 — confirm it's ports, not the dependency.** The exception text already points at local socket allocation rather than a remote failure, but confirm on the host:

```
[Windows]
netstat -ano | findstr TIME_WAIT
netsh int ipv4 show dynamicport tcp     -- what range do we actually have?

[Linux]
ss -s                                    -- summary incl. timewait count
sysctl net.ipv4.ip_local_port_range
```

Thousands of sockets in `TIME_WAIT` against a single destination, and a `TIME_WAIT` count in the same order of magnitude as the port range, is the signature. Correlate the count's growth with the log timestamps of the first exception.

**Step 2 — find the source.** Search for `new HttpClient(` in the call path. Here it's inside a method called once per incoming request. At low load the per-call connections retire faster than they accumulate; at production RPS they don't.

**Step 3 — understand why `using` didn't save it.** Each `HttpClient` owns its own handler and therefore its own connection pool, so nothing is shared. Disposing releases the managed object, but the kernel keeps the 4-tuple in `TIME_WAIT` for `2 × MSL` (RFC 9293) so late segments can't be misread as belonging to a new connection. The bottleneck is the protocol, not the GC.

**Step 4 — fix.** Replace per-request construction with a factory-registered typed client:

```csharp
builder.Services.AddHttpClient<PaymentClient>(c =>
{
    c.BaseAddress = new Uri("https://payment.example.com/v2/");   // trailing slash
    c.Timeout = Timeout.InfiniteTimeSpan;                          // Polly owns timeouts
})
.UseSocketsHttpHandler((handler, _) =>
{
    handler.PooledConnectionLifetime = TimeSpan.FromMinutes(2);    // DNS refresh
    handler.MaxConnectionsPerServer  = 50;
})
.SetHandlerLifetime(Timeout.InfiniteTimeSpan)      // one rotation clock, not two
.AddStandardResilienceHandler(options =>
{
    options.Retry.DisableForUnsafeHttpMethods();   // it's a payment API
});
```

Then inject `PaymentClient` everywhere the old `new HttpClient()` was, and make sure no singleton captures it.

**Step 5 — verify.** After deploy, the `TIME_WAIT` count against that destination should fall to a handful and stay flat under the same load. Add a dashboard panel for it; this failure is far cheaper to catch as a trend than as an outage.

**Two follow-on lessons worth stating in the postmortem.** `PooledConnectionLifetime` was added not for the socket problem but for the *next* one — rolling deployments change pod IPs, and without connection recycling the pool keeps dialling the old address. And `DisableForUnsafeHttpMethods()` was added because the standard handler retries POSTs by default: fixing socket exhaustion without that line would have traded an availability incident for a double-charge incident.

</details>

## Self-Test

<details>
<summary>1. Why does <code>Dispose()</code> on <code>HttpClient</code> not immediately free the TCP socket?</summary>

`Dispose()` releases the managed object and, if the client owns its handler, the pool — but the operating system then holds each closed socket in `TIME_WAIT`. That's a TCP state, not a .NET one: the connection's 4-tuple is reserved for `2 × MSL` (RFC 9293 §3.3.2) so that a segment delayed in the network from the old connection cannot be delivered into a new connection that happens to reuse the same tuple. On Windows the effective duration is governed by the `TcpTimedWaitDelay` parameter, documented with a default of 240 seconds and reducible to 30. No managed code can bypass it. The fix is not "dispose harder" but "open fewer connections" — reuse handlers.
</details>

<details>
<summary>2. A typed client with <code>AddStandardResilienceHandler()</code> gets a 401. How many retries fire, and what should you do about it?</summary>

Zero. The standard handler's retry (and breaker) handle HTTP 500-and-above, 408, 429, `HttpRequestException`, and `TimeoutRejectedException`. 401 is none of those — and correctly so, since replaying the identical request with the identical expired credential returns the identical 401. If you need 401 to trigger a token refresh, that is not a retry concern: add a `DelegatingHandler` registered **after** the resilience handler (so it sits inside and runs per attempt) that inspects the response, refreshes the credential, sets `request.Headers.Authorization`, and re-sends. Putting the refresh logic outside the resilience handler is the common mistake — it would run once and never see the retried attempts.
</details>

<details>
<summary>3. <code>BaseAddress = new Uri("https://api.example.com/v2")</code> with <code>GetAsync("users")</code> — what breaks, and why?</summary>

It calls `https://api.example.com/users`; the `v2` is silently dropped. RFC 3986 §5.3 merges a relative reference against the base by retaining the base path up to and including its last `/` and discarding the remainder. With no trailing slash the retained portion is just `/`. Fix: `https://api.example.com/v2/`. And the mirror-image trap — `GetAsync("/users")` — is an absolute-path reference that replaces the base path entirely, so it also lands on `https://api.example.com/users` even when `BaseAddress` *does* have its trailing slash. Both rules must hold.
</details>

<details>
<summary>4. What is <code>MinimumThroughput</code> for, and what is the shipped default?</summary>

It's the statistical floor: the breaker will not open until it has observed at least that many calls within `SamplingDuration`, so that one failure out of one call doesn't read as a 100% failure ratio and trip the circuit on the first hiccup. **The standard resilience handler's default is 100**, alongside a 10% failure ratio and a 30-second sampling window. That default is the thing to reason about: a client doing a couple of requests per second will never accumulate 100 calls in 30 seconds, so its breaker is effectively inert — protection you believe you have and don't. Tune it to observed traffic in both directions.
</details>

<details>
<summary>5. You add <code>AddStandardResilienceHandler()</code> to a client that POSTs orders. What have you just changed?</summary>

You have enabled retries on those POSTs. The standard handler is documented as retrying **all** HTTP methods by default, with three attempts, exponential backoff and jitter, on 500-and-above / 408 / 429 / `HttpRequestException` / `TimeoutRejectedException`. A 503 after a POST is ambiguous — the server may have processed the order and then failed, or failed before processing — so each retry risks a duplicate order. Remedies, in order: call `options.Retry.DisableForUnsafeHttpMethods()` (or `DisableFor(HttpMethod.Post)`) so POSTs aren't retried; or make the endpoint idempotent with an `Idempotency-Key` contract and then retry deliberately. What you must not do is add the line, enjoy the availability improvement, and never find out that the retry set includes your writes.
</details>

## Cross-References

- **Networking foundation:** [Networking Protocols](../../06-distributed-and-observability/04-networking-protocols.md) — TCP `TIME_WAIT`, HTTP/2 multiplexing, QUIC
- **Exception mapping at the boundary:** [Exception Handling](./13-exception-handling.md) — surfacing `HttpRequestException` and `BrokenCircuitException` to callers
- **Real-time complement:** [SignalR](./11-signalr.md)
- **API design context:** [API Design Principles](../../02-api-development/03-api-design-principles.md) — the server side of the idempotency-key contract
- **Async fundamentals:** [Async/Await & Threading](./03-async-and-threading.md) — the `CancellationToken` mechanics Polly's timeouts rely on
- **Dependency injection:** [Dependency Injection](02-dependency-injection.md) — typed-client registration lifetimes and the singleton-capture hazard
- **Configuration:** [Configuration Deep Dive](./15-configuration.md) — binding `HttpStandardResilienceOptions` from configuration, and dynamic reload

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

**Primary — Microsoft Learn**

- *Use the IHttpClientFactory* — https://learn.microsoft.com/dotnet/core/extensions/httpclient-factory — handler lifetime management, the default 2-minute `HandlerLifetime`, `UseSocketsHttpHandler` + `SetHandlerLifetime(Timeout.InfiniteTimeSpan)` guidance, message-handler DI scopes, the singleton-typed-client warning
- *HttpClient guidelines for .NET* — https://learn.microsoft.com/dotnet/fundamentals/networking/http/httpclient-guidelines — DNS behaviour, the two supported lifetime strategies, resilience with static clients, TCP `TIME-WAIT` via RFC 9293
- *Build resilient HTTP apps: key development patterns* — https://learn.microsoft.com/dotnet/core/resilience/http-resilience — the standard resilience handler's five stages and their documented defaults, the handled status codes and exceptions, `DisableFor` / `DisableForUnsafeHttpMethods`, `RemoveAllResilienceHandlers`, standard hedging handler
- *Make HTTP requests using IHttpClientFactory (ASP.NET Core)* — https://learn.microsoft.com/aspnet/core/fundamentals/http-requests — outgoing request middleware ordering ("each handler wraps the next handler")

**Primary — .NET API reference**

- `SocketsHttpHandler.PooledConnectionLifetime` — default `Timeout.InfiniteTimeSpan`
- `SocketsHttpHandler.PooledConnectionIdleTimeout` — default 1 minute on .NET 6+
- `SocketsHttpHandler.EnableMultipleHttp2Connections` — opt-in; enabling it goes against RFC 9113 §9.1
- `HttpClient.Timeout` — default 100 seconds, covering the whole operation
- `Microsoft.Extensions.Http.Resilience.HttpRetryStrategyOptions` — `ShouldRetryAfterHeader`, `DisableFor`, `DisableForUnsafeHttpMethods`
- `Microsoft.AspNetCore.Server.Kestrel.Core.Http2Limits.MaxStreamsPerConnection` — default 100

**Primary — Polly**

- Polly v8 docs — https://www.pollydocs.org/ — `ResiliencePipelineBuilder`, strategy semantics, builder order
- Polly — *Rate limiter strategy* — `RateLimiterStrategyOptions.DefaultRateLimiterOptions`, `AddConcurrencyLimiter(permitLimit, queueLimit)`
- Polly — *Hedging strategy* — `HedgingStrategyOptions<T>`, `ActionGenerator`
- Polly — *Fallback strategy* — `FallbackStrategyOptions<T>`, `Outcome.FromResultAsValueTask`
- Polly — *Chaos engineering* — Simmy absorbed into Polly v8; `AddChaosFault` / `AddChaosLatency` / `AddChaosOutcome` / `AddChaosBehavior`, placed innermost

**Standards**

- RFC 3986 — *URI Generic Syntax*, §5.3 reference resolution (the `BaseAddress` merge rule)
- RFC 9110 — *HTTP Semantics* (status code definitions, idempotency, `Retry-After`)
- RFC 9113 — *HTTP/2*, §6.5.2 `SETTINGS_MAX_CONCURRENT_STREAMS`, §9.1 connection reuse
- RFC 9293 — *Transmission Control Protocol*, §3.3.2 `TIME-WAIT`

**Background**

- Microsoft — *The default dynamic port range for TCP/IP has changed in Windows Vista and Windows Server 2008* (49152–65535)
- Microsoft — *Settings that can be modified to improve network performance* (`TcpTimedWaitDelay`)
- Steve Gordon — *Introduction to HttpClientFactory in ASP.NET Core* — https://www.stevejgordon.co.uk/introduction-to-httpclientfactory-aspnetcore — the foundational explainer, still the clearest walkthrough of the handler pipeline

---

</details>
<!-- nav-footer-start -->

---

[← Previous: Exception Handling & Result Pattern](13-exception-handling.md) · [↑ Back to top](#httpclient--resilience-polly) · [Next: Configuration Deep Dive →](15-configuration.md)

<!-- nav-footer-end -->
