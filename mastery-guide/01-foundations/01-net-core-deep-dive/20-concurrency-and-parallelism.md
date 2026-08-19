# Concurrency and Parallelism in .NET 10

> [Mastery Guide](../../../README.md) › [Foundations](../../README.md) › [.NET Core Deep Dive](README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 2 — Concurrency & DI | 2026-08-18 |

> 📘 **This page is the parallelism half of the concurrency story.** [Async/Await, Multithreading & Synchronization Primitives](03-async-and-threading.md) owns the async state machine, `ConfigureAwait`, sync-over-async deadlocks, `CancellationToken`, and `IAsyncEnumerable<T>`. None of that is repeated here. What lives here is the *other* half: the TPL's data-parallel APIs, PLINQ, partitioning, producer/consumer pipelines, the concurrent collections' real guarantees, and — the part almost nobody can defend under questioning — **the .NET memory model**.

---

## Why It Matters

Two words get used interchangeably in interviews and they are not the same thing.

**Concurrency is dealing with many things at once.** It is a *structuring* property. A web server handling 10,000 open connections on eight cores is concurrent: at any instant almost all of those requests are parked waiting for a database, a downstream API, or a socket. Nothing about that needs more than one core. What it needs is a way to *not hold a thread* while waiting — which is exactly what `async`/`await` and the I/O completion machinery give you.

**Parallelism is doing many things at once.** It is an *execution* property. Resizing 4,000 images, scoring a risk model over 200,000 rows, computing a checksum over a 2 GB file — these are CPU-bound, and the only way to finish sooner is to put more cores on the problem simultaneously. That is what the TPL's `Parallel` class and PLINQ exist for.

Conflating the two is why people reach for `Parallel.ForEach` over a list of URLs and then wonder why the app got *slower* and the unrelated endpoints started timing out. `Parallel.ForEach` is a data-parallel construct: it hands each item to a synchronous delegate on a pool thread and expects that delegate to burn CPU. Give it I/O and every one of those pool threads parks in a blocking wait, the pool's starvation-avoidance logic starts injecting replacement threads slowly, and you have converted a problem the runtime solves for free (async I/O) into thread-pool starvation you now have to debug.

The reverse mistake is quieter but just as real: wrapping a genuinely CPU-bound loop in `async` and `await`, adding state-machine overhead and continuation hops to work that never yields, and getting no concurrency in return because there was never anything to wait for.

Senior interviews probe the seams. *Why is your PLINQ query slower than the `foreach`? What does `ConcurrentDictionary.GetOrAdd` actually guarantee? Why does this flag never get seen by the worker thread? Why is `Volatile.Read` in that double-checked lock and what breaks if I delete it? Why is your counter array slower with eight threads than with one?* Those are the questions this page answers.

---

## Table of Contents

1. [Concurrency vs Parallelism — the distinction that picks your API](#concurrency-vs-parallelism--the-distinction-that-picks-your-api)
2. [Real-World Analogy: One Chef, Four Chefs, and a Slow Oven](#real-world-analogy-one-chef-four-chefs-and-a-slow-oven)
3. [The Data-Parallel Family: Parallel.For, ForEach, ForEachAsync](#the-data-parallel-family-parallelfor-foreach-foreachasync)
4. [MaxDegreeOfParallelism — what the number actually means](#maxdegreeofparallelism--what-the-number-actually-means)
5. [Thread-Local Accumulation and Loop Control](#thread-local-accumulation-and-loop-control)
6. [Why Parallel.ForEach Over I/O Is Usually Wrong](#why-parallelforeach-over-io-is-usually-wrong)
7. [PLINQ — AsParallel, Ordering, and Why It's Often Slower](#plinq--asparallel-ordering-and-why-its-often-slower)
8. [Partitioning — the hidden variable in every data-parallel loop](#partitioning--the-hidden-variable-in-every-data-parallel-loop)
9. [Producer/Consumer: Channel&lt;T&gt;, TPL Dataflow, and plain ConcurrentQueue](#producerconsumer-channelt-tpl-dataflow-and-plain-concurrentqueue)
10. [Concurrent Collections — the guarantees and the gaps](#concurrent-collections--the-guarantees-and-the-gaps)
11. [Synchronisation Primitives from the Parallel Side](#synchronisation-primitives-from-the-parallel-side)
12. [The .NET Memory Model](#the-net-memory-model)
13. [Double-Checked Locking, Correctly](#double-checked-locking-correctly)
14. [False Sharing](#false-sharing)
15. [Decision Matrix — which construct when](#decision-matrix--which-construct-when)
16. [Common Pitfalls](#common-pitfalls)
17. [Best Practices](#best-practices)
18. [Real-World Scenarios](#real-world-scenarios)
19. [Interview-Ready Summary](#interview-ready-summary)
20. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
21. [Cheat Sheet](#cheat-sheet)
22. [Walkthrough](#walkthrough)
23. [Self-Test](#self-test)
24. [Cross-References](#cross-references)
25. [Sources](#sources)

---

## Concurrency vs Parallelism — the distinction that picks your API

The clean statement — Rob Pike's, and worth memorising verbatim because interviewers recognise it — is *"concurrency is about dealing with lots of things at once; parallelism is about doing lots of things at once."* Concurrency is a property of your program's **structure**; parallelism is a property of its **execution**.

The consequence for .NET is direct:

```
                    Is the work waiting, or working?
                    ─────────────────────────────────────────────

   I/O-BOUND (waiting on something else)
   ┌──────────────────────────────────────────────────────────┐
   │ HTTP calls · DB queries · file reads · message brokers    │
   │                                                           │
   │ Goal: hold ZERO threads while waiting                     │
   │ Tool: async/await, Task.WhenAll, Parallel.ForEachAsync,   │
   │       Channel<T>, IAsyncEnumerable<T>                     │
   │ Scaling limit: the remote system, not your cores          │
   │ Adding cores: does nothing                                │
   └──────────────────────────────────────────────────────────┘

   CPU-BOUND (actually executing instructions)
   ┌──────────────────────────────────────────────────────────┐
   │ hashing · parsing · image ops · scoring · compression     │
   │                                                           │
   │ Goal: keep every core busy, minimise coordination         │
   │ Tool: Parallel.For/ForEach, PLINQ, Task.Run fan-out       │
   │ Scaling limit: cores, memory bandwidth, cache             │
   │ Adding cores: helps, up to a point                        │
   └──────────────────────────────────────────────────────────┘

   MIXED (per item: fetch, then compute, then store)
   ┌──────────────────────────────────────────────────────────┐
   │ Tool: Parallel.ForEachAsync (async body, DOP cap), or a   │
   │       pipeline — Channel<T> / Dataflow — with a separate  │
   │       degree of parallelism per stage                     │
   └──────────────────────────────────────────────────────────┘
```

### The mapping, stated plainly

| Question | Concurrency answer | Parallelism answer |
|---|---|---|
| What am I optimising? | Thread *occupancy* — don't hold one while waiting | Wall-clock time on CPU work |
| Core primitive | `Task` + `await` (a continuation, no thread) | `Parallel` / PLINQ (a partitioned workload on pool threads) |
| Does it help on one core? | **Yes** — that's the whole point | No |
| Does it help with I/O? | Yes | No — it just blocks more threads |
| Failure mode when misapplied | State-machine overhead on work that never yields | Thread-pool starvation, or slower-than-sequential |
| Cancellation | `CancellationToken` through the call chain | `ParallelOptions.CancellationToken` / `WithCancellation` |

> 🌐 **Real-world example — an "optimisation" that halved throughput.** A reporting service generated 400 PDFs per night by calling a rendering library (pure CPU) and then uploading each to blob storage (pure I/O), in one `Parallel.ForEach` body. The upload dominated the wall clock, so every pool thread spent most of its life blocked in a synchronous `Upload()` call. **Decision:** split the stages — render with `Parallel.ForEach` bounded by `Environment.ProcessorCount`, then upload with `Parallel.ForEachAsync` and a separate, higher degree of parallelism, since concurrent uploads cost no threads. **Consequence:** the CPU stage saturated the cores it deserved and the I/O stage stopped competing with it for pool threads. The lesson is not "parallel is bad" — it's that *one loop cannot be tuned for two different bottlenecks*.

> ⚠️ **The trap answer.** "Concurrency is multithreading" is wrong and interviewers wait for it. A single-threaded event loop is concurrent. A `Parallel.For` on a one-core container is parallel *code* that executes with no parallelism. The words describe intent and execution, not thread counts.

---

## Real-World Analogy: One Chef, Four Chefs, and a Slow Oven

```
┌──────────────────────────────────────────────────────────────┐
│                     THE RESTAURANT KITCHEN                    │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  CONCURRENCY — one chef, many dishes in flight               │
│  ┌────────────────────────────────────────────────────┐      │
│  │ Chef puts the roast in the oven (45 min)           │      │
│  │  → does NOT stand and watch it                     │      │
│  │ Chef chops salad, plates a starter, stirs a sauce  │      │
│  │ Oven timer dings → chef returns to the roast       │      │
│  │                                                    │      │
│  │ ONE chef. FIVE dishes progressing. No extra staff. │      │
│  │ = async/await. The oven is the I/O device.         │      │
│  └────────────────────────────────────────────────────┘      │
│                                                              │
│  PARALLELISM — four chefs, one enormous prep job             │
│  ┌────────────────────────────────────────────────────┐      │
│  │ 400 onions must be diced. Nobody is waiting on     │      │
│  │ anything — the work IS the work.                   │      │
│  │ Split 100 onions to each of four chefs.            │      │
│  │                                                    │      │
│  │ FOUR chefs. ONE job. Finishes ~4× sooner if the    │      │
│  │ split is even and they don't queue for one knife.  │      │
│  │ = Parallel.ForEach. The knife is the shared lock.  │      │
│  └────────────────────────────────────────────────────┘      │
│                                                              │
│  THE CLASSIC BLUNDER                                         │
│  ┌────────────────────────────────────────────────────┐      │
│  │ Hire four chefs and have all four stand watching   │      │
│  │ four ovens. You pay for four chefs; the roast      │      │
│  │ still takes 45 minutes.                            │      │
│  │ = Parallel.ForEach over I/O.                       │      │
│  └────────────────────────────────────────────────────┘      │
│                                                              │
│  THE COORDINATION TAX                                        │
│  ┌────────────────────────────────────────────────────┐      │
│  │ Four chefs, ONE cutting board. Three wait while    │      │
│  │ one chops. Slower than one chef working alone,     │      │
│  │ because now you also pay for the handoffs.         │      │
│  │ = a contended lock inside a parallel loop.         │      │
│  └────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────┘
```

| Kitchen | .NET |
|---|---|
| Chef | Thread-pool thread |
| Oven (you wait, you don't work) | I/O device + completion port |
| Timer ding | I/O completion → continuation scheduled |
| Splitting 400 onions four ways | Partitioning |
| Everyone gets exactly 100 onions | Range partitioning (static) |
| "Grab another tray when you're free" | Chunk partitioning (load-balancing) |
| The one shared cutting board | Contended lock / shared mutable state |
| Two chefs' elbows colliding at one board | False sharing on one cache line |
| Head chef caps the line at four | `MaxDegreeOfParallelism` |

---

## The Data-Parallel Family: Parallel.For, ForEach, ForEachAsync

Three methods, three different contracts. Getting the contract wrong is the single most common TPL bug.

```csharp
// 1. Parallel.For — an indexed range, synchronous body
Parallel.For(0, pixels.Length, i =>
{
    pixels[i] = Desaturate(pixels[i]);       // pure CPU, no shared writes
});

// 2. Parallel.ForEach — any IEnumerable<T>, synchronous body
Parallel.ForEach(documents, doc =>
{
    doc.Checksum = Sha256(doc.Bytes);        // pure CPU
});

// 3. Parallel.ForEachAsync (.NET 6+) — async body, awaited properly
await Parallel.ForEachAsync(urls, ct, async (url, token) =>
{
    var html = await _http.GetStringAsync(url, token);
    await _store.SaveAsync(url, html, token);
});
```

### The contract differences that matter

| | `Parallel.For` / `ForEach` | `Parallel.ForEachAsync` |
|---|---|---|
| Body delegate | `Action<T>` (or `Action<T, ParallelLoopState>`) | `Func<TSource, CancellationToken, ValueTask>` |
| Returns | `ParallelLoopResult` (a struct, synchronously) | `Task` — **not** `Task<T[]>` |
| Blocks the caller | **Yes** — it is a synchronous method | No — you `await` it |
| Source | `IEnumerable<T>` / index range | `IEnumerable<T>` **or `IAsyncEnumerable<T>`** |
| Default degree of parallelism | Whatever the scheduler provides; `MaxDegreeOfParallelism` defaults to `-1` = *no limit* | `ProcessorCount` — "the operation will execute at most `ProcessorCount` operations in parallel" |
| Loop control (`Break`/`Stop`) | Yes, via `ParallelLoopState` | No — cancel the token instead |
| Thread-local accumulation | Yes, via `localInit` / `localFinally` overloads | No — write to a concurrent collection |
| Exceptions | Aggregated into `AggregateException` | Faults the returned `Task` |
| Right for | CPU-bound work | I/O-bound or mixed work |

> ⚠️ **The `async` lambda trap.** This compiles, runs instantly, and does nothing you can observe:
>
> ```csharp
> // ❌ The lambda binds to Action<string>. An async lambda returning void
> //    is `async void`: nothing awaits it, nothing observes its exceptions,
> //    and the loop "completes" the moment every body has been *started*.
> Parallel.ForEach(urls, async url =>
> {
>     await _http.GetStringAsync(url);
> });
> ```
>
> There is no compiler error because `async void` is a legal conversion target for `Action<T>`. The fix is not a cleverer lambda — it is `Parallel.ForEachAsync`, whose body is `Func<T, CancellationToken, ValueTask>` and is therefore genuinely awaited. This is a favourite interview question precisely because the code *looks* right.

### Collecting results

`Parallel.ForEachAsync` returns `Task`, not `Task<T[]>`, so there is nothing to unpack. Write into a thread-safe collection from inside the body:

```csharp
var results = new ConcurrentBag<Report>();
await Parallel.ForEachAsync(items, options, async (item, ct) =>
{
    results.Add(await ProcessAsync(item, ct));
});
```

`ConcurrentBag<T>` is unordered. `ConcurrentQueue<T>` gives you FIFO *completion* order. **Neither restores input order.** If callers need results aligned to the input sequence, use `SemaphoreSlim` + `Task.WhenAll`, which returns an array in input order — that is the one case where the older pattern still wins.

The same applies to `Parallel.For`: never write to a shared `List<T>` from a parallel body. `List<T>.Add` is not thread-safe; the failure is not a clean exception but a silently corrupted backing array or a lost element.

```csharp
// ❌ Data race — List<T> is not thread-safe
var results = new List<double>();
Parallel.For(0, n, i => results.Add(Score(i)));

// ✅ Pre-sized array, index-addressed, no synchronisation at all
var results = new double[n];
Parallel.For(0, n, i => results[i] = Score(i));
```

The second form is the better answer in an interview and in production: **distinct array slots written by distinct iterations need no synchronisation whatsoever**, because each element is a separate location. (Watch for [false sharing](#false-sharing) if the elements are small and the work per element is tiny — but correctness is not at risk.)

### Exceptions

`Parallel.For`/`ForEach` let every already-started iteration finish, collect everything that threw, and surface one `AggregateException`:

```csharp
try
{
    Parallel.ForEach(files, f => Process(f));   // 3 of 900 throw
}
catch (AggregateException ex)
{
    foreach (var inner in ex.Flatten().InnerExceptions)
        _log.LogError(inner, "file failed");
}
```

`Flatten()` matters: nested parallel constructs produce nested `AggregateException` trees. `Parallel.ForEachAsync` faults its returned `Task` instead, so `await` rethrows the first exception in the usual way — see [Async exception handling](03-async-and-threading.md#async-exception-handling--the-aggregateexception-trap) for why `await` and `.Result` differ there.

---

## MaxDegreeOfParallelism — what the number actually means

This is the most misread property in the TPL, and the docs are unambiguous once you read them:

> "A positive property value limits the number of concurrent operations to the set value. If it is `-1`, there is no limit on the number of concurrently running operations (**with the exception of the `ForEachAsync` method, where `-1` means `ProcessorCount`**)."
> — [`ParallelOptions.MaxDegreeOfParallelism`](https://learn.microsoft.com/dotnet/api/system.threading.tasks.paralleloptions.maxdegreeofparallelism)

Three consequences people get wrong:

1. **It is a ceiling, not a target.** The docs continue: "By default, `For` and `ForEach` will utilize however many threads the underlying scheduler provides, so changing `MaxDegreeOfParallelism` from the default only limits how many concurrent tasks will be used." Setting it to 16 does not summon 16 threads; it forbids a 17th.
2. **The default is not `ProcessorCount` for `For`/`ForEach`.** It is `-1`, meaning unlimited — the pool decides. For `ForEachAsync` the effective default *is* `ProcessorCount`, which is documented on the overloads that take no `ParallelOptions`: "The operation will execute at most `ProcessorCount` operations in parallel."
3. **`0` throws.** The property throws `ArgumentOutOfRangeException` when set to zero or to anything less than `-1`. `Math.Max(1, someComputedValue)` is worth writing.

### When to set it, per the docs

Microsoft's own list of legitimate reasons is short:

- the algorithm does not scale past a known number of cores;
- you are running several algorithms concurrently and want to divide the machine deliberately;
- "the thread pool's heuristics is unable to determine the right number of threads to use and could end up injecting too many threads… in long-running loop body iterations, the thread pool might not be able to tell the difference between reasonable progress or livelock or deadlock."

Everything else is guesswork. There is a fourth reason the docs do not cover because it is not a runtime concern: **protecting a downstream dependency.** A cap of 8 on an I/O loop is often about the remote API's rate limit, not about your cores.

### `Environment.ProcessorCount` is container-aware — and frozen at startup

```csharp
var options = new ParallelOptions
{
    MaxDegreeOfParallelism = Environment.ProcessorCount,
    CancellationToken = ct
};
```

Per the docs, on Linux and macOS for all .NET versions, and on Windows from .NET 6, `Environment.ProcessorCount` returns the **minimum** of: the machine's logical processor count; the count the process is affinitised to, if any; and "if the process is running with a CPU utilization limit, the CPU utilization limit rounded up to the next whole number." It is also **"fixed at .NET runtime startup for the process lifetime."**

> 🌐 **Real-world example — a `MaxDegreeOfParallelism` of 64 on a 0.5-CPU pod.** A batch service hard-coded `MaxDegreeOfParallelism = 64` because the build machine had 32 cores. In Kubernetes it ran with `limits.cpu: 500m`. Sixty-four CPU-bound tasks were admitted onto half a core's worth of quota; the container spent its life being CPU-throttled by the cgroup, and p99 latency for the co-hosted HTTP endpoints went through the roof. **Decision:** replace the constant with `Environment.ProcessorCount`, which already rounds the 0.5 quota up to 1. **Consequence:** the loop ran with a degree of parallelism of one — slower on paper, dramatically faster in practice, because nothing was throttled any more. The general rule: **derive the cap from the runtime, never from the developer's laptop.**

> ⚠️ Because the value is fixed at startup, changing a container's CPU limit *while the process is running* (a vertical-scaling event) will not be observed. If you need to react, you must restart. And `DOTNET_PROCESSOR_COUNT` can override the computed value — useful for pinning behaviour in tests, dangerous if someone sets it in a Helm chart and forgets.

---

## Thread-Local Accumulation and Loop Control

### The aggregation overload

Naively aggregating in a parallel loop means every iteration touching one shared variable — which needs synchronisation, and that synchronisation serialises the loop you just parallelised. `Parallel.For` and `Parallel.ForEach` have a dedicated overload for this: each participating task gets its own local accumulator (`localInit`), the body folds into it, and `localFinally` merges once per task at the end.

```csharp
long total = 0;

Parallel.For(
    fromInclusive: 0,
    toExclusive: values.Length,
    localInit: () => 0L,                        // per-task accumulator
    body: (i, state, localSum) => localSum + Weight(values[i]),
    localFinally: local => Interlocked.Add(ref total, local));  // merged once per task
```

The shape is worth memorising: `body` **returns** the new local value rather than mutating a captured variable, and `localFinally` is the *only* place that touches shared state. If there are eight participating tasks, there are eight `Interlocked.Add` calls in total — not eight million.

> 🌐 **Real-world example — a "parallel" sum that ran slower than `foreach`.** A pricing engine summed 12 million line-item weights inside `Parallel.For` with `lock (_gate) { total += w; }`. Every iteration took and released a lock; the cache line holding `total` bounced between cores on every single add. **Decision:** switch to the `localInit`/`localFinally` overload. **Consequence:** the shared write went from once per element to once per participating task, and the loop finally scaled with cores. Measure your own numbers — but the mechanism is not in doubt: **the fix is not a faster lock, it is fewer shared writes.**

### `Break()` vs `Stop()`

`ParallelLoopState` is handed to your body by the runtime; you cannot construct one. Two methods end a loop early, and the difference is exam material:

| | `Stop()` | `Break()` |
|---|---|---|
| Meaning | "Cease execution at the system's earliest convenience" | "Cease execution of iterations **beyond the current iteration**" |
| Iterations with a lower index | May be abandoned | **Guaranteed to run** |
| Use for | "Any match will do" — existence checks | "Everything up to here" — ordered scans |
| Result surface | `ParallelLoopResult.IsCompleted == false` | `ParallelLoopResult.LowestBreakIteration` has a value |

Neither affects iterations that **have already begun**, which is the detail people miss. A long-running body must cooperate:

```csharp
var result = Parallel.For(0, records.Length, (i, state) =>
{
    if (state.ShouldExitCurrentIteration &&
        state.LowestBreakIteration is long lowest && lowest < i)
        return;                                  // someone broke below us; bail out

    if (IsCorrupt(records[i]))
    {
        state.Break();                           // stop everything after index i
        return;
    }

    Process(records[i]);
});

if (result.LowestBreakIteration is long stoppedAt)
    _log.LogWarning("Halted at record {Index}", stoppedAt);
```

`ShouldExitCurrentIteration` is the single property to poll: it is true if any iteration called `Break()` or `Stop()`, **or threw**. `IsExceptional` and `IsStopped` narrow it down if you need to distinguish.

> 🌐 **Real-world example — `Stop()` where `Break()` was meant.** A ledger validator scanned transactions in order looking for the first bad entry, calling `state.Stop()` on a hit. Because `Stop()` abandons lower-index iterations too, the reported "first bad transaction" varied run to run — sometimes index 4,102, sometimes 3,880, depending on scheduling. **Decision:** `Break()` plus reading `ParallelLoopResult.LowestBreakIteration`. **Consequence:** deterministic reporting, because `Break()` guarantees every iteration below the break point still runs. The general rule: **if the index has meaning, you want `Break()`; if it does not, `Stop()` is cheaper.**

---

## Why Parallel.ForEach Over I/O Is Usually Wrong

Four mechanisms stack up. Any one of them would be enough.

```
Parallel.ForEach(urls, url => {              ← Action<string>: the body MUST block
    var html = _http.GetStringAsync(url).Result;   ← pool thread parked here
    _store.Save(url, html);                        ← ...and here
});

  1. The delegate type forces blocking.
     Action<T> has nowhere to put a Task. Your only options are .Result,
     .Wait(), or a synchronous API. All three park a pool thread for the
     entire duration of the network round trip.

  2. Blocked threads defeat the pool's own scaling.
     A parked thread is invisible progress. The pool responds by injecting
     more threads, but injection is deliberately gradual (see the thread-pool
     starvation section on the async page). Your effective degree of
     parallelism ramps over seconds, not milliseconds.

  3. The default cap is "no limit".
     MaxDegreeOfParallelism defaults to -1 for For/ForEach — documented as
     "no limit on the number of concurrently running operations". So the
     loop keeps asking for more capacity while every thread it gets goes
     straight into a blocking wait.

  4. The damage is process-wide.
     There is one thread pool per process. The starved threads are the same
     ones serving your HTTP endpoints, your health check, and your logging
     flush. The symptom is never "the batch job is slow" — it is "unrelated
     endpoints time out during the nightly batch".
```

The fix is `Parallel.ForEachAsync`, whose body is `Func<T, CancellationToken, ValueTask>`. An awaiting body holds **no thread** while the I/O is outstanding, so the degree of parallelism is a real concurrency budget rather than a thread budget:

```csharp
await Parallel.ForEachAsync(
    urls,
    new ParallelOptions { MaxDegreeOfParallelism = 32, CancellationToken = ct },
    async (url, token) =>
    {
        var html = await _http.GetStringAsync(url, token);
        await _store.SaveAsync(url, html, token);
    });
```

Note that 32 here is a *concurrency* cap chosen to protect the remote server and the connection pool. It is unrelated to core count, and there is no reason it should equal `Environment.ProcessorCount` — that is the tell that you are reasoning about the problem correctly.

> 🌐 **Real-world example — 3,000 supplier endpoints.** A warehouse sync polled 3,000 supplier APIs nightly with `Parallel.ForEach` and a synchronous HTTP client. The job took hours, the pod's thread count climbed steadily all night, and the order-placement API — same process — started returning 504s at 02:00 every day. **Decision:** `Parallel.ForEachAsync` with `MaxDegreeOfParallelism = 24`, chosen because the shared egress proxy allowed 25 concurrent connections. **Consequence:** the thread count flattened, the 504s stopped, and the sync finished faster despite a *lower* nominal degree of parallelism — because it was no longer competing with itself for threads. The 24 came from the proxy's documented limit, not from a benchmark.

> ✅ **When `Parallel.ForEach` over I/O is defensible.** A console tool or a one-shot migration utility with nothing else in the process, calling a library that genuinely has no async API. There is no other traffic to starve, and `Parallel.ForEachAsync` cannot help you await a method that does not exist. Say this out loud in an interview — the absolutist answer ("never") is less convincing than the conditional one.

---

## PLINQ — AsParallel, Ordering, and Why It's Often Slower

PLINQ turns a LINQ-to-Objects query into a partitioned, multi-task query with a single operator:

```csharp
var scores = records
    .AsParallel()
    .WithDegreeOfParallelism(8)
    .WithCancellation(ct)
    .Where(r => r.IsActive)
    .Select(r => new { r.Id, Score = ExpensiveModel(r) })   // the delightfully parallel part
    .ToArray();                                              // the merge
```

### The operator surface worth knowing

| Operator | What it does | Gotcha |
|---|---|---|
| `AsParallel()` | Switches to `ParallelQuery<T>`; every downstream operator resolves to `ParallelEnumerable` | Silently reverts to sequential for [certain query shapes](#when-plinq-quietly-goes-sequential) |
| `AsSequential()` | Switches back — everything after runs on one thread | Use it to bracket a stage that must be serial |
| `AsOrdered()` / `AsUnordered()` | Preserve / stop preserving source order | `AsOrdered()` is sticky until `AsUnordered()` |
| `WithDegreeOfParallelism(n)` | Caps concurrent tasks | Throws `ArgumentOutOfRangeException` if `n < 1` **or `n > 512`**, and `InvalidOperationException` if used twice in one query |
| `WithExecutionMode(ParallelExecutionMode.ForceParallelism)` | Overrides the sequential-fallback analysis | Only after you have measured |
| `WithMergeOptions(...)` | `NotBuffered` / `AutoBuffered` / `FullyBuffered` | Latency vs throughput, not correctness |
| `WithCancellation(ct)` | Cooperative cancellation | Throws `OperationCanceledException`, not `AggregateException` |
| `ForAll(action)` | Runs the action per element **without merging** | No ordering, no return value — the fastest terminal operator |

### Why most PLINQ queries are slower than the sequential version

Microsoft's own guidance is the clearest statement of the mechanism:

> "PLINQ must still partition the data source and schedule the work on the threads, and usually merge the results when the query completes. All these operations add to the computational cost of parallelization; these costs of adding parallelization are called *overhead*."
> — [Understanding Speedup in PLINQ](https://learn.microsoft.com/dotnet/standard/parallel-programming/understanding-speedup-in-plinq)

Concretely, five costs that a `foreach` does not pay:

1. **Partitioning.** Someone has to decide who processes what — see [Partitioning](#partitioning--the-hidden-variable-in-every-data-parallel-loop).
2. **Task scheduling.** Queueing, dequeueing, and possibly stealing work items.
3. **Merging.** "If you are storing the results of a query by calling `ToArray` or `ToList`, then the results from all parallel threads must be merged into the single data structure. This involves an unavoidable computational cost. Likewise, if you iterate the results by using a `foreach` loop, the results from the worker threads need to be serialized onto the enumerator thread."
4. **Delegate indirection.** Every element passes through a delegate call — the same tax `Parallel.For` pays, and the reason range partitioning exists.
5. **Ordering and grouping.** "PLINQ provides the `AsOrdered` operator for situations in which it is necessary to maintain the order of elements in the source sequence. There is a cost associated with ordering, but this cost is usually modest. `GroupBy` and `Join` operations likewise incur overhead."

The docs' own rule of thumb is the one to quote: *"small source collections with trivial delegates are generally not good candidates for PLINQ."* The work per element has to be large enough that parallel execution can pay back the fixed costs.

```csharp
// ❌ Almost certainly slower than the sequential version.
//    Trivial delegate, cheap predicate, and now you pay for
//    partitioning + scheduling + merging to save a few nanoseconds
//    of arithmetic per element.
var odds = numbers.AsParallel().Where(n => n % 2 > 0).ToList();

// ✅ A plausible candidate: the delegate dominates the overhead.
var scored = applications.AsParallel().Select(a => RunCreditModel(a)).ToList();
```

### When PLINQ quietly goes sequential

> "PLINQ will always attempt to execute a query at least as fast as the query would run sequentially… it looks for query operators or combinations of operators that typically cause a query to execute more slowly in parallel mode. When it finds such shapes, PLINQ by default falls back to sequential mode."

The documented shapes:

- `Select`, indexed `Where`, indexed `SelectMany`, or `ElementAt` **after** an ordering or filtering operator that removed or rearranged the original indices;
- `Take`, `TakeWhile`, `Skip`, `SkipWhile` where the source indices are no longer in original order;
- `Zip` or `SequenceEquals`, unless one source has an originally ordered index and the other is indexable;
- `Concat`, unless applied to indexable sources;
- `Reverse`, unless applied to an indexable source.

This is a *feature*, and it is also why "I added `.AsParallel()` and nothing changed" is a common and completely unmysterious bug report. `WithExecutionMode(ParallelExecutionMode.ForceParallelism)` overrides it — after you have measured, not before.

### Ordering

`AsParallel()` produces results in whatever order they finish. `AsOrdered()` restores source order, which the runtime achieves by tracking ordinal indices through every operator and reassembling at the merge.

```csharp
// Unordered — fastest, correct if the consumer doesn't care
var thumbs = photos.AsParallel().Select(Resize).ToList();

// Ordered — output aligns with `photos`
var thumbs = photos.AsParallel().AsOrdered().Select(Resize).ToList();

// Ordered where it matters, unordered where it doesn't
var top = photos.AsParallel()
                .AsOrdered()
                .Where(p => p.IsPublic)      // order preserved through the filter
                .AsUnordered()               // release the constraint...
                .Select(Score)               // ...for the expensive stage
                .ToList();
```

> 🌐 **Real-world example — an ordered report that didn't need to be.** A month-end export ran `AsParallel().AsOrdered()` over 180,000 rows, then handed the result to a writer that sorted by account number anyway. The ordering constraint was carried through the whole query for nothing. **Decision:** drop `AsOrdered()`; the downstream sort was the real contract. **Consequence:** the merge stage stopped buffering to reassemble order. The general point: **`AsOrdered()` is a requirement, not a safety net — if a later `OrderBy` exists, the earlier ordering is pure cost.**

### Exceptions and cancellation

```csharp
try
{
    var results = source.AsParallel().WithCancellation(ct).Select(Risky).ToList();
}
catch (OperationCanceledException) { /* the token fired */ }
catch (AggregateException ex)
{
    foreach (var inner in ex.Flatten().InnerExceptions) _log.LogError(inner, "…");
}
```

PLINQ wraps user-delegate exceptions in `AggregateException`, exactly like `Parallel.For`. Cancellation via `WithCancellation` surfaces as `OperationCanceledException` instead — catch both, and catch them in that order.

> ⚠️ **PLINQ is synchronous by design.** There is no `AsParallelAsync`. Any `await` inside a PLINQ delegate has to become `.Result` or `.GetAwaiter().GetResult()`, which reintroduces every problem in [Why Parallel.ForEach over I/O is wrong](#why-parallelforeach-over-io-is-usually-wrong). For async batch work the answer is `Parallel.ForEachAsync`, full stop.

---

## Partitioning — the hidden variable in every data-parallel loop

Every data-parallel construct has to answer one question before it can run: *who processes which elements?* That is partitioning, and it is the difference between a loop that scales and one that does not. Both PLINQ and `Parallel.ForEach` ship default partitioners; you only reach for `System.Collections.Concurrent.Partitioner` when the default's assumptions are wrong for your data.

### Range vs chunk — the two strategies

```
RANGE PARTITIONING (static)
  Source: an array or IList — length known up front
  ┌─────────────┬─────────────┬─────────────┬─────────────┐
  │  0 … 24 999 │ 25k … 49 999│ 50k … 74 999│ 75k … 99 999│
  └──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┘
      Task 1        Task 2        Task 3        Task 4

  + Zero synchronisation after the initial split
  + Cheapest possible partitioning
  − "if one thread finishes early, it cannot help the other threads"
    → catastrophic when per-element cost is uneven

CHUNK PARTITIONING (dynamic, load-balancing)
  Source: anything, including IEnumerable of unknown length
  ┌───────────────────────────────────────────────────────┐
  │  [chunk] [chunk] [chunk] [chunk] [chunk] [chunk] …    │
  └───────────────────────────────────────────────────────┘
      ↑ each task takes a chunk, processes it, comes back

  + "inherently load-balancing because the assignment of elements
     to threads is not pre-determined"
  − "the partitioner does incur the synchronization overhead each
     time the thread needs to get another chunk"
  − "The amount of synchronization incurred… is inversely
     proportional to the size of the chunks"
```

Both quotes are verbatim from [Custom Partitioners for PLINQ and TPL](https://learn.microsoft.com/dotnet/standard/parallel-programming/custom-partitioners-for-plinq-and-tpl). That last line *is* the chunk-size trade-off in one sentence: **small chunks balance well and synchronise often; large chunks synchronise rarely and balance badly.**

The docs' own summary of when each wins:

> "In general, range partitioning is only faster when the execution time of the delegate is small to moderate, and the source has a large number of elements, and the total work of each partition is roughly equivalent. Chunk partitioning is therefore generally faster in most cases."

### What the defaults actually do

| Construct | Source | Default strategy |
|---|---|---|
| PLINQ | array / `IList<T>` | **Range, no load balancing** — "By default when it is passed an IList or an array, PLINQ always uses range partitioning without load balancing" |
| PLINQ | `IEnumerable<T>` | Chunk |
| `Parallel.ForEach` | any | Supports dynamic partitions; "whenever the loop adds a new parallel task, it requests a new partition for that task" |

That PLINQ row is the one that bites. Handed an array, PLINQ splits it into equal *index ranges* — and if element 7 costs 500 ms while elements 8 through 99,999 cost 50 µs each, one task grinds while the rest sit idle.

### Turning load balancing on for PLINQ

`Partitioner.Create` is the switch. The overload table is worth carrying in your head:

| Overload | Uses load balancing |
|---|---|
| `Create<TSource>(IEnumerable<TSource>)` | **Always** |
| `Create<TSource>(TSource[], bool)` | When the `bool` is `true` |
| `Create<TSource>(IList<TSource>, bool)` | When the `bool` is `true` |
| `Create(int, int)` / `Create(int, int, int)` | **Never** (range partitioner) |
| `Create(long, long)` / `Create(long, long, long)` | **Never** (range partitioner) |

```csharp
// Skewed per-element cost over an array: force chunk partitioning
var balanced = Partitioner.Create(records, loadBalance: true);

var results = balanced.AsParallel()
                      .Select(RunModel)
                      .ToArray();
```

### The other direction: killing delegate-invocation cost

The opposite problem is a body so cheap that the *delegate call itself* dominates. The docs are explicit: "The cost of invoking that delegate is about the same as a virtual method call. In some scenarios, the body of a parallel loop might be small enough that the cost of the delegate invocation on each loop iteration becomes significant."

The fix is to parallelise over *ranges* and put a plain `for` inside:

```csharp
var rangePartitioner = Partitioner.Create(0, source.Length);   // Tuple<int,int> ranges

Parallel.ForEach(rangePartitioner, range =>
{
    // ONE delegate invocation per range, not per element
    for (int i = range.Item1; i < range.Item2; i++)
        results[i] = source[i] * Math.PI;
});
```

`Partitioner.Create(int fromInclusive, int toExclusive)` lets the partitioner size the ranges; the three-argument overload `Create(int, int, int rangeSize)` lets you dictate the chunk size directly — "This overload can be used in scenarios where the work per element is so low that even one virtual method call per element has a noticeable impact on performance."

> 🌐 **Real-world example — a per-pixel filter that would not scale.** A convolution pass ran `Parallel.For(0, pixels.Length, i => …)` over a 24-megapixel image. The body was a handful of arithmetic operations, so the loop spent a large share of its time in delegate dispatch and range bookkeeping rather than in the filter. **Decision:** `Partitioner.Create(0, pixels.Length)` with an inner `for`. **Consequence:** delegate invocations dropped from one per pixel to one per range, and the loop became memory-bandwidth-bound — which is where an image filter is *supposed* to be bound. The rule to state in an interview: **if the body is smaller than a virtual call, partition into ranges and loop inside.**

### `EnumerablePartitionerOptions.NoBuffering`

The default `IEnumerable<T>` partitioner buffers — it pulls a chunk of items eagerly so each task has work in hand. For a live stream where every item should be dispatched the moment it arrives, that buffering is latency you cannot afford:

```csharp
var partitioner = Partitioner.Create(liveFeed, EnumerablePartitionerOptions.NoBuffering);

Parallel.ForEach(partitioner, tick => Evaluate(tick));
```

`NoBuffering` makes each task take **one element at a time**. You trade synchronisation frequency for latency and for fairness when element costs vary wildly — the "chunks that contain just one element" case the docs describe.

> 🌐 **Real-world example — a market-data evaluator that lagged behind the feed.** A rules engine consumed a price feed through `Parallel.ForEach(feed, Evaluate)`. Under light load the default partitioner's buffering meant an early tick could sit in a task's private chunk waiting for the chunk to fill, so alerting lagged in exactly the quiet periods where it mattered. **Decision:** `EnumerablePartitionerOptions.NoBuffering`. **Consequence:** per-item dispatch cost rose, tail latency fell, and the engine stopped holding ticks hostage. **Buffering is a throughput optimisation; on a latency-sensitive stream it is a bug.**

### When to write a custom partitioner

Rarely — but know that the extension point exists and what its contract is. Derive from `Partitioner<TSource>` and override `GetPartitions`, `SupportsDynamicPartitions`, and `GetDynamicPartitions`; derive from `OrderablePartitioner<TSource>` instead if results must be sortable or index-addressable, which adds `GetOrderablePartitions` and `GetOrderableDynamicPartitions`.

Two contract rules that cause real bugs if you get them wrong:

- `GetPartitions` **must return exactly `partitionsCount` partitions**. "If the partitioner runs out of data and cannot create as many partitions as requested, then the method should return an empty enumerator for each of the remaining partitions. Otherwise, both PLINQ and TPL will throw an `InvalidOperationException`."
- If you intend it for `Parallel.ForEach`, **you must support dynamic partitions** — the loop requests a new partition whenever it adds a task.

---

## Producer/Consumer: Channel&lt;T&gt;, TPL Dataflow, and plain ConcurrentQueue

All three move items from producers to consumers. They are not interchangeable, and the difference is not style.

| | `ConcurrentQueue<T>` | `Channel<T>` | TPL Dataflow |
|---|---|---|---|
| Thread-safe | Yes | Yes | Yes |
| **Waiting consumer** | ❌ No — you must poll | ✅ `await reader.ReadAsync()` | ✅ `await block.OutputAvailableAsync()` / linked blocks |
| **Backpressure** | ❌ Unbounded — grows until OOM | ✅ `CreateBounded` + `FullMode` | ✅ `BoundedCapacity` |
| Async-aware | ❌ | ✅ Built for it | ✅ |
| Completion signal | ❌ Roll your own | ✅ `Writer.Complete()` → `ReadAllAsync` ends | ✅ `Complete()` → `await Completion`, propagates along links |
| Multi-stage topology | ❌ | Manual (one channel per stage) | ✅ Native — that is the whole point |
| Broadcast (every consumer gets every item) | ❌ | ❌ Deliberately not | ✅ `BroadcastBlock<T>` |
| Batching | ❌ | ❌ | ✅ `BatchBlock<T>` |
| Shipped in-box | ✅ | ✅ | ❌ **NuGet: `System.Threading.Tasks.Dataflow`** |

### Why a plain `ConcurrentQueue<T>` is not a pipeline

`ConcurrentQueue<T>` is a *data structure*. It is thread-safe and lock-free for the common paths, and it is the right choice when you need a shared FIFO and nothing more. It is not a producer/consumer *mechanism*, because it is missing the two things a pipeline needs:

```csharp
// ❌ The shape people write, and why it is wrong
while (!ct.IsCancellationRequested)
{
    if (_queue.TryDequeue(out var item))
        Process(item);
    else
        await Task.Delay(50, ct);     // ← 1. polling: latency floor AND wasted wakeups
}
// ← 2. nothing stops producers when consumers fall behind:
//      the queue grows without bound until the process dies
```

Both defects are structural, not fixable with a tighter poll interval. Tightening the delay trades latency for CPU; loosening it trades CPU for latency; neither adds backpressure.

`Channel<T>` fixes both:

```csharp
var channel = Channel.CreateBounded<Order>(new BoundedChannelOptions(capacity: 500)
{
    FullMode = BoundedChannelFullMode.Wait,   // producer awaits when full = backpressure
    SingleReader = false,
    SingleWriter = false
});

// Consumer — no polling, no delay, exits cleanly on Complete()
await foreach (var order in channel.Reader.ReadAllAsync(ct))
    await ProcessAsync(order, ct);
```

The [async page](03-async-and-threading.md#channelt--the-modern-producer-consumer) covers `Channel<T>`'s bounded-vs-unbounded decision and the `SingleReader`/`SingleWriter` hints; three things worth adding here.

**`BoundedChannelFullMode` is a policy decision, not a default to accept.** The four modes encode four different answers to "the consumer is behind, now what?": `Wait` (block the producer — backpressure), `DropWrite` (discard the new item), `DropOldest`, and `DropNewest`. Telemetry pipelines usually want `DropOldest`; order pipelines want `Wait`; a "latest value" gauge wants a capacity-1 channel with `DropOldest`.

**Prioritised channels exist from .NET 9.** `Channel.CreateUnboundedPrioritized<T>()` and its `UnboundedPrioritizedChannelOptions<T>` overload use `Comparer<T>.Default` (or a comparer you supply) so that "the next item read from the channel will be the element available in the channel with the lowest priority value." There is no bounded prioritised variant — so you get priority *or* backpressure, not both.

**One writer must call `Complete()`.** `ReadAllAsync` ends when the channel is completed, not when it is momentarily empty. Forgetting `Writer.Complete()` is the classic "my consumer never exits and my host hangs on shutdown" bug.

> 🌐 **Real-world example — webhook ingest that OOM'd during a partner outage.** An endpoint accepted webhooks and pushed them onto an unbounded `ConcurrentQueue<T>`; a background worker drained it into a downstream system. When that downstream system went down for 40 minutes, the queue absorbed every event and the pod was OOM-killed — losing everything in memory, including the events that *had* succeeded. **Decision:** `Channel.CreateBounded<T>(capacity)` with `FullMode = Wait`, and the HTTP handler awaiting `WriteAsync` with a short timeout that returns `503 Retry-After` when it expires. **Consequence:** the memory ceiling became a fixed number, and backpressure surfaced at the edge as a retriable status code instead of as a crash. **Unbounded queues do not remove the limit; they relocate it to your memory allocator.**

### TPL Dataflow — when the topology is the point

Dataflow is an actor-style mesh: each block owns a buffer, a delegate, and its own degree of parallelism, and blocks are wired together with `LinkTo`.

```csharp
var options = new ExecutionDataflowBlockOptions
{
    MaxDegreeOfParallelism = 8,
    BoundedCapacity = 100,          // per-block backpressure
    CancellationToken = ct
};

var download  = new TransformBlock<Uri, byte[]>(
                    uri => _http.GetByteArrayAsync(uri, ct), options);

var ocr       = new TransformBlock<byte[], string>(
                    bytes => RunOcr(bytes),                     // CPU-bound
                    new ExecutionDataflowBlockOptions
                    {
                        MaxDegreeOfParallelism = Environment.ProcessorCount,
                        BoundedCapacity = 20
                    });

var index     = new ActionBlock<string>(
                    text => _search.IndexAsync(text, ct),
                    new ExecutionDataflowBlockOptions { MaxDegreeOfParallelism = 4 });

var link = new DataflowLinkOptions { PropagateCompletion = true };
download.LinkTo(ocr, link);
ocr.LinkTo(index, link);

foreach (var uri in uris) await download.SendAsync(uri, ct);
download.Complete();
await index.Completion;             // completion flows down the links
```

**The defaults are conservative and they surprise people.** From the [`ExecutionDataflowBlockOptions`](https://learn.microsoft.com/dotnet/api/system.threading.tasks.dataflow.executiondataflowblockoptions) docs:

| Option | Default |
|---|---|
| `MaxDegreeOfParallelism` | **`1`** — every block is serial until you say otherwise |
| `BoundedCapacity` | `DataflowBlockOptions.Unbounded` (`-1`) |
| `MaxMessagesPerTask` | `Unbounded` (`-1`) |
| `TaskScheduler` | `TaskScheduler.Default` |
| `CancellationToken` | `CancellationToken.None` |

A `MaxDegreeOfParallelism` of 1 is a *feature* — it means a block is a safe place to touch non-thread-safe state — but "I built a Dataflow pipeline and it's not parallel" is entirely explained by never setting it. Note also that "Dataflow blocks capture the state of the options at their construction. Subsequent changes to the provided `ExecutionDataflowBlockOptions` instance should not affect the behavior of a dataflow block" — so reusing and mutating one options object between blocks does not do what it looks like it does.

**Dataflow is not in-box.** The docs say it plainly: "The TPL Dataflow Library… is not distributed with .NET." You take a NuGet dependency on `System.Threading.Tasks.Dataflow`. That is a real consideration for a library author and a non-issue for an application — but know which side of the line you are on.

**Choose Dataflow over `Channel<T>` when** you need multi-stage topology with per-stage parallelism, broadcast (`BroadcastBlock<T>` gives every linked consumer every item — something a channel deliberately never does), batching (`BatchBlock<T>`), joins (`JoinBlock<T1,T2>`), or completion that propagates through the graph. **Choose `Channel<T>` when** it is one queue between producers and consumers: it is in-box, lighter, and easier to reason about.

> 🌐 **Real-world example — one degree of parallelism for three very different stages.** A document-ingest service downloaded scans, OCR'd them, and indexed the text. Written as a single `Parallel.ForEachAsync` over documents, the download stage's ideal concurrency (high — network-bound) and the OCR stage's ideal concurrency (`ProcessorCount` — CPU-bound) had to be the same number, and whichever you picked was wrong for one of them. **Decision:** three Dataflow blocks with `MaxDegreeOfParallelism` set independently per stage, plus `BoundedCapacity` so a fast downloader could not buffer a thousand images ahead of a slow OCR engine. **Consequence:** each stage ran at its own natural rate and memory stayed flat. **The signal that you have outgrown a single parallel loop is needing two different degrees of parallelism in one body.**

---

## Concurrent Collections — the guarantees and the gaps

"Thread-safe" is not one property. Every concurrent collection answers three separate questions, and interviewers probe the gap between them: *are individual operations atomic? are compound operations atomic? is enumeration a snapshot?*

### `ConcurrentDictionary<TKey,TValue>` — what it guarantees

From the [API remarks](https://learn.microsoft.com/dotnet/api/system.collections.concurrent.concurrentdictionary-2):

> "For modifications and write operations to the dictionary, `ConcurrentDictionary<TKey,TValue>` uses fine-grained locking to ensure thread safety. (Read operations on the dictionary are performed in a lock-free manner.)"

So: **reads never block**, and writes take a fine-grained lock rather than one global one. That is the guarantee. Now the gaps.

#### Gap 1 — `GetOrAdd`'s factory can run more than once

This is the single most-asked `ConcurrentDictionary` question, and the docs state it in terms you should be able to quote:

> "However, the `valueFactory` delegate is called outside the locks to avoid the problems that can arise from executing unknown code under a lock. Therefore, `GetOrAdd` is not atomic with regards to all other operations on the `ConcurrentDictionary<TKey,TValue>` class."
>
> "If you call `GetOrAdd` simultaneously on different threads, `valueFactory` may be called multiple times, but only one key/value pair will be added to the dictionary."

Read those two sentences carefully — they contain both halves of the answer. The **dictionary** stays consistent: exactly one entry is added and every caller gets the same value back. Your **factory** does not: it can run N times for N concurrent callers, and N−1 of the objects it produced are silently discarded.

The documented outcome table is worth internalising:

| Scenario | Return value |
|---|---|
| Key is already present | The existing value |
| Key absent; factory runs; recheck finds nothing | The new value is inserted and returned |
| Key absent; factory runs; **another thread inserts meanwhile**; recheck finds theirs | **The other thread's value** — yours is thrown away |

That third row is where production incidents come from:

```csharp
// ❌ Creates and abandons connections/clients under concurrency
private readonly ConcurrentDictionary<string, SqlConnection> _conns = new();

public SqlConnection Get(string name) =>
    _conns.GetOrAdd(name, n => OpenConnection(n));
    // Two threads racing on a cold key both open a connection.
    // One is stored. The other is leaked — never returned to the pool,
    // never disposed, and invisible to every code path you wrote.
```

**The fix is `Lazy<T>`**, and the reason it works is worth saying out loud: the *`Lazy<T>` wrapper* may be constructed more than once, but constructing one is free and side-effect-free. Only the wrapper that actually wins the insert is ever returned to callers, so only its factory is ever forced.

```csharp
// ✅ The expensive work happens exactly once
private readonly ConcurrentDictionary<string, Lazy<SqlConnection>> _conns = new();

public SqlConnection Get(string name) =>
    _conns.GetOrAdd(name, n => new Lazy<SqlConnection>(
        () => OpenConnection(n),
        LazyThreadSafetyMode.ExecutionAndPublication)).Value;
```

`LazyThreadSafetyMode.ExecutionAndPublication` is the mode that guarantees the factory runs once even under concurrent `.Value` access. For an async factory the same trick works with `Lazy<Task<T>>` — but be deliberate about exception caching, because a `Lazy<Task<T>>` that captured a faulted task will keep handing that faulted task to every future caller.

`AddOrUpdate` has the identical caveat: its delegates run outside the locks, so "the code executed by these delegates is not subject to the atomicity of the operation." An `updateValueFactory` can be invoked, lose the CAS race, and be invoked again — which is fine for a pure function and catastrophic for one with side effects.

> 🌐 **Real-world example — 60 HTTP clients where there should have been one.** A multi-tenant gateway cached a configured `HttpClient` per tenant in a `ConcurrentDictionary` via `GetOrAdd`. On a cold start, dozens of simultaneous first requests for the same tenant each ran the factory. One client was stored; the rest were garbage but held sockets until finalisation, and connection counts to the tenant's origin spiked far above the configured pool size. **Decision:** wrap the value in `Lazy<HttpClient>` with `ExecutionAndPublication`. **Consequence:** one client per tenant, deterministically. **The general rule: if the factory has side effects — sockets, files, registrations, metrics — `GetOrAdd` alone is not enough.**

#### Gap 2 — compound operations are still races

Thread-safe *operations* do not compose into thread-safe *sequences*:

```csharp
// ❌ Two atomic operations do not make one atomic operation
if (!dict.ContainsKey(key))      // ← another thread can insert here
    dict[key] = Compute();       // ← and you overwrite it

// ✅ One atomic operation
dict.TryAdd(key, Compute());     // returns false if someone beat you
```

The atomic primitives are `TryAdd`, `TryRemove`, `TryUpdate` (compare-and-swap on the value), `GetOrAdd`, and `AddOrUpdate`. Anything you build out of `ContainsKey` + indexer, or `TryGetValue` + `[]=`, is a check-then-act race.

#### Gap 3 — enumeration is not a snapshot

> "The enumerator returned from the dictionary is safe to use concurrently with reads and writes to the dictionary, however it does not represent a moment-in-time snapshot of the dictionary. The contents exposed through the enumerator may contain modifications made to the dictionary after `GetEnumerator` was called."

This is a genuine improvement over `Dictionary<TKey,TValue>`, which throws `InvalidOperationException` if the collection changes mid-enumeration. But "won't throw" is not "consistent". If you need a stable view — to compute a total, to serialise state, to iterate twice — call `ToArray()`, which takes the locks and gives you a real snapshot.

```csharp
// May observe entries added after the loop started; may miss removals
foreach (var kvp in dict) { … }

// A genuine point-in-time snapshot
foreach (var kvp in dict.ToArray()) { … }
```

`Count` is in the same family: obtaining it is not free the way `Dictionary<,>.Count` is, and by the time you act on the value it may be stale. Prefer `IsEmpty` when that is the actual question.

### When a plain `lock` beats `ConcurrentDictionary`

Three cases, and being able to name them is a strong senior signal:

1. **A multi-field invariant.** If a write must update the dictionary *and* a counter *and* an index in one indivisible step, no per-key lock helps you. `ConcurrentDictionary` makes each operation atomic; it cannot make your transaction atomic. One `lock` around a plain `Dictionary<,>` plus the other fields is simpler *and* correct.
2. **Write-dominated, low-contention workloads.** `ConcurrentDictionary` pays for its concurrency: a bucket-and-lock array, more allocation per entry, and a `Count` that is no longer a field read. If the map is written far more than it is read and only one or two threads ever touch it, `lock` + `Dictionary<,>` is the leaner structure. Measure — but do not assume "concurrent" means "faster".
3. **You need a consistent multi-key read.** Reading three related keys out of a `ConcurrentDictionary` gives you three independently-timed reads. Under a `lock`, they are one observation.

> 🌐 **Real-world example — a "lock-free" cache that produced impossible states.** A rate limiter kept `ConcurrentDictionary<string, int>` of request counts plus a separate `_totalRequests` field updated with `Interlocked.Increment`. Both operations were individually atomic; together they were not, so a diagnostics endpoint routinely reported a total that did not equal the sum of the per-key counts, and an alert fired on the discrepancy. **Decision:** one `lock` around a plain `Dictionary<string,int>` and the total, held for the handful of instructions it takes to update both. **Consequence:** the invariant held, and the critical section was short enough that contention never showed up in the profile. **`ConcurrentDictionary` gives you atomic operations; if your invariant spans more than one, you still need a lock.**

### The rest of the family, briefly

| Type | Shape | Use it when |
|---|---|---|
| `ConcurrentQueue<T>` | FIFO, segmented linked list of array segments | Order matters and you have your own signalling |
| `ConcurrentStack<T>` | LIFO, `Interlocked`-based linked list | Recency matters (work-stealing, undo) |
| `ConcurrentBag<T>` | Thread-local lists with stealing | Same thread adds and takes; order is irrelevant |
| `BlockingCollection<T>` | Blocking wrapper over an `IProducerConsumerCollection<T>` | **Legacy** — its `Add`/`Take` are synchronous and block threads; `Channel<T>` replaces it in async code |
| `ImmutableDictionary<K,V>` etc. | Persistent structures; every "mutation" returns a new instance | Read-mostly config where readers need a guaranteed-stable view with zero locking |

`ConcurrentBag<T>` deserves its footnote: it is optimised for the case where **the same thread both adds and removes**, keeping a thread-local list and only stealing from other threads' lists when its own is empty. Used as a general-purpose "any thread produces, any thread consumes" queue it can be the *slowest* choice in the family. It is the right default for collecting results out of a `Parallel.ForEachAsync` body and the wrong default for a work queue.

`ImmutableDictionary<K,V>` plus `Interlocked.CompareExchange` on the reference is the underrated pattern for read-mostly data:

```csharp
private ImmutableDictionary<string, FeatureFlag> _flags = ImmutableDictionary<string, FeatureFlag>.Empty;

// Readers: zero synchronisation, always see one coherent version
public FeatureFlag? Get(string key) =>
    Volatile.Read(ref _flags).TryGetValue(key, out var f) ? f : null;

// Writers: build the new version, publish it atomically, retry on a race
public void Set(string key, FeatureFlag flag)
{
    ImmutableDictionary<string, FeatureFlag> original, updated;
    do
    {
        original = Volatile.Read(ref _flags);
        updated  = original.SetItem(key, flag);
    }
    while (Interlocked.CompareExchange(ref _flags, updated, original) != original);
}
```

Readers pay nothing and can never observe a torn or half-updated map; writers pay a copy. For a config table read millions of times and written on deployment, that is exactly the right trade.

---

## Synchronisation Primitives from the Parallel Side

The [async page](03-async-and-threading.md#7-synchronization-primitives) is the reference for the full primitive catalogue — `Monitor`, `System.Threading.Lock`, `Mutex`, `Semaphore`, the event primitives, `Barrier`. What follows is the parallel-computation view: the four questions that come up when you are protecting shared state inside a data-parallel loop rather than serialising an async pipeline.

### `lock` cannot be held across `await` — and the reason is thread identity

`lock` (over an `object`) compiles to `Monitor.Enter`/`Monitor.Exit`, and `Monitor` is **thread-affine**: the thread that entered must be the thread that exits. An `await` may resume its continuation on a different pool thread, at which point `Monitor.Exit` would throw `SynchronizationLockException`. Rather than let you write that, the C# compiler rejects it outright — **CS1996, "Cannot await in the body of a lock statement."** The same restriction applies to `System.Threading.Lock` (.NET 9 / C# 13): the language reference states "You can't use the `await` expression in the body of a `lock` statement."

`SemaphoreSlim(1, 1)` is the async mutex precisely because it does **not** enforce thread identity — it counts permits, not owners, so a continuation on a different thread may legally `Release()` what another thread `WaitAsync()`'d.

The corollary that catches people: **`SemaphoreSlim` is not reentrant.** `lock` lets the same thread re-enter; a count-1 semaphore does not, so a public method that acquires the gate and then calls a private helper that acquires the same gate deadlocks against itself. The discipline is *acquire once at the public entry point*.

```csharp
// ❌ CS1996 — will not compile
lock (_gate) { await _db.SaveAsync(x); }

// ✅ Async mutual exclusion
await _gate.WaitAsync(ct);            // SemaphoreSlim(1, 1)
try     { await _db.SaveAsync(x, ct); }
finally { _gate.Release(); }
```

> ⚠️ CS1996 only guards the `lock` **statement**. You can still hand-write `Monitor.Enter` / `await` / `Monitor.Exit` and the compiler will let you. Don't.

### `Interlocked` — the CAS foundation, and the barrier surface

Inside a parallel loop, `Interlocked` is usually the right answer for single-variable updates: it is one atomic instruction rather than a lock acquire/release pair, and the docs note that **"the members of this class do not throw exceptions."**

Beyond `Increment`/`Decrement`/`Add`/`Exchange`/`CompareExchange`, three members matter for the memory-model discussion below:

| Member | What it is |
|---|---|
| `Interlocked.MemoryBarrier()` | Full fence for the current processor |
| `Interlocked.MemoryBarrierProcessWide()` | "Provides a process-wide memory barrier that ensures that reads and writes from any CPU cannot move across the barrier" |
| `Interlocked.SpeculationBarrier()` | "Defines a memory fence that blocks speculative execution past this point until pending reads and writes are complete" |

`Interlocked.Read(ref long)` exists for one reason: a plain 64-bit read is **not** guaranteed atomic on a 32-bit platform. On 64-bit it is redundant; write it anyway if the code targets both.

`CompareExchange` is the primitive everything lock-free is built on, including `ConcurrentDictionary`'s writes and the `ImmutableDictionary` publish loop above. The idiom is always the same: read, compute, swap-if-unchanged, retry.

```csharp
private long _highWaterMark;

public void Observe(long value)
{
    long current;
    do
    {
        current = Volatile.Read(ref _highWaterMark);
        if (value <= current) return;                // nothing to do
    }
    while (Interlocked.CompareExchange(ref _highWaterMark, value, current) != current);
    // the loop re-runs only if another thread moved the mark between our read and our write
}
```

Note the `Volatile.Read` on the initial load. It is not decoration: without it the JIT is permitted to hoist that read out of the loop (see the next section), and the retry would spin forever comparing against a stale cached value.

### `ReaderWriterLockSlim` — and when it loses to a plain `lock`

`ReaderWriterLockSlim` allows many concurrent readers and one exclusive writer, plus a third *upgradeable read* mode from which a thread can promote to write without releasing its read access. The documented rules that get asked about:

- **Default is `LockRecursionPolicy.NoRecursion`**, "recommended for all new development, because recursion introduces unnecessary complications and makes your code more prone to deadlocks."
- **Only one thread can be in upgradeable mode at a time**, and any number can be in read mode alongside it. That single-upgrader rule is *why* upgrading cannot deadlock under the default policy.
- **A thread that entered in plain read mode may never upgrade.** "Regardless of recursion policy, a thread that initially entered read mode is not allowed to upgrade to upgradeable mode or write mode, because that pattern creates a strong probability of deadlocks. For example, if two threads in read mode both try to enter write mode, they will deadlock."
- **Readers are blocked when writers are queued.** "Blocking new readers when writers are queued is a lock fairness policy that favors writers."
- It is `IDisposable`, and it has **managed thread affinity** — "each `Thread` object must make its own method calls to enter and exit lock modes."

**When it loses.** The mechanism is straightforward: `ReaderWriterLockSlim` maintains reader counts, waiter counts, upgrade state, and events. An uncontended `Monitor` acquire is a thin-lock compare-and-swap on the object header. So for a critical section of a few instructions — a dictionary lookup, a field read — **the bookkeeping costs more than the work it protects**, and the "many concurrent readers" advantage never materialises because no reader was ever waiting long enough to matter.

Three cases where `lock` wins:

1. **Very short critical sections.** The reader-writer bookkeeping dominates.
2. **Reads and writes roughly balanced.** The read-parallelism benefit shrinks toward zero while the overhead stays.
3. **You could have used `ConcurrentDictionary` instead.** For a read-heavy keyed cache, the lock-free read path beats *any* lock.

`ReaderWriterLockSlim` earns its keep when the critical section is genuinely long, reads genuinely dominate, and the protected state is *not* a single dictionary — a config object graph, a spatial index, a cached materialised view.

> ⚠️ There is **no async API**. `EnterReadLock` blocks. Do not use it in an async pipeline; use `SemaphoreSlim`, or a third-party async reader-writer lock, or restructure to immutable-snapshot-plus-`Interlocked` publication.

> 🌐 **Real-world example — a reader-writer lock around a one-line lookup.** A pricing service guarded a `Dictionary<string, decimal>` with `ReaderWriterLockSlim` because "reads outnumber writes 10,000:1". The protected work was a single `TryGetValue`. Under load the lock's enter/exit sequence was a visible share of the profile, and readers were periodically stalled by the writer-favouring fairness policy while a once-a-minute refresh queued. **Decision:** replace the whole thing with `ConcurrentDictionary`, whose read path takes no lock at all. **Consequence:** the synchronisation disappeared from the profile. **`ReaderWriterLockSlim` is for long critical sections over structured state — for a keyed lookup, the concurrent collection already solved it.**

---

## The .NET Memory Model

This is the deepest gap in most senior candidates' knowledge, and the one that separates "I've used `lock`" from "I know why this needs a barrier."

### The problem, in eight lines

```csharp
private bool _stop;                                   // ordinary field

public void RequestStop() => _stop = true;            // thread A

public void Worker()                                  // thread B
{
    while (!_stop)                                    // may never observe true
    {
        DoUnitOfWork();
    }
}
```

This loop can run forever after `RequestStop()` returns. Not "might occasionally lag" — **forever**. There are two independent reasons, and you should be able to name both:

**1. The compiler/JIT may hoist the read.** `_stop` is not modified inside the loop body as far as the optimiser can see, so it is entitled to load it once into a register before the loop and test the register thereafter. The [.NET memory model spec](https://github.com/dotnet/runtime/blob/main/docs/design/specs/Memory-model.md) permits exactly this: *"The effects of ordinary reads and writes can be reordered as long as that preserves single-thread consistency,"* and it explicitly allows that *"Adjacent non-volatile reads from the same location can be coalesced."* The `Volatile` docs state the guarantee from the other side: *"Volatile reads and writes ensure that a value is read or written to memory and not cached (for example, in a processor register)."*

**2. The hardware may reorder or delay visibility.** Separately from anything the compiler does, a store on one core is not instantaneously visible to another.

Note which of these is the *scarier* one: the JIT hoist is a pure software effect. It will happen on your x64 laptop. "It works on x64, it only breaks on ARM" is a comforting story that does not survive contact with a release-mode JIT.

**The fixes**, in increasing order of heaviness:

```csharp
private volatile bool _stop;                  // C# keyword: every access is volatile
// or
private bool _stop;
public void RequestStop() => Volatile.Write(ref _stop, true);
private bool ShouldStop() => Volatile.Read(ref _stop);
// or, for a cancellation-shaped problem, the right answer:
private readonly CancellationTokenSource _cts = new();
while (!_cts.IsCancellationRequested) { … }
```

For anything that is *logically* cancellation, `CancellationToken` is the correct API and it handles the memory model for you. Hand-rolled flags are for the cases that genuinely are not cancellation.

### What .NET actually guarantees

The runtime's memory model is documented in `dotnet/runtime` at `docs/design/specs/Memory-model.md`, and it is deliberately **stronger than ECMA-335** — the spec opens by rationalising "the invariants… expected by the .NET runtimes in their current implementation". These are the guarantees to quote.

**Atomicity.**

> "Memory accesses to *properly aligned* data of primitive and Enum types with sizes up to the platform pointer size are always atomic."
>
> "Managed references are always aligned to their size on the given platform and accesses are atomic."

So: `int`, `bool`, `char`, an enum, a reference — all atomic when aligned. A `long`/`double` is atomic on 64-bit but **not** on 32-bit unless you use `Interlocked.Read` or `Volatile.Read`. And nothing here makes a *struct* atomic: a multi-field `struct` field can be read torn, which is why `decimal`, `Guid`, and your own value types need a lock or a reference-typed box. For deliberately unaligned access, the spec is blunt: "These facilities ensure fault-free access to potentially unaligned locations, but do not ensure atomicity."

**The four ordering categories.** Everything in .NET falls into one of these:

```
┌───────────────────────────────────────────────────────────────────────┐
│ ORDINARY read / write                                                 │
│   "can be reordered as long as that preserves single-thread          │
│    consistency"                                                       │
│   Unused reads can be elided. Adjacent reads from the same location   │
│   can be coalesced. Adjacent writes to the same location can be       │
│   coalesced.                                                          │
├───────────────────────────────────────────────────────────────────────┤
│ VOLATILE READ  — ACQUIRE                                              │
│   "no read or write that is later in the program order may be         │
│    speculatively executed ahead of a volatile read"                   │
│   Sources: `volatile.` IL prefix · Volatile.Read · Thread.VolatileRead│
│            Volatile.ReadBarrier · LOCK ACQUISITION                    │
├───────────────────────────────────────────────────────────────────────┤
│ VOLATILE WRITE — RELEASE                                              │
│   "the effects of a volatile write will not be observable before      │
│    effects of all previous, in program order, reads and writes        │
│    become observable"                                                 │
│   Sources: `volatile.` IL prefix · Volatile.Write ·Thread.VolatileWrite│
│            Volatile.WriteBarrier · LOCK RELEASE                       │
├───────────────────────────────────────────────────────────────────────┤
│ FULL FENCE                                                            │
│   "effects of reads and writes must be observable no later or no      │
│    earlier than a full-fence operation according to their relative    │
│    program order"                                                     │
│   Sources: Thread.MemoryBarrier · all Interlocked methods             │
└───────────────────────────────────────────────────────────────────────┘
```

The two entries people miss are on the right-hand edge of the acquire and release rows: **taking a lock is an acquire; releasing a lock is a release.** That single fact is why correctly-locked code needs no explicit barriers at all, and it is the load-bearing step in the double-checked-locking argument below.

**Three additional guarantees that matter enormously.**

```csharp
// 1. Object assignment
//    "Object assignment to a location potentially accessible by other threads
//     is a release with respect to accesses to the instance's fields/elements
//     and metadata."
_shared = new Node { Value = 42 };   // the write of Value cannot be observed
                                     // AFTER the write of _shared

// 2. Data-dependent reads are ordered
//    "Memory ordering honors data dependency. When performing indirect reads
//     from a location derived from a reference, it is guaranteed that reading
//     of the data will not happen ahead of obtaining the reference."
var local = _shared;                 // if this sees the new node...
var v = local.Value;                 // ...this cannot see stale contents

// 3. Instance constructors — the one with NO guarantee
//    ".NET runtime does not specify any ordering effects to the instance
//     constructors."
```

Guarantee (3) reads alarming next to (1) and (2), and the resolution is the point: **the constructor body itself carries no ordering, but the *assignment that publishes the reference* does.** The safety of `_shared = new Node { Value = 42 }` comes from the object-assignment release rule and the data-dependency rule — not from anything the constructor does. That distinction is exactly the kind of thing a strong interviewer will push on.

**Scope caveat.** The spec describes the runtimes' current implementations, not a universal contract for every conceivable .NET implementation. That is one honest reason the portable habit — `volatile` on shared flags — is still worth keeping.

### The `Volatile` API surface

| API | Semantics | Version |
|---|---|---|
| `volatile` field modifier (C#) | Every read is acquire, every write is release | All |
| `Volatile.Read<T>` / `Volatile.Write<T>` | Per-access acquire / release | All |
| `Volatile.ReadBarrier()` | Standalone acquire fence | **.NET 10+** |
| `Volatile.WriteBarrier()` | Standalone release fence | **.NET 10+** |
| `Thread.MemoryBarrier()` | Full fence | All |
| `Interlocked.MemoryBarrierProcessWide()` | Process-wide full fence | .NET Core 2.0+ |

Two limits of the C# `volatile` keyword that the `Volatile` class exists to work around, both stated in the docs:

- **It cannot be applied to array elements.** `Volatile.Read(ref arr[i])` can.
- **It cannot be applied to `long`/`double`/`decimal` fields in C#.** The C# reference does *not* state a size rule — it enumerates the permitted types (reference types, pointer types, `sbyte`/`byte`/`short`/`ushort`/`int`/`uint`/`char`/`float`/`bool`, enums with those integral bases, generic type parameters known to be reference types, and `IntPtr`/`UIntPtr`) and gives the reason for the exclusions: "You can't mark other types, including `double` and `long`, as `volatile` because reads and writes to fields of those types can't be guaranteed to be atomic." Note that this is *not* "pointer size or smaller" — `IntPtr` is permitted and `long` is not, even though both are 8 bytes on a 64-bit platform. `Volatile.Read(ref someLong)` works and, per the docs, "Volatile reads and writes on such 64-bit memory are atomic even on 32-bit processors."

And one behaviour that surprises people, quoted from the `Volatile` remarks so you get it right under cross-examination:

> "Even though the volatile write to `y` on thread 1 occurred before the volatile read of `y` on thread 2, thread 2 may still see `y2 == 0`. The volatile write to `y` does not guarantee that a following volatile read of `y` on a different processor will see the updated value."

**Volatile gives you *ordering*, not *promptness*.** It guarantees that if you see the new `y`, you also see everything that preceded the write of `y`. It does not guarantee you see the new `y` at any particular time. Anyone who describes `volatile` as "makes writes immediately visible" has the model wrong.

The docs' own closing advice is the line to repeat in an interview:

> "Volatile memory operations are for special cases of synchronization, where normal locking is not an acceptable alternative. Under normal circumstances, the C# `lock` statement… and the `Monitor` class provide the easiest and least error-prone way of synchronizing access to data, and the `Lazy<T>` class provides a simple way to write lazy initialization code without directly using double-checked locking."

> 🌐 **Real-world example — a worker that would not shut down.** A hosted service polled a `private bool _draining` flag set by a `/drain` admin endpoint. In Debug it worked; in Release on a production pod, `SIGTERM` handling timed out and Kubernetes SIGKILLed the pod mid-write, leaving partial batches. **Diagnosis:** the JIT had hoisted the flag read out of the drain loop — a pure optimiser effect, nothing to do with the CPU. **Decision:** delete the flag and use the `CancellationToken` already being handed to `ExecuteAsync`, which the runtime publishes correctly. **Consequence:** graceful shutdown worked, and one bespoke synchronisation primitive left the codebase. **If the flag means "stop", it is a `CancellationToken`; hand-rolled `bool`s are for the cases that genuinely are not.**

---

## Double-Checked Locking, Correctly

Double-checked locking (DCL) is the pattern of testing a field without a lock, taking the lock only if the test suggests work is needed, and testing again inside. It exists to avoid paying for a lock on every read of an already-initialised value.

Folklore says "DCL needs `volatile`." That is a *good habit* and a *bad explanation*, and the precise version is much more interesting — and much more defensible when someone pushes back.

### The reference-publication form is safe on .NET without `volatile`

The memory model spec ships this exact pattern as a correct example, with its own inline reasoning:

```csharp
public class Singleton
{
    private static readonly object _lock = new object();
    private static Singleton _inst;

    private Singleton() { }

    public static Singleton GetInstance()
    {
        if (_inst == null)
        {
            lock (_lock)
            {
                // taking a lock is an acquire, the read of _inst will happen after taking the lock
                // releasing a lock is a release, if another thread assigned _inst, the write will
                // be observed no later than the release of the lock
                // thus if another thread initialized the _inst, the current thread is guaranteed
                // to see that here.
                if (_inst == null)
                {
                    _inst = new Singleton();
                }
            }
        }

        return _inst;
    }
}
```

The two guarantees that carry it are the ones from the previous section: **object assignment is a release with respect to the instance's fields**, so a reader that observes the reference cannot observe an uninitialised object; and **data-dependent reads are ordered**, so dereferencing that reference cannot read stale contents. This is the specific place where .NET's model is stronger than ECMA-335 and stronger than Java's pre-JSR-133 model, which is why the "DCL is broken" lore imported from other ecosystems does not transfer cleanly.

The spec's `Interlocked` variant is also given, with its own justification — "`Interlocked.CompareExchange` is a full fence, we cannot possibly read null or some other spurious instance":

```csharp
public static Singleton GetInstance()
{
    Singleton localInst = _inst;
    if (localInst == null)
    {
        Interlocked.CompareExchange(ref _inst, new Singleton(), null);
        localInst = _inst;
    }
    return localInst;
}
```

Note the trade-off in that one: it may **construct** more than one `Singleton` under a race (only one is published), so it is right for cheap, side-effect-free objects and wrong for anything that opens a socket. That is the same trade-off as `ConcurrentDictionary.GetOrAdd`, and recognising it as the same trade-off is a good sign.

### The form that IS broken without `Volatile`

Change one thing — guard with a separate `bool` instead of testing the reference itself — and the guarantees evaporate, because there is no longer a data dependency between the flag and the data:

```csharp
// ❌ BROKEN. Can return null.
private static Config? _config;
private static bool _initialized;                 // separate flag: NOT data-dependent
private static readonly object _gate = new();

public static Config Get()
{
    if (!_initialized)                            // ordinary read #1
    {
        lock (_gate)
        {
            if (!_initialized)
            {
                _config = Load();                 // ordinary write A
                _initialized = true;              // ordinary write B
            }
        }
    }
    return _config!;                              // ordinary read #2 — can be null
}
```

The fast path takes no lock, so it gets no acquire fence. It performs two ordinary reads of two *different* locations with no dependency between them, and ordinary reads "can be reordered as long as that preserves single-thread consistency" — which reordering them does, because single-threaded there is no way to tell. A reader can therefore observe `_initialized == true` and `_config == null`, and dereference a null.

The fix is a **release/acquire pair on the flag**:

```csharp
// ✅ Volatile.Write is a release: write A cannot become observable after it.
//    Volatile.Read is an acquire: read #2 cannot be hoisted above it.
public static Config Get()
{
    if (!Volatile.Read(ref _initialized))
    {
        lock (_gate)
        {
            if (!_initialized)                    // inside the lock: plain read is fine
            {
                _config = Load();
                Volatile.Write(ref _initialized, true);
            }
        }
    }
    return _config!;
}
```

Marking the field `private static volatile bool _initialized;` achieves the same thing for every access to it, at the cost of paying for the barriers on accesses that did not need them.

### The pattern to summarise in an interview

> "On .NET, DCL that publishes and tests **the reference itself** is safe without `volatile`, because the runtime memory model makes object assignment a release with respect to the instance's fields and guarantees data-dependent reads are ordered — the memory-model spec ships that pattern as a correct example. DCL that tests a **separate flag** is broken without `Volatile.Read`/`Volatile.Write`, because there is no data dependency for the model to hang the ordering on. And in application code I would write neither: `Lazy<T>` with `ExecutionAndPublication` exists, and Microsoft's own `Volatile` documentation points at it as the way to get lazy initialization 'without directly using double-checked locking.'"

That answer is correct in both directions, cites the source, and ends with the thing you would actually ship:

```csharp
// ✅ What to write
private static readonly Lazy<Config> _config =
    new(Load, LazyThreadSafetyMode.ExecutionAndPublication);

public static Config Get() => _config.Value;
```

`LazyInitializer.EnsureInitialized` is the lower-allocation alternative when you cannot afford the `Lazy<T>` wrapper object — it takes the target field by `ref` and initialises in place. Reach for it only when you have measured the allocation and it mattered.

> 🌐 **Real-world example — a config cache that returned null once per deployment.** A settings provider used the separate-flag DCL above. On a 32-core host, roughly one deployment in twenty produced a single `NullReferenceException` in the first second of traffic and then behaved perfectly for weeks — unreproducible locally, dismissed twice as a transient. **Decision:** replace the whole class with `Lazy<Config>(Load, LazyThreadSafetyMode.ExecutionAndPublication)`. **Consequence:** eight lines deleted, the class of bug eliminated rather than patched. **A memory-model bug's signature is exactly this: rare, load-dependent, machine-dependent, and impossible to reproduce on the box where you wrote it.**

---

## False Sharing

Everything above is about correctness. False sharing is about the case where the code is perfectly correct and *slower with more threads*.

### The mechanism

Cache coherence does not operate on variables. It operates on **cache lines** — fixed-size blocks that the coherence protocol moves between cores as a unit. Two threads writing to two *different* variables that happen to sit in the *same* cache line will invalidate each other's copy of that line on every write, even though they never touch each other's data. Hence "false" sharing: the sharing is an artefact of memory layout, not of the program's logic.

```
   Two counters, adjacent in memory, ONE cache line:

   ┌──────────── one cache line ────────────┐
   │  counters[0]  counters[1]   … padding …│
   └────┬──────────────┬────────────────────┘
        │              │
     Core 0         Core 1
     writes         writes
        │              │
        ▼              ▼
   Every write by Core 0 invalidates Core 1's copy of the WHOLE line
   and vice versa. The line ping-pongs across the interconnect on
   every single increment. Both cores stall waiting for a line they
   already logically own the contents of.

   Correct results. Catastrophic scaling.
   Adding cores makes it WORSE, because there are more invalidators.
```

The tell in a profile is distinctive: the loop is correct, contains no locks, and gets *slower* as you raise `MaxDegreeOfParallelism`. Contention counters show nothing — there is no lock to contend on. Hardware counters (cache-line invalidations, `MEM_LOAD_*` events in a tool like Intel VTune or `perf c2c` on Linux) are what actually name it.

### The BCL does this, which is your citation

You do not have to argue that false sharing is real: the runtime pads for it. `ConcurrentQueueSegment<T>` holds its head and tail indices in a struct whose only purpose is separation, with the comment *"Padded head and tail indices, to avoid false sharing between producers and consumers"*:

```csharp
[StructLayout(LayoutKind.Explicit, Size = 3 * Internal.PaddingHelpers.CACHE_LINE_SIZE)]
internal struct PaddedHeadAndTail
{
    [FieldOffset(1 * Internal.PaddingHelpers.CACHE_LINE_SIZE)] public int Head;
    [FieldOffset(2 * Internal.PaddingHelpers.CACHE_LINE_SIZE)] public int Tail;
}
```

Two details to notice. The head and tail are separated by a full line *and* the struct is padded on both ends, so neither index shares a line with whatever the allocator puts next to the segment. And the size is a **named constant**, not a literal — because the cache line size is platform-dependent. Do not quote a number for it in an interview; say "platform-dependent, which is why the BCL uses a constant" and you are both correct and clearly informed.

### Padding a hot counter

```csharp
[StructLayout(LayoutKind.Explicit, Size = 128)]   // tune per target; measure it
private struct PaddedCounter
{
    [FieldOffset(0)] public long Value;
}

private readonly PaddedCounter[] _hits;           // one slot per partition

public void Record(int partition) =>
    Interlocked.Increment(ref _hits[partition].Value);

public long Total()
{
    long sum = 0;
    for (int i = 0; i < _hits.Length; i++)
        sum += Interlocked.Read(ref _hits[i].Value);
    return sum;
}
```

`ref _hits[i].Value` is legal and gives a genuine interior reference into the array element — this is one of the places C# lets you do the low-level thing cleanly.

### The better answer is usually "don't share at all"

Padding treats the symptom. The cause is that per-thread state was put in shared memory. If the accumulation is per-iteration and merged at the end, the `localInit`/`localFinally` overload eliminates the shared write entirely — no padding required, and the local accumulator lives happily on the task's own stack or in its own object:

```csharp
long total = 0;
Parallel.For(0, n,
    localInit: () => 0L,
    body: (i, _, local) => local + Weigh(i),
    localFinally: local => Interlocked.Add(ref total, local));
```

**Reach for padding only when the counters must be individually addressable** — a per-partition histogram, a per-shard rate limiter, a metrics array read by a scraper — so a merge-at-the-end design is not available.

### When not to pad

Padding is not free: `Size = 128` per counter turns a compact `long[64]` into 8 KB, which is itself a cache-footprint problem if the array is scanned. Do not pad:

- fields that are read-mostly (a shared line that nobody writes is a *benefit* — it stays valid in every core's cache);
- arrays where each element is touched by exactly one thread for the whole run *and* the elements are large enough to span lines already;
- anything you have not measured. False sharing is a real effect with a specific fingerprint. Padding on suspicion just makes the data structure bigger.

> 🌐 **Real-world example — a metrics array that got slower with every core added.** A request-classification stage kept `long[] _countsByCategory` and incremented a category counter per request via `Interlocked.Increment`. With 16 categories, the entire array fit inside one or two cache lines, so 32 worker threads incrementing 16 different counters were all fighting over the same line. Throughput *dropped* when `MaxDegreeOfParallelism` was raised from 8 to 32 — the classic signature. **Decision:** pad each counter to its own line with an explicit-layout struct. **Consequence:** the loop began scaling with the degree of parallelism instead of against it. **The diagnostic to remember: correct code, no locks, and negative scaling means the contention is in the cache, not in your program.**

---

## Decision Matrix — which construct when

| Need | Reach for | Why not the alternative |
|---|---|---|
| CPU work over an indexed range | `Parallel.For` | PLINQ adds merge cost you don't need |
| CPU work over a collection | `Parallel.ForEach` | — |
| CPU work with a per-thread accumulator | `Parallel.For`/`ForEach` `localInit`/`localFinally` | A shared counter serialises the loop |
| CPU work, tiny body, indexable source | `Partitioner.Create(0, len)` + inner `for` | Per-element delegate dispatch dominates |
| CPU work, wildly uneven per-element cost | `Partitioner.Create(source, loadBalance: true)` | Range partitioning can't rebalance |
| CPU work expressed as a query | PLINQ `AsParallel()` | Only if the delegate is expensive |
| **I/O work over a collection** | **`Parallel.ForEachAsync`** | `Parallel.ForEach` blocks pool threads |
| I/O work where results must keep input order | `SemaphoreSlim` + `Task.WhenAll` | `ForEachAsync` returns `Task`, not `Task<T[]>` |
| I/O work over a stream of unknown length | `Parallel.ForEachAsync` over `IAsyncEnumerable<T>` | — |
| One queue between producers and consumers | `Channel<T>` (bounded) | `ConcurrentQueue` has no wait and no backpressure |
| Priority queue between producers/consumers | `Channel.CreateUnboundedPrioritized<T>` (.NET 9+) | No bounded prioritised variant exists |
| Multi-stage pipeline, per-stage parallelism | TPL Dataflow | One loop can't have two degrees of parallelism |
| Every consumer must see every item | Dataflow `BroadcastBlock<T>` | `Channel<T>` deliberately doesn't broadcast |
| Group items into batches | Dataflow `BatchBlock<T>` | — |
| Keyed cache, read-heavy | `ConcurrentDictionary` | `ReaderWriterLockSlim` still takes a lock to read |
| Keyed cache with an expensive factory | `ConcurrentDictionary<K, Lazy<V>>` | Bare `GetOrAdd` can run the factory more than once |
| Read-mostly config snapshot | `ImmutableDictionary` + `Interlocked.CompareExchange` | Readers pay nothing at all |
| Invariant spanning several fields | plain `lock` | `ConcurrentDictionary` can't span operations |
| One counter, one flag, one reference swap | `Interlocked` | A lock is heavier and no safer here |
| Mutual exclusion across `await` | `SemaphoreSlim(1, 1)` | `lock` can't cross `await` (CS1996) |
| Mutual exclusion, sync, .NET 9+ | `lock (System.Threading.Lock)` | — |
| Publish a lazily-built singleton | `Lazy<T>` (`ExecutionAndPublication`) | Hand-rolled DCL is a memory-model minefield |
| Shared flag read without a lock | `Volatile.Read` / `volatile` — or a `CancellationToken` | A plain read can be hoisted out of the loop |
| Correct code that scales *negatively* | Investigate false sharing | There is no lock to blame |

---

## Common Pitfalls

### 1. An `async` lambda passed to `Parallel.ForEach`

```csharp
// ❌ Binds to Action<T> → async void. Returns immediately. Swallows everything.
Parallel.ForEach(urls, async url => await FetchAsync(url));

// ✅
await Parallel.ForEachAsync(urls, async (url, ct) => await FetchAsync(url, ct));
```

No compiler error, no warning, no observable work. Analyzer **CA1849** and friends will not save you here — the conversion is legal.

### 2. Writing to a shared `List<T>` from a parallel body

```csharp
// ❌ List<T> is not thread-safe: lost writes, or a corrupted backing array
Parallel.ForEach(items, i => results.Add(Transform(i)));

// ✅ Pre-sized array, one slot per index — no synchronisation needed at all
var results = new Result[items.Count];
Parallel.For(0, items.Count, i => results[i] = Transform(items[i]));

// ✅ When there is no index: a concurrent collection
var bag = new ConcurrentBag<Result>();
```

### 3. Assuming `MaxDegreeOfParallelism` defaults to `ProcessorCount`

It defaults to `-1`. For `For`/`ForEach` that means *unlimited*; only for `ForEachAsync` does `-1` mean `ProcessorCount`. If you need a cap on `Parallel.ForEach`, set one.

### 4. Hard-coding the degree of parallelism

`MaxDegreeOfParallelism = 32` written on a 32-core laptop is a latent incident on a CPU-limited container. Derive it: `Environment.ProcessorCount` for CPU work, the downstream system's documented limit for I/O work.

### 5. `GetOrAdd` with a side-effecting factory

The factory runs outside the lock and may run more than once. Wrap the value in `Lazy<T>` whenever creating it opens a socket, a file, a connection, or registers anything.

### 6. Treating `ConcurrentDictionary` enumeration as a snapshot

It isn't — the docs say so explicitly. Use `ToArray()` when you need a coherent view.

### 7. Building a compound operation out of atomic ones

```csharp
// ❌ Check-then-act race
if (!dict.ContainsKey(k)) dict[k] = v;

// ✅
dict.TryAdd(k, v);
```

### 8. A polling loop instead of a channel

`while (queue.TryDequeue(...)) else await Task.Delay(50)` is a latency floor plus wasted wakeups plus no backpressure. `Channel<T>` solves all three.

### 9. Forgetting `channel.Writer.Complete()`

`ReadAllAsync` ends on completion, not on emptiness. Without the `Complete()` call the consumer loop never exits and graceful shutdown hangs.

### 10. Dataflow with the default `MaxDegreeOfParallelism`

It is `1`. A "pipeline" where every block is serial is a very expensive `foreach`.

### 11. `AsOrdered()` kept by habit

Ordering is a constraint the runtime must maintain through every downstream operator and the merge. If a later `OrderBy` exists, or the consumer sorts anyway, `AsOrdered()` is pure cost.

### 12. `.AsParallel()` that silently does nothing

PLINQ falls back to sequential mode for [documented query shapes](#when-plinq-quietly-goes-sequential). "I parallelised it and nothing changed" is usually this, not a measurement error.

### 13. Blocking inside a PLINQ delegate

There is no async PLINQ. A `.Result` inside `AsParallel().Select(...)` parks a pool thread per element and reintroduces starvation.

### 14. A shared flag without `Volatile` or `CancellationToken`

The JIT may hoist the read out of the loop. This is a software effect; it happens on x64.

### 15. `ReaderWriterLockSlim` around a one-line critical section

The bookkeeping costs more than the work. Use `lock`, or `ConcurrentDictionary` if the state is a keyed map.

### 16. Recursive `SemaphoreSlim` acquisition

It counts permits, not owners. A helper that re-acquires the gate its caller already holds waits forever for itself.

### 17. Nested parallelism

A `Parallel.ForEach` whose body contains another `Parallel.ForEach` multiplies the work-item count and typically produces oversubscription and cache thrash rather than speed. Parallelise the outer loop only; the inner one becomes a plain `for`.

### 18. Catching `AggregateException` without `Flatten()`

Nested parallel constructs nest their aggregates. `ex.Flatten().InnerExceptions` is the only enumeration that sees everything.

### 19. Padding on suspicion

False sharing has a specific fingerprint — correct, lock-free, and *negatively* scaling. Padding a structure you have not profiled just makes it bigger and colder.

### 20. Assuming `Environment.ProcessorCount` tracks live CPU limits

It is fixed at runtime startup for the process lifetime. Vertical scaling events are invisible until restart.

---

## Best Practices

1. **Classify the work before choosing the API.** CPU-bound → `Parallel`/PLINQ. I/O-bound → `async` + `Parallel.ForEachAsync`. Mixed → separate the stages so each can be tuned independently.
2. **Default to `Parallel.ForEachAsync` for anything touching the network, a database, or a disk.** It is the .NET 6+ answer and it is right almost every time.
3. **Always pass a `CancellationToken`.** `ParallelOptions.CancellationToken` for the TPL, `WithCancellation` for PLINQ, the token parameter for `ForEachAsync`.
4. **Derive the degree of parallelism from something real** — `Environment.ProcessorCount` for CPU, the downstream's documented concurrency limit for I/O. Never a laptop-shaped constant.
5. **Prefer index-addressed output arrays to concurrent collections.** No synchronisation, no ordering surprise, no allocation churn.
6. **Use `localInit`/`localFinally` for any aggregate.** One shared write per task, not per element.
7. **Wrap expensive `ConcurrentDictionary` values in `Lazy<T>` with `ExecutionAndPublication`.** Assume the bare factory will run more than once, because it will.
8. **Use `Channel<T>` bounded, not unbounded, in production.** Bounded forces you to decide what happens to a slow consumer instead of finding out from the OOM killer.
9. **Reach for Dataflow only when the topology justifies the NuGet dependency** — multi-stage, per-stage parallelism, broadcast, batching, or joins. Otherwise `Channel<T>`.
10. **Set `MaxDegreeOfParallelism` explicitly on every Dataflow block.** The default of `1` is a decision; make it a deliberate one.
11. **Never hand-roll double-checked locking.** `Lazy<T>` exists and Microsoft's own docs point at it.
12. **Use `CancellationToken` for anything that means "stop".** Hand-rolled `bool` flags need `Volatile` and are one refactor away from being wrong.
13. **Keep critical sections shorter than the work they protect.** If the lock body is longer than the loop body, the parallelism is theatre.
14. **Never nest parallel constructs.** Parallelise the outermost loop that has enough items.
15. **Benchmark before and after with BenchmarkDotNet, on hardware shaped like production.** Parallelism is the area where intuition is least reliable and the sequential version wins most often.
16. **Say "measure it" instead of quoting a multiplier.** Speedup depends on core count, per-element cost, memory bandwidth, and partitioning. Anyone quoting a fixed number is guessing.

---

## Real-World Scenarios

### Scenario 1: Nightly Batch That Takes Down the API

**Problem.** A single ASP.NET Core process serves an API and hosts a `BackgroundService` that re-prices 300,000 SKUs every night: fetch current cost from a supplier API, run a pricing model, write the result. Written as one `Parallel.ForEach` with synchronous HTTP and synchronous EF Core calls. During the batch, unrelated endpoints time out.

**Diagnosis.** One thread pool per process. Every parallel iteration parks a pool thread in a blocking HTTP wait, the pool injects replacements gradually, and API requests queue behind the ramp. CPU sits well below saturation the whole time — the fingerprint of starvation, not of overload.

**Solution.** Split by bottleneck and give each stage its own budget.

```csharp
protected override async Task ExecuteAsync(CancellationToken ct)
{
    var costs = new ConcurrentDictionary<int, decimal>();

    // Stage 1 — I/O bound. Concurrency capped by the supplier's rate limit.
    await Parallel.ForEachAsync(
        skuIds,
        new ParallelOptions { MaxDegreeOfParallelism = 20, CancellationToken = ct },
        async (id, token) => costs[id] = await _supplier.GetCostAsync(id, token));

    // Stage 2 — CPU bound. Concurrency capped by cores the container actually has.
    var priced = new PricedSku[skuIds.Count];
    Parallel.For(0, skuIds.Count,
        new ParallelOptions
        {
            MaxDegreeOfParallelism = Environment.ProcessorCount,
            CancellationToken = ct
        },
        i => priced[i] = _model.Price(skuIds[i], costs[skuIds[i]]));

    // Stage 3 — I/O bound, batched. One scope per batch, not per row.
    foreach (var batch in priced.Chunk(1_000))
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        db.AddRange(batch);
        await db.SaveChangesAsync(ct);
    }
}
```

**Decision:** three stages, three degrees of parallelism, three different justifications for the number. **Consequence:** pool thread count stops climbing, API latency stops correlating with the batch window, and each stage can be tuned without disturbing the others.

> 🌐 The detail that made the difference was not the parallelism at all — it was that stage 3 writes in batches inside a scope per batch. See [`IServiceScopeFactory` in non-HTTP contexts](02-dependency-injection.md#iservicescopefactory-in-non-http-contexts) for why a `BackgroundService` must never hold one scope across iterations.

### Scenario 2: A Cache That Stampedes on Cold Start

**Problem.** A `ConcurrentDictionary<string, TenantConfig>` cache populated by `GetOrAdd(key, LoadFromDatabase)`. After every deploy, the first burst of traffic for each tenant issues dozens of identical queries — the classic cache stampede.

**Solution.** `Lazy<T>` collapses the stampede to one query per key, because only the wrapper that wins the insert is ever forced. For an async loader, `Lazy<Task<T>>` does the same job:

```csharp
private readonly ConcurrentDictionary<string, Lazy<Task<TenantConfig>>> _cache = new();

public Task<TenantConfig> GetAsync(string tenantId) =>
    _cache.GetOrAdd(tenantId, id => new Lazy<Task<TenantConfig>>(
        () => LoadFromDatabaseAsync(id),
        LazyThreadSafetyMode.ExecutionAndPublication)).Value;
```

**Decision:** `Lazy<Task<T>>` rather than a lock per key. **Consequence:** N concurrent callers for a cold key share one in-flight `Task`; the other N−1 `Lazy` wrappers are cheap garbage.

> ⚠️ One caveat to state unprompted: a faulted `Task` stays cached. If `LoadFromDatabaseAsync` throws, every subsequent caller receives the same faulted task forever. Evict on failure — `_cache.TryRemove(tenantId, out _)` in a continuation or a `catch` — or the cache turns a transient database blip into a permanent outage for that tenant.

### Scenario 3: Ingest Pipeline With Backpressure

**Problem.** An endpoint receives IoT telemetry at bursty rates and must persist it to a time-series store that is roughly an order of magnitude slower than peak ingest. The first implementation queued to a `ConcurrentQueue` and drained on a timer; a downstream outage produced an OOM kill.

**Solution.** A bounded channel with an explicit full-mode policy, plus a small pool of consumers.

```csharp
private readonly Channel<Reading> _channel = Channel.CreateBounded<Reading>(
    new BoundedChannelOptions(capacity: 10_000)
    {
        FullMode = BoundedChannelFullMode.Wait,   // backpressure, not data loss
        SingleReader = false,
        SingleWriter = false
    });

// Producer (HTTP handler) — surfaces pressure as a retriable status code
public async Task<IResult> Post(Reading r, CancellationToken ct)
{
    using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
    timeout.CancelAfter(TimeSpan.FromMilliseconds(250));
    try
    {
        await _channel.Writer.WriteAsync(r, timeout.Token);
        return Results.Accepted();
    }
    catch (OperationCanceledException) when (!ct.IsCancellationRequested)
    {
        return Results.StatusCode(StatusCodes.Status503ServiceUnavailable);
    }
}

// Consumers — N of them, all reading the same channel
protected override Task ExecuteAsync(CancellationToken ct) =>
    Parallel.ForEachAsync(
        _channel.Reader.ReadAllAsync(ct),          // IAsyncEnumerable<Reading>
        new ParallelOptions { MaxDegreeOfParallelism = 4, CancellationToken = ct },
        async (reading, token) => await _tsdb.WriteAsync(reading, token));
```

**Decision:** bounded capacity plus `Wait`, with a short write timeout at the edge. **Consequence:** memory is capped at a number you chose, the client learns about pressure through a `503` it can retry, and the `ForEachAsync`-over-`IAsyncEnumerable` overload gives the consumer side a degree-of-parallelism knob without any extra plumbing.

> 🌐 **The FullMode choice is domain logic.** The same pipeline carrying *diagnostic* telemetry rather than billing readings would use `BoundedChannelFullMode.DropOldest` — losing the oldest sample is strictly better than rejecting the newest, and nobody wants a debug feed applying backpressure to production. Writing `Wait` by reflex for both is how you end up throttling a business-critical path to protect a log stream.

### Scenario 4: Parallel Aggregation Over a Large File

**Problem.** Compute a histogram over 40 million records loaded into an array. The first attempt used `Parallel.For` with `Interlocked.Increment(ref buckets[b])` and scaled *negatively* past four threads.

**Solution.** Two changes, in this order.

```csharp
// 1. Per-task histograms merged once — removes the shared write entirely
var global = new long[BucketCount];

Parallel.For(
    0, records.Length,
    localInit: () => new long[BucketCount],                 // task-private
    body: (i, _, local) => { local[Bucket(records[i])]++; return local; },
    localFinally: local =>
    {
        for (int b = 0; b < BucketCount; b++)
            Interlocked.Add(ref global[b], local[b]);        // once per task
    });

// 2. If BucketCount is small enough that even the per-task arrays are hot,
//    partition into ranges so the delegate isn't invoked 40 million times.
var partitioner = Partitioner.Create(0, records.Length);
```

**Decision:** eliminate the shared write before considering padding. **Consequence:** the shared-memory traffic drops from one atomic per record to `BucketCount` atomics per task, and the loop begins scaling. Padding was never needed — the per-task arrays are not shared, so there is nothing to falsely share.

> 🌐 **Real-world example — the version that needed padding anyway.** A variant of this job kept a *live* per-shard counter array that a Prometheus scraper read every 15 seconds, so merge-at-the-end was not available: the counters had to be individually addressable at all times. **Decision:** explicit-layout padding, one counter per cache line. **Consequence:** the scraper kept its live view and the workers stopped invalidating each other. **Padding is the fallback for when you genuinely cannot stop sharing — not the first move.**

### Scenario 5: A Query That Got Slower With `.AsParallel()`

**Problem.** A developer added `.AsParallel()` to a LINQ pipeline over 50,000 order rows and reported no improvement — sometimes a regression.

**Diagnosis, in order:**

1. **Is the delegate expensive?** The `Select` was a property projection. Per the docs, "small source collections with trivial delegates are generally not good candidates for PLINQ" — the partition/schedule/merge overhead had nothing to pay it back.
2. **Did PLINQ even parallelise?** The query contained an indexed `Where` after an `OrderBy`, one of the documented shapes PLINQ runs sequentially by default.
3. **Was there shared state?** The projection incremented a captured counter — which would have serialised the query even if it had parallelised, and was a data race besides.
4. **What did the terminal operator cost?** `ToList()` forces a merge of every partition into one structure.

**Solution.** Remove `.AsParallel()`. The genuine win was elsewhere: the expensive stage was a per-order tax calculation further down, which was extracted into its own `Parallel.ForEachAsync` over the already-filtered set.

**Consequence:** the sequential LINQ stayed sequential (correctly), and parallelism was applied to the one stage where the per-element cost justified it. **The general lesson: `.AsParallel()` is not a performance annotation you sprinkle on a query — it is a decision about one specific stage's per-element cost.**

---

## Interview-Ready Summary

- **Concurrency is structure, parallelism is execution.** Dealing with many things at once vs doing many things at once. Async/await is the concurrency tool; `Parallel`/PLINQ is the parallelism tool. Applying either to the other's problem is the archetypal mistake.
- **`Parallel.For`/`ForEach` take a synchronous `Action<T>`; `Parallel.ForEachAsync` takes `Func<T, CancellationToken, ValueTask>`.** An `async` lambda handed to `Parallel.ForEach` becomes `async void` — it compiles, completes instantly, and swallows exceptions.
- **`MaxDegreeOfParallelism` defaults to `-1`, meaning *unlimited* — except on `ForEachAsync`, where `-1` means `ProcessorCount`.** It is a ceiling, not a target. `Environment.ProcessorCount` already accounts for CPU affinity and container CPU limits, and is fixed at process startup.
- **`Parallel.ForEach` over I/O is wrong** because the body must block, blocked threads defeat the pool's gradual injection, the default cap is unlimited, and the damage is process-wide.
- **PLINQ overhead is partition + schedule + merge**, and it must be repaid by expensive per-element delegates. PLINQ silently falls back to sequential for documented query shapes. `AsOrdered()` costs; the docs call it "usually modest" — quote that rather than a number.
- **Partitioning decides whether data parallelism helps.** Range partitioning is free but cannot rebalance; chunk partitioning balances but pays synchronisation "inversely proportional to the size of the chunks." PLINQ uses range-without-load-balancing for arrays and `IList<T>` by default — `Partitioner.Create(source, true)` switches it. `Partitioner.Create(0, len)` collapses per-element delegate dispatch into per-range.
- **`Channel<T>` over `ConcurrentQueue<T>`** because a queue has no awaiting read, no completion signal, and no backpressure. Bounded in production. `CreateUnboundedPrioritized` exists from .NET 9. **Dataflow over `Channel<T>`** when the topology is the point — per-stage parallelism, broadcast, batching, joins — and remember it is a NuGet package with `MaxDegreeOfParallelism = 1` by default.
- **`ConcurrentDictionary` guarantees lock-free reads and fine-grained locked writes.** It does **not** guarantee that `GetOrAdd`'s factory runs once — the docs say it "may be called multiple times, but only one key/value pair will be added" — nor that enumeration is a snapshot, nor that compound operations are atomic. `Lazy<T>` fixes the first; `ToArray()` the second; `TryAdd`/`TryUpdate` the third. A plain `lock` wins when the invariant spans multiple fields.
- **`lock` cannot cross `await`** — CS1996 — because `Monitor` is thread-affine and the continuation may resume elsewhere. `SemaphoreSlim(1,1)` is the async mutex precisely because it counts permits, not owners; which is also why it is not reentrant.
- **`ReaderWriterLockSlim` loses to `lock`** on short critical sections (bookkeeping exceeds the work), on balanced read/write ratios, and any time `ConcurrentDictionary` would have done. Default policy is `NoRecursion`; only one thread may hold upgradeable mode; a plain reader may never upgrade.
- **The .NET memory model:** aligned primitives up to pointer size and all managed references are atomic. Ordinary accesses may be reordered "as long as that preserves single-thread consistency", unused reads elided, adjacent same-location reads coalesced. Volatile read = acquire, volatile write = release, and **lock acquire/release are exactly those**. `Interlocked` and `Thread.MemoryBarrier` are full fences. **Object assignment is a release with respect to the instance's fields**, and **data-dependent reads are ordered** — but **"the .NET runtime does not specify any ordering effects to the instance constructors."**
- **`volatile` gives ordering, not promptness.** The docs are explicit that a volatile read on another processor may still see the old value.
- **Double-checked locking:** testing the *reference itself* is safe on .NET without `volatile` (the spec ships that exact pattern), because of the object-assignment-release and data-dependency guarantees. Testing a *separate flag* is broken without `Volatile.Read`/`Volatile.Write`, because there is no data dependency. In application code, write `Lazy<T>` with `ExecutionAndPublication` and neither question arises.
- **False sharing** is correct, lock-free code that scales *negatively*. The coherence protocol moves cache lines, not variables. The BCL pads for it — `ConcurrentQueueSegment`'s `PaddedHeadAndTail` exists "to avoid false sharing between producers and consumers" — and uses a named constant because the line size is platform-dependent. The better fix is usually to stop sharing (`localInit`/`localFinally`); pad only when the counters must stay individually addressable.

---

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~20-25 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this section once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.

### Drill 1 — Concurrency vs parallelism

> **Q**: What's the difference between concurrency and parallelism, and how does it map onto .NET APIs?
>
> **A**: Concurrency is *dealing with* many things at once — a structuring property. Parallelism is *doing* many things at once — an execution property. In .NET, concurrency is `async`/`await`: the point is to hold **no thread** while waiting for I/O, and it helps even on a single core. Parallelism is the TPL — `Parallel.For`/`ForEach`, PLINQ: the point is to put more cores on CPU-bound work, and it does nothing on one core. The practical test is one question: *is this work waiting, or is it working?*
>
> **Cross-Q**: A single-threaded Node-style event loop — is that concurrent, parallel, both, neither?
>
> **A**: **Concurrent, not parallel.** It has many operations in flight and interleaves them, which is concurrency by definition, but only one thing executes at a time so there is no parallelism. That example is the cleanest disproof of "concurrency means multithreading". The mirror case is also worth naming: a `Parallel.For` running inside a container limited to one CPU is parallel *code* executing with zero parallelism.
>
> **Cross-Q²**: I have a loop that downloads a file, decompresses it, and uploads the result — per item, 5,000 items. Which is it, and what do you use?
>
> **A**: It is **both**, in three stages with different bottlenecks, and that is the tell that one loop is the wrong shape. Download and upload are I/O-bound — concurrency, `Parallel.ForEachAsync`, cap chosen from the remote service's limits. Decompression is CPU-bound — parallelism, cap `Environment.ProcessorCount`. If I write it as a single `Parallel.ForEachAsync` I have to pick one number that is wrong for two of the three stages: too high and the decompression oversubscribes the cores, too low and the transfers underuse the network. The correct structures are either three sequential passes with three degrees of parallelism, or a TPL Dataflow mesh with per-block `MaxDegreeOfParallelism`. **Needing two different degrees of parallelism in one body is the signal you have outgrown a single loop.**

### Drill 2 — `Parallel.ForEach` over I/O

> **Q**: Why is `Parallel.ForEach` usually the wrong tool for I/O-bound work?
>
> **A**: Four reasons that stack. (1) The body is `Action<T>`, so there is nowhere to put a `Task` — you are forced into `.Result`, `.Wait()`, or a synchronous API, all of which park a pool thread for the whole round trip. (2) A parked thread looks like no progress, so the pool injects replacements, and injection is deliberately gradual — your effective concurrency ramps over seconds. (3) `MaxDegreeOfParallelism` defaults to `-1`, documented as *no limit*, so the loop keeps asking for capacity it will immediately block. (4) There is one thread pool per process, so the victims are your HTTP endpoints and your health check, not the batch job. The answer is `Parallel.ForEachAsync`, whose body is `Func<T, CancellationToken, ValueTask>` and therefore holds no thread while awaiting.
>
> **Cross-Q**: Someone "fixes" it by passing an `async` lambda to `Parallel.ForEach`. What happens?
>
> **A**: It compiles, and it is worse. The lambda binds to `Action<T>`, so an `async` lambda there is **`async void`**: the loop treats the delegate as complete the moment it *returns at the first await*, so `Parallel.ForEach` finishes almost instantly with all the work still in flight. Nothing awaits those state machines, so exceptions are not captured on any Task — with no `SynchronizationContext` installed they surface on a pool thread, and per Microsoft's thread pool documentation an unhandled exception on a pool thread terminates the process. There is no compiler error because `async void` is a legal `Action<T>`. This is one of the highest-signal traps in the TPL precisely because the code reads correctly.
>
> **Cross-Q²**: Is there *any* case where `Parallel.ForEach` over I/O is defensible?
>
> **A**: Yes, and saying so is stronger than the absolutist answer. A console tool or one-shot migration utility, where there is no other traffic in the process to starve and the library you must call genuinely has no async API — `Parallel.ForEachAsync` cannot await a method that does not exist. In that case you are trading threads for wall-clock in a process that has nothing else to do, which is a legitimate trade. What makes it defensible is the *absence of a shared pool with other consumers*. Inside a web host, that condition never holds.

### Drill 3 — `MaxDegreeOfParallelism`

> **Q**: What does `MaxDegreeOfParallelism` default to, and what does the default mean?
>
> **A**: `-1`. For `Parallel.For` and `Parallel.ForEach` the docs say that means "there is no limit on the number of concurrently running operations" — the underlying scheduler decides. For `Parallel.ForEachAsync`, `-1` means `ProcessorCount`, which is also documented on the overloads that take no `ParallelOptions`: "the operation will execute at most `ProcessorCount` operations in parallel." So the same property has two meanings depending on the method, which is exactly the kind of asymmetry that gets asked about. It is also a **ceiling, not a target** — the docs are explicit that changing it "only limits how many concurrent tasks will be used."
>
> **Cross-Q**: I set it to `Environment.ProcessorCount` and my container has a `500m` CPU limit. What value do I get, and does it change if the limit is raised at runtime?
>
> **A**: You get **1**. On Linux and macOS for all versions, and on Windows from .NET 6, `Environment.ProcessorCount` returns the minimum of the machine's logical processors, the affinity count if the process is affinitised, and "the CPU utilization limit rounded up to the next whole number" — `0.5` rounds up to `1`. And no, raising the limit later has no effect: the docs say the value "is fixed at .NET runtime startup for the process lifetime. It does not reflect changes in the environment settings while the process is running." A vertical-scale event needs a restart to be observed. `DOTNET_PROCESSOR_COUNT` can override the computed value, which is useful for pinning behaviour in tests and dangerous if someone sets it in a chart and forgets.
>
> **Cross-Q²**: For an I/O loop, should `MaxDegreeOfParallelism` be `ProcessorCount`?
>
> **A**: **No, and being able to say why is the point.** For CPU work the constraint is cores, so `ProcessorCount` is the right derivation. For I/O work no core is occupied while waiting, so core count is irrelevant — the constraint is whatever the *other side* can take: the API's documented rate limit, the connection pool size, the egress proxy's concurrency cap, the database's `max_connections`. Deriving an I/O cap from `ProcessorCount` is a category error that happens to look responsible. If I set 24 for an I/O loop, I should be able to point at the thing that said 24.

### Drill 4 — Aggregation in a parallel loop

> **Q**: I want to sum a computed value over ten million elements in parallel. How?
>
> **A**: The `localInit`/`localFinally` overload of `Parallel.For`. Each participating task gets a private accumulator from `localInit`, the body **returns** the updated local rather than mutating a captured variable, and `localFinally` merges once per task with `Interlocked.Add`. If there are eight tasks, there are eight shared writes total, not ten million.
>
> **Cross-Q**: Why not just `lock (_gate) { total += x; }` in the body — the lock is uncontended most of the time, isn't it?
>
> **A**: It is contended by construction — that is the whole point of the loop. Every iteration on every core takes and releases the same lock, so the loop is serialised at its narrowest point and you have added lock overhead on top. Even switching to `Interlocked.Add` in the body only removes the lock, not the sharing: the cache line holding `total` still bounces between cores on every increment, so throughput is bounded by the interconnect rather than by the arithmetic. **The fix is not a faster synchronisation primitive — it is fewer shared writes.**
>
> **Cross-Q²**: My aggregate is a 256-bucket histogram, and a metrics endpoint has to read it *live*. `localFinally` doesn't apply. Now what?
>
> **A**: Now the counters must be individually addressable at all times, so merge-at-the-end is genuinely unavailable and I have to deal with the sharing directly. 256 `long`s occupy a handful of cache lines, so 32 threads incrementing 256 different counters are still fighting over a small number of lines — **false sharing**, whose fingerprint is correct, lock-free code that gets *slower* as you raise the degree of parallelism. The fix is padding each counter onto its own line with an explicit-layout struct, which is exactly what the BCL does in `ConcurrentQueueSegment`'s `PaddedHeadAndTail` — "to avoid false sharing between producers and consumers". Two caveats I'd add unprompted: the line size is platform-dependent, which is why the BCL uses a named constant instead of a literal, and padding inflates the array, so I'd only do it after confirming the negative-scaling signature in a profile.

### Drill 5 — PLINQ performance

> **Q**: I added `.AsParallel()` to a LINQ query and it got slower. Give me the checklist.
>
> **A**: Four things, in order. (1) **Is the delegate expensive enough?** PLINQ has to partition, schedule, and merge; the docs say "small source collections with trivial delegates are generally not good candidates for PLINQ." A property projection cannot repay that. (2) **Did it parallelise at all?** PLINQ analyses query shape and falls back to sequential for documented patterns — indexed `Where`/`Select`/`ElementAt` after an ordering or filtering operator that rearranged indices, `Take`/`Skip` on reordered sources, `Zip`, `Concat`, `Reverse` on non-indexable sources. (3) **Is there shared state in a delegate?** A captured counter or list serialises the query and is a data race besides. (4) **What does the terminal operator cost?** `ToList`/`ToArray` force a merge of every partition; `foreach` serialises results onto the enumerator thread. `ForAll` skips the merge entirely.
>
> **Cross-Q**: What exactly does `AsOrdered()` cost, and when is it free?
>
> **A**: It is never free, and Microsoft's own wording is the safest thing to quote: "There is a cost associated with ordering, but this cost is usually modest." Mechanically, PLINQ must track each element's ordinal index through every downstream operator and reassemble at the merge, which means buffering — a partition that finishes early cannot yield until the partitions ahead of it have. `GroupBy` and `Join` are called out as carrying their own overhead for the same structural reason. Where it is *pure waste* is when a later `OrderBy` or a sorting consumer exists — then you paid to preserve an order that gets discarded. The mitigation is scoping: `AsOrdered()` for the stage that needs it, `AsUnordered()` before the expensive stage that does not.
>
> **Cross-Q²**: Can I use PLINQ for a batch of HTTP calls if I'm careful?
>
> **A**: No. PLINQ is synchronous by design — there is no async operator, no `AsParallelAsync`, and the delegates return values, not tasks. "Careful" would mean `.Result` or `.GetAwaiter().GetResult()` inside each delegate, which parks a pool thread per element and reproduces every problem from Drill 2 with worse ergonomics. The correct answer is `Parallel.ForEachAsync`. PLINQ's niche is CPU-bound, side-effect-free, expensive-per-element transformation — and the honest follow-up is that even there, `Parallel.ForEach` over a partitioner is often simpler to reason about and easier to cap.

### Drill 6 — Partitioning

> **Q**: What is partitioning and why does chunk size decide whether data parallelism helps?
>
> **A**: Partitioning is how a data-parallel construct decides who processes which elements. Two strategies. **Range partitioning** splits an indexable source into contiguous index ranges up front — zero synchronisation afterwards, but per the docs "if one thread finishes early, it cannot help the other threads finish their work." **Chunk partitioning** hands each task a chunk on demand and lets it come back for more — inherently load-balancing, but "the partitioner does incur the synchronization overhead each time the thread needs to get another chunk," and crucially "the amount of synchronization incurred in these cases is inversely proportional to the size of the chunks." That last sentence is the whole trade-off: small chunks balance well and synchronise often; large chunks synchronise rarely and balance badly. Pick wrong in either direction and the parallelism is eaten by coordination or by idle cores.
>
> **Cross-Q**: My source is an array and per-element cost varies by two orders of magnitude. What does PLINQ do by default and how do I fix it?
>
> **A**: Exactly the wrong thing: "By default when it is passed an IList or an array, PLINQ always uses range partitioning without load balancing." Equal index ranges with wildly unequal costs means one task grinds while the rest finish and idle. The fix is `Partitioner.Create(source, loadBalance: true)` and querying the partitioner instead of the array — the overload table documents which overloads load-balance: the `IEnumerable<T>` one always does, the array and `IList<T>` ones do when the boolean is `true`, and the numeric range overloads never do.
>
> **Cross-Q²**: Opposite problem — my body is three arithmetic operations and the loop won't scale. Same fix?
>
> **A**: No, the opposite fix. Here the body is smaller than the machinery around it: the docs note "the cost of invoking that delegate is about the same as a virtual method call", and at three operations per element the dispatch dominates. Load balancing would make it worse by adding synchronisation. The fix is `Partitioner.Create(0, source.Length)`, which yields `Tuple<int,int>` ranges, and a plain `for` inside the body — one delegate invocation per range instead of per element. The three-argument overload lets you dictate `rangeSize` directly, which the docs recommend "in scenarios where the work per element is so low that even one virtual method call per element has a noticeable impact." **Uneven cost → more partitioning. Trivial body → less.**

### Drill 7 — `Channel<T>` vs `ConcurrentQueue<T>` vs Dataflow

> **Q**: I have producers and consumers. Why not just a `ConcurrentQueue<T>`?
>
> **A**: Because `ConcurrentQueue<T>` is a data structure, not a pipeline, and it is missing the two things a pipeline needs. First, **no awaiting read** — the consumer has to poll with `TryDequeue` plus a `Task.Delay`, which is simultaneously a latency floor and wasted CPU, and tuning the delay only moves the problem between the two. Second, **no backpressure** — it is unbounded, so when the consumer falls behind, memory grows until the process dies. `Channel<T>` gives you `ReadAllAsync` (no polling), `CreateBounded` with a `FullMode` policy (backpressure), and `Writer.Complete()` (a real completion signal, so `ReadAllAsync` ends and shutdown works).
>
> **Cross-Q**: What are the bounded full modes and how do you choose between them?
>
> **A**: `Wait` blocks the producer until space frees — genuine backpressure, and the right default for anything where losing an item is a business problem. `DropWrite` discards the incoming item, `DropOldest` and `DropNewest` discard from the buffer. It is a **domain decision, not a performance tuning knob**: an order pipeline wants `Wait`, a diagnostic telemetry feed wants `DropOldest` because losing the oldest sample beats applying backpressure to production, and a "latest value" gauge is a capacity-1 channel with `DropOldest`. Reaching for `Wait` by reflex on a log stream is how you end up throttling a critical path to protect a debug feed. Worth also knowing: .NET 9 added `Channel.CreateUnboundedPrioritized<T>`, which reads lowest-priority-value first — but there is no bounded prioritised variant, so it is priority *or* backpressure, not both.
>
> **Cross-Q²**: When would you take the Dataflow NuGet dependency instead?
>
> **A**: When the topology is the point, not the queue. Four things Dataflow does that `Channel<T>` will not: per-stage `MaxDegreeOfParallelism` in one mesh, so a network-bound stage and a CPU-bound stage can each run at their natural rate; **broadcast** via `BroadcastBlock<T>`, where every linked consumer gets every item — something a channel deliberately does not do, since a channel item goes to exactly one reader; batching via `BatchBlock<T>`; and completion that propagates along links with `PropagateCompletion`. Two things to flag: it is *not* distributed with .NET — the docs say so explicitly, it is the `System.Threading.Tasks.Dataflow` package — and `ExecutionDataflowBlockOptions.MaxDegreeOfParallelism` **defaults to 1**, so every block is serial until you say otherwise. "I built a Dataflow pipeline and it isn't parallel" is almost always that default.

### Drill 8 — `ConcurrentDictionary` guarantees

> **Q**: What does `ConcurrentDictionary<TKey,TValue>` actually guarantee?
>
> **A**: Two things, precisely. Reads are **lock-free** — the docs say "read operations on the dictionary are performed in a lock-free manner". Writes use **fine-grained locking** rather than one global lock, so concurrent writers to different keys generally don't serialise. That is it. It does not guarantee that compound operations are atomic, that enumeration is a snapshot, or that the delegate you hand to `GetOrAdd`/`AddOrUpdate` runs once.
>
> **Cross-Q**: Walk me through the `GetOrAdd` factory guarantee. Exactly what can happen?
>
> **A**: The docs are quotable here: "the `valueFactory` delegate is called outside the locks to avoid the problems that can arise from executing unknown code under a lock. Therefore, `GetOrAdd` is not atomic with regards to all other operations." And: "If you call `GetOrAdd` simultaneously on different threads, `valueFactory` may be called multiple times, but only one key/value pair will be added to the dictionary." So the **dictionary** is consistent — one entry, and every caller receives the same value — but **your factory** is not: N concurrent callers on a cold key can run it N times, and N−1 results are silently discarded. That is harmless for a pure computation and a resource leak for anything that opens a socket, a file, or a connection, because nothing disposes the losers. The fix is `ConcurrentDictionary<K, Lazy<V>>` with `LazyThreadSafetyMode.ExecutionAndPublication` — the wrapper may be constructed many times, but only the one that wins the insert is ever returned, so only its factory is ever forced.
>
> **Cross-Q²**: When would you use a plain `lock` over a `Dictionary<,>` instead?
>
> **A**: Three cases. (1) **The invariant spans more than one thing.** `ConcurrentDictionary` makes each *operation* atomic; it cannot make your *transaction* atomic. If a write must update the map, a counter, and a secondary index together, per-key locking does not help and you get states no single-threaded run could produce. (2) **Write-dominated with low contention.** The concurrent version pays a bucket-and-lock array, more per-entry allocation, and a `Count` that is no longer a field read; if one or two threads write far more than anyone reads, `lock` + `Dictionary<,>` is leaner. (3) **You need a consistent multi-key read** — three `TryGetValue` calls are three independently-timed observations, whereas one lock makes them one. And the fourth thing I would mention: enumeration is documented as *not* "a moment-in-time snapshot", so anything that needs a coherent view calls `ToArray()`, which does take the locks.

### Drill 9 — Synchronisation choice

> **Q**: Why can't you hold a `lock` across an `await`?
>
> **A**: Because `lock` over an ordinary object compiles to `Monitor.Enter`/`Monitor.Exit`, and `Monitor` is **thread-affine** — the thread that entered must be the thread that exits. A continuation after an `await` may resume on a different pool thread, at which point `Monitor.Exit` would throw `SynchronizationLockException`. Rather than let you emit code that can hit that, the compiler rejects it outright with **CS1996**. The same restriction applies to `System.Threading.Lock` in .NET 9 — the language reference says "You can't use the `await` expression in the body of a `lock` statement." The replacement is `SemaphoreSlim(1, 1)` with `WaitAsync`/`Release`, which works precisely because a semaphore counts *permits*, not *owners*, so a continuation on another thread may legally release it.
>
> **Cross-Q**: What do you lose by switching from `lock` to `SemaphoreSlim(1,1)`?
>
> **A**: **Reentrancy.** `lock` lets the same thread re-enter and requires a matching number of exits; `SemaphoreSlim` has no concept of an owner, so a public method that takes the gate and then calls a private helper that takes the same gate waits forever for itself. It is not a deadlock between two threads — it is one logical operation deadlocking against itself, which is harder to spot in a stack trace. The discipline is *acquire exactly once at the public entry point* and let internal helpers assume the gate is held, ideally with a naming convention (`FooCore` = "gate already held"). You also lose the compiler-generated `try`/`finally`, so every `WaitAsync` needs a hand-written `finally { Release(); }`.
>
> **Cross-Q²**: When does `ReaderWriterLockSlim` lose to a plain `lock`?
>
> **A**: Mechanism first: `ReaderWriterLockSlim` maintains reader counts, waiter counts, upgrade state and events, whereas an uncontended `Monitor` acquire is a thin-lock CAS on the object header. So for a critical section of a few instructions — a `TryGetValue`, a field read — the bookkeeping costs more than the work, and the "many concurrent readers" benefit never materialises because nobody was waiting. It also loses when reads and writes are roughly balanced, and any time the state is a keyed map, because `ConcurrentDictionary`'s read path takes no lock at all. There are documented subtleties I'd raise too: the default is `NoRecursion`; only one thread may hold upgradeable mode at a time; a thread that entered plain read mode may **never** upgrade — "if two threads in read mode both try to enter write mode, they will deadlock"; and readers are blocked while writers are queued, a fairness policy that favours writers. It earns its keep for genuinely long critical sections over structured state that isn't a dictionary.

### Drill 10 — The memory model, part 1

> **Q**: A worker loops on `while (!_stop)` and another thread sets `_stop = true`. Why might the loop never exit?
>
> **A**: Two independent reasons, and both should be named. **The JIT may hoist the read.** Nothing inside the loop modifies `_stop` as far as the optimiser can see, so it can load it once into a register and test the register forever. The .NET memory model spec permits it — "the effects of ordinary reads and writes can be reordered as long as that preserves single-thread consistency", and "adjacent non-volatile reads from the same location can be coalesced" — and the `Volatile` docs state the converse guarantee, that volatile accesses "ensure that a value is read or written to memory and not cached (for example, in a processor register)". **Separately, the hardware may delay visibility.** The first reason is the important one for interviews because it is a pure software effect: it will happen on an x64 laptop in Release. "It only breaks on ARM" is a comforting story that a release-mode JIT disproves.
>
> **Cross-Q**: So marking it `volatile` fixes it. Does `volatile` make the write immediately visible to the other thread?
>
> **A**: **No — and the docs say so in a sentence worth memorising**: "Even though the volatile write to `y` on thread 1 occurred before the volatile read of `y` on thread 2, thread 2 may still see `y2 == 0`. The volatile write to `y` does not guarantee that a following volatile read of `y` on a different processor will see the updated value." `volatile` gives **ordering, not promptness**. Its guarantee is conditional: *if* you observe the volatile write, you also observe everything that preceded it in program order. It says nothing about *when*. Anyone describing `volatile` as "makes writes immediately visible" has the model wrong, and that phrasing is a common interview tell.
>
> **Cross-Q²**: Two limits of the C# `volatile` keyword and what you use instead?
>
> **A**: It **cannot be applied to array elements**, and it **cannot be applied to `long`/`double`** — the C# reference enumerates the permitted types rather than stating a size rule, and says the exclusions exist "because reads and writes to fields of those types can't be guaranteed to be atomic". (Worth getting right under cross-examination: it is *not* a "pointer size or smaller" rule — `IntPtr` is permitted and `long` is not, though both are 8 bytes on 64-bit.) `Volatile.Read`/`Volatile.Write` cover both — they take the location by `ref`, so `Volatile.Read(ref arr[i])` is fine, and per the docs "volatile reads and writes on such 64-bit memory are atomic even on 32-bit processors, unlike regular reads and writes." .NET 10 also added standalone `Volatile.ReadBarrier()` and `Volatile.WriteBarrier()` for when you want the fence without an access. And the honest closing: for anything that means "stop", none of this is the right API — `CancellationToken` is, and the runtime handles the publication for you.

### Drill 11 — The memory model, part 2

> **Q**: What does the .NET memory model actually guarantee?
>
> **A**: Four categories. **Atomicity**: "memory accesses to properly aligned data of primitive and Enum types with sizes up to the platform pointer size are always atomic", and managed references are always aligned and atomic — so `int`, `bool`, `char`, enums and references are safe; `long`/`double` are not on 32-bit; and no multi-field struct is atomic at all. **Ordinary accesses** may be reordered "as long as that preserves single-thread consistency", with unused reads elided and adjacent same-location accesses coalesced. **Volatile read = acquire** ("no read or write that is later in the program order may be speculatively executed ahead of a volatile read") and **volatile write = release** ("the effects of a volatile write will not be observable before effects of all previous, in program order, reads and writes become observable") — and critically, **lock acquisition is an acquire and lock release is a release**. **Full fences**: `Thread.MemoryBarrier` and every `Interlocked` method. The model is deliberately stronger than ECMA-335.
>
> **Cross-Q**: The spec says "the .NET runtime does not specify any ordering effects to the instance constructors." Doesn't that make `_shared = new Node { Value = 42 }` unsafe?
>
> **A**: No, and the resolution is the interesting part. The safety does not come from the constructor — it comes from the **assignment that publishes the reference**. The spec states: "Object assignment to a location potentially accessible by other threads is a release with respect to accesses to the instance's fields/elements and metadata." So the write of `Value` cannot become observable after the write of `_shared`. And on the reading side: "Memory ordering honors data dependency… it is guaranteed that reading of the data will not happen ahead of obtaining the reference." Together those two mean a thread that sees the new reference cannot see an uninitialised object. The constructor carrying no ordering of its own is true and irrelevant, because publication is what is being ordered.
>
> **Cross-Q²**: So is `long`/`double` tearing a real risk in code you'd write today?
>
> **A**: On 64-bit it is not, for a single aligned field — the platform pointer size covers it. Where it stays real is 32-bit targets, which still exist in some device and legacy scenarios, and that is what `Interlocked.Read(ref long)` and `Volatile.Read(ref long)` are for. The risk that *has not* gone away on any platform is **structs**: `decimal`, `Guid`, `DateTime` in some layouts, and every multi-field value type you write are all larger than a pointer and can therefore be read torn — half old, half new — with no exception and no diagnostic. The mitigations are a lock, or boxing the value into an immutable reference type and swapping the reference with `Interlocked.Exchange`, which brings you back into the atomic-reference guarantee.

### Drill 12 — Double-checked locking

> **Q**: Does double-checked locking need `volatile` in .NET?
>
> **A**: **It depends on what you're testing, and the honest answer distinguishes the two cases.** If the pattern tests the **reference itself** — `if (_inst == null) { lock { if (_inst == null) _inst = new Singleton(); } }` — it is safe on .NET *without* `volatile`, and the runtime's own memory-model spec ships exactly that code as a correct example, with inline comments noting that taking the lock is an acquire and releasing it is a release. The two guarantees underneath are object-assignment-is-a-release and data-dependent-reads-are-ordered. If the pattern tests a **separate flag** — a `bool _initialized` guarding a `_config` field written beside it — it is **broken** without `Volatile`, because there is no data dependency between the flag and the data for the model to hang ordering on.
>
> **Cross-Q**: Show me the broken one and explain the failure step by step.
>
> **A**: Writer, inside the lock: `_config = Load();` then `_initialized = true;` — two ordinary writes. Reader, on the fast path, takes **no lock**, so it gets no acquire fence: it does an ordinary read of `_initialized`, then an ordinary read of `_config`. Those are two different locations with no dependency, and the model permits reordering them because single-threaded you could never tell. So a reader can observe `_initialized == true` and `_config == null` and dereference null. The fix is a release/acquire pair *on the flag*: `Volatile.Write(ref _initialized, true)` after the `_config` write, so the write of `_config` cannot become observable after it; and `Volatile.Read(ref _initialized)` on the fast path, so the read of `_config` cannot be hoisted above it. Marking the field `volatile` does the same for every access. The signature of the bug in production is exactly what you'd predict: rare, load-dependent, machine-dependent, and unreproducible on the developer's box.
>
> **Cross-Q²**: What would you actually ship?
>
> **A**: `Lazy<T>` with `LazyThreadSafetyMode.ExecutionAndPublication`, and I'd cite Microsoft's own `Volatile` documentation, which says the `Lazy<T>` class "provides a simple way to write lazy initialization code without directly using double-checked locking." It is fewer lines, it is correct by construction, and it removes the whole category of question. `LazyInitializer.EnsureInitialized` is the lower-allocation alternative when the `Lazy<T>` wrapper object itself has been measured to matter. The `Interlocked.CompareExchange` variant that the spec also documents is fine for cheap objects but has the same trade-off as `GetOrAdd`: it may **construct** more than one instance and publish only one, so it is wrong for anything that opens a resource.

### Drill 13 — False sharing

> **Q**: A lock-free counter array gets *slower* as I add threads. Correct results, no contention counters. What is it?
>
> **A**: False sharing. Cache coherence operates on **cache lines**, not variables. If several counters sit inside one line, every write by one core invalidates every other core's copy of that whole line — even though the cores are touching different counters and are logically independent. The line ping-pongs across the interconnect on every increment and both cores stall. "False" because the sharing is an artefact of memory layout, not of the program's logic. The fingerprint is exactly what was described: correct, lock-free, and **negative** scaling with degree of parallelism, with nothing to show in lock-contention counters because there is no lock.
>
> **Cross-Q**: How do you confirm it and how do you fix it?
>
> **A**: Confirm with hardware counters — cache-line invalidation events, `perf c2c` on Linux or VTune's memory-access analysis — plus the simplest experiment: increase the spacing between the counters and see whether the negative scaling inverts. Fix by padding each counter onto its own cache line with `[StructLayout(LayoutKind.Explicit, Size = …)]` and an array of that struct; `ref array[i].Value` gives you a genuine interior reference so `Interlocked.Increment` still works. The BCL does exactly this and it's the citation I'd give: `ConcurrentQueueSegment<T>` holds its indices in `PaddedHeadAndTail`, commented "Padded head and tail indices, to avoid false sharing between producers and consumers", with head and tail separated by a full line and the struct padded at both ends. Note it uses a **named constant** for the size, not a literal — the line size is platform-dependent, so I would not quote a number.
>
> **Cross-Q²**: When is padding the wrong answer?
>
> **A**: Most of the time, because it treats the symptom. The cause is that per-thread state was placed in shared memory, and the better fix is usually to stop sharing: `Parallel.For`'s `localInit`/`localFinally` gives each task a private accumulator merged once at the end, so there is nothing to falsely share and no padding needed. Padding is the fallback for when the counters must be **individually addressable at all times** — a live metrics array a scraper reads, a per-shard rate limiter. It also has a real cost: padding sixty-four counters to a line each turns a compact array into kilobytes, which is its own cache-footprint problem if anything scans it. And I would never pad read-mostly data — a shared line nobody writes stays valid in every core's cache, which is a *benefit*.

### Drill 14 — Putting it together

> **Q**: Design the concurrency for a service that ingests CSV uploads: parse each row, validate against a reference table, enrich via an external API, and bulk-insert. Files are up to a million rows.
>
> **A**: Four stages with three different characters, so I'd resist writing one loop. **Parse** is CPU-bound and streaming — read with `IAsyncEnumerable<Row>` so a million rows never materialise at once. **Validate** is CPU-bound against an in-memory reference table, which I'd hold as an `ImmutableDictionary` published with `Interlocked.CompareExchange` so validators read it with zero synchronisation. **Enrich** is I/O-bound — `Parallel.ForEachAsync` with `MaxDegreeOfParallelism` derived from the external API's documented rate limit, not from `ProcessorCount`. **Insert** is I/O-bound and batched — chunk into bulk operations, one DI scope per batch. Between the stages, bounded `Channel<T>`s so a fast parser cannot buffer the whole file ahead of a slow enricher.
>
> **Cross-Q**: Where's the memory-model risk in that design?
>
> **A**: Three places. (1) The **reference table swap**: if I published it with a plain assignment and validators read it with a plain read, a validator's read could be hoisted out of its loop and it would use a stale table indefinitely — hence `Volatile.Read` on the load and `Interlocked.CompareExchange` on the publish, which is a full fence. (2) Any **shared progress counter** for the upload's status endpoint — that is a cross-thread flag and needs `Interlocked`, and if there is one per shard it is a false-sharing candidate. (3) Any **"finished" flag** used to end a consumer loop, which should not exist at all: `Writer.Complete()` on the channel and a `CancellationToken` are the correct signals, and both handle publication properly.
>
> **Cross-Q²**: How do you decide the degree of parallelism for each stage, and how do you know the design worked?
>
> **A**: Each number needs a *source*, and I should be able to point at it. Parse and validate: `Environment.ProcessorCount`, which already accounts for container CPU limits and affinity. Enrich: the external API's rate limit or the egress connection cap — whichever is smaller — never core count, because no core is held while awaiting. Insert: the database's connection pool size. For verification I'd watch four things: thread-pool thread count should stay *flat* under load, not climb (climbing means something is blocking); CPU should approach saturation during parse/validate and stay low during enrich; the channel depths tell me which stage is the bottleneck; and end-to-end throughput before and after, measured on production-shaped hardware. **I would not quote a speedup multiplier — the number depends on core count, per-row cost, and the external API's latency, and any figure I gave without measuring would be invented.**

---

</details>

---

## Cheat Sheet

- **Concurrency = dealing with many things at once (structure) · Parallelism = doing many things at once (execution).** Async/await for the first, `Parallel`/PLINQ for the second. A single-threaded event loop is concurrent, not parallel. `Parallel.For` on a one-core pod is parallel code with no parallelism.
- **The three loops**: `Parallel.For` (indexed, sync body) · `Parallel.ForEach` (any `IEnumerable<T>`, sync body) · `Parallel.ForEachAsync` (.NET 6+, `Func<T, CancellationToken, ValueTask>`, `IEnumerable<T>` **or** `IAsyncEnumerable<T>`).
- **`async` lambda + `Parallel.ForEach` = `async void`.** Compiles, returns instantly, work still in flight, exceptions unobservable. Use `ForEachAsync`.
- **`MaxDegreeOfParallelism` defaults to `-1`** = *no limit* for `For`/`ForEach`; **= `ProcessorCount` for `ForEachAsync`**. A ceiling, not a target. `0` or `< -1` throws.
- **`Environment.ProcessorCount`** = min(logical CPUs, affinity count, CPU-utilisation limit rounded up). **Fixed at process startup.** Overridable via `DOTNET_PROCESSOR_COUNT`.
- **Cap derivation**: CPU work → `Environment.ProcessorCount`. I/O work → the downstream's limit (rate limit, pool size, proxy cap). Never a laptop-shaped constant.
- **Aggregate with `localInit`/`localFinally`** — the body *returns* the new local; `localFinally` is the only shared write. One `Interlocked.Add` per task, not per element.
- **`Break()` vs `Stop()`**: `Break()` guarantees lower-index iterations still run and sets `ParallelLoopResult.LowestBreakIteration`; `Stop()` abandons everything at the earliest convenience. Neither cancels iterations already begun — poll `ShouldExitCurrentIteration`.
- **PLINQ overhead = partition + schedule + merge**, repaid only by expensive per-element delegates. "Small source collections with trivial delegates are generally not good candidates for PLINQ."
- **PLINQ goes sequential by default** for indexed `Select`/`Where`/`SelectMany`/`ElementAt` after reordering, `Take`/`Skip` on reordered sources, and `Zip`/`SequenceEquals`/`Concat`/`Reverse` on non-indexable sources. Override with `ParallelExecutionMode.ForceParallelism` — after measuring.
- **`WithDegreeOfParallelism(n)`**: `n` must be 1–512, and may appear only once per query. `ForAll` skips the merge. `WithCancellation` throws `OperationCanceledException`; delegate failures arrive as `AggregateException` — always `.Flatten()`.
- **Partitioning**: range = free but cannot rebalance · chunk = balances, with synchronisation "inversely proportional to the size of the chunks". PLINQ uses **range without load balancing** for arrays/`IList<T>`. `Partitioner.Create(src, true)` → chunk. `Partitioner.Create(0, len)` → ranges, killing per-element delegate dispatch. `EnumerablePartitionerOptions.NoBuffering` → one item at a time, for latency.
- **`ConcurrentQueue` → `Channel<T>` → Dataflow**, in increasing order of capability. The queue has no awaiting read, no completion, no backpressure. Channel adds all three: `CreateBounded` with a deliberate `FullMode` (`Wait` / `DropWrite` / `DropOldest` / `DropNewest`), and always call `Writer.Complete()`. `CreateUnboundedPrioritized` is .NET 9+ (no bounded variant, so priority *or* backpressure).
- **Dataflow** = NuGet (`System.Threading.Tasks.Dataflow`), not in-box. Defaults: `MaxDegreeOfParallelism` **1**, `BoundedCapacity` −1, `MaxMessagesPerTask` −1. Use it for per-stage parallelism, `BroadcastBlock` (channels don't broadcast), `BatchBlock`, joins, `PropagateCompletion`.
- **`ConcurrentDictionary` guarantees**: lock-free reads, fine-grained locked writes. **Does not guarantee**: a single factory invocation (`valueFactory` "may be called multiple times, but only one key/value pair will be added"), snapshot enumeration ("does not represent a moment-in-time snapshot"), or atomic compound operations. Fixes: `Lazy<T>` + `ExecutionAndPublication`, `ToArray()`, `TryAdd`/`TryUpdate`.
- **A plain `lock` beats `ConcurrentDictionary`** when the invariant spans multiple fields, when writes dominate at low contention, or when you need a consistent multi-key read.
- **`lock` can't cross `await`** — CS1996; `Monitor` is thread-affine and the same holds for `System.Threading.Lock`. `SemaphoreSlim(1,1)` is the async mutex: it counts permits, not owners — hence it works across `await` and hence it is **not reentrant**. Acquire once per public entry point.
- **`ReaderWriterLockSlim`**: default `NoRecursion`; one upgradeable holder at a time; a plain reader may **never** upgrade; readers block while writers queue. Loses to `lock` on short sections and balanced ratios, loses to `ConcurrentDictionary` for keyed caches, and has **no async API**.
- **Memory model — atomicity**: aligned primitives and enums up to pointer size, plus all managed references. Not `long`/`double` on 32-bit. **Never** multi-field structs.
- **Memory model — ordering**: ordinary accesses reorder freely within single-thread consistency (unused reads elided, adjacent same-location accesses coalesced) · volatile read = **acquire** · volatile write = **release** · **lock acquire/release are exactly those** · `Interlocked` and `Thread.MemoryBarrier` are full fences.
- **Memory model — publication**: "Object assignment… is a release with respect to accesses to the instance's fields" · "data-dependent reads are ordered" · but "**the .NET runtime does not specify any ordering effects to the instance constructors**".
- **`volatile` = ordering, not promptness.** A volatile read on another processor may still see the old value. It can't be applied to array elements or `long`/`double` — use `Volatile.Read`/`Write`. `Volatile.ReadBarrier`/`WriteBarrier` are **.NET 10+**.
- **DCL**: testing the **reference** is safe without `volatile` on .NET (the spec ships that example). Testing a **separate flag** needs `Volatile.Write` (release) + `Volatile.Read` (acquire). Ship `Lazy<T>` with `ExecutionAndPublication` and the question never arises.
- **False sharing** = correct, lock-free, *negatively* scaling code. Coherence moves cache lines, not variables. BCL evidence: `ConcurrentQueueSegment`'s `PaddedHeadAndTail`, "to avoid false sharing between producers and consumers", sized by a **named constant** because the line size is platform-dependent. Prefer eliminating the sharing over padding it.

---

## Walkthrough

<details>
<summary>📖 Click to expand — a nightly batch that took out the API, end to end</summary>

A composite scenario assembled from how this failure usually presents. The diagnostic *shape* is what to rehearse, not the specific numbers.

**Symptom.** One ASP.NET Core process hosts a public API and a `BackgroundService` that re-prices the catalogue nightly. Every night between 01:00 and 04:00, unrelated API endpoints — including `/health` — return gateway timeouts. Container CPU during the window sits nowhere near its limit. Restarting the pod clears it until the next night.

**Diagnosis chain.**

1. **CPU is low while latency is high.** That combination rules out "the batch is CPU-hungry" and points at threads, not cores. A saturated box looks different.

2. **Watch the pool.** `dotnet-counters monitor -n api` shows `dotnet.thread_pool.thread.count` climbing steadily through the window, `dotnet.thread_pool.queue.length` high, and `dotnet.thread_pool.work_item.count` low — lots pending, little completing. That is the starvation fingerprint (full counter list on the [async page](03-async-and-threading.md#thread-pool-starvation)).

3. **Find who is blocking.** `dotnet-stack report -n api` shows dozens of threads whose bottom frames are `ThreadPoolWorkQueue.Dispatch()` and whose top frames are `Task.SpinThenBlockingWait` → `GetResultCore`. Something calls `.Result` on pool threads, many times over.

4. **Read the batch.**

   ```csharp
   // The original
   Parallel.ForEach(skus, sku =>
   {
       var cost  = _supplier.GetCostAsync(sku.Id).Result;   // ← blocking HTTP
       var price = _model.Price(sku, cost);                 //   CPU
       _db.SaveChanges(price);                              // ← blocking DB
   });
   ```

   Three defects in five lines. The body is `Action<T>`, so blocking is the only option available. `MaxDegreeOfParallelism` was never set, so it defaults to `-1` — documented as *no limit* — and the loop keeps requesting capacity it immediately parks. And there is one thread pool per process, so the API's request threads and the batch's blocked threads are drawn from the same well.

5. **Why staging looked fine.** Staging runs the batch against 200 SKUs with no concurrent API traffic. Starvation is a *contention* failure; a test with no contention cannot reproduce it.

**Root cause.** An I/O-bound workload expressed with a CPU-bound construct, in a process that shares its thread pool with a latency-sensitive API, with no concurrency cap.

**Fix.** Split by bottleneck; derive every cap from something real.

```csharp
// Stage 1 — I/O. Cap = the supplier's documented rate limit.
var costs = new ConcurrentDictionary<int, decimal>();
await Parallel.ForEachAsync(
    skus,
    new ParallelOptions { MaxDegreeOfParallelism = 20, CancellationToken = ct },
    async (sku, token) => costs[sku.Id] = await _supplier.GetCostAsync(sku.Id, token));

// Stage 2 — CPU. Cap = cores the container actually has.
var priced = new PricedSku[skus.Count];
Parallel.For(0, skus.Count,
    new ParallelOptions
    {
        MaxDegreeOfParallelism = Environment.ProcessorCount,
        CancellationToken = ct
    },
    i => priced[i] = _model.Price(skus[i], costs[skus[i].Id]));

// Stage 3 — I/O, batched, one DI scope per batch.
foreach (var batch in priced.Chunk(1_000))
{
    using var scope = _scopeFactory.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    db.AddRange(batch);
    await db.SaveChangesAsync(ct);
}
```

**What each change bought.**

| Change | Effect |
|---|---|
| `ForEachAsync` instead of `ForEach` | No pool thread held during the supplier call |
| Explicit cap on stage 1 | Protects the supplier and the connection pool; the loop stops asking for capacity it will park |
| `Environment.ProcessorCount` on stage 2 | Honours the container's CPU quota instead of the build agent's core count |
| Scope per batch in stage 3 | Change tracker and DB connection released between batches — see [`IServiceScopeFactory` in non-HTTP contexts](02-dependency-injection.md#iservicescopefactory-in-non-http-contexts) |
| Token threaded everywhere | The batch actually stops on shutdown instead of being SIGKILLed mid-write |

**Verification.** Thread-pool thread count stays **flat** during the window instead of climbing — that single metric is what proves the fix. CPU now rises during stage 2, which is correct: CPU-bound work *should* use CPU. API p99 stops correlating with the batch window.

**Post-mortem actions.** A load test that runs the batch *and* API traffic together, because the failure only exists under contention. An alert on thread-pool thread-count growth rather than on endpoint latency, so the cause fires before the symptom. And a review rule: **any `Parallel.ForEach` whose body contains `.Result`, `.Wait()`, or a synchronous I/O call is a defect, not a style preference.**

**What to say in an interview.** "The giveaway was high latency with low CPU — that combination means threads, not cores. `Parallel.ForEach` forces a synchronous body, so every iteration parked a pool thread in a network wait, and because `MaxDegreeOfParallelism` defaults to unlimited the loop kept asking for more. The fix wasn't a bigger pool; it was matching the construct to the workload and giving each stage a cap I could point at a reason for."

</details>

---

## Self-Test

<details>
<summary>1. Why does <code>Parallel.ForEach(urls, async url =&gt; await FetchAsync(url))</code> compile but do nothing useful?</summary>

The lambda binds to `Action<T>`, and an `async` lambda whose body returns no value is a legal `Action<T>` — so it becomes **`async void`**. `Parallel.ForEach` therefore considers each iteration complete the moment the state machine hits its first `await` and returns, which means the loop finishes with essentially all the work still in flight. Nothing holds a `Task`, so nothing can await completion or observe faults; with no `SynchronizationContext` installed the exception is raised on a pool thread, and an unhandled exception on a pool thread terminates the process.

The fix is `Parallel.ForEachAsync`, whose body parameter is `Func<TSource, CancellationToken, ValueTask>` — a shape that cannot silently degrade to `async void`, because the delegate must return something the loop awaits.
</details>

<details>
<summary>2. <code>ParallelOptions.MaxDegreeOfParallelism</code> is left at its default. How many operations run concurrently?</summary>

It depends on the method, which is the point of the question. The default is `-1`, and the docs say: "If it is -1, there is no limit on the number of concurrently running operations (**with the exception of the `ForEachAsync` method, where -1 means `ProcessorCount`**)."

So for `Parallel.For`/`Parallel.ForEach` the answer is "whatever the scheduler provides, unbounded" — the docs add that these methods "will utilize however many threads the underlying scheduler provides, so changing `MaxDegreeOfParallelism` from the default only limits how many concurrent tasks will be used." For `Parallel.ForEachAsync` the answer is `Environment.ProcessorCount`, stated on the overloads that take no `ParallelOptions`: "The operation will execute at most `ProcessorCount` operations in parallel."
</details>

<details>
<summary>3. Trade-off: <code>ConcurrentDictionary.GetOrAdd(key, factory)</code> vs <code>ConcurrentDictionary&lt;K, Lazy&lt;V&gt;&gt;</code>.</summary>

Bare `GetOrAdd` is simpler and allocates one object per entry. Its documented behaviour: the factory "is called outside the locks to avoid the problems that can arise from executing unknown code under a lock", so under concurrency on a cold key "`valueFactory` may be called multiple times, but only one key/value pair will be added to the dictionary." The dictionary stays consistent; the *extra objects your factory built* are silently discarded.

Harmless for a pure computation. A resource leak for anything that opens a socket, a file, a connection, or registers a callback — nothing disposes the losers, and nothing in your code even knows they existed.

`ConcurrentDictionary<K, Lazy<V>>` with `LazyThreadSafetyMode.ExecutionAndPublication` costs one extra allocation per entry and one indirection per read, and guarantees the expensive factory runs exactly once: the `Lazy` wrapper may be constructed several times, but only the one that wins the insert is ever returned, so only its factory is ever forced.

**Rule:** side-effect-free factory → bare `GetOrAdd`. Factory that acquires a resource → `Lazy<T>`. Async factory → `Lazy<Task<V>>`, with an eviction path on failure, because a faulted `Task` otherwise stays cached forever.
</details>

<details>
<summary>4. Analyse this double-checked lock. Correct on .NET? <code>if (_inst == null) { lock (_gate) { if (_inst == null) _inst = new Thing(); } } return _inst;</code></summary>

**Yes, on .NET, without `volatile`** — and the runtime's own memory-model spec publishes this exact pattern as a correct example, with inline comments noting that "taking a lock is an acquire" and "releasing a lock is a release".

Two guarantees from that spec carry it. **"Object assignment to a location potentially accessible by other threads is a release with respect to accesses to the instance's fields/elements and metadata"** — so the writes that initialise the object cannot become observable after the write of `_inst`. And **"data-dependent reads are ordered"** — so a thread that reads the reference cannot then read stale contents through it.

Note what does *not* save it: the same spec says "the .NET runtime does not specify any ordering effects to the instance constructors." The ordering comes from the **publication**, not the constructor. That distinction is the whole answer.

Two things worth adding unprompted. This is stronger than ECMA-335 requires and stronger than Java's pre-JSR-133 model, which is why "DCL is broken" lore imported from other ecosystems does not transfer. And it is still not what you should ship — `Lazy<T>` with `ExecutionAndPublication` is fewer lines, and Microsoft's own `Volatile` documentation points at it as the way to write lazy initialisation "without directly using double-checked locking".
</details>

<details>
<summary>5. Same pattern, but guarded by a separate <code>bool _initialized</code> instead of the reference. Still correct?</summary>

**No.** Swap the guard from the reference to a separate flag and both saving guarantees disappear, because there is no longer a data dependency for the model to hang ordering on.

```csharp
if (!_initialized)                 // ordinary read #1 — no lock ⇒ no acquire fence
{
    lock (_gate)
    {
        if (!_initialized)
        {
            _config = Load();      // ordinary write A
            _initialized = true;   // ordinary write B
        }
    }
}
return _config!;                   // ordinary read #2 — can observe null
```

The fast path takes no lock, so it gets no acquire. It performs two ordinary reads of two unrelated locations, and ordinary accesses "can be reordered as long as that preserves single-thread consistency" — which reordering these does, since single-threaded nothing could tell the difference. A reader can therefore see `_initialized == true` and `_config == null`.

The fix is a release/acquire pair on the flag: `Volatile.Write(ref _initialized, true)` after the `_config` write (release — write A cannot become observable after it) and `Volatile.Read(ref _initialized)` on the fast path (acquire — read #2 cannot be hoisted above it). Marking the field `volatile` does the same for every access at slightly higher cost.

The production signature is diagnostic in itself: rare, load-dependent, machine-dependent, gone by the time anyone looks, and impossible to reproduce on the developer's laptop.
</details>

<details>
<summary>6. A lock-free per-shard counter array gets slower as you raise <code>MaxDegreeOfParallelism</code>. Name the cause, the confirmation, and two fixes.</summary>

**Cause: false sharing.** Cache coherence moves *cache lines*, not variables. Several `long` counters sit inside one line, so every increment by one core invalidates every other core's copy of that whole line, even though the cores touch different counters. The line ping-pongs across the interconnect on every write. The fingerprint is exactly as described — correct results, no locks, *negative* scaling — and lock-contention counters show nothing because there is no lock.

**Confirmation:** hardware counters (cache-line invalidations; `perf c2c` on Linux, VTune's memory-access analysis on Windows), plus the cheap experiment of spacing the counters further apart and watching the scaling invert.

**Fix 1 — stop sharing (preferred).** `Parallel.For`'s `localInit`/`localFinally`: each task accumulates privately and merges once at the end. Nothing is shared, so nothing can be falsely shared, and no padding is needed.

**Fix 2 — pad (when the counters must be live and individually addressable).** An explicit-layout struct one cache line wide, one per counter; `ref array[i].Value` still gives `Interlocked` a real interior reference. The BCL does exactly this — `ConcurrentQueueSegment<T>`'s `PaddedHeadAndTail`, commented "to avoid false sharing between producers and consumers" — and sizes it with a **named constant**, because the cache line size is platform-dependent. Don't quote a byte count.

Caveat worth volunteering: padding inflates the array, which is its own cache-footprint problem if anything scans it, and read-mostly data should **never** be padded — a shared line nobody writes stays valid in every core's cache, which is a benefit.
</details>

<details>
<summary>7. You need a producer/consumer queue between an HTTP endpoint and a background writer. Compare <code>ConcurrentQueue&lt;T&gt;</code>, <code>Channel&lt;T&gt;</code>, and TPL Dataflow, and pick one.</summary>

`ConcurrentQueue<T>` is a thread-safe FIFO and nothing more. **No awaiting read**, so the consumer must poll — a latency floor plus wasted wakeups, and tuning the delay only trades one for the other. **No backpressure**, so when the writer falls behind, memory grows until the process is OOM-killed. **No completion signal**, so graceful shutdown is hand-rolled.

`Channel<T>` fixes all three: `Reader.ReadAllAsync` for an awaiting read, `CreateBounded` with an explicit `FullMode` for backpressure, and `Writer.Complete()` so the consumer loop actually ends. It is in-box.

TPL Dataflow adds topology — per-block `MaxDegreeOfParallelism`, `BroadcastBlock` (every consumer gets every item, which a channel deliberately never does since an item goes to exactly one reader), `BatchBlock`, joins, and completion that propagates along links. It is **not** distributed with .NET; it is the `System.Threading.Tasks.Dataflow` NuGet package, and its `MaxDegreeOfParallelism` defaults to **1**.

**Pick `Channel<T>`**, bounded, with a `FullMode` chosen from the domain: `Wait` if losing an item is a business problem (the handler then surfaces pressure as `503 Retry-After`), `DropOldest` if it is diagnostic telemetry where the newest sample matters most. Escalate to Dataflow only when a second stage appears that needs its own degree of parallelism.
</details>

<details>
<summary>8. Someone adds <code>.AsParallel()</code> to a query over 50,000 rows and reports no change. Give the diagnostic order.</summary>

Four checks, in this order, because each is cheaper than the next.

1. **Did PLINQ parallelise at all?** It analyses query shape and falls back to sequential by default for documented patterns: indexed `Select`/`Where`/`SelectMany`/`ElementAt` after an operator that removed or rearranged indices; `Take`/`TakeWhile`/`Skip`/`SkipWhile` on reordered sources; `Zip`/`SequenceEquals`, `Concat`, and `Reverse` on non-indexable sources. "Nothing changed" is most often literally true — nothing changed.
2. **Is the delegate expensive enough to repay the overhead?** Partition + schedule + merge is a fixed cost, and the docs say "small source collections with trivial delegates are generally not good candidates for PLINQ."
3. **Is there shared state in a delegate?** A captured counter or list both serialises the query and is a data race.
4. **What does the terminal operator cost?** `ToList`/`ToArray` force a merge; `foreach` serialises results onto the enumerator thread; `ForAll` skips the merge entirely.

One shape check to add: if the source is an array or `IList<T>`, PLINQ uses **range partitioning without load balancing** by default, so an uneven per-element cost leaves one task grinding while the rest idle — `Partitioner.Create(source, loadBalance: true)` is the switch.
</details>

---

## Cross-References

- **[Async & Threading](03-async-and-threading.md)** — the other half of this topic: the async state machine, `ValueTask`, `ConfigureAwait`, `SynchronizationContext`, sync-over-async deadlocks, `CancellationToken`, `IAsyncEnumerable<T>`, thread-pool starvation and its counters, and the full synchronisation-primitive catalogue.
- **[.NET Fundamentals & Garbage Collection](01-net-fundamentals.md)** — object layout, allocation, and why per-iteration allocation inside a parallel loop shows up as GC pressure.
- **[Dependency Injection](02-dependency-injection.md)** — `IServiceScopeFactory` per unit of work, and why scoped services (notably `DbContext`) are not thread-safe across a parallel fan-out.
- **[Memory & Performance](../05-csharp-mastery/09-memory-and-performance.md)** — cache behaviour, struct layout, `Span<T>`, and BenchmarkDotNet, which is how every question on this page gets settled empirically.
- **[LINQ Deep Dive](../05-csharp-mastery/06-linq-language-deep-dive.md)** — deferred execution and the operator pipeline that PLINQ parallelises.
- **[Data Structures](../03-data-structures.md)** — the sequential collections the concurrent ones are built on.
- **[Background Services](../../05-microservices-and-messaging/02-background-services.md)** — `BackgroundService` lifecycle, graceful shutdown, and the `Channel<T>` + hosted-service pattern for production fire-and-forget.
- **[Caching](10-caching.md)** — cache stampede, `Lazy<T>` inside a `ConcurrentDictionary`, and `IMemoryCache`'s own concurrency behaviour.
- **[Data Access](05-data-access.md)** — why `DbContext` must never be shared across parallel tasks, and `DbContextFactory` for the cases where you need one per task.
- **[Exception Handling](13-exception-handling.md)** — `AggregateException`, `Flatten()`, and error handling across task boundaries.
- **[OpenTelemetry](../../06-distributed-and-observability/06-opentelemetry.md)** — the `dotnet.thread_pool.*` counters that turn "the app feels slow" into a diagnosis.
- **[Version History](18-version-history.md)** — when `Parallel.ForEachAsync` (.NET 6), `System.Threading.Lock` and `Channel.CreateUnboundedPrioritized` (.NET 9), and `Volatile.ReadBarrier`/`WriteBarrier` (.NET 10) landed.
- **[Interview Prep](16-interview-prep.md)** — rapid-fire concurrency questions.

---

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

**Primary sources used for the claims on this page**

- [.NET Memory Model specification — `dotnet/runtime/docs/design/specs/Memory-model.md`](https://github.com/dotnet/runtime/blob/main/docs/design/specs/Memory-model.md) — atomicity of aligned primitives and managed references; the ordinary / acquire / release / full-fence categories; lock acquisition and release as acquire and release; "Object assignment… is a release with respect to accesses to the instance's fields/elements and metadata"; "data-dependent reads are ordered"; "the .NET runtime does not specify any ordering effects to the instance constructors"; and the lock-based and `Interlocked.CompareExchange` singleton examples with their inline reasoning.
- [API: `System.Threading.Volatile`](https://learn.microsoft.com/dotnet/api/system.threading.volatile) — the `x`/`y` acquire-release worked example; "volatile reads and writes ensure that a value is read or written to memory and not cached (for example, in a processor register)"; the "may still see `y2 == 0`" caveat; 64-bit atomicity on 32-bit processors; the array-element and language limitations; and the pointer to `Lazy<T>` "without directly using double-checked locking".
- [API: `Volatile.ReadBarrier`](https://learn.microsoft.com/dotnet/api/system.threading.volatile.readbarrier) / [`Volatile.WriteBarrier`](https://learn.microsoft.com/dotnet/api/system.threading.volatile.writebarrier) — moniker range confirms **.NET 10+**.
- [API: `System.Threading.Interlocked`](https://learn.microsoft.com/dotnet/api/system.threading.interlocked) — "the members of this class do not throw exceptions"; the member list including `MemoryBarrier`, `MemoryBarrierProcessWide`, and `SpeculationBarrier`.
- [API: `ParallelOptions.MaxDegreeOfParallelism`](https://learn.microsoft.com/dotnet/api/system.threading.tasks.paralleloptions.maxdegreeofparallelism) — default `-1` means no limit, "with the exception of the `ForEachAsync` method, where -1 means `ProcessorCount`"; the ceiling-not-target wording; the documented reasons to set it.
- [API: `Parallel.ForEachAsync`](https://learn.microsoft.com/dotnet/api/system.threading.tasks.parallel.foreachasync) — all six overloads; "the operation will execute at most `ProcessorCount` operations in parallel"; `IAsyncEnumerable<T>` support.
- [API: `ParallelLoopState`](https://learn.microsoft.com/dotnet/api/system.threading.tasks.parallelloopstate) — `Break()` vs `Stop()`, "this does not affect iterations that have already begun execution", and the `ShouldExitCurrentIteration` / `LowestBreakIteration` cooperation pattern.
- [API: `Environment.ProcessorCount`](https://learn.microsoft.com/dotnet/api/system.environment.processorcount) — the minimum of logical processors, affinity, and "the CPU utilization limit rounded up to the next whole number"; "fixed at .NET runtime startup for the process lifetime".
- [API: `ParallelEnumerable.WithDegreeOfParallelism`](https://learn.microsoft.com/dotnet/api/system.linq.parallelenumerable.withdegreeofparallelism) — `ArgumentOutOfRangeException` when "less than 1 or greater than 512"; `InvalidOperationException` if used more than once per query.
- [Understanding Speedup in PLINQ](https://learn.microsoft.com/dotnet/standard/parallel-programming/understanding-speedup-in-plinq) — the definition of parallelisation overhead; "small source collections with trivial delegates are generally not good candidates for PLINQ"; the `AsOrdered` / `GroupBy` / `Join` cost note; merge cost on `ToArray`/`ToList`/`foreach`; and the complete list of query shapes PLINQ executes sequentially by default.
- [Custom Partitioners for PLINQ and TPL](https://learn.microsoft.com/dotnet/standard/parallel-programming/custom-partitioners-for-plinq-and-tpl) — range vs chunk partitioning; "if one thread finishes early, it cannot help the other threads finish their work"; "the amount of synchronization incurred in these cases is inversely proportional to the size of the chunks"; "By default when it is passed an IList or an array, PLINQ always uses range partitioning without load balancing"; the `Partitioner.Create` load-balancing table; the range-partitioner-plus-inner-`for` pattern with its delegate-cost rationale; and the custom-partitioner contract.
- [API: `ConcurrentDictionary<TKey,TValue>.GetOrAdd`](https://learn.microsoft.com/dotnet/api/system.collections.concurrent.concurrentdictionary-2.getoradd) — "uses fine-grained locking… (Read operations on the dictionary are performed in a lock-free manner)"; "the `valueFactory` delegate is called outside the locks"; "`valueFactory` may be called multiple times, but only one key/value pair will be added to the dictionary"; and the three-row return-value table.
- [API: `ConcurrentDictionary<TKey,TValue>.GetEnumerator`](https://learn.microsoft.com/dotnet/api/system.collections.concurrent.concurrentdictionary-2.getenumerator) — "safe to use concurrently with reads and writes… however it does not represent a moment-in-time snapshot".
- [API: `ExecutionDataflowBlockOptions`](https://learn.microsoft.com/dotnet/api/system.threading.tasks.dataflow.executiondataflowblockoptions) — the defaults table (`MaxDegreeOfParallelism` = 1, `BoundedCapacity` = −1, `MaxMessagesPerTask` = −1); "The TPL Dataflow Library… is not distributed with .NET"; options captured at block construction.
- [API: `Channel`](https://learn.microsoft.com/dotnet/api/system.threading.channels.channel) and [`Channel.CreateUnboundedPrioritized`](https://learn.microsoft.com/dotnet/api/system.threading.channels.channel.createunboundedprioritized) — the factory surface; moniker range confirms `CreateUnboundedPrioritized` is **.NET 9+**; "the next item read from the channel will be the element available in the channel with the lowest priority value".
- [API: `ReaderWriterLockSlim`](https://learn.microsoft.com/dotnet/api/system.threading.readerwriterlockslim) — `LockRecursionPolicy.NoRecursion` default; only one thread in upgradeable mode; "a thread that initially entered read mode is not allowed to upgrade… if two threads in read mode both try to enter write mode, they will deadlock"; "Blocking new readers when writers are queued is a lock fairness policy that favors writers"; managed thread affinity.
- [`ConcurrentQueueSegment.cs` — `PaddedHeadAndTail`](https://github.com/dotnet/runtime/blob/main/src/libraries/System.Private.CoreLib/src/System/Collections/Concurrent/ConcurrentQueueSegment.cs) — "Padded head and tail indices, to avoid false sharing between producers and consumers", declared `[StructLayout(LayoutKind.Explicit, Size = 3 * Internal.PaddingHelpers.CACHE_LINE_SIZE)]`.
- [C# reference — the `lock` statement](https://learn.microsoft.com/dotnet/csharp/language-reference/statements/lock) — "You can't use the `await` expression in the body of a `lock` statement"; the CS1996 restriction and its application to `System.Threading.Lock`.

**Further reading**

- [Parallel Programming in .NET](https://learn.microsoft.com/dotnet/standard/parallel-programming/) — the TPL and PLINQ conceptual documentation set.
- [Order Preservation in PLINQ](https://learn.microsoft.com/dotnet/standard/parallel-programming/order-preservation-in-plinq) and [Merge Options in PLINQ](https://learn.microsoft.com/dotnet/standard/parallel-programming/merge-options-in-plinq).
- [Thread-Safe Collections](https://learn.microsoft.com/dotnet/standard/collections/thread-safe/) — the `System.Collections.Concurrent` overview.
- [`System.Threading.Channels` source](https://github.com/dotnet/runtime/tree/main/src/libraries/System.Threading.Channels) · [`System.Threading.Tasks.Dataflow` source](https://github.com/dotnet/runtime/tree/main/src/libraries/System.Threading.Tasks.Dataflow).
- [BenchmarkDotNet](https://benchmarkdotnet.org/) — the only honest way to answer "is the parallel version faster?" for your workload.

---

</details>
<!-- nav-footer-start -->

---

[← Previous: Cryptography, Hashing & Encoding](19-cryptography-hashing-and-encoding.md) · [↑ Back to top](#concurrency-and-parallelism-in-net-10) · [Next: SOLID Principles →](../02-solid-principles.md)

<!-- nav-footer-end -->
