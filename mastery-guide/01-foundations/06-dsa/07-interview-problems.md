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

---

## Common pitfalls

1. **Brute force first; ask if optimization is wanted.** Solving the optimal version when interviewer wanted to see thought process is missing the point.
2. **Skipping edge cases.** Empty input, single element, single character, n=0, n=1 — always discuss.
3. **Off-by-one bugs in sliding window.** When `right` is the inclusive end, window size = `right - left + 1`. Be deliberate.
4. **Two pointers without invariant.** Define what each pointer represents (e.g., "left = smallest index of viable window start"); this prevents drift.
5. **Recursion stack overflow on deep trees / linked lists.** ~10⁵ depth is the .NET default ceiling. Iterative versions for production-shaped data.
6. **`Dictionary<,>` lookup with mutable struct keys.** If you mutate a key after insertion, lookups fail silently.
7. **Hash collisions assumed impossible.** `Dictionary<,>` is O(1) average; pathological keys can make it O(n). Validate that custom `GetHashCode` distributes well.
8. **Mistaking subset for subarray.** "Subset" allows non-contiguous; "subarray" / "substring" requires contiguous. Read the problem carefully.
9. **Greedy when DP is needed.** Coin change with arbitrary denominations: greedy fails. If you can construct a counterexample, greedy doesn't work.
10. **Solving the wrong problem.** Misreading "minimum" as "maximum"; "longest" as "shortest." Re-read the prompt; restate it back to the interviewer.
11. **No complexity analysis.** Stating Big-O for time AND space is expected — interviewers ask for both.
12. **Premature optimization on the whiteboard.** Get a correct solution first; then talk through how to optimize. Bug-free correct beats elegant-but-broken.

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
> **A**: Iterative. O(n) time, O(1) space, no stack risk. Recursive is O(n) stack — overflow at n > 10⁴-10⁵. Iterative pattern: three pointers (`prev`, `curr`, `next`); reverse one link per iteration.
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
> **A**: `MemoryCache` uses size/priority-based eviction, not strict LRU. For strict LRU in .NET, hand-roll the LinkedList+Dictionary pattern, or use libraries like `Microsoft.Extensions.Caching.Memory` configured carefully, or `BitFaster.Caching` (LRU/LFU implementations). LRU is a specific eviction policy; production caches often use TinyLFU or ARC (adaptive replacement) which are more sophisticated than pure LRU.

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
> **A**: Yes. `Channel<T>` is multi-producer multi-consumer safe by default. Spawn N producer tasks all writing to `channel.Writer`; spawn M consumer tasks all reading from `channel.Reader`. Coordination: `await Task.WhenAll(producers); channel.Writer.Complete(); await Task.WhenAll(consumers);`. Closing the writer signals all consumers' foreach to end.

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
> **A**: Sorted list insertion is O(n) (shift elements). Two heaps give O(log n) — exponentially better for large streams. For n = 10⁶ inserts: sorted list = 10¹² ops; two heaps = 2×10⁷ ops. Five orders of magnitude.
>
> **Cross-Q²**: How to handle deletions / sliding window median?
>
> **A**: Hard. Standard `PriorityQueue<,>` doesn't support efficient delete by value. Options: (a) "lazy deletion" — mark elements as deleted in a side set; skip on dequeue. (b) `SortedSet<T>` (red-black tree) — O(log n) insert AND delete AND find median (track the middle iterator). (c) Indexed binary heap with side dictionary — complex but O(log n) all ops. Sliding window median is an advanced problem; sorted set is the typical interview answer.

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

## Walkthrough — Mock interview: Detect cycle in linked list

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: Interviewer: "Given the head of a singly linked list, return `true` if it contains a cycle, otherwise `false`. Use O(1) extra space." You have 25 minutes. The list could be empty, a single node, or have millions of nodes.

**Diagnosis** (the senior approach): Don't code yet. Restate: "I need to detect whether some `next` pointer revisits a previous node. With unbounded space I'd use a `HashSet<ListNode>` and walk the list — return `true` on the first revisit. That's O(n) time, O(n) space. The constraint says O(1) space, so I need a different approach." Mention Floyd's tortoise-and-hare: two pointers, `slow` advances by 1, `fast` by 2. If there's a cycle, `fast` eventually wraps around and meets `slow` inside the cycle. If `fast` hits `null`, no cycle. Walk through a 4-node example with a cycle on a paper: positions confirm `fast` and `slow` meet at the same node within ~n iterations.

**Fix** (the implementation): Communicate complexity *before* coding. "O(n) time, O(1) space — meets the constraint." Edge cases: `head == null` → false; `head.next == null` → false. Then code:

```csharp
public bool HasCycle(ListNode? head) {
    if (head?.next is null) return false;
    var slow = head; var fast = head.next;
    while (fast is not null && fast.next is not null) {
        if (slow == fast) return true;
        slow = slow!.next;
        fast = fast.next.next;
    }
    return false;
}
```

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
