# Caching Strategies

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-08 |

> 📘 **Main file**: Interview-ready summary, drills, and cheat sheet live in **[Redis & Caching](../../03-data-and-persistence/05-redis.md)**. This file is the implementation deep-dive.

> 📖 **Companion files**: [Redis Deep Dive](../../03-data-and-persistence/05-redis.md) (data structures, persistence, clustering) and [System Design Prep › Caching](../../08-craft-and-interview-prep/03-system-design-prep.md). This file is the reference for .NET caching APIs and the strategy decisions that surround them.

**Level:** Intermediate to Advanced &nbsp;·&nbsp; **Reading time:** ~25 min &nbsp;·&nbsp; **Scope:** In-process, distributed, hybrid, output, and response caching in ASP.NET Core 10 / .NET 10.

---

## Why Caching Matters

A request that hits the database is two to four orders of magnitude slower than a request that hits memory. A modern API serving 1,000 RPS where every request reads the same product catalog will exhaust a database in minutes — but the same load served from L1 memory is rounding error on a single node. Caching is therefore not an optimization; for any non-trivial system it is **architecture**.

Caching is also one of the easiest places to introduce a critical bug. Stale prices, leaked tenant data, an unbounded dictionary that OOMs the host, a thundering herd that DDOSes the database during a cold start — every team eventually meets all of these. The discipline is to **make caching a deliberate design**, not a reflex sprinkled on slow endpoints.

This guide covers the .NET 10 toolbox (`IMemoryCache`, `IDistributedCache`, `HybridCache`, output caching, response caching), the strategies that wrap them (cache-aside, read-through, write-through, write-behind), and the operational concerns (invalidation, key design, stampede prevention) that separate a cache from a footgun.

