# Data Structures & Algorithms (DSA)

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › DSA

A focused sub-chapter covering data structures and algorithms from a senior-.NET-engineer angle — `.NET` collection internals, complexity analysis, search/sort/graph/DP algorithms, and 30 worked interview problems with idiomatic C# solutions.

## Why a separate sub-chapter

Two prior placeholder files (`03-data-structures.md`, `04-searching-algorithms.md`) couldn't reasonably hold the breadth a senior interview prep needs. Sorting, graph algorithms, dynamic programming, and complexity analysis each deserve their own file. Promoting DSA to a sub-chapter mirrors what we did with SQL Mastery and C# Mastery: a focused, sequenced reading path with depth comparable to the rest of the guide.

The orientation is **pragmatic** — every algorithm is shown with the .NET BCL primitive that already implements it (when one exists), Big-O comes with .NET-specific cost notes (boxing, GC pressure, JIT warmup), and interview problems use idiomatic modern C# (records, `Span<T>`, `PriorityQueue<TElement,TPriority>`, etc.).

## Topics in this sub-chapter

| # | Topic | Level | Estimated read time |
|---|---|---|---|
| 1 | [Data Structures](./01-data-structures.md) | Basics–Intermediate | 30 min |
| 2 | [Complexity Analysis](./02-complexity-analysis.md) | Basics | 20 min |
| 3 | [Searching Algorithms](./03-searching-algorithms.md) | Intermediate | 25 min |
| 4 | [Sorting Algorithms](./04-sorting-algorithms.md) | Intermediate | 25 min |
| 5 | [Graph Algorithms](./05-graph-algorithms.md) | Intermediate–Advanced | 30 min |
| 6 | [Dynamic Programming](./06-dynamic-programming.md) | Advanced | 30 min |
| 7 | [Interview Problems](./07-interview-problems.md) | Mixed | 45 min (reference) |

---

## Recommended reading order

**Path A — sequential (best for thorough coverage):** 1 → 2 → 3 → 4 → 5 → 6 → 7.

**Path B — interview prep (high-yield, time-boxed):** 2 (complexity) → 7 (interview problems) → revisit 1/3/4/5/6 as patterns surface.

**Path C — .NET-collection-aware lookup:** 1 (data structures + .NET BCL mapping) → 2 (complexity) → 3-6 as algorithm types come up in real work.

## Cross-references within the broader guide

- **Foundation: [.NET Core Deep Dive › Hash-based lookup table](../01-net-core-deep-dive/08-patterns-and-best-practices.md#15-hash-based-lookup-table)** — `Dictionary<TKey,TValue>` internals.
- **Foundation: [C# Mastery › Generics & Variance](../05-csharp-mastery/04-generics-and-variance.md)** — generic specialization is why `List<int>` is so much faster than `ArrayList`.
- **Foundation: [C# Mastery › Memory & Performance](../05-csharp-mastery/09-memory-and-performance.md)** — `Span<T>`, `stackalloc`, `ArrayPool` come up in DSA hot paths.
- **Sibling: [Multithreading Practice](../../08-craft-and-interview-prep/01-multithreading-practice.md)** — concurrency-flavored DSA problems.
- **Sibling: [Coding Practice](../../08-craft-and-interview-prep/02-coding-practice.md)** — applied problem-solving lens.
- **Data: [SQL › Indexes](../../03-data-and-persistence/03-sql/06-indexes-and-query-optimization.md)** — B-trees in practice.

## Sources (sub-chapter wide)

- *Introduction to Algorithms* (CLRS) by Cormen, Leiserson, Rivest, Stein (MIT Press, 4th ed. 2022) — the canonical algorithms reference.
- *Algorithms* by Robert Sedgewick (Addison-Wesley, 4th ed. 2011) — practical, clean code.
- *The Algorithm Design Manual* by Steven Skiena (Springer, 3rd ed. 2020) — emphasizes when to use each algorithm.
- *Cracking the Coding Interview* by Gayle Laakmann McDowell (CareerCup, 6th ed. 2015) — interview-shaped problems.
- *Elements of Programming Interviews in C++/Java/Python* by Aziz, Lee, Prakash — concise problem sets; concepts transfer to C#.
- Stephen Toub — *"Performance Improvements in .NET"* annual posts on devblogs — many DSA-relevant `Array.Sort` / hash table / SIMD insights.
- Microsoft Learn — [Collections (C#)](https://learn.microsoft.com/en-us/dotnet/csharp/programming-guide/concepts/collections) and [.NET Generic Collections](https://learn.microsoft.com/en-us/dotnet/standard/generics/).
- LeetCode, NeetCode, HackerRank — interview problem sets by category.
- Visualgo — [visualgo.net](https://visualgo.net/) — interactive algorithm visualizations.

<!-- nav-footer-start -->

---

[← Previous: Memory & Performance Idioms](../05-csharp-mastery/09-memory-and-performance.md) · [↑ Back to top](#data-structures--algorithms-dsa) · [Next: Data Structures →](01-data-structures.md)

<!-- nav-footer-end -->
