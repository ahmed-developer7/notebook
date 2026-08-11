# Searching Algorithms

> [Mastery Guide](../README.md) › [Foundations](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Complete | Medium | Phase 11 — Craft & Interview Prep | 2026-08-10 |

> **Executive summary page.** This is a one-screen overview of the search algorithms every senior .NET engineer is expected to recognize. The full deep dive — mechanics, off-by-one walkthroughs, BCL vectorization notes, string-search algorithms, and 15 cross-questioning drills plus a 5-question self-test — lives in **[DSA › Searching Algorithms](./06-dsa/03-searching-algorithms.md)**.

## Why it matters

Search is the most-asked algorithm category in interviews — *Two Sum*, *Find First/Last Position*, *Search in Rotated Array* are staples. Production code is full of search even when you don't call it that: `Dictionary` lookup is search; `IndexOf` is search; database index probes are search; pattern matching is search. Knowing which algorithm is behind which BCL primitive lets you pick the right primitive — and lets you write the algorithm yourself when an interviewer asks.

## Quick reference table

| Algorithm | Time | Space | Input requirement | Typical use |
|---|:---:|:---:|---|---|
| Linear search | O(n) | O(1) | Any | Small N, unsorted, or short-circuit (`Any`/`First`) |
| Binary search | O(log n) | O(1) iter / O(log n) rec | **Sorted** | The default for sorted random-access data |
| Lower / upper bound | O(log n) | O(1) | Sorted | Find boundaries / insertion points |
| Exponential search | O(log i) | O(1) | Sorted, unbounded | Target near start of huge stream |
| Interpolation search | O(log log n) avg / O(n) worst | O(1) | Sorted, **uniform** distribution | Rare; numeric data |
| Hash lookup | O(1) avg / O(n) worst | O(n) extra | Hashable keys | Default for point lookups |
| Bloom filter | O(k) | O(bits), keys not stored | Hashable keys | Probabilistic membership; false positives only |
| Tree search (BST) | O(log n) balanced / O(n) degenerate | O(n) tree | `IComparable` keys | Ordered iteration + lookup |
| Trie | O(L) | O(total chars) | String keys | Prefix queries, autocomplete |
| BFS (graph) | O(V + E) | O(V) | Graph | Shortest path on unweighted graphs |
| DFS (graph) | O(V + E) | O(V) | Graph | Connectivity, cycle detection, topo sort |
| Dijkstra | O((V+E) log V) binary heap | O(V) | Weighted, non-negative | Shortest path on weighted graphs |
| Naive substring | O(n × m) worst | O(1) | Strings | What the BCL vectorizes |
| KMP | O(n + m) | O(m) | Strings | Guaranteed-linear; streamable |
| Boyer-Moore | O(n/m) avg / O(n × m) worst | O(m + Σ) | Strings | Skip-scanning long patterns (`grep`) |
| Rabin-Karp | O(n + m) avg / O(n × m) worst | O(1) | Strings | Rolling hash; multi-pattern |
| Aho-Corasick | O(n + m + z) | O(m) | Strings, multi-pattern | Many needles in one pass |
| Regex | varies — backtracking can blow up | varies | Patterns | Structured matching, not substring search |

n = size, m = pattern length (total, multi-pattern), L = prefix length, k = hash functions, z = matches, Σ = alphabet, V = vertices, E = edges, i = target's index.

## When to use what

```
Data unsorted, small N, single search?            → Linear search (or List<T>.IndexOf)
Data unsorted, many searches?                     → Build Dictionary<,> / HashSet<T> once → O(1)
Membership only, huge set, memory-bound?          → Bloom filter (accept false positives)
Data sorted, point lookup?                        → Binary search (Array.BinarySearch)
Data sorted, find first match / boundary?         → Lower bound / upper bound
Data sorted, target probably near start?          → Exponential search
Need shortest path, unweighted graph?             → BFS
Need connectivity / cycle detection?              → DFS
Need shortest path, weighted (non-negative)?      → Dijkstra
Need shortest path, possibly negative weights?    → Bellman-Ford
Need substring location in long text?             → IndexOf (ordinal) — KMP only if you must stream
Need multi-pattern scan (multiple needles)?       → SearchValues<string> (.NET 9+) / Aho-Corasick
Need prefix / autocomplete lookups?               → Trie (no BCL type — hand-roll or library)
```

## ASCII at a glance — binary search

```
sorted: [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
target: 13

Step 1:  low=0, high=9, mid=4 → arr[4]=9   < 13 → low=5
Step 2:  low=5, high=9, mid=7 → arr[7]=15  > 13 → high=6
Step 3:  low=5, high=6, mid=5 → arr[5]=11  < 13 → low=6
Step 4:  low=6, high=6, mid=6 → arr[6]=13  ✓ FOUND at index 6

Steps: ⌈log₂(10)⌉ = 4 (vs 7 for linear)
```

## Common .NET implementations

```csharp
// Linear search — SIMD-vectorized for bitwise-equatable primitives.
// Not a .NET 8 feature: string.IndexOf since .NET Core 2.1,
// Array.IndexOf (byte/char) since .NET Core 3.0.
int idx = Array.IndexOf(arr, target);
int idx2 = list.IndexOf(target);            // delegates to Array.IndexOf
int idx3 = span.IndexOf(target);

// Multi-target scan — hoist the needle set (chars .NET 8+, strings .NET 9+)
private static readonly SearchValues<char> Delims = SearchValues.Create(",;|");
int idx4 = span.IndexOfAny(Delims);

// Binary search — on sorted array
int hit = Array.BinarySearch(sorted, target);
// returns ~insertionPoint if not found:
if (hit < 0) {
    int insertAt = ~hit;                    // bitwise complement trick
}

// Hash lookup — O(1) average
var dict = new Dictionary<string, User>();
if (dict.TryGetValue("alice", out var u)) { /* ... */ }

// Build once, query many — costly build, fast reads (.NET 8+)
var frozen = users.ToFrozenDictionary(x => x.Name);

// Substring search — always pass StringComparison;
// the bare IndexOf(string) overload is culture-sensitive, not ordinal.
int pos = text.IndexOf("needle", StringComparison.Ordinal);

// Regex — prefer the source generator to RegexOptions.Compiled (.NET 7+)
[GeneratedRegex(@"\d{3}-\d{4}")]
private static partial Regex Phone();
// Compiled is for runtime-built patterns you run many times, never one-shots.

// Sorted-set range query (red-black tree; SortedDictionary<,> has no such method)
var sorted = new SortedSet<int> { 1, 3, 5, 7, 9 };
var range = sorted.GetViewBetween(3, 7);    // 3, 5, 7
```

## Hand-rolled binary search (the interview classic)

```csharp
public static int BinarySearch<T>(IList<T> sorted, T target) where T : IComparable<T>
{
    int low = 0, high = sorted.Count - 1;
    while (low <= high)
    {
        int mid = low + (high - low) / 2;     // ← avoids overflow on huge arrays
        int cmp = sorted[mid].CompareTo(target);
        if (cmp == 0) return mid;
        if (cmp < 0) low = mid + 1;
        else         high = mid - 1;
    }
    return -1;                                // or ~low for "where it would go"
}
```

> **The classic bug:** `int mid = (low + high) / 2;` overflows when `low + high > int.MaxValue`. Use `low + (high - low) / 2`. (Joshua Bloch's famous Java fix in 2006.)

## Read the full deep dive

This page is a quick reference. For the full treatment — variant binary searches, off-by-one walkthroughs, exponential and interpolation search, BCL `IndexOf` vectorization, KMP / Boyer-Moore mechanics, BFS / DFS reference implementations, and 15 cross-questioning drills plus a 5-question self-test — go to:

> **[DSA › Searching Algorithms (full deep dive)](./06-dsa/03-searching-algorithms.md)**

For the full DSA sub-chapter index covering data structures, complexity analysis, sorting, graph algorithms, and dynamic programming, see **[DSA README](./06-dsa/README.md)**.

## Cross-references

- **[DSA › Searching Algorithms](./06-dsa/03-searching-algorithms.md)** — full deep dive (variants, BCL mappings, 15 drills + self-test).
- **[DSA › Data Structures](./06-dsa/01-data-structures.md)** — the structures these algorithms operate on.
- **[DSA › Graph Algorithms](./06-dsa/05-graph-algorithms.md)** — where Dijkstra and Bellman-Ford are actually worked through.
- **[Data Structures (summary)](./03-data-structures.md)** — sibling executive summary.
- **[LINQ](../03-data-and-persistence/02-linq.md)** — `Where`, `First`, `Any` are linear searches.
- **[SQL Indexes and Query Optimization](../03-data-and-persistence/03-sql/06-indexes-and-query-optimization.md)** — B-tree index lookup is a binary search at heart.
- **[Elasticsearch and Kibana](../06-distributed-and-observability/03-elasticsearch-and-kibana.md)** — inverted indexes are a different search structure.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *Introduction to Algorithms* (CLRS, 4th ed. 2022) — Ch. 2, 11, 12, 20, 22, 32. (3rd-edition numbering differs.)
- Microsoft Learn — [`Array.BinarySearch`](https://learn.microsoft.com/dotnet/api/system.array.binarysearch) (`~insertionPoint`; on duplicates returns "not necessarily the first"), [`MemoryExtensions.IndexOf`](https://learn.microsoft.com/dotnet/api/system.memoryextensions.indexof), [`SearchValues<T>`](https://learn.microsoft.com/dotnet/api/system.buffers.searchvalues-1) (.NET 8+), [`String.IndexOf`](https://learn.microsoft.com/dotnet/api/system.string.indexof) (bare overload is culture-sensitive), [source generators](https://learn.microsoft.com/dotnet/standard/base-types/regular-expression-source-generators) (".NET 7 introduced a new `RegexGenerator` source generator"; prefer it to `RegexOptions.Compiled`).
- Joshua Bloch — *Extra, Extra — Read All About It: Nearly All Binary Searches and Mergesorts are Broken* (2006).
- Stephen Toub — [*Performance Improvements in .NET Core 2.1*](https://devblogs.microsoft.com/dotnet/performance-improvements-in-net-core-2-1/) (`String.IndexOf` vectorized) and [*Regular Expression Improvements in .NET 7*](https://devblogs.microsoft.com/dotnet/regular-expression-improvements-in-dotnet-7/) (Boyer-Moore deleted from `Regex`).

</details>
<!-- nav-footer-start -->

---

[← Previous: Data Structures](03-data-structures.md) · [↑ Back to top](#searching-algorithms) · [Next: C# Mastery — Basics to Advanced →](05-csharp-mastery/README.md)

<!-- nav-footer-end -->
