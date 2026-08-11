# C# Mastery — Basics to Advanced

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › C# Mastery

A focused sub-chapter on the C# language itself — separate from "how .NET hosts and runs your code." Nine files covering everything from `int x = 5;` through `Span<T>` allocation-free parsing, written for a backend engineer who already knows .NET but wants language fluency end-to-end.

## Why a separate sub-chapter

The deep-dive treats C# as the medium it writes everything in, but never sits down and *teaches* the language as its own subject. That gap matters: many senior interviews ask language-level questions (variance, closure capture rules, `ref struct` constraints, expression trees) that don't surface naturally when you're learning ASP.NET. This sub-chapter fills that gap with one clear path through the language.

It also stays sequenced. The .NET deep-dive is a 18-file reference — you jump to a topic when you need it. This sub-chapter is a *progression*: each file assumes the previous, so you can read it in order and never feel like you're missing prerequisites.

## Topics in this sub-chapter

| # | Topic | Level | Estimated read time |
|---|---|---|---|
| 1 | [Fundamentals](./01-fundamentals.md) | Basics | 15 min |
| 2 | [Type System Deep Dive](./02-type-system.md) | Basics–Intermediate | 25 min |
| 3 | [OOP & Polymorphism](./03-oop-and-polymorphism.md) | Intermediate | 25 min |
| 4 | [Generics & Variance](./04-generics-and-variance.md) | Intermediate–Advanced | 25 min |
| 5 | [Delegates, Events & Lambdas](./05-delegates-events-lambdas.md) | Intermediate–Advanced | 20 min |
| 6 | [LINQ — Language Deep Dive](./06-linq-language-deep-dive.md) | Intermediate–Advanced | 25 min |
| 7 | [Nullability & Pattern Matching](./07-nullability-and-pattern-matching.md) | Intermediate | 20 min |
| 8 | [Reflection, Attributes & Source Generators](./08-reflection-attributes-and-source-gen.md) | Advanced | 25 min |
| 9 | [Memory & Performance Idioms](./09-memory-and-performance.md) | Advanced | 30 min |

---

## Recommended reading order

**Path A — sequential (learning):** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.

**Path B — interview prep (high-yield):** 2 (type system) → 4 (generics & variance) → 5 (closures, expression trees) → 7 (NRT, patterns) → 9 (Span/ref struct gotchas).

**Path C — performance lens:** 2 (`ref struct`, `readonly struct`) → 9 (`Span<T>`, allocation-free) → 4 (generic specialization) → 8 (source generators replacing reflection).

## What's not in this sub-chapter (and where it lives)

- **Async/await internals, threading, synchronization primitives** → [.NET Core Deep Dive › Async & Threading](../01-net-core-deep-dive/03-async-and-threading.md). This sub-chapter touches `IAsyncEnumerable` inside the LINQ file but does not duplicate the state-machine deep dive.
- **Modern C# features as a single reference** (records, primary constructors, collection expressions in one place) → [.NET Core Deep Dive › Modern C# Features](../01-net-core-deep-dive/12-modern-csharp.md). This sub-chapter weaves modern features into the topical files (records under type system, primary ctors under OOP, etc.) rather than collecting them in one file.
- **Per-version language deltas** (what shipped in C# 11 vs 12 vs 13 vs 14) → [.NET Core Deep Dive › Version History](../01-net-core-deep-dive/18-version-history.md).
- **EF Core LINQ specifics** (translation rules, `IQueryable` provider behavior) → [.NET Core Deep Dive › Data Access](../01-net-core-deep-dive/05-data-access.md). This sub-chapter's LINQ file covers language LINQ; the EF angle is one cross-link.
- **Garbage collection mechanics** (generations, modes, LOH) → [.NET Core Deep Dive › GC](../01-net-core-deep-dive/01-net-fundamentals.md#3-garbage-collection-in-net-10). This sub-chapter's memory file talks about *what allocates and what doesn't*; the GC file talks about *what happens to allocations once made*.

## Cross-references within the broader guide

- **Sibling: [.NET Core Deep Dive](../01-net-core-deep-dive/README.md)** — runtime, ASP.NET Core, EF, DI, configuration, etc.
- **Sibling: [SOLID Principles](../02-solid-principles.md)** — design contracts; many examples in this sub-chapter implicitly demonstrate them.
- **[Result Pattern](../../04-architecture-and-patterns/03-result-pattern.md)** — pattern-matching application from `07-nullability-and-pattern-matching.md`.
- **[Data Structures](../03-data-structures.md)** — what each generic collection in `System.Collections.Generic` actually is.

## Sources (chapter-wide)

- *C# 12 in a Nutshell* (and the upcoming C# 13/14 editions) by Joseph Albahari (O'Reilly) — the canonical desk reference.
- *Pro C# 10 with .NET 6* by Andrew Troelsen / Phil Japikse (Apress) — comprehensive walkthrough.
- *CLR via C#* by Jeffrey Richter (Microsoft Press) — the deep mechanics of C# on the CLR.
- Microsoft Learn — [C# language documentation](https://learn.microsoft.com/en-us/dotnet/csharp/).
- Stephen Toub's per-release performance posts on [devblogs.microsoft.com/dotnet](https://devblogs.microsoft.com/dotnet/) — the most insightful write-ups on what `Span`, `ref struct`, and source generators *actually* buy you.
- Mads Torgersen's language-design blog posts — for the *why* behind C# evolution.

<!-- nav-footer-start -->

---

[← Previous: Searching Algorithms](../04-searching-algorithms.md) · [↑ Back to top](#c-mastery--basics-to-advanced) · [Next: C# Fundamentals →](01-fundamentals.md)

<!-- nav-footer-end -->
