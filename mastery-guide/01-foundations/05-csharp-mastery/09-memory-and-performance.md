# Memory & Performance Idioms

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › [C# Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 1 — Language & Runtime Fluency | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [The allocation taxonomy](#the-allocation-taxonomy)
  - [GC fundamentals — generations, LOH, POH](#gc-fundamentals--generations-loh-poh)
  - [Workstation vs Server GC; concurrent vs background](#workstation-vs-server-gc-concurrent-vs-background)
  - [`Span<T>` and `ReadOnlySpan<T>`](#spant-and-readonlyspant)
  - [`Memory<T>` and `ReadOnlyMemory<T>`](#memoryt-and-readonlymemoryt)
  - [`stackalloc`](#stackalloc)
  - [`ArrayPool<T>` and `MemoryPool<T>`](#arraypoolt-and-memorypoolt)
  - [`ValueTask` vs `Task` — deep dive](#valuetask-vs-task--deep-dive)
  - [Defensive copy trap with structs](#defensive-copy-trap-with-structs)
  - [`ref` returns and `ref` locals](#ref-returns-and-ref-locals)
  - [`IDisposable` and `IAsyncDisposable` — the full pattern](#idisposable-and-iasyncdisposable--the-full-pattern)
  - [Allocation-free string building](#allocation-free-string-building)
  - [Boxing checklist — when value types secretly allocate](#boxing-checklist--when-value-types-secretly-allocate)
  - [`unsafe` and pointers](#unsafe-and-pointers)
  - [Sizing decisions: when each tool wins](#sizing-decisions-when-each-tool-wins)
  - [Measurement: BenchmarkDotNet](#measurement-benchmarkdotnet)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--gen-2-pressure-from-string-concat)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

The .NET BCL since .NET Core 2.1 has been quietly rebuilt around a low-allocation philosophy: `Span<T>`, `ReadOnlySpan<T>`, `string.Create`, `ArrayPool<T>`, ref structs, and source-generated paths. The library team's goal — "you should rarely need to write `unsafe`" — is largely realized: 95% of allocation-free code now uses safe primitives.

For a senior backend engineer, this matters in two contexts: (1) writing hot-path code (parsers, serializers, telemetry, framework internals) where each allocation costs measurable GC pressure; (2) reading the BCL source to understand *why* `string.Concat` is faster than `+`, why `Utf8JsonReader` doesn't allocate, why `LoggerMessage` source-gen exists. The mental model is: "for every allocation, ask if it's necessary, and if a `Span<T>`-based alternative exists."

This file is the practical end of the type-system chapter — `ref struct`, `readonly struct`, generics + `unmanaged` constraint all converge here.

## Core concepts

### The allocation taxonomy

Five places allocations can come from in a typical .NET app, ranked by frequency:

1. **Object instantiation** — `new Foo()` for a class. Heap allocation in Gen 0.
2. **Boxing** — value type stored in `object` / interface. Heap allocation, pure GC pressure since the value type itself is small.
3. **String operations** — `+`, `Replace`, `Substring`, `Trim` — each returns a *new* string.
4. **Array creation** — `new int[1024]` (heap) vs `stackalloc int[1024]` (stack).
5. **Closure capture** — lambda capturing a local creates a heap-allocated closure object.

Allocation isn't always bad — Gen 0 collections are fast. But on hot paths (request handlers, parsers, log formatters, serializers), persistent allocation pressure causes:
- More frequent Gen 0 collections (stop-the-world, brief).
- Promotion to Gen 1/2 (more expensive collections).
- Fragmentation in the LOH for big allocations.
- Inflated working set.

**Rule of thumb:** profile first (BenchmarkDotNet, dotnet-counters, dotMemory). Don't pre-optimize. But once you know where the pressure is, reach for the tools below.

### GC fundamentals — generations, LOH, POH

The .NET GC is **generational** and **mark-and-sweep**. Allocations land in a generation; survivors are *promoted* to older generations; only the surviving objects are scanned at each collection. The win: young objects die fast, so most allocations are reclaimed by a cheap collection that ignores 99% of the heap.

**The five regions** (.NET 5+):

| Region | What lands here | Collection cost | How often |
|---|---|---|---|
| **Gen 0** | New small-object allocations (`< 85,000 B`) | Microseconds | Frequent (every few MB allocated) |
| **Gen 1** | Survivors of one Gen 0 collection | Microseconds | Less frequent (~10× rarer than Gen 0) |
| **Gen 2** | Survivors of two collections (long-lived objects, statics, caches) | Milliseconds–seconds | Rare (~10–100× rarer than Gen 1) |
| **LOH** (Large Object Heap) | Single allocations `≥ 85,000 B` | Expensive (treated like Gen 2) | Collected only on Gen 2 |
| **POH** (Pinned Object Heap, .NET 5+) | Objects allocated via `GC.AllocateArray<T>(len, pinned: true)` | Like Gen 2, but never moves | Rare |

**Collection frequencies (rules of thumb on a typical web service)**:

- **Gen 0**: every ~256 KB to a few MB of allocations on the current thread. Pause ~< 1 ms.
- **Gen 1**: ~1 in 10 Gen 0 collections promotes enough to trigger Gen 1.
- **Gen 2**: every few seconds to minutes depending on long-lived allocation rate. Pause **10s–100s of ms** on workstation GC, lower on Server GC. **This is what hurts p99 latency.**
- **LOH**: contributes to Gen 2 pressure; large strings, large arrays, large JSON payloads.

**Why the 85,000-byte LOH threshold?**

Three reasons, in order of importance:

1. **Copying cost** — the GC reclaims Gen 0/1/2 with a **compacting** algorithm: it copies surviving objects to remove holes. Copying an 80 KB array on every collection is wasteful. Past some size, the cost of moving the object exceeds the cost of leaving a hole. Microsoft empirically chose 85,000 bytes (~20 × 4 KB pages on x86).
2. **CLR design history** — that number is hard-coded for backward compatibility. It's *not* tunable per app (without unsupported COM-host hooks).
3. **Alignment** — 85,000 happens to align well with 8 KB segments the GC uses for LOH internally.

**LOH consequences**:

- **No compaction by default** (you can opt in with `GCSettings.LargeObjectHeapCompactionMode = CompactOnce` then trigger a Gen 2 collection — expensive, use sparingly).
- **Fragmentation** — repeatedly allocating/freeing differently-sized big objects leaves holes the GC can't reuse efficiently.
- **Gen 2 pressure** — every LOH allocation is essentially a Gen 2 allocation; bulk LOH activity drives Gen 2 collection frequency up.

**Pinned Object Heap (POH, .NET 5+)**

Before POH, pinning an object via `fixed (byte* p = arr)` or `GCHandle.Alloc(arr, GCHandleType.Pinned)` left the object **in its current generation** — typically Gen 0 — but marked it un-moveable. This blocks compaction during the next collection, leaving holes around the pinned object: **heap fragmentation**.

POH separates pinned allocations into their own region from day one. The GC knows nothing in POH will ever move, so it doesn't try to compact around it.

```csharp
// .NET 5+ — allocate directly into POH
byte[] buffer = GC.AllocateArray<byte>(length: 1024, pinned: true);

// Equivalent for ref types: GC.AllocateUninitializedArray<T>(len, pinned: true)
// (slightly faster — skips zero-init for value types)

// vs. old way (causes fragmentation):
byte[] regular = new byte[1024];
GCHandle handle = GCHandle.Alloc(regular, GCHandleType.Pinned);
IntPtr ptr = handle.AddrOfPinnedObject();
// ... use ptr ...
handle.Free();
```

**When to use POH**:

- Long-lived buffers passed to native interop (the OS or driver holds the pointer for hours).
- Network pipelines (Kestrel, gRPC) where the kernel writes directly into managed buffers.
- Scenarios where you'd otherwise pin frequently and fragment the heap.

Most application code never touches POH directly — the BCL uses it internally (e.g., `System.IO.Pipelines`, socket buffers).

### Workstation vs Server GC; concurrent vs background

Two orthogonal axes control GC behavior. **They're set at process start** via the `.runtimeconfig.json` or environment variables and **cannot be changed after the process is running**.

**Workstation vs Server**

| | Workstation GC | Server GC |
|---|---|---|
| Heap layout | One heap, shared | One heap **per logical CPU** |
| GC threads | Same as user thread (stop-the-world on one thread) | Dedicated GC thread per heap, runs in parallel |
| Allocation throughput | Lower (single heap = contention) | Much higher (per-CPU heaps, near-zero contention) |
| Pause time | Often higher (single-threaded mark/sweep) | Lower per pause (parallel mark/sweep across heaps) |
| Memory footprint | Smaller | Larger (per-CPU heaps, larger segments) |
| Default for | Console apps, desktop, libraries | **ASP.NET Core**, services |

ASP.NET Core defaults to **Server GC** when running on a machine with ≥ 2 logical CPUs. You can verify with `GCSettings.IsServerGC` (`true` on a typical web host).

**Concurrent / Background GC**

Concurrent GC (workstation) and Background GC (server, .NET 4.5+) allow **most of a Gen 2 collection to run on a background thread** while user threads keep allocating in Gen 0. The stop-the-world phase shrinks to the brief mark roots + end-of-collection compact step.

| Mode | Setting | Effect |
|---|---|---|
| **Background GC** | `System.GC.Concurrent: true` (default true on Server) | Gen 2 runs mostly in background; Gen 0/1 still stop-the-world but very fast |
| **Non-concurrent** | `System.GC.Concurrent: false` | All collections stop-the-world; lower latency variance but worse p99 under load |

**Recommended config for a web service** (in `.csproj` or `runtimeconfig.json`):

```xml
<PropertyGroup>
  <ServerGarbageCollection>true</ServerGarbageCollection>
  <ConcurrentGarbageCollection>true</ConcurrentGarbageCollection>
  <RetainVMGarbageCollection>true</RetainVMGarbageCollection>  <!-- keep segments around for reuse -->
</PropertyGroup>
```

Or via environment variables (containers):

```
DOTNET_gcServer=1
DOTNET_gcConcurrent=1
```

**Dynamic Adaptation to Application Sizes (DATAS, .NET 8+)**

A newer mode that auto-tunes Server GC for low-memory containers (avoiding the "Server GC uses too much RAM" trap in 256 MB Kubernetes pods). Enable via `DOTNET_GCDynamicAdaptationMode=1` or `<GarbageCollectionAdaptationMode>1</GarbageCollectionAdaptationMode>`. On .NET 9+ it's stable and recommended for containerized services.

**`GC.Collect()` — when to call it**

**Almost never.** The GC is significantly smarter than your manual intuition about when to collect. Forcing a collection wastes CPU and disrupts the GC's heuristics about heap shape. The two legitimate cases:

1. **After a known one-time large allocation phase** (e.g., loading a large data set once at startup, then never again). Calling `GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: true)` once at the end can reclaim and compact before steady-state begins.
2. **Benchmarking** — to bring the heap to a known state between iterations.

`GC.Collect()` in a hot path is a code smell that always loses on a benchmark.

### `Span<T>` and `ReadOnlySpan<T>`

`Span<T>` is the headline allocation-killing primitive. It's a `ref struct` (stack-only) that represents a contiguous region of memory — *without owning it*. The same `Span<T>` API can wrap:
- A heap array (`new int[100].AsSpan()`).
- A stack array (`stackalloc int[100]`).
- Native memory (interop scenarios).
- A slice of any of the above (`span.Slice(10, 20)`).

```csharp
// Wrap an array
int[] arr = new int[10];
Span<int> span = arr.AsSpan();

// Wrap stack memory
Span<int> stack = stackalloc int[10];

// Slicing — no allocation, just adjusts pointer + length
Span<int> middle = span.Slice(2, 5);     // arr[2..7]

// Indexing
span[0] = 42;
int x = span[0];

// Iteration
foreach (var v in span) Console.WriteLine(v);

// Copy
span.CopyTo(other);
```

**`ReadOnlySpan<T>`** is the immutable cousin — same shape, no `set` indexer. `string` exposes a `ReadOnlySpan<char>` view via `s.AsSpan()` and `MemoryExtensions.AsSpan(s)`.

**Why a ref struct:** if `Span<T>` could escape to the heap (as a class field or boxed `object`), it could survive past the lifetime of the underlying memory (e.g., a `stackalloc` whose stack frame is gone). The ref-struct constraint *guarantees* the span doesn't outlive its data.

**Restrictions** (because `ref struct`):
- Cannot be a field of a class or non-`ref struct`.
- Cannot be captured by a lambda or local function.
- Cannot cross `await` or `yield return`.
- Cannot be boxed.
- (Pre-C# 13) cannot be a generic argument; C# 13's `allows ref struct` constraint relaxes this.

In exchange: zero allocation, near-pointer speed, safe.

### `Memory<T>` and `ReadOnlyMemory<T>`

`Span<T>` can't cross async boundaries. For async parsing / streaming where you need a memory view that *can* be a class field or survive an `await`, use `Memory<T>`.

```csharp
async Task ProcessAsync(Memory<byte> buffer, CancellationToken ct)
{
    int read = await stream.ReadAsync(buffer, ct);
    // process buffer.Span (slice into it after the await)
    ParseLine(buffer.Span.Slice(0, read));
}

void ParseLine(ReadOnlySpan<byte> line) { /* sync, span-based */ }
```

`Memory<T>` is a regular struct (not ref struct), so it can be stored in a class, returned from async, etc. To do actual work, you go through `.Span` to get a `Span<T>` for that scope.

**The pattern:**
- `Memory<T>` for storage and async transit.
- `Span<T>` for synchronous processing (where you do the actual work).

### `stackalloc`

`stackalloc` allocates on the **stack**, not the heap. Lifetime is the enclosing method (the stack frame). Combined with `Span<T>`, it's how you get array-like access without GC pressure:

```csharp
public bool ParseSimple(ReadOnlySpan<char> input)
{
    Span<int> tokens = stackalloc int[8];   // 32 bytes on stack
    int count = 0;

    // ... fill tokens ...

    return Validate(tokens.Slice(0, count));
}
```

**When `stackalloc` is safe** (the four conditions — all must hold):

```
✓ Size is bounded by a compile-time constant or clamped to a known small max (≤ ~1 KB ideal, ≤ 4 KB max)
✓ Scope is bounded — never returned, never stored in a field, never crosses await or yield
✓ Not inside a loop — every iteration adds to the stack frame; you'll overflow
✓ Element type is unmanaged (no reference types in stackalloc — only structs without references)
```

**When `stackalloc` overflows:**

The CLR does not check available stack before `stackalloc`. If your `stackalloc byte[size]` exceeds the remaining stack (typical thread stack: 1 MB on Windows, 8 MB on Linux), the result is **immediate process termination** — no `StackOverflowException` you can catch, no second chance. The thread (and the whole process in modern .NET) just dies.

The risk is real because:
- ASP.NET Core's request stack already has ~100s of KB consumed by the middleware pipeline.
- Recursive code (e.g., parsers, expression evaluators) reduces the remaining stack on each call.
- `stackalloc` in a generic method gets duplicated per JIT specialization; nested generics compound.

**The safe pattern** — used throughout the .NET BCL (`Utf8JsonReader`, `Path`, `Regex`):

```csharp
const int StackThreshold = 256;

void Process(ReadOnlySpan<char> input)
{
    // Adaptive: stack for small, pool for big
    byte[]? rented = null;
    Span<byte> buffer = input.Length <= StackThreshold
        ? stackalloc byte[StackThreshold]
        : (rented = ArrayPool<byte>.Shared.Rent(input.Length));

    try
    {
        var slice = buffer.Slice(0, input.Length);
        // ... use slice ...
    }
    finally
    {
        if (rented is not null)
            ArrayPool<byte>.Shared.Return(rented);
    }
}
```

**Performance vs `new byte[]`**

| Allocation | Cost per call | GC pressure | Notes |
|---|---|---|---|
| `new byte[1024]` | ~30–50 ns | Gen 0 contribution | Allocated in Gen 0; survives if escaped |
| `stackalloc byte[1024]` | ~1–2 ns (frame adjustment) | **Zero** | Reclaimed automatically when method returns |
| `ArrayPool<byte>.Shared.Rent(1024)` | ~20–40 ns rent + ~10 ns return | Zero (amortized) | First rent allocates; subsequent rents are free |

For tight loops doing 1M iterations: `stackalloc` saves 30–50 ms of allocation cost and ~1–2 GB/s of GC pressure compared to `new`.

**`stackalloc` requires unmanaged element types** — references would create issues for the GC (which doesn't scan stack frames the same way as heap). `stackalloc string[10]` is a compile error.

### `ArrayPool<T>` and `MemoryPool<T>`

For buffers too big for `stackalloc` (or for variable sizes), the BCL ships **`ArrayPool<T>.Shared`** — a thread-safe pool that gives you a power-of-2-sized array and reclaims it on return.

```csharp
var pool = ArrayPool<byte>.Shared;
byte[] buffer = pool.Rent(1024);
try
{
    // use buffer (length may be > 1024 — it's at least 1024)
    int read = stream.Read(buffer, 0, 1024);
    Process(buffer.AsSpan(0, read));
}
finally
{
    pool.Return(buffer, clearArray: false);   // 'true' if buffer held PII
}
```

`MemoryPool<T>` gives you `IMemoryOwner<T>` — a wrapper that's `IDisposable`, returning the memory automatically. Cleaner for `using` blocks:

```csharp
using IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(1024);
Memory<byte> mem = owner.Memory;
// use mem
```

**Rent and return — the `IDisposable` pattern**

`ArrayPool<T>` itself doesn't expose `IDisposable`; the BCL idiom is **`try/finally` with explicit Return**, or use `MemoryPool<T>` which wraps the rental in `IMemoryOwner<T> : IDisposable`. For consistency in modern code:

```csharp
// Pattern 1: try/finally (most explicit, lowest overhead)
byte[] buffer = ArrayPool<byte>.Shared.Rent(size);
try
{
    Use(buffer.AsSpan(0, size));
}
finally
{
    ArrayPool<byte>.Shared.Return(buffer);
}

// Pattern 2: IMemoryOwner via using (cleaner, ~10 ns extra)
using IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(size);
Use(owner.Memory.Span.Slice(0, size));

// Pattern 3: helper struct (your own RAII wrapper)
public readonly struct PooledArray<T> : IDisposable
{
    public T[] Array { get; }
    private readonly ArrayPool<T> _pool;
    public PooledArray(int size, ArrayPool<T>? pool = null)
    {
        _pool = pool ?? ArrayPool<T>.Shared;
        Array = _pool.Rent(size);
    }
    public void Dispose() => _pool.Return(Array);
}
```

**When to rent / when to skip the pool**

| Buffer size | Strategy |
|---|---|
| ≤ ~256 B | `stackalloc` (faster than rent overhead) |
| 256 B – 4 KB | `stackalloc` if safe, else pool |
| 4 KB – 84,999 B | **`ArrayPool<T>.Rent`** (sweet spot — avoids Gen 0 churn) |
| ≥ 85,000 B | `ArrayPool<T>.Rent` is essential — avoids LOH pressure |
| Very rare allocation, large | Consider `new` once + cache as static |

The pool's rent/return overhead (~20–40 ns) makes it lose to `stackalloc` and `new` for tiny one-shot allocations. The breakpoint where pooling wins is roughly **when allocation frequency exceeds 10K/sec on the same path**.

**Pool-cleared-on-return considerations**

`Return(array, clearArray: false)` is the default — fast, but the **next caller sees your old data** in the unused portion of the array. Three concerns:

1. **PII leak** — if you stored credit-card numbers, JWTs, passwords, or user data in the buffer, pass `clearArray: true` on return to zero it out (or wipe manually with `Array.Clear` before return).
2. **Security audit failure** — security review will flag any pool usage without explicit consideration of clearing. Add a comment in your code stating whether the buffer can hold sensitive data.
3. **Reference types arrays** (`ArrayPool<object>`, `ArrayPool<string>`) — for reference types, `clearArray` defaults to **true** (not false) automatically. The runtime forces clearing to avoid keeping objects alive past their intended lifetime (otherwise the GC would treat the pool as a leak). Knowing this saves you from a "why is my object not getting collected" debug session.

```csharp
// Sensitive data — always clear
ArrayPool<byte>.Shared.Return(jwtBuffer, clearArray: true);

// Non-sensitive numeric data — clear is wasted CPU
ArrayPool<int>.Shared.Return(indexBuffer, clearArray: false);
```

**Custom pool instances**

`ArrayPool<T>.Shared` is one global pool per element type. If you have a hot path that needs predictable rent behavior independent of the rest of the process, you can create a dedicated pool:

```csharp
private static readonly ArrayPool<byte> _myPool =
    ArrayPool<byte>.Create(maxArrayLength: 1024 * 1024, maxArraysPerBucket: 50);
```

Rare — the shared pool is well-tuned for most workloads. Only reach for a custom pool when profiling shows shared-pool contention or you need bounded memory.

**The "never touch after return" rule**

After `Return`, the array may be in another thread's hands within microseconds. **Any access — read or write — is a use-after-free at the managed level**: you'll see torn data, corrupted state, or "impossible" race conditions. Set the rental variable to `null` after returning if you're unsure:

```csharp
byte[]? buffer = ArrayPool<byte>.Shared.Rent(size);
try { /* use buffer */ }
finally
{
    var local = buffer;
    buffer = null;        // null out before returning to prevent accidental reuse
    ArrayPool<byte>.Shared.Return(local);
}
```

`ArrayPool<T>` is what `MemoryStream`, `Pipe`, `Utf8JsonReader`, and many ASP.NET internals use under the hood.

### `ValueTask` vs `Task` — deep dive

`Task` is a **class** (heap allocation per async invocation). `ValueTask<T>` is a **struct** (zero allocation when the result is synchronous). The point: hot async paths that **frequently complete synchronously** (cached result, fast-path check) save the Task allocation entirely.

```csharp
// Task version — always allocates a Task object
public async Task<User> GetUserAsync(int id)
{
    if (_cache.TryGet(id, out var user))
        return user;                 // even synchronous return allocates a Task<User>
    return await _db.GetUserAsync(id);
}

// ValueTask version — synchronous path is allocation-free
public ValueTask<User> GetUserAsync(int id)
{
    if (_cache.TryGet(id, out var user))
        return new ValueTask<User>(user);  // wraps result in the struct, zero alloc
    return new ValueTask<User>(_db.GetUserAsync(id));  // wraps the Task when async
}
```

**When to use `ValueTask`**

- The method **frequently completes synchronously** (≥ 50% of calls hit a cache/early-exit).
- The method is on a **hot path** (called millions of times — the Task allocation matters).
- The method is part of a high-throughput API surface like a serializer, parser, or codec.

**When `Task` is the right choice**

- General-purpose APIs that callers may store, await multiple times, or use with `Task.WhenAll`.
- Methods that almost always go async (DB queries, HTTP calls without a cache layer).
- Public APIs in shared libraries — `Task` is the conventional contract; `ValueTask` adds caller-side gotchas.

**The four `ValueTask` rules** (memorize — interviews probe this)

```
✗ 1. Never await the same ValueTask twice.
       var vt = SomeMethod();
       await vt;                    // ok
       await vt;                    // may throw or return wrong result

✗ 2. Never call .Result, .GetAwaiter().GetResult(), or .AsTask() before awaiting.
       var vt = SomeMethod();
       var result = vt.Result;      // ok if vt is completed; throws otherwise
       await vt;                    // already consumed — undefined behavior

✗ 3. Never await concurrently (Task.WhenAll, etc.) — only one consumer.
       Task.WhenAll(vt1, vt2);      // wrong — vt1 and vt2 are structs, each consumed once

✗ 4. ValueTask is not a general-purpose Task — it's an optimization tool.
       Don't return ValueTask from public APIs unless the perf case justifies the contract.
```

**Why these rules exist**: `ValueTask<T>` may wrap a pooled `IValueTaskSource<T>` (an internal interface used to avoid all allocations including the source Task). When you await it, the source may be reset and given to another caller. Awaiting twice reads from a reset/recycled source — corruption.

**Converting between Task and ValueTask**

```csharp
// Task → ValueTask: free wrap
ValueTask<int> vt = new ValueTask<int>(taskInstance);

// ValueTask → Task: pays the allocation you tried to avoid; only use when forced
Task<int> t = vt.AsTask();   // call before awaiting; consumes the ValueTask

// In ASP.NET, EF Core, channels: many APIs return ValueTask; await directly
var user = await GetUserAsync(id);     // works for both Task and ValueTask transparently
```

**`IAsyncEnumerable<T>` and `ValueTask`**

`IAsyncEnumerator<T>.MoveNextAsync()` returns `ValueTask<bool>`. This is a deliberate choice: when iterating cached data, each `MoveNext` completes synchronously, and a Task allocation per element would be catastrophic. `IAsyncEnumerable` is the canonical example of "frequently synchronous" async patterns.

### Defensive copy trap with structs

When you pass a struct **by value**, the runtime copies it. When you pass it **by reference** with `in` (or `ref readonly`), the runtime can pass a pointer — *unless* it isn't sure the struct can't mutate itself, in which case it makes a hidden defensive copy. This is the **defensive copy trap**.

**Setup**

```csharp
public struct BigPoint              // NOT readonly
{
    public double X, Y, Z, W, A, B, C, D;   // 64 bytes
    public double Magnitude() => Math.Sqrt(X*X + Y*Y + Z*Z + W*W);
}

public readonly struct BigPointRO   // readonly struct
{
    public readonly double X, Y, Z, W, A, B, C, D;
    public BigPointRO(double x, double y, /* ... */) { X = x; Y = y; /* ... */ }
    public double Magnitude() => Math.Sqrt(X*X + Y*Y + Z*Z + W*W);
}

// Caller
void Use(in BigPoint p)            // 'in' = pass by readonly reference
{
    double m = p.Magnitude();      // ← potential defensive copy here
}

void Use(in BigPointRO p)
{
    double m = p.Magnitude();      // no defensive copy — compiler proves immutability
}
```

**What happens**

When `Use(in BigPoint p)` calls `p.Magnitude()`, the compiler doesn't know whether `Magnitude()` might mutate `this`. To preserve the `in` contract ("caller's variable doesn't change"), the compiler **copies `p` to a hidden local**, then calls `Magnitude()` on the copy. For a 64-byte struct in a hot loop, this defensive copy is real cost.

For `BigPointRO`, the `readonly` keyword on the struct **promises** that `Magnitude()` cannot mutate `this` — so the compiler skips the copy.

**Detection**: the Roslyn analyzer `IDE0250` ("Make struct readonly") flags candidates. Also visible in IL: look for a `dup`/`stloc`/`ldloca` sequence right before the method call.

**Practical impact** — measured on a typical .NET 8 build:

| Method shape | Cost per call | Notes |
|---|---|---|
| `void M(in BigPoint)` calling `p.Magnitude()` | ~3–4 ns + 64 B copied | Defensive copy on each property access too |
| `void M(in BigPointRO)` calling `p.Magnitude()` | ~0.5 ns | No copy, direct read |

In a hot loop of 100M iterations, that's hundreds of MB/s of CPU bandwidth on memory copies that compiled away with one keyword.

**Properties that cause defensive copies on a non-readonly struct**:

- Calling **any non-`readonly` instance method**.
- Reading **any property** (properties are method calls).
- Passing the struct to another `in` parameter.
- Calling interface methods (even if the struct implements the interface — boxes too).

**The fixes** (in priority order):

1. **Make the struct `readonly struct`** — eliminates all defensive copies for instance method calls.
2. If full `readonly` is impossible, mark individual members `readonly`: `public readonly double Magnitude() => ...;` (C# 8+). The method promises it won't mutate `this`.
3. Use `ref readonly` returns and parameters consistently for large structs.
4. For very large structs (≥ 16 bytes typically), question whether it should be a struct at all — at some size, the copy cost exceeds the heap-allocation cost of a class.

**`readonly struct` guarantees**:

```
✓ All instance fields are readonly (compile-enforced)
✓ All instance properties are get-only or {init}
✓ No mutating methods — every instance method is implicitly readonly
✓ Compiler will not emit defensive copies for in-parameters or ref-readonly returns
✓ Safe to use as a dictionary key (hash code can't change)
```

### `ref` returns and `ref` locals

C# 7 added the ability to return and store **references** (not copies) to struct fields and array elements. The win: avoid copying large structs and avoid re-lookups in collections.

```csharp
public ref int GetSlot(int[] arr, int index)
{
    return ref arr[index];     // returns a reference to the slot, not the value
}

ref int slot = ref GetSlot(arr, 5);
slot = 42;                     // writes directly to arr[5]
slot++;                        // writes directly to arr[5] again — no re-lookup
```

**Rules**:

- The reference must not outlive the underlying storage (compiler-enforced via lifetime tracking).
- `ref` locals can only be initialized to `ref`-returned values or `ref` parameters.
- Cannot store a `ref` in a heap field; can't cross `await`.
- `ref readonly` returns prevent mutation through the reference (e.g., `MemoryMarshal.GetReference`).

**The killer feature — `CollectionsMarshal.GetValueRefOrNullRef` (.NET 6+)**:

`Dictionary<TKey, TValue>` normally requires two lookups for a "find-and-update" pattern: one `TryGetValue`, one `Add` or `dict[key] = ...`. With `GetValueRefOrNullRef`, you do **one** lookup and mutate in place:

```csharp
using System.Runtime.InteropServices;

var counts = new Dictionary<string, int>();

// Old way — two lookups
if (counts.TryGetValue(key, out var current))
    counts[key] = current + 1;
else
    counts[key] = 1;

// New way — one lookup, direct mutation
ref int count = ref CollectionsMarshal.GetValueRefOrNullRef(counts, key);
if (Unsafe.IsNullRef(ref count))
    counts[key] = 1;
else
    count++;                  // writes directly into the dictionary's bucket
```

Performance: roughly **2× faster** for the common "increment a counter" pattern; bigger wins for large `TValue` structs (no copy).

**Similar utilities**:

- `CollectionsMarshal.AsSpan(List<T>)` — get a `Span<T>` over a list's backing array. Use for tight loops over a list without indexer overhead.
- `CollectionsMarshal.SetCount(List<T>, int)` — bypass `Add` and write directly into the span.
- `MemoryMarshal.GetReference(span)` — get a `ref T` to span[0] for low-level loops.
- `Unsafe.Add(ref T, int)` — pointer arithmetic on managed references.

**When to reach for `ref`**:

- Hot loops mutating dictionary values, list elements, or array slots — `ref` saves the re-lookup.
- Passing large structs through method chains — avoid copies.
- Building span-based algorithms that need to write into the underlying memory.

For ordinary application code, `ref` returns are overkill. They earn their keep in framework code, parsers, serializers, math libraries.

### `IDisposable` and `IAsyncDisposable` — the full pattern

`IDisposable` is the .NET convention for **deterministic resource cleanup** — files, sockets, DB connections, native handles, locks. The runtime's finalizer is non-deterministic (runs whenever the GC feels like it); `IDisposable` lets callers say "I'm done with this resource right now".

**The basic case — managed resources only** (most code):

```csharp
public sealed class HttpHandler : IDisposable
{
    private readonly HttpClient _client = new();
    private bool _disposed;

    public void Dispose()
    {
        if (_disposed) return;
        _client.Dispose();
        _disposed = true;
    }
}
```

No finalizer. The class owns only managed resources (other `IDisposable` instances). If the caller forgets `Dispose`, the GC eventually collects everything; the finalizer in `HttpClient` (etc.) handles the cleanup. Adding a finalizer here would be wrong — it adds GC overhead and never runs in normal flow.

**The full pattern — managed + unmanaged resources**:

When your class directly owns an **unmanaged** resource (raw `IntPtr` to a native handle, `Marshal.AllocHGlobal` memory, a `SafeHandle`-less interop pointer), you need the full Dispose pattern with a finalizer as the safety net.

```csharp
public class NativeResourceHolder : IDisposable
{
    private IntPtr _handle;            // unmanaged
    private FileStream? _stream;       // managed
    private bool _disposed;

    public NativeResourceHolder() { _handle = NativeMethods.Open(); _stream = File.OpenRead("..."); }

    public void Dispose()
    {
        Dispose(disposing: true);
        GC.SuppressFinalize(this);     // tell GC: no finalizer needed
    }

    protected virtual void Dispose(bool disposing)
    {
        if (_disposed) return;

        if (disposing)
        {
            // Called from Dispose() — safe to access managed resources
            _stream?.Dispose();
        }

        // Always release unmanaged — whether Dispose() or finalizer path
        if (_handle != IntPtr.Zero)
        {
            NativeMethods.Close(_handle);
            _handle = IntPtr.Zero;
        }

        _disposed = true;
    }

    // Finalizer — runs if caller forgot Dispose(); LAST resort
    ~NativeResourceHolder() => Dispose(disposing: false);
}
```

**Why the `disposing` flag**:

- `Dispose()` → calls `Dispose(true)` → can touch other managed objects (they're guaranteed alive because the caller has a reference to `this`).
- Finalizer → calls `Dispose(false)` → **must not touch managed objects**, because they may have already been finalized (finalizer order is undefined). Only release unmanaged.

**`GC.SuppressFinalize(this)`**: marks the object as finalization-complete so the GC skips the finalizer queue when reclaiming. Without it, the object survives one extra GC cycle (sits in the f-reachable queue), wasting performance.

**Modern alternative — `SafeHandle`**: the BCL's `SafeHandle` (and its subclasses) **wraps unmanaged handles with a built-in finalizer**. You hold a `SafeHandle` field instead of `IntPtr`, and you don't need your own finalizer:

```csharp
public sealed class BetterNativeHolder : IDisposable
{
    private readonly MySafeHandle _handle = NativeMethods.OpenSafe();

    public void Dispose() => _handle.Dispose();   // SafeHandle handles the rest
    // No finalizer needed
}
```

In 2026 code, **prefer `SafeHandle`** over `IntPtr` + custom finalizer. The full Dispose pattern with finalizer is now rarely needed in application code.

**When you can skip the finalizer entirely**:

- Class owns only managed `IDisposable` resources (no raw unmanaged handles).
- Class owns a `SafeHandle` (which has its own finalizer).
- Class is `sealed` and the unmanaged resource lifecycle is otherwise guaranteed.

Adding a finalizer "just in case" is a measurable perf cost — every instance enters the finalization queue, survives an extra GC, and serializes finalizer execution on the single finalizer thread. **Don't add finalizers without a unique unmanaged resource to release.**

**`IAsyncDisposable` and `await using` (C# 8+)**:

Some resources need **asynchronous** cleanup — flushing a network buffer, closing a SQL connection cleanly, draining a channel. Sync `Dispose()` would block the thread.

```csharp
public sealed class AsyncResource : IAsyncDisposable
{
    private readonly Stream _stream;

    public async ValueTask DisposeAsync()
    {
        await _stream.FlushAsync();
        await _stream.DisposeAsync();
    }
}

// Caller:
await using var r = new AsyncResource();   // calls DisposeAsync at end of scope
```

**When `IAsyncDisposable` over `IDisposable`**:

- The cleanup itself does I/O (flush, drain, network close) — sync Dispose would block.
- The class is async-first (streams, DB connections, hosted services).
- The caller is already in an async context — `await using` is natural.

**Implement both** when you can: `IDisposable` for sync callers, `IAsyncDisposable` for async callers. The BCL convention: `DisposeAsync()` does the real work; `Dispose()` calls `DisposeAsync().AsTask().GetAwaiter().GetResult()` or duplicates the logic synchronously.

```csharp
public sealed class DualResource : IDisposable, IAsyncDisposable
{
    public void Dispose() => DisposeCore(async: false).GetAwaiter().GetResult();
    public ValueTask DisposeAsync() => DisposeCore(async: true);

    private async ValueTask DisposeCore(bool async)
    {
        if (async) await _stream.DisposeAsync();
        else _stream.Dispose();
    }
}
```

ASP.NET Core, EF Core, and `HttpClient` all follow this dual pattern.

### Allocation-free string building

Strings are immutable; every operation that "modifies" a string actually allocates a new one. On hot paths (logging, formatting, CSV/JSON building), string allocations dominate. The BCL has five tools, in increasing sophistication.

**The hierarchy — `string.Concat` vs `StringBuilder` vs `string.Create` vs interpolation handler vs UTF-8 literal**

| Tool | Allocations | When it wins | Notes |
|---|---|---|---|
| `a + b + c` operator | N intermediates + result | Few parts (≤ 3), all known | Compiler folds to `string.Concat` for ≤ 4 args |
| `string.Concat(a, b, c)` | 1 (just the result) | Known small list of strings | Internal pre-counts total length, single alloc |
| `StringBuilder` | Internal char[] growth + final ToString | Many parts (≥ 4), variable count, conditional | Some intermediate `char[]` grows but each only once |
| `string.Create(len, state, span => ...)` | **1** (the result, length known) | You can compute total length ahead | Writes into the string's final char buffer |
| `$"..."` interpolation (C# 10+) | 0 if logger filtered, else 1 | Templated logging via `ILogger` | `DefaultInterpolatedStringHandler` uses pooled buffers |
| `"text"u8` UTF-8 literal | 0 | Byte sequences known at compile time | Bytes baked into assembly metadata |

**The trap: `+` in a hot loop**

```csharp
// ❌ O(n²) allocations
string result = "";
for (int i = 0; i < items.Length; i++)
    result += items[i] + ",";        // each += allocates result.Length + items[i].Length + 1

// For 10,000 items each ~20 chars: ~10,000 allocations totaling ~1 GB allocated.
```

The reason: each `result += x` allocates a new string equal to *total accumulated length*. After N iterations, total bytes allocated is ~N²/2 × avgItemLength. For 10K items at 20 chars each, that's ~1 GB allocated to produce a 200 KB string. Gen 2 GC starts thrashing.

**Fix #1: `StringBuilder`**

```csharp
// ✓ O(n) allocations — internal char[] grows by doubling
var sb = new StringBuilder(capacity: items.Length * 22);   // pre-size if known
for (int i = 0; i < items.Length; i++)
{
    sb.Append(items[i]);
    sb.Append(',');
}
string result = sb.ToString();
```

Pre-sizing the capacity (`new StringBuilder(estimatedSize)`) avoids the doubling churn entirely. Critical for known-size builds.

**Fix #2: `string.Create` when length is known**

```csharp
// ✓ Single allocation — the final string, written directly
int totalLen = items.Sum(s => s.Length + 1);
string result = string.Create(totalLen, items, (span, items) =>
{
    int pos = 0;
    foreach (var s in items)
    {
        s.AsSpan().CopyTo(span.Slice(pos));
        pos += s.Length;
        span[pos++] = ',';
    }
});
```

`string.Create` gives you a `Span<char>` over the new string's internal buffer **before** the string is frozen as immutable. You write into it, then return. **One allocation total**. Beats `StringBuilder` when you can compute the length ahead of time.

**Fix #3: `Span<char>` + `stackalloc` for tiny strings**

```csharp
// Build a 16-char string with zero heap allocation until ToString()
Span<char> buffer = stackalloc char[16];
"prefix-".AsSpan().CopyTo(buffer);
buffer[7] = (char)('0' + n);
string result = new string(buffer[..8]);   // allocates only the final string
```

**Fix #4: UTF-8 literals (C# 11+)**

When you're writing to a stream/socket that takes bytes, skip the UTF-16-to-UTF-8 conversion entirely:

```csharp
ReadOnlySpan<byte> contentType = "application/json"u8;     // baked at compile time
ReadOnlySpan<byte> crlf = "\r\n"u8;

// Writing HTTP response headers
await stream.WriteAsync(contentType);
await stream.WriteAsync(crlf);
// Zero allocations, zero encoding work
```

**`DefaultInterpolatedStringHandler` (C# 10):**

The compiler converts `$"x = {n}"` to a sequence of `AppendLiteral` / `AppendFormatted` calls into a stack-allocated handler. For small interpolated strings, this avoids intermediate allocations entirely.

```csharp
int n = 42;
string s = $"n = {n}";
// Equivalent to (simplified):
// var handler = new DefaultInterpolatedStringHandler(literalLength: 4, formattedCount: 1);
// handler.AppendLiteral("n = ");
// handler.AppendFormatted(n);
// string s = handler.ToStringAndClear();
```

The killer use case is `ILogger`: `_logger.LogInformation($"Request {id} took {ms}ms")`. The custom handler is told the log level filter before formatting; if `Information` is filtered out, **zero work happens** — no formatting, no allocation. Pre-C# 10, the `$"..."` always allocated and the logger then discarded the string.

Custom interpolated string handlers (`[InterpolatedStringHandler]`) let libraries hook this — `LoggerMessage`, `ZString`, `SqlInterpolatedStringHandler`, etc.

**`StringBuilder` — still relevant** for many sequential appends with unknown length. Allocates fewer intermediate strings than `+`. Modern code prefers `string.Create` when length is known, falling back to `StringBuilder` for variable-length building.

### Boxing checklist — when value types secretly allocate

**Boxing** is the runtime wrapping a value type in a heap object so it can be referenced through `object` or an interface. Each box is a heap allocation (typically 24–40 bytes for a small struct) plus a copy of the struct's contents. In hot paths, boxing is one of the top three allocation sources after string operations and closures.

**The complete list of when boxing happens**:

```
✓ Assigning a value type to a variable of type 'object'.
       int i = 5; object o = i;                 ← boxes (1 allocation)

✓ Assigning a value type to a variable of an interface type.
       int i = 5; IComparable c = i;            ← boxes

✓ Passing a value type as a parameter typed 'object' or interface.
       void Log(object o); Log(42);             ← boxes

✓ Returning a value type from a method that returns 'object' or interface.

✓ Calling a virtual method inherited from object that the struct didn't override.
       struct S { } new S().ToString();         ← boxes (uses object.ToString)
       struct S { override string ToString() => "S"; } new S().ToString();  ← NO box

✓ Calling an interface method on a struct through the interface type.
       IComparable c = new MyStruct(); c.CompareTo(...);   ← boxes
       new MyStruct().CompareTo(...);                       ← direct call, no box

✓ Using a value type as a generic argument WITHOUT a matching constraint.
       void M<T>(T x) { object o = x; }   ← boxes inside M (no constraint)
       void M<T>(T x) where T : IComparable<T> { x.CompareTo(...); }   ← no box
       (JIT specializes per concrete T; calls the struct's method directly)

✓ Putting a value type in a non-generic collection (ArrayList, Hashtable).
       ArrayList list = new(); list.Add(42);     ← boxes

✓ Concatenating a value type into a string via '+' (pre-C# 6).
       "x = " + 42                              ← used to box; modern compiler uses interpolation
```

**How to detect boxing in your code**:

1. **Roslyn analyzer `HAA0601`** (Heap Allocation Analyzer / ClrHeapAllocationAnalyzer) — flags suspected boxing at compile time. The package isn't on by default — install `ClrHeapAllocationAnalyzer` or `Microsoft.CodeAnalysis.BannedApiAnalyzers`.

2. **IL inspection** — boxing appears as the `box` IL opcode. Use ILSpy or `dotnet-ildasm` and search for `box`:
    ```
    IL_0001: ldloc.0
    IL_0002: box        [System.Runtime]System.Int32   ← here
    IL_0007: callvirt   instance string object::ToString()
    ```

3. **BenchmarkDotNet `[MemoryDiagnoser]`** — measures bytes allocated per call. If a method that takes a struct allocates more than expected (e.g., 24 B for what should be 0), there's a hidden box.

4. **PerfView / dotMemory allocation traces** — show `System.Int32` (or whatever struct) in the allocation report. Value types in an allocation profile = boxing.

**The fixes**:

| Symptom | Fix |
|---|---|
| `IComparable c = myStruct` | Use generic constraint: `void M<T>(T x) where T : IComparable<T>` |
| `object Log(object x)` taking structs | Use generic method `Log<T>(T x)` and call `x.ToString()` via constrained or direct call |
| `ArrayList` / `Hashtable` | Use `List<T>` / `Dictionary<TK,TV>` |
| Struct calling `ToString()` from `object` | Override `ToString()` on the struct |
| Struct calling interface method via interface | Call directly on the struct, or use generic constraint |
| Enum boxing in `switch`/format | Use `enum.ToString()` directly (modern .NET avoids the box) |

**The subtle one — generic methods**

```csharp
void M1<T>(T x)
{
    object o = x;          // ← boxes if T is a value type, no constraint
}

void M2<T>(T x) where T : IFoo
{
    x.DoFoo();             // ← no box; JIT specializes per struct T
    object o = x;          // ← still boxes (object is base of T)
}

void M3<T>(T x) where T : class
{
    object o = x;          // ← no box; T is constrained to ref type, already an object
}
```

The constraint **`where T : IFoo`** doesn't prevent boxing to `object` — it only prevents boxing when calling `x.DoFoo()`. The JIT specializes the method per concrete value-type `T`, so the constrained call site emits a direct method call instead of a virtual interface call.

### `unsafe` and pointers

`unsafe` blocks let you use C-style pointers (`int*`, `byte*`), pin GC objects (`fixed`), and do pointer arithmetic. With `Span<T>` covering 95% of allocation-free patterns, `unsafe` is rarely the right tool anymore — but knowing it exists matters for interop and BCL reading.

```csharp
unsafe
{
    int x = 5;
    int* p = &x;
    *p = 10;
    Console.WriteLine(x);   // 10

    byte[] arr = new byte[10];
    fixed (byte* pArr = arr)   // pin while in scope; tells GC don't move
    {
        // *pArr operations
    }
}
```

Requires `<AllowUnsafeBlocks>true</AllowUnsafeBlocks>` in the `.csproj`.

**When `unsafe` is genuinely needed:**
- Native interop (P/Invoke) where the API requires pointers.
- Bit-twiddling that `MemoryMarshal` doesn't cover.
- Performance-critical code beating `Span<T>` (very rare; usually only relevant for SIMD via `Vector<T>` or low-level math kernels).

For most code: prefer `Span<T>` + `MemoryMarshal` (which exposes safe equivalents to many pointer operations, e.g., `MemoryMarshal.AsBytes(span)`).

### Sizing decisions: when each tool wins

| Scenario | First reach for | Then |
|---|---|---|
| Parsing a fixed-size header | `stackalloc Span<byte>` | — |
| Streaming bytes from a network | `ArrayPool<byte>` + `Memory<byte>` | `Span<byte>` for sync work |
| Building a string from many parts | `string.Create` if you know the length, else `StringBuilder` | — |
| Slicing a string for parsing | `s.AsSpan()` + `ReadOnlySpan<char>` | — |
| JSON serialization | `JsonSerializerContext` (source-gen) | — |
| Logging | source-generated `[LoggerMessage]` | — |
| Regex compilation | `[GeneratedRegex]` (C# 11+) | `Regex` with `Compiled` flag |
| Native interop | `unsafe` + `fixed` (or `Marshal`) | — |
| Cross-`await` buffer | `Memory<T>` | sync `Span<T>` between awaits |
| Generic value-type math | `where T : INumber<T>` | — |
| Hot-loop without GC | `record struct` / `readonly struct` | `Span<T>` if applicable |

### Measurement: BenchmarkDotNet

All allocation talk is theoretical until measured. **BenchmarkDotNet** (NuGet: `BenchmarkDotNet`) is the canonical micro-benchmarking tool. It builds a Release-mode assembly, warms it up, then measures with statistical rigor (mean + median + standard deviation + outlier detection).

**The core attributes**:

```csharp
using BenchmarkDotNet.Attributes;
using BenchmarkDotNet.Running;

[MemoryDiagnoser]                                      // track allocations
[SimpleJob(RuntimeMoniker.Net90)]                      // .NET version
[HideColumns("Job", "Error", "StdDev")]                // declutter output
public class StringConcatBenchmark
{
    [Params(10, 100, 1000)]                            // run benchmark for each size
    public int N { get; set; }

    private string[] _items = null!;

    [GlobalSetup]                                      // runs once before all benchmarks
    public void Setup() => _items = Enumerable.Range(0, N).Select(i => i.ToString()).ToArray();

    [Benchmark(Baseline = true)]
    public string PlusOperator()
    {
        string r = "";
        for (int i = 0; i < N; i++) r += _items[i];
        return r;
    }

    [Benchmark]
    public string StringBuilder()
    {
        var sb = new StringBuilder();
        for (int i = 0; i < N; i++) sb.Append(_items[i]);
        return sb.ToString();
    }

    [Benchmark]
    public string StringCreate()
    {
        int len = _items.Sum(s => s.Length);
        return string.Create(len, _items, (span, items) =>
        {
            int pos = 0;
            foreach (var s in items) { s.AsSpan().CopyTo(span.Slice(pos)); pos += s.Length; }
        });
    }
}

// Run with: BenchmarkRunner.Run<StringConcatBenchmark>();
```

**Reading the output**:

```
| Method        | N    | Mean      | Allocated | Ratio |
|---------------|------|-----------|-----------|-------|
| PlusOperator  | 100  | 14.8 us   | 50.4 KB   | 1.00  |
| StringBuilder | 100  | 2.1 us    | 1.9 KB    | 0.14  |
| StringCreate  | 100  | 0.6 us    | 0.4 KB    | 0.04  |
```

- **Mean** — average time per call.
- **Allocated** — bytes allocated **per call** (the headline number `[MemoryDiagnoser]` adds).
- **Ratio** — relative to the baseline (`Baseline = true`).
- **Gen 0/1/2** — collections per 1000 ops (also added by `[MemoryDiagnoser]`).

**Common attributes — the full toolkit**:

| Attribute | Purpose |
|---|---|
| `[Benchmark]` | Method is a benchmark candidate |
| `[Benchmark(Baseline = true)]` | Reference for `Ratio` column |
| `[Params(1, 10, 100)]` | Parameterize by value — one row per combination |
| `[ParamsSource(nameof(M))]` | Parameterize from a property/method |
| `[MemoryDiagnoser]` | Track allocations and GC counts |
| `[ThreadingDiagnoser]` (.NET 5+) | Track thread contention, completed-work-items |
| `[GlobalSetup]` / `[GlobalCleanup]` | Run once before / after all iterations |
| `[IterationSetup]` / `[IterationCleanup]` | Run before / after each iteration (use sparingly) |
| `[SimpleJob(RuntimeMoniker.Net90)]` | Target a specific runtime |
| `[DisassemblyDiagnoser]` | Print JIT'd assembly for the benchmark |
| `[EtwProfiler]` / `[PerfCollectProfiler]` | Capture ETW traces during the run |

**Warmup vs measurement**

BenchmarkDotNet runs three phases automatically:

1. **Pilot** — figures out how many invocations make a measurable batch (e.g., 1000 calls = 1 ms).
2. **Warmup** — typically 15 iterations to let the JIT compile, tier-1, tier-2, and PGO stabilize. Discarded.
3. **Workload** — typically 15 iterations of actual measurement.

If your benchmark is dominated by **first-call JIT cost**, you'd get inflated numbers without warmup. BDN handles this by default, but you can tune via `[SimpleJob(warmupCount: 5, iterationCount: 20)]`.

**Common pitfalls**

1. **Constant folding / dead-code elimination** — the JIT optimizes away code with no observable effect. A benchmark that returns void and has no side effects measures nothing.
    ```csharp
    [Benchmark]
    public void Bad() { var x = 1 + 2; }       // JIT eliminates entirely — measures 0
    
    [Benchmark]
    public int Good() => 1 + 2;                 // return value forces evaluation
    ```
    Rule: **always return the computed value** from a benchmark. BDN consumes the return value to prevent elimination.

2. **Inlining gives unrealistic results** — if your benchmark method body is trivial, the JIT may inline it into the harness, eliminating call overhead. Mark with `[MethodImpl(MethodImplOptions.NoInlining)]` if you're specifically measuring call cost.

3. **Running in Debug mode** — BDN refuses to run on Debug builds by default (would give meaningless numbers). Always use Release config.

4. **Running under a debugger attached** — disables tier-2 JIT optimizations. BDN warns if `Debugger.IsAttached`.

5. **Benchmarks affecting each other via static state** — if benchmark A leaves the heap in a different shape than benchmark B, you'll see noise. Use `[IterationSetup]` to reset state.

6. **Async benchmarks need `[Benchmark]` to return `Task` / `ValueTask`** — BDN awaits it correctly. Don't `.Wait()` inside the benchmark.

7. **Allocations from the benchmark harness itself** — BDN reports only allocations attributable to the benchmark method body, but closures or lambdas inside can sneak in. Profile-check by setting up `private static readonly` cache fields outside the benchmark.

8. **Cold cache vs warm cache** — micro-benchmarks measure warm-cache performance. Real workloads have cold caches. BDN can simulate cold caches via `[ColdStart]` but most production perf differences come from cold caches and aren't captured.

9. **Tiny differences aren't real** — if mean times overlap within 5%, your benchmark is in the noise floor. Optimize when you see ≥ 30% delta with non-overlapping confidence intervals.

10. **Synthetic benchmarks ≠ production wins** — a 10× faster micro-benchmark for a function that's 0.1% of request time saves you nothing. Profile real workloads (`dotnet-trace`, `PerfView`) before optimizing.

**Beyond micro-benchmarks**:

- **`dotnet-counters monitor System.Runtime`** — live GC stats on a running process.
- **`dotnet-trace collect`** — full ETW-style trace; view in PerfView or Speedscope.
- **`dotnet-dump analyze`** — post-mortem heap analysis with SOS commands.
- **JetBrains dotMemory / dotTrace** — UI-based memory + CPU profiling.
- **PerfView** (Vance Morrison) — the gold standard for low-level CLR perf investigation.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

```
┌──────────────────────────────────────────────────────────────┐
│   Allocation tools by use case                                │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│   Small fixed buffer (≤1 KB)                                  │
│   ──────────────────────────                                  │
│   stackalloc int[256] ─→ Span<int>     (zero alloc)           │
│                                                               │
│   Variable / large buffer                                     │
│   ───────────────────────                                     │
│   ArrayPool<byte>.Shared.Rent(n) ─→ byte[]/Span (pooled)      │
│   MemoryPool<byte>.Shared.Rent(n) ─→ IMemoryOwner             │
│                                                               │
│   Async transit                                               │
│   ─────────────                                               │
│   Memory<T>  ─→ inside method, .Span for sync work            │
│                                                               │
│   String building                                             │
│   ────────────                                                │
│   string.Create(len, state, callback)  (1 alloc — the result) │
│   $"..."                          (DefaultInterpolatedString) │
│   "..."u8                       (UTF-8, baked into metadata)  │
│   StringBuilder              (multi-step, intermediate-free)  │
└──────────────────────────────────────────────────────────────┘
```

**`Span<T>` lifecycle:**

```
   Heap array        Stack frame
   ──────────        ───────────
   [a][b][c][d]     [span: ptr=0xABCD, len=4]
                          │
                          │ wraps the heap array's memory
                          ▼
                    ─→  reads and writes go directly to [a][b][c][d]
                        no copy, no allocation
                        slicing creates a new span (different ptr/len), still no alloc
```

**Pooled buffer round-trip:**

```
1. Rent(1024)  → ArrayPool gives you a byte[] ≥ 1024 (might be 2048)
2. Use it      → Span<byte> over slice [0..read]
3. Return      → ArrayPool reclaims; another caller can rent it next
4. Don't touch → after Return, treat the array as gone
```

</details>
## Common pitfalls

1. **`stackalloc` in a loop.** Each iteration allocates more stack — eventually overflows. Move outside the loop.
2. **Forgetting to `Return` an `ArrayPool` rental.** Causes pool exhaustion and silent fallback to `new` allocations. Always pair `Rent` with `Return` in `try/finally`, or use `IMemoryOwner` with `using`.
3. **Holding a `Span<T>` past its memory's lifetime.** Compiler usually catches this (ref struct rules), but `MemoryMarshal.CreateSpan` can defeat the check — be careful.
4. **`Span<T>` in async methods.** Compile error — can't cross `await`. Use `Memory<T>` for the field/parameter, `Span<T>` only inside synchronous segments.
5. **Slicing in a loop allocates the slice's underlying array.** `arr.Skip(10).Take(20)` is LINQ — allocates. `arr.AsSpan(10, 20)` is a span — free. For arrays, prefer span slicing.
6. **`stackalloc` returning to caller.** You can't — the stack frame is gone. Use `Span<T>` only inside the allocating method.
7. **Pinning a large object with `fixed` for too long.** Pinned objects can't be moved by the GC, fragmenting the heap. Pin briefly.
8. **Treating `string.Create` as always faster.** It's a one-allocation path *if* you know the final length. For unknown sizes, `StringBuilder` is often clearer and similar in speed.
9. **Profiling synthetic benchmarks but not real code.** A micro-benchmark showing `Span<T>` is 5x faster doesn't mean your endpoint is 5x faster — the work the span replaces is rarely the bottleneck. Profile in production-shape workloads.
10. **Reaching for `unsafe` before `Span<T>` + `MemoryMarshal`.** 95% of "I need pointers" cases are now solved by safe primitives. `MemoryMarshal.Cast`, `MemoryMarshal.AsBytes`, `MemoryMarshal.GetReference` cover most of the gap.

## Interview-ready summary

- **The allocation taxonomy**: object new, boxing, strings, arrays, closures. Profile first, then attack the dominant source.
- **`Span<T>`** = `ref struct` view over contiguous memory (heap array, stack, native). Zero alloc, near-pointer speed. Restricted: no async crossings, no class fields, no boxing. Slicing is free.
- **`ReadOnlySpan<T>`** = immutable view. `string.AsSpan()` is the canonical entry point.
- **`Memory<T>`** = heap-allocatable cousin. Use for async transit; convert to `Span<T>` for actual work.
- **`stackalloc`** allocates on the stack. Combined with `Span<T>`, gives small fixed buffers with zero GC. Keep ≤ ~1 KB; never in a loop.
- **`ArrayPool<T>.Shared`** for variable / large buffers. `Rent` + `Return` (or `IMemoryOwner` + `using`).
- **`string.Create`**, **`DefaultInterpolatedStringHandler`**, **UTF-8 literals (`"abc"u8`)**, source-gen logging — the four major allocation-free string idioms.
- **`unsafe`** rarely the right tool now. `Span<T>` + `MemoryMarshal` cover most cases. Reserve `unsafe` for native interop or sub-`Span` performance.
- **`BenchmarkDotNet`** + `[MemoryDiagnoser]` — measure allocations, don't guess. Real workload profiling beats micro-benchmarks for end-user impact.
- **`record struct`**, **`readonly struct`**, **`ref struct`** — the type-system primitives that make the rest of these tools safe and ergonomic.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.
### Drill 1 — Gen 0 vs Gen 2

> **Q**: What's the difference between a Gen 0 and a Gen 2 collection, and which one hurts p99 latency?
>
> **A**: Gen 0 collects newly-allocated objects; runs frequently (every few MB), pauses are sub-millisecond, only scans the small Gen 0 region. Gen 2 collects long-lived survivors plus the LOH; runs rarely (seconds to minutes), pauses can be tens to hundreds of ms, scans the entire managed heap. **Gen 2 pauses are what spike p99 latency** under load.
>
> **Cross-Q**: If most allocations die young, why isn't my web service Gen 2-free?
>
> **A**: Three sources push objects to Gen 2: (1) **LOH allocations** — any allocation ≥ 85,000 bytes goes straight to LOH which is collected as part of Gen 2; (2) **closures and async state machines** that capture long-lived state survive Gen 0/1 and promote; (3) **caches** (`IMemoryCache`, static dictionaries) by design hold references to objects that survive multiple collections. Profile with `dotnet-counters monitor System.Runtime --counters gen-2-gc-count` to find the rate; allocation trace with `dotnet-trace` to find the source.
>
> **Cross-Q²**: Why doesn't .NET just have one generation and skip the complexity?
>
> **A**: The **generational hypothesis** — empirically, ~95% of objects die in their first GC cycle. A single-generation collector would scan the entire heap on every collection, paying for objects that are obviously alive (the long-lived ones — caches, configuration, the DI container). Generational lets the GC scan only the small "young" region most of the time, and only pay for the full heap rarely. The trade-off is the bookkeeping of remembered sets (cross-generational references), which Microsoft accepted because the steady-state CPU savings is ~10×.

### Drill 2 — LOH threshold

> **Q**: Why does the LOH have an 85,000-byte threshold? Why that specific number?
>
> **A**: Above ~85 KB, the cost of **copying the object during compaction** exceeds the cost of leaving a hole in the heap. The CLR's Gen 0/1/2 are compacting collectors — they slide surviving objects together to eliminate fragmentation. Past some size, moving the object is more expensive than tolerating fragmentation, so LOH is **non-compacting**. Microsoft picked 85,000 empirically based on x86 page sizes; the threshold isn't tunable.
>
> **Cross-Q**: What's the consequence of LOH being non-compacting?
>
> **A**: **Fragmentation**. Repeatedly allocating and freeing differently-sized large objects leaves holes the GC can't combine. After a while, the LOH may have 200 MB of "free" space scattered across 1000 holes, but a new 5 MB allocation can't fit because no single hole is that big. You'll see `OutOfMemoryException` on a process that the OS thinks has plenty of RAM. You can manually trigger an LOH compaction once with `GCSettings.LargeObjectHeapCompactionMode = GCLargeObjectHeapCompactionMode.CompactOnce` followed by `GC.Collect()`, but it's expensive (full Gen 2 + move every LOH object) — only do it after a known bulk-allocation phase.
>
> **Cross-Q²**: I have a JSON serializer producing 100 KB documents at 1000 req/s. What do I do?
>
> **A**: Three layers. (1) **Stream to the output** — don't materialize the document; use `Utf8JsonWriter` writing directly to the response `Stream`. The serializer's internal buffer is pooled (`ArrayPool<byte>`) and stays below the LOH threshold. (2) **If you must buffer** (e.g., to compute Content-Length), rent from `ArrayPool<byte>.Shared.Rent(102400)` — pool buffers are reused, no LOH churn. (3) **Monitor** with `dotnet-counters` to confirm `loh-size` is flat over time. If you're already using `System.Text.Json` correctly, all this is done for you — most LOH pressure in modern services comes from logging or custom CSV/XML generators.

### Drill 3 — Pinned Object Heap

> **Q**: When would you allocate into the Pinned Object Heap, and why does it exist?
>
> **A**: POH (Pinned Object Heap, .NET 5+) is for **long-lived buffers that must remain at a fixed memory address** — typically passed to native code via P/Invoke or used by zero-copy I/O (Kestrel sockets, gRPC). Before POH, the only way to pin was `fixed` blocks or `GCHandle.Alloc(Pinned)`, which kept the object in Gen 0 but un-moveable — causing fragmentation around it. POH allocates these objects in a dedicated region the GC never tries to compact.
>
> **Cross-Q**: Show me the API.
>
> **A**:
> ```csharp
> // .NET 5+ — allocates directly into POH
> byte[] buffer = GC.AllocateArray<byte>(length: 4096, pinned: true);
> // 'pinned: true' is the POH switch; default false uses regular heap.
> 
> // Faster variant — skip zero-init for unmanaged element types
> byte[] fast = GC.AllocateUninitializedArray<byte>(length: 4096, pinned: true);
> ```
> The returned array can be passed to native code; its address won't change for the lifetime of the array. No `fixed` block needed.
>
> **Cross-Q²**: When is POH the wrong choice?
>
> **A**: Three cases. (1) **Short-lived buffers** — POH objects survive Gen 2 collections (treated like Gen 2 by default), so a short-lived POH allocation pays Gen 2 cost forever. Use `ArrayPool<T>` with `clearArray: true` instead. (2) **Buffers that won't be passed to native code** — pinning has no benefit; you're just paying for a separate heap region. (3) **Hot allocation patterns** — POH allocation is the same cost as any heap allocation; pooling beats it. Rule: POH for **long-lived interop buffers**; pool for everything else.

### Drill 4 — `stackalloc` safety

> **Q**: `Span<byte> buf = stackalloc byte[size];` where `size` comes from a request parameter. Critique.
>
> **A**: Stack overflow waiting to happen. The CLR doesn't bounds-check `stackalloc` against the remaining thread stack; a malicious or buggy `size` of 10 MB **immediately terminates the process** — no catchable exception. Default thread stack is 1 MB on Windows, and ASP.NET Core middleware already consumes hundreds of KB. The remaining headroom is small.
>
> **Cross-Q**: Show me the safe pattern.
>
> **A**: Clamp to a known-safe constant, fall back to `ArrayPool<T>`:
> ```csharp
> const int Threshold = 256;
> byte[]? rented = null;
> Span<byte> buffer = size <= Threshold
>     ? stackalloc byte[Threshold]
>     : (rented = ArrayPool<byte>.Shared.Rent(size));
> try {
>     var slice = buffer.Slice(0, size);
>     // use slice
> }
> finally {
>     if (rented is not null) ArrayPool<byte>.Shared.Return(rented);
> }
> ```
> This is the canonical .NET BCL idiom — `Utf8JsonReader`, `Path`, `Regex` all use variants.
>
> **Cross-Q²**: Why is `stackalloc` in a `for` loop dangerous even with bounded size?
>
> **A**: The C# spec says the lifetime of `stackalloc` is the **enclosing method**, not the loop iteration. Each iteration's `stackalloc` adds to the stack frame and *doesn't reclaim until the method returns*. A loop allocating 256 bytes for 10,000 iterations consumes 2.5 MB of stack — far exceeding the 1 MB default. The fix: move the `stackalloc` outside the loop and reuse the buffer; or use `ArrayPool` if the size varies. Roslyn warns on this (`CS9081`) only in some cases — the safest rule is "no `stackalloc` inside loop bodies, ever".

### Drill 5 — `Span<T>` vs `byte[]`

> **Q**: What does `Span<T>` buy you over `byte[]`?
>
> **A**: Three things: (1) **Zero-allocation slicing** — `arr.AsSpan(10, 50)` creates a span pointing into `arr` without allocating; `arr.Skip(10).Take(50).ToArray()` allocates a new array. (2) **Unified API over heap, stack, and native memory** — the same `Span<byte>` works whether the bytes came from `new byte[N]`, `stackalloc`, or `Marshal.AllocHGlobal`. (3) **Compile-time lifetime safety** — the compiler refuses to let a span escape its data's lifetime, preventing use-after-free at the managed level.
>
> **Cross-Q**: Can I store a `Span<T>` in a class field?
>
> **A**: No — compile error. `Span<T>` is a `ref struct`, which the runtime treats as **stack-only**. The reason: a `Span<T>` may point to stack memory (`stackalloc`); allowing it as a class field could let the span survive past its stack frame, causing memory corruption. For storage, use `Memory<T>` (regular struct, heap-storable), then convert via `.Span` for synchronous work.
>
> **Cross-Q²**: Why can't a `Span<T>` cross an `await`?
>
> **A**: Async methods are lowered by the compiler into a **state machine** — a class that captures all locals as fields, so the method can be paused and resumed. If a `Span<T>` local were captured in that state machine, it would become a field of a class, which the `ref struct` rules forbid. The compile error is `CS4012: Parameters or locals of type 'Span<T>' cannot be declared in async methods or async lambdas`. Workaround: store `Memory<T>` across the await, convert to `Span<T>` only within synchronous segments between awaits.

### Drill 6 — ArrayPool cost/benefit

> **Q**: When does `ArrayPool<T>.Rent` actually beat `new`?
>
> **A**: When the buffer size is **large enough that allocation cost matters** (≥ ~4 KB) and **the allocation happens frequently enough that pooling amortizes** (≥ ~10K times per second on the same path). Below those, `new` is competitive and simpler. Above, pooling saves both the allocation cost (~30–50 ns per `new byte[4096]`) and the Gen 0 GC pressure (~4 KB allocated per call → 40 MB/s at 10K/s).
>
> **Cross-Q**: What's the failure mode I need to test for?
>
> **A**: **Forgotten Return**. The pool falls back silently to `new` allocations when starved — no error, no log. The symptom is allocations gradually creeping up under load; the root cause is a code path that rents but doesn't return on the exception path. Detection: profile with `dotMemory` or `dotnet-trace` — look for `byte[]` allocations climbing without the matching pool population. Prevention: always wrap `Rent` in `try/finally` with `Return`, or use `MemoryPool<T>.Shared.Rent()` which gives you `IMemoryOwner<T> : IDisposable`.
>
> **Cross-Q²**: I `Return` a buffer that held a JWT. Two requests later, the next caller gets the same array. What do they see?
>
> **A**: They see **your JWT, in the unused portion**. `Return(arr, clearArray: false)` (the default) doesn't zero the buffer. If you stored sensitive data, you must call `Return(arr, clearArray: true)` or wipe manually with `arr.AsSpan(0, length).Clear()` before returning. Reference-type arrays (`ArrayPool<object>`) are always cleared on return regardless of the flag — the runtime forces it to prevent keeping objects alive in the pool. This is a security-review red flag: any pool usage in a security-sensitive code path needs explicit `clearArray: true` plus a code comment justifying the decision.

### Drill 7 — `ValueTask` vs `Task`

> **Q**: When would you switch from `Task<T>` to `ValueTask<T>`, and what breaks?
>
> **A**: Switch when the method **frequently completes synchronously** (cached result, fast-path check) on a **hot path** (millions of calls). `ValueTask<T>` is a struct — synchronous completion needs no Task allocation, saving ~50 ns and ~80 bytes per call. What breaks: callers can no longer **await the same value twice**, call **`.Result`** before awaiting, or pass it to **`Task.WhenAll`** — the struct may wrap a pooled, single-use source.
>
> **Cross-Q**: Should I always return `ValueTask` from my async methods then?
>
> **A**: No. **`ValueTask` is an optimization tool, not a default.** Reasons to stick with `Task`: (1) **Caller ergonomics** — `Task` is the universal contract; `ValueTask` adds caller-side rules they need to remember. (2) **Caching the result for multiple awaiters** — `Task` is freely awaitable any number of times; `ValueTask` is not. (3) **Composition with `Task.WhenAll` / `Task.WhenAny`** — these expect `Task`; `vt.AsTask()` defeats the optimization. Rule: `ValueTask` for hot-path internal APIs with synchronous fast-paths; `Task` for everything else.
>
> **Cross-Q²**: `IAsyncEnumerator<T>.MoveNextAsync()` returns `ValueTask<bool>`. Why was that choice made?
>
> **A**: When iterating cached data, each `MoveNext` completes synchronously — a `Task` allocation per element would be catastrophic. For a 10K-element cached enumerable, returning `Task<bool>` per `MoveNext` would allocate 10K Task instances, ~800 KB of garbage. `ValueTask<bool>` with synchronous completion is zero-allocation for the entire iteration. This is the **canonical example** of when `ValueTask` exists — and why `IAsyncEnumerable` shipped only after `ValueTask` was stable.

### Drill 8 — Defensive copy

> **Q**: `void Method(in BigStruct s) { var x = s.X; }` where `BigStruct` is NOT readonly. Does this copy `s`?
>
> **A**: Likely yes — depends on what `s.X` is. If `X` is a property (a method call) or any non-`readonly` instance method, the compiler emits a **defensive copy**: it copies `s` to a hidden local first, then accesses `.X` on the copy. The reason: without `readonly` guarantees, the compiler can't prove `X`'s getter won't mutate `s`, and the `in` contract promises the caller's variable doesn't change.
>
> **Cross-Q**: How do I prevent the defensive copy?
>
> **A**: Two options. (1) **Make the struct `readonly struct`** — the compiler now knows nothing in the struct can mutate `this`, so no defensive copy. (2) Mark individual methods/properties `readonly` (C# 8+): `public readonly int X => _x;` or `public readonly int Magnitude() => ...`. The `readonly` keyword on members promises they don't mutate. Detection: Roslyn analyzer `IDE0250` suggests `readonly struct`; in IL look for the `dup`/`stloc`/`ldloca` pattern before the call.
>
> **Cross-Q²**: I have a 256-byte struct in a hot loop iterating 100M times. How much does the defensive copy cost?
>
> **A**: Roughly **8 ns of memcpy + cache pressure per iteration**, plus the JIT can't vectorize loops that involve hidden copies. On a 100M-iteration loop that's ~0.8 seconds of CPU time just on defensive copies — completely eliminated by adding `readonly` to the struct declaration. This is one of the highest-leverage one-keyword wins in C#. Combine with `in` parameters: `void Process(in BigReadOnlyStruct s)` passes a 64-bit pointer instead of 256 bytes, with zero defensive copy overhead.

### Drill 9 — `readonly struct` guarantees

> **Q**: What does the `readonly` keyword on a struct declaration actually guarantee?
>
> **A**: Four things, compile-enforced: (1) **All instance fields must be `readonly`** — can only be assigned in the constructor. (2) **All instance properties are get-only or `init`-only** — no setters. (3) **All instance methods are implicitly `readonly`** — they cannot mutate `this`. (4) **Compiler emits no defensive copies** when the struct is passed via `in` or accessed through `ref readonly`.
>
> **Cross-Q**: Does `readonly struct` give me thread safety?
>
> **A**: Almost. The struct *itself* is immutable, so reads from multiple threads are safe. **But**: when assigning a struct, the assignment is **not atomic for structs larger than the native word size** (8 bytes on 64-bit). A reader could see a half-updated struct mid-write — torn read. To be fully thread-safe across writes, either keep the struct ≤ 8 bytes, or use `Volatile.Read` / `Interlocked.CompareExchange` for assignment, or wrap in a class with a single reference swap. `readonly struct` solves immutability, not atomic update.
>
> **Cross-Q²**: What's the difference between `readonly struct`, `record struct`, and `readonly record struct`?
>
> **A**: `readonly struct` — the keyword constraints above; equality is reference-default (must override manually if you want value equality). `record struct` — value-equality auto-generated (Equals, GetHashCode, ==), but **fields are mutable by default** (you can declare `record struct Point(int X, int Y)` and reassign properties). `readonly record struct` — both: immutable AND value-equality. **For dictionary keys, hot loops, and value-typed coordinates, `readonly record struct` is the modern best choice** — it's the most rigorous combination.

### Drill 10 — `IDisposable` and finalizers

> **Q**: I'm writing a class that holds an `HttpClient` and a `FileStream`. Do I need a finalizer?
>
> **A**: **No.** Both `HttpClient` and `FileStream` are managed `IDisposable`s — they own their own unmanaged resources (sockets, file handles) and have their own finalizers as safety nets. Your class just needs to implement `IDisposable` and call `Dispose()` on both fields. Adding a finalizer here would add GC overhead (every instance enters the finalizer queue, survives an extra GC) for zero benefit — the cleanup would happen anyway via the children's finalizers.
>
> **Cross-Q**: When DO I need a finalizer?
>
> **A**: When your class **directly owns an unmanaged resource** — a raw `IntPtr` to a native handle, memory from `Marshal.AllocHGlobal`, or any resource not wrapped in another `IDisposable`. The finalizer is the **safety net** in case the caller forgets `Dispose()`. In 2026, **prefer `SafeHandle`** — its built-in finalizer handles cleanup, so your class needs only `IDisposable` and no finalizer of its own. The full Dispose pattern with `~MyClass()` and `protected virtual void Dispose(bool disposing)` is now rarely needed in application code.
>
> **Cross-Q²**: Why does `Dispose()` typically call `GC.SuppressFinalize(this)`?
>
> **A**: To tell the GC "this object is fully cleaned up; skip the finalizer". Without `SuppressFinalize`, the object **survives one extra GC cycle**: it sits in the f-reachable queue, the finalizer thread runs `~MyClass()` (which is now redundant work), then it's collected on the next cycle. `SuppressFinalize` removes the object from the finalization queue so it's collected on the first eligible cycle — saves both CPU and one generation of memory pressure. **Always call it in the `Dispose()` method when your class has a finalizer**, even if the finalizer body is empty after Dispose-cleanup runs.

### Drill 11 — `IAsyncDisposable`

> **Q**: When would you implement `IAsyncDisposable` over `IDisposable`?
>
> **A**: When the cleanup work itself **does I/O** — flushing a network buffer, gracefully closing a SQL connection (which may send a goodbye packet), draining a `Channel<T>`, awaiting in-flight tasks before disposal. Sync `Dispose()` would block the calling thread, which is unacceptable in async-first code paths (every blocked thread is a thread-pool starvation risk). `IAsyncDisposable.DisposeAsync()` returns `ValueTask` and the caller uses `await using` for scope-bound disposal.
>
> **Cross-Q**: Should I implement both `IDisposable` and `IAsyncDisposable`?
>
> **A**: Usually yes — for **maximum caller compatibility**. The BCL convention: `DisposeAsync()` does the real work; `Dispose()` either calls `DisposeAsync().AsTask().GetAwaiter().GetResult()` (sync-over-async, with caveats) or duplicates the cleanup logic synchronously. `HttpClient`, `Stream`, `DbContext` all implement both. **Caveat**: `await using` calls `DisposeAsync` only; `using` calls `Dispose`. If only `IAsyncDisposable` is implemented and someone writes `using x = ...;`, they get a compile error — explicit but not always desirable.
>
> **Cross-Q²**: `await using` vs `using`: what's the lowered code?
>
> **A**: `using` lowers to a `try/finally` calling `obj.Dispose()`. `await using` lowers to a `try/finally` calling `await obj.DisposeAsync()`. The `finally` block runs the async dispose synchronously to the surrounding async method's flow — if `DisposeAsync` throws, the exception surfaces from the enclosing scope, same as sync `using`. **One gotcha**: `await using` is only legal inside an `async` method; using it in a sync context is a compile error (which is what you want — it forces the caller to be async-aware).

### Drill 12 — String concat in a hot loop

> **Q**: Why is `result += items[i]` in a 10,000-iteration loop catastrophic?
>
> **A**: Strings are immutable, so each `+=` allocates a **new string** equal to `result.Length + items[i].Length` and copies all of `result` into it. After N iterations, total bytes allocated is **O(N²)** — for 10K items averaging 20 chars, that's ~1 GB allocated to produce a 200 KB string. Gen 0 thrashes, intermediate strings cross the LOH threshold and pollute Gen 2, p99 latency spikes.
>
> **Cross-Q**: What are the three fixes ranked by perf?
>
> **A**: (1) **`string.Create(len, items, callback)`** if total length is computable — single allocation, writes directly into the new string's char buffer. ~5× faster than StringBuilder. (2) **`StringBuilder` with pre-sized capacity** — `new StringBuilder(estimatedLen)` avoids growth churn; ~20× faster than `+=`. (3) **`StringBuilder` without pre-sized capacity** — internal char[] doubles as needed; still ~10× faster than `+=`. For genuine variable-length building with conditional appends, `StringBuilder` is the right choice.
>
> **Cross-Q²**: How does C# 10's interpolated string `$"x = {n}"` differ from `string.Format("x = {0}", n)`?
>
> **A**: `string.Format` boxes value-type args into an `object[]` (one alloc + N boxes), parses the format string at runtime (CPU cost), and produces the final string. `$"x = {n}"` lowers to **`DefaultInterpolatedStringHandler`** — a stack-allocated builder that uses pooled char buffers. Zero boxing (it has `AppendFormatted<T>(T value)` generic methods, JIT-specialized per `T`). Zero format-string parsing (the layout is compile-time-known). One final allocation: the result string. For `ILogger`, the custom handler is told the log filter level *before formatting* — if the level is disabled, **zero work happens**. This is why `_logger.LogInformation($"...")` is now safe in hot paths.

### Drill 13 — `string.Create` vs StringBuilder

> **Q**: When does `string.Create` beat `StringBuilder`?
>
> **A**: When you **know the final length ahead of time**. `string.Create` allocates the result string once and gives you a `Span<char>` to write into; `StringBuilder` grows its internal `char[]` (doubling, so amortized O(N) allocations) and then allocates the final string via `ToString()`. For known length: `string.Create` is 1 allocation; `StringBuilder` is `log2(N)` allocations of intermediate growth arrays plus the final string.
>
> **Cross-Q**: Walk me through a real `string.Create` example.
>
> **A**:
> ```csharp
> // Building "Hello, {name}!" — total length is known: 9 + name.Length
> string greeting = string.Create(9 + name.Length, name, (chars, state) =>
> {
>     "Hello, ".AsSpan().CopyTo(chars);
>     state.AsSpan().CopyTo(chars[7..]);
>     chars[7 + state.Length] = '!';
> });
> ```
> The `state` parameter avoids the lambda capturing `name` (which would allocate a closure). The lambda receives `Span<char>` over the new string's storage — you write the characters directly, no intermediate buffer.
>
> **Cross-Q²**: What's the catch with `string.Create`?
>
> **A**: Three. (1) **You must compute the final length exactly** — write past `chars.Length` and you get an `IndexOutOfRangeException`; write less and the string has uninitialized chars at the end. (2) **The callback runs synchronously and cannot async-await** — no I/O inside. (3) **Captures cost allocation** — use the `state` parameter for any data the callback needs; don't capture outer variables. For unknown lengths or complex logic with conditional content, `StringBuilder` is still the right tool. `string.Create` is the specialist for known-length single-allocation construction.

### Drill 14 — Boxing count

> **Q**: `int i = 5; object o = i; int j = (int)o;` — how many heap allocations?
>
> **A**: **One**. The first assignment `object o = i` boxes — allocates a small object on the heap, copies the value 5 into it, and stores the reference in `o`. The cast `(int)o` is an **unbox** — copies the value back out of the heap object into the stack-allocated `j`. Unboxing doesn't allocate; it reads from existing memory. The box has ~24 bytes overhead on 64-bit (object header + the int).
>
> **Cross-Q**: How would I count boxes without running the code?
>
> **A**: Three ways. (1) **ILSpy / ildasm** — look for the `box` IL opcode; each occurrence is one heap allocation. (2) **Roslyn analyzer `HAA0601`** (heap allocation analyzer) — flags suspected boxes at compile time. (3) **BenchmarkDotNet `[MemoryDiagnoser]`** — measure `Allocated` column on a `[Benchmark]`. For a method that should be allocation-free but reports 24+ bytes per call, there's a hidden box. The fix is usually adding a generic constraint or calling the struct's method directly instead of through an interface.
>
> **Cross-Q²**: Where do enum boxes happen, and is `.NET 9` better than `.NET Framework 4.8` here?
>
> **A**: Three classic enum-boxing spots: (1) `string.Format("{0}", myEnum)` boxes the enum to `object` for the format. (2) `Console.WriteLine(myEnum)` calls the `object` overload — boxes. (3) `myEnum.ToString()` in older runtimes boxed before formatting. **.NET Core / .NET 5+** added optimized paths: `Enum.ToString()` no longer boxes for common cases; the interpolation handler `$"{myEnum}"` calls a generic `AppendFormatted<T>` that doesn't box. **.NET Framework 4.8** still boxes in all three cases — one reason hot-path code on .NET Framework allocates more than the equivalent on modern .NET.

### Drill 15 — Boxing in generic methods

> **Q**: `void Compare<T>(T a, T b) where T : IComparable<T> { a.CompareTo(b); }` — does this box?
>
> **A**: **No**. The constraint `where T : IComparable<T>` tells the JIT that any concrete `T` it specializes for implements `IComparable<T>`. When `T` is a value type, the JIT generates a **specialized method body** that calls `T.CompareTo(T)` directly — a non-virtual method call on the struct, no box. When `T` is a reference type, the call is via the interface, but reference types don't box. This is the **single most important reason `List<T>` exists** and `ArrayList` is dead.
>
> **Cross-Q**: What if I remove the constraint? `void Compare<T>(T a, T b) { ((IComparable<T>)a).CompareTo(b); }`
>
> **A**: **Boxes**, for value types. The cast `(IComparable<T>)a` boxes `a` to the interface type. The JIT specializes the generic but can't prove `T` implements the interface at compile time, so it must use a runtime cast that allocates. Two changes restore zero-box: (1) add the constraint, as shown; or (2) keep no constraint but accept the box (rarely the right answer).
>
> **Cross-Q²**: I see `where T : IComparable<T>` in a method, and inside it I do `object o = a;`. Does that box?
>
> **A**: **Yes, it boxes for value-type T**. The constraint prevents boxing on **interface method calls** (`a.CompareTo(b)` is direct), but assignment to `object` is a separate operation — the runtime must produce a reference-typed value, which requires boxing the struct. Rule: constraints solve boxing on **calls through the constraint**; they don't solve boxing on **assignments to `object`** or to broader interface types. To avoid the box, keep the value in `T` form and use other constraint-call sites; don't widen to `object`.

### Drill 16 — Server vs Workstation GC

> **Q**: ASP.NET Core defaults to which GC mode, and why?
>
> **A**: **Server GC** (when running on a machine with ≥ 2 logical CPUs). Server GC creates **one heap per logical CPU**, uses dedicated GC threads, and runs collections in parallel across heaps. The result: much higher allocation throughput (per-CPU heaps eliminate contention) and shorter individual pause times (parallel work). The trade-off is **higher memory footprint** (each heap has its own segments) — typically 2–3× a workstation-GC equivalent. For a web service, this trade-off is universally correct: response throughput and tail latency matter more than peak RAM.
>
> **Cross-Q**: I'm running ASP.NET Core in a 256 MB Kubernetes pod. Should I still use Server GC?
>
> **A**: **Test with both modes**. Classic Server GC may over-commit memory in small containers — each CPU gets a heap segment (often 256 MB+), and on a 4-vCPU pod you can end up with 1 GB of GC heap budgeted for a 256 MB pod. .NET 8+ added **DATAS** (Dynamic Adaptation to Application Sizes) — enable with `DOTNET_GCDynamicAdaptationMode=1` or `<GarbageCollectionAdaptationMode>1</GarbageCollectionAdaptationMode>`. DATAS shrinks the heap budget to match the container limit. For containers with < 512 MB, Workstation GC may actually be better; for ≥ 1 GB, Server GC with DATAS wins. **Always measure** in your specific topology.
>
> **Cross-Q²**: How do I verify which GC mode my process is actually running?
>
> **A**: `System.Runtime.GCSettings.IsServerGC` returns `true` or `false` at runtime. Also `GCSettings.LatencyMode` tells you `Interactive`, `Batch`, `LowLatency`, etc. For an external check: `dotnet-counters monitor System.Runtime` shows GC stats; the heap size and Gen 2 collection cadence will look very different on Server vs Workstation. If you're suspicious of a misconfiguration (e.g., `runtimeconfig.json` deployed wrong), `IsServerGC` is the first thing to log at startup.

### Drill 17 — `GC.Collect()`

> **Q**: When should you call `GC.Collect()` in production code?
>
> **A**: **Almost never.** The GC is significantly smarter than any manual heuristic — it monitors allocation rate, segment fullness, and survival rates to decide when to collect. Forcing a collection wastes CPU and disrupts the GC's tuning. **`GC.Collect()` in a hot path is a code smell that always loses on a benchmark.**
>
> **Cross-Q**: Are there *any* legitimate cases?
>
> **A**: Two. (1) **After a known one-time large allocation phase** — e.g., loading a 500 MB cache at app startup, then never allocating that much again. One `GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: true)` at the end of the load phase compacts the heap into a clean steady-state shape. (2) **Benchmarking** — bringing the heap to a known state between iterations of a micro-benchmark. Both cases are rare and explicit.
>
> **Cross-Q²**: What does `GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: true)` mean parameter-by-parameter?
>
> **A**: (a) `2` — collect up to and including Gen 2 (so all generations + LOH). (b) `GCCollectionMode.Forced` — actually perform the collection now (alternatives: `Default` = let GC decide if collection is warranted; `Optimized` = collect only if there's likely a benefit). (c) `blocking: true` — wait for the collection to complete before returning (vs background async). (d) `compacting: true` — include LOH compaction (normally LOH is non-compacting). Combined: "synchronously perform a full collection of all generations including LOH compaction, right now." Maximum disruption, maximum reclamation. Use only in the bootstrap scenarios above.

### Drill 18 — BenchmarkDotNet `[MemoryDiagnoser]`

> **Q**: What does `[MemoryDiagnoser]` add to a BenchmarkDotNet report?
>
> **A**: Three columns: **Allocated** (bytes per call, the headline number), and **Gen 0 / Gen 1 / Gen 2** (collection counts per 1000 ops). It runs each benchmark twice — once for time measurement, once with allocation tracking enabled (which adds overhead, so it's separated). The result is per-call attribution of how much garbage your method generates and which generations are affected.
>
> **Cross-Q**: I see `Method A: 100 ns, 0 B`; `Method B: 80 ns, 24 B`. Which is faster in production?
>
> **A**: **Likely A**, even though B has a lower per-call mean. The 24 B/op on the hot path becomes Gen 0 pressure: at 1M ops/sec, that's 24 MB/s of allocations, triggering Gen 0 every few hundred ms. Each Gen 0 briefly pauses all threads; under load the pause amortizes into worse p99/p999 latency even though average latency is fine. A's 0 B/op contributes zero to GC. **Senior rule**: micro-benchmarks measure CPU; production performance is CPU + GC + cache + tail-latency. Always include `[MemoryDiagnoser]` and weigh allocations alongside time.
>
> **Cross-Q²**: What are the two most common BenchmarkDotNet pitfalls?
>
> **A**: (1) **Dead-code elimination** — a benchmark that returns `void` and has no observable side effect gets optimized to nothing by the JIT, reporting 0 ns. Fix: **always return the computed value** from the benchmark method; BDN consumes it to force evaluation. (2) **Running in Debug mode or under a debugger** — disables tier-2 JIT optimizations, giving meaningless numbers. BDN warns about both at startup. Honorable mention: **`[Params]` cardinality explosion** — `[Params(1, 10, 100, 1000)]` × 4 benchmarks × 3 runtimes = 48 runs taking 30+ minutes. Tune your parameter set deliberately.

### Drill 19 — Closure allocations

> **Q**: `var n = 5; Func<int> f = () => n * 2;` — how many allocations?
>
> **A**: **One**. The lambda captures the local `n`, so the compiler generates a **closure class** — a heap-allocated object with `n` as a field and a method that returns `n * 2`. The `Func<int>` is then a delegate pointing to that method on the closure instance. Total: 1 closure object (~24 bytes) + 1 delegate (~32 bytes for non-static methods). For a one-time lambda this is fine; in a hot loop, both add up.
>
> **Cross-Q**: How do I write a closure-free version?
>
> **A**: Two approaches. (1) **No capture** — refactor so the lambda doesn't reference outer state: `Func<int, int> f = n => n * 2;` then call `f(5)`. No closure allocated; the delegate may be cached as a static field by Roslyn (since C# 7.2's static lambdas in C# 9 `static () => ...`). (2) **Method group** — replace the lambda with a static method: `static int Double(int n) => n * 2; Func<int, int> f = Double;`. (3) **For collection APIs**, use overloads that take state: `list.FirstOrDefault((item, state) => item.Id == state.Id, criteria)` instead of `list.FirstOrDefault(item => item.Id == criteria.Id)`. The state-passing overload avoids the closure capture entirely.
>
> **Cross-Q²**: How do I detect closure allocations in production code?
>
> **A**: Three tools. (1) **Roslyn analyzer `HAA0301-302`** (Heap Allocation Analyzer) — flags lambdas that capture variables and warns about closure allocation. (2) **`[MemoryDiagnoser]` benchmarks** — if a method that should be allocation-free reports 56+ bytes per call, there's likely a closure. (3) **PerfView allocation trace** — search for compiler-generated `<>c__DisplayClass*` types; each one is a closure. The most common offenders: LINQ in hot paths (`.Where(x => x.Id == myId)` captures `myId`), event handlers that capture state, and lambda parameters to async methods.

### Drill 20 — `ref` returns

> **Q**: What's a real-world use of `ref` returns?
>
> **A**: **Dictionary in-place update** via `CollectionsMarshal.GetValueRefOrNullRef`. The typical "find-or-add" pattern requires two dictionary lookups (`TryGetValue` then `[key] = ...`). `GetValueRefOrNullRef` does **one** lookup and returns a `ref TValue` to the bucket slot — you mutate in place. For counter-increment patterns (`counts[key]++`), this is roughly **2× faster** than the two-lookup version.
>
> **Cross-Q**: Show me the code.
>
> **A**:
> ```csharp
> using System.Runtime.InteropServices;
> 
> var counts = new Dictionary<string, int>();
> ref int slot = ref CollectionsMarshal.GetValueRefOrNullRef(counts, "alice");
> if (Unsafe.IsNullRef(ref slot))
>     counts["alice"] = 1;             // first time — add via normal path
> else
>     slot++;                          // direct mutation, no second lookup
> ```
> `Unsafe.IsNullRef(ref slot)` checks whether the dictionary returned a "not found" marker (a null ref). On hit, `slot++` writes through the ref directly into the dictionary's internal bucket.
>
> **Cross-Q²**: Why is this only available in .NET 6+? Wasn't `ref` return added in C# 7?
>
> **A**: C# 7 (2017) added `ref` returns and `ref` locals — the language feature. But the BCL didn't expose `ref` returns from `Dictionary<TKey, TValue>` because of safety: a `ref` to a dictionary slot becomes invalid if the dictionary resizes (the backing array is reallocated). Exposing the ref via the normal API surface would let callers hold dangling refs. **.NET 6 (2021)** added `CollectionsMarshal.GetValueRefOrNullRef` in the `System.Runtime.InteropServices` namespace — explicitly opt-in, the name signals "you're crossing into unsafe territory, you take responsibility for not resizing the dictionary while holding the ref". Similar gating exists for `CollectionsMarshal.AsSpan(List<T>)` — span over the list's backing array, invalidated by `Add`.

</details>
## Cheat Sheet

- **GC generations**: Gen 0 (microseconds, frequent); Gen 2 + LOH (milliseconds, rare — but spikes p99).
- **LOH threshold**: ≥ 85,000 B goes to LOH (treated like Gen 2, non-compacting by default).
- **POH** (.NET 5+): `GC.AllocateArray<T>(len, pinned: true)` — for long-lived interop buffers.
- **Server GC**: default for ASP.NET Core with ≥ 2 CPUs; per-CPU heaps; high throughput, more RAM.
- **`Span<T>`**: `ref struct` view; zero alloc; can't cross `await` or be a class field.
- **`ReadOnlySpan<T>`**: read-only view; `string.AsSpan()` and UTF-8 literals (`"abc"u8`).
- **`Memory<T>`**: heap-storable cousin; safe to await; `.Span` to actually access.
- **`stackalloc Span<byte>`**: fixed-size on stack; cap at ~1 KB; never in a loop; clamp size from input.
- **`ArrayPool<T>.Shared.Rent` + `Return`**: variable-sized buffers; pass `clearArray: true` for PII.
- **`ValueTask<T>`**: hot-path synchronous completion saves Task alloc; **await once, no concurrent**.
- **`readonly struct`**: eliminates defensive copies on `in` parameters and ref-readonly access.
- **`in` parameter**: pass-by-reference for big structs; pair with `readonly struct` to avoid defensive copies.
- **`ref T` returns**: `CollectionsMarshal.GetValueRefOrNullRef(dict, key)` — one lookup instead of two.
- **`IDisposable`**: needed for any owned resource; finalizer only if owning raw unmanaged `IntPtr` (prefer `SafeHandle`).
- **`IAsyncDisposable`**: when cleanup itself does I/O; pair with `await using`.
- **`string.Create(len, state, span => ...)`**: single-alloc string when length known; beats `StringBuilder`.
- **`DefaultInterpolatedStringHandler`** (C# 10): `$"..."` for `ILogger` allocates only if log enabled.
- **UTF-8 literal**: `"text"u8` is `ReadOnlySpan<byte>` — no allocation, no encode.
- **Boxing checklist**: any cast to `object` / interface, generic without constraint, `ArrayList` — checks via IL `box` opcode.
- **`GC.Collect()`**: almost never; only after one-time bulk loads or in benchmark setup.
- **BenchmarkDotNet + `[MemoryDiagnoser]`**: measure `Allocated` column — return the value to defeat dead-code elimination.
- **Heuristic**: hot path → check Allocated column → swap to span/pool until 0 B/op.

## Walkthrough — Gen 2 pressure from `string` concat

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: An order-export endpoint generates 100 MB CSV files. Production shows Gen 2 GC every 8 seconds during exports; p99 latency for *unrelated* endpoints jumps from 30 ms to 1500 ms. The endpoint itself takes 12 seconds for a 100 MB file.

**Diagnosis**: Run `dotnet-counters monitor System.Runtime` — `gen-2-gc-count` rate confirms the spike correlates with export volume. Capture an allocation trace: `dotnet-trace collect --providers Microsoft-Windows-DotNETRuntime:0x1:5,Microsoft-DotNETCore-SampleProfiler -p <pid>`. Open in PerfView; Allocation View shows ~95% of bytes are `System.String` instances ranging 1 KB to 100 KB. Code review of `ExportRows`: `csv += $"{order.Id},{order.Total},{order.CustomerName}\n";` inside a per-row loop — each `+=` allocates a new string equal to total accumulated CSV length so far. 1M rows × ~50 KB average accumulated length = 25 GB allocated, much of it making it to the LOH (objects ≥ 85,000 B), then to Gen 2.

**Fix**: Stream directly to the response stream as UTF-8 bytes via `Utf8JsonWriter`/`StreamWriter` patterns and pooled buffers.

```csharp
await using var sw = new StreamWriter(response.Body, Encoding.UTF8, bufferSize: 64 * 1024);
foreach (var o in orders)
    await sw.WriteLineAsync($"{o.Id},{o.Total},{o.CustomerName}");
// or for utmost perf: rent a pooled buffer, format with UTF-8 literals + Utf8Formatter, flush on full
```

After: zero retained CSV allocations, Gen 2 collections drop to baseline (every 60 s+), endpoint runs in ~1.5 s.

**Why it works**: Streaming avoids ever materializing the 100 MB string in memory — bytes leave the process as fast as they're produced. Replacing `+=` with a buffered writer changes the allocation pattern from O(n²) cumulative string copies to O(n) once-through-buffer writes. LOH pressure disappears because no allocation crosses the 85,000-byte threshold.

</details>
## Self-test

<details>
<summary>1. Why does the C# compiler refuse to let you store a `Span<T>` in a class field, and what's the workaround for an async method that needs span-like access?</summary>

`Span<T>` holds a managed pointer (`byref`) into memory that may be on the stack, heap, or native — it's a `ref struct` to enforce stack-only lifetime. A class field would let the span outlive its backing memory (e.g., `stackalloc` after the frame returns) — the compiler refuses to prevent this. For async methods, the compiler lowers them into a state machine class; locals become fields, so a `Span<T>` local in an async method is also a compile error. Workaround: store `Memory<T>` (heap-storable) on the field/parameter, and inside synchronous regions call `.Span` to do the actual work.
</details>

<details>
<summary>2. Apply: profile shows `string.Format("{0}-{1}", a, b)` as a hot allocator. Three faster alternatives, ranked.</summary>

(1) Interpolated string handler (C# 10+): `$"{a}-{b}"` lowers to `DefaultInterpolatedStringHandler` which uses pooled buffers; for ILogger, allocates *nothing* if level is filtered. (2) `string.Create`: `string.Create(a.Length + b.Length + 1, (a, b), (span, state) => ...)` — single allocation, no intermediate `object[]`. (3) `Utf8.TryWrite` to a pooled byte span if downstream is binary. The classic `string.Format` boxes value-type args into `object[]` and runs format-string parsing every call — the modern alternatives skip both costs.
</details>

<details>
<summary>3. Trade-off: when does `stackalloc` lose to `ArrayPool<T>.Rent`?</summary>

`stackalloc` is unbeatable for *small* (≤ ~1 KB), *known-size*, *single-frame* buffers — zero allocation, zero GC, automatic reclaim on return. Loses when (a) size is large or unknown — risk of `StackOverflowException`, especially in async methods or recursion; (b) buffer must outlive the method; (c) used in a loop — each iteration adds to stack, blowing the frame. `ArrayPool<T>.Rent(size)` handles arbitrary sizes, survives across async boundaries (it's heap-allocated), but pays the rental/return overhead and pollutes the pool if `Return` is missed. Rule: ≤ 1 KB on stack; > 1 KB or async → pool.
</details>

<details>
<summary>4. Analyze: BenchmarkDotNet shows `Method A: 100 ns, 0 B`; `Method B: 80 ns, 24 B`. Which is faster in production?</summary>

Likely A — even though B is faster per call. The 24 B/op on the hot path becomes Gen 0 pressure: at 1M ops/sec, that's 24 MB/s of allocations, triggering Gen 0 collections every few hundred ms. Each collection pauses *all* threads briefly; under load, the pause amortizes into worse p99/p999 even if avg latency improves. The 0 B/op method has no GC contribution. Senior rule: micro-benchmarks measure CPU; production performance is CPU + GC + cache + tail-latency. Always include `[MemoryDiagnoser]` and weigh allocations.
</details>

<details>
<summary>5. You see `Span<byte> buffer = stackalloc byte[size];` where `size` comes from a request parameter. Critique.</summary>

Stack overflow waiting to happen. `stackalloc` doesn't bounds-check against the remaining stack — a malicious or buggy `size` of 10 MB blows the thread stack, killing the process (no `OutOfMemoryException`, just immediate termination). Two fixes: (1) clamp the stackalloc size and fall back to pooled array: `Span<byte> buffer = size <= 1024 ? stackalloc byte[size] : ArrayPool<byte>.Shared.Rent(size);` — note the rented array must be returned in `finally`. (2) Always use `ArrayPool` for sizes derived from input. The pattern `size <= threshold ? stackalloc : pool.Rent` is the .NET BCL standard idiom — see `Utf8JsonReader` source.
</details>

## Cross-references

- **Previous: [Reflection, Attributes & Source Generators](./08-reflection-attributes-and-source-gen.md)** — source generators are the allocation-free alternative to reflection.
- **[Type System Deep Dive](./02-type-system.md)** — `ref struct`, `readonly struct`, `record struct` are the foundations.
- **[Generics & Variance](./04-generics-and-variance.md)** — `where T : unmanaged`, `where T : allows ref struct` constraints.
- **[Garbage Collection in .NET 10](../01-net-core-deep-dive/01-net-fundamentals.md#3-garbage-collection-in-net-10)** — what happens to allocations once made.
- **[Async/Await deep dive](../01-net-core-deep-dive/03-async-and-threading.md)** — why `Span<T>` can't cross `await` (state machine boxing).

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [Memory and Span usage guidelines](https://learn.microsoft.com/en-us/dotnet/standard/memory-and-spans/memory-t-usage-guidelines).
- Microsoft Learn — [`Span<T>` documentation](https://learn.microsoft.com/en-us/dotnet/api/system.span-1).
- Stephen Toub — *"Performance Improvements in .NET 8/9"* (devblogs) — single best resource on allocation reduction in modern .NET.
- Konrad Kokosa — *Pro .NET Memory Management* (Apress, 2018) — comprehensive coverage of GC, allocations, profiling.
- Adam Sitnik — [BenchmarkDotNet documentation](https://benchmarkdotnet.org/) and his blog on memory.
- *Writing High-Performance .NET Code* by Ben Watson — practical performance-engineering reference.

</details>
<!-- nav-footer-start -->

---

[← Previous: Reflection, Attributes & Source Generators](08-reflection-attributes-and-source-gen.md) · [↑ Back to top](#memory--performance-idioms) · [Next: Data Structures & Algorithms (DSA) →](../06-dsa/README.md)

<!-- nav-footer-end -->
