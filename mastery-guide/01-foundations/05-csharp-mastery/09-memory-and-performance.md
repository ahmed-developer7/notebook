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
  - [Data locality: object layout, padding, and cache lines](#data-locality-object-layout-padding-and-cache-lines)
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

The .NET BCL since .NET Core 2.1 has been quietly rebuilt around a low-allocation philosophy: `Span<T>`, `ReadOnlySpan<T>`, `string.Create`, `ArrayPool<T>`, ref structs, and source-generated paths. The library team's goal — "you should rarely need to write `unsafe`" — is largely realized: the safe primitives now cover the cases that used to require pointers.

For a senior backend engineer, this matters in two contexts: (1) writing hot-path code (parsers, serializers, telemetry, framework internals) where each allocation costs measurable GC pressure; (2) reading the BCL source to understand *why* `string.Concat` pre-counts the total length and allocates exactly once (and why the `+` operator in a single expression compiles straight into it), why `Utf8JsonReader` doesn't allocate, why `LoggerMessage` source-gen exists. The mental model is: "for every allocation, ask if it's necessary, and if a `Span<T>`-based alternative exists."

This file is the practical end of the type-system chapter — `ref struct`, `readonly struct`, generics + `unmanaged` constraint all converge here.

> 🌍 **In the real world**: the interview version of this topic is almost never "make this loop faster". It is "your p99 doubled after a release, average latency didn't move, CPU didn't move — what do you look at?" A candidate who reaches straight for allocation and GC pause distribution is answering the question that was asked. A candidate who talks about algorithmic complexity is answering the average, and the average is exactly the number that stayed flat. Everything on this page exists to make that first answer available under pressure.

> 🌍 **In the real world**: a team is told to "reduce allocations" after a memory-usage review and spends a sprint replacing `foreach` with `for`, caching `string.Empty`, and micro-tuning helper methods. Allocation rate barely moves. The actual source — visible in the first five minutes of an allocation trace — is one middleware calling `JsonSerializer.Serialize` to a `string` for an audit log, on every request, including the ones nobody audits. The lesson that survives into the interview: *measure first* is not humility boilerplate, it is the difference between a sprint and an afternoon.

## Core concepts

### The allocation taxonomy

Five places allocations can come from in a typical .NET app, ranked by frequency:

1. **Object instantiation** — `new Foo()` for a class. Heap allocation in Gen 0.
2. **Boxing** — value type stored in `object` / interface. Heap allocation, pure GC pressure since the value type itself is small.
3. **String operations** — `+`, `Replace`, `Substring`, `Trim` — each returns a *new* string.
4. **Array creation** — `new int[1024]` (heap) vs `stackalloc int[1024]` (stack).
5. **Closure capture** — lambda capturing a local creates a heap-allocated closure object.

**Expanding #5, because it is the one that surprises people**

A lambda that captures nothing is compiled to a cached static delegate — allocated once, ever. A lambda that captures *anything* forces the compiler to generate a **display class** (`<>c__DisplayClass...`), heap-allocate one per entry into the enclosing scope, and hoist the captured locals into it as fields. Three details that matter:

- **Capture is per-scope, not per-variable.** All variables captured by all lambdas in the same scope share one display class. So a lambda that captures one `int` can keep a large object alive, because a *different* lambda in the same method captured it into the same display class. This is a real and very hard-to-see leak source in event handlers and registered callbacks.
- **`this` counts.** Referencing an instance field or method inside a lambda captures `this`, which pins the entire enclosing object for the delegate's lifetime.
- **`static` lambdas are a compile-time guard**, not an optimization: `static () => ...` (C# 9) makes it an *error* to capture anything. Use it on any lambda you intend to be allocation-free, and the compiler enforces it forever, including after the next person edits the body.

```csharp
// Allocates a display class + a delegate on every call
items.Where(x => x.TenantId == tenantId);

// Allocates neither: nothing captured, delegate is cached by Roslyn
items.Where(static x => x.IsActive);
```

> 🌍 **In the real world**: a background job walks a work queue and starts one task per item:
>
> ```csharp
> for (int i = 0; i < batch.Count; i++)
>     _ = Task.Run(() => Process(batch[i]));      // captures i, not batch[i]
> ```
>
> Some items are processed twice, some never, and every so often it throws `ArgumentOutOfRangeException` with `i == batch.Count`. The `for` variable is **one** variable for the whole loop, hoisted into a single display class that all the lambdas share — so each task reads whatever `i` happens to be when it runs, not what it was when the task was created. A `foreach` variable does not behave this way (C# 5 made it per-iteration), which is exactly why this bug survives review: the same-looking `foreach` version is correct. Two fixes: copy to a loop-local (`int idx = i;`) or capture the item instead of the index. The allocation angle is the same mechanism seen from the other side — **the closure is an object with a lifetime, and reasoning about it as if it were a snapshot is what produces both the leaks and the races.**

Allocation isn't always bad — Gen 0 collections are fast. But on hot paths (request handlers, parsers, log formatters, serializers), persistent allocation pressure causes:
- More frequent Gen 0 collections (stop-the-world, brief).
- Promotion to Gen 1/2 (more expensive collections).
- Fragmentation in the LOH for big allocations.
- Inflated working set.

**Rule of thumb:** profile first (BenchmarkDotNet, dotnet-counters, dotMemory). Don't pre-optimize. But once you know where the pressure is, reach for the tools below.

**Growth: the allocation you pay for log N times instead of once**

Category #4 above says "array creation", which undersells it. Most arrays in application code are never created directly — they are created *repeatedly*, by a collection growing. That is the single most common allocation source in ordinary CRUD code, and it is invisible because nobody wrote `new`.

`List<T>` in CoreLib starts life pointing at a **shared static empty array**, so `new List<T>()` allocates only the `List<T>` object itself. On the first `Add` it allocates a backing array of `DefaultCapacity = 4`; after that, `Grow` computes `2 * _items.Length`, clamped to `Array.MaxLength`. Every growth allocates a new array, copies the old contents, and abandons the old array as garbage. So filling a list to N elements without presizing:

- allocates roughly **log₂(N) arrays**, not one;
- allocates and copies roughly **2N element slots' worth of bytes** in total, of which all but the last array is garbage;
- and puts the **later intermediates over the LOH threshold** for large N, exactly as the string-concat case does.

`Dictionary<TKey,TValue>` and `HashSet<T>` are worse per resize, because a resize is not just a copy: the bucket count moves to the next **prime**, both the buckets array and the entries array are reallocated, and **every entry has to be re-bucketed** into the new bucket count. (The stored hash codes are reused rather than recomputed — the exception being the collision-resistance path for `string` keys, which does recompute them — so it is a re-bucket rather than a full rehash, but it is still O(n) work per resize on top of the allocation.)

The fixes are boring and effective, and each has its own version gate:

| API | Gate | Use |
|---|---|---|
| `new List<T>(capacity)`, `new Dictionary<K,V>(capacity)` | always | You know the size at construction |
| `Dictionary<TKey,TValue>.EnsureCapacity(n)` / `HashSet<T>.EnsureCapacity(n)` | .NET Core 2.1 | You learn the size after construction; returns the capacity you actually got |
| `List<T>.EnsureCapacity(n)`, and the same on `Stack<T>` / `Queue<T>` | .NET 6 | Same, for the list-shaped collections |
| `CollectionsMarshal.SetCount(list, n)` + `CollectionsMarshal.AsSpan(list)` | .NET 8 | Presize *and* skip `Add`'s per-element work — at the cost of possibly exposing uninitialized elements |
| `Array.Empty<T>()` | .NET Framework 4.6 / .NET Core 1.0 | Returning "no items" without allocating; `new T[0]` allocates a fresh object every call |

Two details that make this a senior answer rather than a tip:

- **`ToList()` and `ToArray()` are not always growth-bound.** Both take a count-known fast path when the source can report its count — `ICollection<T>` at minimum, and in modern LINQ any iterator that can report one, which is what `Enumerable.TryGetNonEnumeratedCount` exposes publicly. So `someList.ToArray()` is one exact-size allocation. The growth churn appears when the count genuinely isn't known ahead of time — a `Where`, a projection over a data reader, an `IAsyncEnumerable` drained into a list. That is where presizing (or not materializing at all) pays.
- **Never presize from untrusted input.** `Dictionary.EnsureCapacity`'s own documentation carries the warning: "If `capacity` comes from user input, prefer letting the collection resize itself as elements are added instead of calling this method. If you must use a user-specified value, either clamp it to a reasonable limit… or verify that the element count matches the specified value." A request that says `"count": 2000000000` and sends three rows has just asked you to allocate a 2-billion-entry table. This is the same failure shape as `stackalloc` sized from input, one layer up.

> 🌍 **In the real world**: a reporting endpoint does `var rows = query.Where(Filter).Select(Project).ToList();` and typically returns a few hundred rows. A new tenant onboards with 400,000 rows and the endpoint starts triggering full GCs. Nothing about the code changed and no single allocation is large — the list simply grew through every power of two on the way up, and the last several backing arrays were each large objects allocated straight into the LOH and then discarded. The team's first instinct was "the query is slow"; the trace said `T[]`, several sizes of it, all garbage. Two fixes, and they are different decisions: presize the list if you must materialize (`EnsureCapacity` after a `Count()`), or stop materializing and stream the projection to the response. The transferable point: **a collection that grows is a loop that allocates, and the size comes from your data, not your code.**

**The sixth category: allocations the JIT deletes for you (escape analysis)**

The list above describes what the *IL* asks for. It is no longer what the *machine code* does. The JIT performs **escape analysis**: it decides whether an object allocated in a method can outlive that method. Microsoft's definition: "Objects 'escape' when assigned to non-local variables or passed to functions not inlined by the JIT. If an object can't escape, it can be allocated on the stack."

What has shipped, gate by gate:

| Runtime | What the JIT can stack-allocate |
|---|---|
| .NET 9 | Boxes whose lifetime is provably local (object stack allocation for boxes) |
| .NET 10 | Small, fixed-size arrays of value types with no GC pointers; small, fixed-size arrays of reference types; objects reachable only through **local struct fields**; the `Func`/delegate object itself when it doesn't escape |

```csharp
// .NET 10: 'numbers' never leaves Sum, so the JIT allocates it on the stack —
// no CORINFO_HELP_NEWARR_1_VC call in the generated code at all.
static void Sum()
{
    int[] numbers = { 1, 2, 3 };
    int sum = 0;
    for (int i = 0; i < numbers.Length; i++) sum += numbers[i];
    Console.WriteLine(sum);
}
```

Three things follow that matter in an interview:

1. **"`new` means heap" is now a half-truth.** The accurate statement is "`new` on a reference type *requests* a heap object; the JIT may satisfy it on the stack when it can prove the object doesn't escape." Say the second version.
2. **Inlining is a precondition.** An object passed to a method the JIT did *not* inline is treated as escaping. This is why .NET 10 also relaxed the inliner's size limits for methods returning small fixed-size arrays — the two optimizations only pay off together.
3. **It is an optimization, not a contract.** Nothing in the language guarantees stack allocation, it doesn't apply in Debug/tier-0 code, and the shapes it recognizes change every release. You cannot design around it; you can only stop writing code that *defeats* it (capturing into fields, passing to non-inlineable virtual calls, storing into statics).

In .NET 10 the remaining heap allocation in the delegate example above is the closure display class itself — the runtime team's notes say stack allocation of closures is planned for a later release, not shipped.

> 🌍 **In the real world**: a team upgrades from .NET 8 to .NET 10 and their allocation-per-request number drops without a single code change. Someone writes it up as "the GC got faster". It didn't — the JIT stopped asking the GC for several of the objects. The reason this matters beyond trivia: the same team then "optimises" the hot method by extracting a helper, the helper is too large to inline, the array starts escaping again, and the win silently reverses. The number regressed because of a refactor that looks, in review, like an unambiguous improvement.

**Stack vs heap — what actually determines where a value lives**

This is the oldest question in the .NET interview and the most commonly answered wrong, because the familiar answer — "value types go on the stack, reference types go on the heap" — is not a rule about types. It is a rule about *storage locations*, and the type only participates.

The accurate formulation, and the one to say out loud: **a value type lives wherever its storage location lives.** Work through the cases:

| The value | Where its bytes are |
|---|---|
| `int i` as a method local | A register if the JIT can enregister it; otherwise the stack frame |
| `struct Point p` as a method local | Same — register(s) or stack frame, no heap object, no header |
| `int Count` as a field of a `class` | **Inside the class's heap object.** There is no separate stack copy |
| `Point[] points` element | **Inside the array on the heap**, laid out contiguously, no per-element header |
| A local captured by a lambda | **Inside the display class on the heap** — the local is *hoisted*, and it is no longer a stack slot at all |
| A local that lives across an `await` | Inside the state machine, which is on the stack until the method suspends and on the heap afterwards |
| `(object)p` or `IComparable c = p` | Inside a **boxed** heap object |
| A reference-type local (`var s = new Foo()`) | The *reference* is a register or stack slot; the *object* is on the heap — unless escape analysis proves it doesn't escape (above) |

So both halves of the folk answer are wrong at the edges: a value type is frequently on the heap, and a reference type's object is occasionally on the stack. The framing that survives cross-questioning is Eric Lippert's: **the stack is an implementation detail.** What the language actually guarantees is *lifetime and copy semantics* — a value type is copied on assignment and its storage is reclaimed with whatever contains it; a reference type is copied by reference and its storage is reclaimed by the GC. Where the bytes sit is the runtime's business, and the runtime has changed its mind about it twice in the last two releases.

**The stack you are actually spending**

The stack is not free-form space; it is a fixed reservation made when the thread was created, and you cannot grow it from managed code.

- On **Windows** the default is the reservation baked into the executable's PE header by the linker, which is 1 MB unless changed.
- On **Linux** the main thread's stack comes from the process limit (`ulimit -s`, commonly 8 MB). CoreCLR uses a smaller fixed default on Alpine/musl. This asymmetry is why "it overflowed only in the container" is a real bug report.
- The runtime honours a hex-valued `DOTNET_DefaultStackSize` (historically `COMPlus_DefaultStackSize`) for threads it creates.
- For a thread you create yourself, `new Thread(work, maxStackSize)` takes an explicit size; the documented meaning of `0` is "use the default in the executable's header".
- **You cannot set the stack size of a thread-pool thread**, and in ASP.NET Core your request runs on one. So the stack budget for a request handler is whatever the pool's threads were created with, minus everything the middleware pipeline has already pushed onto it.

That last point is the one that matters for `stackalloc` and for recursion, and it is why the `stackalloc` guidance further down this page is expressed as a small constant rather than "whatever fits".

> 🌍 **In the real world**: an expression evaluator parses user-supplied filter strings recursively. It has a unit test with a 5,000-term expression that passes on every developer machine and in CI, both Linux with an 8 MB `ulimit -s`, running on the test host's main thread. In production the same input arrives on an ASP.NET Core request — a thread-pool thread on an Alpine-based image, with a middleware pipeline already several hundred frames deep — and the pod dies with no exception, no log, and an exit code the orchestrator reports as a crash. Nothing was wrong with the algorithm and nothing was wrong with the test. **The test measured a different stack.** The durable lesson: recursion depth and `stackalloc` size are properties of the *thread you happen to be on*, and the thread you are on in production is the one you have the least control over. The fix that shipped was an explicit depth limit that returns a 400, not a bigger stack.

### GC fundamentals — generations, LOH, POH

The .NET GC is **generational**, **tracing**, and — for gen 0/1/2 — **compacting** (the LOH is swept rather than compacted by default, which is the source of its fragmentation problem). Allocations land in a generation; survivors are *promoted* to older generations. The win is that a young collection traces only the young region plus whatever the write barrier has marked as dirty, so the vast majority of a long-lived heap is never touched. Note the phrasing: the collector traces *reachable* objects and reclaims everything else — it never enumerates the garbage, which is why the cost of a collection scales with **live** data, not with how much you allocated.

**The five regions** (.NET 5+):

| Region | What lands here | Collection cost | How often |
|---|---|---|---|
| **Gen 0** | New small-object allocations (`< 85,000 B`) | Cheapest — only the Gen 0 region is traced | Most frequent; triggered by the Gen 0 allocation budget filling |
| **Gen 1** | Survivors of one Gen 0 collection | Still cheap — Gen 0 + Gen 1 traced | Less often than Gen 0 |
| **Gen 2** | Survivors of two collections (long-lived objects, statics, caches) | Most expensive — the whole heap is traced | Rarest; the one that shows up in tail latency |
| **LOH** (Large Object Heap) | Single allocations `≥ 85,000 B` | Expensive (traced and reclaimed with Gen 2) | Collected only on Gen 2 |
| **POH** (Pinned Object Heap, .NET 5+) | Objects allocated via `GC.AllocateArray<T>(len, pinned: true)` | Collected with Gen 2, but never moves | Rare |

**What actually drives collection frequency**

Don't memorise numbers here — they are per-process, and the runtime retunes them at runtime. Memorise the causal chain instead:

- **Gen 0 fires when the Gen 0 allocation budget is exhausted**, not on a timer. The budget is dynamic: the GC raises and lowers it based on survival rate and (under DATAS) on the size of the long-lived data. So "how often does Gen 0 run" is a function of *your allocation rate*, which is the number you actually control.
- **Gen 1 fires when Gen 1's budget fills with Gen 0 survivors.** More survivors per Gen 0 means more promotion means more Gen 1.
- **Gen 2 fires on budget exhaustion, on memory-load pressure, and on explicit `GC.Collect`.** It traces everything, so its pause scales with *live* heap size — not with allocation rate. This is why a large cache makes every full GC more expensive even if the cache itself is never touched.
- **LOH allocations are gen-2 allocations.** Every 85 KB+ buffer you allocate is a direct vote for a more frequent, more expensive full GC.

The one number worth internalising is a *ratio*, not an absolute: the fraction of wall-clock time the process spends paused. The runtime computes it for you — see `GCMemoryInfo.PauseTimePercentage` and `GC.GetTotalPauseDuration()` in the measurement section.

**Why the 85,000-byte LOH threshold?**

1. **Copying cost** — the GC reclaims Gen 0/1/2 with a **compacting** algorithm: it copies surviving objects to remove holes. Past some size, moving the object costs more than tolerating the hole, so the LOH is swept rather than compacted by default.
2. **The number itself was chosen by measurement, not derivation.** Microsoft's documentation says only that objects at or above this size are treated as large; there is no elegant reason behind 85,000, and an interviewer asking "why that number" is usually testing whether you'll invent one. The honest answer — "empirically tuned, and configurable" — is the better answer.
3. **It *is* configurable, upward.** `System.GC.LOHThreshold` in `runtimeconfig.json` (or `DOTNET_GCLOHThreshold` as a hex env var) has existed since .NET Core 3.0. The value must be **larger** than the default and may be capped by the runtime; read back what you actually got with `GC.GetConfigurationVariables()`. Raising it is a real tactic for a service whose natural buffer size sits just above 85 KB — but it makes those buffers compactable and copied, so it is a trade, not a free win.

**LOH consequences**:

- **No compaction by default** (you can opt in with `GCSettings.LargeObjectHeapCompactionMode = CompactOnce` then trigger a Gen 2 collection — expensive, use sparingly).
- **Fragmentation** — repeatedly allocating/freeing differently-sized big objects leaves holes the GC can't reuse efficiently.
- **Gen 2 pressure** — every LOH allocation is essentially a Gen 2 allocation; bulk LOH activity drives Gen 2 collection frequency up.

> 🌍 **In the real world**: an export endpoint reads a file with `File.ReadAllBytes` and hands the array to a hashing routine. Files are typically 40 KB, so nothing looks wrong. Then a customer uploads 300 KB files and the service starts doing full GCs during business hours. Nobody wrote a "large object" — they wrote `ReadAllBytes`, and the size came from a customer. The general shape: **LOH pressure is usually inherited from input, not authored**, which is why it shows up in production and not in the load test with the synthetic 10 KB fixture.

**Regions, not segments (.NET 7+)**

Older material — and older interviewers — describe the GC heap as a set of large **segments** (on the order of hundreds of MB reserved per heap). Starting in **.NET 7**, the GC heap switched its physical representation from segments to **regions** on 64-bit Windows and Linux. This is worth knowing because it changes what several older recommendations mean:

- A region is **4 MB for the small object heap** by default; **UOH** (LOH + POH) regions are eight times the SOH region size. Tunable via `System.GC.RegionSize` / `DOTNET_GCRegionSize`, though the docs' advice is that most apps shouldn't.
- At startup the GC **reserves** — not commits — a large virtual range for regions. With no other configuration and no memory constraint, that reservation is 256 GB (larger on machines with more than 256 GB of RAM). Reserved virtual address space is not memory in use; a monitoring dashboard that alarms on virtual size will page you for nothing.
- Because regions are small and individually decommittable, the GC can **return memory to the OS at a much finer granularity** than a segment allowed. That is what makes DATAS (below) practicable at all.
- Consequence for advice you may have inherited: `System.GC.RetainVM` ("put segments on a standby list instead of releasing them") is a segment-era knob whose default is `false`, and it is not the general-purpose throughput switch it was sometimes presented as.

**Write barriers and card tables — why storing a reference costs more than storing an `int`**

This is the mechanism behind generational GC, and the one senior candidates most often can't explain.

The generational trick only works if a Gen 0 collection can avoid tracing Gen 2. But a Gen 2 object can hold a reference to a Gen 0 object (`_cache[key] = newlyAllocatedItem;`), and that Gen 0 object must not be collected. Tracing all of Gen 2 to find such references would defeat the entire design.

The runtime's answer: **every write of a reference into a heap field goes through a write barrier** — a small snippet of code the JIT emits at the assignment site. The barrier records that a region of the older heap has been dirtied, in a side structure called the **card table**. At collection time the GC traces the young generations plus only the dirty cards, instead of all of Gen 2.

```csharp
class Node { public Node? Next; public int Value; }

node.Value = 42;      // plain store — no barrier
node.Next  = other;   // reference store — JIT emits a write barrier here
```

Three practical consequences:

1. **Reference-typed fields are more expensive to write than value-typed ones**, everywhere, not just in hot loops. This is one real argument for storing an index or an id instead of an object reference in a large, frequently-mutated structure.
2. **Arrays of structs beat arrays of classes twice over** — no per-element object header, and no write barrier when you assign the elements (assuming the struct itself holds no references).
3. **The barrier implementation is a tuning surface for the runtime team.** .NET 10 brought the dynamically-switchable write-barrier implementation to Arm64, with a default that models GC regions more precisely — trading a little write throughput for shorter collections. It's a good example to cite when asked "what has actually changed in the GC recently".

**Pinned Object Heap (POH, .NET 5+)**

Before POH, pinning an object via `fixed (byte* p = arr)` or `GCHandle.Alloc(arr, GCHandleType.Pinned)` left the object **in its current generation** — typically Gen 0 — but marked it un-moveable. This blocks compaction during the next collection, leaving holes around the pinned object: **heap fragmentation**.

POH separates pinned allocations into their own region from day one. The GC knows nothing in POH will ever move, so it doesn't try to compact around it.

```csharp
// .NET 5+ — allocate directly into POH
byte[] buffer = GC.AllocateArray<byte>(length: 1024, pinned: true);

// Sibling API, NOT a ref-type variant: skips the zero-fill.
// Caveats worth knowing, straight from the CoreLib source:
//   - if T is (or contains) a reference type, it falls back to `new T[length]`
//     and you get zero-init anyway — the GC must see valid references;
//   - unpinned requests smaller than 2048 bytes also fall back to `new T[length]`,
//     because below that the zero-fill is cheaper than the slow-path call;
//   - pinned requests always take the uninitialized path.
// So the returned buffer may contain arbitrary bytes. Overwrite before reading.
byte[] fast = GC.AllocateUninitializedArray<byte>(length: 4096, pinned: true);

// Note on the pinned overload: the documented restriction is version-gated —
// "In .NET 7 and earlier versions: if pinned is set to true, T must not be a
// reference type or a type that contains object references."

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

**What keeps an object alive — the root set**

Everything above describes how the collector *reclaims*. This is the other half: how it decides what not to reclaim. A tracing collector starts from a set of **roots** and marks everything reachable; unreachable is a synonym for garbage. So every "memory leak" in .NET is really the same question — *what is still pointing at this?* — and being able to enumerate the root set is what lets you answer it.

The roots are:

| Root | Where it comes from |
|---|---|
| **Stack slots and registers of every thread** | Live locals, as reported by the JIT's GC info for the exact instruction pointer |
| **Static fields** | One set per type — per *closed* generic type for generics — alive for the life of the load context. `[ThreadStatic]` gives one per thread |
| **GC handles** | `GCHandleType.Normal` (a strong reference held outside the heap), `Pinned` (strong *and* immovable), and the weak variants below |
| **The finalization queue** | An object with a pending finalizer is reachable until the finalizer thread has run it — which is why a finalizer extends lifetime rather than shortening it |
| **Runtime-internal structures** | Loaded types, interned string literals, and the execution context — `AsyncLocal` values are reachable from every live async operation that flowed them |

Two consequences that are worth stating precisely, because interviewers use them as the follow-up.

**1. Liveness is what the JIT can prove, not what your braces say.** An object becomes collectable at the last instruction that actually reads it, not at the closing brace of its scope. In Release code the JIT reports a local as dead once nothing reads it again, so **an object can be finalized while one of its own instance methods is still executing**, and a delegate passed to native code can be collected while native code still holds the function pointer. That is exactly the scenario `GC.KeepAlive` exists for: the docs describe it as ensuring "the existence of a reference to an object that is at risk of being prematurely reclaimed", for the case where "there are no references to the object in managed code or data, but the object is still in use in unmanaged code". Its own example is a `SetConsoleCtrlHandler` delegate, kept alive by a `GC.KeepAlive(hr)` placed at the *end* of the range where the delegate must survive — "code this method at the end, not the beginning".

```csharp
var handler = new NativeCallback(OnEvent);
Native.Register(handler);          // native side stores the function pointer
// ... nothing in managed code reads 'handler' again ...
GC.KeepAlive(handler);             // ← without this, 'handler' may already be gone
```

In practice the better answer is "hold it in a field, or use `SafeHandle`" — `GC.KeepAlive` is the fix for code you cannot restructure.

**2. There is a whole family of *weak* roots, and choosing among them is a design decision.**

| Primitive | Semantics |
|---|---|
| `WeakReference<T>` (`trackResurrection: false`, the default) | A **short** weak reference. Cleared as soon as the object is collected — you never observe a finalized object through it |
| `WeakReference<T>(target, trackResurrection: true)` | A **long** weak reference. Survives until the object's memory is actually reclaimed, so the target may be an object whose finalizer has already run. Rarely what you want |
| `ConditionalWeakTable<TKey, TValue>` | Holds the **key weakly** and keeps the value alive only for as long as the key is alive. The way to attach state to objects you don't own without rooting them — and unlike a `Dictionary`, a value that references its own key does not leak the pair |
| `System.Runtime.DependentHandle` (.NET 6+, public) | The primitive `ConditionalWeakTable` is built on: a weak reference to a target plus a dependent that is kept alive as long as the target is |

**The managed leak taxonomy** — in a managed process there is no leak in the C sense; there is *unintended retention*, and it comes from a short list:

1. **A static collection that only ever grows** — a cache with no eviction, a `ConcurrentDictionary` used as a memo table keyed by something unbounded. This is the most common one by a wide margin.
2. **An event whose subscribers never unsubscribe.** `publisher.Changed += handler` puts a strong reference to the *subscriber* in the publisher's invocation list. A long-lived publisher therefore roots every short-lived subscriber that ever attached.
3. **A captured closure held by something long-lived** — a registered callback, a `Timer`, a `CancellationToken.Register` that is never disposed. The display class roots everything else captured in that scope, per the closure rules above.
4. **A pooled buffer of reference type returned without `clearArray: true`** — the pool becomes the root, as described under `ArrayPool<T>`.
5. **A pending finalizer that can't run** — a blocked finalizer thread means every finalizable object behind it stays reachable.

**How to find it, in the order you'd actually do it**

The tool that answers "who references this" is not a profiler you have to install:

```
# Snapshot the object graph of a LIVE process. Triggers a GC, reconstructs the
# graph from EventPipe events — low overhead, safe under load.
dotnet-gcdump collect -p <pid>       # take one, wait under steady load, take another
                                     # then diff the two in Visual Studio or PerfView

# Full dump when you need more than the graph (stacks, native state, sync blocks)
dotnet-dump collect -p <pid>
dotnet-dump analyze core_dump
  > dumpheap -stat                   # what is on the heap, by type and total bytes
  > dumpheap -type OrderDto          # addresses of instances of the suspect type
  > gcroot <address>                 # THE command: the reference path back to a root
  > gchandles                        # strong/pinned handle counts — interop retention
  > finalizequeue                    # is the finalizer thread keeping things alive?
  > eeheap -gc                       # generation and region layout
```

The discipline that makes this fast: **compare two snapshots rather than staring at one.** A single heap dump of a healthy service also contains millions of objects. What identifies a leak is the *delta* between two dumps taken under the same load, and then exactly one `gcroot` on one instance of the type that grew. Both tools see managed memory only — if the heap is flat and RSS is climbing, you are in native memory and this workflow will tell you nothing.

> 🌍 **In the real world**: a singleton configuration service exposes `event Action<Config> Changed`, and a scoped request-handling class subscribes in its constructor. Nobody unsubscribes, because nobody thought of the subscription as a resource. The heap grows linearly with total requests served, forever; Gen 2 grows with it, so full GCs get slower and slower over a deployment's lifetime and the pod is "fixed" by the weekly restart that everyone has stopped noticing. Two gcdumps an hour apart showed the handler's declaring type multiplying; one `gcroot` showed the path — static singleton → event field → `Action` invocation list → each subscriber. The fix is `-=` in `Dispose`, and the design fix is to not have a singleton publish to scoped subscribers at all. The transferable sentence: **`+=` is an assignment into a field owned by the publisher, and the publisher's lifetime is now your lifetime.**

> 🌍 **In the real world**: a service adds a `static readonly ConcurrentDictionary<string, ParsedQuery>` to cache parsed query strings, keyed by the raw query. It is correct, it is fast, and it is unbounded — the key space is whatever clients send. Memory climbs for days and then the pod OOM-kills. Everyone calls it a leak; it is not, it is **retention working exactly as written**. The distinction matters in an interview, because the fixes are different: a leak is fixed by dropping a reference, unbounded retention is fixed by choosing an eviction policy (`MemoryCache` with a size limit and `SetSize` on entries, or an LRU). The question that separates the two is "if I stop the load, does it go back down?"

> 🌍 **In the real world**: an interop wrapper registers a managed callback with a native audio library and passes the delegate directly into the P/Invoke. It runs fine for hours in testing and crashes intermittently in production with a native access violation and no managed stack. The delegate was a local, never referenced again after registration, and the GC — correctly — collected it while the native library still held its function pointer. This is not a race in the usual sense and no amount of locking helps. The fixes, in order of preference: store the delegate in a field of an object with the right lifetime; keep a `GCHandle` and free it on teardown; or `GC.KeepAlive` at the end of the range. The general lesson worth carrying: **the moment a reference leaves managed code, the GC stops being able to see it, and lifetime becomes your problem.**

### Workstation vs Server GC; concurrent vs background

Two orthogonal axes control GC behavior. **They're set at process start** via the `.runtimeconfig.json` or environment variables and **cannot be changed after the process is running**.

**Workstation vs Server**

| | Workstation GC | Server GC |
|---|---|---|
| Heap layout | One heap, shared | One heap **per logical CPU** |
| GC threads | Same as user thread (stop-the-world on one thread) | Dedicated GC thread per heap, runs in parallel |
| Allocation throughput | Lower (single heap = contention) | Much higher (per-CPU heaps, near-zero contention) |
| Pause time | Often higher (single-threaded mark/sweep) | Lower per pause (parallel mark/sweep across heaps) |
| Memory footprint | Smaller | Larger (a heap and an allocation budget per CPU) |
| Default for | Console apps, desktop, libraries | **ASP.NET Core**, services |

The precise rule is worth stating precisely, because it is a favourite follow-up. Microsoft's documentation puts it two ways, and both matter:

- Workstation GC "is the default GC flavor for standalone apps. For hosted apps, for example, those hosted by ASP.NET, **the host determines the default GC flavor**" — which is why an ASP.NET Core app gets Server GC without you asking, and a console app that references the same libraries does not.
- "Workstation garbage collection is **always used on a computer that has only one logical CPU**, regardless of the configuration setting." So `<ServerGarbageCollection>true</ServerGarbageCollection>` on a 1-vCPU container is silently a no-op — a very common source of "I configured it and nothing changed".

Verify at runtime with `GCSettings.IsServerGC`. Logging it once at startup, next to the process's CPU and memory limits, converts an entire category of production mystery into a grep.

**Concurrent / Background GC**

Concurrent GC (workstation) and Background GC (server, .NET 4.5+) allow **most of a Gen 2 collection to run on a background thread** while user threads keep allocating in Gen 0. The stop-the-world phase shrinks to the brief mark roots + end-of-collection compact step.

| Mode | Setting | Effect |
|---|---|---|
| **Background GC** | `System.GC.Concurrent: true` (the default) | Gen 2 runs mostly in background; Gen 0/1 still stop-the-world but very fast |
| **Non-concurrent** | `System.GC.Concurrent: false` | All collections stop-the-world; lower latency variance but worse p99 under load |

**Config for a web service** (in `.csproj`, which the SDK writes into `runtimeconfig.json`):

```xml
<PropertyGroup>
  <ServerGarbageCollection>true</ServerGarbageCollection>
  <ConcurrentGarbageCollection>true</ConcurrentGarbageCollection>
</PropertyGroup>
```

Both of those are already the effective defaults for an ASP.NET Core app on a multi-CPU host; setting them explicitly is documentation, not tuning. Resist adding more. In particular `<RetainVMGarbageCollection>` (`System.GC.RetainVM`) defaults to `false` — release memory to the OS — and is a segment-era knob; in the regions world it is not a general throughput switch.

Or via environment variables (containers — note the runtime reads these **only at GC initialization**, so changing them on a running process does nothing):

```
DOTNET_gcServer=1
DOTNET_gcConcurrent=1
```

**Dynamic Adaptation to Application Sizes (DATAS)**

DATAS makes the Server GC heap size track the application's live data instead of the machine's CPU count — it starts with one heap and adds heaps only when the measured throughput cost of collecting justifies it. This is the fix for the classic "Server GC ate my 256 MB pod" complaint.

The version gate is the part people get wrong: DATAS was **introduced in .NET 8** and is **enabled by default starting in .NET 9**. On .NET 9 and .NET 10 you are already running it, so the realistic action is the opposite of the one usually quoted — if a throughput-sensitive service regressed on the .NET 9 upgrade, the experiment is to turn DATAS *off* and compare:

| Knob | Value |
|---|---|
| MSBuild property | `<GarbageCollectionAdaptationMode>0</GarbageCollectionAdaptationMode>` |
| `runtimeconfig.json` | `System.GC.DynamicAdaptationMode: 0` |
| Environment variable | `DOTNET_GCDynamicAdaptationMode=0` |

**Heap hard limits and containers — the mechanism behind "why does my pod OOM-kill?"**

A container memory limit is enforced by the kernel, which has no idea what a GC is. Left to itself the runtime would size its heap for the *machine*, allocate past the cgroup limit, and be killed — with no managed exception, no stack trace, and an exit code the orchestrator reports as OOMKilled. The runtime therefore reads the cgroup limit and sets a **heap hard limit**:

- `System.GC.HeapHardLimit` / `DOTNET_GCHeapHardLimit` — maximum commit size for the GC heap plus GC bookkeeping, in bytes (64-bit only).
- `System.GC.HeapHardLimitPercent` / `DOTNET_GCHeapHardLimitPercent` — the same thing as a percentage. **In a memory-limited environment the container limit is treated as total physical memory, and the default is 75%.**
- With neither set and a limit present, the documented default is **20 MB or the heap-hard-limit percent of the container limit, whichever is larger.**
- Related and separate: `System.GC.HighMemoryPercent` (`DOTNET_GCHighMemPercent`), default **90%**, is the memory-load level at which the GC switches to aggressive full compacting collections to avoid paging. In a container, "memory load" is measured against the container limit.

Two things a senior candidate should say out loud about this:

1. **The 25% that the hard limit leaves is not slack, it is the rest of your process** — native allocations, the JIT, thread stacks, buffers held by native libraries, the runtime itself. A managed heap sized at 100% of the pod limit guarantees an OOM kill.
2. **`OutOfMemoryException` and OOMKilled are different failures.** The first means the GC hit *its* limit and told you in managed code; the second means the kernel hit *its* limit and told nobody. If you only ever see the second, your managed heap is not the thing that grew.

> 🌍 **In the real world**: a service is moved from VMs to Kubernetes with a 512 MB limit and starts getting killed under load that the VMs handled comfortably. Memory dashboards show the managed heap sitting well under the limit the whole time, which is exactly why the investigation takes a week — everyone is watching the heap. The growth is in native memory held by a compression library and by thread stacks from an unbounded degree of parallelism. The durable lesson: **the GC's hard limit governs the managed heap only**, and a container limit is a budget for the whole process.

> 🌍 **In the real world**: a team sets `DOTNET_gcServer=1` in the deployment manifest for a sidecar running on a 1-vCPU pod, ships it, and reports no change. There is no bug and no typo — the runtime uses Workstation GC on a single-logical-CPU machine regardless of configuration. The tell would have been one startup log line printing `GCSettings.IsServerGC`, which is why that line is worth its cost.

**Latency modes and no-GC regions — the two knobs you can change at runtime**

Everything above is set at process start. Two things are not, and they are the interesting ones because they let you tell the GC something it cannot infer.

**`GCSettings.LatencyMode`** takes a `System.Runtime.GCLatencyMode`. The documented members and their real constraints:

| Mode | What it does | Constraint |
|---|---|---|
| `Batch` | Disables GC concurrency, collects in a batch. "The most intrusive mode… maximum throughput at the expense of responsiveness" | **Overrides the `gcConcurrent` setting** — switching to `Batch` stops further concurrent collections |
| `Interactive` | Concurrent collection while the app runs. The default | The default for workstation; for a hosted app the host's settings take precedence |
| `LowLatency` | Suppresses gen 2 entirely; only gen 0 and gen 1 run. A full collection happens anyway if the system is under memory pressure | **Not available for Server GC.** Intended for short windows only |
| `SustainedLowLatency` | Suppresses *foreground* gen 2; gen 0, gen 1, and background gen 2 still run | Available for workstation **and** server, but **not if background GC is disabled**. Docs warn it produces a larger heap and more fragmentation because it doesn't compact |
| `NoGCRegion` | Collection suspended for a critical path | **Read-only** — you cannot assign it. You enter it with `GC.TryStartNoGCRegion` and leave with `GC.EndNoGCRegion` |

**`GC.TryStartNoGCRegion(totalSize)`** is the one worth knowing in detail, because every part of its contract is a trap:

```csharp
// Ask for enough headroom to get through the critical path without a collection.
if (GC.TryStartNoGCRegion(totalSize: 16 * 1024 * 1024))
{
    try   { DoLatencyCriticalWork(); }
    finally
    {
        // Only legal if we are still IN the region.
        if (GCSettings.LatencyMode == GCLatencyMode.NoGCRegion)
            GC.EndNoGCRegion();
    }
}
else
{
    // The runtime could not commit the budget. This is a normal outcome, not an error.
    DoLatencyCriticalWork();
}
```

- It returns `bool`. **Ignoring the return value is the bug**, because a `false` means you are not in the region and the matching `EndNoGCRegion` will throw.
- The single-argument overload actually commits **2 × `totalSize`** — `totalSize` for the SOH and `totalSize` again for the LOH. Use the `(totalSize, lohSize)` overload if you care.
- `totalSize` (minus `lohSize`) **must not exceed the ephemeral segment size**, or you get `ArgumentOutOfRangeException`.
- Calls **cannot nest**; a second `TryStartNoGCRegion` while already in a region throws `InvalidOperationException`.
- `totalSize` must cover "allocations by the app, as well as allocations that the runtime makes on the app's behalf" — which you cannot enumerate by reading your own code.
- `disallowFullBlockingGC: true` is the genuinely clever overload, and the docs name the use case: a node calls it, reports itself **ready** to the load balancer if it returns `true` and **out of rotation** if it returns `false`, then does its full blocking collection while it isn't serving traffic. That is a real architecture, not a micro-optimisation.

**`GC.AddMemoryPressure` / `RemoveMemoryPressure`** solve the opposite problem: memory the GC cannot see. "The garbage collector only knows about managed memory and schedules collections based on this knowledge" — so a 200-byte managed wrapper holding a 50 MB native buffer looks free, sits in gen 2, and holds that buffer until a gen 2 collection happens to run. `AddMemoryPressure(bytes)` after the native allocation and `RemoveMemoryPressure(bytes)` after freeing it lets the runtime "trigger a gen2 GC if deemed productive". Two caveats straight from the docs, both of which are the interview follow-up:

- They "improve performance only for types that **exclusively depend on finalizers** to release the unmanaged resources. It's not necessary to use these methods in types that follow the dispose pattern." If your type is disposed properly, the pressure API buys nothing.
- "You must ensure that you remove **exactly** the amount of pressure you add. Failing to do so can adversely affect the performance of the system in applications that run for long periods of time." An unbalanced pair is a slow-acting self-inflicted GC storm.

> 🌍 **In the real world**: a trading-adjacent service wraps its order-submission path in `GC.TryStartNoGCRegion` and discards the return value, because in dev it always succeeded. In production, under load and with a larger live heap, it starts returning `false` — and now the `finally` block's unconditional `GC.EndNoGCRegion()` throws `InvalidOperationException` from inside a `finally`, replacing a latency problem with an exception that masks the original one. The fix is three lines: check the return value, guard the `End` on `GCSettings.LatencyMode == GCLatencyMode.NoGCRegion`, and treat `false` as a normal path. The framing that generalises: **`TryStartNoGCRegion` is a request, not a directive** — the `Try` prefix and the `bool` return are the API saying so, and an unchecked `Try*` call is a review comment in any codebase.

> 🌍 **In the real world**: an image-processing service decodes with a native library that allocates its pixel buffers outside the managed heap and frees them in a finalizer. The managed heap graph is flat and boring; the container's working set climbs until the kernel kills the pod. Nothing in the managed heap dump explains it, because nothing in the managed heap is the problem — each managed wrapper is a few hundred bytes and the GC has no reason to hurry. Adding `GC.AddMemoryPressure` on decode and `RemoveMemoryPressure` on release let the runtime start scheduling gen 2 collections in proportion to the memory that actually existed. The real fix, applied afterwards, was `IDisposable` plus `using` so lifetime stopped depending on the GC at all. Both are worth saying in an interview: **pressure APIs make the finalizer-based design survivable; disposal makes it correct.**

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
- Cannot be **live across** an `await` or a `yield return`. Note the version gate: through C# 12, declaring one anywhere in an `async` method or iterator was an error at all; since C# 13 the declaration is fine and only crossing the suspension point is rejected. A `ref struct` *parameter* of an `async` method is still forbidden outright.
- Cannot be boxed.
- (Pre-C# 13) cannot be a generic argument; C# 13's `allows ref struct` constraint relaxes this.

In exchange: zero allocation, near-pointer speed, safe.

**C# 14: implicit span conversions (the language finally knows about `Span<T>`)**

Until C# 13, `Span<T>` was an ordinary library type that the compiler had only narrow, special-cased knowledge of. C# 14 adds **first-class support**: new implicit conversions among `T[]`, `Span<T>`, and `ReadOnlySpan<T>`, which compose with other conversions, work for extension-method receivers, and participate in generic type inference.

Practically, this means the overload you *wanted* is now the overload you *get*:

```csharp
void Handle(ReadOnlySpan<char> value) { }

// C# 14: an array or a Span<char> flows into a ReadOnlySpan<char> parameter
// without an explicit .AsSpan(), and span-typed extension methods can be
// invoked on an array receiver.
char[] buffer = GetBuffer();
Handle(buffer);
```

Two senior-level caveats:

- **This is a language gate, not a BCL gate.** The APIs existed; what changed is the compiler's conversion rules. You need C# 14 (which ships with .NET 10) to use them, and `<LangVersion>` governs it independently of your `TargetFramework`.
- **It shifts overload resolution.** When a type offers both an array-taking and a span-taking overload, C# 14 can now pick the span one where C# 13 picked the array one. That is listed among the compiler's breaking changes for .NET 10, and it is the kind of change that turns up as a behavioural difference in a library you don't own, not a compile error in yours.

**`SearchValues<T>` — the pooling idea applied to *searching* (.NET 8+)**

`span.IndexOfAny(needles)` has to re-derive a search strategy from `needles` on every call: how many values, are they contiguous, do they fit a bitmap, can they be vectorised. `SearchValues<T>` does that analysis **once**, at construction, and hands back an immutable object you cache in a `static readonly` field.

```csharp
using System.Buffers;

// Built once, per process. The type is immutable and thread-safe.
private static readonly SearchValues<char> s_delimiters = SearchValues.Create(",;\t|");

static ReadOnlySpan<char> NextField(ReadOnlySpan<char> input)
{
    int i = input.IndexOfAny(s_delimiters);      // no re-analysis, no allocation
    return i < 0 ? input : input[..i];
}
```

Version gates, which are separate:

| API | Gate |
|---|---|
| `SearchValues.Create(ReadOnlySpan<byte>)`, `SearchValues.Create(ReadOnlySpan<char>)` | .NET 8 |
| `SearchValues.Create(ReadOnlySpan<string>, StringComparison)` → `SearchValues<string>` | .NET 9 — and only `Ordinal` or `OrdinalIgnoreCase` are accepted |

Usable with `IndexOfAny`, `IndexOfAnyExcept`, and `ContainsAny` on spans. The failure mode to name in an interview: **constructing the `SearchValues<T>` inside the hot method**, which pays the analysis on every call and is strictly worse than the plain overload. It belongs in a static field or it doesn't belong at all.

> 🌍 **In the real world**: a log-ingest service validates that a header value contains no control characters using a `Regex` compiled at startup. Replacing it with `value.AsSpan().IndexOfAnyExcept(s_allowed) >= 0` removed the regex, its match object, and its capture allocations from a path that runs on every log line. The decision that made this worth doing wasn't the speed argument — it was that the regex was a *validation* predicate that returned a bool, so nothing downstream needed the match. When the answer is "yes or no", any API that hands you an object has already lost.

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
    // Size against the WORST CASE in the destination's units, not the input's.
    // A char can encode to up to 3 UTF-8 bytes (4 for a surrogate pair), so
    // comparing input.Length against a byte threshold is a latent overflow.
    int maxBytes = Encoding.UTF8.GetMaxByteCount(input.Length);

    // Adaptive: stack for small, pool for big
    byte[]? rented = null;
    Span<byte> buffer = maxBytes <= StackThreshold
        ? stackalloc byte[StackThreshold]
        : (rented = ArrayPool<byte>.Shared.Rent(maxBytes));

    try
    {
        int written = Encoding.UTF8.GetBytes(input, buffer);
        var slice = buffer[..written];
        // ... use slice ...
    }
    finally
    {
        if (rented is not null)
            ArrayPool<byte>.Shared.Return(rented);
    }
}
```

**How the three options differ — mechanism, not multipliers**

| Allocation | What actually happens | GC pressure | Failure mode |
|---|---|---|---|
| `new byte[1024]` | Bump the Gen 0 allocation pointer, zero the memory, write an object header. Cheap per call; the cost lands later, in collection. | Consumes Gen 0 budget every call | None — it just gets slower in aggregate |
| `stackalloc byte[1024]` | Subtract from the stack pointer. No header, no GC bookkeeping, reclaimed by the epilogue. | **None** | Stack exhaustion → immediate process death |
| `ArrayPool<byte>.Shared.Rent(1024)` | Index into a bucket; take from the per-thread slot or a per-core stack; allocate only on a miss. | None once warm | Forgotten `Return`, or use-after-`Return` |

The reason not to quote a nanosecond ratio here: `new` is cheap *at the allocation site* and expensive *at collection time*, and how expensive depends on survival rate, generation, and GC flavour. A micro-benchmark of the allocation alone measures the half of the cost that doesn't matter. Measure with `[MemoryDiagnoser]` and look at the **Allocated** column, which is the input to the cost you can't see.

**`stackalloc` requires unmanaged element types** — references would create issues for the GC (which doesn't scan stack frames the same way as heap). `stackalloc string[10]` is a compile error.

> 🌍 **In the real world**: a parser used `stackalloc byte[length]` where `length` came from a length-prefix field in the wire protocol. It ran for two years. It died the first time a client sent a corrupt frame — not with an exception the middleware could catch and turn into a 400, but with the process disappearing and the orchestrator restarting the pod. The post-mortem had nothing to read, because nothing was written: a stack overflow gets no first-chance exception, no `finally`, no log flush. The one-line fix was the clamp-and-pool pattern above. The lesson worth carrying into an interview: **`stackalloc` sized from untrusted input is a remote denial-of-service, not a performance question.**

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
Memory<byte> mem = owner.Memory;        // may be LONGER than 1024 — slice it
// use mem
```

Two things about `MemoryPool<T>.Shared` that get asked as a "do you actually know this" question: it is **backed by `ArrayPool<T>.Shared`** — it is a convenience wrapper that trades an `IMemoryOwner<T>` allocation for `using`-shaped lifetime management, not a second, independent pool — and like `Rent`, `owner.Memory` is *at least* the length you asked for. Code that treats `owner.Memory.Length` as the requested length is a bug that only shows up when the bucket size differs from the request.

**How `ArrayPool<T>.Shared` is actually built**

Worth knowing because it explains every one of its rules. From the CoreLib source, the shared pool is a tiered cache:

1. **Buckets by power-of-two length**, starting at 16 elements. There are 27 of them, so the shared pool caches arrays up to 2³⁰ elements — far beyond `ArrayPool<T>.Create()`, which is a different implementation whose defaults are 1,048,576 elements per array and 50 arrays per bucket. Note the unit: **elements, not bytes**. An `ArrayPool<long>` bucket of 1,048,576 is 8 MB.
2. **A per-thread slot per bucket** (`[ThreadStatic]`), checked first and filled last. This is why a rent/return pair on the same thread is close to free and why "the pool is slow under contention" is usually a claim about a *different* pool.
3. **Per-core stacks behind that**, each with its own lock, with a thread allowed to steal from another core's stack when its own is empty.
4. **Trimming on Gen 2 collections and under memory pressure** — the pool registers a gen-2 callback, timestamps idle buffers, and lets stale ones go. A pool is not a leak; a *forgotten rental* is.

Two consequences that read as surprises if you haven't read the source:

- **`Rent` can hand you a buffer full of arbitrary bytes.** On a miss the shared pool allocates via `GC.AllocateUninitializedArray<T>` when `T` is a primitive other than `bool` — deliberately skipping the zero-fill, because "every bit pattern is valid" for those types. So the contents are not merely *a previous caller's data*, they are whatever the OS handed back. Always track how many bytes you wrote and slice to that.
- **`Return` validates the length and throws.** The array's length must exactly match a bucket size, or you get `ArgumentException` — "The buffer is not associated with this pool and may not be returned to it." So `pool.Return(new byte[1000])` throws, and so does returning a buffer you sliced-and-copied into a new array. Rent, use, return **the same reference**.

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

// Pattern 2: IMemoryOwner via using (cleaner; costs one owner object per rental)
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

The pool's rent/return path costs a bucket-index computation, a thread-static lookup, and possibly a lock — cheap, but not free, so it loses to `stackalloc` and to plain `new` for tiny one-shot buffers. The honest framing of the break-even: pooling wins when **the same code path allocates the same size often enough that the buffer stays warm in the per-thread or per-core cache**. That is a property of your traffic, not a constant, and it's the reason the sizing table above is expressed in bytes rather than in calls per second — buffer size is the part you can reason about without a profiler.

**Pool-cleared-on-return considerations**

`Return(array, clearArray: false)` is the default — fast, but the **next caller sees your old data** in the unused portion of the array. Three concerns:

1. **PII leak** — if you stored credit-card numbers, JWTs, passwords, or user data in the buffer, pass `clearArray: true` on return to zero it out (or wipe manually with `Array.Clear` before return).
2. **Security audit failure** — security review will flag any pool usage without explicit consideration of clearing. Add a comment in your code stating whether the buffer can hold sensitive data.
3. **Reference-type arrays are the case where *not* clearing is a leak — and nothing clears them for you.** Both pool implementations in CoreLib clear only when `clearArray: true` is passed; there is no automatic clearing for reference element types. So an `ArrayPool<string>` or `ArrayPool<MyDto>` buffer returned with the default keeps every element it held **reachable from the pool**, which is a GC root that lives for the life of the process. Those objects are promoted, survive every collection, and never appear in a "who references this?" chain that mentions your code. **For `ArrayPool<T>` where `T` is a reference type, `clearArray: true` is the default you should adopt.**

```csharp
// Sensitive data — always clear
ArrayPool<byte>.Shared.Return(jwtBuffer, clearArray: true);

// Non-sensitive numeric data — clear is wasted CPU
ArrayPool<int>.Shared.Return(indexBuffer, clearArray: false);

// Reference elements — clear, or the pool holds these objects alive
ArrayPool<OrderDto>.Shared.Return(dtoBuffer, clearArray: true);
```

**Diagnosing a pool that isn't pooling**

`ArrayPool<T>` reports through an EventSource named **`System.Buffers.ArrayPoolEventSource`**, which is the answer to "the pool degrades silently, how would you ever know?" It emits `BufferRented`, `BufferAllocated`, `BufferReturned`, and `BufferDropped` — and the allocate/drop events carry a *reason*:

| Event + reason | What it tells you |
|---|---|
| `BufferAllocated` / `Pooled` | Cold start: first buffer of this size. Expected, and should stop. |
| `BufferAllocated` / `PoolExhausted` | Rentals outnumber returns. Either you leak rentals, or your concurrency exceeds what the pool retains. |
| `BufferAllocated` / `OverMaximumSize` | You are renting something bigger than the pool will cache — every call allocates. |
| `BufferDropped` / `Full` | Returns outnumber rentals for that size; the pool is discarding. Usually harmless. |

Collect it with `dotnet-trace collect --providers System.Buffers.ArrayPoolEventSource -p <pid>`. A steady stream of `PoolExhausted` under load is the signature of a missing `Return` on an exception path, and it is far faster to find this way than by staring at an allocation profile full of `byte[]`.

> 🌍 **In the real world**: a gateway rents a buffer, writes the upstream response into it, and returns it in a `finally`. Under load a small number of requests start returning **corrupted** bodies — bytes from a different tenant's response. There is no race in the writing code. The bug is a `catch` block, added months earlier for a timeout case, that returns the buffer to the pool and then lets the outer `finally` return it *again*. The array is now in the pool twice; two threads rent the same array and write to it concurrently. This is a **double-free**, and Microsoft's own documentation is unusually blunt about it: "Returning the same array reference twice or continuing to use the array reference after it has been returned is a high-severity security issue." Pooling moves a class of bug from "impossible in managed code" back onto the table, which is exactly why the null-out-before-return discipline below exists.

**Pooling *objects*, not buffers — `ObjectPool<T>`**

`ArrayPool<T>` pools arrays. When the expensive thing is an object's *initialization* rather than its size, the ASP.NET Core stack ships `Microsoft.Extensions.ObjectPool`:

```csharp
using Microsoft.Extensions.ObjectPool;

// A pooled type that knows how to reset itself.
public sealed class ScratchBuffer : IResettable
{
    public byte[] Data { get; } = new byte[64 * 1024];
    public bool TryReset() { Array.Clear(Data); return true; }   // false => don't pool me
}

builder.Services.TryAddSingleton<ObjectPoolProvider, DefaultObjectPoolProvider>();
builder.Services.TryAddSingleton<ObjectPool<ScratchBuffer>>(sp =>
    sp.GetRequiredService<ObjectPoolProvider>()
      .Create(new DefaultPooledObjectPolicy<ScratchBuffer>()));

// At the call site
var scratch = pool.Get();
try { /* use scratch */ }
finally { pool.Return(scratch); }   // TryReset() runs here because of IResettable
```

The pieces: `ObjectPool<T>` (`Get`/`Return`), `ObjectPoolProvider` / `DefaultObjectPoolProvider` (factory, DI-registered), `PooledObjectPolicy<T>` (how to create and how to reset, for types you don't control), and `IResettable.TryReset()` (how a type resets *itself*; returning `false` means "I'm not in a reusable state, drop me").

Three facts the docs state that answer the usual interview follow-ups:

- **The pool bounds what it *retains*, not what it *allocates*.** Under a burst, `Get` will happily construct new instances; the limit only governs how many are kept. So it cannot be used as a concurrency limiter.
- **There is no requirement to return.** An un-returned object is simply garbage-collected — which makes `ObjectPool<T>` strictly safer than `ArrayPool<T>` on the exception path, at the cost of a silent loss of the benefit.
- **Disposal has defined semantics.** With `DefaultObjectPoolProvider` and a `T` that implements `IDisposable`: items not returned to the pool get disposed, disposing the pool disposes its contents, `Get` after disposal throws `ObjectDisposedException`, and `Return` after disposal disposes the item.

And the guidance Microsoft leads with, which is the right note to end on: "Unless the initialization cost of an object is high, it's usually slower to get the object from the pool." Pooling a cheap object is a pure loss plus a lifetime bug waiting to happen.

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

- The method **usually completes synchronously** — the common case hits a cache or an early-exit and never awaits anything.
- The method is on a **hot path** (called often enough that a per-call object matters).
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

**What an `async` method actually allocates — and why `ValueTask` alone doesn't fix it**

This is the follow-up that separates people who have read the lowering from people who have read a blog post. `ValueTask` removes the *Task* allocation. It does not remove the *state machine* allocation, and on a path that genuinely goes async, the state machine is the bigger object.

The compiler rewrites an `async` method into a state machine type holding every local that lives across an `await`. In Release builds that type is a **struct**, and it lives on the caller's stack — for as long as the method completes synchronously. The moment the method actually suspends, the builder must **box that struct onto the heap** so it can survive the return, and it allocates the machinery to resume it.

So the allocation profile of an `async` method has two regimes:

| Path taken | What gets allocated |
|---|---|
| Completes without ever suspending | Nothing for the state machine (struct stays on the stack). `Task` still allocates unless you return `ValueTask`. |
| Suspends at least once | The boxed state machine, plus the returned object |

Consequences that are worth saying in an interview:

1. **`async` on a method with no `await` on the hot path is not free-but-wasteful, it is genuinely free** — which is why the "fast path" idiom exists: a non-`async` outer method that checks the cache and returns `new ValueTask<T>(value)`, delegating to a private `async` method only when it must actually wait.
2. **Every local you keep alive across an `await` widens the state machine**, and therefore the box. Large structs, several `Span`-shaped buffers turned into arrays "because Span can't cross await" — these all land in one heap object with a Gen 0 lifetime that is as long as the I/O.
3. **`ConfigureAwait(false)` is not an allocation optimization.** It changes capture of the synchronization context. People conflate the two constantly.

For the rare case where a hot async method suspends on *most* calls and you still want the state machine pooled, .NET 6 added an opt-in builder:

```csharp
using System.Runtime.CompilerServices;

// Opt this method's state machine into pooling. Applies per method.
[AsyncMethodBuilder(typeof(PoolingAsyncValueTaskMethodBuilder<>))]
public async ValueTask<int> ReadChunkAsync(Stream s, Memory<byte> buffer)
{
    return await s.ReadAsync(buffer);
}
```

`PoolingAsyncValueTaskMethodBuilder` / `PoolingAsyncValueTaskMethodBuilder<TResult>` (both `System.Runtime.CompilerServices`, .NET 6+) reuse the state-machine object instead of allocating one per suspension. The catch is that it makes the `ValueTask` rules *load-bearing rather than advisory* — the returned `ValueTask` is now backed by a pooled, single-use source, so awaiting twice is no longer "may misbehave", it is reading from an object someone else owns. Reach for it only with a measurement in hand.

> 🌍 **In the real world**: a repository method is changed from `Task<Order>` to `ValueTask<Order>` across a codebase because "ValueTask is faster". Allocation per request barely moves — the method hits the database on almost every call, so the state machine box and the `IValueTaskSource` were always the cost, and the `Task` object was noise. What *does* change is that a caller who was doing `var t = repo.GetAsync(id); await Log(t); return await t;` now has undefined behaviour. The team traded a real correctness hazard for a benefit they never measured. `ValueTask` earns its keep on the *cache-hit* shape; applying it uniformly is cargo cult with sharp edges.

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

**Detection**: two Roslyn IDE analyzers cover the two granularities — `IDE0250` ("Make struct `readonly`") for the whole type and `IDE0251` ("Make member `readonly`") for individual members you can't make the whole type immutable for. Also visible in IL: look for a `dup`/`stloc`/`ldloca` sequence right before the method call.

**Practical impact**

State the mechanism, not a multiplier. Each defensive copy is a `memcpy` of `sizeof(T)` bytes plus a stack slot to hold the copy. The cost therefore scales with the struct's size and with how many times per iteration you touch it — and *every* property read is a separate copy, so a loop body that reads four properties pays four copies, not one. It also blocks optimizations rather than merely adding work: a hidden copy in the loop body is an aliasing wall the JIT has to respect, so hoisting and vectorization stop.

The reason this is worth an interview answer at all is the shape of the fix: it is a **keyword**, applied to a type declaration, with no call-site changes and no behavioural change. There are very few of those.

**Properties that cause defensive copies on a non-readonly struct**:

- Calling **any non-`readonly` instance method**.
- Reading **any property** (properties are method calls).
- Passing the struct to another `in` parameter.
- Calling interface methods (even if the struct implements the interface — boxes too).

**The fixes** (in priority order):

1. **Make the struct `readonly struct`** — eliminates all defensive copies for instance method calls.
2. If full `readonly` is impossible, mark individual members `readonly`: `public readonly double Magnitude() => ...;` (C# 8+). The method promises it won't mutate `this`.
3. Use `ref readonly` returns and parameters consistently for large structs.
4. For large structs, question whether it should be a struct at all. Microsoft's framework design guidelines put the boundary at "an instance size under 16 bytes" — above that, and absent the immutability and short-lifetime conditions the guideline also lists, the copies start costing more than the one heap allocation a class would have paid.

**`readonly struct` guarantees**:

```
✓ All instance fields are readonly (compile-enforced)
✓ All instance properties are get-only or {init}
✓ No mutating methods — every instance method is implicitly readonly
✓ Compiler will not emit defensive copies for in-parameters or ref-readonly returns
✓ Safe to use as a dictionary key (hash code can't change)
```

> 🌍 **In the real world**: a pricing engine models money as `struct Money { decimal Amount; string Currency; }` — not `readonly`, because someone needed to fix up the currency once, years ago. The valuation loop iterates a `Money[]` and reads `.Amount` and `.Currency` through an `in` parameter. Every read copies the whole struct, because a plain `struct`'s property getter *might* mutate `this` and the compiler has to assume it does. Nobody wrote a copy; the copies are in the codegen. The fix was `readonly struct` plus making the one mutation return a new value — a two-line change that nothing else in the codebase noticed. The reason to remember this case: the smell was not "this is slow", it was **a mutable struct that is treated as a value everywhere it is used**. That mismatch is what generates the copies, and you can see it in review without a profiler.

> 🌍 **In the real world**: the mirror-image failure. A team hears "structs avoid allocation" and converts a 200-byte DTO from `class` to `struct`. Allocation goes down; throughput goes down with it. The object was being passed through six layers, stored in a `List<T>`, and returned from an interface method — so every hop copied 200 bytes, the `List<T>` indexer returned copies that mutations were silently applied to and lost, and the interface call boxed it right back onto the heap. **`struct` is not "class without allocation"; it is a different assignment semantics that happens to avoid allocation.** If the type is passed around rather than computed with, the copies find you.

> 🌍 **In the real world**: mutable structs in collections produce a bug the compiler catches in the obvious shapes and misses in the one people actually write. `dict[key].Count++` and mutating a `foreach` variable both fail to compile — the first because you can't modify the return value of an indexer, the second because a `foreach` iteration variable is read-only. So the developer does the thing the compiler accepts: `var v = dict[key]; v.Count++;`. That copies, increments the copy, and discards it. Clean build, passing type checker, silently wrong. The durable rule: **if a struct is mutable and lives in a collection, every read gives you a copy, and "it compiled" tells you nothing.** Make it a `readonly struct` and mutate by replacement, or reach for `CollectionsMarshal.GetValueRefOrNullRef` below to get a genuine reference to the slot.

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

What you save is one hash computation and one bucket probe per update, plus — for a large `TValue` struct — the copy out and the copy back in. The second saving is the one that grows with your type; the first is fixed.

For the "add if missing" half of the pattern there is a companion that removes the second lookup too:

```csharp
// .NET 6+: one lookup, inserts a default entry if the key was absent.
ref int count = ref CollectionsMarshal.GetValueRefOrAddDefault(counts, key, out bool existed);
count++;                      // works for both the found and the just-added case
```

**Similar utilities** (each has its own version gate):

| API | Gate | What it gives you |
|---|---|---|
| `CollectionsMarshal.AsSpan(List<T>)` | .NET 5 | `Span<T>` over the list's backing array — indexer-free, bounds-check-hoisted loops |
| `CollectionsMarshal.GetValueRefOrNullRef(dict, key)` | .NET 6 | `ref TValue` to the bucket, or a null ref |
| `CollectionsMarshal.GetValueRefOrAddDefault(dict, key, out bool)` | .NET 6 | Same, inserting when absent |
| `CollectionsMarshal.SetCount(List<T>, int)` | .NET 8 | Set `Count` directly, then fill via `AsSpan` — skips `Add`'s per-element work |
| `MemoryMarshal.GetReference(span)` | .NET Core 2.1 | `ref T` to `span[0]` for low-level loops |
| `Unsafe.Add(ref T, int)` | .NET Core 2.1 | Pointer arithmetic on managed references |

**The safety contract you are opting out of**

Everything in `CollectionsMarshal` lives in `System.Runtime.InteropServices` for a reason: the returned reference is **only valid until the collection changes shape.** Any `Add`, `Remove`, `Clear`, or resize can reallocate the backing array, at which point your `ref` points at an array the GC is free to collect — you are writing into a detached object, and nothing throws. `SetCount` is sharper still: it can *expose uninitialized elements* if you grow the list and read before writing. The rule to state: **acquire the ref, use it, drop it, and do not touch the collection in between.**

**`scoped` and ref safety (C# 11+)**

The compiler tracks a *ref-safe-to-escape* lifetime for every `ref` and `ref struct`, and it errs toward assuming a parameter's reference could escape through the return value. Two keywords let you correct it in each direction:

```csharp
// 'scoped' narrows the lifetime: promises this reference does NOT escape,
// which lets callers pass a reference to stack data they couldn't otherwise.
static int Sum(scoped ReadOnlySpan<int> values) { /* ... */ }

// [UnscopedRef] widens it: on a struct member, says the returned ref to a field
// may outlive the method — needed for things like a struct exposing 'ref this.Item'.
[UnscopedRef] public ref int First() => ref _items[0];
```

`scoped` is the one you will actually write, and usually because the compiler asked for it: you took a `ref struct` parameter, returned something derived from it, and got a lifetime error you didn't understand. C# 14 additionally allows `scoped`, `ref`, `in`, `out`, and `ref readonly` on **implicitly typed lambda parameters**, so these modifiers no longer force you to spell out every lambda parameter type.

**When to reach for `ref`**:

- Hot loops mutating dictionary values, list elements, or array slots — `ref` saves the re-lookup.
- Passing large structs through method chains — avoid copies.
- Building span-based algorithms that need to write into the underlying memory.

For ordinary application code, `ref` returns are overkill. They earn their keep in framework code, parsers, serializers, math libraries.

> 🌍 **In the real world**: a metrics aggregator counts events into a `Dictionary<string, Counter>` where `Counter` is a struct with several fields. The original code did `TryGetValue`, mutated the local copy, then wrote it back with `dict[key] = c` — three hash lookups and two full struct copies per event. Rewritten with `GetValueRefOrAddDefault`, it became one lookup and an in-place update. The part worth remembering is what made it *safe*: the aggregator holds a lock over the whole update, so no other thread can resize the dictionary while the ref is live. Take that lock away and the same code is a use-after-free with no exception to point at it. `ref` into a collection buys speed by borrowing a guarantee the collection wasn't offering.

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
    // Safe ONLY because the async:false path contains no await, so the returned
    // ValueTask is already completed and GetResult() just rethrows any exception.
    // Blocking on a ValueTask that has actually suspended violates its contract —
    // if you must block on a genuinely async one, go through .AsTask() first.
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

> 🌍 **In the real world**: a wrapper class gets a finalizer added "for safety" during a code review, because the reviewer remembered the Dispose pattern from a book. The class owns only a `FileStream`. Nothing breaks, and the cost is invisible for a year: every instance is registered on the finalization queue at construction, survives at least one extra collection, and gets promoted; the single finalizer thread serialises the work. It surfaces during an incident as an unexplained Gen 1 population and a growing finalization queue in `!finalizequeue`. The rule that would have prevented it: **a finalizer is for a resource nothing else will release — a raw handle you own.** Owning another `IDisposable` is not that. `GCMemoryInfo.FinalizationPendingCount` is how you see this from inside the process.

> 🌍 **In the real world**: a hosted service implements `IAsyncDisposable` only, and a caller in a synchronous startup path writes `using var svc = ...`, which doesn't compile — so they write `svc.DisposeAsync().AsTask().Wait()` instead and move on. Under load, on a runtime with a saturated thread pool, that `Wait()` occupies a pool thread while the continuation it is waiting for needs a pool thread to run. The shutdown hangs. **`await using` is not sugar for `using`; the compile error that pushed the caller into sync-over-async was the design working as intended**, and the right response was to make the caller async, not to defeat the check.

### Allocation-free string building

Strings are immutable; every operation that "modifies" a string actually allocates a new one. On hot paths (logging, formatting, CSV/JSON building), string allocations dominate. The BCL has five tools, in increasing sophistication.

**The hierarchy — `string.Concat` vs `StringBuilder` vs `string.Create` vs interpolation handler vs UTF-8 literal**

| Tool | Allocations | When it wins | Notes |
|---|---|---|---|
| `a + b + c` in **one expression** | 1 (the result) | Few parts, all known | Roslyn folds the whole expression into a single `string.Concat` — there are no intermediates. See below |
| `a += b` **repeated** | 1 per `+=`, total bytes O(N²) | Never, in a loop | Each statement is a separate `Concat` over the whole accumulated string |
| `string.Concat(a, b, c)` | 1 (just the result) | Known small list of strings | Pre-counts total length, single alloc |
| `StringBuilder` | One `char[]` chunk per growth + the final `ToString` | Many parts (≥ 4), variable count, conditional | Chunks are linked, never recopied on growth — see below |
| `string.Create(len, state, span => ...)` | **1** (the result, length known) | You can compute total length ahead | Writes into the string's final char buffer |
| `$"..."` interpolation (C# 10+) | 1 (the result); the scratch buffer is pooled | Formatting values into a string at all | Lowers to `DefaultInterpolatedStringHandler`, which rents from `ArrayPool<char>.Shared` and returns it in `ToStringAndClear()`. **Not** free when the result is discarded — see the `ILogger` note below |
| `Utf8.TryWrite(span, $"...")` / `MemoryExtensions.TryWrite` | **0** | The destination is a caller-owned buffer | The handler writes straight into your `Span<byte>` / `Span<char>`; no string is ever created |
| `"text"u8` UTF-8 literal | 0 | Byte sequences known at compile time | Bytes baked into assembly metadata |

**What the `+` operator actually compiles to**

Worth getting right, because the folklore version ("`+` allocates an intermediate per operator") is wrong and an interviewer may be checking. Roslyn lowers **a whole concatenation expression** into one `string.Concat` call: `a + b + c + d` becomes `string.Concat(a, b, c, d)`, which pre-counts the total length and allocates the result exactly once. Two refinements that follow from the Roslyn implementation:

- **Value types are not boxed.** Roslyn does not emit the `object`-taking `Concat` overloads; it calls `ToString()` on value-type operands (and `?.ToString()` on reference types) and then uses the `string`-taking overloads. So `"id=" + orderId` where `orderId` is an `int` allocates the `int`'s string and the result, not a box. This is a compiler optimisation, not a language rule — check the IL if it matters.
- **Beyond four operands there is no fixed overload**, so the compiler falls back to the `params` form and you pay for the array as well. The four-string overload exists precisely so the common case avoids it.

The quadratic behaviour has nothing to do with the operator and everything to do with **statement boundaries**: `result += x` in a loop is N separate `Concat` calls, each over the entire accumulated string.

**The trap: `+=` in a hot loop**

```csharp
// ❌ N allocations whose TOTAL SIZE grows quadratically
string result = "";
for (int i = 0; i < items.Length; i++)
    result += items[i] + ",";        // each += allocates result.Length + items[i].Length + 1
```

The reason: each `result += x` allocates a new string of the *whole accumulated length* and copies the old contents into it. So the allocation count is O(N) but the bytes copied and allocated are O(N²) — iteration *i* copies everything the first *i−1* iterations produced. Two derived consequences you can state without needing a benchmark:

- **The intermediate strings cross the LOH threshold long before the final one does.** With UTF-16, 85,000 bytes is about 42,500 characters — so from that point on, every single iteration produces a large object and a direct contribution to Gen 2.
- **The peak is not the final string's size**, it is roughly the last two intermediates alive at once, which is why the memory graph shows a sawtooth rather than a ramp.

**Fix #1: `StringBuilder`**

```csharp
// ✓ Bytes allocated is linear in the output; nothing is recopied on growth
var sb = new StringBuilder(capacity: items.Length * 22);   // pre-size if known
for (int i = 0; i < items.Length; i++)
{
    sb.Append(items[i]);
    sb.Append(',');
}
string result = sb.ToString();
```

**What `StringBuilder` actually is** — worth getting right, because the usual description is wrong. It is **not** a single `char[]` that doubles and copies. In CoreLib, a `StringBuilder` is a **linked list of chunks**: fields `m_ChunkChars` (the current buffer), `m_ChunkPrevious` (the previous chunk), `m_ChunkOffset`, `m_ChunkLength`. When the current chunk fills, `ExpandByABlock` allocates a *new* chunk and relinks — the source comment reads "Move all of the data from this chunk to a new one, via a few O(1) reference adjustments." **Existing characters are never recopied on growth.**

Two constants from that source explain the behaviour you observe:

- `DefaultCapacity = 16` — a `new StringBuilder()` starts at 16 chars.
- `MaxChunkSize = 8000` — new chunks are sized `max(needed, min(currentLength, 8000))`. The cap is deliberate; the comment says it exists "so we stay in the small object heap, and never allocate really big chunks even if the string gets really big." 8,000 chars is 16,000 bytes, comfortably below the 85,000-byte LOH threshold. **`StringBuilder` is engineered to keep its own buffers out of the LOH** — the final string it produces is still a single allocation and can absolutely land there.

So pre-sizing (`new StringBuilder(estimatedSize)`) doesn't avoid "doubling churn"; it avoids **allocating a chain of chunks**, and it means `ToString()` copies from one buffer instead of walking a list. Note that a capacity you pass to the constructor is honoured directly — the 8,000-char cap applies to *growth* chunks, not to the initial one, so `new StringBuilder(200_000)` really does allocate one large-object buffer.

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

The compiler converts `$"x = {n}"` into a handler struct — a local, so it lives on the stack — plus a sequence of `AppendLiteral` / `AppendFormatted` calls. The handler's scratch buffer is **rented from `ArrayPool<char>.Shared`** and returned in `ToStringAndClear()`, so the only lasting allocation is the result string. `AppendFormatted<T>(T value)` is generic and JIT-specialised, so value-type holes are not boxed — which is the concrete improvement over `string.Format`, whose parameters are typed `object` and therefore box every value-type argument. (The boxes are the cost; `string.Format` does *not* allocate an `object[]` on top — it has non-`params` overloads for one, two, and three arguments and a `params ReadOnlySpan<object?>` overload beyond that.)

```csharp
int n = 42;
string s = $"n = {n}";
// Equivalent to (simplified):
// var handler = new DefaultInterpolatedStringHandler(literalLength: 4, formattedCount: 1);
// handler.AppendLiteral("n = ");
// handler.AppendFormatted(n);
// string s = handler.ToStringAndClear();
```

**Which APIs actually take a handler — and the one that famously does not**

The point of `[InterpolatedStringHandlerAttribute]` is that a method can accept the *pieces* of an interpolated string and decide, before formatting, whether to do the work at all. In the BCL that hook is used by:

| API | Handler | Gate |
|---|---|---|
| `StringBuilder.Append` / `AppendLine` | `StringBuilder.AppendInterpolatedStringHandler` | .NET 6 — appends straight into the builder's chunk, no intermediate string |
| `MemoryExtensions.TryWrite(Span<char>, ...)` | `TryWriteInterpolatedStringHandler` | .NET 6 — formats into a buffer you own; returns `false` instead of throwing if it doesn't fit |
| `Utf8.TryWrite(Span<byte>, ...)` | `Utf8.TryWriteInterpolatedStringHandler` | .NET 8 — same, straight to UTF-8 bytes |

**`Microsoft.Extensions.Logging` is not on that list, and this is the single most repeated piece of wrong advice in this area.** `_logger.LogInformation($"Request {id} took {ms}ms")` binds the interpolated string to the ordinary `string message` parameter. The string is therefore **built, allocated, and passed even when the level is disabled** — the logger cannot short-circuit something that has already been evaluated. The API proposal to add interpolated-string-handler overloads to the `ILogger` extension methods (dotnet/runtime #111283) was **closed as not planned**, and its own problem statement is the fact worth quoting: "all of the expense associated with generating the messages are incurred even if it's then immediately thrown away".

There is a second, larger cost: interpolation destroys the **message template**, so the structured fields (`OrderId`, `Ms`) never reach the sink and the log line becomes an unqueryable string. The analyzer `CA2254` ("the logging message template should not vary between calls") exists to catch exactly this.

So the two correct forms are:

```csharp
// ✓ Message template: arguments are passed as-is, formatting happens only if the
//   level is enabled, and the sink gets structured OrderId / Ms fields.
_logger.LogInformation("Order {OrderId} completed in {Ms}ms", order.Id, elapsedMs);

// ✓✓ Source-generated: no params array, no boxing of the int, level check inlined.
[LoggerMessage(Level = LogLevel.Information, Message = "Order {OrderId} completed in {Ms}ms")]
static partial void LogCompleted(ILogger logger, int orderId, long ms);
```

Custom handlers (`[InterpolatedStringHandler]`) let *libraries* build the short-circuiting pattern — that is how a logging façade could offer it, and some third-party libraries do. It is not something `ILogger` gives you for free.

> 🌍 **In the real world**: a team reads about C# 10 interpolated string handlers and does a codebase-wide sweep replacing `_logger.LogDebug("Processing {Id}", id)` with `_logger.LogDebug($"Processing {id}")`, on the understanding that the handler will skip the work when `Debug` is off. It doesn't, because `ILogger` has no handler overload — so they added a string allocation per call on a disabled level, and simultaneously lost every structured field in their log queries. The regression showed up as a step change in allocation rate on a release whose diff contained no new features. The two things to take away: **an optimisation that depends on an overload you haven't verified exists is a guess**, and the `CA2254` analyzer would have flagged all of it at build time for the price of turning it on.

**`StringBuilder` — still relevant** for many sequential appends with unknown length: it allocates chunk buffers rather than a fresh full-length string per append. Modern code prefers `string.Create` when length is known, falling back to `StringBuilder` for variable-length building — and skips the `string` entirely when the destination is bytes, using `Utf8.TryWrite` (.NET 8+) into a pooled or stack buffer.

**The interface that makes all of this composable: `TryFormat`**

Every one of the zero-allocation paths above needs the *leaf* values — an `int`, a `Guid`, a `DateTime`, a `decimal` — to be formattable directly into a span, or the whole chain collapses back into intermediate strings. Two interfaces provide that, and knowing which is which is a good version-gating question:

| Interface | Method | Gate |
|---|---|---|
| `ISpanFormattable` | `bool TryFormat(Span<char> destination, out int charsWritten, ReadOnlySpan<char> format, IFormatProvider? provider)` | .NET 6 — implemented across the primitives, `Guid`, `DateTime`, `TimeSpan`, `decimal`, the numeric types |
| `IUtf8SpanFormattable` | `bool TryFormat(Span<byte> utf8Destination, out int bytesWritten, ...)` | .NET 8 — the same idea straight to UTF-8, skipping UTF-16 entirely |

Their parsing counterparts are `ISpanParsable<T>` / `IUtf8SpanParsable<T>` (.NET 7 / .NET 8). The practical shape: `int.TryFormat(buffer, out int written)` writes digits into your buffer and allocates nothing, where `n.ToString()` allocates a string you are about to copy and discard. When you see `Utf8JsonWriter` or a logging source generator produce no allocations for a numeric field, this is the mechanism underneath — and it is also why implementing `ISpanFormattable` (not just `ToString`) on your own value types is what lets *callers* stay allocation-free.

> 🌍 **In the real world**: the classic "an API that allocated its way into GC pressure" is not a parser or a serializer — it is logging. A service logs one structured line per request with `_logger.LogInformation("Order {OrderId} for {Customer} completed in {Ms}ms", ...)`. That is the correct, allocation-aware form. Then someone adds a debug line inside the per-item loop: `_logger.LogDebug("Processing " + item.Id + " of " + order.Id);` — string concatenation, evaluated **before** the logger is called, so the filter never gets a chance to suppress it. `Debug` is disabled in production, so the string is built, passed, and thrown away, millions of times an hour. Allocation profile: `System.String`, most of the bytes, attributed to a line that produces no output. The fix is the message-template overload — `_logger.LogDebug("Processing {ItemId} of {OrderId}", item.Id, order.Id)` — or better, a `[LoggerMessage]` source-generated method. Note what is *not* a fix: switching the concatenation to `$"Processing {item.Id}"`, because `ILogger` has no interpolated-string-handler overload and the string is built either way. The transferable point: **the cost of a log statement is paid at the call site, not at the sink**, and every argument you build eagerly is paid whether or not anyone is listening.

> 🌍 **In the real world**: a CSV export built with `string.Join(",", row)` per row looked fine in review and profiled badly, because `string.Join` over an `IEnumerable<string>` allocates an enumerator, an internal `StringBuilder`, and the joined string — per row — before the writer then copies it again into its own buffer. Writing the fields straight into the `TextWriter` removed three of the four allocations and made the row length irrelevant. The general shape: **a convenience method that returns a `string` you immediately hand to something that writes bytes is a materialization you didn't need.**

### Boxing checklist — when value types secretly allocate

**Boxing** is the runtime wrapping a value type in a heap object so it can be referenced through `object` or an interface. The size follows from object layout rather than from a benchmark: on 64-bit, every heap object carries an 8-byte object header and an 8-byte method-table pointer before its fields, and the result is rounded up to the allocation granularity — so a boxed `int` is a 24-byte object holding 4 bytes of payload. Boxing therefore costs an allocation, a copy of the struct's contents, and a permanent 16-byte-plus-padding overhead per value. In hot paths, boxing is one of the top three allocation sources after string operations and closures.

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

✓ Concatenating a value type into a string via '+' — historically, not today.
       "x = " + n   (n is an int)
         older compilers → string.Concat(object, object)   ← boxed
         Roslyn today   → string.Concat("x = ", n.ToString())  ← no box
       This is a compiler optimisation, not a language rule. Check the IL if it matters.

✓ Iterating a collection through an interface, which boxes its STRUCT enumerator.
       List<int> list = ...;
       foreach (var x in list)                  ← List<T>.Enumerator is a struct; no box
       IEnumerable<int> seq = list;
       foreach (var x in seq)                   ← GetEnumerator() returns IEnumerator<int>: BOXES
```

**The struct-enumerator case deserves its own paragraph**, because it is the one that hides behind good design. `List<T>`, `Dictionary<K,V>`, `HashSet<T>`, `Queue<T>`, `ImmutableArray<T>` and `Span<T>` all expose a **public struct `Enumerator`**, and `foreach` binds to it by pattern-matching `GetEnumerator()` on the *static* type. Typing the variable, field, or parameter as `IEnumerable<T>` throws that away: the interface implementation returns `IEnumerator<T>`, which boxes the struct.

This puts a genuine tension on the table, and being able to name both sides is the senior answer:

- Accepting `IEnumerable<T>` is the better API — it is what "depend on abstractions" means, and it is what makes the method testable and composable.
- Accepting `List<T>` or `ReadOnlySpan<T>` is the faster implementation on a hot path.

The resolution is *not* "always use the concrete type". It is: expose `IEnumerable<T>` at the boundary, and use the concrete type inside the loop that runs a million times — the same file, sometimes the same method. Note that .NET 10 narrowed the gap for one common case specifically: the JIT can now devirtualize and inline **array** interface methods, so `foreach` over an `int[]` typed as `IEnumerable<int>` no longer blocks the optimizations it used to. That is arrays, not `List<T>`, and it is a JIT optimization rather than a language guarantee.

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
| Enum passed to an `object` parameter (`string.Format("{0}", e)`, `Console.WriteLine(e)`) | `Enum.GetName<TEnum>(e)` (.NET 5+, generic — no box), or `$"{e}"`, whose `AppendFormatted<T>` is generic |
| `e.ToString()` on an enum | Unavoidable in IL: `ToString` is inherited from `System.Enum` (a class) and enums don't override it, so the receiver is boxed. On .NET 9+ the JIT *may* stack-allocate that box when it provably doesn't escape — an optimisation, not a guarantee |

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

### Data locality: object layout, padding, and cache lines

Everything up to here has been about *how many* allocations. This section is about the other half of memory performance, which is *how the bytes are arranged* — and it is the half that a candidate who has only read blog posts about `Span<T>` cannot discuss. A loop that allocates nothing can still be dominated by cache misses.

**Where the overhead comes from**

On 64-bit CoreCLR, a heap object is laid out as an **object header slot** (8 bytes, immediately *before* the object reference; the sync-block index occupies 4 of them), then a **method table pointer** (8 bytes, at offset 0 — this is what the reference actually points at), then the fields. CoreCLR's `object.h` defines a **minimum object size** of 24 bytes on x64, which is why an instance of a class with no fields at all still costs 24 bytes, and why the boxed `int` in the boxing section is a 24-byte object wrapping 4 bytes of payload. An array carries the same header plus its length, so a `byte[1]` is nowhere near one byte.

Struct fields inside a class or an array pay **none** of this — no header, no method table pointer, no per-element indirection. That is the entire structural argument for `struct` over `class` in bulk data, and it is a different argument from "avoids allocation".

**Three different answers to "how big is it"**

```csharp
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

sizeof(MyStruct)            // compile-time constant. Requires an 'unsafe' context for
                            // user-defined structs (not for the built-in primitives
                            // and enum types), and only works for unmanaged types
Unsafe.SizeOf<T>()          // the runtime's managed layout size — works for any T,
                            // and this is the one to use when you want the truth
Marshal.SizeOf<T>()         // the MARSHALLED size, i.e. how big it is after conversion
                            // for interop. Different on purpose: a 'bool' marshals to
                            // 4 bytes by default. Throws for types the marshaller
                            // can't lay out (generics, reference-containing structs)
```

Confusing the second and third is a classic: `Marshal.SizeOf` is not "the size of the struct", it is "the size of the struct as the interop marshaller will build it".

**Layout and padding are decisions the compiler makes for you, differently for structs and classes**

Microsoft's `StructLayoutAttribute` documentation is explicit: the C#, Visual Basic and C++ compilers apply **`LayoutKind.Sequential` to structs by default**, while classes default to **`LayoutKind.Auto`**, which lets the runtime reorder fields to minimise padding. So the field order you type matters for a struct and generally does not for a class. One important qualifier from the same docs: for **non-blittable** types, `Sequential` "controls the layout when the class or structure is marshaled to unmanaged code, but does not control the layout in managed memory" — so a struct containing a `string` is not guaranteed to be laid out in declaration order in the managed heap either.

Alignment then does the damage. Work the arithmetic rather than memorising a number:

```csharp
// Sequential layout, 8-byte alignment for 'long':
struct Wasteful { byte A; long B; byte C; }
//  A at 0, 7 bytes of padding, B at 8, C at 16, tail padding to a multiple of 8 → 24

struct Tidy     { long B; byte A; byte C; }
//  B at 0, A at 8, C at 9, tail padding → 16

// Or hand the problem to the runtime:
[StructLayout(LayoutKind.Auto)] struct Reordered { byte A; long B; byte C; }
```

Confirm with `Unsafe.SizeOf<T>()` rather than trusting the derivation — that is the point of having the API. The reason it matters: `Wasteful` and `Tidy` hold identical data and differ by 8 bytes per instance, so an array of a million of them differs by 8 MB, which is a third of the array. You pay for that twice, once in footprint and once in memory bandwidth on every pass over it.

**Pointer chasing: the difference between an array of structs and an array of classes**

```
Order[] orders          (Order is a CLASS)
┌────┬────┬────┬────┐
│ref │ref │ref │ref │   the array holds 8-byte references…
└─┬──┴─┬──┴─┬──┴─┬──┘
  ▼    ▼    ▼    ▼      …each pointing at a separate 24-byte-minimum heap object,
 [hdr|mt|fields]        wherever the allocator happened to put it. Every element
 [hdr|mt|fields]        access is a potential cache miss, and the prefetcher
 [hdr|mt|fields]        cannot help because the addresses aren't sequential.

OrderRow[] rows         (OrderRow is a STRUCT)
┌──────────┬──────────┬──────────┬──────────┐
│  fields  │  fields  │  fields  │  fields  │   one contiguous block. Sequential
└──────────┴──────────┴──────────┴──────────┘   access, prefetcher-friendly, no
                                                headers, no indirection.
```

This is why the write-barrier point earlier said arrays of structs win *twice over*. There is in fact a third win, specific to reference-typed arrays: because array covariance makes `string[]` assignable to `object[]`, the CLR must **type-check every reference store into an array** — that is where `ArrayTypeMismatchException` comes from, and the check is paid on stores that succeed as well as the ones that throw. The JIT elides it in the cases it can prove safe (storing `null`, or storing an element read from the same array), but in the general case a store into a `T[]` of reference type costs a covariance check *plus* a write barrier, where a store into a struct array costs neither.

**False sharing — when two threads that share nothing still contend**

Caches are coherent at the granularity of a **cache line**, not a variable. If thread A writes `counters[0]` and thread B writes `counters[1]` and both live on the same line, every write invalidates the other core's copy of that line and it ping-pongs between them. Neither thread shares data with the other; they share a line. There is no correctness bug and no lock, so nothing in the code looks wrong — throughput just fails to scale as you add threads, which is the opposite of the symptom people go looking for.

CoreLib takes this seriously enough to have a constant for it. `Internal.PaddingHelpers.CACHE_LINE_SIZE` is **64**, and **128 on ARM64** — and `ConcurrentQueue`'s segment uses it to force the head and tail counters onto separate lines:

```csharp
// dotnet/runtime, ConcurrentQueueSegment.cs — the shape, not a snippet to copy
[StructLayout(LayoutKind.Explicit, Size = 3 * Internal.PaddingHelpers.CACHE_LINE_SIZE)]
internal struct PaddedHeadAndTail
{
    [FieldOffset(1 * Internal.PaddingHelpers.CACHE_LINE_SIZE)] public int Head;
    [FieldOffset(2 * Internal.PaddingHelpers.CACHE_LINE_SIZE)] public int Tail;
}
```

Padding before, between, and after — because the neighbours on either side matter too. Note what this tells you about when to reach for it: the BCL applies padding to the two hottest concurrently-written fields in a lock-free queue, and essentially nowhere else. The cheaper fix, and the one to try first in application code, is **not to share the line at all**: accumulate into a local and publish once at the end, or give each worker its own object rather than its own slot in a shared array.

> 🌍 **In the real world**: an ingestion pipeline keeps per-worker statistics in a `long[] counts` indexed by worker id and increments with `Interlocked.Increment(ref counts[i])`. It scales beautifully to two workers and stops scaling at four; at eight, adding workers makes total throughput *worse*. There is no lock, no shared state, and no bug — eight `long`s is 64 bytes, so all eight counters sit on one or two cache lines and every increment invalidates every other core's copy. The fix that shipped was not padding: each worker accumulated into a plain local `long` and did one `Interlocked.Add` at the end of its batch, which removed the contention and the atomic operation from the hot loop together. **The interesting part for an interview is the diagnosis**, because "throughput goes down as I add cores, with no lock in the picture" has a very short list of causes and false sharing is at the top of it.

> 🌍 **In the real world**: a telemetry aggregator holds an hour of samples as `List<Sample>` where `Sample` is a `class` with four numeric fields. The aggregation pass is a simple loop with no allocation at all, and it is slow in a way that no allocation profiler explains. The heap holds a million small objects, each with 16 bytes of header, each at whatever address the allocator handed out an hour ago and each reached through a separate dereference — the loop is bound by memory latency, not arithmetic. Converting `Sample` to a `readonly record struct` and the container to a `Sample[]` made the pass one sequential scan over one contiguous block, removed the per-object headers, and removed the write barrier from every store. The decision was safe *because* of the properties the type already had: small, immutable, value-like, and never used polymorphically. **Convert to a struct for locality, not for allocation** — and only when those four conditions hold, or you get the copy problems described in the defensive-copy section instead.

### `unsafe` and pointers

`unsafe` blocks let you use C-style pointers (`int*`, `byte*`), pin GC objects (`fixed`), and do pointer arithmetic. With `Span<T>` and `MemoryMarshal` covering the patterns that used to require it, `unsafe` is rarely the right tool anymore — but knowing it exists matters for interop and BCL reading.

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
| Scanning for the same character/byte set repeatedly | `static readonly SearchValues<T>` (.NET 8+) | plain `IndexOfAny` if the set varies |
| Reusing an object that is expensive to *initialise* | `ObjectPool<T>` + `IResettable` | `ArrayPool<T>` if the cost is just the buffer |
| Counting or accumulating into a dictionary | `CollectionsMarshal.GetValueRefOrAddDefault` (.NET 6+) | `TryGetValue` + assign |
| Big `MemoryStream` buffers churning the LOH | Stream to the destination; else pooled buffers | `RecyclableMemoryStream` (`Microsoft.IO.RecyclableMemoryStream`) |
| Filling a collection whose final size you know | `new List<T>(capacity)` / `EnsureCapacity(n)` | `CollectionsMarshal.SetCount` + `AsSpan` (.NET 8) |
| Attaching state to objects you don't own | `ConditionalWeakTable<TKey,TValue>` | `WeakReference<T>` if the *value* is the cache |
| A cache that must not root its entries forever | `MemoryCache` with a size limit and eviction | `WeakReference<T>` for large, recreatable values |
| Counters written concurrently by many threads | Accumulate in a local, publish once | Cache-line padding only if the shared write is unavoidable |
| Formatting your own value type into someone's buffer | Implement `ISpanFormattable` (.NET 6) | `IUtf8SpanFormattable` (.NET 8) if the sink is bytes |
| A latency-critical window you must not be paused in | `GC.TryStartNoGCRegion` — **check the return value** | `GCSettings.LatencyMode = SustainedLowLatency` for longer windows |
| A managed wrapper over a large native buffer | `IDisposable` + `using` | `GC.AddMemoryPressure` / `RemoveMemoryPressure` if only a finalizer exists |

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

**Reading the output** — the *shape* of the report, not numbers to memorise (yours will differ by machine, runtime and N):

```
| Method        | N    | Mean      | Error    | Allocated | Ratio |
|---------------|------|-----------|----------|-----------|-------|
| PlusOperator  | 100  |  <time>   | <±>      | <bytes>   | 1.00  |
| StringBuilder | 100  |  <time>   | <±>      | <bytes>   | <x>   |
| StringCreate  | 100  |  <time>   | <±>      | <bytes>   | <x>   |
```

Read it in this order, which is not left to right:

1. **Allocated first.** It is the most stable column across machines and the one that predicts production behaviour. If a method you believe is allocation-free reports a non-zero value, stop and find the box or the closure before looking at time at all.
2. **Error / StdDev next.** If the intervals of two rows overlap, the ordering between them is not a result.
3. **Mean and Ratio last**, and only relative to the baseline within the same run.

- **Mean** — average time per call.
- **Allocated** — bytes allocated **per call** (the headline number `[MemoryDiagnoser]` adds).
- **Ratio** — relative to the baseline (`Baseline = true`).
- **Gen 0/1/2** — collections per 1000 ops (also added by `[MemoryDiagnoser]`).

**What the `Allocated` column is, and the three things it cannot see**

This is the part that turns a benchmark from evidence into a decision, and it comes straight from how the diagnoser is built. BenchmarkDotNet measures allocation with **`GC.GetAllocatedBytesForCurrentThread`**, runs a **separate iteration set** when any diagnoser is attached (so the tracking overhead doesn't contaminate the timing run), and its own documentation puts the accuracy at "99.5% … when using default settings or `Job.ShortRun` (or any longer job than it)". Three consequences:

1. **It counts the benchmark thread only.** A method that offloads its work with `Task.Run`, or that hands a callback to a thread-pool thread, reports the allocations of the *dispatch*, not of the work. A "0 B" result on a method whose body is `Task.Run(...)` is not a zero-allocation method; it is a measurement of the wrong thread.
2. **It counts managed allocation only.** `stackalloc`, `NativeMemory.Alloc`, `Marshal.AllocHGlobal`, memory held by a native library, and anything served from a warm `ArrayPool` are all **invisible**. "0 B allocated" means "asked the GC for nothing", not "used no memory" — which is exactly the claim a pooled implementation is making, and exactly why you must check for a missing `Return` some other way.
3. **It is per-call, so `[Params]` changes its meaning.** A method whose `Allocated` grows linearly with `N` and one whose `Allocated` is constant are telling you different things about scaling, and a single-`N` benchmark hides that. Parameterise on size whenever allocation could depend on it.

The fourth thing worth saying: `Allocated` is what you compare across *runs*, because it is deterministic in a way that `Mean` is not. If a refactor is meant to be allocation-neutral, `Allocated` is the regression test.

**The shape of a pooling benchmark** — the case where the harness lies to you most easily:

```csharp
[MemoryDiagnoser]
[SimpleJob(RuntimeMoniker.Net10_0)]
public class BufferStrategy
{
    // Parameterise on size: this is the axis the answer actually depends on.
    [Params(128, 4096, 100_000)]
    public int Size { get; set; }

    [Benchmark(Baseline = true)]
    public int Fresh()
    {
        byte[] buffer = new byte[Size];
        return Consume(buffer.AsSpan(0, Size));
    }

    [Benchmark]
    public int Pooled()
    {
        byte[] buffer = ArrayPool<byte>.Shared.Rent(Size);
        try { return Consume(buffer.AsSpan(0, Size)); }
        finally { ArrayPool<byte>.Shared.Return(buffer); }
    }

    // The work must be real and its result returned, or the JIT deletes the buffer.
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int Consume(Span<byte> span) { span[0] = 1; return span.Length; }
}
```

Three things this shape is deliberately doing, each of which is a defect in the version people write first:

- **`[Params]` includes a size above 85,000 bytes**, because that is where the answer changes character — `Fresh` becomes a gen-2 allocation per call while `Pooled` stays flat. A benchmark that only tests 4 KB measures the boring half of the question.
- **The result is returned and `Consume` is `NoInlining`**, so the buffer is genuinely used. Without that, escape analysis and dead-code elimination can remove the allocation you are trying to measure — and `Fresh` will look suspiciously good.
- **The pool is warm for the whole run**, which is honest for a steady-state server and dishonest for a cold path. `Pooled` reporting 0 B is the benchmark saying "no *managed* allocation", not "no memory" — the buffer exists, it is just held by the pool. If you want the cold number, you need a fresh `ArrayPool<byte>.Create()` per iteration, and then `[IterationSetup]` overhead starts distorting short benchmarks. Pick which question you are asking and say which one in the write-up.

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
2. **Warmup** — runs until the measurements stabilise, so the JIT can compile, tier up, and let dynamic PGO settle. Discarded.
3. **Workload** — the iterations that are actually reported.

Both counts are **adaptive by default**, not fixed: BDN chooses them from the measurements it is taking, bounded by `MinWarmupIterationCount` (6) / `MaxWarmupIterationCount` (50) and `MinIterationCount` (15) / `MaxIterationCount` (100). The documentation's own advice is that you *shouldn't* specify `WarmupCount` / `IterationCount` / `IterationTime` yourself, because pinning them defeats the heuristic. The reason to know the numbers anyway is diagnostic: a benchmark that ran the maximum warmup iterations was still moving when BDN gave up, which usually means tiering, a cache warming up, or state leaking between iterations — all of which mean the reported mean is not steady-state. If your benchmark is dominated by **first-call JIT cost** and you actually want to measure that, the tool for it is `RunStrategy.ColdStart`, not a smaller warmup count.

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

8. **Cold cache vs warm cache** — micro-benchmarks measure steady-state, warm-cache, fully-tiered-up performance. Real requests arrive against cold CPU caches, cold branch predictors, and sometimes tier-0 code. BDN can be told to measure the cold case with `[SimpleJob(RunStrategy.ColdStart)]` (a `RunStrategy` value, not a standalone attribute), but the default `Throughput` strategy is what everyone runs, and it systematically flatters anything whose working set doesn't fit in cache.

9. **Tiny differences aren't real** — BenchmarkDotNet prints an `Error` (half of the 99.9% confidence interval) and `StdDev` for a reason. If the intervals of two rows overlap, you have measured noise, and no threshold rule of thumb rescues that. Report the interval, not the mean.

10. **Synthetic benchmarks ≠ production wins** — a micro-benchmark improvement on a function that is a negligible share of request time saves you nothing. Amdahl's law is the argument, and the fraction is the number you need. Profile real workloads (`dotnet-trace`, `PerfView`) to establish it before optimizing.

**Beyond micro-benchmarks**:

- **`dotnet-counters monitor -p <pid> --counters System.Runtime`** — live runtime stats. Note the syntax: `--counters` takes `provider[counter,counter]`, so a filtered view is `--counters System.Runtime[dotnet.gc.collections,dotnet.gc.heap.total_allocated]`. Passing a bare counter name without its provider does not work.
- **`dotnet-trace collect`** — full ETW-style trace; view in PerfView or Speedscope. Also the way to capture `System.Buffers.ArrayPoolEventSource`.
- **`dotnet-gcdump collect -p <pid>`** — the object *graph* of a live process, reconstructed from EventPipe events with low enough overhead to take under load. Two of these, minutes apart, diffed in Visual Studio or PerfView, is the standard answer to "what is growing and what still references it". This is the tool most candidates don't know exists.
- **`dotnet-dump analyze`** — post-mortem heap analysis with SOS commands (`dumpheap -stat`, `gcroot`, `gchandles`, `finalizequeue`, `dumpasync`).
- **JetBrains dotMemory / dotTrace** — UI-based memory + CPU profiling.
- **PerfView** (Vance Morrison) — the gold standard for low-level CLR perf investigation.

**Measuring in production — the APIs, not the tools**

BenchmarkDotNet answers "which of these two implementations allocates less". It cannot answer "is GC why our p99 moved last Tuesday". For that the runtime exposes the numbers directly, and a senior candidate should be able to name them without reaching for a profiler.

```csharp
// Process-wide allocation total. 'precise: false' (default) is cheap and
// approximate; 'true' walks all thread allocation contexts.
long allocated = GC.GetTotalAllocatedBytes();

// Per-thread. Sample it around a unit of work to attribute allocation to it.
long before = GC.GetAllocatedBytesForCurrentThread();
DoWork();
long cost = GC.GetAllocatedBytesForCurrentThread() - before;

// Total time all managed threads have been paused for GC (.NET 7+).
TimeSpan paused = GC.GetTotalPauseDuration();

// Rich snapshot of the last collection.
GCMemoryInfo info = GC.GetGCMemoryInfo();
```

`GCMemoryInfo` is the one worth knowing properly. Its properties answer distinct questions:

| Property | The question it answers |
|---|---|
| `Generation` | Was the last collection a gen 0, 1 or 2? |
| `PauseDurations` | How long were the stop-the-world phases of that collection? (A background gen 2 has two.) |
| `PauseTimePercentage` | What share of total process elapsed time has been spent paused, cumulatively? Documented as a running counter updated at the end of each GC. |
| `HeapSizeBytes` / `TotalCommittedBytes` | Live heap vs. memory actually committed — the gap is the GC's headroom, and the reason committed exceeds heap. |
| `FragmentedBytes` | How much of the heap is holes. Rising over time on the LOH is the fragmentation story. |
| `PinnedObjectsCount` | How many pinned objects the GC had to work around. |
| `MemoryLoadBytes` / `HighMemoryLoadThresholdBytes` | How close the process is to the level where the GC starts doing aggressive full compacting collections. In a container, both are measured against the container limit. |
| `Compacted` / `Concurrent` | Whether that collection compacted, and whether it ran in the background. |

**And the modern path: built-in metrics (.NET 9+).** The runtime now publishes a `System.Runtime` **Meter**, which means GC data flows into OpenTelemetry and your existing dashboards with no custom code:

| Instrument | What it reports |
|---|---|
| `dotnet.gc.collections` | Collection count, tagged `gc.heap.generation` = `gen0` / `gen1` / `gen2` |
| `dotnet.gc.heap.total_allocated` | Same value as `GC.GetTotalAllocatedBytes()` |
| `dotnet.gc.pause.time` | Same value as `GC.GetTotalPauseDuration()` |
| `dotnet.gc.last_collection.heap.size` | Heap size at the last collection, tagged by generation including `loh` and `poh` |
| `dotnet.gc.last_collection.heap.fragmentation.size` | Fragmentation, tagged by generation |
| `dotnet.gc.last_collection.memory.committed_size` | Committed bytes at the last collection |
| `dotnet.process.memory.working_set` | Process working set — the number the container limit is enforced against |

Version gate worth stating precisely: these instruments arrived in **.NET 9**. On .NET 8 and earlier the same tooling falls back to the older `System.Runtime` **EventCounters** with different names (`gen-0-gc-count`, `gc-heap-size`, `alloc-rate`, `time-in-gc`, `loh-size`, `poh-size`). If a dashboard broke on the .NET 9 upgrade, this rename is why.

The two derived signals worth alerting on, in order:

1. **Pause time as a fraction of elapsed time** — from `dotnet.gc.pause.time` or `PauseTimePercentage`. This is the only GC number that maps directly onto user-visible latency.
2. **Allocation rate** — the derivative of `dotnet.gc.heap.total_allocated`. It is the *cause*; everything else on this list is an effect. A regression here precedes the pause-time regression, which makes it the better alert.

> 🌍 **In the real world**: a team adds a GC dashboard and alerts on heap size. It never fires, because the heap is healthy — the service allocates furiously but everything dies in Gen 0, so the heap stays small and flat while the process spends a significant fraction of its time paused. The alert that would have caught it is pause-time percentage, which is the ratio nobody thinks to graph because every tutorial graphs bytes. **Heap size tells you about retention; pause time tells you about latency, and they are different failures.**

> 🌍 **In the real world**: a "zero-allocation" rewrite of a request-enrichment step is signed off on a benchmark reporting **0 B allocated**. In production the allocation rate doesn't move at all. The rewrite had moved the enrichment onto a `Task.Run`, and `[MemoryDiagnoser]` measures the benchmark thread — so every allocation the work still did happened on a thread the harness wasn't watching. Worse, the change added a thread-pool work item per request, so the real effect was *more* allocation plus scheduling latency. Nothing about the benchmark was misconfigured; it answered the question it was asked. **The senior habit is to state, in the write-up, which thread and which memory the number covers** — "0 B on the calling thread, managed only" is a claim you can check, and "zero-allocation" is not.

> 🌍 **In the real world**: an optimization is validated with a BenchmarkDotNet run showing a large improvement, shipped, and produces no measurable change in p99. The benchmark was correct. The method being optimized ran once per request against a database call that dominated everything. The reviewer's question that would have saved the sprint is not "is this benchmark sound?" but **"what fraction of a request does this method account for?"** — and the honest answer, "I don't know, I only measured the method", is the answer that ends the discussion.

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
1. Rent(1024)  → ArrayPool gives you a byte[] ≥ 1024 (bucket size, e.g. 1024)
                 contents may be a previous caller's data OR never-zeroed memory
2. Use it      → Span<byte> over slice [0..written]; track 'written' yourself
3. Return      → clearArray:true if it held secrets, or if T is a reference type
                 length must match a bucket exactly or ArgumentException
4. Don't touch → after Return, treat the array as gone. Returning twice is a
                 double-free: two callers get the same buffer.
```

**Where an allocation can actually land (.NET 10):**

```
   new int[3]  /  (object)someStruct  /  x => x + local   ← the shapes the
                              │                              JIT recognises today
                    ┌─────────┴─────────┐
                    │  JIT escape       │   Does it outlive the method?
                    │  analysis         │   (assigned to a field? returned?
                    └─────────┬─────────┘    passed to a non-inlined call?)
                    NO        │        YES
          ┌───────────────────┘         └────────────────────┐
          ▼                                                  ▼
   ── STACK FRAME ──                              ── GC HEAP ──
   pointer bump, freed                      size < 85,000 B ?
   by the epilogue,                          ├── yes → Gen 0 ──survive──▶ Gen 1 ──▶ Gen 2
   invisible to the GC                       └── no  → LOH (swept with Gen 2, not compacted)
                                             pinned:true → POH (never moves)
```

**Where a `struct Point { int X, Y; }` actually lives — five answers, one type:**

```
   void M()
   {
       Point a;              ──▶ STACK FRAME (or registers). No header.
       var n = new Node();
       n.P = a;              ──▶ INSIDE n's HEAP OBJECT:
                                 [hdr|mt| P.X | P.Y | …other fields… ]
       var arr = new Point[3];
       arr[0] = a;           ──▶ INSIDE THE ARRAY, contiguously:
                                 [hdr|mt|len| X Y | X Y | X Y ]
       Func<int> f = () => a.X;
                             ──▶ HOISTED into the display class on the heap.
                                 'a' is no longer a stack slot at all.
       object o = a;         ──▶ BOXED: its own heap object, header + copy.
   }

   async Task N()
   {
       Point b;              ──▶ stack while the method runs synchronously;
       await IoAsync();          inside the boxed state machine once it suspends.
       Use(b);
   }

   Rule: a value type lives wherever its STORAGE LOCATION lives.
   The language guarantees copy semantics and lifetime — not placement.
```

**Why a reference store costs more than an `int` store:**

```
   Gen 2                                   Gen 0
   ┌───────────────────┐                   ┌───────────────┐
   │ oldObj            │                   │ youngObj      │
   │   .Next  ─────────┼──────────────────▶│               │
   └───────────────────┘                   └───────────────┘
            │
            │  oldObj.Next = youngObj;
            │  JIT emits a WRITE BARRIER here
            ▼
   card table:  [ ][ ][X][ ][ ][ ]     ← the card covering oldObj is marked dirty
                       ▲
   A Gen 0 collection now traces:  all of Gen 0  +  only the DIRTY cards of Gen 2.
   Without the barrier it would have to trace all of Gen 2 — which is the entire
   cost that generational collection exists to avoid.

   oldObj.Value = 42;   ← plain int store, no barrier, no card
```

</details>
## Common pitfalls

1. **`stackalloc` in a loop.** Each iteration allocates more stack — eventually overflows. Move outside the loop.
2. **Forgetting to `Return` an `ArrayPool` rental.** The pool degrades to plain allocation — invisible in the type system, but *not* invisible to diagnostics: `System.Buffers.ArrayPoolEventSource` reports `BufferAllocated` with reason `PoolExhausted`. Always pair `Rent` with `Return` in `try/finally`, or use `IMemoryOwner` with `using`.
3. **Holding a `Span<T>` past its memory's lifetime.** Compiler usually catches this (ref struct rules), but `MemoryMarshal.CreateSpan` can defeat the check — be careful.
4. **`Span<T>` in async methods.** Since C# 13 the local is legal; what fails is keeping it **live across** the `await` (CS4007). A `ref struct` *parameter* is still an outright error (CS4012). Use `Memory<T>` for the field/parameter, `Span<T>` only inside synchronous segments.
5. **Using LINQ where you meant slicing.** `arr.Skip(10).Take(20)` allocates iterator objects (and a closure if the lambda captures); materializing it with `ToArray()` allocates the array too. `arr.AsSpan(10, 20)` allocates nothing — a span is a pointer and a length. For contiguous data, prefer span slicing.
6. **`stackalloc` returning to caller.** You can't — the stack frame is gone. Use `Span<T>` only inside the allocating method.
7. **Pinning a large object with `fixed` for too long.** Pinned objects can't be moved by the GC, fragmenting the heap. Pin briefly.
8. **Treating `string.Create` as always faster.** It's a one-allocation path *if* you know the final length. For unknown sizes, `StringBuilder` is often clearer and similar in speed.
9. **Profiling synthetic benchmarks but not real code.** A micro-benchmark improvement on a helper method does not transfer to the endpoint unless that method is a meaningful share of the endpoint's time — and the work a span replaces usually isn't. Establish the share first, in a production-shape workload, then optimize.
10. **Reaching for `unsafe` before `Span<T>` + `MemoryMarshal`.** Almost every "I need pointers" case is now solved by safe primitives. `MemoryMarshal.Cast`, `MemoryMarshal.AsBytes`, `MemoryMarshal.GetReference` cover most of the gap.
11. **Returning a pooled array twice.** Usually an exception path that returns, plus a `finally` that returns again. The array is now in the pool twice, two callers rent the same buffer, and you get cross-request data corruption with no exception anywhere. Microsoft's docs classify this as a high-severity security issue; null out the local before returning so a second return is a `NullReferenceException` you can find.
12. **Returning an array the pool didn't give you.** `ArrayPool<T>.Return` requires the array's length to match a bucket size exactly and throws `ArgumentException` otherwise. `Return(new byte[1000])` throws.
13. **Not clearing a reference-type pooled array.** `ArrayPool<string>.Shared.Return(buf)` with the default `clearArray: false` leaves every element reachable from the pool for the life of the process. Nothing clears it for you.
14. **Assuming `Rent(n)` gives you `n` and gives you zeros.** It gives you *at least* `n`, and for primitive element types the shared pool may hand back memory that was never zeroed. Track what you wrote and slice to it.
15. **Alerting on heap size instead of pause time.** A service can spend a large share of its wall clock paused while its heap stays small and flat, because everything dies in Gen 0. `dotnet.gc.pause.time` / `GCMemoryInfo.PauseTimePercentage` is the latency signal; heap size is the retention signal.
16. **Treating stack allocation by the JIT as something you can rely on.** Escape analysis is an optimization with no language guarantee; it doesn't apply in Debug or tier-0 code, and an innocuous refactor that makes a method un-inlineable silently reverses it.
17. **Believing `_logger.LogDebug($"...")` is free when `Debug` is off.** `Microsoft.Extensions.Logging` has no interpolated-string-handler overload, so the string is built and allocated regardless, and the message template — and with it every structured field — is destroyed. Enable `CA2254`.
18. **Answering "value types live on the stack".** They live wherever their storage lives: in the enclosing object if they're a field, in the array if they're an element, in the display class if captured, in the state-machine box if they cross an `await`. Say "the stack is an implementation detail; what's guaranteed is copy semantics and lifetime".
19. **Calling `GC.TryStartNoGCRegion` and ignoring the `bool`.** On `false` you are not in the region, and the matching `GC.EndNoGCRegion()` throws `InvalidOperationException` — usually from inside a `finally`, where it replaces the original problem with a worse one. Guard on `GCSettings.LatencyMode == GCLatencyMode.NoGCRegion`.
20. **Presizing a collection from untrusted input.** `EnsureCapacity(userSuppliedCount)` is the `stackalloc`-from-input bug one layer up; the API's own docs say to clamp it or let the collection grow instead.
21. **Letting a long-lived publisher hold short-lived subscribers.** `+=` stores a strong reference to the subscriber in the publisher's invocation list. A singleton event plus scoped subscribers is a leak that grows with total requests served, forever.
22. **Reading `Marshal.SizeOf<T>()` as "the size of the struct".** It is the *marshalled* size — a `bool` becomes 4 bytes by default. `Unsafe.SizeOf<T>()` is the managed layout size.
23. **Trusting a `0 B` benchmark result.** `[MemoryDiagnoser]` measures managed allocation **on the benchmark thread only**. Work moved to the thread pool, `stackalloc`, native memory, and a warm pool are all invisible to it.
24. **Assuming a struct gets reference equality by default.** It gets `ValueType.Equals`, which compares fields (reflectively unless the type qualifies for the bitwise fast path) and boxes on the way in. `==` isn't generated at all — that one *is* a compile error.

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
- **Escape analysis** — the JIT stack-allocates objects it can prove don't escape: boxes (.NET 9), small fixed-size arrays of value *and* reference types, objects held only in local struct fields, and non-escaping delegates (.NET 10). "`new` means heap" is now a half-truth.
- **Write barriers and card tables** — a reference store into a heap field costs more than a value store, because the JIT emits a barrier that marks the card so a young collection can skip tracing old generations.
- **Regions, not segments** (.NET 7+) — 4 MB SOH regions, 8× for UOH, with a large *reserved* (not committed) virtual range. Old segment-era advice like `RetainVM` no longer means what it did.
- **Containers** — the GC heap hard limit defaults to the larger of 20 MB and 75% of the cgroup limit; the remaining headroom belongs to native memory, the JIT, and thread stacks. Workstation GC is forced on a single-logical-CPU machine regardless of configuration. DATAS is **on by default from .NET 9**.
- **Pooling has three tiers**: `stackalloc` (no allocator at all), `ArrayPool<T>` / `MemoryPool<T>` (buffers), `ObjectPool<T>` + `IResettable` (objects whose *initialization* is the cost).
- **Production measurement** — `GC.GetTotalAllocatedBytes()`, `GC.GetAllocatedBytesForCurrentThread()`, `GC.GetTotalPauseDuration()` (.NET 7+), `GC.GetGCMemoryInfo()`, and the `System.Runtime` Meter (.NET 9+). Alert on **pause-time fraction** and **allocation rate**, not heap size.
- **Stack vs heap** — not a property of the type, a property of the storage location. A value type lives in whatever contains it: a class field lives in the heap object, an array element in the array, a captured local in the display class, a local crossing `await` in the state-machine box. What the language guarantees is copy semantics and lifetime, not placement. Thread stacks are a fixed reservation (1 MB from the PE header on Windows; `ulimit -s` on Linux; `DOTNET_DefaultStackSize` to override), and you cannot set the size of a thread-pool thread's stack.
- **Growth is the hidden allocator** — `List<T>` starts from a shared empty array, allocates `DefaultCapacity = 4` on first `Add`, then doubles; filling to N allocates ~log₂(N) arrays and ~2N slots' worth of bytes. `EnsureCapacity` (Dictionary/HashSet .NET Core 2.1; List/Stack/Queue .NET 6), `CollectionsMarshal.SetCount` (.NET 8), `Array.Empty<T>()`. Never presize from untrusted input.
- **The root set** — thread stacks and registers, statics and `[ThreadStatic]`, GC handles (`Normal`/`Pinned`/`Weak`/`WeakTrackResurrection`), the finalization queue, runtime internals. Every managed "leak" is unintended retention, and `gcroot` is the command that names it. Weak options: `WeakReference<T>` (short vs `trackResurrection`), `ConditionalWeakTable<TKey,TValue>`, `DependentHandle` (.NET 6+).
- **Liveness is precise, not lexical** — an object can be finalized while one of its own methods runs; a delegate handed to native code can be collected while native still holds the pointer. `GC.KeepAlive` at the *end* of the range, or better, a field or a `SafeHandle`.
- **Runtime-settable GC knobs** — `GCSettings.LatencyMode` (`LowLatency` is workstation-only; `SustainedLowLatency` needs background GC and grows the heap), `GC.TryStartNoGCRegion` / `EndNoGCRegion` (returns `bool`, no nesting, single-arg overload commits 2 × `totalSize`), `GC.AddMemoryPressure` / `RemoveMemoryPressure` for native memory the GC can't see — and remove exactly what you add.
- **Data locality** — a heap object costs an 8-byte header slot plus an 8-byte method-table pointer, with a 24-byte minimum on x64; struct fields and array elements pay none of it. Structs default to `LayoutKind.Sequential` and classes to `Auto`, so field order matters for one and not the other. Reference-type array stores pay a covariance check *and* a write barrier. Cache lines are 64 bytes (128 on ARM64) and false sharing is the reason throughput can fall as you add threads.
- **`[MemoryDiagnoser]` limits** — measured via `GC.GetAllocatedBytesForCurrentThread`, in a separate iteration set: benchmark thread only, managed allocation only. `0 B` is a narrower claim than "zero-allocation".

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
> **A**: The **generational hypothesis** — most objects die young. A single-generation collector would trace the entire heap on every collection, paying for objects that are obviously alive (caches, configuration, the DI container). Generational tracing lets the GC touch only the small young region most of the time and pay for the full heap rarely. The trade-off it buys with is **bookkeeping**: an old object can reference a young one, so the runtime must record those references or the young collection would be unsound. That is what the write barrier and card table do — the JIT emits a barrier on every reference store into a heap field, marking the card so a young collection traces only the dirtied portion of the old generations. So the honest summary is: generational GC trades a small, constant cost on every reference *write* for a large saving on every *collection*. Name the write barrier and you've answered the question behind the question.

### Drill 2 — LOH threshold

> **Q**: Why does the LOH have an 85,000-byte threshold? Why that specific number?
>
> **A**: Above ~85 KB, the cost of **copying the object during compaction** exceeds the cost of leaving a hole in the heap. The CLR's Gen 0/1/2 are compacting collectors — they slide surviving objects together to eliminate fragmentation. Past some size, moving the object is more expensive than tolerating fragmentation, so LOH is **non-compacting** by default. The exact number was chosen by measurement, not derived — if an interviewer pushes for a reason behind 85,000 specifically, the correct move is to say it was empirically tuned rather than to invent one. And it **is** tunable upward: `System.GC.LOHThreshold` in `runtimeconfig.json` (or `DOTNET_GCLOHThreshold`, hex, as an env var) has existed since .NET Core 3.0. The value must exceed the default and may be capped by the runtime; read back the effective value with `GC.GetConfigurationVariables()`.
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
> **A**: The C# spec says the lifetime of `stackalloc` is the **enclosing method**, not the loop iteration. Each iteration's `stackalloc` adds to the stack frame and *doesn't reclaim until the method returns*. A loop allocating 256 bytes for 10,000 iterations consumes ~2.5 MB of stack — far exceeding the 1 MB Windows default. The fix: move the `stackalloc` outside the loop and reuse the buffer; or use `ArrayPool` if the size varies. The diagnostic that catches this is the **code-analysis rule `CA2014`, "Do not use stackalloc in loops"** — an analyzer rule, not a compiler warning, so it fires only if analyzers are enabled. (Don't confuse it with `CS9081`, which is a compiler warning about a `stackalloc` result possibly *escaping* its method — a different bug.) The safest rule remains "no `stackalloc` inside loop bodies, ever"; `CA2014`'s own docs allow suppression only when the loop runs a known-small number of times.

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
> **A**: Async methods are lowered by the compiler into a **state machine** — a class that hoists every local that is *live across a suspension point* into a field, so the method can be paused and resumed. A `Span<T>` held across the `await` would become a field of a class, which the `ref struct` rules forbid. Be precise about the version gate, because the blanket rule most people quote is out of date: **through C# 12** merely declaring a `ref struct` local anywhere in an `async` method was an error. **Since C# 13** the declaration is legal and the compiler objects only when the value is still needed after the suspension — Microsoft Learn's *ref struct types* puts it as "a `ref struct` variable can't be used in the same block as the `await` expression" — which surfaces as **CS4007, "Instance of type 'System.Span&lt;int&gt;' cannot be preserved across 'await' or 'yield' boundary."** A `ref struct` **parameter** is still rejected outright with **CS4012**, because a parameter is live at every suspension point by definition. Workaround unchanged: store `Memory<T>` across the await, convert to `Span<T>` only within synchronous segments between awaits. See [Type System › `ref struct`](./02-type-system.md#ref-struct-spant-and-memoryt--the-stack-only-family) for the full current restriction list.

### Drill 6 — ArrayPool cost/benefit

> **Q**: When does `ArrayPool<T>.Rent` actually beat `new`?
>
> **A**: Two conditions, and neither is a number you can memorise. First, the buffer must be **big enough that the allocation contributes meaningfully to Gen 0 budget consumption** — below a few hundred bytes, `stackalloc` beats both and above ~85,000 bytes pooling is close to mandatory because you're otherwise allocating straight into the LOH. Second, the same path must rent the **same size often enough that the buffer stays warm in the pool's per-thread slot or per-core stack** — that's what makes a rent a pointer swap rather than an allocation. If either fails, `new` is competitive and simpler. Note the asymmetry that makes this an easy call at the top end: `new byte[100_000]` is a gen-2 allocation *every single time*, whereas the pooled version is one allocation ever.
>
> **Cross-Q**: What's the failure mode I need to test for?
>
> **A**: **Forgotten Return.** The pool degrades to plain allocation when starved; the symptom is allocations creeping up under load, and the root cause is almost always a path that rents but doesn't return when it throws. It is *not* silent, though, which is the part most people don't know: `ArrayPool<T>` publishes an EventSource named **`System.Buffers.ArrayPoolEventSource`** with `BufferRented`, `BufferAllocated`, `BufferReturned` and `BufferDropped` events, and `BufferAllocated` carries a reason — `Pooled` (cold start), `PoolExhausted` (rentals outnumber returns), or `OverMaximumSize` (you're renting bigger than the pool caches). A stream of `PoolExhausted` under load *is* the diagnosis. Capture it with `dotnet-trace collect --providers System.Buffers.ArrayPoolEventSource`. Prevention: `try/finally`, or `MemoryPool<T>.Shared.Rent()` for `IMemoryOwner<T> : IDisposable`.
>
> **Cross-Q²**: I `Return` a buffer that held a JWT. Two requests later, the next caller gets the same array. What do they see?
>
> **A**: They see **your JWT, in the unused portion**. `Return(arr, clearArray: false)` (the default) doesn't zero the buffer, and nothing else does either — I'd correct a common misconception here: **neither pool implementation in CoreLib clears automatically for any element type**, including reference types. So `Return(arr, clearArray: true)` (or `arr.AsSpan(0, length).Clear()` before returning) is on you. For **reference-type** arrays there's a second reason beyond disclosure: an uncleared `ArrayPool<string>` buffer keeps every element reachable *from the pool*, which is a process-lifetime GC root — a leak that never appears in a reference chain mentioning your code. And going the other way, `Rent` for primitive element types may hand back memory the runtime deliberately did **not** zero (`GC.AllocateUninitializedArray` on the miss path), so you cannot treat the tail of a rented buffer as zeros either. Any pool usage in a security-sensitive path needs an explicit `clearArray: true` and a comment saying why.

### Drill 7 — `ValueTask` vs `Task`

> **Q**: When would you switch from `Task<T>` to `ValueTask<T>`, and what breaks?
>
> **A**: Switch when the method **usually completes synchronously** (cached result, fast-path check) on a **hot path**. `ValueTask<T>` is a struct, so the synchronous path returns a value rather than allocating a `Task<T>`. What breaks: callers can no longer **await the same value twice**, call **`.Result`** before awaiting, or pass it to **`Task.WhenAll`** — the struct may wrap a pooled, single-use source. And be precise about what it does *not* buy you: it removes the `Task` object, not the async state machine. If the method actually suspends, the compiler-generated state machine struct still gets boxed onto the heap, and that box is the larger object. `ValueTask` is an optimization for the *cache-hit* shape specifically.
>
> **Cross-Q**: Should I always return `ValueTask` from my async methods then?
>
> **A**: No. **`ValueTask` is an optimization tool, not a default.** Reasons to stick with `Task`: (1) **Caller ergonomics** — `Task` is the universal contract; `ValueTask` adds caller-side rules they need to remember. (2) **Caching the result for multiple awaiters** — `Task` is freely awaitable any number of times; `ValueTask` is not. (3) **Composition with `Task.WhenAll` / `Task.WhenAny`** — these expect `Task`; `vt.AsTask()` defeats the optimization. Rule: `ValueTask` for hot-path internal APIs with synchronous fast-paths; `Task` for everything else.
>
> **Cross-Q²**: `IAsyncEnumerator<T>.MoveNextAsync()` returns `ValueTask<bool>`. Why was that choice made?
>
> **A**: Because the allocation would be **per element**, not per call. When iterating already-buffered data, every `MoveNext` completes synchronously; returning `Task<bool>` would allocate one object per item, so a single enumeration of N items produces N garbage objects for zero benefit. `ValueTask<bool>` with synchronous completion allocates nothing for the whole iteration. There is a second reason that's worth knowing because it applies even when the iteration *does* go async: a `ValueTask` can be backed by an `IValueTaskSource` that the enumerator **reuses across every `MoveNextAsync` call**, whereas a `Task` is single-use by construction and must be a fresh object each time. So `ValueTask<bool>` is the only choice that can make a long async iteration allocation-free end to end. This is the **canonical example** of why `ValueTask` exists — and why `IAsyncEnumerable` shipped only after `ValueTask` was stable.

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
> **A**: Don't quote a figure — describe what's being paid, because that's what generalises. Per copy: a 256-byte `memcpy`, a 256-byte stack slot that evicts something else from L1, and — the part people miss — **one copy per member access**, not one per iteration, since each property getter is a separate call the compiler must protect. So a loop body touching four properties pays four copies. On top of the direct cost it *blocks* optimizations: the hidden copy is an aliasing barrier, so the JIT stops hoisting and stops vectorizing. And the fix is a single keyword on the type declaration with no call-site change and no behavioural change — combine it with `in` so `void Process(in BigReadOnlyStruct s)` passes a pointer instead of 256 bytes. If the interviewer wants a number, the correct answer is "I'd put it under `[MemoryDiagnoser]` with and without `readonly` and show you", which is also the true answer.

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
> **A**: `readonly struct` — the keyword constraints above, and **nothing about equality**. Be careful here, because the common wrong answer is "structs get reference equality by default": they do not. Every struct inherits `ValueType.Equals`, which Microsoft's own guidance describes as performing "a value equality check by using reflection to compare the values of every field in the type" — correct, but slow, and it goes through `Equals(object)`, so calling it **boxes**. (CoreCLR has a bitwise fast path, gated on the type containing no pointers and being tightly packed, so whether you get the fast or the reflective path depends on your fields.) Separately, `==` is **not** generated for a plain struct at all — "the `==` and `!=` operators can't operate on a struct unless the struct explicitly overloads them", so `a == b` on a bare struct is a compile error. `record struct` — generates `Equals(T)`, `IEquatable<T>`, `GetHashCode`, and `==`/`!=` for you, but **its positional properties are mutable** (`record struct Point(int X, int Y)` has settable `X` and `Y`). `readonly record struct` — both: immutable *and* generated value equality. **For dictionary keys, hot loops, and value-typed coordinates, `readonly record struct` is the modern best choice**, and the reason is concrete rather than stylistic: it gives you a non-boxing `IEquatable<T>.Equals` and a real `GetHashCode`, which is what `Dictionary<TKey,TValue>` looks for before it falls back to the slow path.

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
> **A**: Strings are immutable, so each `+=` allocates a **new string** equal to `result.Length + items[i].Length` and copies all of `result` into it. The allocation *count* is O(N); the bytes allocated and copied are **O(N²)**, because iteration *i* re-copies everything the previous *i−1* iterations produced. Two things follow that make it worse than the big-O suggests: with UTF-16, 85,000 bytes is about 42,500 characters, so past that point **every single iteration produces a large object** and contributes directly to Gen 2; and the intermediates are exactly the objects most likely to still be alive when a collection runs, so they get promoted rather than dying cheaply in Gen 0.
>
> **Cross-Q**: What are the three fixes ranked by perf?
>
> **A**: Rank them by *allocation count and bytes copied*, which is the property you can reason about without a benchmark. (1) **`string.Create(len, items, callback)`** when the total length is computable — exactly one allocation, the result itself, written in place with no intermediate buffer at all. (2) **`StringBuilder` with pre-sized capacity** — the constructor's capacity is honoured directly, so you get one chunk plus one final copy in `ToString()`. (3) **`StringBuilder` without a capacity** — starts at 16 chars and links additional chunks as it fills; more allocations than (2), but still linear in the output and, crucially, it never re-copies what it already holds. For genuine variable-length building with conditional appends, `StringBuilder` is the right choice; if you find yourself quoting a multiplier between these three, measure it on your data instead.
>
> **Cross-Q²**: How does C# 10's interpolated string `$"x = {n}"` differ from `string.Format("x = {0}", n)`?
>
> **A**: `string.Format` **boxes every value-type argument** (N boxes) and parses the format string at runtime (CPU cost) before producing the final string. Get the array part right, because it is the half people overstate: `string.Format` has *non-`params`* overloads for one, two, and three arguments, and .NET added a `params ReadOnlySpan<object?>` overload that the compiler stack-allocates beyond that — so **no `object[]` is allocated at any argument count** unless you hand it one yourself. The boxes are the real cost. `$"x = {n}"` lowers to **`DefaultInterpolatedStringHandler`** — a stack-allocated builder that uses pooled char buffers. Zero boxing (it has `AppendFormatted<T>(T value)` generic methods, JIT-specialized per `T`). Zero format-string parsing (the layout is compile-time-known). One final allocation: the result string. Now the part to get right, because it is the most commonly repeated error about this feature: **that short-circuiting does not apply to `ILogger`.** `Microsoft.Extensions.Logging` has no interpolated-string-handler overload — the proposal to add one (dotnet/runtime #111283) was closed as not planned — so `_logger.LogDebug($"...")` builds and allocates the string before the logger ever sees it, and additionally destroys the message template that structured sinks rely on. The BCL APIs that *do* take a handler and can therefore skip the work are `StringBuilder.Append`/`AppendLine`, `MemoryExtensions.TryWrite` (.NET 6) and `Utf8.TryWrite` (.NET 8). For logging, the answer is the message-template overload or `[LoggerMessage]`, and `CA2254` is the analyzer that enforces it.

### Drill 13 — `string.Create` vs StringBuilder

> **Q**: When does `string.Create` beat `StringBuilder`?
>
> **A**: When you **know the final length ahead of time**. `string.Create` allocates the result string once and gives you a `Span<char>` to write into — one allocation, total. `StringBuilder` always costs at least two: its buffer plus the final string produced by `ToString()`.
>
> Be careful how you describe `StringBuilder`'s buffer, because the usual description is wrong and an interviewer who has read CoreLib will notice. It is **not** a single `char[]` that doubles and copies. It is a **linked list of chunks** — `m_ChunkChars` for the current buffer, `m_ChunkPrevious` for the one before. When a chunk fills, `ExpandByABlock` allocates a new one and relinks; the source comment describes this as "a few O(1) reference adjustments", and existing characters are **never re-copied**. New chunks are sized `max(needed, min(currentLength, MaxChunkSize))` with `MaxChunkSize = 8000` chars — a cap the source says exists "so we stay in the small object heap", since 8,000 chars is 16,000 bytes, well under the 85,000-byte LOH threshold. So `StringBuilder` is engineered to keep *its own* buffers off the LOH; the string it finally produces is a single allocation and can land there regardless.
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
> **A**: **One**. The first assignment `object o = i` boxes — allocates a small object on the heap, copies the value 5 into it, and stores the reference in `o`. The cast `(int)o` is an **unbox** — copies the value back out of the heap object into the stack-allocated `j`. Unboxing doesn't allocate; it reads from existing memory. On x64 that box is a **24-byte object** — 16 bytes of header (sync-block index + method-table pointer), 4 bytes of payload, 4 of padding — so the overhead is 20 bytes to carry 4 bytes of data.
>
> **Cross-Q**: How would I count boxes without running the code?
>
> **A**: Three ways. (1) **ILSpy / ildasm** — look for the `box` IL opcode; each occurrence is one heap allocation. (2) **Roslyn analyzer `HAA0601`** (heap allocation analyzer) — flags suspected boxes at compile time. (3) **BenchmarkDotNet `[MemoryDiagnoser]`** — measure `Allocated` column on a `[Benchmark]`. For a method that should be allocation-free but reports 24+ bytes per call, there's a hidden box. The fix is usually adding a generic constraint or calling the struct's method directly instead of through an interface.
>
> **Cross-Q²**: Where do enum boxes happen, and is `.NET 9` better than `.NET Framework 4.8` here?
>
> **A**: Three classic enum-boxing spots, and be precise about which ones modern .NET actually fixed. (1) `string.Format("{0}", myEnum)` boxes — the parameter is `object` and always was. (2) `Console.WriteLine(myEnum)` binds the `object` overload — boxes. (3) `myEnum.ToString()` **still boxes the receiver in IL**, because `ToString` is inherited from `System.Enum`, which is a class, and enum types don't override it; a `constrained.` call to a method the value type doesn't implement boxes. What modern .NET improved is (a) the *implementation* of `Enum.ToString` and the generic helpers — `Enum.GetName<TEnum>(value)`, `IsDefined<TEnum>`, `GetValues<TEnum>` arrived in **.NET 5** and take the value generically, so no box at the call; (b) `$"{myEnum}"`, which lowers to the handler's generic `AppendFormatted<T>(T)` and so doesn't box the argument; and (c) on **.NET 9+**, the JIT can stack-allocate a box that provably doesn't escape, which can make the remaining box free — but that is an optimisation with no guarantee, not a language change. The honest one-liner: *the way to avoid an enum box is to keep it in a generic `T` or a strongly-typed parameter and never let it reach an `object`.*

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
> **A**: **Server GC** — but say *why* it's the default rather than quoting a CPU count, because the mechanism is what's being probed. Microsoft's docs put it as: workstation GC "is the default GC flavor for standalone apps. For hosted apps, for example, those hosted by ASP.NET, **the host determines the default GC flavor**." Server GC creates one heap and one dedicated GC thread per logical CPU and collects them in parallel, which raises allocation throughput (per-CPU heaps mean near-zero contention on the allocation path) and shortens individual pauses. The trade-off is a larger memory footprint, because each heap carries its own allocation budget. There's one hard rule underneath all of this: **"Workstation garbage collection is always used on a computer that has only one logical CPU, regardless of the configuration setting."** So on a 1-vCPU container, `ServerGarbageCollection=true` is silently a no-op.
>
> **Cross-Q**: I'm running ASP.NET Core in a 256 MB Kubernetes pod. Should I still use Server GC?
>
> **A**: Two separate mechanisms are in play and the version gate matters. (1) **The heap hard limit.** In a memory-limited environment the runtime treats the container limit as total physical memory and defaults the managed heap to the larger of 20 MB and **75%** of it. That's `System.GC.HeapHardLimitPercent`; you can lower it, and you should if the process holds a lot of *native* memory, because the remaining 25% is the budget for everything that isn't the managed heap. (2) **DATAS**, which makes the number of heaps and the gen 0 budget track the application's live data rather than the CPU count. DATAS was **introduced in .NET 8 and is enabled by default from .NET 9** — so on a current runtime you are already running it, and the realistic experiment is turning it *off* (`DOTNET_GCDynamicAdaptationMode=0`) if a throughput-sensitive service regressed on upgrade. The honest answer to the question as asked is: measure both, in your topology, with your traffic — and know that on .NET 9+ "should I enable DATAS" is already answered for you.
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
> **A**: (1) **Dead-code elimination** — a benchmark that returns `void` and has no observable side effect gets optimized to nothing by the JIT, reporting 0 ns. Fix: **always return the computed value** from the benchmark method; BDN consumes it to force evaluation. (2) **Running in Debug mode or under a debugger** — disables tier-2 JIT optimizations, giving meaningless numbers. BDN warns about both at startup. Honorable mention: **`[Params]` cardinality explosion** — the run count is the product of every parameter's cardinality, every `[Benchmark]` method, and every job, so `[Params(1, 10, 100, 1000)]` across 4 benchmarks and 3 runtimes is 48 full measurement runs. Tune your parameter set deliberately; each run pays its own pilot, warmup and workload phases.

### Drill 19 — Closure allocations

> **Q**: `var n = 5; Func<int> f = () => n * 2;` — how many allocations?
>
> **A**: **Two objects, so two allocations.** The lambda captures the local `n`, so the compiler generates a **display class** (`<>c__DisplayClass...`) — a heap object holding `n` as a field and a method returning `n * 2`. Then the `Func<int>` itself is a delegate object whose target is that display-class instance. Say "one display class and one delegate" rather than quoting byte counts; the sizes follow from object layout and the delegate's field count, and the *number* of objects is what the interviewer is checking. Note also that the display class is **per scope, not per lambda** — every lambda in the same scope shares one, which is how a lambda that captures one `int` can end up keeping a large object alive.
>
> **Cross-Q**: How do I write a closure-free version?
>
> **A**: Three approaches, in the order you should try them. (1) **Capture nothing** — pass the value as a parameter instead: `Func<int, int> f = static n => n * 2;` then call `f(5)`. Roslyn caches a non-capturing lambda's delegate in a static field, so it is allocated once for the life of the process. Marking it `static` (C# 9) makes accidental capture a **compile error**, which is the real value — it survives the next person editing the body. (2) **Method group** — `static int Double(int n) => n * 2; Func<int, int> f = Double;`. (3) **Use a state-passing overload where the API offers one.** These exist precisely to let you avoid the capture, but you have to check that the specific API has one — LINQ's `Enumerable` methods largely do **not**, so `list.FirstOrDefault(x => x.Id == criteria.Id)` genuinely does capture. Ones that do: `ConcurrentDictionary<K,V>.GetOrAdd(key, Func<K,TArg,V>, TArg)`, `string.Create(length, state, SpanAction<char,TState>)`, `ThreadPool.QueueUserWorkItem<TState>(Action<TState>, TState, bool)`, `CancellationToken.Register(Action<object?>, object?)`.
>
> **Cross-Q²**: How do I detect closure allocations in production code?
>
> **A**: Three tools. (1) **Roslyn analyzer `HAA0301-302`** (Heap Allocation Analyzer) — flags lambdas that capture variables and warns about closure allocation. (2) **`[MemoryDiagnoser]` benchmarks** — if a method that should be allocation-free reports 56+ bytes per call, there's likely a closure. (3) **PerfView allocation trace** — search for compiler-generated `<>c__DisplayClass*` types; each one is a closure. The most common offenders: LINQ in hot paths (`.Where(x => x.Id == myId)` captures `myId`), event handlers that capture state, and lambda parameters to async methods.

### Drill 20 — `ref` returns

> **Q**: What's a real-world use of `ref` returns?
>
> **A**: **Dictionary in-place update** via `CollectionsMarshal.GetValueRefOrNullRef`. The typical "find-or-add" pattern costs two dictionary lookups — `TryGetValue`, then `[key] = ...` — each of which hashes the key and probes a bucket chain. `GetValueRefOrNullRef` does **one** lookup and returns a `ref TValue` pointing at the entry, which you mutate in place. Two savings, and they scale differently: the second hash-and-probe is a fixed saving, while for a large `TValue` struct you also stop copying the value out and back in, which grows with `sizeof(TValue)`. `GetValueRefOrAddDefault(dict, key, out bool existed)` (.NET 6) covers the insert case in the same single lookup.
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

### Drill 21 — Do value types live on the stack?

> **Q**: Value types live on the stack and reference types live on the heap. True?
>
> **A**: No — that's a statement about types, and the real rule is about **storage locations**. A value type's bytes live wherever its storage lives. As a method local it may be in a register or the stack frame; as a field of a class it lives *inside that heap object*; as an array element it lives inside the array on the heap; captured by a lambda it lives in the display class on the heap; alive across an `await` it ends up in the state-machine object once the method suspends; boxed, it lives in a heap object of its own. And the converse fails too — since .NET 9/10, escape analysis lets the JIT satisfy a reference-type `new` on the stack when it can prove the object doesn't escape. The formulation that holds up: **the stack is an implementation detail.** What the language guarantees is *copy semantics* (assignment copies the value) and *lifetime* (reclaimed with whatever contains it), not placement.
>
> **Cross-Q**: Then why does the distinction matter at all for performance?
>
> **A**: Because of what it implies about **layout and indirection**, not about which region the bytes are in. A struct field inside a class or an array pays no object header, no method-table pointer and no per-element dereference — on x64 that's 16 bytes of overhead avoided per element, against a 24-byte minimum object size, plus the difference between a sequential scan and a pointer chase. It also means no write barrier on stores, and no array covariance check. Those are the reasons `Point[]` beats `Point_asClass[]` in a loop, and none of them is "the stack is faster than the heap".
>
> **Cross-Q²**: I have a recursive parser that works in tests and kills the process in production. Where do I look?
>
> **A**: At the **stack the code is actually running on**, which is different in the two environments. A thread's stack is a fixed reservation made at creation: on Windows it comes from the reservation in the executable's PE header (1 MB by default); on Linux the main thread's comes from `ulimit -s`, commonly 8 MB, and CoreCLR uses a smaller fixed default on Alpine/musl. Tests typically run on a main or test-host thread; an ASP.NET Core request runs on a **thread-pool thread whose stack size you cannot configure**, with the middleware pipeline already some hundreds of frames deep. So the same input has far less headroom in production. `DOTNET_DefaultStackSize` (hex) raises the default for runtime-created threads and `new Thread(work, maxStackSize)` sets it for one you own, but neither is the right fix: a stack overflow is not a catchable exception, so the fix is a **depth limit that returns a 400**, plus moving any large buffers out of `stackalloc` and into the pool.

### Drill 22 — Diagnose a managed memory leak

> **Q**: A service's memory climbs steadily over a week and the pod is restarted to fix it. How do you find the cause?
>
> **A**: First separate the two failures, because they need different tools. If `GCMemoryInfo.HeapSizeBytes` (or `dotnet.gc.last_collection.heap.size`) is climbing, it's **managed retention** and everything below applies. If the managed heap is flat while the working set climbs, it's native memory and none of it will help. Assuming managed: `dotnet-gcdump collect -p <pid>` twice, spaced apart under comparable load, and diff the two in Visual Studio or PerfView. The diff — not a single dump — is what identifies the growing type, because a healthy heap also contains millions of objects. Then take one instance of that type into `dotnet-dump analyze` and run `gcroot <address>`, which prints the reference path back to a root. That path *is* the answer.
>
> **Cross-Q**: What are the roots it could end at, and which one is it usually?
>
> **A**: The root set is: live locals on any thread's stack (or in registers), static fields and `[ThreadStatic]` slots, GC handles (`Normal`, `Pinned`, and the weak variants), objects in the finalization queue awaiting their finalizer, and runtime-internal structures. In application code it is nearly always a static: a cache with no eviction, or — the one that hides best — an **event**. `publisher.Changed += handler` puts a strong reference to the *subscriber* into the publisher's invocation list, so a singleton publisher roots every scoped subscriber that ever attached. Runners-up: a `Timer` or `CancellationToken.Register` callback holding a closure, and an `ArrayPool<T>` of reference type returned with `clearArray: false`, where the pool itself becomes the root.
>
> **Cross-Q²**: The `gcroot` path ends at a `static ConcurrentDictionary`. Is that a leak?
>
> **A**: Probably not — and saying so is the point. In a managed process there is no leak in the C sense; there is **unintended retention**, and a static cache is retention working exactly as written. The diagnostic question is "if the load stops, does memory come back down?" If yes, it's live working set, not a leak. If no, the cache is unbounded and the fix is a **policy**, not a missing `Remove`: `MemoryCache` with a size limit and `SetSize` on entries, an LRU, or a `WeakReference<T>`/`ConditionalWeakTable` if the value should die with something else. A genuine leak — a reference nobody intended to keep — is fixed by dropping the reference; unbounded retention is fixed by deciding what you're willing to keep. Getting the classification right is what stops a team from "fixing" a cache by deleting it.

### Drill 23 — Throughput falls as you add threads

> **Q**: A parallel aggregation scales from one thread to two, stops improving at four, and gets *slower* at eight. There is no lock and no shared mutable state except a `long[]` of per-worker counters. What's happening?
>
> **A**: **False sharing.** Cache coherency operates on cache lines, not variables — 64 bytes on x64, and CoreLib's `PaddingHelpers.CACHE_LINE_SIZE` is 128 on ARM64. Eight `long`s is 64 bytes, so all eight counters sit within one or two lines. Every worker's write invalidates the line in every other core's cache, and the line ping-pongs between cores. The threads share no data; they share a line. It reads as a scaling ceiling rather than contention because there is nothing to show up in a lock-contention profile.
>
> **Cross-Q**: How do you fix it?
>
> **A**: Two options, and prefer the first. (1) **Stop sharing the line**: each worker accumulates into a plain local and does one `Interlocked.Add` (or one write under its own lock) at the end of its batch. This removes both the false sharing and the atomic operation from the hot loop, and it needs no knowledge of cache-line size. (2) **Pad**, if the shared write genuinely cannot be batched — which is what `ConcurrentQueue` does internally: `PaddedHeadAndTail` is `[StructLayout(LayoutKind.Explicit, Size = 3 * CACHE_LINE_SIZE)]` with `Head` and `Tail` at separate line offsets, padded before, between and after. Note where the BCL chose to spend that memory: on the two hottest concurrently-written fields of a lock-free queue, and essentially nowhere else. That's the calibration to carry — padding is a last resort, not a habit.
>
> **Cross-Q²**: Same aggregation, but now the slow part is a single-threaded pass over a million records and it allocates nothing. Where does the time go?
>
> **A**: Memory latency, most likely, and the shape of the data is the reason. If the records are a `List<Record>` where `Record` is a **class**, the list holds a million 8-byte references, each pointing at a separate heap object of at least 24 bytes, at whatever address the allocator produced — so the loop is a pointer chase the prefetcher cannot predict, and each element access is a potential cache miss. The same data as a `Record[]` of `readonly record struct` is one contiguous block: sequential access, no per-object headers, no indirection, and no write barrier on stores. Before converting, check the struct conditions — small, immutable, value-like, not used polymorphically — because if the type is passed through layers instead of computed over, you trade cache misses for the copies described in the defensive-copy section. The honest closing line is that this is a hypothesis you confirm with a profiler that reports cache misses, not with a stopwatch.

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
- **`DefaultInterpolatedStringHandler`** (C# 10): `$"..."` rents its scratch buffer from `ArrayPool<char>.Shared`; one allocation, the result. **`ILogger` has no handler overload** — `LogDebug($"...")` allocates even when the level is off, and loses the message template. Use templates or `[LoggerMessage]`; `CA2254` catches it.
- **Handler-taking APIs that really do skip the work**: `StringBuilder.Append`/`AppendLine`, `MemoryExtensions.TryWrite` (.NET 6), `Utf8.TryWrite` (.NET 8).
- **UTF-8 literal**: `"text"u8` is `ReadOnlySpan<byte>` — no allocation, no encode.
- **Boxing checklist**: any cast to `object` / interface, generic without constraint, `ArrayList` — checks via IL `box` opcode.
- **`GC.Collect()`**: almost never; only after one-time bulk loads or in benchmark setup.
- **BenchmarkDotNet + `[MemoryDiagnoser]`**: measure `Allocated` column — return the value to defeat dead-code elimination.
- **Escape analysis**: JIT stack-allocates non-escaping objects — boxes (.NET 9); small fixed-size arrays, local struct fields, delegates (.NET 10).
- **Write barrier**: emitted on every reference store into a heap field; marks a card so young GCs can skip old generations.
- **Regions** (.NET 7+): 4 MB SOH, 8× for UOH; a big *reserved* virtual range is normal and is not memory in use.
- **LOH threshold is configurable upward**: `System.GC.LOHThreshold` / `DOTNET_GCLOHThreshold` (.NET Core 3.0+).
- **Container heap limit**: default = max(20 MB, 75% of the cgroup limit). `HighMemoryPercent` default 90%. **DATAS on by default from .NET 9.**
- **1 logical CPU ⇒ Workstation GC**, regardless of `ServerGarbageCollection`.
- **`ArrayPool` contract**: `Rent` gives *at least* n and may be uninitialized; `Return` needs the exact bucket length or throws; reference-type arrays need `clearArray: true` or the pool holds them alive; double-return is a documented security issue.
- **`ObjectPool<T>` + `IResettable.TryReset()`**: pools objects, bounds what it *retains* not what it allocates, and returning is optional.
- **`SearchValues<T>`** (.NET 8; `SearchValues<string>` .NET 9, Ordinal/OrdinalIgnoreCase only): build once into a `static readonly`, then `IndexOfAny` / `ContainsAny`.
- **`StringBuilder` is a chunk list**, not a doubling array — `MaxChunkSize` 8,000 chars, deliberately kept under the LOH threshold.
- **Production GC APIs**: `GC.GetTotalAllocatedBytes()`, `GetAllocatedBytesForCurrentThread()`, `GetTotalPauseDuration()` (.NET 7+), `GetGCMemoryInfo()`; `System.Runtime` Meter (.NET 9+).
- **`dotnet-counters` syntax**: `--counters System.Runtime[dotnet.gc.collections,dotnet.gc.pause.time]` — provider name required.
- **C# 14**: implicit conversions among `T[]`, `Span<T>`, `ReadOnlySpan<T>`; can shift overload resolution.
- **Stack vs heap**: storage location decides, not the type. Field → in the object; element → in the array; captured → in the display class; across `await` → in the state-machine box.
- **Thread stacks**: 1 MB PE-header default on Windows; `ulimit -s` on Linux; `DOTNET_DefaultStackSize` (hex) to override; `new Thread(work, maxStackSize)`; **no per-work-item control on the thread pool**.
- **Collection growth**: `List<T>` = shared empty array → 4 → doubling, capped at `Array.MaxLength`. Dictionary/HashSet resize to the next prime and **rehash**. `EnsureCapacity`: Dictionary/HashSet .NET Core 2.1, List/Stack/Queue .NET 6.
- **`Array.Empty<T>()`** instead of `new T[0]`; `List<T>` with no items allocates only the list object.
- **Roots**: thread stacks + registers, statics / `[ThreadStatic]`, GC handles, the finalization queue, runtime internals. `dotnet-gcdump` ×2 + diff, then `gcroot`.
- **Weak**: `WeakReference<T>` (short by default; `trackResurrection: true` = long), `ConditionalWeakTable<TKey,TValue>` (weak key, value alive with it), `DependentHandle` (.NET 6+, `System.Runtime`).
- **`GC.KeepAlive`** goes at the **end** of the range, for objects only native code still uses. Liveness is what the JIT can prove, not your braces.
- **`GCSettings.LatencyMode`**: `LowLatency` workstation-only; `SustainedLowLatency` needs background GC, bigger heap, more fragmentation; `NoGCRegion` is read-only.
- **`GC.TryStartNoGCRegion(n)`** returns `bool`, commits 2 × n on the single-arg overload, can't nest, ≤ ephemeral segment size. Guard `EndNoGCRegion()` on the current latency mode.
- **`GC.AddMemoryPressure` / `RemoveMemoryPressure`**: for native memory freed only by a finalizer; remove exactly what you add.
- **Object layout (x64)**: 8-byte header slot + 8-byte method-table pointer, 24-byte minimum. `Unsafe.SizeOf<T>()` for managed size; `Marshal.SizeOf<T>()` is the *marshalled* size.
- **Layout defaults**: structs `Sequential`, classes `Auto`. Field order matters for structs; `[StructLayout(LayoutKind.Auto)]` opts a struct into runtime reordering.
- **Reference-array stores** pay a covariance check (`ArrayTypeMismatchException`) plus a write barrier; struct-array stores pay neither.
- **Cache line** 64 B (128 B on ARM64 in CoreLib's `PaddingHelpers`). False sharing = throughput falls as threads increase, with no lock in sight. Fix by not sharing the line.
- **`ISpanFormattable`** (.NET 6) / **`IUtf8SpanFormattable`** (.NET 8): `TryFormat` into a caller's buffer — what makes the whole zero-allocation chain work at the leaves.
- **`[MemoryDiagnoser]`**: `GC.GetAllocatedBytesForCurrentThread`, separate iteration set, benchmark thread only, managed only. BDN warmup/iteration counts are adaptive (6–50 / 15–100).
- **Heuristic**: hot path → check Allocated column → swap to span/pool until 0 B/op.

## Walkthrough — Gen 2 pressure from `string` concat

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: An order-export endpoint generates large CSV files. During exports, full (Gen 2) collections become frequent, and p99 latency spikes on *unrelated* endpoints — the classic signature of a noisy neighbour inside your own process, because a stop-the-world pause doesn't care which request caused it.

**Diagnosis**, in the order you'd actually do it:

1. **Confirm it's GC, not CPU.** `dotnet-counters monitor -p <pid> --counters System.Runtime[dotnet.gc.collections,dotnet.gc.pause.time,dotnet.gc.heap.total_allocated]` (on .NET 9+; on .NET 8 and earlier the same tool falls back to the EventCounter names `gen-2-gc-count`, `time-in-gc`, `alloc-rate`). Rising gen 2 count and rising pause time that track export volume is the confirmation.
2. **Find what's allocating.** `dotnet-trace collect --providers Microsoft-Windows-DotNETRuntime:0x1:5,Microsoft-DotNETCore-SampleProfiler -p <pid>`, then PerfView's Allocation View. The report is dominated by `System.String`, in sizes ranging from small up to very large — a size *distribution* that climbs is itself the clue, because it means one logical string is being rebuilt at growing lengths.
3. **Read the code that matches the shape.** `csv += $"{order.Id},{order.Total},{order.CustomerName}\n";` inside the per-row loop. Each `+=` allocates a string the size of everything written so far and copies it. Bytes allocated grow with the *square* of the row count, and past ~42,500 characters every intermediate is a large object allocated straight into the LOH — which is collected only with Gen 2, which is why an export endpoint became a latency problem for the whole service.

**Fix**: never materialize the document. Stream it to the response as it is produced.

```csharp
await using var sw = new StreamWriter(response.Body, Encoding.UTF8, bufferSize: 64 * 1024);
foreach (var o in orders)
    await sw.WriteLineAsync($"{o.Id},{o.Total},{o.CustomerName}");
// Lower still: rent a byte buffer from ArrayPool, format with Utf8.TryWrite /
// Utf8Formatter and UTF-8 literals, and flush when the buffer fills.
```

**Why it works** — three distinct mechanisms, and being able to separate them is the point of the walkthrough:

1. **The quadratic copying disappears.** A buffered writer appends; it never re-copies what it already wrote. Bytes allocated become linear in the output instead of quadratic.
2. **Nothing crosses the LOH threshold.** The writer's buffer is a fixed 64 KB, under 85,000 bytes, so the export stops contributing to Gen 2 at all.
3. **Peak working set stops tracking file size.** The whole document is never resident, so the endpoint's memory profile is flat regardless of how many rows the customer asked for — which also removes the input-driven failure mode where a bigger export means a bigger outage.

**How you'd verify**, rather than assert: re-run the same `dotnet-counters` view during an export and compare gen 2 count and `dotnet.gc.pause.time` against the baseline captured in step 1. That before/after pair is the deliverable; a claimed speedup with no baseline is not.

</details>
## Self-test

<details>
<summary>1. Why does the C# compiler refuse to let you store a `Span<T>` in a class field, and what's the workaround for an async method that needs span-like access?</summary>

`Span<T>` holds a managed pointer (`byref`) into memory that may be on the stack, heap, or native — it's a `ref struct` to enforce stack-only lifetime. A class field would let the span outlive its backing memory (e.g., `stackalloc` after the frame returns) — the compiler refuses to prevent this. For async methods, the compiler lowers them into a state machine class and hoists into fields every local that is live across a suspension point; a `Span<T>` held across the `await` would become such a field, which is **CS4007**. Since C# 13 the *declaration* of a `Span<T>` local in an async method is legal — only crossing the `await` is not — while a `ref struct` **parameter** remains an outright error (**CS4012**). Workaround: store `Memory<T>` (heap-storable) on the field/parameter, and inside synchronous regions call `.Span` to do the actual work.
</details>

<details>
<summary>2. Apply: profile shows `string.Format("{0}-{1}", a, b)` as a hot allocator. Three faster alternatives, ranked.</summary>

(1) Interpolated string `$"{a}-{b}"`: lowers to `DefaultInterpolatedStringHandler`, whose scratch buffer is rented from `ArrayPool<char>.Shared`, so the result string is the only lasting allocation — and no boxing, because `AppendFormatted<T>` is generic. (2) `string.Create`: `string.Create(a.Length + b.Length + 1, (a, b), (span, state) => ...)` — single allocation, no intermediate `object[]`. (3) `Utf8.TryWrite(destination, $"{a}-{b}")` into a pooled or stack byte span if downstream is binary — **zero** allocations, because the handler writes straight into your buffer and no string is created. The classic `string.Format` boxes each value-type argument and runs format-string parsing every call — the modern alternatives skip both costs. What it does *not* do is allocate an `object[]`: the two-argument call above binds to the non-`params` `Format(string, object, object)` overload, and beyond three arguments the compiler picks the `params ReadOnlySpan<object?>` overload and stack-allocates the span. Quote the boxes, not the array. (Full measured ledger in [Type System › Boxing and unboxing](./02-type-system.md#boxing-and-unboxing).) One thing *not* to say: that interpolation is free when the result is discarded. That only holds for APIs with an interpolated-string-handler parameter, and `ILogger` is not one of them.
</details>

<details>
<summary>3. Trade-off: when does `stackalloc` lose to `ArrayPool<T>.Rent`?</summary>

`stackalloc` is unbeatable for *small* (≤ ~1 KB), *known-size*, *single-frame* buffers — zero allocation, zero GC, automatic reclaim on return. Loses when (a) size is large or unknown — stack exhaustion is **not** a catchable `StackOverflowException` in modern .NET, it is immediate process termination with no `finally`, no log flush and no dump; (b) the buffer must outlive the method; (c) it is used in a loop — the lifetime is the enclosing *method*, so each iteration adds to the frame and nothing is reclaimed until the method returns (`CA2014` flags this). `ArrayPool<T>.Rent(size)` handles arbitrary sizes and survives across async boundaries, but pays rent/return overhead, requires the exact array back, and quietly loses its benefit if a `Return` is missed. Rule: ≤ ~1 KB and bounded by a constant on the stack; anything derived from input, or anything crossing an `await`, goes to the pool.
</details>

<details>
<summary>4. Analyze: BenchmarkDotNet shows `Method A: 100 ns, 0 B`; `Method B: 80 ns, 24 B`. Which is faster in production?</summary>

Likely A — even though B is faster per call. The 24 B/op on the hot path becomes Gen 0 pressure: at 1M ops/sec, that's 24 MB/s of allocations, triggering Gen 0 collections every few hundred ms. Each collection pauses *all* threads briefly; under load, the pause amortizes into worse p99/p999 even if avg latency improves. The 0 B/op method has no GC contribution. Senior rule: micro-benchmarks measure CPU; production performance is CPU + GC + cache + tail-latency. Always include `[MemoryDiagnoser]` and weigh allocations.
</details>

<details>
<summary>5. You see `Span<byte> buffer = stackalloc byte[size];` where `size` comes from a request parameter. Critique.</summary>

Stack overflow waiting to happen. `stackalloc` doesn't bounds-check against the remaining stack — a malicious or buggy `size` of 10 MB blows the thread stack, killing the process (no `OutOfMemoryException`, just immediate termination). Two fixes: (1) clamp the stackalloc size and fall back to pooled array: `Span<byte> buffer = size <= 1024 ? stackalloc byte[size] : ArrayPool<byte>.Shared.Rent(size);` — note the rented array must be returned in `finally`. (2) Always use `ArrayPool` for sizes derived from input. The pattern `size <= threshold ? stackalloc : pool.Rent` is the .NET BCL standard idiom — see `Utf8JsonReader` source.
</details>

<details>
<summary>6. Explain: `struct Point { public int X, Y; }`. Name three places a `Point` can live that are not the stack.</summary>

(1) **As a field of a class** — `class Node { Point P; }` puts `P`'s eight bytes inside `Node`'s heap object; there is no separate stack copy. (2) **As an array element** — `Point[] pts` is one contiguous heap block of `Point`s, no headers and no indirection per element. (3) **Captured by a lambda** — the local is *hoisted* into a compiler-generated display class on the heap and stops being a stack slot at all; the same happens to any local that lives across an `await`, which ends up in the state-machine object once the method suspends. And boxing makes a fourth: `object o = p` copies the bytes into a heap object with a header. The formulation to give an interviewer: a value type lives wherever its **storage location** lives; the language guarantees copy semantics and lifetime, not placement. "The stack is an implementation detail."
</details>

<details>
<summary>7. Diagnose: heap grows steadily across a deployment, working set follows, restarts "fix" it. Walk the investigation.</summary>

First classify: if `GCMemoryInfo.HeapSizeBytes` / `dotnet.gc.last_collection.heap.size` is growing it is managed retention; if the managed heap is flat while the working set climbs, it is native memory and none of the managed tooling applies. For managed: `dotnet-gcdump collect -p <pid>` **twice**, spaced under comparable load, and diff them — the delta names the type that grew, where a single dump cannot. Then `dotnet-dump analyze` on a full dump and `gcroot <address>` on one instance of that type, which prints the path back to a root. Roots are: live locals on any thread, statics and `[ThreadStatic]`, GC handles, the finalization queue, runtime internals. In application code the answer is usually a static — and the sneakiest static is an **event**, because `+=` stores a strong reference to the subscriber inside the publisher. Last step: classify again. If load stopping brings memory down, it was working set; if not and the root is an unbounded cache, the fix is an eviction policy, not a missing `Remove`.
</details>

<details>
<summary>8. Critique: "we made it allocation-free — the benchmark reports 0 B."</summary>

Ask three questions before accepting it. (1) **Which thread?** `[MemoryDiagnoser]` measures with `GC.GetAllocatedBytesForCurrentThread`, so anything the method offloads to the thread pool is invisible; a method whose body is `Task.Run(...)` can report `0 B` while allocating more than before. (2) **Which memory?** It counts *managed* allocation only — `stackalloc`, `NativeMemory.Alloc`, buffers held by a native library, and anything served from a warm `ArrayPool` all read as zero. `0 B` means "asked the GC for nothing", which is exactly the claim a pooled implementation makes, and it is compatible with a leaked rental. (3) **Which size?** Allocation that scales with input is invisible in a single-`N` benchmark; parameterise on size, and include one above 85,000 bytes if buffers are involved, because that is where the answer changes character. Then the follow-up that decides whether any of it matters: what fraction of a request does this method account for?
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
- Stephen Toub — *"Performance Improvements in .NET 8/9/10"* (devblogs) — single best resource on allocation reduction in modern .NET.
- Konrad Kokosa — *Pro .NET Memory Management* (Apress, 2018) — comprehensive coverage of GC, allocations, profiling.
- Adam Sitnik — [BenchmarkDotNet documentation](https://benchmarkdotnet.org/) and his blog on memory.
- *Writing High-Performance .NET Code* by Ben Watson — practical performance-engineering reference.

**Verified against these, for the specific claims on this page:**

- Microsoft Learn — [What's new in the .NET 10 runtime](https://learn.microsoft.com/en-us/dotnet/core/whats-new/dotnet-10/runtime) — stack allocation of small value-type and reference-type arrays, escape analysis for local struct fields and delegates, array interface devirtualization, Arm64 write-barrier changes.
- Microsoft Learn — [Garbage collector config settings](https://learn.microsoft.com/en-us/dotnet/core/runtime-config/garbage-collector) — `HeapHardLimit` / `HeapHardLimitPercent` (75% default in a memory-limited environment), `HighMemoryPercent` (90%), `LOHThreshold`, `RetainVM` (default `false`), region size and region range, and **DATAS enabled by default from .NET 9**.
- Microsoft Learn — [Workstation vs. server garbage collection](https://learn.microsoft.com/en-us/dotnet/standard/garbage-collection/workstation-server-gc) — "the host determines the default GC flavor", and workstation GC forced on a single-logical-CPU machine.
- Microsoft Learn — [`GCMemoryInfo`](https://learn.microsoft.com/en-us/dotnet/api/system.gcmemoryinfo) and [`GC.GetTotalPauseDuration`](https://learn.microsoft.com/en-us/dotnet/api/system.gc.gettotalpauseduration) (.NET 7+).
- Microsoft Learn — [.NET runtime built-in metrics](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/built-in-metrics-runtime) — the `System.Runtime` Meter instruments, all "available starting in .NET 9".
- Microsoft Learn — [`dotnet-counters`](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/dotnet-counters) — the `--counters provider[counter,…]` syntax.
- Microsoft Learn — [`ArrayPool<T>.Return`](https://learn.microsoft.com/en-us/dotnet/api/system.buffers.arraypool-1.return) — the `clearArray` contract and the double-free / use-after-free security note.
- dotnet/runtime source — `SharedArrayPool.cs` and `ConfigurableArrayPool.cs` (tiered per-thread / per-core design, bucket-length validation in `Return`, `GC.AllocateUninitializedArray` on the `Rent` miss path, gen-2 trimming), `ArrayPoolEventSource.cs` (event names and `BufferAllocatedReason`), `GC.CoreCLR.cs` (`AllocateArray` / `AllocateUninitializedArray` and the 2048-byte fallback), `StringBuilder.cs` (`m_ChunkPrevious` chunk list, `DefaultCapacity = 16`, `MaxChunkSize = 8000`, `ExpandByABlock`).
- Microsoft Learn — [`SearchValues<T>`](https://learn.microsoft.com/en-us/dotnet/api/system.buffers.searchvalues-1) and [`SearchValues.Create`](https://learn.microsoft.com/en-us/dotnet/api/system.buffers.searchvalues.create) — byte/char overloads .NET 8, the `ReadOnlySpan<string>` + `StringComparison` overload .NET 9 (Ordinal / OrdinalIgnoreCase only).
- Microsoft Learn — [Object reuse with `ObjectPool`](https://learn.microsoft.com/en-us/aspnet/core/performance/objectpool) — `ObjectPool<T>`, `ObjectPoolProvider`, `PooledObjectPolicy<T>`, `IResettable`, disposal semantics, and "it places a limit on the number of objects it retains".
- Microsoft Learn — [CA2014: Do not use `stackalloc` in loops](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/quality-rules/ca2014).
- Microsoft Learn — [What's new in C# 14](https://learn.microsoft.com/en-us/dotnet/csharp/whats-new/csharp-14) — implicit span conversions and modifiers on simple lambda parameters.
- Microsoft Learn — [`GC.KeepAlive`](https://learn.microsoft.com/en-us/dotnet/api/system.gc.keepalive) — premature reclamation while native code still holds a reference, and "code this method at the end, not the beginning".
- Microsoft Learn — [`GC.TryStartNoGCRegion`](https://learn.microsoft.com/en-us/dotnet/api/system.gc.trystartnogcregion) — all four overloads, the 2 × `totalSize` commit on the single-argument form, the ephemeral-segment limit, no nesting, and the `disallowFullBlockingGC` load-balancer pattern.
- Microsoft Learn — [`GCLatencyMode`](https://learn.microsoft.com/en-us/dotnet/api/system.runtime.gclatencymode) and [Latency modes](https://learn.microsoft.com/en-us/dotnet/standard/garbage-collection/latency) — `LowLatency` is workstation-only, `SustainedLowLatency` requires background GC and grows the heap, `NoGCRegion` is read-only.
- Microsoft Learn — [`GC.AddMemoryPressure`](https://learn.microsoft.com/en-us/dotnet/api/system.gc.addmemorypressure) — the finalizer-only caveat and "remove exactly the amount of pressure you add".
- Microsoft Learn — [`dotnet-gcdump`](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/dotnet-gcdump) and [`dotnet-dump`](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/dotnet-dump) — EventPipe-based graph capture on a live process, comparing snapshots, and the SOS commands (`dumpheap`, `gcroot`, `gchandles`, `finalizequeue`).
- Microsoft Learn — [`Dictionary<TKey,TValue>.EnsureCapacity`](https://learn.microsoft.com/en-us/dotnet/api/system.collections.generic.dictionary-2.ensurecapacity) (.NET Core 2.1+) — including the caution about capacity that comes from user input.
- Microsoft Learn — [`StructLayoutAttribute`](https://learn.microsoft.com/en-us/dotnet/api/system.runtime.interopservices.structlayoutattribute) — `Sequential` is the compiler default for structs, `Auto` for classes, and `Sequential` does not control managed layout for non-blittable types.
- Microsoft Learn — [How to define value equality for a type](https://learn.microsoft.com/en-us/dotnet/csharp/programming-guide/statements-expressions-operators/how-to-define-value-equality-for-a-type) — `ValueType.Equals` compares fields by reflection; `==` does not work on a struct unless overloaded.
- dotnet/runtime issue [#111283](https://github.com/dotnet/runtime/issues/111283) — "Interpolated string overloads of ILogger extensions", **closed as not planned**; the reason the `$"..."`-is-free-when-filtered claim is false for `Microsoft.Extensions.Logging`. Paired with [CA2254](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/quality-rules/ca2254).
- dotnet/roslyn PR [#35006](https://github.com/dotnet/roslyn/pull/35006) — "Avoid boxing in string concatenation": Roslyn calls `ToString()` on value-type operands rather than using the `object`-taking `string.Concat` overloads.
- dotnet/runtime source — `List.cs` (`DefaultCapacity = 4`, `Grow` doubling clamped to `Array.MaxLength`, the shared empty array), `DefaultInterpolatedStringHandler.cs` (`ArrayPool<char>.Shared` scratch buffer, `ToStringAndClear`), `ConcurrentQueueSegment.cs` (`PaddedHeadAndTail`, `PaddingHelpers.CACHE_LINE_SIZE` = 64, 128 on ARM64), CoreCLR `object.h` (`MIN_OBJECT_SIZE`, 24 bytes on x64).
- BenchmarkDotNet docs — [Diagnosers](https://benchmarkdotnet.org/articles/configs/diagnosers.html) (`MemoryDiagnoser` measures via `GC.GetAllocatedBytesForCurrentThread` in a separate run, ~99.5% accurate at default settings) and [Jobs](https://benchmarkdotnet.org/articles/configs/jobs.html) (adaptive warmup 6–50 and workload 15–100 iterations; the advice not to pin them).
- Eric Lippert — *"The stack is an implementation detail"* (Fabulous Adventures in Coding) — the canonical correction to "value types live on the stack".

</details>
<!-- nav-footer-start -->

---

[← Previous: Reflection, Attributes & Source Generators](08-reflection-attributes-and-source-gen.md) · [↑ Back to top](#memory--performance-idioms) · [Next: Data Structures & Algorithms (DSA) →](../06-dsa/README.md)

<!-- nav-footer-end -->
