# .NET Version History (.NET 7 → .NET 10)

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Reference | High | Phase 1 — Language & Runtime Fluency | 2026-05-07 (post .NET 10 GA) |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [The release cadence — LTS vs STS](#the-release-cadence--lts-vs-sts)
  - [.NET 7 (Nov 2022, STS — out of support)](#net-7-nov-2022-sts--out-of-support)
  - [.NET 8 (Nov 2023, LTS — supported through Nov 2026)](#net-8-nov-2023-lts--supported-through-nov-2026)
  - [.NET 9 (Nov 2024, STS — out of support May 2026)](#net-9-nov-2024-sts--out-of-support-may-2026)
  - [.NET 10 (Nov 2025, LTS — supported through Nov 2028)](#net-10-nov-2025-lts--supported-through-nov-2028)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--upgrading-net-8-to-net-10-in-production)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Microsoft has shipped a major .NET release every November since the .NET 5 unification. Each release alternates LTS (3-year support) and STS (Standard-Term Support, 18 months). Senior .NET engineers need version literacy: which features arrived when, which versions are still supported, what's gained by upgrading. Interviewers ask "what's new in .NET 8?" or "why .NET 10 over .NET 9?" — knowing the answer is table stakes for senior roles.

This file is the canonical reference inside the guide for "what changed and when." The other 17 files explain *how* features work; this one anchors them in time and helps you talk about upgrade paths.

How to read this file:
- **Each version section** lists language → runtime → ASP.NET Core → EF Core → libraries → tooling.
- **Bold = the headliner** for that release (the feature you'd lead with in an interview).
- **(.NET X+)** annotations elsewhere in the guide point back to this file for context.

When NOT to over-index on this: don't pick projects by the latest version alone. **LTS releases (.NET 8, .NET 10)** are the production safe bets. STS (.NET 7, .NET 9) are interesting but expire fast.

## Core concepts

### The release cadence — LTS vs STS

```
                 Nov 2022      Nov 2023      Nov 2024      Nov 2025      Nov 2026
                    │             │             │             │             │
                  .NET 7        .NET 8        .NET 9        .NET 10       (.NET 11)
                  STS           LTS           STS           LTS           STS
                  18 months     3 years       18 months     3 years       18 months
                  EOL May'24    EOL Nov'26    EOL May'26    EOL Nov'28    EOL May'28
```

- **LTS (Long-Term Support):** 36 months of patches. Even-numbered versions: .NET 6, 8, 10, 12.
- **STS (Standard-Term Support):** 18 months of patches. Odd-numbered: .NET 5, 7, 9, 11.

**Production rule of thumb:** target LTS for systems you don't want to upgrade twice a year. Target STS for greenfield work where you want the newest features and accept the upgrade cadence.

As of May 2026:
- **.NET 6** (LTS, Nov 2021): out of support since Nov 2024.
- **.NET 7** (STS, Nov 2022): out of support since May 2024.
- **.NET 8** (LTS, Nov 2023): supported through Nov 2026 — many production systems on this.
- **.NET 9** (STS, Nov 2024): out of support May 2026 — about to fall off.
- **.NET 10** (LTS, Nov 2025): the current production target. Supported through Nov 2028.

### .NET 7 (Nov 2022, STS — out of support)

Released alongside C# 11. The "performance and AOT polish" release.

**Language — C# 11:**
- **`required` members** — `public required string Name { get; init; }` forces the caller to set it; replaces ad-hoc constructor validation.
- **Raw string literals** — `"""..."""` for multi-line strings, JSON, SQL embedded in C# without escape soup.
- **List patterns** — `if (arr is [1, 2, .., 9, 10]) { ... }`.
- **Generic math (static abstract members in interfaces)** — `INumber<T>`, `IAddable<T>`, etc. enables `T Sum<T>(IEnumerable<T>) where T : INumber<T>`.
- **File-scoped types** — `file class X` visible only within the file; great for source generators.
- **UTF-8 string literals** — `"abc"u8` returns `ReadOnlySpan<byte>` directly; avoids encoding overhead in hot paths.
- **`ref` fields and `scoped` ref** — enabled `Span<T>` to live as a struct field.

**Runtime / GC / JIT:**
- **NativeAOT for console apps** went GA — single-file, ahead-of-time compiled binaries with no JIT and minimal startup time.
- **On-Stack Replacement (OSR)** — hot methods recompile in place during execution.
- **Profile-Guided Optimization (PGO) — preview** — JIT learns hot paths from runtime profiles.
- **~1,000+ performance PRs** documented by Stephen Toub.

**ASP.NET Core:**
- **`MapGroup`** for Minimal APIs — `app.MapGroup("/orders").RequireAuthorization()` for shared route prefixes and metadata.
- **Endpoint filters** — middleware-like behaviour at the per-endpoint level.
- **Output caching middleware** — `app.UseOutputCache()` + `[OutputCache]` attribute.
- **Rate limiting middleware** — `Microsoft.AspNetCore.RateLimiting` GA with token-bucket / sliding-window / fixed-window / concurrency limiters.
- **gRPC JSON transcoding** — expose gRPC services as REST without dual-implementation.

**EF Core 7:**
- **`ExecuteUpdate` / `ExecuteDelete`** — bulk operations without loading entities into memory.
- **JSON columns** for SQL Server, mapped as owned subdocuments.
- **`DateOnly` / `TimeOnly`** mapped to native DB types.

**Libraries / BCL:** `TimeSpan.FromXxx` overloads taking `int`; `[StringSyntax]` attribute for IDE highlighting; rate-limiting primitives in `System.Threading.RateLimiting`.

**Tooling:** `dotnet publish /t:PublishContainer` builds a Docker image without a Dockerfile.

### .NET 8 (Nov 2023, LTS — supported through Nov 2026)

The big LTS release. Many production systems still run on this in 2026.

**Language — C# 12:**
- **Primary constructors for classes** — `public class OrderService(IRepo repo, ILogger log) { ... }`. Saves boilerplate; the parameters are in scope throughout the class. Records had this since C# 9; classes get it now.
- **Collection expressions** — `int[] x = [1, 2, 3];`, `List<int> y = [1, 2, 3];`, spread with `[..first, ..second]`.
- **Default lambda parameters** — `(int x = 10) => x * 2`.
- **Alias any type** — `using IntDict = System.Collections.Generic.Dictionary<int, int>;`.
- **Inline arrays** — `[InlineArray(8)] struct Buffer { byte _e0; }` for fixed-size struct arrays.
- **Experimental attribute** — `[Experimental("DiagId")]` flags APIs as preview.

**Runtime / GC / JIT:**
- **Dynamic PGO on by default** — typical 5–20% throughput uplift on real workloads.
- **NativeAOT for ASP.NET Core (Minimal APIs)** — Minimal API apps can publish AOT-only. Trade-off: no `Microsoft.AspNetCore.Mvc` controllers, no reflection-heavy serializers.
- **Tiered compilation improvements** including **DynamicPGO + ReadyToRun composite mode**.

**ASP.NET Core:**
- **`MapIdentityApi<TUser>()`** — opinionated identity-as-API for SPAs and mobile, separate from the cookie/MVC Identity stack.
- **Keyed services in DI** — `services.AddKeyedScoped<IFoo>("primary", PrimaryFoo)`; resolve with `[FromKeyedServices("primary")]`.
- **`IExceptionHandler`** — first-class global exception handling registered via `services.AddExceptionHandler<MyHandler>()`.
- **HTTP/3 enabled by default** in Kestrel.
- **Blazor United** — Server + WebAssembly + Static SSR + Streaming + per-component interactivity in one app model.

**EF Core 8:**
- **Complex types (value objects)** — `[ComplexType]` mapping for owned-type-like patterns without the weird ID semantics.
- **Hierarchy mapping (TPC, TPT, TPH)** stabilised.
- **`Json` column improvements** including for Postgres jsonb.
- **Raw SQL queries returning unmapped types** — `db.Database.SqlQuery<DTO>($"SELECT ...")`.

**Libraries / BCL:**
- **`TimeProvider`** — abstract clock; injectable into tests; replaces ad-hoc `DateTime.Now` mocks.
- **`FrozenDictionary<K,V>` / `FrozenSet<T>`** — read-optimised immutable collections, faster lookups than `Dictionary<K,V>`.
- **`Random.GetItems` / `Random.Shuffle`**.
- **`System.Numerics.Tensors`** for SIMD-accelerated math.

**Tooling / containers:**
- **`dotnet publish /p:PublishProfile=DefaultContainer`** with chiseled Ubuntu base images for tiny, secure containers.
- **`.NET Aspire` preview** — opinionated stack for cloud-ready distributed apps (orchestration, OpenTelemetry, dashboard).

### .NET 9 (Nov 2024, STS — out of support May 2026)

The "polish and observability" release. Many shops skipped 9 to wait for 10's LTS.

**Language — C# 13:**
- **`params` collections** — `params` works for any `IEnumerable<T>`-compatible type, not just arrays. `void Log(params ReadOnlySpan<string> args)` allocates zero.
- **`System.Threading.Lock`** — `private Lock _l = new();` then `lock (_l) { ... }`. Faster than locking on `object` and clearer intent.
- **Partial properties** — like partial methods, useful for source generators.
- **`\e` escape sequence** for ESC character (terminal control codes).
- **`field` keyword (preview)** — refer to a property's backing field inside `get`/`set`. Promoted to GA in C# 14.
- **Implicit index access in object initializers** — `new T { [^1] = value }`.

**Runtime / GC / JIT:**
- **More dynamic PGO improvements** — better inlining heuristics, devirtualization.
- **GC reduces commit churn** on long-running services.
- **Loop optimizations** for vectorization.

**ASP.NET Core:**
- **Built-in OpenAPI** — `builder.Services.AddOpenApi()` + `app.MapOpenApi()` produces an OpenAPI document from Minimal APIs. Replaces Swashbuckle for new projects (Swashbuckle still supported).
- **HybridCache (preview → GA)** — combines `IMemoryCache` (L1) and `IDistributedCache` (L2) with stampede protection. The pattern most production apps roll by hand, now first-party.
- **Static asset delivery improvements** — fingerprinted asset URLs, automatic compression.
- **Improved Blazor static SSR** — server-rendered with progressive enhancement.

**EF Core 9:**
- **Improved `ExecuteUpdateAsync`** — accepts compiled-query-like patterns.
- **Better `Json` query support** with provider-specific operators.
- **Read-only context performance** improvements.

**Libraries / BCL:**
- **LINQ `CountBy` / `AggregateBy` / `Index`** — `items.CountBy(x => x.Category)` returns `IEnumerable<KeyValuePair<TCategory, int>>`. `Index()` adds index numbers like Python's `enumerate`.
- **ReDoS attack detection** in regex compilation.
- **`OrderedDictionary<TKey, TValue>`** — generic ordered dictionary in BCL.

**Tooling:**
- **.NET Aspire 9 GA** — distributed-app dev experience matures (Postgres, Redis, RabbitMQ, Kafka resources; OpenTelemetry wired by default; dashboard).

### .NET 10 (Nov 2025, LTS — supported through Nov 2028)

The current LTS. **Default target for new production work** in 2026.

**Language — C# 14:**
- **Extension members beyond methods** — extension *properties*, *operators*, and *static members*. The biggest C# language change in years:
  ```csharp
  public static class StringExtensions
  {
      extension(string s)
      {
          public bool IsBlank => string.IsNullOrWhiteSpace(s);
          public string Reversed => new(s.Reverse().ToArray());
      }
  }
  
  "hello".IsBlank   // false, used like a property on string
  "hello".Reversed  // "olleh"
  ```
- **`field` keyword** — promoted from preview. Inside a property accessor, `field` refers to the auto-generated backing field, no need to declare it explicitly:
  ```csharp
  public string Name
  {
      get;
      set => field = value?.Trim() ?? throw new ArgumentNullException();
  }
  ```
- **Null-conditional assignment** — `obj?.Property = value;` (no-op if `obj` is null).
- **Partial constructors and partial events** — for source generators.
- **`nameof` over unbound generics** — `nameof(List<>)`.
- **Unsafe lambdas / lambdas with modifiers** — `static`, `unsafe` on lambdas.
- **User-defined compound assignment** — overload `+=`, `-=`, etc. directly without overloading the base operator.
- **Implicit span conversions** — `string` → `ReadOnlySpan<char>` works without explicit `.AsSpan()`.

**Runtime / GC / JIT:**
- **NativeAOT improvements** — closer to feature parity with full runtime; better library compatibility.
- **More dynamic PGO** — devirtualization across more call sites.
- **GC region-based heap improvements** for sustained-load services.
- **Stack-allocated arrays** — small array allocations escape-analyzed onto the stack.

**ASP.NET Core:**
- **Server-Sent Events (SSE) helpers in Minimal APIs** — `Results.ServerSentEvents(IAsyncEnumerable<T>)` for streamed responses.
- **Memory-efficient validation** — new validation pipeline reduces allocations.
- **Granular static-asset optimization** — per-asset compression / fingerprinting policies.
- **Blazor diagnostics improvements** and simpler form-state management.
- **Improved OpenAPI** — better handling of polymorphic types, generic type parameters.

**EF Core 10:**
- **Continued perf improvements** in change tracking and query translation.
- **Better complex-type support**.
- **Improved migrations** for online schema changes.

**Libraries / BCL:**
- **Continued LINQ additions** and reflection improvements for source generators.
- **Performance**: smaller allocations across HTTP and JSON code paths.

**Tooling:**
- **`dotnet run` improvements** — runs single-file C# programs with `#:package` directives for inline package references (the "shebang for C#" experience).
- **.NET Aspire 10** — production deployment story matures (Azure / AWS / GCP integrations).

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Release timeline

```
2022     2023     2024     2025     2026     2027     2028
  │        │        │        │        │        │        │
  ▼        ▼        ▼        ▼        ▼        ▼        ▼
.NET 7   .NET 8   .NET 9   .NET 10  (.NET 11) (.NET 12) ...
STS      LTS      STS      LTS       STS       LTS
─────    ──────────────    ──────────────
EOL      EOL Nov 2026      EOL Nov 2028
May 2024
         ──── EOL May 2026 ────
```

LTS releases (.NET 8, 10, 12 ...) overlap with the next LTS — you have time to upgrade.

### Headline features at a glance

| Area | .NET 7 (STS) | .NET 8 (LTS) | .NET 9 (STS) | .NET 10 (LTS) |
|---|---|---|---|---|
| Language | C# 11 | C# 12 | C# 13 | C# 14 |
| Top language feature | required, raw strings | primary constructors, collection expressions `[...]` | `params` collections, `Lock` | extension members (everything), `field` |
| AOT | Console GA | ASP.NET Minimal APIs | Continued | Near feature parity |
| OpenAPI | Swashbuckle | Swashbuckle | **Built-in `AddOpenApi`** | Built-in (improved) |
| Identity | Cookie/MVC | + `MapIdentityApi` | continued | continued |
| Hybrid cache | manual | manual | **`HybridCache`** | continued |
| HTTP/3 | preview | **default** | default | default |
| Aspire | — | preview | **9 GA** | 10 GA |
| Container build | `dotnet publish` | chiseled bases | continued | continued |
| Bulk EF ops | `ExecuteUpdate`/`Delete` | improved | improved | improved |
| Default ports | 5000 / 5001 | 5000 / 5001 | 5000 / 5001 | 5000 / 5001 |

### Five key code samples — one per major release

**C# 11 — `required` members + raw string literals (.NET 7):**
```csharp
public class OrderRequest
{
    public required string CustomerId { get; init; }
    public required decimal Total { get; init; }
}

var json = """
    {
        "customerId": "abc-123",
        "total": 99.50
    }
    """;
```

**C# 12 — primary constructor + collection expression (.NET 8):**
```csharp
public class OrderService(IOrderRepository repo, ILogger<OrderService> log)
{
    private static readonly string[] AllowedStatuses = ["Pending", "Paid", "Shipped"];

    public async Task<Order> PlaceAsync(int[] items)
    {
        log.LogInformation("Placing order with {Count} items", items.Length);
        return await repo.CreateAsync(items);
    }
}
```

**C# 13 — params collections + Lock (.NET 9):**
```csharp
private readonly Lock _gate = new();

public void LogAll(params ReadOnlySpan<string> messages)
{
    lock (_gate)
    {
        foreach (var m in messages) Console.WriteLine(m);
    }
}

LogAll("a", "b", "c");   // zero-allocation params
```

**C# 14 — extension members + field keyword (.NET 10):**
```csharp
public static class StringExtensions
{
    extension(string s)
    {
        public bool IsEmail => s.Contains('@') && s.Contains('.');
        public string Trimmed => s.Trim();
    }
}

if (input.IsEmail) { /* ... */ }

public class Product
{
    public string Name
    {
        get;
        set => field = value?.Trim() ?? throw new ArgumentNullException(nameof(value));
    }
}
```

**ASP.NET Core .NET 9 — built-in OpenAPI:**
```csharp
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddOpenApi();           // .NET 9+ replaces Swashbuckle for many cases

var app = builder.Build();
app.MapOpenApi();                         // serves /openapi/v1.json
app.MapGet("/orders/{id}", (int id) => Results.Ok(new { id, status = "Paid" }));
app.Run();
```

### Upgrade cost (rough rule of thumb)

```
.NET 6  → .NET 8   (LTS to LTS)   : low-medium effort; some package nuget bumps
.NET 7  → .NET 8   (STS to LTS)   : low effort; mostly transparent
.NET 8  → .NET 10  (LTS to LTS)   : low-medium; AOT-paths benefit most
.NET 9  → .NET 10  (STS to LTS)   : trivial in most cases
─────────────────────────────────
EF Core: bump EF Core nuget independently; usually backward-compatible.
Aspire: more churn; pin Aspire version separately.
NativeAOT: re-test every upgrade; library compatibility shifts.
```

</details>
## Common pitfalls

1. **Shipping production on STS (.NET 7, 9, 11).** 18-month support window. You'll be forced to upgrade twice as often as on LTS. Pick LTS for systems you don't want to babysit.
2. **Targeting `net8.0` while running `dotnet --version 10.0.x` SDK.** Works, but make sure your `<TargetFramework>` matches what you actually deploy. Mixed SDK/runtime versions in CI vs local cause confusing build errors.
3. **NativeAOT compatibility surprises.** Some libraries (especially older ones, anything heavy on reflection / `Activator.CreateInstance`) don't AOT. Test `dotnet publish -p:PublishAot=true` before committing.
4. **Assuming Swashbuckle still required on .NET 9+.** Built-in `AddOpenApi` covers most cases. Swashbuckle remains for advanced features (XML comments, custom filters), but new projects should start with built-in.
5. **Treating `params` collections as drop-in.** Calling code that passes `null` to `params ReadOnlySpan<T>` fails differently from `params T[]`. Test edge cases.
6. **Mixing C# language versions across a solution.** `<LangVersion>latest</LangVersion>` per project; consistent across the solution. Otherwise newer features fail to compile in older projects.
7. **Forgetting EF Core's bulk operations skip change tracking.** `ExecuteUpdateAsync` doesn't fire `SaveChangesAsync` interceptors. Audit columns / soft-delete cascades / domain events all bypass.
8. **Identity API confusion.** `MapIdentityApi` is the new lightweight one; cookie/MVC Identity still exists separately. Don't try to use both.
9. **HybridCache without configuring distributed backing.** Without an `IDistributedCache` registered, HybridCache falls back to L1-only — silently. Verify both are wired.
10. **Aspire pinned across major versions.** Aspire's API evolves faster than .NET itself. Pin Aspire NuGet versions explicitly; expect breaking changes between major .NET upgrades.
11. **Reading `<TargetFramework>net9.0</TargetFramework>` and assuming "current."** Source code captures intent at write time; .NET 10 may be the better target now. When upgrading, multi-target if you have library consumers; bump TFM if you control deployment.
12. **STS-to-STS upgrade gap.** If you're on .NET 9 and the next LTS (.NET 10) is what you want, you upgrade through .NET 10 — there's no skipping. Plan it as a single bump, not two.

## Interview-ready summary

- **Cadence:** new release every November. Even = LTS (3 yrs), odd = STS (18 months).
- **As of May 2026:** .NET 8 (LTS) and .NET 10 (LTS) are supported; .NET 9 expires this month.
- **.NET 7** brought C# 11 (required, raw strings, generic math), Minimal API filters, output cache + rate limiting, EF Core bulk ops.
- **.NET 8** is the big LTS — C# 12 (primary constructors, collection expressions), NativeAOT for ASP.NET, identity API, keyed DI, HTTP/3 default, `TimeProvider`, frozen collections.
- **.NET 9** added C# 13 (params collections, Lock), built-in OpenAPI, HybridCache, LINQ `CountBy`/`AggregateBy`, Aspire 9 GA.
- **.NET 10** is the current LTS — C# 14 (extension members beyond methods, field keyword, null-conditional assignment), more AOT polish, SSE in Minimal APIs.
- **Production guidance:** target LTS unless you need a feature only on STS. Multi-target libraries; pin SDK in `global.json`.

**Expected interview questions:**

1. *"What's new in .NET 8?"* — LTS release. C# 12 (primary constructors for classes, collection expressions, default lambda params). NativeAOT for ASP.NET Core. Keyed DI. `IExceptionHandler`. HTTP/3 default. `TimeProvider`. Frozen collections. PGO on by default.
2. *"What's new in .NET 9?"* — STS. C# 13 (params collections, `System.Threading.Lock`, partial properties). Built-in OpenAPI. HybridCache. LINQ `CountBy`/`AggregateBy`. Aspire 9 GA.
3. *"What's new in .NET 10?"* — LTS, current. C# 14 with the headline being **extension members beyond methods** (extension properties, operators), `field` keyword GA, null-conditional assignment. Continued AOT and PGO improvements. Better SSE support in Minimal APIs.
4. *"Why prefer LTS for production?"* — 36 months of patches vs 18; one upgrade every 2 years instead of every year. Reduces operational overhead and CVE-patch churn.
5. *"What's `TimeProvider` and why is it useful?"* — Abstract clock introduced in .NET 8. Inject `TimeProvider` instead of using `DateTime.UtcNow`; tests can advance time deterministically. Replaces hand-rolled `IClock` abstractions.
6. *"What's the difference between Swashbuckle and `AddOpenApi`?"* — Swashbuckle is the legacy NuGet (still supported). `AddOpenApi` is built into ASP.NET Core 9+. For new projects, `AddOpenApi` is enough; Swashbuckle has more advanced customization.
7. *"What's NativeAOT and which versions support what?"* — Compiles to native ahead of time, no JIT, fast startup, smaller binaries. .NET 7 GA for console, .NET 8 added ASP.NET Core Minimal APIs. .NET 10 closes more compatibility gaps.
8. *"What does `field` (C# 14) replace?"* — The hand-written backing-field pattern: `private string _name; public string Name { get => _name; set => _name = value?.Trim() ... }`. With `field`, no explicit declaration: the compiler generates the backing storage; you just reference `field` in the accessor.

## Cheat Sheet

- **Cadence**: November release; even = LTS (3 yrs); odd = STS (18 mo).
- **Currently supported (May 2026)**: .NET 8 (LTS), .NET 10 (LTS); .NET 9 expires this month.
- **.NET 7**: C# 11 — required, raw strings, generic math; Minimal API filters.
- **.NET 8**: C# 12 — primary ctors, collection expressions; NativeAOT for ASP.NET; keyed DI; `TimeProvider`; frozen collections.
- **.NET 9**: C# 13 — params collections, `Lock`, partial properties; built-in OpenAPI; HybridCache.
- **.NET 10**: C# 14 — extension members beyond methods, `field` keyword, null-conditional assignment.
- **`global.json`**: pin SDK version; avoids "works on my machine" version mismatch.
- **Multi-target libs**: `<TargetFrameworks>net8.0;net10.0</TargetFrameworks>` for broad consumption.
- **STS upgrade rule**: don't skip — .NET 9 → .NET 10 is one bump; can't jump 9 → 11.
- **AOT readiness**: `dotnet publish -p:PublishAot=true` early in CI to surface trim warnings.

## Walkthrough — Upgrading .NET 8 to .NET 10 in production

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A team runs 12 services on .NET 8 (LTS, supported through Nov 2026). The platform team wants to roll forward to .NET 10 (LTS, supported through Nov 2028) to capture C# 14 features (`field` keyword, extension properties), better AOT cold-start, and to align with the next two-year cycle.

**Diagnosis**: Read `dotnet --info` and the per-project `<TargetFramework>` to confirm starting state. Inventory dependencies: `dotnet list package --outdated --include-transitive` shows which NuGets ship .NET 10 builds. Critical packages (EF Core, ASP.NET Core, Aspire) must align — Aspire in particular is pinned per major .NET version. Run the upgrade-assistant: `dotnet tool install -g upgrade-assistant; upgrade-assistant analyze .` produces a per-project compatibility report with breaking changes flagged.

**Fix**: Phase the rollout. (1) Pin SDK in `global.json` to enforce reproducible builds: `{"sdk": {"version": "10.0.100", "rollForward": "latestFeature"}}`. (2) Bump one library project's `<TargetFramework>` to `net10.0`; fix any breaking changes (often EF Core's `ExecuteUpdate` parameter changes, or `IHostingEnvironment` deprecations). (3) Run the project's existing tests + `dotnet publish -p:PublishAot=true` in CI to surface trim/AOT warnings early. (4) Bump the entry-point service after libraries land. (5) Deploy to canary 1%, watch p99 latency / GC counters / error rate for 24h. (6) Roll forward across services one per week.

```xml
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <LangVersion>latest</LangVersion>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  </PropertyGroup>
</Project>
```

**Why it works**: Phasing is critical because .NET majors change runtime behavior subtly — GC heuristics, JIT decisions, BCL implementations. Per-service canary catches regressions before they hit all traffic. Pinning SDK ensures CI and local builds match. The two-LTS cadence (.NET 8 → .NET 10) is intentional: skipping the STS in between (`net9.0`) avoids a forced upgrade in Nov 2026 when .NET 9 expires.

</details>
## Self-test

<details>
<summary>1. What's the difference between LTS and STS, and why does Microsoft alternate them?</summary>

LTS (Long-Term Support) = 3 years of patches; STS (Standard-Term Support) = 18 months. Microsoft alternates them so even-numbered versions (even = LTS: .NET 6, 8, 10) get the long support window and odd-numbered (.NET 7, 9, 11) ship as innovation drops with shorter support. Production teams skip STS and upgrade LTS-to-LTS every 2 years; teams that need a specific feature (e.g., HybridCache shipped in .NET 9) can take an STS. The "STS gap" — running .NET 9 in May 2026 means upgrading to .NET 10 within weeks or losing patches — is a planning trap; pick LTS unless the STS feature is worth the upgrade tempo.
</details>

<details>
<summary>2. Apply: a service is on .NET 7 (out of support). What's the recommended path forward and why?</summary>

.NET 7 is STS, expired May 2024. The team must upgrade. Best path: jump straight to .NET 10 (current LTS) — .NET 8 is also LTS but expires Nov 2026, only 18 months out. The upgrade hops are .NET 7 → 8 (test) → 9 (test) → 10 if you want incremental confidence, or 7 → 10 if your dependencies allow. Multi-step upgrades catch breaking changes more cleanly; direct hops are faster. Either way, do not stay on .NET 7 — no security patches means CVE risk. Pre-upgrade checklist: NuGets supporting target TFM, AOT compatibility if relevant, EF Core migration semantics if jumping 7 → 9 (`ExecuteUpdate`/`ExecuteDelete` are .NET 7+ but their semantics evolved).
</details>

<details>
<summary>3. Trade-off: when does NativeAOT make sense, and when should you stick with JIT?</summary>

NativeAOT wins for: (a) serverless / cold-start sensitive workloads — Azure Functions, AWS Lambda — where JIT warm-up burns money; (b) constrained-memory containers where JIT's working set is too large; (c) single-file deployments needing minimal binary size; (d) scenarios needing zero JIT (security/regulatory). Loses for: (a) reflection-heavy code paths (older ORMs, IoC containers, legacy serializers); (b) plugin systems loading DLLs at runtime; (c) hot-paths where Tier 1 JIT optimizations + Dynamic PGO eventually outperform AOT. Trade-off summary: AOT trades startup time + size for build complexity + reflection limits. Default to JIT for monoliths; consider AOT for microservices, CLI tools, edge workloads.
</details>

<details>
<summary>4. Analyze: a colleague wants to use C# 14's `field` keyword in a project targeting `net8.0`. Will it compile?</summary>

No — `field` requires both the C# 14 compiler (Roslyn shipped with the .NET 10 SDK or VS 17.12+) *and* a `<LangVersion>` set to 14 or `latest`. The C# version is independent of the target framework, so technically you can set `<LangVersion>latest</LangVersion>` in a `net8.0` project, but `field` may emit IL that requires runtime support not present in net8.0. The pragmatic answer: feature-by-feature. Some C# 14 features (records improvements, syntactic sugar) work on older TFMs; others (anything touching the runtime, like `Lock`) need the new BCL. Check the language-version reference docs. If it's purely syntactic, bumping `<LangVersion>` works; if it's runtime-bound, you must bump TFM.
</details>

<details>
<summary>5. You see `<TargetFrameworks>net8.0;net10.0</TargetFrameworks>` in a library. Explain the build output and trade-offs.</summary>

The compiler builds the library *twice* — once for each TFM — producing `bin/Debug/net8.0/Lib.dll` and `bin/Debug/net10.0/Lib.dll`. Consumers on .NET 8 reference the first; .NET 10 consumers the second. Inside the source, `#if NET10_0_OR_GREATER` blocks let you use newer APIs only when targeting newer TFMs, with fallbacks for older. Trade-offs: (+) wide compatibility — one NuGet package serves both LTS audiences; (+) new features available where supported; (−) build is slower (compiles n times), tests must run per TFM, debugging is more complex, NuGet package is larger. Use multi-targeting for libraries with broad consumer base (Newtonsoft, Polly, Serilog do this); skip it for application services where you control the runtime.
</details>

## Cross-references

- [.NET Fundamentals](./01-net-fundamentals.md) — runtime overview; the timeline diagram lives there too.
- [Modern C# Features](./12-modern-csharp.md) — companion file; covers C# 9–11/12 features used elsewhere in the guide. Update path: when this file lists a C# 14 feature you want to lean into, add a fuller treatment there.
- [Async/Await, Multithreading](./03-async-and-threading.md) — `Lock` (C# 13) and `TimeProvider` (.NET 8) live here in practice.
- [Configuration](./15-configuration.md) — `IOptions` evolution.
- [Middleware](./04-middleware.md) — output cache, rate limiting, OpenAPI middleware register here.
- [APIs & Microservices](./06-apis-and-microservices.md) — Minimal API features (`MapGroup`, endpoint filters, OpenAPI).
- [Data Access (EF Core)](./05-data-access.md) — bulk ops, JSON columns introduced in this timeline.
- [Caching Strategies](./10-caching.md) — HybridCache (.NET 9+).
- [Microservices chapter](../../05-microservices-and-messaging/README.md) — Aspire applies broadly.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — *What's new in .NET 7* / *…8* / *…9* / *…10* (search "what's new dotnet" on learn.microsoft.com for the canonical lists).
- .NET Blog — release announcements: [devblogs.microsoft.com/dotnet/announcing-dotnet-7](https://devblogs.microsoft.com/dotnet/announcing-dotnet-7/), `…/announcing-dotnet-8/`, `…/announcing-dotnet-9/`, `…/announcing-dotnet-10/`.
- Stephen Toub's "Performance Improvements in .NET X" series on the .NET blog — exhaustive deep-dives. The single best source on per-release runtime / JIT / BCL changes.
- *.NET releases* page — [dotnet.microsoft.com/platform/support/policy/dotnet-core](https://dotnet.microsoft.com/platform/support/policy/dotnet-core) — current support timeline.
- Mads Torgersen's C# language design notes (`/dotnet/csharplang` on GitHub) — C# 11–14 design rationale.
- *C# 12 in a Nutshell*, *C# 13 in a Nutshell* by Joseph Albahari — concise reference per language version.

_Last reviewed: 2026-05-07. Re-verify the .NET 10 specifics against the latest release notes when reading this 6+ months from now._

</details>
<!-- nav-footer-start -->

---

[← Previous: Hands-On Mini Project — TaskFlow API](17-taskflow-mini-project.md) · [↑ Back to top](#net-version-history-net-7--net-10) · [Next: SOLID Principles →](../02-solid-principles.md)

<!-- nav-footer-end -->