## Contents
- [Caching Strategies](#20-caching-strategies)

---

## 20. Caching Strategies

### Table of Contents
1. [Introduction](#introduction)
2. [Cache Tiers — L1, L2, CDN](#cache-tiers--l1-l2-cdn)
3. [In-Memory Caching — IMemoryCache](#in-memory-caching--imemorycache)
4. [Distributed Caching — IDistributedCache + Redis](#distributed-caching--idistributedcache--redis)
5. [HybridCache — L1 + L2 in One API (.NET 9+)](#hybridcache--l1--l2-in-one-api-net-9)
6. [Output Caching — ASP.NET Core Middleware (.NET 7+)](#output-caching--aspnet-core-middleware-net-7)
7. [Response Caching — HTTP Caching Headers](#response-caching--http-caching-headers)
8. [Cache Read/Write Strategies](#cache-readwrite-strategies)
9. [Cache Invalidation](#cache-invalidation)
10. [Cache Key Design](#cache-key-design)
11. [Cache Stampede & Thundering Herd](#cache-stampede--thundering-herd)
12. [Common Pitfalls](#common-pitfalls)
13. [Best Practices](#best-practices)
14. [Real-World Scenarios](#real-world-scenarios)
15. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
16. [Self-Test](#self-test)
17. [Cross-References](#cross-references)
18. [Sources](#sources)

---

### Introduction

#### What is a Cache?

A cache is a **temporary high-speed store of data** placed between a slow source of truth (database, remote API, file system) and the consumer. The cache trades **freshness for latency**: it returns a possibly-stale value instantly instead of recomputing the canonical value from scratch.

- **Without a cache:** Every request computes the answer from the source of truth.
- **With a cache:** First request computes; subsequent requests return the stored answer until it expires or is invalidated.

#### Without Cache vs With Cache

```
WITHOUT CACHE:
    Request 1 ──► [API] ──► [DB query: 80ms] ──► response (90ms total)
    Request 2 ──► [API] ──► [DB query: 80ms] ──► response (90ms)
    Request 3 ──► [API] ──► [DB query: 80ms] ──► response (90ms)
    1000 RPS = 1000 DB queries/sec → DB at 100% CPU

WITH CACHE (L1 in-memory, 5-min TTL):
    Request 1 ──► [API] ──► [cache miss] ──► [DB: 80ms] ──► [populate] ──► response (92ms)
    Request 2 ──► [API] ──► [cache hit: 0.05ms] ──────────────────────────► response (1ms)
    Request 3 ──► [API] ──► [cache hit: 0.05ms] ──────────────────────────► response (1ms)
    1000 RPS ≈ 0.003 DB queries/sec average → DB at <1% CPU
```

The first request pays full freight. Every subsequent request within the TTL pays microseconds. The economics of caching are nearly always favorable for read-heavy workloads.

#### Real-World Analogy: The Coffee Shop Counter

```
                    [Espresso Machine]   ← Source of truth (slow, accurate, expensive)
                            │
                            │ pull shot (30s)
                            ▼
                    [Thermal Carafe]     ← Distributed cache (warm, shared)
                            │
                            │ pour (2s)
                            ▼
                    [Pre-poured Cup]     ← In-memory cache (hot, single barista)
                            │
                            │ hand to customer (instant)
                            ▼
                       [Customer]

- Pre-poured cup is fastest but few exist; goes cold (TTL)
- Thermal carafe serves many customers; refilled from machine periodically
- Espresso machine is the truth but slow; only invoked on miss
```

This three-tier model maps directly onto how you'll structure caching in a serious application: a per-process L1, a shared L2, and a backing store.

---

### Cache Tiers — L1, L2, CDN

```
┌────────────────────────────────────────────────────────────────────┐
│                     REQUEST PATH (READ)                            │
│                                                                    │
│   Browser ──► CDN ──► Edge ──► App L1 ──► App L2 ──► Database      │
│              ~5ms    ~20ms    ~0.05ms    ~1-3ms    ~10-100ms       │
│                                                                    │
│   Each tier: faster, smaller, less authoritative than the next     │
└────────────────────────────────────────────────────────────────────┘
```

| Tier | Where | Latency | Capacity | Shared? | Survives restart? |
|------|-------|---------|----------|---------|-------------------|
| Browser cache | User device | <1 ms | tiny | No | Yes |
| CDN | Edge POPs worldwide | 5-30 ms | huge | Yes (per region) | Yes |
| L1 (in-process) | App memory | 0.01-0.1 ms | small (MBs-GBs) | No | **No** |
| L2 (distributed) | Redis/Memcached | 0.5-3 ms | large (GBs-TBs) | Yes | Configurable |
| Database | Source of truth | 5-100+ ms | massive | Yes | Yes |

**Rule of thumb:** add a tier only when the next tier is too slow or too expensive for your workload. Don't reach for Redis if a 10 MB `IMemoryCache` solves it.

---

### In-Memory Caching — IMemoryCache

```
┌─────────────────────────────────────┐
│ IMemoryCache Properties             │
├─────────────────────────────────────┤
│ ✓ Fastest cache (~50 ns reads)      │
│ ✓ Stores any object reference       │
│ ✓ Sliding + absolute expiration     │
│ ✓ Size-limit eviction               │
│ ✓ Eviction callbacks                │
│ ✓ Built into the BCL                │
│ ✗ Not shared across instances       │
│ ✗ Lost on app restart               │
│ ✗ Heap pressure if unbounded        │
│ ✗ Stampede on cold start            │
└─────────────────────────────────────┘
```

#### Registration

```csharp
// Program.cs
builder.Services.AddMemoryCache(options =>
{
    options.SizeLimit = 1024;                    // logical "size units"
    options.CompactionPercentage = 0.25;         // evict 25% when full
    options.ExpirationScanFrequency = TimeSpan.FromMinutes(1);
});
```

`SizeLimit` is unit-less — you decide what 1 unit means (1 entry? 1 KB? 1 MB?). When entries are added with `.SetSize(n)`, the cache enforces the cap.

#### Reading — `TryGetValue` + populate pattern

```csharp
public class ProductService(IMemoryCache cache, AppDbContext db)
{
    public async Task<Product?> GetProductAsync(int id, CancellationToken ct)
    {
        var key = $"product:v1:{id}";

        if (cache.TryGetValue(key, out Product? product))
            return product;                                          // hit

        product = await db.Products.FindAsync([id], ct);             // miss
        if (product is not null)
        {
            cache.Set(key, product, new MemoryCacheEntryOptions
            {
                SlidingExpiration  = TimeSpan.FromMinutes(5),        // reset on each access
                AbsoluteExpirationRelativeToNow = TimeSpan.FromHours(1),  // hard cap
                Size = 1,
                Priority = CacheItemPriority.Normal
            });
        }
        return product;
    }
}
```

#### `GetOrCreateAsync` — the idiomatic shortcut

```csharp
public Task<Product?> GetProductAsync(int id, CancellationToken ct) =>
    cache.GetOrCreateAsync($"product:v1:{id}", async entry =>
    {
        entry.SlidingExpiration = TimeSpan.FromMinutes(5);
        entry.AbsoluteExpirationRelativeToNow = TimeSpan.FromHours(1);
        entry.Size = 1;
        return await db.Products.FindAsync([id], ct);
    });
```

**⚠️ Caveat:** `GetOrCreateAsync` does **not** deduplicate concurrent factory calls. Two requests missing the same key on the same instance will both run the factory. See [Cache Stampede](#cache-stampede--thundering-herd).

#### Sliding vs Absolute Expiration

```
ABSOLUTE EXPIRATION:                    SLIDING EXPIRATION:
                                         
T=0   Set, abs=10                        T=0   Set, slide=5
T=3   Read  (still valid)                T=3   Read  (still valid, slides to 8)
T=7   Read  (still valid)                T=7   Read  (still valid, slides to 12)
T=10  EXPIRED ─── always                 T=12  Read  (still valid, slides to 17)
                                         T=22  EXPIRED ─── only if no reads for 5
                                         
Use when freshness matters               Use for hot session data
                                         
COMBINED (recommended): slide=5, abs=60
- Active items stay warm
- Inactive items eventually flush
- Nothing lives forever in cache
```

#### When to Use IMemoryCache

```
✅ Good fit:
├─ Single-server / fixed-size deployments
├─ Reference data: lookups, taxonomies, feature flags
├─ Hot session-scoped objects on sticky sessions
├─ Per-instance computed values (e.g. precompiled regex)
└─ Microsecond latency is non-negotiable

❌ Bad fit:
├─ Multi-instance API where users hit different pods
│  (each pod sees a different cache → inconsistent reads)
├─ Data > a few hundred MB (heap pressure + GC pauses)
├─ Cross-process invalidation requirements
└─ Anything that must survive restart (use L2 or DB)
```

---

### Distributed Caching — IDistributedCache + Redis

```
┌─────────────────────────────────────┐
│ IDistributedCache Properties        │
├─────────────────────────────────────┤
│ ✓ Shared across all app instances   │
│ ✓ Survives app restart              │
│ ✓ Multiple backends: Redis, SQL,    │
│   NCache, in-memory test impl       │
│ ✓ Byte-array based (lang-neutral)   │
│ ✗ Network round-trip (~1-3 ms)      │
│ ✗ Serialization cost                │
│ ✗ Operational ownership of Redis    │
│ ✗ No "size" callback / no priorities│
└─────────────────────────────────────┘
```

#### Registration (Redis)

```csharp
// Microsoft.Extensions.Caching.StackExchangeRedis
builder.Services.AddStackExchangeRedisCache(options =>
{
    options.Configuration = builder.Configuration.GetConnectionString("Redis");
    options.InstanceName  = "MyApp:";   // key prefix for multi-tenant Redis
});
```

#### Read/Write — string and JSON helpers

```csharp
public class SessionService(IDistributedCache cache)
{
    private static readonly DistributedCacheEntryOptions Options = new()
    {
        SlidingExpiration = TimeSpan.FromMinutes(20),
        AbsoluteExpirationRelativeToNow = TimeSpan.FromHours(8)
    };

    public async Task<UserSession?> GetAsync(string sid, CancellationToken ct)
    {
        var bytes = await cache.GetAsync($"session:{sid}", ct);
        return bytes is null ? null : JsonSerializer.Deserialize<UserSession>(bytes);
    }

    public Task SetAsync(string sid, UserSession s, CancellationToken ct) =>
        cache.SetAsync($"session:{sid}",
            JsonSerializer.SerializeToUtf8Bytes(s), Options, ct);

    public Task RemoveAsync(string sid, CancellationToken ct) =>
        cache.RemoveAsync($"session:{sid}", ct);
}
```

#### Architecture — what L2 looks like at runtime

```
       ┌──────────┐  ┌──────────┐  ┌──────────┐
       │ App #1   │  │ App #2   │  │ App #3   │   ← all behind a load balancer
       │ pod      │  │ pod      │  │ pod      │
       └────┬─────┘  └────┬─────┘  └────┬─────┘
            │             │             │
            └─────────────┼─────────────┘
                          │ TCP (RESP protocol)
                          ▼
                  ┌──────────────┐
                  │  Redis       │   ← single source of cached truth
                  │  (cluster or │     for *all* app instances
                  │   replica)   │
                  └──────┬───────┘
                         │ optional persistence
                         ▼
                    [AOF / RDB]
```

#### When to Use IDistributedCache

```
✅ Good fit:
├─ Multi-instance APIs (Kubernetes, ECS, App Service plans)
├─ Cross-pod session state
├─ Idempotency keys / dedupe windows
├─ JWT denylists / token revocation
├─ Rate-limit counters (atomic INCR)
└─ Anything that must outlive a single pod

❌ Bad fit:
├─ Sub-millisecond per-request access
│  (network RTT alone defeats the cache for hot path)
├─ Replacing the database for write-heavy workloads
├─ Storing massive blobs (>~1 MB per key — break it up)
└─ Single-instance dev boxes (overkill)
```

For Redis-specific concerns (data types, persistence, clustering, pub/sub, distributed locks), see [Redis Deep Dive](../../03-data-and-persistence/05-redis.md).

---

### HybridCache — L1 + L2 in One API (.NET 9+)

`HybridCache` (in `Microsoft.Extensions.Caching.Hybrid`) is the official Microsoft answer to "how do I combine memory + distributed without writing it myself for the tenth time." It manages a per-process L1, a shared L2, **and** stampede protection.

```
┌─────────────────────────────────────┐
│ HybridCache Properties              │
├─────────────────────────────────────┤
│ ✓ Two-tier reads (L1 → L2 → factory)│
│ ✓ Single-flight per key (no stampede│
│ ✓ Tag-based eviction                │
│ ✓ Built-in serialization            │
│ ✓ Drop-in for IDistributedCache     │
│ ✗ Newer API — ecosystem still grows │
│ ✗ Requires .NET 9+                  │
└─────────────────────────────────────┘
```

```csharp
// .NET 10
builder.Services.AddHybridCache(options =>
{
    options.DefaultEntryOptions = new HybridCacheEntryOptions
    {
        Expiration      = TimeSpan.FromMinutes(30),    // L2 absolute
        LocalCacheExpiration = TimeSpan.FromMinutes(2) // L1 absolute
    };
});

public class CatalogService(HybridCache cache, ICatalogDb db)
{
    public ValueTask<Product?> GetAsync(int id, CancellationToken ct) =>
        cache.GetOrCreateAsync(
            key:    $"product:{id}",
            factory: async ct2 => await db.GetProductAsync(id, ct2),
            options: null,
            tags:    ["products", $"product:{id}"],
            cancellationToken: ct);

    public Task InvalidateAsync(int id, CancellationToken ct) =>
        cache.RemoveByTagAsync($"product:{id}", ct).AsTask();
}
```

The factory runs **at most once per key per process** even under high concurrency — HybridCache funnels concurrent misses through a single in-flight task. This solves the stampede problem (covered below) without you writing the locking yourself.

**Decision matrix — pick one:**

| Need | Use |
|------|-----|
| Single-instance app, microsecond reads | `IMemoryCache` |
| Multi-instance, simple shared cache | `IDistributedCache` (Redis) |
| Multi-instance, want both speed and sharing, no manual stampede control | **`HybridCache`** ← default for new code on .NET 9+ |
| Bespoke read-through pipeline with custom serializers | Build on `IDistributedCache` |

---

### Output Caching — ASP.NET Core Middleware (.NET 7+)

Output caching stores the **HTTP response** keyed by request shape, before the endpoint runs. It's the right tool when whole responses are stable and computed identically across requests.

```csharp
builder.Services.AddOutputCache(options =>
{
    options.AddBasePolicy(b => b.Expire(TimeSpan.FromSeconds(30)));
    options.AddPolicy("ProductCatalog", b => b
        .Expire(TimeSpan.FromMinutes(10))
        .Tag("products")
        .SetVaryByQuery("category", "page")
        .SetVaryByHeader("Accept-Language"));
});

var app = builder.Build();
app.UseOutputCache();

app.MapGet("/api/products", GetProducts).CacheOutput("ProductCatalog");
```

#### Tag-based invalidation (write side)

```csharp
app.MapPost("/api/products", async (
    Product p,
    IOutputCacheStore cacheStore,
    AppDbContext db,
    CancellationToken ct) =>
{
    db.Products.Add(p);
    await db.SaveChangesAsync(ct);

    // Wipe every response tagged "products"
    await cacheStore.EvictByTagAsync("products", ct);
    return Results.Created($"/api/products/{p.Id}", p);
});
```

#### Output caching vs Response caching

```
                          OUTPUT CACHE (server-side)        RESPONSE CACHE (client/proxy)
                          ─────────────────────────         ─────────────────────────────
Storage location          Server memory or distributed       Browser, CDN, intermediaries
Control                   Server fully owns it               Honored by clients (Cache-Control)
Invalidation              Tags, eviction APIs                TTL only — can't recall
Vary by                   Configurable + custom keys         Vary header
Auth-aware?               Default: skip authenticated reqs   Public/private directives
Right tool for…           Internal API caching, SSR pages    Static assets, public APIs
```

You usually want **both** for public read-heavy endpoints: output cache prevents your server from recomputing; response cache headers let the CDN serve a copy without ever touching your origin.

---

### Response Caching — HTTP Caching Headers

```csharp
[ResponseCache(Duration = 60, Location = ResponseCacheLocation.Any, VaryByQueryKeys = ["category"])]
[HttpGet("public/products")]
public IActionResult Public() => Ok(...);
```

Emits `Cache-Control: public, max-age=60` and lets browsers / CDNs cache. **Authenticated responses default to private** — never accidentally cache a personalized page on a CDN.

```
PUBLIC RESPONSE CACHING:
  Browser ──► CDN ──► Origin
              │
              ▼
       [60s, max-age=60]
       Subsequent requests served from CDN, origin is silent
```

---

### Cache Read/Write Strategies

There are four canonical patterns. Pick one **per data flow**, then stick to it.

#### 1. Cache-Aside (Lazy Loading) — *the default*

```
READ:                              WRITE:
  app ──► cache?                     app ──► DB write
        ├─ hit  → return                       │
        └─ miss → DB ──► populate cache        ▼
                       → return            invalidate cache
```

App is responsible for both reading and populating. The cache itself is "dumb" — it doesn't know about the DB.

```csharp
public async Task<Product?> ReadAsync(int id) =>
    await cache.GetOrCreateAsync($"product:{id}", _ => db.GetAsync(id));

public async Task UpdateAsync(Product p)
{
    await db.UpdateAsync(p);
    cache.Remove($"product:{p.Id}");   // invalidate; next read refills
}
```

✅ Simple, no special infra. Survives cache outages (just slower).
❌ First read is always a miss. Stale window between DB write and invalidate.

#### 2. Read-Through

The cache layer fetches from the DB on miss. App talks only to the cache.

```
  app ──► cache.Get(key)
            │
            ├─ hit  → return
            └─ miss → cache loads from DB internally → return
```

Implemented in .NET via abstractions over `HybridCache` or custom decorators. Same shape as cache-aside but encapsulated.

#### 3. Write-Through

```
  app ──► cache.Set ──► (cache writes to DB synchronously) ──► return
```

Every write goes through the cache, which updates the DB before acknowledging. Cache and DB always agree.

✅ Strong consistency between cache and DB.
❌ Write latency = cache write + DB write. DB outage breaks writes.

#### 4. Write-Behind (Write-Back)

```
  app ──► cache.Set ──► (acks immediately) ──► return
                         │
                         ▼ async batch
                       [DB]
```

Cache acks the write and flushes to the DB asynchronously.

✅ Fastest writes; DB load smoothed.
❌ Window where cache has data the DB doesn't — crash = data loss. Reserve for high-throughput, loss-tolerant workloads (analytics counters, telemetry).

#### Strategy comparison

| Strategy | Write latency | Read latency | Consistency | Complexity | Typical use |
|----------|--------------|--------------|-------------|------------|-------------|
| Cache-aside | DB only | Cache hit / miss | Eventual | Low | **Default** for most APIs |
| Read-through | DB only | Cache hit / miss | Eventual | Low-medium | Encapsulated reads |
| Write-through | Cache + DB | Cache hit | Strong | Medium | Financial, inventory |
| Write-behind | Cache only | Cache hit | Eventual + risk | High | Counters, telemetry |

---

### Cache Invalidation

> "There are only two hard things in computer science: cache invalidation and naming things." — Phil Karlton

#### TTL (Time To Live)

```
  Key set at T=0, TTL=60s
  ┌─────────────────────── 60s window ────────────────────────┐
  T=0   T=10  T=20  T=30  T=40  T=50  T=60
  │      │     │     │     │     │     │
  set    hit   hit   hit   hit   hit   miss → repopulate
```

✅ Dead simple. Always eventually consistent.
❌ Stale window equal to TTL. Choose TTL = max acceptable staleness.

#### Event-based invalidation

```csharp
public async Task UpdatePriceAsync(int productId, decimal price)
{
    await db.UpdatePriceAsync(productId, price);
    await cache.RemoveAsync($"product:{productId}");
    await cache.RemoveByTagAsync($"product:{productId}");
    await bus.PublishAsync(new PriceChanged(productId, price));   // tell other services
}
```

Every writer is responsible for evicting affected keys. Consider **eventing across services** so that downstream caches in other services also drop their stale copies.

#### Tag-based invalidation

```csharp
await cache.GetOrCreateAsync(
    $"product:{id}",
    factory,
    tags: ["products", $"category:{p.CategoryId}", $"product:{id}"]);

// Invalidate all products in a category in one call:
await cache.RemoveByTagAsync($"category:{categoryId}", ct);
```

Tags are how you invalidate **groups of related keys** without enumerating them.

#### Versioned keys (immutable cache)

```csharp
// Bump the version to atomically invalidate all keys of a kind:
var version = await cache.GetStringAsync("schema:product:v") ?? "1";
var key = $"product:v{version}:{id}";

// On schema change:
await cache.SetStringAsync("schema:product:v",
    (int.Parse(version) + 1).ToString());
// Old keys orphan and get evicted by TTL; readers immediately see new keys.
```

Useful for deploys that change object shape — old serialized data becomes inaccessible without explicit eviction.

---

### Cache Key Design

Keys are an API. Get them wrong once and you'll regret it for years.

```
   product:v2:t-acme:42:detail
   ───┬──── ─┬─ ──┬──── ┬─ ──┬───
      │      │    │     │    │
   entity   ver tenant  id  view
```

**Rules:**

1. **Namespace by entity** (`product:`, `user:`, `order:`).
2. **Include a schema version** (`v2`) — bump on shape changes.
3. **Include the tenant** (`t-acme`) — never accidentally serve tenant A's data to tenant B.
4. **Include the ID**.
5. **Include the projection** (`:detail` vs `:summary`) when one entity has multiple shapes.
6. **No spaces, no localized strings, no untrusted input** — sanitize anything user-supplied.
7. **Hash long keys** (`SHA256` truncated to 16 hex chars) when query parameters could blow past Redis's 512 MB key limit (rare) or readability limit (common).

```csharp
static string ProductKey(string tenant, int id, string view = "detail") =>
    $"product:v2:{tenant}:{id}:{view}";
```

---

### Cache Stampede & Thundering Herd

When a hot key expires (or is first requested on cold start), every concurrent request misses simultaneously and hits the database. On a busy API this can multiply DB load by 100x in milliseconds.

```
                       cache TTL expires
                              │
                              ▼
   t=0    [Req1] [Req2] [Req3] ... [Req500]   ← all miss at once
                              │
                              ▼
                          [Database]            ← 500 concurrent identical queries
                              │
                          (overload, timeouts, cascading failure)
```

#### Solution 1: Single-flight (lock per key)

```csharp
private static readonly ConcurrentDictionary<string, SemaphoreSlim> _locks = new();

public async Task<Product?> GetAsync(int id, CancellationToken ct)
{
    var key = $"product:{id}";
    if (cache.TryGetValue(key, out Product? p)) return p;     // fast path

    var sem = _locks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));
    await sem.WaitAsync(ct);
    try
    {
        // double-check after acquiring lock
        if (cache.TryGetValue(key, out p)) return p;

        p = await db.Products.FindAsync([id], ct);
        if (p is not null)
            cache.Set(key, p, TimeSpan.FromMinutes(5));
        return p;
    }
    finally
    {
        sem.Release();
        // Optional: prune the dictionary on a timer to avoid unbounded growth
    }
}
```

This is the **double-checked locking** pattern adapted for caching. Note: `_locks` is per-process; on a 10-pod cluster you still get up to 10 concurrent factory calls. That's usually fine; if not, use a distributed lock (Redis `SET NX PX`).

#### Solution 2: HybridCache (built-in single-flight)

```csharp
// HybridCache deduplicates concurrent factory calls per key, per instance, automatically:
await hybridCache.GetOrCreateAsync(
    $"product:{id}",
    async ct2 => await db.GetProductAsync(id, ct2),
    cancellationToken: ct);
```

This is the **lowest-effort** answer on .NET 9+ and the recommended default.

#### Solution 3: Probabilistic early refresh

Refresh a small random fraction of requests *before* the TTL expires, so the cache is always warm:

```csharp
// Beta-distribution-inspired: occasionally refresh in the last 10% of TTL
var ttlRemaining = entry.AbsoluteExpiration - DateTimeOffset.UtcNow;
if (ttlRemaining < TimeSpan.FromSeconds(30) &&
    Random.Shared.NextDouble() < 0.05)
{
    _ = Task.Run(() => RefreshAsync(key));   // fire-and-forget refresh
}
return cached;
```

#### Solution 4: Stale-while-revalidate

Serve the stale value while a background task refreshes. HybridCache does not yet do this natively in 10.0; libraries like FusionCache implement it.

---

### Common Pitfalls

1. **Caching authenticated/personal data publicly.**
   Output cache or CDN serves user A's profile to user B. Always vary by user identity, or only cache anonymous responses.

2. **Forgetting tenancy in the key.**
   Multi-tenant SaaS reads `product:42` and gets tenant B's product. Always include `tenant:` in the key.

3. **Caching exceptions.**
   `GetOrCreateAsync` factory throws → next request runs factory again → DB still down → cascading failure. Cache only successful results; on failure, return error without populating.

4. **Unbounded cache size.**
   `IMemoryCache` with no `SizeLimit` and entries with no `Size` will fill until OOM. Always set a cap.

5. **Sliding-only expiration on hot keys.**
   A frequently-accessed key with sliding-only expiration **never expires** — and never refreshes. Always combine with absolute expiration.

6. **Serializing non-deterministically.**
   `JsonSerializer` with `TypeNameHandling.All` for unknown types invites RCE on cache poisoning. Use a strict allow-list or `System.Text.Json` with `JsonSerializerOptions` configured deliberately.

7. **Using cache as the source of truth.**
   "We can lose Redis and rebuild" → "We've been running on Redis-only for 6 months and DB has stale data." Cache is **derived state**; database is **authoritative**.

8. **Cache-aside without invalidation on writes.**
   Update DB, forget to evict cache → users see old data for the full TTL. Bake the eviction into your repository / unit of work.

9. **Storing too-large objects.**
   1 MB cached entity × 10K cached entries = 10 GB heap. Cache identifiers + small projections; rehydrate on demand.

10. **Ignoring deserialization cost.**
    A 50 ms Postgres query with 10 ms `JsonSerializer.Deserialize` from Redis is only 60→10 ms. Compare end-to-end, not just the network hop. For very large objects on hot paths, consider `MessagePack` or `MemoryPack`.

---

### Best Practices

1. **Default to cache-aside.** It is the simplest, most resilient pattern. Reach for write-through only when you have a real consistency requirement that justifies the latency cost.

2. **Use `HybridCache` for new code on .NET 9+.** It bundles L1+L2, stampede protection, and tag invalidation behind one API.

3. **Always set both sliding and absolute expiration.** Sliding keeps hot data warm; absolute guarantees nothing lives forever and prevents zombie entries.

4. **Version your cache keys (`v1`, `v2`).** Bumping the version is the safest deploy-time invalidation when serialized shape changes.

5. **Namespace keys by entity and tenant.** `product:v1:tenant-acme:42`. This prevents cross-tenant leakage by construction.

6. **Cache the projection, not the entity.** Cache the DTO you return, not the EF entity. Avoids change-tracking surprises and keeps payloads small.

7. **Cap cache size and observe eviction metrics.** Without bounds + observability you'll find out about cache problems via `OutOfMemoryException`.

8. **Tag entries you'll need to invalidate together.** "All products in category X" should be one `RemoveByTagAsync` call, not 10K key deletions.

9. **Plan for cold start.** Pre-warm critical caches on startup, or use stagger + jitter so a fleet restart doesn't stampede the DB.

10. **Measure hit ratio.** Below ~80% on a hot endpoint usually means a key design problem (over-specific keys) or a TTL too short. Above 99.9% on a rare endpoint means you're caching something nobody asked for — wasted memory.

---

### Real-World Scenarios

#### Scenario 1 — Product Catalog (read-heavy, slow-changing)

```
Pattern:    Cache-aside with HybridCache (L1 + L2)
TTL:        L1 = 2 min, L2 = 30 min
Keys:       product:v1:{tenant}:{id}
Tags:       ["products", $"category:{id}", $"product:{id}"]
Invalidate: On admin update → RemoveByTagAsync($"product:{id}")
Stampede:   Handled by HybridCache single-flight
```

Result: 99% hit ratio on the hot path, DB sees ~30 reads/min for catalog instead of 10K/min. Admin edits propagate within seconds across the fleet.

#### Scenario 2 — Stock Prices (read-heavy, fast-changing)

```
Pattern:    Output caching (10s TTL) + CDN at edge
TTL:        10 seconds (max acceptable staleness)
Vary by:    Symbol, currency
Invalidate: TTL only (event-based not worth the complexity)
```

Result: `MSFT` quote endpoint serves 100K RPS with origin doing ~10 fetches/sec total. Acceptable 10-second lag for non-trader users.

#### Scenario 3 — Cold-Start Stampede on Deploy

```
Symptom:    Every k8s rollout caused a 500-error spike for 30 seconds.
            New pods came up with empty caches; first traffic burst hit DB.

Fix 1:      Pre-warm — on Startup.OnApplicationStarted, iterate top 100
            products and call cache.Set explicitly.
Fix 2:      HybridCache single-flight prevents per-pod stampede.
Fix 3:      Stagger pod readiness so all 20 pods don't go live at once.
Fix 4:      Add a circuit breaker on the DB call so cache misses fail
            fast rather than queue up if DB is overloaded.

Outcome:    Rollouts now invisible to clients; DB CPU stays under 30%.
```

#### Scenario 4 — JTI Denylist (security-driven)

```
Pattern:    IDistributedCache (Redis), absolute TTL = remaining JWT lifetime
Key:        jti:{jwt-id}
Value:      "revoked"
Read:       Auth middleware checks every request
Write:      On user logout / password change / admin revoke

Why distributed:  Token revocation must be visible to all instances.
                  In-memory wouldn't propagate across the cluster.
```

See also [Security Deep Dive › JWT Revocation](./09-security.md).

---

### Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.

#### Drill 1 — `IMemoryCache` vs `IDistributedCache`

> **Q**: When do you pick `IMemoryCache` vs `IDistributedCache`?
>
> **A**: `IMemoryCache` for single-instance / pinned-instance scenarios where 50ns reads matter and you don't need to share state across pods — reference data, feature flags, per-instance computed values. `IDistributedCache` for multi-instance APIs where any pod can serve any request and they need to see the same data — sessions, idempotency keys, JWT denylists, anything that must outlive a pod.
>
> **Cross-Q**: What happens in a multi-instance API if I use `IMemoryCache` for product data with a 5-min TTL?
>
> **A**: Each pod has its own cache. Pod A loads product 42 from the DB and caches it. Pod B (next request via load balancer) misses, loads from DB independently, caches independently. Database load is *N× higher* than ideal where N = pod count. Worse: a product update via Pod A evicts only Pod A's copy — Pods B and C serve stale data for the full TTL. The cache is technically working; the architecture isn't.
>
> **Cross-Q²**: When would the multi-instance `IMemoryCache` *still* be acceptable?
>
> **A**: When the cached data is *truly static within the TTL* (configuration loaded at startup, reference lookups that change daily, compiled regex). Or when staleness across pods is tolerable (analytics counters where slight divergence doesn't matter). The trade-off is "N× DB load and short staleness vs network round-trip on every read." For genuinely static data the in-memory choice wins; for anything that updates, distributed cache or HybridCache wins.

#### Drill 2 — Cache read/write strategies

> **Q**: Compare cache-aside, read-through, write-through, write-behind.
>
> **A**: **Cache-aside**: app reads from cache, falls through to DB on miss, manually populates. Default pattern; cache outage = slow but works. **Read-through**: cache fetches from DB on miss transparently — app talks only to cache. Encapsulated form of cache-aside. **Write-through**: writes go through cache, which synchronously writes to DB. Cache and DB always agree; slower writes. **Write-behind**: writes go to cache, return immediately, DB updated asynchronously. Fastest writes but data loss risk on crash. Cache-aside is the default; write-through for financial/inventory; write-behind only for loss-tolerant counters.
>
> **Cross-Q**: What's the consistency window in cache-aside?
>
> **A**: From DB write to cache invalidation. The classic race: (1) Thread A reads "not in cache, fetches from DB, value = X." (2) Thread B writes new value Y to DB and evicts cache. (3) Thread A finally writes X to cache — overwriting B's eviction with stale data. Cache now holds X for the next TTL. Mitigation: short TTLs, double-check timestamp before populating, write-through pattern, or "set-if-not-newer" semantics with versioning. The window can't be eliminated without giving up the simplicity.
>
> **Cross-Q²**: Write-behind crashes mid-flush. What's lost?
>
> **A**: Every write that was in the cache but hadn't been persisted yet. Magnitude depends on flush interval (typical: 1-30 seconds of writes) and queue depth. For acceptable loss surface: counters, telemetry, view counts, analytics. For unacceptable: payments, inventory, audit logs. The fix isn't to avoid write-behind everywhere — it's to scope it to data classes where loss is recoverable (re-emit metrics from logs, recompute counters from raw events).

#### Drill 3 — Cache stampede

> **Q**: A hot key expires at 14:00. 500 concurrent requests miss simultaneously. What happens?
>
> **A**: Cache stampede / thundering herd. All 500 requests fall through to the DB at once — DB CPU spikes, query queue fills, response times explode, downstream timeouts cascade. The cache "working" makes it worse: between expiration and the first populated value, every miss adds DB load. On a busy API this can take down the database.
>
> **Cross-Q**: How does single-flight (per-key locking) solve this, and what does it cost?
>
> **A**: Per-key `SemaphoreSlim` — the first miss acquires the lock, fetches from DB, populates cache; subsequent misses wait, then read from cache after release. Down to ~1 DB call per pod per TTL boundary. Cost: lock contention adds latency to concurrent misses, and the lock dictionary grows unboundedly without pruning. Per-process; on a 10-pod cluster you still get up to 10 concurrent fetches.
>
> **Cross-Q²**: HybridCache's built-in single-flight vs Redis distributed lock — when each?
>
> **A**: **HybridCache single-flight**: per-process. 10 pods can still produce 10 concurrent DB calls. Fine for most workloads — 10× is much better than 500×. **Redis distributed lock** (`SET NX PX`): cluster-wide single-flight, exactly 1 DB call per TTL boundary across all pods. Worth it when the cache miss is *very* expensive (multi-second computation, external API call costing per-request, ML inference). Risk: distributed lock failures (Redis hiccup, network split) require careful expiry and fallback paths — Redlock isn't free.

#### Drill 4 — TTL strategy

> **Q**: Fixed expiry vs sliding vs absolute — when each?
>
> **A**: **Absolute**: expires at a fixed time regardless of access. Right for freshness-critical data ("max 5 minutes stale, hard cap"). **Sliding**: TTL resets on each read. Right for session-like data ("active users stay warm, idle ones flush"). **Combined** (recommended for most cases): sliding for hotness, absolute as a backstop so nothing lives forever. Pure sliding on a hot key never expires — and never refreshes — silently stale forever.
>
> **Cross-Q**: A frequently-accessed key with sliding-only expiration. What's the bug?
>
> **A**: It never expires. Every access slides the TTL forward; the cache holds yesterday's data until the application restarts. Symptoms: "we updated the database but the API still returns the old value, and it has for hours/days." Always combine sliding with absolute: `SlidingExpiration = 5min, AbsoluteExpirationRelativeToNow = 1hr`. The absolute is the safety net.
>
> **Cross-Q²**: How do you pick a TTL value?
>
> **A**: TTL = max acceptable staleness. For a product catalog that admins edit daily: 5-30 min is fine (admins accept a few minutes for changes to propagate). For stock prices: 1-10 seconds. For user permissions: 30 seconds to 5 min depending on revocation urgency. The trade-off is hit ratio vs staleness — longer TTL = higher hit ratio but more stale data. Measure both: instrument hit ratio and have a way to detect "user saw stale data" feedback. Most apps over-cache (long TTL because nobody set one explicitly).

#### Drill 5 — Cache invalidation

> **Q**: Three invalidation strategies — TTL, tags, events. Trade-offs?
>
> **A**: **TTL**: zero coordination, always eventually consistent, but staleness equal to TTL. **Tags**: invalidate groups by name (`RemoveByTagAsync("category:42")`). Useful when one write affects many keys. Requires tag-aware cache (HybridCache, OutputCache, FusionCache). **Events**: explicit invalidation via message bus or direct call when writes happen. Tightest consistency, highest complexity — every writer must publish, every cache must subscribe, cross-service eventing in microservices. Most apps: TTL by default, tags for grouped invalidation, events for cross-service consistency-critical paths.
>
> **Cross-Q**: I update a product. With cache-aside, what do I evict?
>
> **A**: Every cache key that contained that product's data. Naively: `cache.Remove($"product:{id}")`. But also: list views (`products:category:42`), search results, summary pages. This is why tags help — tag the entry `["product:42", "category:42", "search:products"]` on populate, then `RemoveByTagAsync("product:42")` evicts every dependent. Without tags, you either enumerate the keys (fragile, easy to miss) or rely on TTL (stale window).
>
> **Cross-Q²**: Cross-service caching: Service A updates a user's permissions, Service B has cached "user 42 is admin = true." How does B find out?
>
> **A**: Three options. (1) **Short TTL** in B — accept up to N seconds of stale permissions, no coordination needed. (2) **Event-driven invalidation** — Service A publishes `UserPermissionsChanged` to a broker, Service B subscribes and evicts. Reliable but adds infrastructure. (3) **No cache in B for permissions** — call A on every check. Highest latency, perfect consistency. For security-critical caches (permissions, revocations) most teams choose (2) plus a very short TTL as fallback.

#### Drill 6 — Output caching

> **Q**: Output caching (.NET 7+) vs Response caching — what's the difference?
>
> **A**: **Response caching** sets HTTP headers (`Cache-Control: public, max-age=60`) and lets *clients/proxies/CDNs* decide whether to cache. You control via directives; you don't control storage. **Output caching** stores responses on *your server* (in-memory or distributed) and serves them before the endpoint runs. You own the storage, you control invalidation (`EvictByTagAsync`), and authenticated responses can be cached safely with custom keys.
>
> **Cross-Q**: A public read-heavy endpoint — which do you use?
>
> **A**: Both. Output caching prevents your origin from recomputing the response when the CDN can't help (cache busted, edge missing); response caching headers let the CDN serve copies without ever hitting your origin. Output cache TTL = 60s, response cache `Cache-Control: public, max-age=60, s-maxage=300` (longer for CDN). Each layer absorbs different traffic shapes. Origin sees a request only when both the CDN and the output cache miss simultaneously.
>
> **Cross-Q²**: How do you avoid accidentally caching personalized responses on a CDN?
>
> **A**: ASP.NET Core defaults to `Vary: *` and `Cache-Control: private` for authenticated responses — they won't cache on shared CDNs. Output caching by default *skips* authenticated requests. Explicit checks: in your policy, use `b.NoCache()` for authenticated paths, `b.SetVaryByCustomKey(ctx => ctx.User.Identity?.Name)` if you really need to cache per-user (rare, usually a smell). The bug pattern: `[ResponseCache(Location = Public)]` on an endpoint that returns user-specific data — every user sees the first user's response from the CDN.

#### Drill 7 — Redis vs IMemoryCache

> **Q**: When does Redis become worth the operational cost vs `IMemoryCache`?
>
> **A**: When you need (1) **shared state across instances** (sessions, JWT denylists, rate-limit counters), (2) **persistence across restarts** (don't want to rebuild caches on every deploy), (3) **larger working set than fits in one pod's heap**, or (4) **atomic operations** (`INCR`, distributed locks, pub/sub). Below those needs, Redis adds latency (1-3ms network), serialization cost, and operational ownership for negative value.
>
> **Cross-Q**: What's the latency math? When does the round-trip kill the benefit?
>
> **A**: Redis local: ~0.5-2ms. Redis cross-AZ: ~2-5ms. `IMemoryCache`: ~50ns (40,000× faster). DB query: 5-100ms. Redis wins vs DB by ~10-100×. `IMemoryCache` wins vs Redis by ~10,000×. So: if 50ns vs 1ms doesn't matter and you need sharing, Redis. If you make 1M cache reads per request hot path, even 1ms is unacceptable — switch to a hybrid pattern where L1 is in-memory and L2 is Redis (i.e., HybridCache).
>
> **Cross-Q²**: I have a single pod and no scale-out plan. Should I still use Redis?
>
> **A**: Generally no — `IMemoryCache` is simpler and faster. Exception: you need persistence (data must survive pod restart without re-fetching from a slow source), or you need pub/sub for fan-out (SignalR backplane, message broker substitute). Adding Redis "just in case we scale" is premature infrastructure — easier to migrate later than to maintain unused infra now.

#### Drill 8 — Cache key design

> **Q**: A bad cache key design — what does it look like and what does it cause?
>
> **A**: `cache.Get(productId.ToString())` — no namespacing, no tenant, no version. Causes: (1) collision risk (does `42` mean product 42 or user 42?), (2) cross-tenant leakage (tenant A's product 42 served to tenant B), (3) inability to bulk-invalidate (no shared prefix for `Scan`/eviction), (4) deploy-time bugs when serialized shape changes — old data lives on with the new code.
>
> **Cross-Q**: What does a robust key look like?
>
> **A**: `product:v2:t-acme:42:detail` — namespace (entity), version (schema), tenant (isolation), id, projection (view shape). Each segment serves a purpose: namespace prevents collisions, version invalidates on shape change, tenant prevents leakage, id locates the entity, projection distinguishes "detail" from "summary." All hyphen/colon-separated, no spaces, no untrusted input directly (sanitize via hash if needed).
>
> **Cross-Q²**: A hot key (`product:popular-item`) is causing Redis CPU spike. What's the fix?
>
> **A**: "Hot key" problem — one key serving thousands of req/sec saturates a single Redis shard. Fixes: (1) **L1 cache the hot key locally** — HybridCache pattern, in-process cache absorbs the load. (2) **Sharded keys** — `product:popular-item:shard-N` where N = random(0,10), client picks a random shard. (3) **Read replicas** — Redis replicas serve read traffic. (4) **Multi-tier** — CDN absorbs the very hot path entirely. Hot key prevention starts at design time: identify which keys will have skewed access and plan accordingly.

#### Drill 9 — Negative caching

> **Q**: A user keeps asking for `GET /products/9999` which doesn't exist. Each request hits the DB. What do you cache?
>
> **A**: The "not found" answer. **Negative caching** stores nulls/404s with a (usually shorter) TTL: `cache.Set("product:9999", null, TimeSpan.FromMinutes(1))`. Next 1000 requests get an instant 404 from cache. Without it, an attacker can DoS your DB by hammering non-existent IDs. The shorter TTL lets you recover quickly when the resource is created.
>
> **Cross-Q**: What's the gotcha with caching nulls in `IMemoryCache`?
>
> **A**: `TryGetValue` returns `false` for both "not in cache" and "in cache but value is null." You can't distinguish a real cached null from a miss. Workarounds: (1) cache a sentinel object (`new NotFound()`) instead of null; (2) wrap in `Optional<T>` / `Result<T>`; (3) use HybridCache which handles this better. The same issue affects `IDistributedCache` — serialized `null` is `0 bytes` which is ambiguous.
>
> **Cross-Q²**: When is negative caching dangerous?
>
> **A**: When the resource is *eventually* created and you cached a long "not found" — users see "doesn't exist" for the TTL after creation. Fix: short negative TTL (30s-1min) vs longer positive TTL (5-30min), and explicit invalidation on creation. Also dangerous for security-sensitive lookups — caching "user doesn't exist" leaks user enumeration if response times differ between cached negatives and DB lookups. Use constant-time responses for those.

#### Drill 10 — Stale-while-revalidate

> **Q**: What problem does stale-while-revalidate solve, and how?
>
> **A**: Eliminates "first user pays the latency" after expiration. With plain TTL, the first request after expiry triggers a DB fetch — that user waits. With SWR, the cache serves the stale value *immediately* while a background task refreshes the cache for the next request. Latency stays consistent; freshness lags by one fetch interval. Trade-off: users may see slightly stale data, but never wait for revalidation.
>
> **Cross-Q**: Does HybridCache support stale-while-revalidate natively?
>
> **A**: Not in .NET 10 as of writing — HybridCache is single-flight (deduplicates concurrent misses) but not SWR (still synchronously refreshes on miss). FusionCache (community library) implements SWR explicitly. You can DIY: when reading, check if entry is "close to expiry" and fire-and-forget a background refresh while returning the cached value. Be careful with concurrent refresh tasks and exception handling in fire-and-forget paths.
>
> **Cross-Q²**: When is SWR the wrong choice?
>
> **A**: When the data must be *fresh on read* for correctness — financial transactions, security checks, inventory counts. SWR explicitly returns potentially-stale data; if that's unacceptable, use synchronous refresh with short TTL and accept the latency. SWR is for "stale is OK if it lets latency stay flat" — UI views, catalogs, search results — not for transactional reads.

#### Drill 11 — Cache layer per service vs shared cache

> **Q**: In a microservices system, should each service have its own cache or share a single Redis cluster?
>
> **A**: **Per-service** by default. Each service owns its cache, with its own schema version and TTL semantics. Avoids coupling — Service A's cache schema changes don't break Service B. **Shared Redis cluster** is fine *physically* (one Redis ops team) as long as each service uses a different keyspace prefix (`serviceA:`, `serviceB:`). What you *don't* want is two services reading/writing the *same* keys — that's a hidden coupling and a contract you didn't agree to.
>
> **Cross-Q**: A service caches another service's data. Whose responsibility is invalidation?
>
> **A**: The owning service publishes change events. The caching service subscribes and evicts on event. Without events, the cache trusts TTL — fine for non-critical reads, dangerous for security/billing. The pattern requires asynchronous messaging infrastructure (broker, pub/sub) — adding it to a system that doesn't have one is non-trivial. Often the simpler answer is "don't cache across service boundaries; call the source service every time and let *it* cache internally."
>
> **Cross-Q²**: Two services need the same reference data (e.g., country list). Shared cache or per-service cache?
>
> **A**: Per-service. The reference data is stable but each service has its own life cycle. Sharing the cache key creates a coupling: if Service A's developer changes the schema, Service B breaks until updated. Each service should call the owning service (or a flat file/embedded data) and cache locally. The data is small; duplication is cheaper than coupling. Exception: very large reference data (e.g., 10M product catalog) where duplication wastes memory — then accept the coupling carefully with versioned keys.

#### Drill 12 — EF Core second-level cache

> **Q**: Does EF Core have a second-level cache like Hibernate?
>
> **A**: No, not built-in. EF Core has *first-level* cache (the change tracker within a single `DbContext` instance) but no shared-across-context cache. Community libraries exist (EFCoreSecondLevelCacheInterceptor, EFCore.Cacheable) that intercept queries and cache results — but Microsoft has deliberately not built one into the framework.
>
> **Cross-Q**: Why hasn't Microsoft built one?
>
> **A**: Two reasons. (1) Invalidation is hard — any tracked change can invalidate any cached query, and tracking *which* queries depend on *which* entities is complex (Hibernate has years of subtle bugs here). (2) Microsoft prefers explicit caching at the application layer (`IMemoryCache` / `HybridCache`) where the developer decides what to cache and when to invalidate. The EF Core team has stated it's not on the roadmap. Use application-level caching with explicit invalidation.
>
> **Cross-Q²**: Should I use a third-party EF second-level cache?
>
> **A**: Usually no. Third-party EF caches work via query interception — automatic but hard to reason about. You don't control TTL per query, eviction patterns surprise you, and the invalidation logic is opaque. Explicit caching at the service layer is more verbose but predictable. Reserve EF second-level caches for legacy projects with very EF-coupled architectures where retrofitting service-layer caching is impractical.

#### Drill 13 — CDN as cache

> **Q**: How does CDN fit into the cache hierarchy, and what's "push" vs "pull"?
>
> **A**: CDN is the outermost layer — closest to the user, geographically distributed, absorbing public read traffic before it reaches your origin. **Pull**: CDN fetches from origin on first request to a path, then caches per response headers. Default mode for most CDNs (Cloudflare, CloudFront). **Push**: you upload assets to the CDN explicitly via API. Used for build artifacts (JS bundles, images) where you want the asset available at the edge before any user requests it.
>
> **Cross-Q**: A user hits a CDN edge that has stale content. What happens?
>
> **A**: Edge serves the stale content per its cached `Cache-Control` (until `max-age` expires or you've called CDN's purge API). You can trigger refresh: (1) **TTL expiry** — edge fetches from origin on next request after `max-age`. (2) **Purge by URL** — CDN API call invalidates a specific path or pattern; next request triggers a fresh fetch. (3) **Versioned URLs** — change the URL (e.g., `app.v2.js`), edge has no cached copy, fetches fresh. Versioning is the safest pattern for static assets — never need to purge, just deploy a new version.
>
> **Cross-Q²**: My API returns dynamic per-user JSON. Should I cache it on a CDN?
>
> **A**: Almost certainly not — personalized JSON has cardinality = number of users × paths, defeating the cache's purpose. Exceptions: cacheable per-user responses with explicit `Vary` headers (rare and operationally complex), or splitting the response into shell + data where the shell is cacheable and the data is fetched separately. The right pattern: cache *static* assets (JS/CSS/images) on CDN, fetch *dynamic* JSON from origin with output caching at the application layer.

#### Drill 14 — Eviction policies

> **Q**: LRU vs LFU vs absolute — when each?
>
> **A**: **LRU** (Least Recently Used) — evicts the entry not accessed for the longest time. Good general default; assumes "recent = useful." **LFU** (Least Frequently Used) — evicts the entry with the lowest access count. Better when access patterns are stable and old-but-popular keys should stay. **Absolute** (TTL-based eviction) — evicts on time, not access. Use when freshness, not popularity, drives eviction. `IMemoryCache` uses size-based eviction with priority hints (`CacheItemPriority`); Redis offers configurable `maxmemory-policy` (LRU, LFU, allkeys, volatile variants).
>
> **Cross-Q**: A cache hits its size limit. What does `IMemoryCache` do exactly?
>
> **A**: Runs a *compaction* pass: evicts entries by priority (Low → Normal → High → NeverRemove) until total size drops by `CompactionPercentage` (default 25%). Within a priority bucket it uses time since last access (LRU-ish). The next `Set` succeeds. Caveat: `SizeLimit` is enforced *after* the next `Set`, not during — there's a brief window where memory exceeds the cap. Set `CompactionPercentage` higher (0.5+) on memory-pressured hosts so compaction frees more headroom per pass.
>
> **Cross-Q²**: Redis is configured `maxmemory-policy noeviction`. What happens when memory fills?
>
> **A**: Redis refuses new writes — `SET` returns `OOM`. Reads continue to work. This is the right policy for "Redis as authoritative store" (sessions you don't want evicted unexpectedly) but wrong for "Redis as cache" (where you'd rather lose old data than refuse new writes). Pick policy by data class: `allkeys-lru` or `allkeys-lfu` for cache, `noeviction` for source-of-truth data, `volatile-lru` for mixed (only evict keys with explicit TTL). Misconfiguration causes "Redis stopped accepting writes at 3am" production incidents.

#### Drill 15 — "I'll just cache it"

> **Q**: A senior engineer says "this endpoint is slow, let's just cache it." Why is that often wrong?
>
> **A**: It treats caching as a free fix. Real costs: (1) **Invalidation complexity** — every write site must remember to evict; bugs cause stale data. (2) **Tenant/security leakage** if keys aren't scoped properly. (3) **Stampede risk** on cold start. (4) **Operational surface** — observability, eviction monitoring, memory tuning. (5) **Mask the root cause** — the endpoint may be slow due to N+1 queries, missing index, or bad query plan; caching hides the symptom and the bug ships. Caching is a *deliberate* design decision, not a default.
>
> **Cross-Q**: What's the diagnosis sequence before reaching for cache?
>
> **A**: (1) **Profile the endpoint** — where is time spent? DB query? External call? Serialization? (2) **Optimize the actual hot spot** — add an index, fix N+1 with `.Include`, paginate, switch to a leaner projection. Often you can drop 100ms to 10ms without a cache. (3) **Measure post-optimization** — is it now fast enough? (4) **Only then**, if still slow under real load, *and* the data is cacheable (stable, non-personalized, tolerant of staleness), introduce caching. The senior's instinct skips (1)–(3).
>
> **Cross-Q²**: When is "just cache it" the right answer?
>
> **A**: When the source is irreducibly slow and cacheable. Examples: third-party API with 200ms latency that bills per call (cache, hard), expensive computation (ML inference, report generation), aggregate query that requires a full table scan and runs every page load. The data is stable enough to tolerate the cache TTL, the access pattern is read-heavy, and invalidation is tractable. The shortcut is fine when the underlying constraint genuinely can't be optimized further — and you understand the costs.

</details>

---

### Self-Test

<details>
<summary>1. Why is a <code>SlidingExpiration</code> on its own almost always wrong for a hot cache entry?</summary>

Sliding expiration measures *inactivity* — every read pushes the expiry out by another interval. A hot key is by definition read more often than that, so it never goes inactive, never expires, and never re-runs its factory. Microsoft's in-memory caching guidance states it plainly: an item set with only a sliding expiration is at risk of never expiring.

The production shape is the tell: "we changed the price in the database this morning, the API is still serving the old one, and restarting the pod fixes it." Nothing looks broken — high hit ratio, no errors, no evictions — which is why it survives code review and then lives for weeks.

Fix: always pair it with a hard cap. `SlidingExpiration = 5 min` plus `AbsoluteExpirationRelativeToNow = 1 hr`; whichever elapses first evicts the entry, and sliding never extends an entry's life beyond the absolute expiration. Sliding keeps genuinely hot entries warm, absolute guarantees nothing lives forever.
</details>

<details>
<summary>2. I wrapped the catalog read in <code>IMemoryCache.GetOrCreateAsync</code> with a five-minute expiration. The database still shows a burst of identical queries every five minutes. What's happening?</summary>

`GetOrCreateAsync` is an extension method over `IMemoryCache` with no lock around the factory — it is look, miss, run factory, populate. Every request arriving between the entry expiring and the first factory call completing sees an empty key and runs its own factory. Microsoft's in-memory caching notes say exactly this: multiple requests can find the cached key value empty because the callback hasn't finished, and several threads can end up repopulating the item. The size of the burst is the endpoint's concurrency at the expiry boundary — not something you configured.

Two fixes. `HybridCache.GetOrCreateAsync` gets it for free: a `HybridCache` instance funnels concurrent callers for a given key into one factory call and the rest await that result. Hand-rolled, it's a per-key `SemaphoreSlim`, re-checking the cache *after* acquiring the lock (the double-check), plus something that prunes the lock dictionary or it grows unbounded.

The part people miss: both are per-process. `HybridCache`'s coordination explicitly does not extend to other `HybridCache` instances, so across ten pods you still get up to ten factory calls per boundary. Ten instead of five hundred usually ends the conversation; when the miss is genuinely expensive — a multi-second computation, a third-party call billed per request — you need a cluster-wide lock (Redis `SET NX PX`), and then you own the lock's expiry and the fallback path for when Redis is unreachable.
</details>

<details>
<summary>3. Trade-off: hand-wiring <code>IMemoryCache</code> in front of <code>IDistributedCache</code> versus using <code>HybridCache</code>, for a catalog API running on ten pods.</summary>

Hand-wired, you write and own the L1 lookup, the L2 lookup, serialize and deserialize, populating both tiers on a miss, two sets of expirations, and a stampede lock. Each is a place to be subtly wrong, and the serialized shape becomes a contract you have to version yourself.

`HybridCache` collapses that into one `GetOrCreateAsync` that walks L1 → L2 → factory and writes back to both tiers. Serialization is built in (`string` and `byte[]` handled internally, `System.Text.Json` for everything else, swappable for protobuf or XML). Stampede protection comes with it. And it adds `RemoveByTagAsync`, which neither `IMemoryCache` nor `IDistributedCache` offers at all. `Expiration` and `LocalCacheExpiration` let you hold L2 long and L1 short.

What you still have to know, because it sets your TTLs: L1 is per-process, and invalidation reaches only the current server plus the distributed store — the in-memory copies on the other nine pods are untouched by a `RemoveAsync` or a `RemoveByTagAsync`. `LocalCacheExpiration` is therefore your real fleet-wide staleness bound, and "the admin's edit propagates everywhere in seconds" holds only if you keep it short or add your own backplane. Tag invalidation is also logical rather than physical: it records an "ignore anything created before this point" rule, so superseded entries keep occupying memory and Redis until they expire normally. Keep hand-wiring only for what the abstraction won't do — a bespoke read-through pipeline, or stale-while-revalidate (FusionCache implements SWR, and also ships as a `HybridCache` implementation).
</details>

<details>
<summary>4. Analyze: <code>cache.Set(product.Id.ToString(), product, TimeSpan.FromMinutes(30))</code> in a multi-tenant SaaS. Refactor it.</summary>

Worst first: there is no tenant in the key. `42` is global, so whichever tenant misses first populates it and every other tenant reads *that* tenant's product for the next thirty minutes. That is a data-disclosure incident, not a caching bug, and it cannot reproduce on a single-tenant dev box.

Then: no namespace, so `42` collides with user 42 or order 42 in the same cache. No schema version, so the next deploy that changes the DTO reads yesterday's shape back out — a stale in-process object under `IMemoryCache`, a deserialization failure or a silently wrong object under a distributed cache. No projection, so `detail` and `summary` callers share one entry and whoever populates first decides what both receive. And caching the EF entity instead of a DTO drags the change tracker and the whole object graph in with it.

Refactor: one helper so no call site invents its own format, and cache the DTO rather than the entity.

```csharp
static string ProductKey(string tenant, int id, string view = "detail") =>
    $"product:v2:{tenant}:{id}:{view}";
```

The rule that isn't about shape: never concatenate raw user input into a key. Microsoft's cache-key guidance calls this out directly — arbitrary user-supplied keys let an attacker flood the cache with meaningless entries and exhaust memory. Hash or validate anything that arrived over the wire.
</details>

<details>
<summary>5. Explain what output caching gives you that response caching can't, and name one risk.</summary>

Response caching is defined by HTTP headers. `[ResponseCache]` only sets them; the Response Caching Middleware does keep a server-side copy, but it still follows the directives the client sends, which is how the client defeats it — browsers such as Chrome and Edge send `Cache-Control: max-age=0`, the middleware obeys, and the origin regenerates a response it already had. Whatever browsers, proxies and CDNs stored you can neither enumerate nor recall, and the middleware's own store is limited to memory.

Output caching stores the response on your server, ahead of the endpoint. Because you own the store you get server-side policy the client can't override; extensible storage; programmatic invalidation (`.Tag("products")` in the policy, `IOutputCacheStore.EvictByTagAsync("products", ct)` on the write path); resource locking, on by default, so a burst of requests for one uncached response waits on a single execution instead of stampeding; and revalidation, answering `If-None-Match` / `If-Modified-Since` with a 304 instead of the body.

The risk: the cached artifact is a whole rendered response, so a key mistake hands one user's data to another. The key defaults to the entire URL, and `SetVaryByQuery` / `SetVaryByHeader` / `VaryByValue` are how you add everything else it varies on — miss a dimension and you serve the wrong body. The default policy is conservative for exactly this reason (200s only, GET and HEAD only, nothing that sets cookies, nothing for authenticated requests), and the classic way to defeat it is pipeline order: `UseOutputCache` must come *after* `UseAuthentication` and `UseAuthorization`, or the middleware can serve content cached for unauthorized users to authorized ones. Reaching for a custom vary-by-user key to cache per user is usually the signal that the response shouldn't be output-cached at all.
</details>

---
### Cross-References

- **[Redis Deep Dive](../../03-data-and-persistence/05-redis.md)** — data structures, persistence, clustering, distributed locks.
- **[Security](./09-security.md)** — JWT denylist via distributed cache; rate limiting via Redis counters.
- **[Memory & Performance](../05-csharp-mastery/09-memory-and-performance.md)** — heap pressure from unbounded caches; GC interaction.
- **[API Design Principles](../../02-api-development/03-api-design-principles.md)** — output caching, ETags, conditional requests.
- **[System Design Prep](../../08-craft-and-interview-prep/03-system-design-prep.md)** — caching tier decisions in interview-style designs.
- **[Service Worker & PWA](../../07-frontend-integration/04-service-worker-and-pwa.md)** — client-side caching counterpart.
- **[InfluxDB](../../03-data-and-persistence/06-influxdb.md)** — clarification: a time-series DB is not a cache.
- **[Version History](./18-version-history.md)** — `HybridCache` (.NET 9) and related additions.

---

### Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — *Cache in-memory in ASP.NET Core* and *Distributed caching*.
- Microsoft Learn — *HybridCache library in ASP.NET Core* (.NET 9+).
- Microsoft Learn — *Output caching middleware* and *Response caching middleware*.
- StackExchange.Redis documentation.
- Phil Karlton (attributed) — "There are only two hard things in computer science…"
- Cloudflare Engineering — *Why probabilistic early expiration prevents thundering herds*.

---

</details>
<!-- nav-footer-start -->

---

[← Previous: Security & Authentication](09-security.md) · [↑ Back to top](#caching-strategies) · [Next: SignalR — Real-Time Communication →](11-signalr.md)

<!-- nav-footer-end -->
