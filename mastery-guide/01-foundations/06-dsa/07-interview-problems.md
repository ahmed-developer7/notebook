# Interview Problems

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › [DSA](./README.md) › Interview Problems

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 11 — Craft & Interview Prep | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [How to use this file](#how-to-use-this-file)
  - [Pattern recognition cheat sheet](#pattern-recognition-cheat-sheet)
- [Arrays & strings](#arrays--strings)
- [Linked lists](#linked-lists)
- [Trees](#trees)
- [Graphs](#graphs)
- [Dynamic programming](#dynamic-programming)
- [Backtracking](#backtracking)
- [Concurrency](#concurrency)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--mock-interview-detect-cycle-in-linked-list)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Knowing complexity theory and individual algorithms is necessary but not sufficient. The interview test is **applying** them under time pressure, recognizing the pattern, writing the C# code, and discussing trade-offs. This file is 30 high-value problems in the categories interviewers actually use, with idiomatic .NET solutions.

The selection skews to **patterns that recur** — sliding window, two pointers, fast/slow pointers, BFS/DFS templates, DP over indices, backtracking. Mastering ~30 representative problems gives broad coverage of what you'll encounter.

For each problem: statement → brute force → optimal → key insight → variants. Read in any order; cross-reference the underlying technique to its file in this sub-chapter.

**Read every problem twice.** The first pass is the algorithm — the pattern, the invariant, the complexity. The second pass is the .NET annotation under it: what allocates, which BCL guarantee the code is leaning on, and which C# semantic would silently change the answer if the types changed. At ten years' experience the algorithm half is the half you already have; the annotation half is where a senior interview actually goes, and it is the half nobody practises because LeetCode never asks for it.

> 🌍 **In the real world**: a ten-year .NET engineer walked a panel through an optimal sliding-window solution in eight minutes — restated the problem, worked an example, gave brute force, gave optimal, stated time and space, listed edge cases. The debrief said "solid on algorithms, thin on the platform," and the offer went elsewhere. What had happened is that the follow-up — "your window state is a `Dictionary<char,int>`; what does that allocate, and what happens when a caller hands you a two-million-character request body?" — got a shrug and a guess. The algorithm is the ticket to the second question. The second question is the interview.



## Core concepts

### How to use this file

**Phase 1 (week 1)**: read every problem and its key insight. Don't try to solve cold.

**Phase 2 (week 2)**: pick 5 problems per session; solve fresh (don't peek). Compare to the solutions here. The gap between your solution and this one is the learning.

**Phase 3 (final prep)**: from the problem statement alone, **explain** the optimal solution in <2 minutes. If you can teach it, you've got it.

### Pattern recognition cheat sheet

Recognizing the pattern in the first 30 seconds is more than half the interview battle:

| Signal | Likely pattern |
|---|---|
| "Find pair / triplet that sums to X" | Two pointers (sorted) or hash set |
| "Longest / shortest substring with property" | Sliding window |
| "Find duplicate / cycle in array or list" | Floyd's tortoise & hare |
| "Find Kth element" | Heap (priority queue) or quickselect |
| "Sorted matrix / sorted rotated array" | Modified binary search |
| "Tree traversal" | DFS (pre/in/post) or BFS (level-order) |
| "Shortest path unweighted" | BFS |
| "Shortest path weighted" | Dijkstra |
| "Topological order / course schedule" | Topological sort (Kahn's or DFS) |
| "Path counts / step counts" | DP over indices |
| "Subsequence / substring optimization" | DP 2D |
| "Subset / combination / permutation" | Backtracking |
| "Decision under capacity / weight constraint" | Knapsack DP |
| "Merge intervals / scheduling" | Sort + sweep |

Recognising the pattern gets you a correct solution. What separates a senior loop from a mid-level one is the *second* question, and the second questions are as predictable as the patterns:

| Their follow-up | What is actually being tested |
|---|---|
| "What does that allocate, per call?" | Whether you have ever opened an allocation profile |
| "What if the tree is a million deep?" | Whether you know a stack overflow kills the process, not the request |
| "What if the node type were a `record`?" | Whether you know which equality your collection is using |
| "What if the input is user-supplied?" | Hash flooding — and whether .NET's mitigation covers your key type |
| "Now ship it. What breaks at 3am?" | Cancellation, backpressure, fault propagation |
| "Prove it's faster." | Whether you reach for a number or for a benchmark |

None of these have LeetCode answers. All of them have .NET answers, and the annotations under each problem below are those answers.

---

## Arrays & strings

### 1. Two Sum

**Problem**: Given `int[] nums` and `int target`, return indices of two numbers summing to target.

**Brute force**: nested loops, O(n²).

**Optimal**: hash map of value → index. For each `x`, check if `target - x` is in the map.

```csharp
public int[] TwoSum(int[] nums, int target)
{
    var seen = new Dictionary<int, int>();
    for (int i = 0; i < nums.Length; i++)
    {
        int complement = target - nums[i];
        if (seen.TryGetValue(complement, out var j)) return [j, i];
        seen[nums[i]] = i;
    }
    return [];
}
```

**Complexity**: O(n) time, O(n) space.

**Insight**: hash-set lookup turns "find pair" from O(n²) to O(n).

**Variants**: 3Sum (sort + two pointers), 4Sum (sort + nested two pointers).

**What the interviewer asks next.** This is the most-asked problem in the industry, so nobody gets credit for the hash map. Everything below is about the `Dictionary<int, int>`, and any one of the three is a five-minute conversation.

*It resizes, and you can stop it.* `Dictionary<,>` keeps a bucket array sized to a prime. When it fills, `Resize` allocates a larger entries array **and a larger bucket array**, copies, and re-buckets every live entry. Growing to n means a geometric series of allocations, each one larger than the last, and each one leaving the previous pair to the GC. `new Dictionary<int, int>(nums.Length)` pays for one of each. One word of code, and it is the difference between "I've used a dictionary" and "I know what one does."

*It chains — it does not probe.* There are two arrays, not one. `private int[]? _buckets` and `private Entry[]? _entries`, where an entry is `{ uint hashCode; int next; TKey key; TValue value; }` and `next` is documented in the source as the "0-based index of next entry in chain: -1 means end of chain" (dotnet/runtime, `Dictionary.cs`). A bucket does not hold a key — it holds an index into `_entries`, and each entry points at the next entry in its chain. The chain is a linked list threaded through one flat array:

```
Dictionary<int,int>, 3 buckets. Int32.GetHashCode() returns the value itself,
so 7, 10 and 13 are all ≡ 1 (mod 3): one bucket, one chain, three entries.

  _buckets (int[])            _entries (Entry[])  — inserted 7, then 10, then 13
  ┌───────┬───────┐           ┌───────┬──────────┬──────┬─────┐
  │ index │ value │           │ index │ hashCode │ next │ key │
  ├───────┼───────┤           ├───────┼──────────┼──────┼─────┤
  │   0   │   0   │ empty     │   0   │     7    │  -1  │  7  │ ← end of chain
  │   1   │   3   │ → idx 2   │   1   │    10    │   0  │ 10  │
  │   2   │   0   │ empty     │   2   │    13    │   1  │ 13  │ ← head of chain
  └───────┴───────┘           └───────┴──────────┴──────┴─────┘
    a bucket stores index + 1, so the value 3 means _entries[2]; 0 means empty

  lookup(7)  →  bucket[1] = 3  →  _entries[2]: key 13, miss, next = 1
                               →  _entries[1]: key 10, miss, next = 0
                               →  _entries[0]: key  7, HIT
```

That is not open addressing, and the distinction earns its keep on the next point: a bad hash does not degrade your neighbours' lookups by clustering into their slots, it lengthens exactly one chain — which is why the pathological case is invisible in an average-latency chart and obvious in a p99.

*Its collision defence does not cover `int` keys.* .NET has a hash-flooding mitigation, and it is narrower than most people assume. On insert, `Dictionary<,>` counts how far it walked the chain, and if that exceeds a threshold it rebuilds with a randomized hash — but only under this guard:

```csharp
// dotnet/runtime, Dictionary.cs, TryInsert
if (!typeof(TKey).IsValueType && collisionCount > HashHelpers.HashCollisionThreshold &&
    comparer is NonRandomizedStringEqualityComparer)
{
    Resize(entries.Length, forceNewHashCodes: true);
}
```

Both halves exclude `int`. It is a value type, and its comparer is not the string comparer. And `Int32.GetHashCode()` returns the value itself (`return m_value;` — dotnet/runtime, `Int32.cs`), with the bucket chosen by that value modulo the prime. So a caller who chooses the numbers can choose multiples of that prime, land every key in one chain, and turn your O(n) endpoint into O(n²) inside a single request — no exception, no error log, just a request that takes minutes. The mitigation is real; it is for `string` keys and only for `string` keys.

*It hashes twice when you only meant once.* Two Sum genuinely needs both lookups (they are different keys). Frequency counting does not: `counts[c] = counts.TryGetValue(c, out var n) ? n + 1 : 1` hashes `c`, walks the chain, then hashes `c` and walks the chain again for one logical increment. `CollectionsMarshal.GetValueRefOrAddDefault` (.NET 6+) returns a `ref` into the entry and does it once:

```csharp
using System.Runtime.InteropServices;

// two lookups per character
counts[c] = counts.TryGetValue(c, out var n) ? n + 1 : 1;

// one lookup per character; `exists` tells you whether it was just added
ref int slot = ref CollectionsMarshal.GetValueRefOrAddDefault(counts, c, out _);
slot++;
```

Know the caveat before you offer it: "Items should not be added to or removed from the `Dictionary<TKey,TValue>` while the `ref TValue` is in use" (Microsoft Learn, *CollectionsMarshal.GetValueRefOrAddDefault*). Add an entry while holding the `ref` and a resize may move the entries array; your `ref` still points into the **old** array, which is still alive because the `ref` is keeping it so. The write succeeds, silently, into a copy nobody reads.

> 🌍 **In the real world**: a batch pricing endpoint took a JSON array of up to 5,000 line-item ids and matched them pairwise against a rules table with exactly the Two Sum shape — `Dictionary<int, decimal>`, one pass, textbook. It ran in single-digit milliseconds for two years. Then one tenant's integration started sending ids generated by their own hash function, which happened to produce values that were all congruent modulo the dictionary's bucket prime. Every id landed in one chain. The endpoint went from milliseconds to tens of seconds, thread-pool threads piled up behind it, and the incident was reported as "the pricing service is down" — which it effectively was, for every tenant, because the pool was saturated. Nobody had attacked anything; the collision was accidental, which is the part worth remembering, because it means "we're not a target" is not a defence. Two changes shipped: the ids were hashed through a mixing step before being used as keys, and the endpoint got a cap on batch size. The first fixed the bug. The second is the one that would have kept the blast radius to one tenant.

### 2. Longest Substring Without Repeating Characters

**Problem**: Given string `s`, find length of longest substring without repeats.

**Brute force**: check every substring, O(n³).

**Optimal**: sliding window. Expand right; on duplicate, shrink left.

```csharp
public int LengthOfLongestSubstring(string s)
{
    var lastSeen = new Dictionary<char, int>();
    int left = 0, max = 0;
    for (int right = 0; right < s.Length; right++)
    {
        if (lastSeen.TryGetValue(s[right], out var idx) && idx >= left)
            left = idx + 1;
        lastSeen[s[right]] = right;
        max = Math.Max(max, right - left + 1);
    }
    return max;
}
```

**Complexity**: O(n) time, O(min(n, alphabet)) space.

**Insight**: classic sliding window. Track last-seen index of each character.

**Bounded alphabet, unbounded allocation.** The `Dictionary<char, int>` is doing a job an array does better. If the input is known-ASCII, `Span<int> lastSeen = stackalloc int[128]` filled with `-1` gives O(1) indexed access with zero heap allocation and zero hashing — the whole window state lives in 512 bytes of stack that vanishes on return. Say it as a trade, not a rule: the array is `O(alphabet)` whether the string is 3 characters or 3 million, so it wins for long strings over a small alphabet and loses badly for short strings over Unicode.

**`char` is not "a character".** Every solution on this page treats `s[i]` as one character, and in .NET `s[i]` is one **UTF-16 code unit**. An emoji is two code units (a surrogate pair); an accented letter may be one code unit or two (base plus combining mark) depending on normalisation. So "longest substring without repeating characters" over `"👍👎👍"` sees repeated *halves* of surrogate pairs and returns an answer about nothing. `s.AsSpan().EnumerateRunes()` iterates Unicode scalar values instead of code units, and `StringInfo.GetTextElementEnumerator` iterates grapheme clusters — what a user calls a character. The interview answer is not to write the Rune version; it is to say the sentence out loud, because the person asking has shipped this bug.

### 3. Valid Anagram

**Problem**: Given strings `s` and `t`, are they anagrams?

**Optimal**: count frequencies; compare.

```csharp
public bool IsAnagram(string s, string t)
{
    if (s.Length != t.Length) return false;
    var count = new int[26];
    foreach (var c in s) count[c - 'a']++;
    foreach (var c in t) if (--count[c - 'a'] < 0) return false;
    return true;
}
```

**Complexity**: O(n) time, O(1) space (fixed alphabet).

**Insight**: use a fixed-size array for ASCII; `Dictionary<char, int>` for Unicode.

**This code throws on most real input, and that is the point.** `count[c - 'a']` is only in range for `c` in `'a'..'z'`. Feed it `"Listen"` and `'L' - 'a'` is `-21` (`'L'` is 76, `'a'` is 97), so it throws `IndexOutOfRangeException` on the first character. Feed it `"café"` and `'é' - 'a'` is 136 — also out of range. The `int[26]` trick is not a solution to "are these anagrams"; it is a solution to "are these anagrams, given the precondition that both are lowercase ASCII." Say the precondition, then ask whether it holds. An interviewer who has been burned by this will be listening for exactly that, and the candidates who get it right are the ones who say "let me check the input contract" rather than the ones who add a `ToLower()`.

And `ToLower()` is the wrong fix twice over. It allocates a second string per call, and it is culture-sensitive: in Turkish, `'I'.ToLower()` is `'ı'` (dotless i), not `'i'`, so an anagram checker that lower-cases with the current culture gives different answers on a Turkish server. If you need case-insensitivity, `ToLowerInvariant()` at minimum, and understand you are still comparing code units, not characters.

> 🌍 **In the real world**: a product-search feature deduplicated near-identical listings with an anagram-style character-frequency signature, and the `int[26]` version had been in production for a year because the catalogue was English. A European rollout added accented product names and the endpoint began throwing `IndexOutOfRangeException` — but only for some listings, so it read as an intermittent 500 rather than a bug with a clear trigger. The engineer on call widened the array to 256 and changed the index to `count[c % 256]` so nothing could ever throw again, which stopped the exceptions and quietly introduced a worse defect: every `char` above 255 now aliased onto some byte, so unrelated CJK listings collided on identical signatures and started matching each other as duplicates and merging. Nobody found *that* for another two months, because the failure was a silent merge rather than a crash. The lesson is not about Unicode. It is that widening a bounds check is almost never the fix for an out-of-range index — the index was computed from an assumption, and the assumption is what broke.

### 4. Group Anagrams

**Problem**: Given `string[] strs`, group anagrams together.

**Optimal**: canonicalize each string (sorted chars or frequency tuple); group by canonical form.

```csharp
public IList<IList<string>> GroupAnagrams(string[] strs)
{
    var groups = new Dictionary<string, List<string>>();
    foreach (var s in strs)
    {
        var key = string.Concat(s.OrderBy(c => c));
        if (!groups.TryGetValue(key, out var list)) groups[key] = list = new();
        list.Add(s);
    }
    return groups.Values.Cast<IList<string>>().ToList();
}
```

**Complexity**: O(n × k log k) where k is max string length.

**Insight**: hash by canonical form. Frequency tuple (`int[26]` → string) avoids the sort cost: O(n × k).

**The line that allocates.** `string.Concat(s.OrderBy(c => c))` is one expression and several allocations per input string: `OrderBy` returns an `OrderedEnumerable` object, buffers the source into a `char[]`, builds a parallel array of sort keys, allocates an enumerator, and `string.Concat` walks that enumerator to build the result. Exactly one of those — the result string — outlives the call. The rest is Gen 0 garbage, produced once per element, in a loop.

The span version allocates only the key:

```csharp
using System.Buffers;

static string CanonicalKey(string s)
{
    const int StackLimit = 256;
    Span<char> buf = stackalloc char[StackLimit];
    char[]? rented = null;
    if (s.Length > StackLimit)
    {
        rented = ArrayPool<char>.Shared.Rent(s.Length);  // NOTE: *at least* s.Length
        buf = rented;
    }
    buf = buf[..s.Length];                               // ...so slice to what you asked for
    s.CopyTo(buf);
    buf.Sort();                                          // MemoryExtensions.Sort, .NET 5+
    string key = new string(buf);
    if (rented is not null) ArrayPool<char>.Shared.Return(rented);
    return key;
}
```

Three things in there are worth being able to defend. The `stackalloc` is unconditional and fixed-size — never `stackalloc s.Length`, because an attacker-chosen length becomes a stack overflow, and a stack overflow is a dead process (see [Number of Islands](#20-number-of-islands)). `Rent` "retrieves a buffer that is at least the requested length" and the returned array "may not be zero-initialized" (Microsoft Learn, *ArrayPool&lt;T&gt;.Rent*), which is why the slice is not optional and why you must never trust the tail. And the sort is now `Array.Sort`'s introsort rather than LINQ's stable sort — irrelevant for characters, but the kind of substitution you should notice yourself making.

> 🌍 **In the real world**: a catalogue import ran a fuzzy-duplicate pass over roughly a million product titles per night, keyed by a sorted-character signature written exactly as the `OrderBy` line above. It had never been a problem because it ran at 2am on a box doing nothing else. Moving the importer into the same service as the public API changed that: the import's allocation rate pushed Gen 0 collections to a rate that showed up as a periodic latency shelf on unrelated API endpoints — request p99 climbing every night for the ninety minutes of the import, with no correlation to any API change. The API team looked at the API for a week. What settles this class of argument is not a profiler screenshot, it is the allocation counter: `dotnet-counters monitor --counters System.Runtime` on the running process shows `alloc-rate` and Gen 0 count without attaching anything or restarting. Two hours of rewriting the signature builder to the span version above took the import's steady-state allocation to roughly the size of its output. The generic lesson: an allocation-heavy background job in a shared process is not slow — it makes *other* things slow, which is why it is so rarely found by looking at the thing that is slow.

### 5. Container With Most Water

**Problem**: Given heights, find two lines that form a container holding the most water.

**Optimal**: two pointers from both ends; move the shorter inward.

```csharp
public int MaxArea(int[] heights)
{
    int left = 0, right = heights.Length - 1, max = 0;
    while (left < right)
    {
        int area = (right - left) * Math.Min(heights[left], heights[right]);
        max = Math.Max(max, area);
        if (heights[left] < heights[right]) left++; else right--;
    }
    return max;
}
```

**Complexity**: O(n) time, O(1) space.

**Insight**: moving the taller side can't help (width decreases, height capped). Always move the shorter.

**That `area` is an `int` multiplication, and C# will not tell you when it wraps.** `(right - left) * Math.Min(...)` multiplies a width by a height, both `int`, into an `int`. The language default is not to check: "The default statement is `unchecked`… In an unchecked context, the operation result is truncated by discarding any high-order bits that don't fit in the destination type" (Microsoft Learn, *The checked and unchecked statements*). Give it 100,001 posts each 100,000 tall and the true answer is 100,000 × 100,000 = 10,000,000,000, which does not fit in an `int` (`int.MaxValue` is 2,147,483,647). The method returns a smaller **positive** number. No exception, no warning, no negative value to raise an eyebrow — just a plausible answer that is wrong, which is the worst failure mode a function can have.

Three responses, and knowing which one to reach for first is the actual test:

1. **Widen the operand, not the result.** `long area = (long)(right - left) * Math.Min(heights[left], heights[right]);` — and read that cast carefully, because `long area = (right - left) * Math.Min(...)` multiplies in `int`, wraps, *then* widens the wrong answer. That version survives code review indefinitely, because the declaration says `long` and the eye stops there.
2. **Make the wrap loud.** `checked { … }` around the expression, or `<CheckForOverflowUnderflow>true</CheckForOverflowUnderflow>` in the `.csproj`, which flips the default for the whole assembly and turns every silent truncation into an `OverflowException`. Worth knowing it exists even if you would not enable it on a hot path.
3. **Bound the input.** If the domain caps width and height, encode the cap in a guard, not in a comment.

Two details that make this a senior answer rather than a trivia answer. The wrap is only silent for *non-constant* expressions — "Constant expressions are evaluated by default in a checked context and overflow causes a compile-time error", so `int x = 100_000 * 100_000;` does not compile while the identical arithmetic on variables ships. And `checked` is textual, not dynamic: a `checked { }` block does not extend into the methods it calls, so wrapping the call site protects nothing that happens inside the callee.

The transferable form: **any product of two problem-sized quantities needs its type decided deliberately** — areas, byte counts, `count × pageSize`, `rows × cols`. `int` looks obviously sufficient precisely because each factor is small. The sum-shaped version of the same bug (a counting DP whose accumulator overflows) is worked through in [Dynamic Programming](./06-dynamic-programming.md#dp-fundamentals--overlapping-subproblems--optimal-substructure).

> 🌍 **In the real world**: a media service computed the storage a customer's uploads would consume before accepting them — `int pixels = width * height;` then a bytes-per-pixel multiply, all in `int`, in a quota check that had run correctly for years against phone photos. A customer began uploading gigapixel scans of engineering drawings. The product overflowed, the quota check computed a small positive size, and the upload was admitted; the *actual* write then blew through the tenant's quota, and the next one, and the storage account's soft limit, before anyone connected the alerts to the uploads. Nothing threw at any point — the check did its job on a number that was arithmetically wrong. The eventual fix was one cast and a guard on the dimensions, and the post-mortem action item was the interesting part: the team turned on `CheckForOverflowUnderflow` in the *test* configuration only, so overflow raises during CI and stays truncating in production. That is a deliberate, defensible position — surface the class of bug where it is cheap to find, don't add a branch to every arithmetic operation on the hot path — and being able to state it is worth more in an interview than the cast is.

### 6. Trapping Rain Water

**Problem**: Given heights, compute how much water is trapped after rain.

**Optimal**: two pointers. Track `leftMax` and `rightMax`; move the shorter side; accumulate water = `max - height`.

```csharp
public int Trap(int[] heights)
{
    int left = 0, right = heights.Length - 1, leftMax = 0, rightMax = 0, water = 0;
    while (left < right)
    {
        if (heights[left] < heights[right])
        {
            if (heights[left] >= leftMax) leftMax = heights[left];
            else water += leftMax - heights[left];
            left++;
        }
        else
        {
            if (heights[right] >= rightMax) rightMax = heights[right];
            else water += rightMax - heights[right];
            right--;
        }
    }
    return water;
}
```

**Complexity**: O(n) time, O(1) space.

**Insight**: water at index `i` = `min(maxLeft, maxRight) - height[i]`. Two pointers track both max simultaneously.

**The interesting decision here is not in the body, it is in the signature.** `int Trap(int[] heights)` reads the array and never stores it, never mutates it, and never needs its length to change — which means `int[]` is over-specified. It forces every caller to *have an array*. A caller holding a `List<int>`, a slice of a larger buffer, a `stackalloc`, or a rented `ArrayPool<int>` array has to copy first, and the copy is O(n) work and an O(n) allocation added to an algorithm whose whole selling point is O(1) space.

```csharp
public static int Trap(ReadOnlySpan<int> heights) { /* body is character-for-character identical */ }
```

Every caller improves and none breaks — `int[]`, `Span<int>`, and `ArraySegment<int>` all convert implicitly, `list` goes through `CollectionsMarshal.AsSpan(list)`, and a sub-range is `buffer.AsSpan(start, len)` with no copy. `ReadOnlySpan<T>` also documents the contract in the type: *I read this, I do not keep it, I do not change it.* That is the whole reason the BCL's own scanning APIs are shaped this way.

Now defend it, because the follow-up is "why isn't everything a span?" `Span<T>` and `ReadOnlySpan<T>` are `ref struct`s, and the compiler enforces that they never reach the heap. From Microsoft Learn, *ref struct types*, the constraints that actually bite:

| Constraint | What it costs you in real code |
|---|---|
| "You can't declare a `ref struct` as the type of a field in a class or a non-`ref struct`" | No caching the input on the object, no storing it in a closure state machine |
| "You can't capture a `ref struct` variable in a lambda expression or a local function" | A LINQ-ish or callback-based refactor of the body will not compile |
| "Beginning with C# 13, a `ref struct` variable can't be used in the same block as the `await` expression" | The method cannot become `async` later without restructuring |
| "Beginning with C# 13, `ref struct` types … can be used in iterators, provided they aren't in code segments with the `yield return` statement" | It cannot become a `yield return` generator either |
| "You can't box a `ref struct`" | It cannot be passed as `object`, and before C# 13 it could not be a type argument at all |

So the rule is not "prefer spans", it is: **span parameters are right for synchronous, self-contained, read-and-return work, and wrong the moment the data has to outlive the call.** Say it that way and the follow-up is answered before it is asked. The version of this decision you will actually make at work is the async one — a parsing helper written against `ReadOnlySpan<char>` is perfect until someone needs it to `await` a lookup in the middle, at which point the signature has to change to `ReadOnlyMemory<char>` and the whole call chain moves with it.

> 🌍 **In the real world**: a telemetry API accepted batches of readings and ran a handful of small analytics over each batch — min, max, a trapped-water-shaped "gap volume", a couple of rolling aggregates. Each helper took `double[]`, and because the batch arrived as a `List<double>` and each helper wanted a different sub-range, the controller called `.Skip(a).Take(b).ToArray()` between them. Six helpers, six array allocations per request, every array a copy of most of the batch — and at the batch sizes the service actually saw, several of those landed on the large object heap, which is collected with Gen 2 and not compacted by default. The endpoint's own CPU time was unremarkable; what was remarkable was the Gen 2 collection rate of the whole process, which meant *every* endpoint's p99 moved when this one got busy. The fix touched no algorithm: the helpers were changed to take `ReadOnlySpan<double>`, the controller got one `CollectionsMarshal.AsSpan(batch)` and passed slices of it, and the six allocations became zero. What makes this worth telling is the review conversation, not the diff — the objection was "spans are a micro-optimisation", and the answer that ended it was that the change removed six O(n) *copies*, not six nanoseconds. **A span parameter is usually an algorithmic change wearing a performance costume.**

### 7. Longest Palindromic Substring

**Problem**: Given a string, find the longest palindromic substring.

**Optimal**: expand around centers. For each index, expand outward while characters match (handle even and odd length palindromes).

```csharp
public string LongestPalindrome(string s)
{
    if (string.IsNullOrEmpty(s)) return "";
    int start = 0, maxLen = 1;
    for (int i = 0; i < s.Length; i++)
    {
        int len1 = ExpandAround(s, i, i);          // odd
        int len2 = ExpandAround(s, i, i + 1);      // even
        int len = Math.Max(len1, len2);
        if (len > maxLen)
        {
            maxLen = len;
            start = i - (len - 1) / 2;
        }
    }
    return s.Substring(start, maxLen);
}

private int ExpandAround(string s, int left, int right)
{
    while (left >= 0 && right < s.Length && s[left] == s[right]) { left--; right++; }
    return right - left - 1;
}
```

**Complexity**: O(n²) time, O(1) space. Manacher's algorithm gets O(n) but is rarely interview-required.

**Insight**: 2n-1 possible palindrome centers (n odd-length + n-1 even-length).

**`s.Substring(start, maxLen)` copies, and the copy is the feature.** In .NET a substring is an independent `string` with its own character storage — it shares nothing with `s`. That costs one allocation and one copy per call, and it buys you the guarantee that returning a 12-character result from a 4-megabyte input keeps 12 characters alive. Some platforms have shipped the other design (a substring that keeps a reference into the parent's buffer), and the bug that design produces is a heap full of enormous strings that nothing appears to reference. If an interviewer asks "does `Substring` allocate?", the complete answer is "yes, and here is what the alternative costs."

**Which is exactly the trap you re-open with `AsMemory`.** The zero-copy version of the return value looks like an obvious upgrade:

```csharp
// no allocation... and no independence either
public ReadOnlyMemory<char> LongestPalindrome(string s) => s.AsMemory(start, maxLen);
```

`ReadOnlyMemory<char>` is not a `ref struct`, so unlike a span it *can* be stored in a field, held by a cache, or parked on an object that outlives the request — and a `ReadOnlyMemory<char>` holds a reference to the whole original `string`. Keep a 12-character slice of a four-million-character request body on a cached object and the GC keeps all four million characters — eight megabytes of UTF-16 — alive for as long as that object lives. The allocation profiler shows nothing, because nothing was allocated; the Gen 2 heap grows anyway. `ToString()` on the memory, or `new string(span)`, is how you cut it loose — and knowing *when* to pay for that cut is the point.

(A second reason not to reach for it as a lookup key: `ReadOnlyMemory<char>` does not compare by content. Its default equality asks whether two instances refer to the same object over the same range, so `"abc".AsMemory()` and another `"abc".AsMemory()` are not equal. A `Dictionary<ReadOnlyMemory<char>, _>` without a hand-written content comparer will simply never find anything — and it will not throw while not finding it.)

The rule that comes out of it: **slice for the duration of a call, copy for anything you keep.** `ReadOnlySpan<char>` for the working loop because the compiler makes it impossible to keep; a real `string` for anything that crosses a cache, a field, or a `Task` boundary.

> 🌍 **In the real world**: a log-ingestion service parsed newline-delimited records out of pooled buffers and, sensibly, avoided allocating a string per field by keeping `ReadOnlyMemory<char>` slices. One of those fields — a tenant identifier, typically eight characters — was copied onto a per-tenant counter object that lived in a long-lived `ConcurrentDictionary`, as a `ReadOnlyMemory<char>` field, because a `string` there "would have allocated". Each of those eight-character fields silently held the entire log batch it had been sliced out of. Memory climbed steadily with no matching allocation rate, the dictionary held a few thousand tiny objects, and every leak hunt found "a few thousand tiny objects" and moved on, because the tooling reported the *slice's* size, not its referent's. It was found by opening a dump and looking at what was actually rooting the large-object heap. The fix was one `.ToString()`, at the point the counter object was created — deliberately paying for one eight-character allocation to release a multi-megabyte one. The lesson generalises past `Memory<T>`: **any zero-copy view is a reference to something bigger, and the moment its lifetime exceeds the parse it stops being an optimisation.**

### 8. Sliding Window Maximum

**Problem**: Given `int[] nums` and window size `k`, return the max in each window of size k.

**Optimal**: monotonic deque; maintain decreasing order so the front is always the current max.

```csharp
public int[] MaxSlidingWindow(int[] nums, int k)
{
    var result = new int[nums.Length - k + 1];
    var deque = new LinkedList<int>();         // stores indices
    for (int i = 0; i < nums.Length; i++)
    {
        // Remove out-of-window indices
        while (deque.Count > 0 && deque.First!.Value < i - k + 1) deque.RemoveFirst();
        // Maintain decreasing order
        while (deque.Count > 0 && nums[deque.Last!.Value] < nums[i]) deque.RemoveLast();
        deque.AddLast(i);
        if (i >= k - 1) result[i - k + 1] = nums[deque.First!.Value];
    }
    return result;
}
```

**Complexity**: O(n) time (each element pushed and popped at most once), O(k) space.

**Insight**: monotonic deque for O(1) "max so far in window" queries.

**`LinkedList<T>` is the wrong container here, and it is a good interview answer to say so.** `LinkedList<int>` is a doubly-linked list of `LinkedListNode<int>`, and `LinkedListNode<T>` is a **class**. `AddLast` allocates one heap object per push — an object header, plus `prev`, `next`, `list` references, plus the `int`. The algorithm pushes every element exactly once, so an n-element input allocates n nodes to hold at most k of them at a time, and hands the other n−k to the GC. The nodes are also scattered across the heap, so walking the deque chases pointers instead of walking a cache line.

A monotonic deque over a fixed window has a bounded size by construction, which is exactly the case a ring buffer serves. Same algorithm, same complexity, one allocation total:

```csharp
public int[] MaxSlidingWindow(int[] nums, int k)
{
    if (k < 1 || k > nums.Length) throw new ArgumentOutOfRangeException(nameof(k));

    var result = new int[nums.Length - k + 1];
    var dq = new int[k];        // ring buffer of indices; allocated once, never grows
    int head = 0, count = 0;    // live entries are dq[(head + 0..count-1) % k]

    for (int i = 0; i < nums.Length; i++)
    {
        // drop the index that just fell out of the window (at most one per step)
        if (count > 0 && dq[head] <= i - k) { head = (head + 1) % k; count--; }
        // drop indices whose values this one dominates
        while (count > 0 && nums[dq[(head + count - 1) % k]] < nums[i]) count--;
        dq[(head + count) % k] = i;
        count++;
        if (i >= k - 1) result[i - k + 1] = nums[dq[head]];
    }
    return result;
}
```

Note the guard that the original silently lacked: `new int[nums.Length - k + 1]` with `k > nums.Length` asks for a negative-length array and throws `OverflowException`, which is not a message anyone will connect to a bad window size.

The general shape is worth carrying out of this problem: **when the data structure's size is bounded by the problem, a linked structure is paying per-element allocation for flexibility you have already ruled out.** That sentence answers a whole family of follow-ups, and it is why `Stack<T>` and `Queue<T>` in the BCL are array-backed while `LinkedList<T>` exists mainly for O(1) removal of a node you already hold — which is precisely what the LRU cache in Drill 7 needs and this problem does not.

---

## Linked lists

### 9. Reverse Linked List

**Problem**: Reverse a singly-linked list.

**Iterative**:
```csharp
public ListNode? Reverse(ListNode? head)
{
    ListNode? prev = null, curr = head;
    while (curr != null)
    {
        var next = curr.Next;
        curr.Next = prev;
        prev = curr;
        curr = next;
    }
    return prev;
}
```

**Complexity**: O(n) time, O(1) space.

**Insight**: three pointers: prev / curr / next.

### 10. Detect Cycle (Floyd's Tortoise and Hare)

**Problem**: Determine if a linked list has a cycle.

**Optimal**: two pointers, slow (1 step) and fast (2 steps). If they meet, there's a cycle.

```csharp
public bool HasCycle(ListNode? head)
{
    var slow = head;
    var fast = head;
    while (fast?.Next != null)
    {
        slow = slow!.Next;
        fast = fast.Next.Next;
        if (slow == fast) return true;
    }
    return false;
}
```

**Complexity**: O(n) time, O(1) space.

**Insight**: in a cycle, fast catches up to slow. To find the cycle's start: after meeting, reset slow to head; advance both 1 step; meeting point is the cycle start.

**`slow == fast` is the load-bearing line, and in C# it does not mean what the algorithm needs.** The invariant Floyd's relies on is *object identity* — the two pointers are looking at the same node. `==` in C# means whatever the operand's **static type** says it means, resolved at compile time:

| Declaration of `ListNode` | What `slow == fast` compiles to |
|---|---|
| `class ListNode { ... }` | reference comparison — correct |
| `record ListNode(int Val) { ... }` | the synthesised `operator ==`, i.e. member-wise equality |
| `class ListNode` with a hand-written `operator ==` | whatever that operator does |
| variable typed as `object` or an interface | reference comparison, *even if the runtime type overloads `==`* — operator resolution is static |

The second and fourth rows are the two ways this goes wrong, and they go wrong in opposite directions. Give the node value equality and `HasCycle` returns `true` for an acyclic list that merely contains two equal nodes — a false positive on correct data. Type a variable as `object` and a carefully written `operator ==` is bypassed without a warning. `ReferenceEquals(slow, fast)` says identity and cannot be overridden, which is exactly why it exists. When identity is the invariant, spell it.

The same trap has a dictionary form, and [Clone Graph](#18-clone-graph) below is where it bites hardest.

> 🌍 **In the real world**: a workflow engine detected circular step dependencies by walking `Next` links with tortoise-and-hare. `WorkflowStep` was a plain class for three years, then a refactor made it a `record` — the PR was about serialisation and value semantics for a diff view, and it did what it said. The cycle detector started rejecting legitimate workflows as circular, because two steps of the same type with the same configuration are `==` to a record. The validation error said "circular dependency detected", so the reports came in as "the validator is broken" and every investigation went into the graph-building code. The one-line repair was `ReferenceEquals`. The durable lesson is about blast radius: changing `class` to `record` changes the meaning of `==`, `Equals`, `GetHashCode`, and therefore the behaviour of every `Dictionary`, `HashSet`, `Distinct`, and `Contains` that type has ever been put into — most of which are nowhere near the file you edited, and none of which the compiler will point at.

### 11. Merge Two Sorted Lists

**Problem**: Merge two sorted linked lists into one sorted list.

**Optimal**: dummy node + tail pointer; pick smaller head each step.

```csharp
public ListNode? Merge(ListNode? a, ListNode? b)
{
    var dummy = new ListNode(0);
    var tail = dummy;
    while (a != null && b != null)
    {
        if (a.Val <= b.Val) { tail.Next = a; a = a.Next; }
        else                { tail.Next = b; b = b.Next; }
        tail = tail.Next;
    }
    tail.Next = a ?? b;
    return dummy.Next;
}
```

**Complexity**: O(n + m) time, O(1) space.

**Insight**: dummy node avoids special-casing the head.

### 12. Find Middle of Linked List

**Problem**: Return the middle node.

**Optimal**: slow/fast pointers; when fast reaches end, slow is at middle.

```csharp
public ListNode? FindMiddle(ListNode? head)
{
    var slow = head;
    var fast = head;
    while (fast?.Next != null)
    {
        slow = slow!.Next;
        fast = fast.Next.Next;
    }
    return slow;
}
```

**Complexity**: O(n) time, O(1) space.

**Insight**: combines with reverse to check palindrome list, with cycle detection, etc.

**`slow!.Next` is the most interesting character on this page.** The `!` is the null-forgiving operator, and it does exactly one thing: it silences the compiler. It emits no IL, performs no check, and asserts nothing the runtime will verify. It is a comment addressed to the analyser, and like every comment it can be wrong — at which point you get a `NullReferenceException` on a line that the compiler had already flagged and you had already overruled.

Here the assertion happens to hold, and being able to say *why* is the whole exercise. `slow` starts equal to `head`; the loop only runs when `fast?.Next != null`, which requires `fast` non-null, which requires `head` non-null, and `slow` never advances further than `fast`. Three sentences. If you cannot produce them, the `!` is not an assertion, it is a wish.

The habits that separate the two:

- **Prove it or restructure it.** `while (fast?.Next is not null)` followed by hoisting `head` into a non-nullable local at the top (`if (head is null) return null; ListNode node = head;`) makes the invariant visible to the compiler, and then the `!` is not needed at all. Removing a suppression by teaching the compiler the truth beats keeping the suppression.
- **Never use `!` to silence a warning you have not investigated.** The warning is the analyser reporting that it cannot prove something. Sometimes that means the analyser is limited; sometimes it means you are wrong.
- **Know that the guarantee is compile-time only.** Nullable reference type annotations are erased — a `ListNode` parameter declared non-nullable can still receive `null` from a caller in a `#nullable disable` file, from reflection, from a deserialiser, or from any assembly compiled without the feature. That is why the BCL still writes `ArgumentNullException.ThrowIfNull(head)` at public boundaries: **annotations are for your compiler, guards are for other people's code.**

> 🌍 **In the real world**: a team enabled `<Nullable>enable</Nullable>` on a mature service and got several thousand warnings. The pragmatic plan — fix the ones in new code, suppress the rest, revisit later — was executed by a scripted pass that appended `!` at each warning site. It compiled clean, and the annotation had, in aggregate, changed nothing except that the compiler had now been instructed to stop mentioning any of it. Two months later a `NullReferenceException` in a mapping method traced to a `!` that the script had placed on a genuinely-nullable database column. The retrospective conclusion was the useful one: the value of the feature is entirely in the warnings you *act* on, so a bulk suppression is worse than not enabling it — it costs the same churn and buys a false sense that the codebase is null-clean. What they did next was enable it project by project, with `<WarningsAsErrors>Nullable</WarningsAsErrors>` on each project as it was finished, so a property that had been made null-clean could never quietly regress.

---

## Trees

### 13. Inorder Traversal (iterative)

**Problem**: BST inorder = sorted order. Implement iteratively.

```csharp
public List<int> InorderIterative(TreeNode? root)
{
    var result = new List<int>();
    var stack = new Stack<TreeNode>();
    var curr = root;
    while (curr != null || stack.Count > 0)
    {
        while (curr != null) { stack.Push(curr); curr = curr.Left; }
        curr = stack.Pop();
        result.Add(curr.Val);
        curr = curr.Right;
    }
    return result;
}
```

**Complexity**: O(n) time, O(h) space.

**Insight**: simulate recursion with an explicit stack. Pre-order, post-order similar with adjusted push order.

**State the reason you'd choose this in production, because it is not elegance.** The recursive version is shorter and clearer; this one exists so that the O(h) frontier lives on the heap instead of the call stack — heap exhaustion throws a catchable `OutOfMemoryException`, call-stack exhaustion terminates the process. On a balanced tree neither matters. On a tree whose shape is derived from data you did not generate — a category hierarchy, a comment thread, a filesystem — the depth is an input, and "the depth is an input" is the whole argument.

Two small wins while you are here: `new Stack<TreeNode>(height)` if you have any idea of the height, and note that `Stack<T>` is array-backed (so is `Queue<T>`, as a circular buffer) — neither allocates per push once the array is large enough, which is why they are the right primitives for this and `LinkedList<T>` is not.

### 14. Maximum Depth of Binary Tree

```csharp
public int MaxDepth(TreeNode? root) =>
    root == null ? 0 : 1 + Math.Max(MaxDepth(root.Left), MaxDepth(root.Right));
```

**Complexity**: O(n) time, O(h) space (recursion stack).

**Insight**: trivial recursive DFS. Iterative BFS counting levels also works.

### 15. Validate BST

**Problem**: Is a binary tree a valid BST?

**Optimal**: recurse with allowed range `(min, max)`.

```csharp
public bool IsValidBst(TreeNode? root) => Validate(root, long.MinValue, long.MaxValue);

private bool Validate(TreeNode? node, long min, long max)
{
    if (node == null) return true;
    if (node.Val <= min || node.Val >= max) return false;
    return Validate(node.Left, min, node.Val) && Validate(node.Right, node.Val, max);
}
```

**Complexity**: O(n) time, O(h) space.

**Insight**: comparing only with parent is wrong (a left child far up the tree can exceed an ancestor's right). Pass the range down.

**The `long` sentinels are a trick, and tricks have expiry dates.** Widening to `long` works only because `Val` is `int`, so no node value can ever equal `long.MinValue` or `long.MaxValue`. Change `TreeNode.Val` to `long` — a plausible schema change, made in a different file, by someone who has never read this method — and a tree containing `long.MinValue` is reported invalid, silently, on exactly one node. Change it to `decimal` or `DateTime` and the method does not compile, which is the good outcome.

Nullable bounds say "no bound" instead of "a bound so extreme it cannot occur", and survive any value type:

```csharp
public bool IsValidBst(TreeNode? root) => Validate(root, null, null);

private bool Validate(TreeNode? node, int? min, int? max)
{
    if (node is null) return true;
    if (min is int lo && node.Val <= lo) return false;
    if (max is int hi && node.Val >= hi) return false;
    return Validate(node.Left, min, node.Val) && Validate(node.Right, node.Val, max);
}
```

This is a small thing to have an opinion about, and interviewers ask it precisely because it separates "I memorised the sentinel" from "I know why the sentinel was chosen". The general form — **a sentinel is a value you are betting cannot occur, and the bet is invisible at the call site** — recurs in every `-1 means not found`, every `DateTime.MinValue means never`, and every `0 means unset` you will ever review.

### 16. Lowest Common Ancestor (BST)

**Problem**: LCA of two nodes p and q in a BST.

**Optimal**: walk down; the first node where p and q split (one ≤, one ≥) is the LCA.

```csharp
public TreeNode? LcaBst(TreeNode? root, TreeNode p, TreeNode q)
{
    while (root != null)
    {
        if (p.Val < root.Val && q.Val < root.Val) root = root.Left;
        else if (p.Val > root.Val && q.Val > root.Val) root = root.Right;
        else return root;
    }
    return null;
}
```

**Complexity**: O(h) time, O(1) space.

**Insight**: the BST property gives an O(h) descent. For general binary trees, O(n) recursion required.

### 17. Serialize and Deserialize Binary Tree

**Problem**: Convert tree to string and back.

**Optimal**: pre-order with null markers.

```csharp
public string Serialize(TreeNode? root)
{
    var sb = new StringBuilder();
    SerHelper(root, sb);
    return sb.ToString();
}

private void SerHelper(TreeNode? node, StringBuilder sb)
{
    if (node == null) { sb.Append("#,"); return; }
    sb.Append(node.Val).Append(',');
    SerHelper(node.Left, sb);
    SerHelper(node.Right, sb);
}

public TreeNode? Deserialize(string data)
{
    var queue = new Queue<string>(data.Split(',', StringSplitOptions.RemoveEmptyEntries));
    return DeserHelper(queue);
}

private TreeNode? DeserHelper(Queue<string> queue)
{
    var token = queue.Dequeue();
    if (token == "#") return null;
    return new TreeNode(int.Parse(token))
    {
        Left = DeserHelper(queue),
        Right = DeserHelper(queue)
    };
}
```

**Complexity**: O(n) time and space for both.

**Insight**: pre-order + null markers uniquely encodes the tree. Level-order with markers also works.

**The object initializer is doing something subtle.** `new TreeNode(...) { Left = DeserHelper(queue), Right = DeserHelper(queue) }` is only correct because `Left`'s initializer runs before `Right`'s — the two calls consume tokens from a shared queue, so their order *is* the format. That is a real ordering dependency expressed as syntax that reads like a declaration, and a "tidy-up" that swaps the two lines to alphabetise them produces a tree that is a mirror of the input, with no compiler complaint and no exception. Write it as statements so the dependency is visible:

```csharp
var node = new TreeNode(int.Parse(token));
node.Left  = DeserHelper(queue);   // must consume before Right — the queue is the format
node.Right = DeserHelper(queue);
return node;
```

**And this is a deserialiser, so assume the input is hostile.** `queue.Dequeue()` on an exhausted queue throws `InvalidOperationException` on truncated input — fine, if you expected it. What is not fine is deep input: a payload of 500,000 `1,` tokens is a 500,000-frame recursion, and in .NET that is not an exception you catch (see [Number of Islands](#20-number-of-islands)). This is exactly why `System.Text.Json` ships a `MaxDepth` option and enforces it before recursing. Any recursive parser that reads from the network needs a depth limit as a first-class parameter, not as a comment.

`int.Parse(token)` is also culture-sensitive by default; `int.Parse(token, CultureInfo.InvariantCulture)` for a wire format, always, because the format does not change when the server's locale does.

---

## Graphs

### 18. Clone Graph

**Problem**: Deep clone a graph (each node has a value and neighbors list).

**Optimal**: BFS or DFS with a `Dictionary<Node, Node>` mapping originals to clones.

```csharp
public Node? CloneGraph(Node? node)
{
    if (node == null) return null;
    var clones = new Dictionary<Node, Node>();
    var queue = new Queue<Node>();
    clones[node] = new Node(node.Val);
    queue.Enqueue(node);
    while (queue.Count > 0)
    {
        var orig = queue.Dequeue();
        foreach (var n in orig.Neighbors)
        {
            if (!clones.ContainsKey(n))
            {
                clones[n] = new Node(n.Val);
                queue.Enqueue(n);
            }
            clones[orig].Neighbors.Add(clones[n]);
        }
    }
    return clones[node];
}
```

**Complexity**: O(V + E) time, O(V) space.

**Insight**: cycle-safe by checking the dictionary before recursing.

**`Dictionary<Node, Node>` keys on equality, and this algorithm needs identity.** `new Dictionary<Node, Node>()` uses `EqualityComparer<Node>.Default`, which calls `Node.Equals` — reference equality for a plain class, but member-wise equality for a `record`, and whatever the author wrote for anything that overrides `Equals`/`GetHashCode`. In a graph of two distinct nodes that happen to carry the same value, a value-equality comparer collapses them into one key. The clone then has fewer nodes than the original, with edges rewired to the survivor, and every test on a graph of distinct values passes.

Say what you mean:

```csharp
// Identity, not equality — cannot be subverted by the node type.
var clones = new Dictionary<Node, Node>(ReferenceEqualityComparer.Instance);
```

`ReferenceEqualityComparer` (`System.Collections.Generic`, .NET 5+) is a sealed singleton implementing `IEqualityComparer<object>`; it satisfies a `Dictionary<Node, Node>` because `IEqualityComparer<in T>` is contravariant and `Node` is a reference type. Its `GetHashCode` is based on object identity rather than contents, which is the half people forget — a comparer that gets `Equals` right and `GetHashCode` wrong puts identical objects in different buckets and never finds them.

The same argument applies to every `visited` set in every graph traversal on this page. If the vertex type is under someone else's control, "have I been here" is an identity question and should be asked with an identity comparer.

> 🌍 **In the real world**: a permissions service cloned an org-unit graph before applying a what-if simulation, using exactly the dictionary above. `OrgUnit` overrode `Equals` to compare by `(TenantId, Code)` — a reasonable domain decision made years earlier, in a different file, for a different reason. Most tenants were fine. One had two org units with the same code in different branches of the tree, a data-quality issue that had never mattered because nothing else compared org units. The simulation silently merged them, so a permission grant to one branch appeared to apply to the other, and the what-if screen told an administrator that a change was safe when it was not. It was found by an auditor, not by monitoring, because the output was a plausible answer rather than an error. The transferable point: a domain `Equals` is a statement about *business* identity, and a graph algorithm asks about *object* identity. They are different questions, and the default comparer answers the wrong one.

### 19. Course Schedule (Cycle Detection)

**Problem**: Given prerequisites, can all courses be completed (i.e., no cycle in the prereq graph)?

**Optimal**: topological sort via Kahn's algorithm; if cycle, can't sort.

```csharp
public bool CanFinish(int n, int[][] prereqs)
{
    var graph = new Dictionary<int, List<int>>();
    var inDeg = new int[n];
    foreach (var p in prereqs)
    {
        if (!graph.TryGetValue(p[1], out var list)) graph[p[1]] = list = new();
        list.Add(p[0]);
        inDeg[p[0]]++;
    }
    var queue = new Queue<int>();
    for (int i = 0; i < n; i++) if (inDeg[i] == 0) queue.Enqueue(i);
    int processed = 0;
    while (queue.Count > 0)
    {
        var v = queue.Dequeue();
        processed++;
        if (graph.TryGetValue(v, out var nbrs))
            foreach (var n2 in nbrs)
                if (--inDeg[n2] == 0) queue.Enqueue(n2);
    }
    return processed == n;
}
```

**Complexity**: O(V + E) time and space.

**Insight**: Kahn's signals cycle when not all vertices visited.

**Kahn's tells you *that* there is a cycle, not *which* one.** `processed != n` is a boolean, and the vertices still sitting with non-zero in-degree at the end are exactly the ones in or downstream of a cycle — so a two-line addition turns a useless error into a useful one: collect the indices where `inDeg[i] > 0` after the loop and report them. This distinction is the entire follow-up. Anyone shipping a scheduler, a build graph, or a migration ordering will be asked "and what does the error message say?", and "cycle detected" is the wrong answer.

If you need the actual cycle rather than the set of implicated vertices, that is DFS with three-colour marking — grey means "on the current path", and finding a grey vertex gives you the back edge and therefore the cycle, which Kahn's structurally cannot.

> 🌍 **In the real world**: this is not a puzzle, it is what `Microsoft.Extensions.DependencyInjection` does when you register `A` depending on `B` depending on `A` — and the reason its message names the chain rather than saying "circular dependency" is that a container which only said the latter would be unusable in an app with four hundred registrations. A team building a workflow product learned this the expensive way: their validator ran Kahn's, returned `false`, and rendered "This workflow contains a circular dependency." Support tickets arrived with screenshots of hundred-step workflows and the question "which steps?". The engineering change was the two lines above — report the vertices with residual in-degree — and it closed a category of support ticket outright. The transferable lesson is that **a detection algorithm and a diagnostic are different deliverables**, and the gap between them is usually a handful of lines that nobody writes because the tests only assert on the boolean.

### 20. Number of Islands

**Problem**: Given a 2D grid of 1s (land) and 0s (water), count connected islands.

**Optimal**: BFS or DFS from each unvisited land cell; mark cells visited.

```csharp
public int NumIslands(char[][] grid)
{
    int rows = grid.Length, cols = grid[0].Length, count = 0;
    for (int r = 0; r < rows; r++)
        for (int c = 0; c < cols; c++)
            if (grid[r][c] == '1')
            {
                count++;
                Sink(grid, r, c, rows, cols);
            }
    return count;
}

private void Sink(char[][] grid, int r, int c, int rows, int cols)
{
    if (r < 0 || c < 0 || r >= rows || c >= cols || grid[r][c] != '1') return;
    grid[r][c] = '0';
    Sink(grid, r + 1, c, rows, cols);
    Sink(grid, r - 1, c, rows, cols);
    Sink(grid, r, c + 1, rows, cols);
    Sink(grid, r, c - 1, rows, cols);
}
```

**Complexity**: O(rows × cols) time, O(rows × cols) space (recursion stack worst case).

**Insight**: connected-components on an implicit grid graph. Sink each island as you count it.

**Read that space complexity again — it is the interview.** "O(rows × cols) recursion stack" is not a footnote, it is the failure mode. A 2000 × 2000 grid that is all land is a four-million-frame recursion, and here is precisely what .NET does about it:

**You do not get an exception.** "You can't catch a `StackOverflowException` object with a `try`/`catch` block, and the corresponding process is terminated by default" (Microsoft Learn, *StackOverflowException*). Not the request — the process, taking every other in-flight request on that instance with it, plus whatever was buffered and unflushed. The same page notes that `[HandleProcessCorruptedStateExceptions]` has no effect here. So the reflexive answer — "I'd wrap it in a try/catch" — is not a partially-right answer, it is a wrong answer, and it is the single most common thing candidates say when this comes up.

**There is no frame count to memorise.** The budget is *stack bytes ÷ frame bytes*. The numerator comes from the executable header (`Thread`'s docs give the default as 1 megabyte and let you override it per-thread); the denominator comes from how many locals and arguments the JIT chose to spill for that method, on that platform, at that optimisation level. Anyone quoting you a depth figure has measured one build of one program. What is portable is the shape of the answer, not the number.

Three fixes, in ascending order of how seriously you are taking the problem:

1. **Move the frontier to the heap.** Replace recursion with an explicit `Stack<(int r, int c)>`. Same traversal, same complexity, but the stack now lives where memory is measured in gigabytes and where exhaustion throws `OutOfMemoryException` — which *is* catchable. This is the answer to give first; it costs nothing and it removes the class of failure rather than mitigating it.
2. **Probe before descending.** `RuntimeHelpers.EnsureSufficientExecutionStack()` throws `InsufficientExecutionStackException` when the remaining stack falls below the reserve the runtime keeps for raising an exception safely (Microsoft Learn, *RuntimeHelpers.EnsureSufficientExecutionStack*). Roslyn and `System.Text.Json` call it on their recursive paths. It converts process death into a caught exception for one call per level — the right tool when the recursion is genuinely natural and you only need a floor under it.
3. **Give the work its own stack.** `new Thread(work, maxStackSize: 64 * 1024 * 1024)` runs the recursion with a larger budget. Note the constraint that makes this a *supporting* answer rather than the answer: thread-pool threads take the process default and you cannot resize one, so this only works where you own the thread — which means an `async` request handler has to hand the work off to get it.

**Two other things about this specific implementation.** `Sink` destroys the caller's grid: after `NumIslands` returns, every `'1'` is a `'0'`. If the caller needed that grid, it is gone, and the method's signature promises nothing about it. And the recursion here is *four-way* — each frame can spawn four more — so the depth is bounded by the island's cell count rather than by its diameter, which is why a large blob is far worse than a long thin peninsula.

**And once the frontier moves to an explicit stack, the stack element becomes a struct — which has a copy rule you should be able to recite.** `Stack<(int r, int c)>` stores a `ValueTuple<int,int>`, and value types are copied on every assignment, argument pass and return: "By default, the system copies variable values on assignment, when passing an argument to a method, and when returning a method result" (Microsoft Learn, *Structure types*). For eight bytes that is free and nobody cares. The reason to know the rule anyway is that as soon as somebody replaces the tuple with a named type — and on a grid problem they will, because `cell.Row` reads better than `cell.Item1` — the copies stop being free and start being *wrong*:

```csharp
struct Cell                       // note: NOT readonly
{
    public int R, C;
    public int Index(int cols) => R * cols + C;   // compiler can't prove this doesn't mutate
    public void Bump() => R++;                    // ...because this one does
}

class Visitor
{
    private readonly Cell _origin = new Cell { R = 0, C = 0 };
    // Every `_origin.Index(cols)` in the hot loop copies the whole Cell first.
}
```

The mechanism is on Microsoft Learn, in *Structure types*, and it is worth quoting exactly because it is the sentence nobody has read: "a `readonly` member can call a non-`readonly` member. In that case, the compiler creates a copy of the structure instance and calls the non-`readonly` member on that copy. As a result, the original structure instance isn't modified." The same defensive copy is emitted whenever you *invoke* a member — a method or a property getter — that is not marked `readonly`, through a `readonly` field or an `in` parameter. Plain field reads are free; it is the invocation that triggers it, because the compiler has no way to know the member won't write and protects the original by copying it. In a flood fill that is one hidden copy per such call, and there is nothing in the source to look at.

The really unpleasant version is the correctness one, not the performance one. A mutating method called on a `readonly` field mutates the copy and then throws the copy away:

```csharp
private readonly Cell _origin = new Cell { R = 5 };
_origin.Bump();          // compiles fine; increments R on a temporary
// _origin.R is still 5
```

Two words fix all of it: **make the struct `readonly`.** "All other instance members except constructors are implicitly `readonly`" in a `readonly struct`, so there is nothing left for the compiler to defend against and the copies stop being emitted. `readonly record struct Cell(int R, int C)` gives you that plus value equality plus deconstruction plus a `ToString` in one line, and it is the right default for exactly the kind of small coordinate type these problems produce. If you cannot make the whole type `readonly`, mark the individual members `readonly` — the modifier is per-member too.

> 🌍 **In the real world**: a tile-rendering service represented map coordinates as a mutable `struct TileRef` with `X`, `Y`, `Zoom` and a handful of computed properties, held as a `readonly` field on a long-lived renderer and read inside the per-pixel loop. It was a struct specifically to avoid allocation, which it did. What nobody had noticed is that every computed-property read through that `readonly` field copied the struct first, so the "allocation-free" design was doing a hidden copy per property access, several times per pixel. The symptom was not a crash or a leak — it was that the service was inexplicably CPU-bound doing arithmetic that should have been trivial, and profiling showed time in methods that did nothing but return a field. Adding `readonly` to the struct declaration was a two-word diff that changed no behaviour and removed the copies, because the compiler no longer had anything to defend. The lesson that survives the specific case: **`struct` means "copied", and `readonly struct` is how you tell the compiler it is allowed to stop copying defensively.** Most engineers reach for a struct to avoid the heap and then never say the second half.

> 🌍 **In the real world**: an aerial-imagery pipeline counted contiguous regions in segmentation masks with exactly this flood fill, and had run on 512 × 512 tiles for two years. A customer with higher-resolution capture sent 4096 × 4096 tiles, and one of them was a lake — a single connected region of about ten million cells. The worker process did not throw, did not log, and did not write a crash dump: it vanished, the orchestrator restarted it, it picked the same message off the queue, and it vanished again. The incident presented as a poison-message loop, and the first hour went into the queue and the deserialiser, because that is where poison messages come from. The give-away was the exit code, which was the stack-overflow status rather than an unhandled-exception code — the one piece of evidence a stack overflow leaves behind, since by definition it cannot run your logging. Converting `Sink` to an explicit `Stack<(int, int)>` was a fifteen-line change. The lesson worth keeping is diagnostic rather than algorithmic: **a process that dies without a log line and without a dump is a stack overflow until proven otherwise**, because every other failure mode in .NET gets to say something on the way out.

### 21. Word Ladder

**Problem**: Transform `beginWord` to `endWord` one letter at a time; each intermediate must be in `wordList`. Min steps?

**Optimal**: BFS over words; neighbors = words differing by one letter.

```csharp
public int LadderLength(string begin, string end, IList<string> wordList)
{
    var dict = new HashSet<string>(wordList);
    if (!dict.Contains(end)) return 0;
    var queue = new Queue<(string word, int level)>();
    queue.Enqueue((begin, 1));
    var visited = new HashSet<string> { begin };
    while (queue.Count > 0)
    {
        var (word, level) = queue.Dequeue();
        if (word == end) return level;
        var chars = word.ToCharArray();
        for (int i = 0; i < chars.Length; i++)
        {
            var orig = chars[i];
            for (char c = 'a'; c <= 'z'; c++)
            {
                if (c == orig) continue;
                chars[i] = c;
                var next = new string(chars);
                if (dict.Contains(next) && visited.Add(next))
                    queue.Enqueue((next, level + 1));
            }
            chars[i] = orig;
        }
    }
    return 0;
}
```

**Complexity**: O(L² × N) time where L = word length, N = word count.

**Insight**: BFS for shortest path in unweighted graph. Bidirectional BFS halves the search.

**Count the strings.** For every word dequeued, the inner loops build 25 × L candidates, each one a `new string(chars)`, and hand each to `dict.Contains`. The overwhelming majority miss — a five-letter word has 125 candidates and typically a handful of real neighbours — so the code allocates roughly 25 × L strings per word to keep a handful. Every one of the rest is garbage before the next loop iteration. The complexity is right and the constant is a disgrace, and "the constant is a disgrace" is a legitimate senior observation about an O-optimal solution.

.NET 9 removed the need for them. `HashSet<T>.GetAlternateLookup<TAlternate>()` returns a view that can be probed with a `TAlternate` instead of a `T`, provided the set's comparer implements `IAlternateEqualityComparer<TAlternate, T>` — and the ordinal string comparers do (`public class OrdinalComparer : StringComparer, IAlternateEqualityComparer<ReadOnlySpan<char>, string?>` — dotnet/runtime, `StringComparer.cs`). So the probe can be a span over the scratch buffer, and a string gets materialised only on a hit:

```csharp
// before — one string per candidate, ~25 × L per word, nearly all discarded
chars[i] = c;
var next = new string(chars);
if (dict.Contains(next) && visited.Add(next))
    queue.Enqueue((next, level + 1));

// after (.NET 9+) — probe with a span; allocate only for a real neighbour
var dict   = new HashSet<string>(wordList, StringComparer.Ordinal);
var lookup = dict.GetAlternateLookup<ReadOnlySpan<char>>();   // throws if the comparer can't
...
chars[i] = c;
if (lookup.Contains(chars))              // chars is char[]; converts to ReadOnlySpan<char>
{
    var next = new string(chars);        // one string, and it is a genuine neighbour
    if (visited.Add(next)) queue.Enqueue((next, level + 1));
}
```

Two details to have ready. Pass `StringComparer.Ordinal` explicitly rather than relying on the default — it makes the requirement visible at the declaration, and `GetAlternateLookup` throws `InvalidOperationException` when "the set's comparer is not compatible with `TAlternate`" (Microsoft Learn, *HashSet&lt;T&gt;.GetAlternateLookup*), which is a startup failure you would rather read at the line that caused it. And `visited` still needs a real `string` to store, so the saving is entirely on the miss path — which is the point, because the miss path is nearly all of it.

Version-gate this carefully if it comes up: the alternate-lookup APIs are **.NET 9**, and they lean on the C# 13 `allows ref struct` constraint to let `TAlternate` be a `ReadOnlySpan<char>` at all. On .NET 8 and earlier there is no safe built-in way to probe a `HashSet<string>` with a span, and the honest answer is that you either eat the allocation or hand-roll a keyed set — not that you use a package.

> 🌍 **In the real world**: an address-normalisation service did one-edit-distance lookups against a gazetteer with this exact generate-and-test loop, at a few thousand requests a second. It met its latency SLO comfortably; what it did not meet was its memory budget, and it was restarted on an OOM roughly weekly. The allocations were not leaking — every candidate string was collected promptly — but the *rate* meant the GC was running continuously, and under Server GC the heap simply sat at whatever the collector had not got round to yet. The team spent two sprints hunting a leak that did not exist, because the symptom of a very high allocation rate and the symptom of a leak are both "memory goes up". The distinguishing evidence is Gen 2 size and survival rate: a leak grows Gen 2, a churn problem grows Gen 0 traffic while Gen 2 stays flat. Moving the probe to a span-keyed lookup cut allocation to the words actually found. The transferable diagnostic: **before you look for a leak, check whether anything is actually surviving.**

---

## Dynamic programming

### 22. Climbing Stairs

**Problem**: n stairs, take 1 or 2 at a time. Number of ways?

```csharp
public int ClimbStairs(int n)
{
    if (n <= 2) return n;
    int prev = 1, curr = 2;
    for (int i = 3; i <= n; i++) (prev, curr) = (curr, prev + curr);
    return curr;
}
```

**Complexity**: O(n) time, O(1) space.

**Insight**: Fibonacci with different base.

**This returns a wrong answer from `n = 46` and never says so.** `ClimbStairs(n)` is `Fib(n+1)`, so `ClimbStairs(45)` is `1,836,311,903` and fits an `int`; `ClimbStairs(46)` should be `2,971,215,073`, which does not, and the unchecked `prev + curr` wraps to a negative number that is returned as a count of ways. Same mechanism as the multiplication in [Container With Most Water](#5-container-with-most-water); the full treatment of overflow in counting recurrences, including why `long` only buys you to `Fib(92)` and when to switch to `BigInteger` or modular arithmetic, is in [Dynamic Programming](./06-dynamic-programming.md#dp-fundamentals--overlapping-subproblems--optimal-substructure).

The bit worth adding here is what to *say*. "I'd make it `long`" is a fix. "The output of a counting DP grows exponentially in n while the accumulator is fixed-width, so the correct question is what range of n this must support and whether the caller wants a number or a modulus" is the answer that gets the follow-up you want. Then ask it: an interviewer who says "n is at most 40" has just told you `int` is fine and you have shown you knew to check.

### 23. House Robber

**Problem**: Loot from houses; can't rob adjacent. Max?

```csharp
public int Rob(int[] nums)
{
    int prev2 = 0, prev1 = 0;
    foreach (var n in nums)
    {
        var curr = Math.Max(prev1, prev2 + n);
        prev2 = prev1;
        prev1 = curr;
    }
    return prev1;
}
```

**Complexity**: O(n) time, O(1) space.

**Insight**: at each house, max of (skip = prev1) or (rob = prev2 + current).

### 24. Longest Increasing Subsequence

**Problem**: LIS length.

**O(n log n) solution**:
```csharp
public int LengthOfLis(int[] nums)
{
    var tails = new List<int>();
    foreach (var x in nums)
    {
        int idx = tails.BinarySearch(x);
        if (idx < 0) idx = ~idx;
        if (idx == tails.Count) tails.Add(x);
        else tails[idx] = x;
    }
    return tails.Count;
}
```

**Complexity**: O(n log n) time, O(n) space.

**Insight**: maintain `tails[k]` = smallest tail of any increasing subsequence of length k+1. Binary search inserts.

**`tails` is not the LIS.** It is a list of *lengths*, indexed by length, whose contents are the best-known tail for each. Its final contents are frequently not any subsequence of the input at all. This is the first follow-up in a large fraction of LIS interviews — "great, now print the subsequence" — and the answer is that you have to record a predecessor index per element while you go and walk it back at the end; the `tails` array alone cannot reconstruct it.

**`List<T>.BinarySearch` has a documented caveat that this code depends on not applying.** "If the `List<T>` contains more than one element with the same value, the method returns only one of the occurrences, and it might return any one of the occurrences, not necessarily the first one" (Microsoft Learn, *List&lt;T&gt;.BinarySearch*). It is a plain binary search, not a lower bound. Here that is safe, because `tails` is strictly increasing by construction and so cannot contain duplicates — but say the sentence, because it is the reason the code is correct rather than an accident of it.

That invariant is also the switch between the two variants of the problem, and it is a single character:

| Wanted | Search semantics | Effect on a value already present |
|---|---|---|
| **Strictly** increasing (this code) | lower bound — replace the first element `>= x` | `idx >= 0`, `tails[idx] = x` is a no-op; length does not grow |
| **Non-decreasing** (ties allowed) | upper bound — replace the first element `> x` | must *append* past the run of equals, so the length does grow |

`BinarySearch` gives you neither bound reliably in the presence of duplicates; the strict version is correct only because duplicates cannot occur. If a follow-up asks for the non-decreasing variant, hand-write the bound rather than trying to patch the return value of `BinarySearch` — that patch is where this problem's bugs live.

### 25. Edit Distance

Already covered in [Dynamic Programming](./06-dynamic-programming.md#edit-distance-levenshtein) — Levenshtein 2D DP, O(m × n).

### 26. Word Break

Given a string and a dictionary; can it be segmented?

```csharp
public bool WordBreak(string s, IList<string> wordDict)
{
    var set = new HashSet<string>(wordDict);
    var dp = new bool[s.Length + 1];
    dp[0] = true;
    for (int i = 1; i <= s.Length; i++)
        for (int j = 0; j < i; j++)
            if (dp[j] && set.Contains(s[j..i])) { dp[i] = true; break; }
    return dp[s.Length];
}
```

**Complexity**: O(n²) time (n³ if you count substring), O(n) space.

**Insight**: `dp[i]` = can segment first i chars. Transition: try every split point.

**"n³ if you count substring" deserves more than a parenthesis, because in .NET it is also n² allocations.** `s[j..i]` is a range indexer on a string, and it compiles to `s.Substring(j, i - j)` — a fresh heap string, copied character by character, on every iteration of the inner loop. For an n-character input that is on the order of n²/2 strings created solely to be hashed once and dropped. The asymptotic cost is the copy; the operational cost is the garbage.

Both go away with the same .NET 9 alternate lookup used in [Word Ladder](#21-word-ladder), because the substring never has to exist:

```csharp
public bool WordBreak(string s, IList<string> wordDict)
{
    var set    = new HashSet<string>(wordDict, StringComparer.Ordinal);
    var lookup = set.GetAlternateLookup<ReadOnlySpan<char>>();     // .NET 9+
    int maxWord = 0;
    foreach (var w in wordDict) maxWord = Math.Max(maxWord, w.Length);

    var dp = new bool[s.Length + 1];
    dp[0] = true;
    for (int i = 1; i <= s.Length; i++)
        for (int j = Math.Max(0, i - maxWord); j < i; j++)          // no split can be longer
            if (dp[j] && lookup.Contains(s.AsSpan(j, i - j))) { dp[i] = true; break; }
    return dp[s.Length];
}
```

Two independent improvements, worth separating when you present them. The `maxWord` bound is an algorithmic win available on every runtime — it caps the inner loop at the longest dictionary word rather than at `i`, which on a realistic dictionary is the difference between O(n²) and O(n × maxWord). The span lookup is a constant-factor win available only on .NET 9. Offer the first one first: it needs no version gate and it is the one that changes the complexity.

`s.AsSpan(j, i - j)` also does no bounds arithmetic you have not already done — `AsSpan(start, length)` slices without copying, and the span cannot outlive the string because `s` is rooted for the duration of the call.

---

## Backtracking

### 27. Permutations

**Problem**: All permutations of an array.

```csharp
public IList<IList<int>> Permute(int[] nums)
{
    var result = new List<IList<int>>();
    Backtrack(nums, new List<int>(), new bool[nums.Length], result);
    return result;
}

private void Backtrack(int[] nums, List<int> path, bool[] used, IList<IList<int>> result)
{
    if (path.Count == nums.Length) { result.Add(new List<int>(path)); return; }
    for (int i = 0; i < nums.Length; i++)
    {
        if (used[i]) continue;
        used[i] = true;
        path.Add(nums[i]);
        Backtrack(nums, path, used, result);
        path.RemoveAt(path.Count - 1);
        used[i] = false;
    }
}
```

**Complexity**: O(n × n!) time, O(n) recursion depth.

**Insight**: standard backtracking: choose, recurse, unchoose.

**"O(n) recursion depth" hides where the memory actually goes.** The recursion is shallow — n frames. What is not shallow is `result`: `new List<int>(path)` allocates a fresh list per permutation, and there are n! of them. At n = 12 that is 479 million lists before you have returned anything, and the process dies of memory long before it dies of time. The complexity notation is telling the truth and telling you nothing, because the dominant resource is the *output*, not the work.

That reframes the follow-up entirely. "Make it faster" is not the question; "don't materialise it" is. Returning `IEnumerable<IList<int>>` from an iterator lets the caller consume permutations one at a time and stop early, at which point the memory is O(n) rather than O(n × n!) — and for the overwhelming majority of real uses ("find the first arrangement that satisfies X") early exit is the entire algorithm. Any backtracking problem whose result set is exponential should be asked this question before it is optimised.

> 🌍 **In the real world**: a logistics tool had a "show me every valid combination of carrier, service level and packaging" screen, implemented as backtracking into a `List<List<Option>>` and then paged in the UI. It was built against a customer with three carriers. A customer onboarded with eleven, plus more service levels, and the endpoint stopped returning — not slowly, but by taking the pod's memory limit to the ceiling and getting OOM-killed, repeatedly, which read to the platform team as a memory leak in an unrelated deployment on the same node. The generator was producing the complete result set in order to return the first fifty rows. Converting it to an iterator with `yield return` and letting the pager stop after fifty made the endpoint faster than it had ever been on three carriers, because it now did roughly fifty units of work instead of all of them. The general shape: **when the output is exponential in the input, materialising it is the bug, and the fix is laziness rather than speed.**

### 28. N-Queens

**Problem**: Place N queens on N×N board so none attack each other.

```csharp
public IList<IList<string>> SolveNQueens(int n)
{
    var result = new List<IList<string>>();
    var queens = new int[n];        // queens[r] = column of queen in row r
    Place(0, n, queens, result);
    return result;
}

private void Place(int row, int n, int[] queens, IList<IList<string>> result)
{
    if (row == n) { result.Add(BuildBoard(queens, n)); return; }
    for (int col = 0; col < n; col++)
    {
        if (IsSafe(queens, row, col))
        {
            queens[row] = col;
            Place(row + 1, n, queens, result);
        }
    }
}

private bool IsSafe(int[] queens, int row, int col)
{
    for (int r = 0; r < row; r++)
        if (queens[r] == col || Math.Abs(queens[r] - col) == row - r)
            return false;
    return true;
}

private List<string> BuildBoard(int[] queens, int n)
{
    var board = new List<string>();
    for (int r = 0; r < n; r++)
    {
        var sb = new char[n];
        Array.Fill(sb, '.');
        sb[queens[r]] = 'Q';
        board.Add(new string(sb));
    }
    return board;
}
```

**Complexity**: O(n!) time worst case (with pruning, much better).

**Insight**: backtracking with constraint propagation. Bitmask version is faster (track attacked columns and diagonals as bitmasks).

**First, notice what this code does *not* do — and that it is right not to.** There is no "unchoose" step. `queens[row] = col` is written and never cleared, which contradicts the choose/recurse/unchoose mantra from [Permutations](#27-permutations) and is nevertheless correct, because `IsSafe` only ever reads `queens[r]` for `r < row`. The stale entries past `row` are unreachable by construction. That is a real invariant carried in someone's head rather than in the code, and it is exactly the kind of thing that breaks when a later change makes `IsSafe` scan the whole array. Saying "the array is only meaningful up to `row`, so there is nothing to undo" out loud is worth more than adding a redundant reset.

**Second, `IsSafe` is O(row), so the code contradicts the answer in [Drill 13](#drill-13--backtracking--n-queens).** The drill's O(1) check needs the three occupancy sets it describes, and the honest reading of the code above is "O(n) safety check, O(n²) work per placed row." Both versions are worth having; know which one you wrote.

The bitmask form collapses the three sets into three integers and the safety test into one AND. It is compact enough to write on a whiteboard and it is the version that gets asked about:

```csharp
// cols / diag1 / diag2 are occupancy bitmasks over columns for the CURRENT row.
// Shifting them on the way down is what makes the diagonals track the row.
private static int Solve(int n, int row, int cols, int d1, int d2)
{
    if (row == n) return 1;
    int full  = (1 << n) - 1;
    int avail = full & ~(cols | d1 | d2);     // 1 bits = columns still legal
    int count = 0;
    while (avail != 0)
    {
        int bit = avail & -avail;             // lowest set bit: the next candidate column
        avail -= bit;                         // ...and remove it from the candidates
        count += Solve(n, row + 1, cols | bit, (d1 | bit) << 1, (d2 | bit) >> 1);
    }
    return count;
}
```

Three things to be able to explain, because each is a likely probe. `avail & -avail` isolates the lowest set bit — two's complement negation flips every bit above the lowest one, so the AND leaves only that bit; `System.Numerics.BitOperations.TrailingZeroCount` (.NET Core 3.0+) turns it into a column index if you need one, and `int.TrailingZeroCount` is the generic-math spelling of the same thing (.NET 7+). The `<< 1` and `>> 1` are the whole trick: a queen's diagonal influence moves one column per row, so shifting the mask as you descend keeps "attacked diagonals" expressed in the current row's coordinates and needs no `row ± col` arithmetic. And this version counts solutions rather than building boards — for `n = 8` it returns 92, the known answer, which is how you sanity-check a bitmask rewrite you just did under pressure.

**Third, `BuildBoard` allocates two objects per row per solution.** `new char[n]` then `new string(sb)` — the array exists only to be copied into the string and dropped. `string.Create` writes straight into the string's own buffer:

```csharp
// before: char[] + string, per row, per solution
var sb = new char[n];
Array.Fill(sb, '.');
sb[queens[r]] = 'Q';
board.Add(new string(sb));

// after: one string, no intermediate array
board.Add(string.Create(n, queens[r], static (span, col) =>
{
    span.Fill('.');
    span[col] = 'Q';
}));
```

`string.Create<TState>(int length, TState state, SpanAction<char, TState> action)` hands your callback a mutable `Span<char>` over the not-yet-frozen string — the one sanctioned way to build a string in place. Note the `static` on the lambda: it forces the compiler to reject any accidental capture, which is what keeps this allocation-free rather than merely allocation-*looking*-free, and it is a C# 9 feature worth using habitually on any lambda that is meant to be stateless.

Whether this matters is a judgement call and you should say so: N-Queens returns 92 boards at `n = 8`, so the saving is nothing. The reason to know it is that the identical shape — build a fixed-length string from a small piece of state — is everywhere in real code, in cache keys, correlation ids, and formatted identifiers, on paths that run millions of times.

> 🌍 **In the real world**: a distributed cache sat in front of a read-heavy API, and every lookup built its key with `$"{tenant}:{entity}:{id}:v3"`. Worth knowing what that compiles to, because it is not one thing: Roslyn lowers a short all-`string` interpolation like `$"{a}:{b}"` to a `string.Concat` call, and lowers this one — more parts, and an `int` among them — to a `DefaultInterpolatedStringHandler` with `AppendLiteral`/`AppendFormatted` calls and a final `ToStringAndClear`. Either way there is a fresh string per call, and it runs on the cache *hit* path, which is to say on nearly every request. The service was not slow; it was allocating at a rate that kept Gen 0 collections constant, and the team had spent a sprint tuning GC configuration before anyone counted the strings. Rewriting the hot key builder with `string.Create` and a struct of state, so the characters are written once into the final string's buffer, removed the intermediate handler work; capping it off, the keys for the hottest tenants were built once and cached, which removed the rest. The generalisable observation is about *where* to look: the code that allocates the most in a web service is rarely the code doing the interesting work, it is the small formatting helper on the path every request takes. String building is the single most common thing that turns out to be the top frame in an allocation profile, and almost nobody guesses it before they look.

---

## Concurrency

### 29. Producer-Consumer with `Channel<T>`

**Problem**: Coordinate N producers and M consumers safely.

```csharp
public async Task RunPipeline(int producers, int consumers)
{
    var channel = Channel.CreateBounded<int>(new BoundedChannelOptions(capacity: 100)
    {
        FullMode = BoundedChannelFullMode.Wait
    });

    // Producers
    var prodTasks = Enumerable.Range(0, producers).Select(p => Task.Run(async () =>
    {
        for (int i = 0; i < 1000; i++)
            await channel.Writer.WriteAsync(p * 1000 + i);
    })).ToArray();

    // Wait for all producers, then complete the channel
    _ = Task.WhenAll(prodTasks).ContinueWith(_ => channel.Writer.Complete());

    // Consumers
    var consTasks = Enumerable.Range(0, consumers).Select(c => Task.Run(async () =>
    {
        await foreach (var item in channel.Reader.ReadAllAsync())
            Process(item);
    })).ToArray();

    await Task.WhenAll(consTasks);
}
```

**Complexity**: O(items / parallelism) wall time.

**Insight**: `Channel<T>` is the modern .NET primitive for producer-consumer. Bounded mode provides backpressure naturally.

**That code has a bug, and it is one worth being able to name.** The line

```csharp
_ = Task.WhenAll(prodTasks).ContinueWith(_ => channel.Writer.Complete());
```

reads like plumbing and behaves like a swallow. A `ContinueWith` with no `TaskContinuationOptions` runs on **any** completion — faulted included. So if a producer throws, the continuation still completes the channel cleanly, every consumer's `await foreach` sees a normal end of stream and finishes, `await Task.WhenAll(consTasks)` returns successfully, and `RunPipeline` reports that it processed everything. The `_ =` discard then drops the last reference to the faulted task, so nothing ever observes the exception either. The pipeline ships a partial result and calls it a success.

`ChannelWriter<T>.Complete` takes the failure precisely so it can travel:

```csharp
public async Task RunPipeline(int producers, int consumers)
{
    var channel = Channel.CreateBounded<int>(new BoundedChannelOptions(capacity: 100)
    {
        FullMode = BoundedChannelFullMode.Wait
    });

    // Consumers start FIRST. With a bounded channel they have to: producers block
    // once 100 items are queued, so if nothing is draining, nothing ever completes.
    var consTasks = Enumerable.Range(0, consumers).Select(_ => Task.Run(async () =>
    {
        await foreach (var item in channel.Reader.ReadAllAsync())
            Process(item);
    })).ToArray();

    var prodTasks = Enumerable.Range(0, producers).Select(p => Task.Run(async () =>
    {
        for (int i = 0; i < 1000; i++)
            await channel.Writer.WriteAsync(p * 1000 + i);
    })).ToArray();

    try
    {
        await Task.WhenAll(prodTasks);
        channel.Writer.Complete();          // normal end of stream
    }
    catch (Exception ex)
    {
        channel.Writer.Complete(ex);        // consumers' await foreach rethrows this
    }

    await Task.WhenAll(consTasks);          // the producer fault surfaces here
}
```

`Complete(Exception? error = default)` throws `InvalidOperationException` if "the channel has already been marked as complete" (Microsoft Learn, *ChannelWriter&lt;T&gt;.Complete*), so wherever more than one path can finish the writer, use `TryComplete`, which returns `bool`. And `Task.WhenAll` surfaces only the *first* exception when awaited; if you need all of them, catch and read `task.Exception` off the `WhenAll` task.

**Consumer ordering is a correctness constraint, not a style choice.** Drill 8 below states the coordination as `await Task.WhenAll(producers); Complete(); await Task.WhenAll(consumers);` — with an **unbounded** channel that is fine, and with the bounded one above it deadlocks the moment total items exceed the capacity: producers park in `WriteAsync`, `WhenAll` never returns, `Complete` is never reached, and no consumer has been started to drain anything. The whole point of a bounded channel is that a producer can block, which means a consumer must already be running.

**The closure trap next door.** The producer lambdas capture `p` — a *lambda parameter*, freshly bound per invocation — so they are correct. Write the same fan-out with an index loop and it is not:

```csharp
// Broken: `i` is ONE variable that the loop mutates. Tasks may all observe 3.
var tasks = new List<Task>();
for (int i = 0; i < 3; i++)
    tasks.Add(Task.Run(() => Publish(shards[i])));      // and shards[3] throws

// Fixed: a fresh variable per iteration is what the closure captures.
for (int i = 0; i < 3; i++)
{
    int shard = i;
    tasks.Add(Task.Run(() => Publish(shards[shard])));
}
```

C# 5 scoped the `foreach` iteration variable to the iteration, which is why `foreach` has been safe here for over a decade (Microsoft Learn, breaking-change note *foreach iterator variable is now scoped within the iteration*). `for` was never changed and never will be, because its variable genuinely is one variable that the loop mutates — that is what `for` means. There is no compiler warning. It does not reproduce under a debugger, and it does not reproduce with three fast items, because whether the loop finishes before the first task body runs is a scheduling race.

> 🌍 **In the real world**: a nightly reconciliation job fanned out per-region work with `for (int r = 0; r < regions.Count; r++) tasks.Add(Task.Run(() => Reconcile(regions[r])));` and threw `ArgumentOutOfRangeException` about one night in five, always naming an index one past the end. It was filed as a flaky infrastructure issue and retried. What made it survive three years of code review is that it is *usually* right: with slow task startup the loop wins the race and every closure reads its intended value, so the code passes review, passes tests, and passes most nights. It became reproducible only when the box got more cores. The fix is three characters of indentation; the interesting part is the failure signature, because "throws on the boundary value, intermittently, more often on faster hardware" is the fingerprint of a captured loop variable and almost nothing else.

### 30. Parallel Matrix Multiplication

**Problem**: Multiply two n×n matrices in parallel.

```csharp
public double[,] MultiplyParallel(double[,] a, double[,] b)
{
    int n = a.GetLength(0);
    var c = new double[n, n];
    Parallel.For(0, n, i =>
    {
        for (int j = 0; j < n; j++)
        {
            double sum = 0;
            for (int k = 0; k < n; k++) sum += a[i, k] * b[k, j];
            c[i, j] = sum;
        }
    });
    return c;
}
```

**Complexity**: O(n³ / P) time where P is parallelism, O(n²) space.

**Insight**: outer-loop parallelism is safe (each thread writes its own row). For deeper speedup: SIMD via `Vector<double>`, or block multiplication for cache locality.

**The bottleneck is the inner loop, and parallelism does not touch it.** `double[,]` is stored row-major — one contiguous block, rows laid end to end. The inner loop reads `b[k, j]` for consecutive `k` at fixed `j`, so each read is `n` doubles further along, and no two consecutive reads share a cache line:

```
double[,] b with n = 4 — one contiguous block, row-major:

  memory │ b00 b01 b02 b03 │ b10 b11 b12 b13 │ b20 b21 b22 b23 │ b30 b31 b32 b33 │
          └───── row 0 ────┘ └───── row 1 ────┘ └───── row 2 ────┘ └──── row 3 ────┘

  b[k,j], fixed j, k = 0..3      ▲                 ▲                 ▲            ▲
  (what the inner loop does)     └── stride n ─────┴── stride n ─────┴── stride n ┘
                                 one cache line touched per read, 7 of 8 doubles wasted

  b[k,j], fixed k, j = 0..3      ►─►─►─►
  (what you want it to do)       four doubles, one cache line, prefetcher happy
```

`Parallel.For` multiplies throughput by the core count and leaves that intact — you are now missing cache on every core at once. Reordering the loops to `i`, `k`, `j` fixes it without changing a single arithmetic operation:

```csharp
// before: c[i,j] accumulates in a register, but b[k,j] strides by a whole row
for (int j = 0; j < n; j++)
{
    double sum = 0;
    for (int k = 0; k < n; k++) sum += a[i, k] * b[k, j];
    c[i, j] = sum;
}

// after: a[i,k] is invariant in the inner loop; b[k,j] and c[i,j] both walk forward
for (int k = 0; k < n; k++)
{
    double aik = a[i, k];
    for (int j = 0; j < n; j++) c[i, j] += aik * b[k, j];
}
```

Both are O(n³) and an interviewer reading only the complexity sees no difference — which is exactly why this is asked. Do not quote a speedup factor at them: it depends on `n`, on cache size, and on whether `n` is an unlucky multiple of the line size (a stride that aliases every row onto the same cache set is far worse than one that does not). Say "I'd measure it", and know what the measurement would look like — see the benchmark skeleton in [Common pitfalls](#common-pitfalls).

**Two more things about that `Parallel.For`.** Exceptions from the body do not propagate as themselves: `Parallel.For` collects them and throws `AggregateException` — "the exception that contains all the individual exceptions thrown on all threads" (Microsoft Learn, *Parallel.For*) — so a `catch (DivideByZeroException)` around the call catches nothing. And the write pattern is safe only because each `i` owns an entire row of `c`. Parallelise the `j` dimension instead and adjacent threads write adjacent doubles in the same cache line; every write invalidates the other cores' copies of that line, and you pay coherency traffic for a result that is still perfectly correct. That is **false sharing**, and the fact that it produces right answers slowly is what makes it hard to find.

If it goes further: `Vector<double>` (`System.Numerics`) vectorises the inner loop, and `Vector<T>.Count` is a runtime property, not a constant — it depends on the widest SIMD register the JIT decided to target on that machine, which is why you write the loop against `Vector<double>.Count` and a scalar tail rather than assuming four.

---

## Common pitfalls

1. **Brute force first; ask if optimization is wanted.** Solving the optimal version when interviewer wanted to see thought process is missing the point.
2. **Skipping edge cases.** Empty input, single element, single character, n=0, n=1 — always discuss.
3. **Off-by-one bugs in sliding window.** When `right` is the inclusive end, window size = `right - left + 1`. Be deliberate.
4. **Two pointers without invariant.** Define what each pointer represents (e.g., "left = smallest index of viable window start"); this prevents drift.
5. **Recursion depth is a process risk, not an exception.** There is no ceiling to memorise — the budget is stack bytes ÷ frame bytes and both depend on your build. What is fixed is the consequence: `StackOverflowException` cannot be caught and the process is terminated (Microsoft Learn, *StackOverflowException*). Use iterative versions wherever depth is a function of input size; the three mitigations are under [Number of Islands](#20-number-of-islands).
6. **`Dictionary<,>` lookup with mutable struct keys.** If you mutate a key after insertion, lookups fail silently.
7. **Hash collisions assumed impossible.** `Dictionary<,>` is O(1) average; pathological keys can make it O(n). Validate that custom `GetHashCode` distributes well.
8. **Mistaking subset for subarray.** "Subset" allows non-contiguous; "subarray" / "substring" requires contiguous. Read the problem carefully.
9. **Greedy when DP is needed.** Coin change with arbitrary denominations: greedy fails. If you can construct a counterexample, greedy doesn't work.
10. **Solving the wrong problem.** Misreading "minimum" as "maximum"; "longest" as "shortest." Re-read the prompt; restate it back to the interviewer.
11. **No complexity analysis.** Stating Big-O for time AND space is expected — interviewers ask for both.
12. **Premature optimization on the whiteboard.** Get a correct solution first; then talk through how to optimize. Bug-free correct beats elegant-but-broken.
13. **`==` is not identity.** Cycle detection, `visited` sets and memo dictionaries all ask "is this the same object", and `==` in C# means whatever the *static* type says — reference equality for a plain class, member-wise equality for a `record`, whatever was written for a type with `operator ==`, and reference equality again if the variable is typed as `object`. When identity is the invariant, write `ReferenceEquals`, or build the dictionary with `ReferenceEqualityComparer.Instance`.
14. **Mutating a struct through a collection indexer.** `List<T>`'s indexer returns a **copy** for value types, so `list[i].Visited = true` does not compile and `var s = list[i]; s.Visited = true;` compiles and does nothing. Arrays behave differently — `arr[i].Visited = true` works, because array indexing yields a variable rather than a value — and that inconsistency is where the bug lives, because the code looks identical. For in-place mutation of a `List<T>` of structs, `CollectionsMarshal.AsSpan(list)[i].Visited = true` gives you the `ref`; do not add or remove items while the span is alive.
15. **`ArrayPool<T>.Shared.Rent(n)` does not return an array of length `n`.** It "retrieves a buffer that is at least the requested length" and "may not be zero-initialized" (Microsoft Learn, *ArrayPool&lt;T&gt;.Rent*). Two bugs follow immediately: looping to `buffer.Length` instead of `n`, and assuming a freshly rented DP table is full of zeros when it is full of the previous caller's data. Slice it, and clear it if the algorithm needs zeros.
16. **"O(n) that allocates n times" and "O(n)" are the same complexity and not the same program.** Big-O counts operations and is silent about the GC. Two O(n) solutions can differ by every allocation in one of them, and on a server that difference is felt by requests that never touched your code. When you state a complexity, state the allocation shape next to it — "O(n) time, O(1) allocations" is a sentence that ends this conversation before it starts.
17. **Arithmetic is unchecked, so the wrong answer is silent.** "The default statement is `unchecked`" (Microsoft Learn, *The checked and unchecked statements*), so a product or a running total that exceeds `int.MaxValue` truncates rather than throwing. It bites in three places on this page: areas ([Container With Most Water](#5-container-with-most-water)), counting recurrences ([Climbing Stairs](#22-climbing-stairs)), and any `sum +=` over user-sized data. Cast the *operand*, not the result. Constant expressions are checked at compile time, which is why the bug never appears in the example you tried by hand.
18. **A `struct` that is not `readonly` gets copied where you cannot see it.** Invoking a non-`readonly` member through a `readonly` field or an `in` parameter makes the compiler copy the whole struct first, and a mutating call on a `readonly` field mutates the discarded copy (Microsoft Learn, *Structure types*). Prefer `readonly record struct` for the small coordinate/pair types these problems produce — see [Number of Islands](#20-number-of-islands).
19. **The null-forgiving `!` is not a check.** It emits no IL and asserts nothing at runtime; it tells the compiler to stop reporting that it cannot prove something. If you cannot say in one sentence why the value is non-null, the `!` is a deferred `NullReferenceException`. Guard clauses (`ArgumentNullException.ThrowIfNull`) are for other people's code; annotations are only for your compiler.
20. **"How would you test this?" has a specific right answer, and it is not "unit tests".** The brute force you already wrote *is* the oracle. Generate random inputs, run both, assert they agree — the optimal solution's bugs are almost always in the pruning or the window bookkeeping, and those are precisely the cases a hand-written example set does not contain:

    ```csharp
    // The differential test. The point is the ORACLE, not the framework.
    [Fact] public void Optimal_agrees_with_brute_force()
    {
        var rng = new Random(20260818);               // seeded: a failure must be replayable
        for (int trial = 0; trial < 10_000; trial++)
        {
            int n = rng.Next(0, 40);                  // include 0 and 1 — that is the point
            var nums = new int[n];
            for (int i = 0; i < n; i++) nums[i] = rng.Next(-5, 6);   // small range => many ties
            Assert.Equal(BruteForce(nums), Optimal(nums));
        }
    }
    ```

    Three deliberate choices to be able to defend: the seed is fixed so a failure is reproducible rather than a story about CI; `n` starts at 0 so the empty and single-element cases are generated rather than remembered; and the value range is *narrow* so duplicates and ties occur constantly, because tie-handling is where these algorithms actually break. A property-based library (FsCheck, CsCheck) adds automatic shrinking to a minimal failing input, which is the part that turns a failing seed into a bug you can read. Saying "I'd diff it against the brute force over randomised small inputs, and shrink the counterexample" is a complete, senior answer to a question most candidates answer with "I'd add some unit tests."

    > 🌍 **In the real world**: a pricing engine replaced a straightforward O(n²) tier-matching loop with a sorted-array plus binary-search version, and the change went out with fourteen hand-written unit tests, all green, all derived from the tier tables the team had in front of them. It was wrong for inputs that landed exactly on a tier boundary when two tiers shared a threshold — a case that existed in one customer's configuration and in none of the fourteen tests, because nobody writes a test for a duplicate boundary they have never seen. It was caught six weeks later by a customer's finance team. Afterwards the old loop was not deleted; it was moved into the test project and kept as the oracle, and a differential test over randomised small tables with a deliberately tiny value range ran on every build. That test found two more discrepancies in the following year, both at ties. The durable idea is that **the brute force is an asset, not scaffolding** — it is the only executable specification you will ever have of what the fast version is supposed to do, and deleting it is throwing away the thing that can tell you the rewrite was wrong.

**And when you claim something is faster, show the shape of the measurement.** The rule this guide follows — no number without a source — is the same rule an interviewer applies to you. What you should be able to sketch is not a figure but a harness:

```csharp
[MemoryDiagnoser]                       // allocation columns, which is usually the point
public class WindowMaxBench
{
    [Params(1_000, 100_000)] public int N;   // the answer changes with size — show both
    [Params(8, 512)]         public int K;
    private int[] _data = [];

    [GlobalSetup] public void Setup()
    {
        var rng = new Random(N);             // SEEDED — see below
        _data = new int[N];
        for (int i = 0; i < N; i++) _data[i] = rng.Next();
    }

    [Benchmark(Baseline = true)] public int[] LinkedListDeque() => /* original */ null!;
    [Benchmark]                  public int[] RingBufferDeque() => /* rewrite  */ null!;
}
```

The parts that carry the credibility: a **baseline** so the result is a ratio rather than a number, `[Params]` across sizes so you find out where the answer flips, `[MemoryDiagnoser]` because on this class of rewrite the allocation column is often the whole story, and `[GlobalSetup]` so data generation is outside the measured region.

**And the seed is not a detail.** `[GlobalSetup]` is "executed only once per a benchmarked method after initialization of benchmark parameters" (BenchmarkDotNet docs, *Setup and Cleanup*) — *per benchmarked method*, not once for the run. Seed it from `Random.Shared` and the baseline and the candidate are measured on **different arrays**, so the ratio you report is partly a comparison of two datasets. Deriving the seed from the parameters, as above, gives every method the same input for a given `N` and makes the whole run replayable next month. This is the methodological point an interviewer is actually listening for: not "did you use BenchmarkDotNet" but "did the two things you compared see the same work?"

Saying "I'd run it under BenchmarkDotNet with a baseline, params across n, and a fixed seed so both arms see identical data" is a complete answer. Saying "it's about three times faster" without having run it is the answer that loses the room.

## Interview-ready summary

**Pattern recognition is the highest-leverage interview skill.** From the 30 problems above, the recurring patterns:

- **Hash map for O(1) lookup** — Two Sum, Group Anagrams, Clone Graph.
- **Sliding window** — Longest Substring Without Repeats, Sliding Window Maximum.
- **Two pointers** — Container With Most Water, Trapping Rain Water, Merge Sorted Lists.
- **Fast/slow pointers** — Detect Cycle, Find Middle.
- **Monotonic deque** — Sliding Window Maximum.
- **BFS for shortest path unweighted** — Word Ladder, Number of Islands (variant).
- **DFS / recursion with state** — Tree problems, backtracking.
- **Topological sort** — Course Schedule.
- **DP over indices** — Climbing Stairs, House Robber, LIS.
- **DP 2D** — Edit Distance, LCS, Knapsack.
- **Backtracking** — Permutations, N-Queens, Combinations.

**Communication patterns** (matter as much as code):
- Restate the problem in your words.
- Walk through an example by hand.
- Brute force, identify the bottleneck, propose optimization.
- Code the optimal solution with running commentary.
- State complexity (time + space).
- Discuss edge cases.
- Mention follow-up variants ("if memory was tighter, I'd use rolling arrays").

**Practice ratio**: spend 60% on these patterns, 30% on debugging your bugs (off-by-one, edge cases), 10% on niche algorithms (KMP, segment trees) — only the last makes sense if you've mastered the first 90%.

**The senior differentiator, in one paragraph.** Everything above is table stakes at any level. What is being scored differently for you is whether the solution survives contact with a runtime: which line allocates and how often, what the collection does when the key type changes underneath it, what happens at a depth or a size the sample input never reached, and how a failure in one task reaches the caller. The pattern is what you say in minute four. The four questions below are what you should be volunteering in minute twenty, *before* being asked — because a candidate who raises them unprompted has clearly shipped something, and a candidate who only answers them when prompted has clearly read something.

| Ask yourself | The version of it an interviewer asks |
|---|---|
| What does this allocate, per element? | "Run this at a thousand requests a second. What does the GC see?" |
| Which equality/comparison is this leaning on? | "What if the node type became a `record`?" |
| What is unbounded here — depth, size, alphabet, batch? | "The customer sends ten million. Now what?" |
| Where does a failure surface? | "One worker throws. Who finds out?" |
| Can any of this arithmetic exceed its type? | "What's the largest n this is correct for?" |
| How would I know if it were wrong? | "How would you test this?" |

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.
### Drill 1 — Two pointers

> **Q**: What's the "two pointers" pattern and when does it apply?
>
> **A**: Two pointers (typically `left` and `right`) traverse a data structure with coordinated motion. Applies when (a) the data is sorted or can be sorted, (b) you're looking for pairs/triplets with a target property, (c) you can decide which pointer to advance based on the current relation. Common shapes: opposite ends moving toward middle (Container With Most Water), same-direction at different speeds (Floyd's cycle detection), fixed gap (window of size k).
>
> **Cross-Q**: Walk through 3Sum with two pointers.
>
> **A**: Sort the array. For each `i`, use two pointers `left = i+1`, `right = n-1` to find pairs that sum to `-nums[i]`. If `nums[i] + nums[left] + nums[right] == 0`: record triplet, advance both. If sum < 0: advance left (need bigger). If sum > 0: advance right (need smaller). Skip duplicates by advancing past equal values. O(n²) total.
>
> **Cross-Q²**: Why does two pointers fail on unsorted data?
>
> **A**: Because the decision "which pointer to advance" relies on the sorted invariant. On `[5, 1, 8, 3]` searching for sum 11: left=0 (5), right=3 (3), sum=8. Should advance left (need bigger)? No — array isn't sorted; advancing left could miss the 8 entirely. Without sortedness, no monotonic decision rule exists. Sort first (O(n log n)) then use two pointers (O(n)) — net O(n log n) beats brute O(n²).

### Drill 2 — Sliding window — fixed vs variable

> **Q**: What's the difference between fixed and variable sliding window?
>
> **A**: **Fixed window**: size k is known ("max sum of any subarray of size 3"). Slide one position at a time; maintain a running sum / state by adding the new element and removing the leaving one. **Variable window**: size depends on a constraint ("longest substring with at most 2 distinct chars"). Expand `right` while constraint holds; shrink `left` when violated.
>
> **Cross-Q**: Implement "longest substring with all unique chars."
>
> **A**: `var seen = new HashSet<char>(); int left = 0, max = 0; for (int right = 0; right < s.Length; right++) { while (!seen.Add(s[right])) seen.Remove(s[left++]); max = Math.Max(max, right - left + 1); } return max;`. Variable window: expand right; shrink left while duplicate exists.
>
> **Cross-Q²**: When does sliding window fail?
>
> **A**: When the constraint isn't *monotonic* in window size. Sliding window works when "if a window of size k satisfies the constraint, so does some smaller window" (or vice versa). For non-monotonic constraints (e.g., "longest window with exactly k distinct chars"), you may need two sliding windows (one for "≤ k" and one for "≤ k-1"; subtract).

### Drill 3 — Hash map for O(n) lookup

> **Q**: Two Sum — why does the hash map approach beat brute force?
>
> **A**: Brute force checks every pair: O(n²). Hash map insight: for each `nums[i]`, we need to know if `target - nums[i]` has been seen earlier. Hash map lookup is O(1) — turns "find the partner" from O(n) scan to O(1) lookup. Total: O(n) with O(n) space. The classic time-space trade-off.
>
> **Cross-Q**: Why iterate and store rather than precompute the whole map first?
>
> **A**: Edge case: target = 6, array = [3, 3]. If we precompute the map then look up, we'd find `target - 3 = 3` and return [0, 0] (same index). The "iterate and store" pattern ensures the complement was seen *earlier* (different index) — naturally avoids self-pairing.
>
> **Cross-Q²**: When does the hash approach *not* win?
>
> **A**: When duplicates are allowed and you need *all* pairs (not just one). Then you iterate the hash with all pairings — could be O(n²) pairs anyway. Also: when memory is tight; brute force is O(1) space, hash is O(n). For n = 10⁹ with strict memory constraints, two pointers on a sorted array (O(n log n) sort + O(n) two-pass) beats O(n) hash because no extra storage.

### Drill 4 — Floyd's cycle detection

> **Q**: Walk through Floyd's tortoise-and-hare for linked-list cycle detection.
>
> **A**: Two pointers: `slow` advances 1 step per iteration, `fast` advances 2. If there's no cycle, `fast` reaches null. If there's a cycle, `fast` eventually laps `slow` — they meet inside the cycle. O(n) time, O(1) space (vs hash-set approach which is O(n) time but O(n) space).
>
> **Cross-Q**: Why does fast catch slow?
>
> **A**: In a cycle of length k, fast gains 1 step per iteration relative to slow. Once both pointers are inside the cycle, the gap closes by 1 per iteration. Within k iterations after slow enters the cycle, they meet. The math: if slow is at position s, fast at 2s. In a cycle of length k starting at offset μ, slow enters at iteration μ. After m more iterations: slow at μ+m mod k, fast at 2(μ+m) mod k. They meet when 2(μ+m) ≡ μ+m (mod k), i.e., m ≡ -μ (mod k). Always solvable.
>
> **Cross-Q²**: How do you find the *start* of the cycle?
>
> **A**: After they meet, reset one pointer (say slow) to head. Advance both 1 step. They meet at the cycle start. Proof: slow traveled μ steps to enter the cycle and m more to meet; total μ+m. Fast traveled 2(μ+m). Difference = μ+m is a multiple of k (cycle length). So μ ≡ -m (mod k). Resetting slow to head and advancing μ steps puts it at the cycle start. Advancing the meeting-point pointer μ steps wraps around the cycle to the start. They converge there.

### Drill 5 — Reverse a linked list

> **Q**: Iterative vs recursive reverse — which do you prefer in production?
>
> **A**: Iterative. O(n) time, O(1) space, no stack risk. Recursive is O(n) stack, and in .NET running out of stack terminates the *process* — you cannot catch `StackOverflowException`, so there is no degraded mode to fall back to. Don't quote a depth number: the ceiling is stack bytes ÷ frame bytes and both are properties of the build. Iterative pattern: three pointers (`prev`, `curr`, `next`); reverse one link per iteration.
>
> **Cross-Q**: Write iterative reverse.
>
> **A**: `ListNode prev = null; ListNode curr = head; while (curr != null) { var next = curr.Next; curr.Next = prev; prev = curr; curr = next; } return prev;`. Five lines. The trick is saving `next` before overwriting `curr.Next`.
>
> **Cross-Q²**: Reverse k consecutive nodes — variation?
>
> **A**: Group into k-sized chunks, reverse each chunk in place, link the reversed chunks. Track the previous group's tail to splice. O(n) time, O(1) space. The off-by-one is in handling the last group (if < k nodes remain, leave them or reverse them — depends on the problem statement).

### Drill 6 — Merge intervals

> **Q**: Given a list of intervals, merge overlapping ones. Approach?
>
> **A**: Sort by start. Iterate; for each interval, if it overlaps with the last merged interval (start ≤ lastEnd), extend lastEnd to max(lastEnd, currentEnd); else push a new interval. O(n log n) for sort + O(n) for merge.
>
> **Cross-Q**: How do you detect overlap?
>
> **A**: Sorted by start ensures `current.start >= last.start`. Overlap when `current.start <= last.end`. (Touching intervals like [1,3] and [3,5] — depends on the problem; usually they're considered overlapping.) Update `last.end = max(last.end, current.end)` to handle nested intervals.
>
> **Cross-Q²**: Insert a new interval into a sorted list of disjoint intervals — O(n) or O(log n)?
>
> **A**: O(n) — even if you binary-search the position (O(log n)), inserting may require shifting elements (O(n)) or merging adjacent intervals (chain of merges, O(n) worst). Binary search finds the position; the merging logic is the bottleneck. For "add interval to sorted set with merging" use a TreeSet/SortedSet variant — O(log n) per insert with merge.

### Drill 7 — LRU cache

> **Q**: Design an LRU cache with O(1) get/put.
>
> **A**: `LinkedList<KeyValuePair<TKey, TValue>>` for ordering + `Dictionary<TKey, LinkedListNode<...>>` for lookup. Get: dict lookup → if found, move node to head, return value. Put: if key exists, update value, move to head. If at capacity, remove tail node from both list and dict; add new node at head.
>
> **Cross-Q**: Why a doubly-linked list specifically?
>
> **A**: To remove an arbitrary node in O(1). When we hit a key, we move that node from its current position to the head. Single-linked list requires O(n) to find the predecessor. Doubly-linked list has `prev` pointer — splice out in O(1), splice in at head in O(1).
>
> **Cross-Q²**: .NET has `MemoryCache` — does it use LRU?
>
> **A**: No — and be precise about which `MemoryCache`, because there are two types with that name (`Microsoft.Extensions.Caching.Memory.MemoryCache`, the modern one, and the older `System.Runtime.Caching.MemoryCache`). The modern one evicts on expiration, and on *size pressure* only if you set `SizeLimit` **and** every entry supplies a `Size` — without both it grows until something else stops it, which is its most-reported surprise. When it does compact, the documented policy in `MemoryCache.cs` is: remove expired entries, then bucket by `CacheItemPriority` (Low, then Normal, then High; `NeverRemove` is skipped), and only *within a bucket* sort by `LastAccessed` and drop the least recently used. So LRU is the tiebreaker, not the policy — a `High`-priority entry survives a thousand more-recently-used `Low` ones. For strict LRU, hand-roll the `LinkedList` + `Dictionary` pattern above, or take `BitFaster.Caching` (LRU/LFU). Production caches often go further still — TinyLFU or ARC — because pure LRU is trivially defeated by a single large scan.

### Drill 8 — Producer-consumer with `Channel<T>`

> **Q**: Implement producer-consumer using `Channel<T>` for backpressure.
>
> **A**: `var channel = Channel.CreateBounded<int>(new BoundedChannelOptions(100) { FullMode = BoundedChannelFullMode.Wait });`. Producer: `await channel.Writer.WriteAsync(item)` — blocks (awaits) when full. Consumer: `await foreach (var item in channel.Reader.ReadAllAsync()) Process(item);`. When producer finishes: `channel.Writer.Complete();` — consumer's foreach ends naturally.
>
> **Cross-Q**: Why `Channel<T>` over `BlockingCollection<T>`?
>
> **A**: First-class async. `BlockingCollection<T>.Take` blocks a thread (sync); `Channel<T>.Reader.ReadAsync` awaits (yields the thread). For async-heavy pipelines (web APIs, async I/O), `Channel<T>` avoids thread starvation. Also: better backpressure semantics, integration with `IAsyncEnumerable<T>`, modern .NET idiomatic pattern.
>
> **Cross-Q²**: Multiple producers + multiple consumers — same code?
>
> **A**: Yes. `Channel<T>` is multi-producer multi-consumer safe by default (the `SingleReader`/`SingleWriter` options are opt-in optimisations, not the default). Spawn N producer tasks all writing to `channel.Writer`; spawn M consumer tasks all reading from `channel.Reader`. **Start the consumers first, then the producers**, and only then `await Task.WhenAll(producers); channel.Writer.Complete(); await Task.WhenAll(consumers);`. The ordering is not style: on a *bounded* channel, `await Task.WhenAll(producers)` before any consumer exists deadlocks as soon as the item count exceeds the capacity — producers park in `WriteAsync` waiting for space, nothing drains, `Complete` is never reached. On an unbounded channel the naive ordering happens to work, which is exactly why the bug survives code review. Closing the writer signals all consumers' `foreach` to end; `Complete(ex)` makes them all rethrow instead, which is how a producer failure reaches the caller rather than being silently dropped.

### Drill 9 — Rate limiter — token bucket

> **Q**: Implement a token-bucket rate limiter.
>
> **A**: Bucket has capacity C (burst size) and refill rate R tokens/sec. Each request consumes 1 token; if bucket empty, request rejected (or queued). Refill on demand: `tokens = min(C, tokens + (now - lastRefill) * R)`. Implementation: `private double _tokens; private DateTime _lastRefill; public bool TryConsume() { Refill(); if (_tokens >= 1) { _tokens--; return true; } return false; } void Refill() { var now = DateTime.UtcNow; _tokens = Math.Min(C, _tokens + (now - _lastRefill).TotalSeconds * R); _lastRefill = now; }`. Thread-safe with `lock`.
>
> **Cross-Q**: Token bucket vs leaky bucket?
>
> **A**: Token bucket *allows bursts* up to capacity (saved-up tokens). Leaky bucket *smooths output* — fixed-rate drain regardless of input bursts. Token bucket is forgiving (sudden spikes after quiet period are fine); leaky bucket is strict (consistent rate). API rate limiters typically use token bucket (allow occasional bursts for retries, ramp-ups).
>
> **Cross-Q²**: .NET built-in for rate limiting?
>
> **A**: `System.Threading.RateLimiting` (.NET 7+). Provides `TokenBucketRateLimiter`, `SlidingWindowRateLimiter`, `ConcurrencyLimiter`, `FixedWindowRateLimiter`. ASP.NET Core has middleware to apply them per-endpoint. Use the built-ins; the hand-rolled version is for understanding (interview answer) or for distributed rate limiting (Redis-backed) where built-ins don't apply.

### Drill 10 — Top-K frequent

> **Q**: Top K most frequent elements in an array. Approach?
>
> **A**: Count frequencies with `Dictionary<int, int>` (O(n)). Then use a min-heap of size K, iterating the frequency map: push (frequency, element); if heap size > K, pop the minimum. O(n + m log K) where m = distinct elements. The heap holds top K.
>
> **Cross-Q**: When does bucket sort beat the heap?
>
> **A**: When frequencies are bounded. Bucket sort: `bucket[freq]` holds list of elements with that frequency. Iterate buckets from high to low, collect top K. O(n) total. For arrays where many elements have the same frequency, this beats O(n log K). For widely varying frequencies, the heap is simpler with comparable performance.
>
> **Cross-Q²**: Quickselect variant — O(n) for top K?
>
> **A**: Quickselect on the frequency-tuple array partitions to find the Kth largest frequency, then collects elements with frequency ≥ that. O(n) average, O(n²) worst. Combined with sorting just the top K group: O(n + K log K). For huge n and small K, both heap and quickselect are sub-second; pick based on simplicity of implementation.

### Drill 11 — Median from data stream

> **Q**: Maintain the running median of a data stream. Approach?
>
> **A**: Two heaps. Max-heap holds the smaller half; min-heap holds the larger half. Invariant: max-heap.size ∈ {min-heap.size, min-heap.size + 1}. New element goes to max-heap if ≤ max-heap.peek, else min-heap. Rebalance if sizes diverge by > 1. Median: if max-heap larger, its top; else average of both tops. O(log n) per insertion, O(1) per query.
>
> **Cross-Q**: Why not just keep a sorted list?
>
> **A**: Sorted list insertion is O(n) (shift elements). Two heaps give O(log n) — asymptotically better, and by a margin that matters long before the stream is large. Multiplying out the complexities for n = 10⁶ inserts: a sorted list is n²/2 ≈ 5×10¹¹ element moves worst case (n²/4 ≈ 2.5×10¹¹ if insertion positions are uniformly distributed), two heaps are n log₂n ≈ 2×10⁷ comparisons. That is an operation count derived from the formula, not a measurement — the constant factors differ (an array shift is a `memmove`, a heap sift is pointer-chasing plus comparisons), so quote it as "four to five orders of magnitude in operations" and offer to measure if they push.
>
> **Cross-Q²**: How to handle deletions / sliding window median?
>
> **A**: Hard, and the version of this answer you have read elsewhere is out of date. **.NET 9 added `PriorityQueue<TElement,TPriority>.Remove(element, out removed, out priority, comparer?)`** — but read what it does before offering it: "the method performs a linear-time scan of every element in the heap" and "in case of duplicate entries, what entry does get removed is non-deterministic and does not take priority into account" (Microsoft Learn, *PriorityQueue&lt;TElement,TPriority&gt;.Remove*). Microsoft's own note introducing it says it exists to *emulate* priority updates at O(n), for education and prototyping. So: the API exists, it is O(n), and saying "there's no Remove" is wrong while saying "there's a Remove so it's solved" is worse. Real options: (a) **lazy deletion** — mark elements dead in a side set and skip them on dequeue, the standard trick and what most Dijkstra implementations actually do; (b) **`SortedSet<T>`** (red-black tree) — O(log n) insert, delete and ordered navigation, at the cost of needing distinct elements or a tie-breaking comparer; (c) an **indexed heap** with a side dictionary from element to heap position, which is the only structure that gives genuine O(log n) decrease-key. Sliding-window median is an advanced problem; the sorted set is the expected interview answer.

### Drill 12 — Trie problems

> **Q**: When do you reach for a trie?
>
> **A**: Three signals. (1) **Prefix queries** — "all words starting with 'pre'". HashSet can't do prefix; trie does O(L + k). (2) **Many similar strings** — IP routing prefixes, dictionary autocomplete, URL routing — trie shares prefix nodes, saving memory. (3) **Pattern multi-search** — Aho-Corasick (trie + failure links) for searching many patterns at once.
>
> **Cross-Q**: Implement word-search problem (find words in a 2D grid).
>
> **A**: Build a trie of target words. DFS each grid cell; at each step, descend in the trie if the current character matches a child. On reaching a terminal node, record the word. Pruning: stop DFS if current trie node has no children. Without trie, you'd do M independent searches; trie shares the prefix exploration across all words.
>
> **Cross-Q²**: When does a trie lose to a HashSet?
>
> **A**: When you only need exact match. HashSet: O(1) lookup, simpler. Trie: O(L) lookup, more memory overhead for parent-child pointers. For "given a word, is it in the dictionary?" — HashSet wins on simplicity and speed. Trie wins when you'd otherwise iterate a sorted list with prefix matching.

### Drill 13 — Backtracking — N-queens

> **Q**: Walk through N-queens with backtracking.
>
> **A**: For each row r, try each column c. If `(r, c)` is safe (no queen in same column, no queen on either diagonal): place queen, recurse to row r+1, then unplace (backtrack). Base case: all rows placed → record solution. Pruning: O(N!) naive becomes much less with safety checks early.
>
> **Cross-Q**: How do you check "safe" in O(1)?
>
> **A**: Track three sets: `cols[col]`, `diag1[row + col]` (top-left to bottom-right), `diag2[row - col + N]` (top-right to bottom-left). Setting a queen: mark all three; check before placing. O(1) per check. Bitmask version: three integers as bitmasks, check via bit AND. Even faster.
>
> **Cross-Q²**: Sudoku — same pattern?
>
> **A**: Yes. Backtracking with constraint sets: `rows[r]`, `cols[c]`, `boxes[r/3 * 3 + c/3]` each hold "digits already in this row/column/box." For each empty cell, try digits 1-9; check none in the three constraint sets; place; recurse; backtrack. O(9^empty_cells) worst case; in practice, constraint propagation prunes massively.

### Drill 14 — String permutations

> **Q**: Generate all permutations of a string. Approach?
>
> **A**: Backtracking with swap. For each position i: swap s[i] with each s[j] (j ≥ i); recurse for position i+1; swap back. Base case: position == length → record permutation. O(n × n!) time, O(n) recursion depth.
>
> **Cross-Q**: How do you handle duplicates without duplicate output?
>
> **A**: Sort the string first. At each position, skip s[j] if s[j] == s[i] and j > i (already tried this value at position i). Alternative: collect into a Set to dedupe at the end (simpler but O(n!) memory). The "skip duplicate at same position" approach is O(n × distinct_permutations) — much less memory.
>
> **Cross-Q²**: Why backtracking with swap rather than choose-and-build?
>
> **A**: Memory. Choose-and-build (`used[]` array, append/remove from `path` list) needs extra memory for tracking. Swap version mutates the input in place — O(1) extra per call. For interview purity, choose-and-build is clearer. For tight memory, swap is preferred. Functionally equivalent.

### Drill 15 — Structuring a 30-min coding answer

> **Q**: I have 30 minutes and a coding problem. How do I structure the answer?
>
> **A**: 1) **Restate the problem in your words (1 min)** — confirm you understand. 2) **Work an example by hand (2 min)** — small N; reveal patterns. 3) **Brute force + complexity (2 min)** — state the obvious solution and its cost. 4) **Identify bottleneck, propose optimization (3 min)** — pattern recognition (hash for lookup, two pointers, DP, etc.). 5) **Code the optimal (15 min)** — talk while coding. 6) **Trace through example (3 min)** — verify correctness. 7) **Complexity analysis (2 min)** — time + space. 8) **Edge cases (2 min)** — empty, single element, all equal, max size.
>
> **Cross-Q**: What if I'm stuck at brute force, can't see the optimization?
>
> **A**: Stay calm and verbalize. "The brute force is O(n²) because [reason]. The bottleneck is [the inner loop / repeated computation]. If we could [do X in O(1)], we'd save the inner loop. [Sliding window / hash map / two pointers / DP] often achieves that here." Often the interviewer drops a hint when you verbalize the bottleneck — they want to see your thought process, not just a flash of brilliance.
>
> **Cross-Q²**: What if I finish early?
>
> **A**: (1) Verify with a second example (a tricky case). (2) Discuss complexity in detail. (3) Discuss edge cases explicitly. (4) Propose variants ("if memory were tight, I'd…" / "if input were sorted, I'd…"). (5) Discuss testing strategy. **Don't** start over-engineering — the interviewer might ask a follow-up; save time for it. Senior signal: own the time, narrate trade-offs, don't fill silence with code.

</details>
## Cheat Sheet

- **"O(1) extra space"** signal: in-place pointers; reverse-and-walk; bit manipulation.
- **"Find the missing/duplicate"**: XOR all elements (xor-pair-cancellation trick).
- **"Top K"**: min-heap of size K via `PriorityQueue<,>` — O(n log k) beats sort O(n log n) for k ≪ n.
- **"Anagram / character frequency"**: `int[26]` array if a-z, else `Dictionary<char,int>`.
- **"Cycle in linked list/graph"**: Floyd's tortoise-and-hare for lists; three-color DFS for graphs.
- **"Two sum / pair with property"**: hash map of complement seen so far.
- **"Subarray sum equals k"**: prefix sum + hash map of prefix occurrences.
- **"Sliding window with constraint"**: two-pointer + counter; shrink from left while invariant breaks.
- **"Tree path sum"**: DFS with running sum; pass to recursive call.
- **"Talk through brute force first"**: signals process; never silent-code the optimal.

**The .NET half of the cheat sheet** — the facts that turn a correct answer into a senior one:

- **`PriorityQueue<,>` is an array-backed *quaternary* min-heap**, and "does not guarantee first-in-first-out semantics for elements of equal priority" (Microsoft Learn). If ties must break deterministically — Dijkstra on a graph with equal weights, or a test that asserts on output order — make the priority a tuple with a sequence number.
- **`Dictionary<,>` chains, it does not probe**, and its randomized-hash defence applies only to `string` keys with the default comparer. Value-type keys are excluded by the guard in `TryInsert`.
- **Pre-size every collection whose final size you know.** `new Dictionary<int,int>(n)`, `new List<T>(n)`, `queue.EnsureCapacity(n)` — one allocation instead of a geometric series of them.
- **`StackOverflowException` cannot be caught and kills the process.** `OutOfMemoryException` can be. That asymmetry is the whole argument for iterative traversal.
- **Probe a `HashSet<string>`/`Dictionary<string,_>` with a `ReadOnlySpan<char>`** via `GetAlternateLookup<ReadOnlySpan<char>>()` (.NET 9+, ordinal comparers only) whenever the key is a slice of something you already hold.
- **`ReferenceEquals` / `ReferenceEqualityComparer.Instance`** whenever the invariant is "same object" rather than "equal value".
- **`stackalloc` a constant, never a length you were given.** Threshold plus `ArrayPool<T>` fallback is the pattern; `Rent` returns *at least* what you asked for and does not clear it.
- **`Parallel.For` throws `AggregateException`**, and parallelising the wrong dimension buys you false sharing and correct answers.
- **Integer arithmetic is unchecked by default.** Areas, byte counts and counting recurrences wrap silently; cast the operand (`(long)a * b`), not the result. Constant expressions *are* checked, which is why your hand-worked example never shows it.
- **`readonly struct` is how you stop the compiler copying defensively.** A non-`readonly` member invoked through a `readonly` field or an `in` parameter copies the whole struct first — and mutates the copy. `readonly record struct` for every small coordinate/pair type.
- **`ReadOnlySpan<T>` for parameters, `string`/`T[]` for anything you keep.** Spans are `ref struct`: no fields, no closures, nothing live across an `await` or a `yield return`. `ReadOnlyMemory<T>` lifts those limits and, in exchange, roots the whole underlying object for as long as you hold it.
- **`!` silences the compiler and checks nothing.** `ArgumentNullException.ThrowIfNull` at boundaries; annotations don't survive into other people's assemblies.
- **The brute force is your test oracle.** Randomised differential testing against it, fixed seed, small value range so ties happen. That is the answer to "how would you test this?"

## Walkthrough — Mock interview: Detect cycle in linked list

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: Interviewer: "Given the head of a singly linked list, return `true` if it contains a cycle, otherwise `false`. Use O(1) extra space." You have 25 minutes. The list could be empty, a single node, or have millions of nodes.

**Diagnosis** (the senior approach): Don't code yet. Restate: "I need to detect whether some `next` pointer revisits a previous node. With unbounded space I'd use a `HashSet<ListNode>` and walk the list — return `true` on the first revisit. That's O(n) time, O(n) space. The constraint says O(1) space, so I need a different approach." Mention Floyd's tortoise-and-hare: two pointers, `slow` advances by 1, `fast` by 2. If there's a cycle, `fast` eventually wraps around and meets `slow` inside the cycle. If `fast` hits `null`, no cycle. Walk through a 4-node example with a cycle on a paper: positions confirm `fast` and `slow` meet at the same node within ~n iterations.

**Fix** (the implementation): Communicate complexity *before* coding. "O(n) time, O(1) space — meets the constraint." Edge cases: `head == null` → false; `head.next == null` → false. Then code:

```csharp
public bool HasCycle(ListNode? head) {
    if (head?.Next is null) return false;
    var slow = head; var fast = head.Next;
    while (fast is not null && fast.Next is not null) {
        if (ReferenceEquals(slow, fast)) return true;   // identity, not equality
        slow = slow!.Next;
        fast = fast.Next.Next;
    }
    return false;
}
```

Say why `ReferenceEquals` and not `==` while you type it — one sentence: "the invariant is that they're the same node, and `==` on a node type is whatever that type declares, so I'll spell out identity." It is a small line that tells the interviewer you have been bitten by a `record`.

Trace through the example aloud, especially the termination condition. State the variant: "If the question asked for the *start* of the cycle, I'd use the same algorithm to find a meeting point, then reset one pointer to head and advance both by 1 — they meet at the cycle start (Floyd's lemma)."

**Why it works**: In a cycle, the relative speed between fast and slow is 1 step per iteration. If there's a cycle of length k, the gap between them closes by 1 each iteration; they meet within k steps after slow enters the cycle. Total iterations ≤ n. The `null` checks on `fast` and `fast.next` correctly handle a non-cyclic list — `fast` reaches the tail and the loop terminates returning `false`. The mental model — "fast catches up to slow if they're on a circular track" — is more important than memorizing the code.

</details>
## Self-test

<details>
<summary>1. What's the standard pattern for "find the K-th largest element," and why does heap beat sort?</summary>

Use a min-heap of size K. Iterate the input; push each element, and if heap size > K, pop the minimum. After processing all elements, the heap contains the top K largest, with the K-th largest at the top (the min of the top K). Time: O(n log k); space: O(k). Sort would be O(n log n) and O(n) — wins only for tiny n. The heap approach beats sort dramatically when k ≪ n (e.g., n=10⁹, k=10) and uses bounded memory regardless of n. .NET implementation: `var heap = new PriorityQueue<int, int>(); foreach (var x in nums) { heap.Enqueue(x, x); if (heap.Count > k) heap.Dequeue(); } return heap.Peek();`.
</details>

<details>
<summary>2. Apply: "longest substring without repeating characters." Walk through the algorithm.</summary>

Sliding window with a `Dictionary<char, int>` mapping char → most recent index. Two pointers: `left` (window start), `right` (window end). For each `right`, if `s[right]` is in the map and `map[s[right]] >= left`, advance `left` to `map[s[right]] + 1` (skip past the prior occurrence). Update `map[s[right]] = right`. Track `max(right - left + 1)`. Time: O(n), each character visited at most twice (once by right, once via left jump). Space: O(min(n, alphabet)). Edge cases: empty string → 0; all same char → 1. The trick is updating `left` to skip *past* the duplicate, not start at the duplicate.
</details>

<details>
<summary>3. Trade-off: when should you use BFS over DFS for tree problems?</summary>

BFS (queue, level-by-level) when: (a) you need shortest path in steps (unweighted), (b) you need level-order traversal (e.g., "average value of each level"), (c) the answer is "found at depth ≤ d," (d) the tree is wide but shallow — DFS would push too many siblings. DFS (stack/recursion) when: (a) you need to explore each path to leaves (e.g., "all root-to-leaf paths summing to X"), (b) you can use the recursion to elegantly express "best answer through this subtree" (e.g., diameter, max path sum), (c) memory is tight and the tree is balanced — DFS uses O(height) stack vs BFS's O(width) queue. Recognize the question type before picking.
</details>

<details>
<summary>4. Analyze: a candidate's solution to "Two Sum" is O(n²) brute force. They claim it's optimal because "all pairs need to be checked." Critique.</summary>

The candidate is wrong about optimality. The brute force checks every pair (n choose 2 = O(n²)), but the optimal uses a hash map of "values I've seen, mapping to their index." For each `nums[i]`, look up `target - nums[i]` in the map; if present, return both indices. If not, add `nums[i] -> i` to the map and continue. Time O(n), space O(n). The insight: we don't need to check pairs; we need to know if the *complement* of the current value has been seen. Hash maps turn "is X present" from O(n) (scan) to O(1) (lookup), which is the classic time-space trade-off pattern senior interviewers probe for.
</details>

<details>
<summary>5. You implement a problem and the interviewer asks "what if the input doesn't fit in memory?" How do you respond?</summary>

Three angles. (1) *Streaming*: can the algorithm work on one pass through a stream? E.g., online K-th largest with a fixed-size heap; running sum/product; sliding window over a stream. (2) *External*: chunk the input, process each chunk in memory, write intermediate results to disk, k-way-merge the chunks (external sort). Mention `IAsyncEnumerable<T>` / `Channel<T>` for the streaming layer in .NET. (3) *Approximation*: if exact answer is impossible (e.g., distinct count over 10TB), use probabilistic data structures — HyperLogLog, Bloom filters, Count-Min Sketch. Senior signal: name the technique, sketch the trade-off (memory vs accuracy), and ask "what's the size?" before committing to one. Don't memorize an answer — show you know the menu.
</details>

## Cross-references

- **Previous: [Dynamic Programming](./06-dynamic-programming.md)** — DP foundation for problems 22-26.
- **[Data Structures](./01-data-structures.md)** — `Dictionary`, `HashSet`, `Queue`, `Stack`, `PriorityQueue`, `LinkedList`.
- **[Searching Algorithms](./03-searching-algorithms.md)** — binary search powers LIS optimal solution.
- **[Graph Algorithms](./05-graph-algorithms.md)** — BFS / DFS underpin the graph problems.
- **[Multithreading Practice](../../08-craft-and-interview-prep/01-multithreading-practice.md)** — concurrency problems extend on this file.
- **[Coding Practice](../../08-craft-and-interview-prep/02-coding-practice.md)** — additional category-organized problems.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *Cracking the Coding Interview* by Gayle Laakmann McDowell (CareerCup, 6th ed. 2015) — the canonical interview prep book; problems organized by pattern.
- *Elements of Programming Interviews* by Aziz, Lee, Prakash — Java/Python/C++ editions; concepts transfer.
- LeetCode — [leetcode.com/problemset](https://leetcode.com/problemset/) — by-tag filtering for category practice.
- NeetCode — [neetcode.io](https://neetcode.io/) — curated 150 problems with video walkthroughs.
- HackerRank — [hackerrank.com/dashboard](https://hackerrank.com/dashboard) — strong on algorithms and data structures.
- *Algorithm Design Manual* by Steven Skiena — chapter 1 has "war stories" of choosing algorithms in real problems.
- *Algorithms Illuminated* (4-volume) by Tim Roughgarden (free PDFs) — clear modern treatment.

</details>
<!-- nav-footer-start -->

---

[← Previous: Dynamic Programming](06-dynamic-programming.md) · [↑ Back to top](#interview-problems) · [Next: 02 — API Development →](../../02-api-development/README.md)

<!-- nav-footer-end -->
