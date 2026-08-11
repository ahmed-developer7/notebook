# Data Structures

> [Mastery Guide](../README.md) › [Foundations](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Complete | Medium | Phase 11 — Craft & Interview Prep | 2026-08-10 |

> **Executive summary page.** This is a one-screen overview of the data structures every senior .NET engineer is expected to recognize. The full deep dive — mechanics, allocation profiles, complexity tables, and 15 cross-question drills — lives in **[DSA › Data Structures](./06-dsa/01-data-structures.md)**. The 30 worked interview problems are a separate file: **[DSA › Interview Problems](./06-dsa/07-interview-problems.md)**.

## Why it matters

Picking the right data structure is the highest-leverage performance decision in most code. `List<T>` where you needed `HashSet<T>` is O(n) lookup pretending to be O(1). `Dictionary<,>` where you needed `SortedDictionary<,>` makes ordered iteration impossible. `ConcurrentDictionary<,>` where a plain `lock` would suffice pays for per-operation synchronization you don't need — and still won't give you atomicity across a multi-step read-compute-write. Senior interviews probe this judgment relentlessly.

## Quick reference table

| Structure | .NET type | Lookup | Insert | Remove | Ordered? | Notes |
|---|---|:---:|:---:|:---:|:---:|---|
| Dynamic array | `List<T>` | O(n) scan, O(1) index | O(1) amortized end | O(n) middle | Insertion order | Default for sequential data |
| Linked list | `LinkedList<T>` | O(n) | O(1) at known node | O(1) at known node | Insertion order | Rare; cache-unfriendly |
| Hash map | `Dictionary<TKey,TValue>` | O(1) avg, O(n) worst | O(1) avg | O(1) avg | No | Workhorse for keyed lookup; worst case = bad `GetHashCode` |
| Hash set | `HashSet<T>` | O(1) avg, O(n) worst | O(1) avg | O(1) avg | No | Deduplication, membership |
| Sorted map | `SortedDictionary<TKey,TValue>` | O(log n) | O(log n) | O(log n) | Yes (key order) | Red-black tree; worst case *is* O(log n) |
| Sorted array map | `SortedList<TKey,TValue>` | O(log n) binary search | O(n) shift | O(n) shift | Yes (key order) | Less memory, faster iteration than the tree; build-once |
| Sorted set | `SortedSet<T>` | O(log n) | O(log n) | O(log n) | Yes | Range queries via `GetViewBetween` |
| Stack | `Stack<T>` | — | O(1) amortized push | O(1) pop | LIFO | DFS, undo, parsing |
| Queue | `Queue<T>` | — | O(1) amortized enqueue | O(1) dequeue | FIFO | BFS, producer-consumer |
| Priority queue | `PriorityQueue<TElem,TPri>` | — | O(log n) | O(log n) min | Min-heap | Dijkstra, top-K; `Remove` by element is O(n), .NET 9+ |
| Frozen map/set | `FrozenDictionary<,>`, `FrozenSet<T>` | O(1) avg (faster reads) | — (immutable) | — | No | Build once, query many |
| Concurrent map | `ConcurrentDictionary<,>` | O(1) avg, O(n) worst | O(1) avg | O(1) avg | No | Lock-free reads, fine-grained write locks |
| Immutable list | `ImmutableList<T>` | O(log n) | O(log n) | O(log n) | Yes | Structural sharing |
| Trie | (hand-rolled) | O(L) | O(L) | O(L) | Prefix order | Autocomplete, IP routing |
| Graph | (hand-rolled) | depends | — | — | — | Adjacency list / matrix / edge list |

L = key/word length.

## When to use what

```
Need keyed lookup, no order needed?           → Dictionary<,>     (HashSet<T> if no value)
Need keyed lookup AND sorted iteration?       → SortedDictionary<,>  (SortedList<,> if built once)
Need fastest possible read-only lookup?       → FrozenDictionary<,>  (.NET 8+, build once)
Need thread-safe map with many writers?       → ConcurrentDictionary<,>
Need LIFO (DFS, undo, expression eval)?       → Stack<T>
Need FIFO (BFS, producer-consumer)?           → Queue<T>  (or Channel<T> for async)
Need ordered min/max access (Dijkstra/topK)?  → PriorityQueue<TElem,TPri>
Need immutable snapshot semantics?            → Immutable* collections
Need autocomplete / prefix search?            → Trie (hand-roll; no BCL type)
Need O(1) splice with held node references?   → LinkedList<T>  (otherwise List<T>)
```

## Common .NET implementations

```csharp
// Dictionary lookup (workhorse)
var users = new Dictionary<string, User>();
if (users.TryGetValue("alice", out var u)) { /* ... */ }

// Set deduplication
var seen = new HashSet<int>(input);

// Stack for DFS / undo
var stack = new Stack<Node>();
stack.Push(root);

// Queue for BFS / level-order
var queue = new Queue<Node>();
queue.Enqueue(root);

// Min-heap priority queue (.NET 6+)
var pq = new PriorityQueue<string, int>();
pq.Enqueue("urgent", 1);
pq.Enqueue("normal", 5);

// Frozen for read-only hot lookup (.NET 8+)
var frozen = users.ToFrozenDictionary();

// Sorted dictionary for ordered iteration
var sorted = new SortedDictionary<int, string>();
foreach (var kvp in sorted) { /* in key order */ }

// Concurrent dictionary for multi-writer
var cd = new ConcurrentDictionary<string, int>();
cd.AddOrUpdate("k", 1, (_, old) => old + 1);
```

## ASCII at a glance

```
┌──────────────┐   keyed?   ┌──────────────────┐   sorted?  ┌────────────────────────┐
│  Need fast   │ ─── Yes ─→ │  Dictionary<,>?  │ ── Yes ──→ │ SortedDictionary<,>    │
│   access?    │            │                  │ ── No ───→ │ Dictionary<,>          │
└──────┬───────┘            └──────────────────┘            └────────────────────────┘
       │ No (sequential)
       ↓
┌──────────────┐   ends?    ┌──────────────────┐
│ Need order?  │ ── LIFO ─→ │   Stack<T>       │
│              │ ── FIFO ─→ │   Queue<T>       │
│              │ ── Pri  ─→ │ PriorityQueue<,> │
│              │ ── Index→  │   List<T>        │
└──────────────┘            └──────────────────┘
```

## Read the full deep dive

This page is a quick reference. For the full treatment — internal mechanics of `Dictionary<,>` collisions, when `LinkedList<T>` actually wins, frozen-collection trade-offs, B-trees, tries, graph representations, concurrent collections, and 15 cross-question drills — go to:

> **[DSA › Data Structures (full deep dive)](./06-dsa/01-data-structures.md)**

For the full DSA sub-chapter index covering complexity analysis, searching, sorting, graphs, dynamic programming, and interview problems, see **[DSA README](./06-dsa/README.md)**.

## Cross-references

- **[DSA › Data Structures](./06-dsa/01-data-structures.md)** — full deep dive (mechanics, complexity, 15 cross-question drills, 5 self-test questions).
- **[DSA › Interview Problems](./06-dsa/07-interview-problems.md)** — the 30 worked problems (arrays, linked lists, trees, graphs, DP, backtracking, concurrency).
- **[DSA › Searching Algorithms](./06-dsa/03-searching-algorithms.md)** — algorithms that operate on these structures.
- **[Generics and Variance](./05-csharp-mastery/04-generics-and-variance.md)** — how `List<T>`, `Dictionary<,>` etc. are typed.
- **[Hash-based lookup](./01-net-core-deep-dive/08-patterns-and-best-practices.md)** — `Dictionary<,>` internals (hashing, collisions, load factor).
- **[SQL Indexes and Query Optimization](../03-data-and-persistence/03-sql/06-indexes-and-query-optimization.md)** — B-trees and hash indexes in databases.
- **[LINQ](../03-data-and-persistence/02-linq.md)** — operators that traverse and project these structures.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *Introduction to Algorithms* (CLRS) — Chapters 10–14, 22.
- Microsoft Docs — [`System.Collections.Generic`](https://learn.microsoft.com/dotnet/api/system.collections.generic).
- Microsoft Docs — [`SortedList<TKey,TValue>`](https://learn.microsoft.com/dotnet/api/system.collections.generic.sortedlist-2) — O(log n) retrieval, O(n) insert/remove **for unsorted data**, lower memory than `SortedDictionary<,>`.
- Microsoft Docs — [`PriorityQueue<TElement,TPriority>`](https://learn.microsoft.com/dotnet/api/system.collections.generic.priorityqueue-2) — array-backed quaternary min-heap; `Remove` is a linear scan (.NET 9+).
- Microsoft Docs — [`ConcurrentDictionary<TKey,TValue>`](https://learn.microsoft.com/dotnet/api/system.collections.concurrent.concurrentdictionary-2) — fine-grained write locking, lock-free reads.
- Microsoft Docs — [Frozen collections](https://learn.microsoft.com/dotnet/api/system.collections.frozen) — "relatively high cost to create but provides excellent lookup performance."
- Stephen Toub — *Performance Improvements in .NET 8/9/10* posts (collection internals).

</details>
<!-- nav-footer-start -->

---

[← Previous: SOLID Principles](02-solid-principles.md) · [↑ Back to top](#data-structures) · [Next: Searching Algorithms →](04-searching-algorithms.md)

<!-- nav-footer-end -->
