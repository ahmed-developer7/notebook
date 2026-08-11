# Exception Handling & Result Pattern

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 6 — API Mastery | 2026-05-07 |

> 📘 **Main file**: Interview-ready summary, drills, and cheat sheet live in **[Exception Handling](../../04-architecture-and-patterns/08-exception-handling.md)**. This file is the implementation deep-dive.

> **Difficulty:** Intermediate to Advanced | **Reading Time:** ~35 min | **Baseline:** .NET 10 (2025-11) / 2026

---

## Why It Matters

Exceptions are the most-misused mechanism in .NET. They are simultaneously a powerful tool for flagging genuinely unexpected failures *and* a tempting hammer for ordinary control flow. Misuse produces three classes of bugs that haunt every production system:

1. **Swallowed exceptions** that hide real problems for weeks.
2. **Generic 500s** that leak stack traces or, worse, secrets.
3. **Overuse of `throw`** for things that are really *expected* outcomes — `NotFound`, `InvalidEmail`, `OutOfStock` — making the happy path unreadable and the codebase 5x slower than it needs to be.

This guide treats exceptions as a system: when they make sense, when they don't, how the .NET 10 middleware pipeline lets you map them to ProblemDetails responses without polluting controllers, and how the *Result* pattern provides a typed alternative for *expected* failures. Both are tools; pick the right one for the failure mode.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Real-World Analogy](#real-world-analogy)
3. [Exception Types](#exception-types)
4. [When to Throw vs Return Result](#when-to-throw-vs-return-result)
5. [Exception Filters and `when` Expressions](#exception-filters-and-when-expressions)
6. [Global Exception Handling](#global-exception-handling)
7. [Problem Details (RFC 9457)](#problem-details-rfc-9457)
8. [Result Pattern (Alternative to Exceptions)](#result-pattern-alternative-to-exceptions)
9. [Async, AggregateException, and ExceptionDispatchInfo](#async-aggregateexception-and-exceptiondispatchinfo)
10. [Logging and Observability](#logging-and-observability)
11. [Common Pitfalls](#common-pitfalls)
12. [Best Practices](#best-practices)
13. [Real-World Scenarios](#real-world-scenarios)
14. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
15. [Self-Test](#self-test)
16. [Cross-References](#cross-references)
17. [Sources](#sources)

---

## Introduction

### What Is an Exception?

An exception is a runtime object that signals an *abnormal* condition — something the caller could not have reasonably foreseen and that the current code path cannot recover from. The CLR unwinds the stack, runs `finally` blocks, and hands the exception to the nearest `catch` that matches.

- **Without exceptions:** Every function returns an error code. Callers must check after every call. One missed check and a corrupted state leaks downstream. The code is 60% error-checking, 40% logic.
- **With exceptions:** The happy path is uncluttered. Errors propagate automatically until somebody decides to handle them. Stack traces, inner exceptions, and structured data all come for free.

### Without Exceptions vs With Exceptions

```
WITHOUT EXCEPTIONS — return codes everywhere
============================================
int Charge(int amount, out Receipt? r) {
    if (amount <= 0) { r = null; return ERR_BAD_AMOUNT; }
    int rc = Bank.Debit(amount);
    if (rc != OK) { r = null; return rc; }
    rc = Ledger.Record(amount);
    if (rc != OK) { Bank.Refund(amount); r = null; return rc; }
    r = new Receipt(amount);
    return OK;
}

  ✗ Error-handling outweighs logic.
  ✗ Caller MUST inspect rc — easy to forget.
  ✗ No stack trace, no context, no inner cause.

WITH EXCEPTIONS — happy path is clean
=====================================
Receipt Charge(int amount) {
    if (amount <= 0) throw new ArgumentException(nameof(amount));
    bank.Debit(amount);
    ledger.Record(amount);
    return new Receipt(amount);
}

  ✓ Reader sees the intent in 4 lines.
  ✓ Stack trace + InnerException for diagnostics.
  ✓ Errors cannot be silently ignored — they propagate.
```

### Why It Matters in 2026

- .NET 10 ships a first-class `IExceptionHandler` middleware contract — no more bolted-on filters or per-controller try/catch.
- ProblemDetails (RFC 9457, which obsoleted RFC 7807) is the de-facto standard for HTTP error responses, and ASP.NET Core has full machinery for it.
- C# 8+ pattern matching makes exception classification radically cleaner.
- The Result pattern has matured into a serious alternative for *expected* business failures — increasingly common in functional-leaning .NET code.

---

## Real-World Analogy

```
EXCEPTIONS — The Smoke Detector
===============================
A smoke detector goes off when something is wrong.
You do NOT use it to announce dinner is ready.

  ✓ Fire in the kitchen           -> ALARM
  ✓ Smoke from a burnt toast      -> ALARM (annoying but valid)
  ✗ Telling someone dinner's done -> NOT what alarms are for

Exceptions are the same:
  ✓ Database connection lost      -> EXCEPTION
  ✓ NullReference in your code    -> EXCEPTION (always a bug)
  ✗ User entered an invalid email -> NOT exceptional, return Result
  ✗ Order not found               -> NOT exceptional, return 404
```

The Result pattern is the opposite end of the spectrum: a calm, expected report of "this didn't work, here's why" — the equivalent of the menu saying *"we are out of the salmon today."* Nobody's house is on fire.

---

## Exception Types

### Built-in Hierarchy (the common ones)

```
System.Exception
  ├── SystemException
  │     ├── ArgumentException
  │     │     ├── ArgumentNullException
  │     │     └── ArgumentOutOfRangeException
  │     ├── InvalidOperationException
  │     ├── NotSupportedException
  │     ├── NullReferenceException        ← always a bug
  │     ├── IndexOutOfRangeException      ← always a bug
  │     ├── OperationCanceledException
  │     │     └── TaskCanceledException
  │     ├── TimeoutException
  │     ├── IO.IOException
  │     │     └── IO.FileNotFoundException
  │     └── Net.Http.HttpRequestException
  └── ApplicationException                ← legacy; do NOT derive from this
```

### Exception Type Properties

```
+-----------------------------------------------------+
|  GOOD CUSTOM EXCEPTIONS                              |
+-----------------------------------------------------+
|  ✓ Inherit from System.Exception (NOT Application*) |
|  ✓ Three standard ctors (default, msg, msg+inner)   |
|  ✓ Carry structured data as properties              |
|  ✓ Named to express domain meaning                  |
|  ✓ Sealed when no further specialization needed     |
|  ✗ Do NOT throw to control normal flow              |
|  ✗ Do NOT catch and rethrow without enrichment      |
+-----------------------------------------------------+
```

### Custom Exception Template

```csharp
public sealed class OrderNotFoundException : Exception
{
    public int OrderId { get; }

    public OrderNotFoundException(int orderId)
        : base($"Order {orderId} was not found.")
        => OrderId = orderId;

    public OrderNotFoundException(int orderId, Exception inner)
        : base($"Order {orderId} was not found.", inner)
        => OrderId = orderId;
}
```

### When to Use Each Built-in Exception

```
+-----------------------------------+----------------------------------+
| Type                              | Throw when                       |
+-----------------------------------+----------------------------------+
| ArgumentNullException             | Required parameter is null       |
| ArgumentOutOfRangeException       | Numeric out-of-range parameter   |
| ArgumentException (others)        | Other invalid argument           |
| InvalidOperationException         | State doesn't allow operation    |
| NotSupportedException             | Feature intentionally not impl'd |
| ObjectDisposedException           | Method called on disposed object |
| OperationCanceledException        | Cancellation token was tripped   |
| TimeoutException                  | A wait period elapsed            |
| KeyNotFoundException              | Lookup returned no entry         |
+-----------------------------------+----------------------------------+
```

> **Throw helpers:** Prefer `ArgumentNullException.ThrowIfNull(arg)` and `ArgumentOutOfRangeException.ThrowIfNegative(arg)` (added in .NET 6/7) — short, intention-revealing, no allocation on the happy path.

---

## When to Throw vs Return Result

This is the single most important decision in error handling. Get it right and your code reads beautifully; get it wrong and you'll either spam logs with non-events or quietly lose real failures.

```
+----------------------------------+----------------------------------+
| Throw an exception when          | Return a Result when             |
+----------------------------------+----------------------------------+
| The failure is unexpected        | The failure is expected          |
| Caller cannot reasonably recover | Caller must routinely handle it  |
| Bug, infrastructure, or contract | Domain / validation outcome      |
| violation                        |                                  |
| Examples:                        | Examples:                        |
|   - DB connection lost           |   - Invalid email format         |
|   - Disk full                    |   - Insufficient stock           |
|   - Null where not allowed       |   - Username already taken       |
|   - JSON deserialization broken  |   - Coupon expired               |
+----------------------------------+----------------------------------+
```

### The Cost of Getting It Wrong

```
EXCEPTIONS FOR FLOW CONTROL — toxic
===================================
foreach (var s in suspectStrings) {
    try {
        var n = int.Parse(s);   // throws on every non-number
        sum += n;
    } catch (FormatException) {
        // ignore
    }
}
  ✗ Hot path allocates exceptions.
  ✗ Profiler will show this as #1 hotspot.
  ✗ Use int.TryParse — it returns bool, no allocation.

RESULT FOR INFRA FAILURES — wrong tool
======================================
public Result<Customer> GetCustomer(int id)
{
    var c = db.Customers.Find(id);   // throws SqlException on outage
    if (c is null) return Result<Customer>.Failure("not found");
    return Result<Customer>.Success(c);
}
  ✗ SqlException slips past — caller sees crash, not Result.
  ✗ Result is for *expected* outcomes, not infrastructure faults.
```

---

## Exception Filters and `when` Expressions

C# 6 introduced exception filters: a boolean `when` clause on a `catch`. Crucially, the filter runs *without unwinding the stack* — which means the original throw site, locals, and chain of frames stay intact for diagnostics if no filter matches.

### Syntax

```csharp
try
{
    await client.SendAsync(request);
}
catch (HttpRequestException ex) when (ex.StatusCode == HttpStatusCode.NotFound)
{
    return null;
}
catch (HttpRequestException ex) when (IsTransient(ex))
{
    await retry.ExecuteAsync();
}
catch (HttpRequestException) // anything else
{
    throw;
}
```

### Why Filters Beat Catch-and-Rethrow

```
WITHOUT FILTER (worse stack trace)
==================================
catch (HttpRequestException ex)
{
    if (ex.StatusCode == HttpStatusCode.NotFound) return null;
    throw;          // stack already partially unwound
}

WITH FILTER (clean stack trace, no unwind)
==========================================
catch (HttpRequestException ex) when (ex.StatusCode == HttpStatusCode.NotFound)
{
    return null;
}
catch (HttpRequestException) { throw; }   // not even entered
```

### Side-Effect-Free Filter Pattern

Filters can call methods, but those methods must be **side-effect free**. A common pattern is conditional logging that doesn't otherwise alter behavior:

```csharp
catch (Exception ex) when (LogAndContinue(ex))
{
    // never reached because LogAndContinue returns false
}

static bool LogAndContinue(Exception ex)
{
    Log.Error(ex, "Unhandled");
    return false;   // forces the runtime to keep searching
}
```

---

## Global Exception Handling

ASP.NET Core 8+ introduced `IExceptionHandler` as the modern, DI-friendly hook for centralized exception handling. .NET 10 keeps it as the recommended approach.

### `UseExceptionHandler` vs `UseStatusCodePages` vs `UseDeveloperExceptionPage`

```
+--------------------------+-----------------------------------------+
| Middleware               | Purpose                                 |
+--------------------------+-----------------------------------------+
| UseDeveloperExceptionPage| Dev-only verbose HTML page with stack   |
|                          | NEVER expose in production.             |
+--------------------------+-----------------------------------------+
| UseExceptionHandler      | Catches unhandled exceptions, replaces  |
|                          | the response, runs IExceptionHandlers.  |
+--------------------------+-----------------------------------------+
| UseStatusCodePages       | Adds a body to bare 4xx/5xx responses   |
|                          | that have no body of their own.         |
+--------------------------+-----------------------------------------+
```

### The Modern Pipeline

```csharp
var app = builder.Build();

if (app.Environment.IsDevelopment())
    app.UseDeveloperExceptionPage();
else
    app.UseExceptionHandler();          // runs IExceptionHandler chain

app.UseStatusCodePages();               // for 4xx without bodies
```

### `IExceptionHandler` Contract (.NET 8+)

```
+--------------------------------------------------------+
|  IExceptionHandler Properties                           |
+--------------------------------------------------------+
|  ✓ TryHandleAsync returns true when handled           |
|  ✓ Returning false passes to the next handler         |
|  ✓ Multiple handlers run in registration order        |
|  ✓ Full DI — inject ILogger, IHostEnvironment, etc.   |
|  ✗ HttpContext.Response cannot be already started     |
|  ✗ Do NOT throw from inside (rethrows are fatal)      |
+--------------------------------------------------------+
```

### Walkthrough: Map Domain Exceptions to ProblemDetails

```
Pipeline:
  Request -> ... -> EndpointInvoked -> throws OrderNotFoundException
                          |
                          v
                +-----------------------+
                | UseExceptionHandler   |
                +-----------------------+
                          |
                          v
                +-----------------------+
                | DomainExceptionHandler|  <- TryHandleAsync = true
                |  - 404 Not Found      |
                |  - ProblemDetails     |
                +-----------------------+
                          |
                          v
                Response sent to client
```

```csharp
public sealed class DomainExceptionHandler(
    IProblemDetailsService problem,
    IHostEnvironment env) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(
        HttpContext ctx, Exception ex, CancellationToken ct)
    {
        var (status, title, type) = ex switch
        {
            OrderNotFoundException     => (404, "Order not found",     "https://errors.example.com/order-not-found"),
            ValidationException        => (400, "Validation failed",   "https://errors.example.com/validation"),
            ConcurrencyException       => (409, "Conflict",            "https://errors.example.com/conflict"),
            UnauthorizedAccessException => (403, "Forbidden",          "https://errors.example.com/forbidden"),
            _                          => (500, "Server error",        "https://errors.example.com/server-error")
        };

        ctx.Response.StatusCode = status;

        return await problem.TryWriteAsync(new ProblemDetailsContext
        {
            HttpContext = ctx,
            Exception = ex,
            ProblemDetails = new ProblemDetails
            {
                Status = status,
                Title  = title,
                Type   = type,
                Detail = env.IsDevelopment() ? ex.ToString() : null
            }
        });
    }
}

// Program.cs
builder.Services.AddProblemDetails();
builder.Services.AddExceptionHandler<DomainExceptionHandler>();
builder.Services.AddExceptionHandler<FallbackExceptionHandler>(); // last resort
```

---

## Problem Details (RFC 9457)

### What Is ProblemDetails?

RFC 9457 (which obsoleted RFC 7807 in 2023) defines a standard JSON shape for HTTP error responses. ASP.NET Core's `ProblemDetails` is the corresponding type. Using it consistently means clients (web, mobile, third-party) only have to learn one error format.

```
+---------------+----------------------------------------------+
| Field         | Meaning                                       |
+---------------+----------------------------------------------+
| type          | URI identifying the *kind* of problem        |
| title         | Short human-readable summary                 |
| status        | HTTP status code (mirrors the response code) |
| detail        | Specific human-readable message              |
| instance      | URI for *this* occurrence                    |
| (extensions)  | Any additional structured data               |
+---------------+----------------------------------------------+
```

### Example Response

```json
{
  "type": "https://errors.example.com/order-not-found",
  "title": "Order not found",
  "status": 404,
  "detail": "Order 42 was not found.",
  "instance": "/api/orders/42",
  "traceId": "00-7d8e1d8...-01",
  "orderId": 42
}
```

### Validation Problem Details

For 400 validation responses, use `ValidationProblemDetails` which adds the `errors` dictionary:

```json
{
  "type": "https://errors.example.com/validation",
  "title": "Validation failed",
  "status": 400,
  "errors": {
    "Email":  ["The Email field is required."],
    "Amount": ["Must be greater than zero."]
  }
}
```

### When to Use ProblemDetails

```
✅ Use ProblemDetails when:
   - Building HTTP APIs consumed by other services or SPAs
   - You want one error contract across all endpoints
   - Clients should be able to programmatically classify errors

❌ Skip ProblemDetails when:
   - Endpoint returns plain text or HTML by design
   - Internal RPC over a custom binary protocol
   - You're streaming and the connection is half-open
```

---

## Result Pattern (Alternative to Exceptions)

The Result pattern represents *expected* failure as a value, not a throw. It's the typed equivalent of "this might or might not work" and forces the caller to handle both branches at compile time.

### Anatomy

```
+---------------------------------------------+
|  RESULT<T> Properties                       |
+---------------------------------------------+
|  ✓ One value: Success(T) OR Failure(Error) |
|  ✓ Compile-time forced branching           |
|  ✓ Composable: chain Map/Bind/Match        |
|  ✓ No exception allocation in hot paths    |
|  ✗ Slightly more verbose than throw        |
|  ✗ Doesn't replace exceptions for bugs     |
+---------------------------------------------+
```

### Reference Implementation

```csharp
public class Result<T>
{
    public T? Value { get; }
    public string? Error { get; }
    public bool IsSuccess => Error is null;

    private Result(T value) => Value = value;
    private Result(string error) => Error = error;

    public static Result<T> Success(T value) => new(value);
    public static Result<T> Failure(string error) => new(error);

    public TResult Match<TResult>(
        Func<T, TResult> onSuccess, Func<string, TResult> onFailure)
        => IsSuccess ? onSuccess(Value!) : onFailure(Error!);
}
```

### Service + Controller Pattern

```csharp
// Service:
public async Task<Result<Order>> PlaceOrderAsync(CreateOrderRequest req)
{
    if (req.Items.Count == 0)
        return Result<Order>.Failure("Order must have at least one item");

    var order = await _repo.CreateAsync(MapToOrder(req));
    return Result<Order>.Success(order);
}

// Controller:
[HttpPost]
public async Task<IActionResult> PlaceOrder(CreateOrderRequest req)
{
    var result = await _service.PlaceOrderAsync(req);
    return result.Match<IActionResult>(
        order => CreatedAtAction(nameof(Get), new { id = order.Id }, order),
        error => BadRequest(new { error }));
}
```

### Result vs Exceptions Side-by-Side

```
+-------------------+-------------------------------+
| Exceptions        | Result Pattern                |
+-------------------+-------------------------------+
| Unexpected errors | Expected business failures    |
| System failures   | Validation errors             |
| Unrecoverable     | "Not found" scenarios         |
+-------------------+-------------------------------+
```

```
DECISION TREE
=============
  Could a careful developer reasonably foresee this outcome
  and want to handle it differently from a "real" error?
       |
       v
   YES -> Result<T>          (validation, "not found", domain rules)
   NO  -> throw               (DB down, null arg, contract violation)
```

For a richer treatment (typed errors, OneOf, library landscape), see the dedicated [Result Pattern guide](../../04-architecture-and-patterns/03-result-pattern.md).

---

## Async, AggregateException, and ExceptionDispatchInfo

### Awaited Tasks: Exceptions Unwrap Cleanly

```csharp
try
{
    await SomeAsyncMethod();
}
catch (HttpRequestException ex) // single exception, not Aggregate
{
    // ...
}
```

The compiler unwraps the *first* inner exception of an awaited Task. You almost always want `await`, not `.Result` or `.Wait()`.

### `Task.WhenAll` Behavior

```
WAITING ON MULTIPLE TASKS
=========================

Task.WhenAll(t1, t2, t3) — all three fail:

  await Task.WhenAll(t1, t2, t3);
  // throws ONE of the inner exceptions (the first observed)
  // The other failures are stored on the returned Task.Exception

  // To see all of them:
  var task = Task.WhenAll(t1, t2, t3);
  try { await task; }
  catch
  {
      foreach (var ex in task.Exception!.InnerExceptions)
          Log.Error(ex, "One of the parallel tasks failed");
  }
```

### `AggregateException` in Async

`AggregateException` is mostly a Task-Parallel-Library legacy. With `await`, you rarely see it — *except* for `Task.WhenAll`'s underlying `Exception` property and any code that calls `.Wait()` / `.Result`. Treat its appearance as a code smell of synchronous-over-async.

### `ExceptionDispatchInfo` — Re-throwing Without Losing the Stack

When you must catch an exception in one place and rethrow it later (e.g. background task → main thread), `throw caught;` resets the stack trace. `ExceptionDispatchInfo` preserves it.

```csharp
ExceptionDispatchInfo? captured = null;
try
{
    await DoWorkAsync();
}
catch (Exception ex)
{
    captured = ExceptionDispatchInfo.Capture(ex);
}

// Later, possibly on a different thread/context:
captured?.Throw();   // original stack trace intact
```

### When Cancellation Is Not An Error

```csharp
try
{
    await streamer.RunAsync(ct);
}
catch (OperationCanceledException) when (ct.IsCancellationRequested)
{
    // Expected. Don't log as error. Don't return 500.
}
```

### Properties

```
+------------------------------------------------------+
|  ASYNC EXCEPTION HANDLING                            |
+------------------------------------------------------+
|  ✓ await unwraps the first inner exception          |
|  ✓ Task.WhenAll surfaces one but holds all          |
|  ✓ ExceptionDispatchInfo preserves stack on rethrow |
|  ✓ OperationCanceledException is expected on cancel |
|  ✗ .Wait() / .Result wrap in AggregateException     |
|  ✗ Forgetting `await` swallows exceptions silently  |
+------------------------------------------------------+
```

---

## Logging and Observability

### Always Log With Context

```csharp
catch (Exception ex)
{
    log.LogError(ex,
        "Charge failed for Order {OrderId}, Customer {CustomerId}",
        orderId, customerId);
    throw;
}
```

```
+------------------------------------------------------+
|  GOOD EXCEPTION LOGS                                  |
+------------------------------------------------------+
|  ✓ Pass the exception as the FIRST argument         |
|  ✓ Use structured properties (not string.Format)    |
|  ✓ Include correlation/trace IDs                    |
|  ✓ Log once at the boundary, not at every frame     |
|  ✗ Log AND throw — duplicates noise                 |
|  ✗ Log only ex.Message — loses stack and inner ex   |
+------------------------------------------------------+
```

### Trace ID Pattern

`HttpContext.TraceIdentifier` — or `Activity.Current?.Id` for OpenTelemetry — should appear on every problem detail and every log line. That single ID lets you go from a user's screenshot to the full server-side context in one query.

```csharp
problemDetails.Extensions["traceId"] =
    Activity.Current?.Id ?? ctx.TraceIdentifier;
```

---

## Common Pitfalls

### 1. Catch Everything, Do Nothing

```csharp
try { ... }
catch { }           // swallow EVERYTHING — bug magnet
```
Symptom: features mysteriously stop working with no log line. *Never* catch without at least logging.

### 2. Catching `Exception` to "Be Safe"

```csharp
catch (Exception ex) { /* handle 7 different things */ }
```
You will eventually catch a `StackOverflowException` (you can't handle it), an `OutOfMemoryException` (you shouldn't), or a typo's `NullReferenceException` (you want it loud, not buried). Catch the specific types you actually handle.

### 3. `throw ex;` Instead of `throw;`

```csharp
catch (Exception ex)
{
    log.LogError(ex, "Boom");
    throw ex;   // ← resets the stack trace to THIS line
}
```
Use bare `throw;`. Use `ExceptionDispatchInfo.Capture(ex).Throw()` only when you need to delay the rethrow.

### 4. Exceptions for Flow Control

`int.Parse` in a tight loop on user input. `Dictionary` lookups via try/catch on `KeyNotFoundException`. Each is 100-1000x slower than the `TryX` equivalent.

### 5. Returning `null` to Signal "Not Found" *and* Throwing on Other Errors

Mixed signals are the worst of both worlds. Pick: throw a domain `NotFoundException` *or* return a `Result<T>` *or* return a nullable. Don't mix in one method's contract.

### 6. Catching `OperationCanceledException` and Logging As Error

Cancellation is normal. A user closed a tab. A deadline elapsed. Logging it at error level pollutes alerts. Filter it out or log at debug.

### 7. Forgetting `ConfigureAwait(false)` In a Library

In legacy SynchronizationContext-bound code, omitting `ConfigureAwait(false)` can deadlock when a sync caller calls `.Wait()`. Library code should opt out unless it explicitly needs the captured context.

### 8. Letting Exceptions Leak Internal Details

A 500 response containing a SQL connection string, server path, or full stack is a security incident. Map all unhandled exceptions to a generic 500 ProblemDetails in production. Stack only in dev.

### 9. Re-Throwing Inside `catch` *and* `finally`

A `throw` inside `finally` swallows the original exception of `try` and replaces it. Almost always a bug — keep `finally` to disposal/cleanup, not control flow.

### 10. `using` Around an `await` of a Long-Running Stream Without Cancellation

Cancelling a hung downstream call leaves the `using` waiting forever to dispose, which holds locks. Always pass a `CancellationToken` and observe it with timeouts.

---

## Best Practices

1. **Use exceptions for the exceptional.** Bugs, infrastructure faults, contract violations. Not for "user typed an invalid email."
2. **Use `Result<T>` for expected business failures.** Validation, domain rule violations, "not found." Forces the caller to handle them at compile time.
3. **Throw with helpers.** `ArgumentNullException.ThrowIfNull(arg)` is shorter, allocation-free on the happy path, and self-documenting.
4. **Catch the narrowest type that matters.** `catch (HttpRequestException ex) when (...)` beats `catch (Exception ex)` in 95% of cases.
5. **Centralize HTTP exception → ProblemDetails mapping** in an `IExceptionHandler`. Controllers stay focused on the happy path.
6. **Always include a trace ID** in ProblemDetails extensions. Production debugging demands it.
7. **Use `throw;` not `throw ex;`.** Stack traces are gold; don't reset them.
8. **Use `ExceptionDispatchInfo`** when you must capture and rethrow across an async/thread boundary.
9. **Treat `OperationCanceledException` specially.** Filter, don't error-log. A 200 user-cancel and a 500 fault should not look the same in your dashboards.
10. **Log once, at the boundary.** Catching, logging, and rethrowing repeatedly multiplies noise without adding signal.
11. **Never swallow silently.** Even a one-line `log.LogDebug` is infinitely better than `catch { }`.
12. **Don't expose stack traces in production responses.** Map to a stable ProblemDetails `type` URL and let logs hold the detail.
13. **Validate early; throw `ArgumentException` at the public boundary.** Internal helpers can assume valid input, which simplifies their bodies.
14. **Custom exceptions carry data.** A `OrderNotFoundException` should know its `OrderId`. Strings parsed from messages are an antipattern.

---

## Real-World Scenarios

### Scenario 1: REST API With Consistent Error Responses

```
+----------------------------------------------------------+
|  Requirement: every error from any endpoint returns      |
|  ProblemDetails with status, type, title, detail,        |
|  trace ID, and (in dev only) stack.                      |
+----------------------------------------------------------+

Pipeline:
  app.UseExceptionHandler()
     -> DomainExceptionHandler  (404/400/409/403 from custom types)
     -> FallbackExceptionHandler (500 with sanitized message)
  app.UseStatusCodePages()      // bodies for bare 4xx

Controllers:
  Throw OrderNotFoundException(id) — never return null mixed with throw.
  Throw ValidationException(errors) for invalid input.
  Return Result<T> at the service layer; controllers translate.
```

### Scenario 2: Retry Logic in a Queue Consumer

```
+----------------------------------------------------------+
|  Requirement: a worker pulls messages, processes each.   |
|  Transient faults retry; poison messages dead-letter.    |
+----------------------------------------------------------+

while (await reader.WaitToReadAsync(ct))
{
    var msg = await reader.ReadAsync(ct);
    try
    {
        await ProcessAsync(msg, ct);
    }
    catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
    catch (Exception ex) when (IsTransient(ex) && msg.Attempts < 5)
    {
        msg.Attempts++;
        await retryQueue.PublishAsync(msg, delay: Backoff(msg.Attempts), ct);
        log.LogWarning(ex, "Transient fail; retrying {Id} attempt {N}", msg.Id, msg.Attempts);
    }
    catch (Exception ex)
    {
        await deadLetter.PublishAsync(msg, reason: ex.GetType().Name, ct);
        log.LogError(ex, "Dead-lettering {Id}", msg.Id);
    }
}
```

### Scenario 3: Logging Exception Context Across Async Boundaries

```
+----------------------------------------------------------+
|  Requirement: a request logs a traceId. A background     |
|  worker awaits a Channel and processes messages          |
|  produced by various requests. Each log line must        |
|  carry the original requesting traceId.                  |
+----------------------------------------------------------+

Producer side:
  channel.Writer.WriteAsync(new WorkItem(payload, Activity.Current?.Id));

Consumer side:
  while (await reader.WaitToReadAsync(ct))
  {
      var item = await reader.ReadAsync(ct);
      using var activity = source.StartActivity("ProcessItem",
          ActivityKind.Internal, parentId: item.TraceParent);
      try { await Handle(item, ct); }
      catch (Exception ex)
      {
          // Log includes traceId because Activity.Current is set
          log.LogError(ex, "Failed item {ItemId}", item.Id);
          ExceptionDispatchInfo.Capture(ex).Throw();
      }
  }
```

---

## 24. Exception Handling & Result Pattern

This section preserves the original anchor (`#24-exception-handling--result-pattern`) used by upstream documents.

### Problem Details (RFC 9457)

```csharp
builder.Services.AddExceptionHandler<GlobalExceptionHandler>();
builder.Services.AddProblemDetails();

public class GlobalExceptionHandler : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(
        HttpContext context, Exception exception, CancellationToken ct)
    {
        var problemDetails = exception switch
        {
            NotFoundException nf => new ProblemDetails
            {
                Status = 404, Title = "Not Found", Detail = nf.Message
            },
            ValidationException ve => new ValidationProblemDetails(ve.Errors)
            {
                Status = 400, Title = "Validation Error"
            },
            _ => new ProblemDetails
            {
                Status = 500, Title = "Server Error",
                Detail = "An unexpected error occurred"
            }
        };

        context.Response.StatusCode = problemDetails.Status ?? 500;
        await context.Response.WriteAsJsonAsync(problemDetails, ct);
        return true;
    }
}
```

### Result Pattern (Alternative to Exceptions)

This anchor (`#result-pattern-alternative-to-exceptions`) is referenced from [Result Pattern](../../04-architecture-and-patterns/03-result-pattern.md). Full discussion above; the canonical reference snippet:

```csharp
public class Result<T>
{
    public T? Value { get; }
    public string? Error { get; }
    public bool IsSuccess => Error is null;

    private Result(T value) => Value = value;
    private Result(string error) => Error = error;

    public static Result<T> Success(T value) => new(value);
    public static Result<T> Failure(string error) => new(error);

    public TResult Match<TResult>(
        Func<T, TResult> onSuccess, Func<string, TResult> onFailure)
        => IsSuccess ? onSuccess(Value!) : onFailure(Error!);
}
```

```
+-------------------+-------------------------------+
| Exceptions        | Result Pattern                |
+-------------------+-------------------------------+
| Unexpected errors | Expected business failures    |
| System failures   | Validation errors             |
| Unrecoverable     | "Not found" scenarios         |
+-------------------+-------------------------------+
```

---

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Throw vs Return Result

> **Q**: When should I throw an exception vs return a `Result<T>`?
>
> **A**: Throw for **unexpected** conditions — bugs, contract violations, infrastructure faults. Return `Result<T>` for **expected** business outcomes — validation failures, "not found," domain rule violations. The litmus test: would a careful developer write code that *routinely* handles this outcome? If yes, Result. If no, throw.
>
> **Cross-Q**: A user passes an invalid email format. Throw `ValidationException` or return `Result.Failure`?
>
> **A**: At the **service-layer boundary**, return `Result<T>` — the controller branches cleanly into `400 BadRequest` or `200 OK`. At the **public API of a domain entity** (constructor or factory), throw — the entity should never exist in an invalid state. So the choice depends on layer: outward-facing service returns Result; inward-facing domain throws. They compose: the service catches the domain throw and converts it to a Result for the caller.
>
> **Cross-Q²**: What's the perf delta of throwing for every invalid email in a bulk import of 10,000 rows?
>
> **A**: Roughly 50-200µs per throw on modern .NET 8+ (it was worse in older versions). For 10k rows, that's 0.5-2 seconds of pure exception cost — easily 50% of the request budget. **Throwing for routine input validation is the most common perf footgun in .NET.** Result/TryParse-style APIs are the fix. The compiler optimizes the success path of a Result to near-zero overhead.

### Drill 2 — `IExceptionHandler` vs `UseExceptionHandler`

> **Q**: What's the difference between `IExceptionHandler` (.NET 8+) and the older `UseExceptionHandler(errorApp => ...)`?
>
> **A**: `UseExceptionHandler` is the *middleware* that catches unhandled exceptions and gives you a chance to write a response. `IExceptionHandler` is a *DI-friendly contract* that lets you register multiple handler classes; `UseExceptionHandler()` (no args) walks them in registration order until one returns `true`. The lambda form is fine for tiny apps; the interface form scales to multiple exception families with full DI.
>
> **Cross-Q**: What happens if my `IExceptionHandler.TryHandleAsync` throws?
>
> **A**: Catastrophic — the response is half-written, the request gets a connection-reset, and any further handlers in the chain are skipped. The middleware logs the secondary exception but cannot recover. **Rule: handlers must be bulletproof — wrap their own bodies in try/catch.**
>
> **Cross-Q²**: I have two handlers — one for domain exceptions, one fallback. The first returns `false`. What does the second see?
>
> **A**: The same `HttpContext` and the same `Exception`. **But** — if the first handler started writing to `HttpContext.Response` before returning `false`, the second handler will fail because the response has already been committed. **Rule: handlers must not write to the response unless they're going to return `true`**. Defer all `Response.WriteAsync` calls until you've decided to handle.

### Drill 3 — ProblemDetails

> **Q**: When is `ProblemDetails` automatic in ASP.NET Core, and when do I have to construct it explicitly?
>
> **A**: With `builder.Services.AddProblemDetails()` registered, the framework automatically returns ProblemDetails for: 4xx/5xx without an existing body (via `UseStatusCodePages`), unhandled exceptions (via `UseExceptionHandler`), and `Results.Problem(...)` in minimal APIs. Explicit construction is needed when you want custom fields, custom `type` URIs, or to map specific exception types in your `IExceptionHandler`.
>
> **Cross-Q**: What's the role of the `type` URI in ProblemDetails — is it dereferenceable?
>
> **A**: It's a **stable identifier**, not a fetchable URL by spec. Most teams use a docs URL (e.g., `https://errors.example.com/order-not-found`) that *does* host a description page. The contract guarantee is "the same `type` URI means the same kind of problem forever" — clients can match on it to classify errors programmatically without parsing the human-readable `title`.
>
> **Cross-Q²**: How does ProblemDetails interact with content negotiation?
>
> **A**: It respects the request's `Accept` header. JSON clients get `application/problem+json`; XML clients (rare) get `application/problem+xml`. If the client sends `text/html` and you registered no HTML formatter for ProblemDetails, you'll get JSON regardless — the framework prefers a valid response over a 406 Not Acceptable. **Tip: log the `Accept` header on 4xx — a surprising number of API bugs are clients setting the wrong Accept and getting a "weird" response.**

### Drill 4 — AggregateException unwrapping

> **Q**: I have `Task<int> t = SomeAsync(); int r = t.Result;` and `SomeAsync` throws `InvalidOperationException`. What does the caller see?
>
> **A**: `AggregateException` wrapping the `InvalidOperationException`. `.Result` and `.Wait()` always wrap. To get the unwrapped exception, switch to `await t`, which unwraps the first inner exception.
>
> **Cross-Q**: I have `Task.WhenAll(t1, t2, t3)` where all three throw. What does `await` give me?
>
> **A**: It throws **one** exception — the first one observed (effectively the first to fault). The other two are lost from the `await` site but **preserved on `task.Exception.InnerExceptions`** of the returned Task. To see all three: `var t = Task.WhenAll(...); try { await t; } catch { foreach (var ex in t.Exception!.InnerExceptions) ... }`.
>
> **Cross-Q²**: Why doesn't `await` unwrap all `AggregateException.InnerExceptions`?
>
> **A**: Because `await` was designed for the common case of a single fault, where unwrapping makes try/catch read naturally. Unwrapping multiple exceptions would force every `await` site to handle `AggregateException` — defeating the whole point of `await`. The trade-off is: simple, mostly-right unwrapping at the cost of losing siblings unless you grab `task.Exception` explicitly. **This is why `Task.WhenAll` is the only async API where you commonly need both `await` and explicit `.Exception` inspection.**

### Drill 5 — ExceptionDispatchInfo

> **Q**: Why use `ExceptionDispatchInfo.Capture(ex).Throw()` instead of just `throw ex;`?
>
> **A**: `throw ex` **resets the stack trace** to the throw point — you lose the original throw site. `ExceptionDispatchInfo.Capture(ex).Throw()` preserves the original stack trace and adds a "rethrow at" frame. For "caught here, rethrown there" patterns (background workers, completion sources, marshaling across threads) it's the only way to keep diagnostics.
>
> **Cross-Q**: When can I use bare `throw;` instead?
>
> **A**: Only **inside the same catch block** that caught the exception. `throw;` (no operand) inside a catch preserves the stack — the C# compiler is smart enough. But once you've stashed the exception in a variable and crossed a method or thread boundary, bare `throw;` is no longer in scope; that's exactly where `ExceptionDispatchInfo` is required.
>
> **Cross-Q²**: Can I capture and rethrow the same exception multiple times?
>
> **A**: Yes — `ExceptionDispatchInfo.Capture(ex)` can be stored and `.Throw()` called more than once. Each rethrow appends a new "rethrow at" frame to the stack. **Pattern**: catch once in a `Channel`-based pipeline, capture, propagate the captured info through the channel, and the consumer rethrows. Each subscriber that rethrows adds its own frame, building a full causal chain.

### Drill 6 — Async exception propagation

> **Q**: This compiles but exceptions silently disappear: `async void Handler() { await DoAsync(); }`. Why?
>
> **A**: `async void` has no `Task` for the exception to land on. The compiler emits code that posts the exception to the current `SynchronizationContext` — in ASP.NET Core that's basically nowhere, and the exception crashes the process or gets swallowed depending on host configuration. **`async void` is only safe for event handlers** (where the event has an explicit error-propagation contract).
>
> **Cross-Q**: How do I make a method that returns void but propagates exceptions?
>
> **A**: Return `Task` instead of `void`, and document that callers must `await` it. If the consumer is an event-handler signature you can't change, write a tiny adapter: `async void OnClick(object s, EventArgs e) { try { await DoAsync(); } catch (Exception ex) { Log(ex); } }` — the catch is required because there's no upstream to propagate to.
>
> **Cross-Q²**: I have `var t = SomeAsync(); /* forget to await */`. Does the exception fire?
>
> **A**: Eventually, when the Task is garbage-collected. The CLR raises `TaskScheduler.UnobservedTaskException` (an AppDomain-level event). In .NET Core, by default this **does not crash the app** (changed from .NET Framework). The exception is logged via that event handler if you've subscribed, otherwise it's silently lost. **Forgetting to `await` is the most insidious async bug** — code looks like it works, exceptions vanish. Linters catch this (CS4014 if you call it inside an async method).

### Drill 7 — try/catch/finally + using

> **Q**: A `using` statement throws inside `Dispose`. What happens to the exception from the try body?
>
> **A**: `using` lowers to `try/finally`. If both the body and `Dispose` throw, **the body exception is lost** — the `Dispose` exception propagates. This is the "exception masking in finally" problem. To preserve both: don't put cleanup code that can fail inside `Dispose`, or use `await using` with an `IAsyncDisposable` that can be observed via try/catch around the `using` block.
>
> **Cross-Q**: What's the order of `try { } catch (A) { } catch (B) { } finally { } `?
>
> **A**: Body runs. If it throws, the runtime walks catches in declaration order, picking the first that matches by type (no LSP fallthrough except in derived-class match). The matched catch runs. **Then finally runs regardless** — exception or no exception, return or no return, even on `goto`. If the catch itself throws, that new exception replaces the body's; finally still runs.
>
> **Cross-Q²**: Can I use `await` inside `finally`?
>
> **A**: Yes — and you should, when cleanup is genuinely async (closing a stream, releasing a lock with `SemaphoreSlim`). The compiler lowers the async state machine to handle await-in-finally correctly. **Gotcha**: if the body threw, and the awaited cleanup throws, the body exception is lost (same masking problem). Pattern: capture body exception, do cleanup, then `ExceptionDispatchInfo.Capture(captured).Throw()`.

### Drill 8 — Custom exception types

> **Q**: When do you create a custom exception type vs use a built-in one like `InvalidOperationException`?
>
> **A**: Custom when the exception carries **domain data** the catcher needs (`OrderNotFoundException.OrderId`), or when callers will programmatically branch on the type. Built-in when the failure is generic and the catcher needs only the message. **Rule**: if you find yourself parsing `ex.Message` to extract an ID or code, you needed a custom type.
>
> **Cross-Q**: Should custom exceptions inherit from `Exception` or `ApplicationException`?
>
> **A**: `Exception`. `ApplicationException` was a misguided 1.0-era idea to separate "app" from "system" exceptions; Microsoft itself reversed course and now says **do not derive from `ApplicationException`**. Inherit directly from `Exception` (or a relevant built-in like `InvalidOperationException` if the meaning fits).
>
> **Cross-Q²**: My custom exception is `[Serializable]`. Do I need the serialization constructor?
>
> **A**: In .NET Framework: yes (`protected MyException(SerializationInfo info, StreamingContext context) : base(info, context)`) — for cross-AppDomain marshaling. In .NET 8+: **no**. Binary serialization of exceptions is obsoleted (and a known security risk). Modern systems serialize via JSON for transport. You can drop the `[Serializable]` attribute entirely for new code targeting .NET 8+.

### Drill 9 — Exception filters (`when` clause)

> **Q**: What's the difference between `catch (X ex) when (cond)` and `catch (X ex) { if (!cond) throw; ... }`?
>
> **A**: The filter is evaluated **without unwinding the stack**. If the condition is false, the search continues for a later matching catch, with the original throw site and locals still intact. The if/throw approach has already unwound to the catch frame; even bare `throw;` then reflects the unwind. For diagnostics and "first-chance" debugger behavior, filters are strictly better.
>
> **Cross-Q**: Can filter conditions have side effects (e.g., logging)?
>
> **A**: They can, but **must be idempotent and cheap**. Filters run while the runtime is searching for a handler — across an entire stack. A filter that does I/O, takes a lock, or allocates heavily slows every exception walk by that cost. **Common pattern**: a "log and continue" filter that always returns false: `catch (Exception ex) when (LogAndReturnFalse(ex)) { /* unreachable */ }`. The runtime continues searching after; the log is captured at the throw site.
>
> **Cross-Q²**: Are exception filters JIT-optimized in .NET 8+?
>
> **A**: The filter body is JIT-compiled like any other code. The runtime executes it via two-pass exception handling (first pass: search and run filters; second pass: unwind and run matched catch + finally). The two-pass model is why filters preserve the stack — they execute in the original frame *before* unwind. In .NET 8+ this is unchanged but JIT improvements (esp. tiered + PGO) reduce per-filter cost. Not worth worrying about unless your filters are doing real work.

### Drill 10 — `Task.WhenAll` exception semantics

> **Q**: `await Task.WhenAll(t1, t2)` where `t1` faults but `t2` succeeds. What's the outcome?
>
> **A**: `await` throws `t1`'s exception. `t2`'s result is on the returned task as `t2.Result` (you have to inspect it explicitly via `t2.Status == TaskStatus.RanToCompletion`).
>
> **Cross-Q**: What if both `t1` and `t2` fault?
>
> **A**: `await` throws one (effectively `t1`'s — the first observed). Both faults are on `aggregateTask.Exception.InnerExceptions`. To handle both: assign the task, `await` in try/catch, then iterate the aggregate task's InnerExceptions.
>
> **Cross-Q²**: How is this different from `Task.WhenAny(t1, t2)`?
>
> **A**: `WhenAny` returns the **first task to complete** (success *or* failure). It doesn't throw — you await the returned `Task<Task>` and then await the inner task to observe its outcome. Use `WhenAny` for "race the fastest" or "use the first responder" patterns. **Trap**: `WhenAny` does not cancel the loser tasks — they keep running until they complete or you cancel via a shared CancellationToken.

### Drill 11 — Logging exceptions

> **Q**: What fields belong in an exception log line?
>
> **A**: The full `Exception` object (as the first ILogger argument), correlation/trace ID, request ID, user/tenant ID (sanitized), and any domain identifiers the catch site has. **Not** `ex.Message` alone — you lose the stack and inner exceptions. **Not** PII (passwords, full PANs, raw card data).
>
> **Cross-Q**: What's the right structured-log shape?
>
> **A**: Use a message template with named placeholders: `log.LogError(ex, "Order {OrderId} failed for customer {CustomerId}", orderId, customerId)`. The exception goes as the **first argument** (special ILogger signature). The template lets log sinks (Seq, ELK, Splunk) index `OrderId` and `CustomerId` as searchable fields — far more useful than a free-form sentence.
>
> **Cross-Q²**: I log at error level and then `throw;`. Is this duplicated noise?
>
> **A**: **Yes — and it's the most common logging antipattern.** The upstream handler will catch and log again, producing duplicate errors with different stacks. Fix: log **once, at the boundary** (the global handler), and let intermediate layers throw. Exception filters can do conditional logging without changing behavior. **Log at the boundary, throw between layers.**

### Drill 12 — Exception type to status code

> **Q**: What mapping do you use for domain exceptions to HTTP status codes?
>
> **A**: A typical mapping in `IExceptionHandler`: `*NotFoundException → 404`, `ValidationException → 400`, `UnauthorizedAccessException → 403`, `ConcurrencyException → 409`, `TimeoutException → 504`, `OperationCanceledException → 499 (client closed connection)`, everything else → 500.
>
> **Cross-Q**: Why 499 for cancellation and not 408 Request Timeout?
>
> **A**: 408 means "the server timed out waiting for the client's request." 499 (nginx-coined, widely supported) means "the client closed the connection while the server was processing." Cancellation in a server typically means the client gave up — that's 499. If your server itself timed out waiting on a downstream, that's 504 Gateway Timeout. **Distinguishing client vs server cancellation in logs is what tells you whether to fix the client UI or the backend latency.**
>
> **Cross-Q²**: A `KeyNotFoundException` from a `Dictionary` lookup bubbles up. Should I map it to 404?
>
> **A**: **No.** That's a *bug* — a domain "not found" should be a `OrderNotFoundException` (or `Result.Failure`), not a raw `KeyNotFoundException` leaking from internal collections. Mapping it to 404 hides the bug and lets your API return 404 for an internal programming error. Fix the throw site to use the right exception. Leave the catch-all at 500 — that way the bug screams.

### Drill 13 — `OperationCanceledException`

> **Q**: Should `OperationCanceledException` be logged as an error?
>
> **A**: **No, almost never.** Cancellation is expected: user closed a tab, deadline elapsed, parent operation gave up. Logging at error level pollutes alerts. Log at debug or information level — and only when correlated with a cancellation token *you* tripped. In a global handler, suppress entirely or log at debug.
>
> **Cross-Q**: How do I distinguish "client canceled" from "server-initiated cancellation"?
>
> **A**: Compare `ex.CancellationToken` to the request's `HttpContext.RequestAborted` token (client) vs your own timeout token (server). If they match: client canceled. If a server token tripped first: your timeout fired. **Standard pattern**: combine tokens with `CancellationTokenSource.CreateLinkedTokenSource(httpContext.RequestAborted, myTimeoutToken)` and check `myTimeoutToken.IsCancellationRequested` to attribute correctly.
>
> **Cross-Q²**: Inside `IExceptionHandler`, can I return `true` for `OperationCanceledException` and write a body?
>
> **A**: You can return `true` (handled), but **writing a body is usually pointless** — the client connection is gone. Just set the response status code (499) and return `true`; ASP.NET Core won't bother to write headers/body once the connection has aborted. **Pattern**: short-circuit cancellation at the top of your handler: `if (ex is OperationCanceledException) return ValueTask.FromResult(true);`.

### Drill 14 — Domain vs infrastructure exceptions

> **Q**: How do you organize the exception type hierarchy for a domain-rich app?
>
> **A**: Two parallel families. **Domain**: `DomainException` base, subclasses per business rule (`OrderNotFoundException`, `InvalidOrderStateException`). **Infrastructure**: usually built-in (`HttpRequestException`, `SqlException`, `IOException`) — don't wrap unless you're crossing a layer boundary. The `IExceptionHandler` maps domain → 4xx and lets infrastructure fall through to 500.
>
> **Cross-Q**: Should I wrap infrastructure exceptions in a domain exception at the repository boundary?
>
> **A**: **Only if** the upper layers need to handle them as domain failures (e.g., "DB unavailable" → "system busy, try again"). Wrapping with no behavior change is just noise. Most teams let `SqlException` propagate and rely on Polly + the global handler to convert it to a 503 / retry-after. The wrap is justified when the upper layer's response is meaningfully different from "server error."
>
> **Cross-Q²**: How do I avoid leaking SQL details to the client?
>
> **A**: The global handler maps unknown exceptions to a generic 500 ProblemDetails with no `Detail` in production. Stack traces and exception types stay in logs only. **Test this**: write an integration test that triggers a SQL exception and asserts the response body contains no "Sql", "connection", or stack-trace markers. It's a one-line test that catches every accidental leak.

### Drill 15 — Performance cost of throwing

> **Q**: When does the cost of throwing exceptions actually matter?
>
> **A**: In hot loops where exceptions occur frequently — typically parsing untrusted input, dictionary lookups by missing key, format conversion. Each throw is ~50-200µs on .NET 8+. At 1k throws/sec that's ~150ms of CPU; at 10k/sec you've burned 1-2 seconds of every server-second on exception machinery alone. **Rule**: any code path where the "exceptional" outcome happens more than 1% of calls is a candidate for Try/Result patterns instead.
>
> **Cross-Q**: Why is throwing so expensive — the stack walk?
>
> **A**: Several factors: building the `Exception` object (allocates), capturing the full call stack (walks frames, resolves symbols), traversing every catch in the call stack to find a match, running first-pass filters, unwinding (second pass) and running `finally` blocks. PGO and the JIT have reduced the cost over the years, but there's no free fast path — it's structural to how exceptions work.
>
> **Cross-Q²**: Are `Exception.HResult` and `Exception.StackTrace` lazily captured?
>
> **A**: `StackTrace` is captured at throw time (the OS stack walk is part of the throw). `Exception.StackTrace` (the *string* property) is lazily formatted on first access — that's why a thrown-and-immediately-rethrown exception is faster than one whose `.StackTrace` is read at log time. `HResult` is set when the exception is constructed (default value or from a constructor). **Bottom line**: throwing is the expensive part. Logging the stack is cheap by comparison.

---

</details>

---

## Self-Test

<details>
<summary>1. Rewriting <code>catch (HttpRequestException ex) { if (!IsTransient(ex)) throw; … }</code> as <code>catch (HttpRequestException ex) when (IsTransient(ex))</code> runs the same code. What actually changes?</summary>

*Which* `catch` body runs is identical. *When the decision is made* is not. The CLR dispatches an exception in two passes: the first walks up the stack looking for a handler and evaluates every `when` filter it meets; the second unwinds the frames between the throw site and the handler that agreed to take it, running `finally` and fault blocks on the way.

A `when` filter is evaluated in pass one, before anything unwinds. If it returns `false`, the search simply continues — the throw site, its locals, and every frame in between are still on the stack. The `if (!cond) throw;` version has already committed to the catch: pass two has run, every intervening `finally` and `using` disposal has already executed, and those frames are gone. Bare `throw;` preserves the exception's accumulated stack trace, but it cannot un-dispose anything or bring the frames back.

What that costs in production: a first-chance break or a crash dump now points at your rethrowing `catch` rather than at the code that actually failed, and the state you most wanted in that dump — the request being processed, the retry counter, the connection object — was torn down on the way up. The same two-pass property is the whole trick behind the `when (LogAndContinue(ex))` pattern above: the filter returns `false`, the runtime keeps searching, and the log line is captured with the stack still standing at the original throw.

The flip side is the constraint. Filters run during the search, potentially across the whole stack, for every exception that passes through. Keep them cheap and side-effect free — I/O or a lock acquisition inside a filter taxes every exception walk that reaches it.
</details>

<details>
<summary>2. Your <code>DomainExceptionHandler</code> sets <code>ctx.Response.StatusCode = 404</code>, <code>TryWriteAsync</code> returns <code>false</code>, so the handler returns <code>false</code>. What does <code>FallbackExceptionHandler</code> inherit?</summary>

A response the first handler already touched, because the middleware only resets once. `ExceptionHandlerMiddlewareImpl` calls `ClearHttpContext(context)`, sets `Response.StatusCode` to its default (500, or whatever a configured `StatusCodeSelector` returns), and *then* enters the `foreach` over the registered handlers, breaking on the first `TryHandleAsync` that returns `true`. Nothing is cleared between handlers.

So the fallback sees `StatusCode == 404`. If it was written assuming a clean slate and only writes a body, the client gets a 500-shaped payload under a 404 status line — a nasty bug, because each half looks correct in isolation. That is the concrete reason behind the contract-box rule: don't mutate the response unless you are going to return `true`.

The `TryWriteAsync` half deserves its own answer, because the handler on this page does `return await problem.TryWriteAsync(...)` — it hands its own handled/not-handled verdict straight to the problem-details service. That call returns `false` when every registered `IProblemDetailsWriter` declines, and the default writer declines when the request's `Accept` header is incompatible with JSON. A client asking for `text/html` therefore falls through to your fallback even though the domain mapping matched perfectly. Decide handled-ness yourself; treat `false` from `TryWriteAsync` as "the body didn't get written," not as "this wasn't my exception."

And the hard boundary: if the response has already *started* when the exception reaches the middleware, none of this runs at all. The middleware logs, records the exception as skipped, and rethrows — once headers are sent the status code can no longer be changed, exception handlers can't run, and the response must be completed or the connection aborted. The client gets a truncated body or a reset, not ProblemDetails.
</details>

<details>
<summary>3. A client team wants the <code>type</code> URI renamed to read better, and the database error text put in <code>detail</code> so their support tool can parse it. Push back on both.</summary>

**On `type`.** It is the stable, machine-readable identity of the *kind* of problem, and it is what clients branch on to classify an error without parsing prose. Renaming it is a breaking change to your error contract, exactly like renaming a JSON field: every client matching the old URI silently drops into its default branch and starts reporting "unknown error" for a case it used to handle correctly. `title` is the field that is allowed to read better — RFC 9457 calls it advisory, "included only for users who are unaware of and cannot discover the semantics of the type URI." If the meaning genuinely changes, mint a new URI rather than repointing the old one. Two related facts worth knowing: the URI is not required to resolve to anything (hosting a docs page there is convention, not obligation), and when `type` is absent its value is assumed to be `about:blank`.

**On `detail`.** RFC 9457 is explicit that consumers SHOULD NOT parse `detail` for information, and that extension members are the more suitable and less error-prone way to carry structured data. If the support tool needs the order id, give it an extension — `"orderId": 42`, exactly as in the example response above — not a sentence it has to regex. `detail` is a human-readable explanation of *this* occurrence.

**On the database error text specifically.** It should not reach the response at all in production. Unhandled infrastructure exceptions map to a generic 500 with no `Detail`; the provider message, the stack, and any connection information stay in logs, correlated by the `traceId` extension. That is what `Detail = env.IsDevelopment() ? ex.ToString() : null` in the handler is guarding, and a 500 body carrying a connection string or a server path is a security incident rather than a debugging convenience.
</details>

<details>
<summary>4. A teammate changes a repository method to return <code>Result&lt;Customer&gt;</code> and says callers can no longer ignore failures. What did that not fix?</summary>

Infrastructure faults — and the signature now lies about them. `db.Customers.Find(id)` still throws on an outage, so the method advertises "every failure comes back as a value" while a whole class of failures still leaves as a throw. A caller who writes `if (result.IsSuccess)` and nothing else crashes on the first database blip, and crashes *more* confidently than before, because the return type told them they had it covered. `Result<T>` is for expected outcomes; a dead connection is not an expected outcome.

The line to draw: throw when the failure is unexpected and the caller cannot reasonably recover — a bug, an infrastructure fault, a contract violation. Return `Result<T>` when the failure is expected and the caller must routinely handle it: invalid email, insufficient stock, coupon expired, "not found." The deciding test is whether a careful developer would foresee the outcome and want to branch on it differently from a real error.

The second thing to check is that the method now has *one* contract. Mixing signals — `null` for "not found," a `Result.Failure` for validation, and a throw for everything else, all from one method — is the worst of both worlds, because no caller can tell which shape to defend against. Pick one per method. Layers may legitimately differ: a domain constructor or factory throws, because the entity must never exist in an invalid state, and the outward-facing service catches that and converts it to a `Result` for its own caller.

On cost, keep the argument structural rather than reaching for a multiplier. Throwing allocates the exception object, captures the stack at the throw site, then runs a two-pass search across the call stack evaluating filters and executing `finally` blocks. None of that has a fast path — it is how exceptions work. So any path where the "exceptional" branch is routine (parsing untrusted input in a loop, looking up a key you expect to be missing) is where `TryParse`, `TryGetValue`, and `Result<T>` belong, and where a profiler will find you.
</details>

<details>
<summary>5. <code>await Task.WhenAll(t1, t2, t3)</code> — all three fault, and you get one line in your logs. Where did the other two go?</summary>

Awaiting a faulted task rethrows exactly one exception. `TaskAwaiter` pulls the task's list of captured `ExceptionDispatchInfo` objects and throws the first one. Because the rethrow goes through `ExceptionDispatchInfo`, the original stack trace survives — but the siblings are never surfaced at the `await` site.

They are not lost, though. They are on the task you discarded. `Task.WhenAll` returns a task that, if any input faults, completes Faulted with "the aggregation of the set of unwrapped exceptions from each of the supplied tasks." Keep the reference and read it:

```csharp
var task = Task.WhenAll(t1, t2, t3);
try { await task; }
catch
{
    foreach (var ex in task.Exception!.InnerExceptions)
        log.LogError(ex, "One of the parallel tasks failed");
}
```

`.Result` or `.Wait()` would have handed you the `AggregateException` wrapper with all three inside — but the stack trace then points at the blocking call rather than at the failing work, and blocking a context-capturing caller is the deadlock shape you are trying to avoid in the first place. Getting the full set that way is the wrong trade; assign the task instead.

Why it matters operationally: three parallel downstream calls, one region goes dark, all three fail. Your alert names a single endpoint. You fix that one, ship, and the next deploy fails identically on the other two — a correlated outage disguised as a flaky single dependency.

Related, for when you need to *move* an exception rather than just observe it: `ExceptionDispatchInfo.Capture(ex)` followed by `.Throw()` later restores the state saved at capture and marks the seam in the trace with `--- End of stack trace from previous location ---`. (Don't grep your logs for the longer sentence the API-reference remarks still quote — that wording predates .NET Core. The live resource, `Exception_EndStackTraceFromPreviousThrow` in CoreLib, is the short form.) `throw ex;` resets the stack trace to that line, and bare `throw;` is only legal inside the `catch` block that caught the exception — which is precisely why crossing a thread or channel boundary needs `ExceptionDispatchInfo`.
</details>

---

## Cross-References

- **Architecture deep-dive:** [Exception Handling (architecture)](../../04-architecture-and-patterns/08-exception-handling.md)
- **Result pattern:** [Result Pattern (deep-dive)](../../04-architecture-and-patterns/03-result-pattern.md)
- **Async fundamentals:** [Async/Await & Threading](./03-async-and-threading.md)
- **HTTP middleware:** [Middleware in ASP.NET Core](./04-middleware.md)
- **Resilience:** [HttpClient & Resilience](./14-httpclient-resilience.md) — where exceptions cross network boundaries
- **API security:** [Security & Authentication](./09-security.md) — `UnauthorizedAccessException` mapping

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — *Handle errors in ASP.NET Core* (`https://learn.microsoft.com/aspnet/core/fundamentals/error-handling`)
- Microsoft Learn — *Exceptions* (`https://learn.microsoft.com/dotnet/standard/exceptions/`)
- RFC 9457 — *Problem Details for HTTP APIs* (`https://datatracker.ietf.org/doc/html/rfc9457`), which obsoleted RFC 7807
- C# Language Reference — *Exception filters (when)*
- .NET API Reference — `System.Runtime.ExceptionServices.ExceptionDispatchInfo`
- .NET API Reference — `Microsoft.AspNetCore.Diagnostics.IExceptionHandler`

---

</details>
<!-- nav-footer-start -->

---

[← Previous: Modern C# Features](12-modern-csharp.md) · [↑ Back to top](#exception-handling--result-pattern) · [Next: HttpClient & Resilience (Polly) →](14-httpclient-resilience.md)

<!-- nav-footer-end -->
