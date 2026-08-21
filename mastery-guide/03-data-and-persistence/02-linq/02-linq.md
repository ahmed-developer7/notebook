# LINQ

> [Mastery Guide](../README.md) › [Data & Persistence](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts (chapter extensions)](#core-concepts-chapter-extensions)
  - [Method syntax vs query syntax](#method-syntax-vs-query-syntax)
  - [Standard query operators worth knowing cold](#standard-query-operators-worth-knowing-cold)
  - [Set operations and grouping](#set-operations-and-grouping)
  - [Joining patterns](#joining-patterns)
  - [Common LINQ-to-SQL translation gotchas](#common-linq-to-sql-translation-gotchas)
  - [Null semantics and three-valued logic](#null-semantics-and-three-valued-logic)
  - [Constants, parameters, and the plan cache](#constants-parameters-and-the-plan-cache)
  - [Projection shape decides the join strategy](#projection-shape-decides-the-join-strategy)
  - [Collation and case sensitivity](#collation-and-case-sensitivity)
  - [Reading the plan of a LINQ query](#reading-the-plan-of-a-linq-query)
  - [Set-based writes with ExecuteUpdate and ExecuteDelete](#set-based-writes-with-executeupdate-and-executedelete)
  - [Streaming vs buffering](#streaming-vs-buffering)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--client-side-evaluation-blowing-memory)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

The deep-dive ([LINQ and Data Querying](../01-foundations/01-net-core-deep-dive/05-data-access.md#12-linq-and-data-querying)) covers `IQueryable` vs `IEnumerable` and deferred vs immediate execution — the foundational distinctions. This file extends with chapter-specific concerns: method vs query syntax, the operator catalog every senior should know cold, joining patterns beyond `Include`, and the LINQ-to-SQL translation gotchas that bite in production.

## Core concepts (chapter extensions)

### Method syntax vs query syntax

LINQ supports two equivalent forms:

```csharp
// Method syntax (most common in 2026)
var orders = db.Orders
    .Where(o => o.Total > 100 && o.Status == "Pending")
    .OrderByDescending(o => o.CreatedAt)
    .Take(10)
    .Select(o => new { o.Id, o.Total });

// Query syntax (SQL-like)
var orders = (from o in db.Orders
              where o.Total > 100 && o.Status == "Pending"
              orderby o.CreatedAt descending
              select new { o.Id, o.Total }).Take(10);
```

They compile to identical IL. Pick one per codebase for consistency. Method syntax is more flexible (chainable, easier composition), query syntax reads better for complex `join` and `group by`. Modern .NET style is method-first.

One asymmetry survives: query syntax has no keyword for a left join, and as of .NET 10 method syntax does — `LeftJoin` and `RightJoin` were added to `Enumerable` and `Queryable`, and EF 10 translates them to `LEFT JOIN` / `RIGHT JOIN`. The EF 10 release notes state the gap plainly: "C# query syntax (`from x select x.Id`) doesn't yet support expressing left/right join operations in this way" (Microsoft Learn, *What's New in EF Core 10*).

> 🌍 **In the real world**: an account-summary query was written years ago in query syntax as the `join ... into g` / `from x in g.DefaultIfEmpty()` pattern, and a cleanup PR "modernised" it into a method-syntax `Join(...)`. The diff looked like a pure style change and was approved in minutes. It was a semantic change: the old pattern is the shape EF Core recognises as `LEFT JOIN`, and `Join` is `INNER JOIN`. Every customer with no orders vanished from the summary. Nobody noticed for a release, because the missing rows were the empty ones — the accounts nobody was looking at, which is exactly the population the summary existed to surface. The durable lesson is that in LINQ, join *shape* is not cosmetic; the pattern is the contract with the translator, and a rewrite of it needs the same review as a change to the SQL.

### Standard query operators worth knowing cold

Memorize these. They appear in every interview.

**Filtering:**
- `Where(predicate)` — keep matching elements.
- `OfType<T>()` — keep elements assignable to T.
- `Distinct()` — remove duplicates by default `Equals`. `DistinctBy(selector)` (.NET 6+) for property-based.

**Projection:**
- `Select(selector)` — transform each element.
- `SelectMany(selector)` — flatten nested collections (`orders.SelectMany(o => o.Items)`).

**Sorting:**
- `OrderBy(key)`, `OrderByDescending`, `ThenBy`, `ThenByDescending`.
- `Reverse()` — only on `IEnumerable`; not translatable to SQL.

**Element selection:**
- `First`, `FirstOrDefault` — first match (throws / null).
- `Single`, `SingleOrDefault` — exactly one (throws if 0 or 2+).
- `Last`, `LastOrDefault` — last match (in EF Core, requires `OrderBy`).
- `ElementAt`, `ElementAtOrDefault` — by index.

**Quantifiers:**
- `Any(predicate)` — does at least one match? (translates to `EXISTS`).
- `All(predicate)` — do all match?
- `Contains(value)` — does collection contain value?

**Aggregation:**
- `Count`, `LongCount`, `Sum`, `Average`, `Min`, `Max`.
- `Aggregate(seed, accumulator)` — fold.

**Set operations:**
- `Union`, `Intersect`, `Except`.
- `Concat` — append (preserves duplicates; vs `Union` which dedupes).

**Pagination:**
- `Skip(n)`, `Take(n)`. `TakeWhile(predicate)`, `SkipWhile(predicate)`.

**Grouping:**
- `GroupBy(key)`, `GroupBy(key, selector)`.

**Joining:**
- `Join(...)` — inner join.
- `GroupJoin(...)` — produces `(outer, IEnumerable<inner>)` pairs. **It has no SQL translation on its own.** Microsoft's wording: "Since databases (especially relational databases) don't have a way to represent a collection of client-side objects, GroupJoin doesn't translate to the server in many cases... That's why EF Core doesn't translate GroupJoin" (Microsoft Learn, *Complex Query Operators*). What EF Core does recognise is `GroupJoin` immediately flattened by `SelectMany` + `DefaultIfEmpty` — that pattern becomes `LEFT JOIN`.
- `LeftJoin(...)`, `RightJoin(...)` — added to `Enumerable`/`Queryable` in **.NET 10**; translated by **EF 10**.

**Conversion:**
- `ToList`, `ToArray`, `ToDictionary`, `ToHashSet`.
- `AsEnumerable`, `AsQueryable` — change interface; switches deferred → immediate or back.
- `AsNoTracking()` (EF Core) — disable change tracking.

> 🌍 **In the real world**: an import job looked up a supplier by its external reference with `.Single(s => s.ExternalRef == r)` and threw `InvalidOperationException: Sequence contains more than one element` at 02:00 one morning, failing the whole batch. The on-call engineer's fix was `.First(...)`, the batch completed, and the incident closed. What `Single` had found was a genuine duplicate created by an earlier partial import — and `First` now silently picked whichever row the plan happened to return, which meant three months of invoices attributed to an arbitrary one of two supplier records. `Single` is not a stricter `First`; it is an assertion that a uniqueness constraint holds. If it fires, the answer is a unique index on the column, not a weaker operator. Note the ordering trap in the other direction too: without an `OrderBy`, "first" is whatever the engine returns, and SQL Server documents that "the order in which rows are returned in a result set isn't guaranteed unless an `ORDER BY` clause is specified" (Microsoft Learn, *ORDER BY Clause*).

### Set operations and grouping

```csharp
// Group orders by status, count per group
var statuses = await db.Orders
    .GroupBy(o => o.Status)
    .Select(g => new { Status = g.Key, Count = g.Count() })
    .ToListAsync();

// Multi-key grouping
var byCountryAndStatus = orders
    .GroupBy(o => new { o.Country, o.Status })
    .Select(g => new { g.Key.Country, g.Key.Status, Total = g.Sum(o => o.Total) });

// Union vs Concat
var allEmails = activeUsers.Select(u => u.Email)
    .Union(deletedUsers.Select(u => u.Email));   // distinct emails

var allEmailsWithDupes = activeUsers.Select(u => u.Email)
    .Concat(deletedUsers.Select(u => u.Email));  // preserves duplicates
```

`GroupBy` translates to SQL `GROUP BY` only in one shape: group by scalar values, then project the key and aggregates over the group. Microsoft states the restriction: "The projection can only contain grouping key columns or any aggregate applied over a column" (Microsoft Learn, *Complex Query Operators*). A predicate over an aggregate becomes `HAVING`:

```csharp
db.Orders.GroupBy(o => o.CustomerId)
         .Where(g => g.Sum(o => o.Total) > 10_000)     // → HAVING SUM(Total) > 10000
         .Select(g => new { CustomerId = g.Key, Total = g.Sum(o => o.Total) })
```

A predicate over a *row* stays a `WHERE` and must go before the `GroupBy`. Moving a predicate across that boundary changes the answer, not just the plan.

> 🌍 **In the real world**: a weekly "orders by status" tile disagreed with the operations team's own count by a few dozen every week. The query was a plain `GroupBy(o => o.Status)` over a `varchar` status column on SQL Server, and the tile showed one `Pending` row. The operations team, exporting the same table into a tool that compared ordinally, saw `Pending` and `pending` — two statuses, written by two services, one of which lower-cased before saving. The database had been hiding the split for a year because the default SQL Server collation is case-insensitive, so `GROUP BY` folded them together. The bug only became visible when a copy of the service was stood up against PostgreSQL for a customer, where the default is case-sensitive and the tile suddenly showed two `Pending` rows. Grouping keys inherit the column's collation; if you have never checked what that collation is, you do not know how many groups your `GroupBy` can produce.

### Joining patterns

For EF Core with navigation properties, **always prefer navigation** over manual `Join`:

```csharp
// ❌ Manual join — verbose, error-prone
var query = from o in db.Orders
            join c in db.Customers on o.CustomerId equals c.Id
            select new { o.Id, c.Name };

// ✅ Navigation property — EF generates the JOIN
var query = db.Orders.Select(o => new { o.Id, o.Customer.Name });
```

Manual `Join` makes sense for:
- Joining across `IEnumerable` collections in memory.
- Cross-database joins via `IQueryable` over different sources.
- Columns that aren't modeled as relationships.

**Left outer join in LINQ.** Before .NET 10 there was no operator for it, only a pattern EF Core pattern-matches:

```csharp
var query = from c in db.Customers
            join o in db.Orders on c.Id equals o.CustomerId into orderGroup
            from o in orderGroup.DefaultIfEmpty()
            select new { c.Name, OrderId = o == null ? (int?)null : o.Id };
```

The recognition is fragile by design. Microsoft's docs say so: "EF Core requires you to flatten out the grouping results of the GroupJoin operator in a step immediately following the operator. Even if the GroupJoin-DefaultIfEmpty-SelectMany is used but in a different pattern, we may not identify it as a Left Join" (Microsoft Learn, *Complex Query Operators*). Insert a `Select` or a `Where` between the `into g` and the `DefaultIfEmpty` and the translation can fall apart.

On **.NET 10 / EF 10** this is a first-class operator and the pattern-matching worry goes away:

```csharp
var query = db.Customers.LeftJoin(
    db.Orders,
    c => c.Id,
    o => o.CustomerId,
    (c, o) => new { c.Name, OrderId = (int?)o.Id });   // → LEFT JOIN
```

EF Core also accepts the `Customers.Include(c => c.Orders)` form when you want the entity graph rather than a flat projection — but note the difference in result shape: `Include` gives you customers each carrying a collection, the join gives you one row per pair.

> 🌍 **In the real world**: a settlement report joined `payments` to `orders` with a manual `Join` on `o.PaymentReference equals p.Reference`, because the two tables lived in different bounded contexts and nobody had modelled a relationship. It reconciled for two years. Then a partner started sending references with a trailing space, the equijoin stopped matching those rows, and the report's totals quietly dropped the affected payments — an inner join expresses "drop what doesn't match", and dropping is silent by construction. The finance team found it, not monitoring. Two changes came out of it: the report became a `LeftJoin` with an explicit "unmatched" bucket that a test asserts is empty, and the join key got a normalising computed column with an index on it. Where a join is your integrity check, an inner join throws the evidence away; a left join keeps it and lets you assert on it.

### Common LINQ-to-SQL translation gotchas

EF Core translates LINQ expressions to SQL. Some C# idioms don't translate:

```csharp
// ✅ string.IsNullOrEmpty IS translatable — on SQL Server it becomes
//    [Notes] IS NULL OR [Notes] LIKE N''
db.Orders.Where(o => !string.IsNullOrEmpty(o.Notes));

// ❌ Custom method calls — not translatable
db.Orders.Where(o => MyMethod(o.Status));   // can't translate MyMethod

// ✅ Inline the logic or pull into client-side after .AsEnumerable()
db.Orders.Where(o => o.Status == "Pending" || o.Status == "Cancelled");

// ❌ string.Equals with a StringComparison overload — EF Core refuses by design
db.Orders.Where(o => o.Status.Equals("pending", StringComparison.OrdinalIgnoreCase));

// ⚠️ DateTime arithmetic
db.Orders.Where(o => o.CreatedAt > DateTime.UtcNow.AddDays(-7));
//   ↑ [CreatedAt] > DATEADD(day, -7.0E0, GETUTCDATE()) — the column stays bare on the left,
//     so this can still seek an index on CreatedAt. That, not "it's a parameter", is what sargable means.
db.Orders.Where(o => EF.Functions.DateDiffDay(o.CreatedAt, DateTime.UtcNow) > 7);
//   ↑ DATEDIFF(day, [CreatedAt], GETUTCDATE()) — SQL Server provider. It translates, but it
//     wraps the column in a function, so it cannot seek an index on CreatedAt. Prefer the first form.
```

Check the translation before you believe it. The per-provider tables are authoritative — Microsoft Learn's *Function Mappings* page for the SQL Server provider lists every .NET member it translates, with an "Added in" column — and `EF.Functions.*` members are **provider-specific**: `DateDiffDay` is a SQL Server extension and does not exist on Npgsql. `.ToQueryString()` on any `IQueryable` (EF Core 5 and later) prints the SQL without executing it, which is the fastest way to settle an argument in review.

**Client-side fallback (changed in EF Core 3):** previously, EF would silently evaluate non-translatable parts in memory after fetching everything. Now it throws — with one deliberate exception that most people get wrong in interviews. Microsoft Learn, *Client vs. Server Evaluation*: "EF Core supports partial client evaluation in the top-level projection (essentially, the last call to `Select()`)... If EF Core detects an expression, in any place other than the top-level projection, which can't be translated to the server, then it throws a runtime exception."

So the same helper method is legal in one position and fatal in another:

```csharp
// ✅ Legal — client evaluation in the final projection
db.Orders.Where(o => o.Total > 100)
         .Select(o => new { o.Id, Label = Describe(o.Status) });   // Describe runs in C#

// ❌ Throws — the same method in a filter
db.Orders.Where(o => Describe(o.Status) == "Awaiting payment");
```

The rule behind the asymmetry: a projection runs over rows the server already decided to send, so client evaluation there costs nothing extra. A filter decides *which* rows to send, so client evaluation there means sending all of them.

```csharp
// ✅ Explicit client-side hop
var ordersByCustomTax = await db.Orders
    .Where(o => o.Total > 100)         // SQL
    .AsEnumerable()                    // hop boundary
    .Where(o => CalculateTax(o) > 10)  // C#
    .ToList();
```

> 🌍 **In the real world**: a tax-band label was computed by a static helper and used in a list endpoint's `Select`. It worked, so the same helper went into the filter of a new "show me the high-band orders" screen, and that threw `InvalidOperationException: The LINQ expression ... could not be translated` the moment it hit staging. The developer read the exception, saw that the identical call worked in the neighbouring method, concluded EF was being inconsistent, and added `.AsEnumerable()` before the `Where` to make it match. It did match — the screen worked, on a staging database with a few thousand orders. EF was not being inconsistent: it was drawing exactly the line between "post-process what I fetched" and "decide what to fetch". Reading the one paragraph of documentation that explains the asymmetry would have cost five minutes and produced a different fix, which is a SQL-expressible band predicate.

### Null semantics and three-valued logic

C# comparison is two-valued: `a != b` is `true` or `false`. SQL comparison is three-valued: `a <> b` is `true`, `false`, or `null`, and `WHERE` discards anything that isn't `true`. In C#, `null != "Pending"` is `true`. In SQL, `NULL <> 'Pending'` is `NULL`, and the row is dropped.

EF Core will not let your LINQ mean something different from your C#. It **injects the null checks for you**. Given two nullable string columns (Microsoft Learn, *Comparisons with null values in queries*):

```csharp
context.Entities.Where(e => e.String1 != e.String2)
```

```sql
WHERE (([e].[String1] <> [e].[String2]) OR ([e].[String1] IS NULL OR [e].[String2] IS NULL))
  AND ([e].[String1] IS NOT NULL OR [e].[String2] IS NOT NULL)
```

You wrote one comparison; five predicates arrived at the database. Three things follow, and a senior candidate should be able to state all three.

1. **`!=` is more expensive than `==`.** Equality needs only `(a = b) OR (a IS NULL AND b IS NULL)`; inequality needs the extra "not both null" arm. The docs put it directly: "the `<>` operation produces more complicated (and potentially slower) query than the `==` operation."
2. **Nullability is a query-performance decision, not just a modelling one.** Comparing two non-nullable columns emits a bare `[a] = [b]` — no compensation at all. The docs' first performance recommendation is "Consider marking columns as non-nullable whenever possible."
3. **The compensation costs sargability.** A disjunction of `IS NULL` tests around a column is much harder for an optimizer to turn into an index seek than a plain equality. If a filter on a nullable column keeps producing scans, this OR-chain is a likely reason, and narrowing the column to `NOT NULL` — or pre-filtering `Where(e => e.String1 != null && ...)`, which lets EF treat the column as non-nullable for the rest of the predicate — is the fix.

**The escape hatch, and why to be careful with it.** `UseRelationalNulls()` turns the compensation off and hands the raw SQL semantics through:

```csharp
optionsBuilder.UseSqlServer(conn, o => o.UseRelationalNulls());
```

Microsoft's own warning: "When using relational null semantics, your LINQ queries no longer have the same meaning as they do in C#, and may yield different results than expected." It is a `DbContext`-options switch, not a database setting — but it changes the meaning of every existing query issued through that context, which makes it a legitimate choice for a codebase whose authors all think in SQL and a landmine everywhere else.

**Engines.** Three-valued logic is ANSI SQL and behaves the same on SQL Server, PostgreSQL and MySQL. What differs is the null-safe comparison operator, which is what EF's generated OR-chain is emulating: PostgreSQL and standard SQL spell it `IS [NOT] DISTINCT FROM`, MySQL has only the null-safe *equality* operator `<=>` (negate it for the inequality case), and SQL Server gained `IS [NOT] DISTINCT FROM` only in **SQL Server 2022** (Microsoft Learn, *IS [NOT] DISTINCT FROM (Transact-SQL)*) — which is why EF's SQL Server translation expands it by hand.

> 🌍 **In the real world**: a fraud team's daily "non-cancelled orders" extract was written twice — once as `db.Orders.Where(o => o.CancelReason != "Duplicate")` in the service, and once as `WHERE cancel_reason <> 'Duplicate'` in a hand-written SQL script for the analysts. For eighteen months the two disagreed by roughly the number of orders that had never been cancelled at all, because `cancel_reason` is `NULL` for those and SQL's `<>` drops `NULL` rows while EF's translation deliberately keeps them. Both queries were "correct"; they answered different questions, and each author was certain the other had a bug. The resolution was not to pick a winner but to write the intent down — `WHERE cancel_reason IS DISTINCT FROM 'Duplicate'` in the script, and a comment in the C# noting that EF preserves C# semantics. When your LINQ and your DBA's SQL give different numbers, null handling is the first place to look, and the fastest proof is `.ToQueryString()` next to the script.

### Constants, parameters, and the plan cache

This is the mechanism that connects a LINQ habit to a database-wide performance problem, and it is where LINQ questions turn into SQL questions in an interview.

**The rule.** EF Core *inlines constants* into the SQL and *parameterizes captured variables*. Same-looking C#, different SQL (Microsoft Learn, *Advanced Performance Topics*):

```csharp
// Constant in the expression tree → literal in the SQL
await context.Posts.FirstOrDefaultAsync(p => p.Title == "post1");
// SELECT TOP(1) ... FROM [Posts] AS [p] WHERE [p].[Title] = N'post1'

// Captured variable → parameter
var postTitle = "post1";
await context.Posts.FirstOrDefaultAsync(p => p.Title == postTitle);
// SELECT TOP(1) ... FROM [Posts] AS [p] WHERE [p].[Title] = @__postTitle_0
```

Two caches are affected, and they are easy to confuse:

- **EF's own query cache**, keyed on the shape of the expression tree. Constants are part of the shape, so a thousand distinct constants means a thousand compilations. EF exposes a *Query Cache Hit Rate* metric; the docs' guidance is that in a normal application it "reaches 100% soon after program startup", and a value that stays below is a sign something is defeating the cache.
- **The database's plan cache.** Because the SQL text differs, the server plans each variant separately. Microsoft is explicit that this is engine-dependent: "SQL Server implicitly maintains an LRU query plan cache, whereas PostgreSQL does not (but prepared statements can produce a very similar end effect)."

Both caches are why hand-building expression trees with `Expression.Constant` is a documented mistake: "This is a frequent mistake when dynamically building expression trees, and causes EF to recompile the query each time it's invoked with a different constant value (it also usually causes plan cache pollution at the database server)." If you must build predicates dynamically, capture the value in a closure (`Expression<Func<string>> p = () => url;` and use `p.Body`) so it arrives as a parameter.

**The `Contains` list — a four-release story worth knowing cold.** `ids.Contains(o.Id)` is the everyday case where this bites, and its translation has changed in every recent major version. That it was a real problem rather than a theoretical one is visible in the tracking issue: efcore#13617 was, in Microsoft's own words, "the most highly-voted issue in the repo at the time" (Microsoft Learn, *What's New in EF Core 10*):

| Version | Translation of `ids.Contains(b.Id)` | What it costs |
|---|---|---|
| EF ≤ 7.0 | inlined constants: `WHERE [Id] IN (1, 2, 3)` | one SQL text per distinct list → plan cache bloat. Tracked as efcore#13617, "the most highly-voted issue in the repo at the time" |
| EF 8.0 | one JSON parameter unpacked server-side: `IN (SELECT [value] FROM OPENJSON(@ids))` | one plan for all lists, but "deprives the database query planner of important information on the cardinality (or length) of the collection" |
| EF 9.0 | as EF 8, plus the ability to choose the strategy — globally and per query | — |
| EF 10.0 (default) | one scalar parameter per element, padded: `IN (@ids1, ... @ids8, @ids9, @ids10)` | stable SQL *and* cardinality information; padding limits how many distinct texts a varying list length can produce |

EF 10 pads deliberately: for an 8-element list it emits 10 parameters, the last two repeating the 8th value "to reduce the number of SQLs generated" while returning the same rows. You control the strategy globally with `UseParameterizedCollectionMode(ParameterTranslationMode.Constant)` or per query with `EF.Constant(ids).Contains(b.Id)`.

**`EF.Constant` and `EF.Parameter`.** These override the default in either direction — `EF.Constant` forces inlining, `EF.Parameter` forces parameterization. `EF.Constant` exists largely for **parameter sniffing**: SQL Server compiles a plan for the first parameter value it sees and reuses it for every later value, so a query that is fast in SSMS with a literal can be slow from the application with a parameter, and vice versa. Inlining hands the optimizer the actual values. EF 10 also redacts inlined values from the log by default — the SQL sent contains `IN (N'Administrator', N'Manager')` while the logged SQL reads `IN (?, ?)` — so do not expect the log to show you what the server saw unless `EnableSensitiveDataLogging` is on.

> 🌍 **In the real world**: a permissions check ran `db.Documents.Where(d => allowedIds.Contains(d.Id))` on an EF Core 6 service, where `allowedIds` came from the caller's ACL and had anywhere from one to several hundred entries. Each distinct list length produced a distinct SQL text, and every distinct *set of values* produced a distinct text too, because the values were inlined. The symptom was not slow queries — it was a SQL Server whose plan cache was almost entirely single-use plans, evicting the plans that mattered, so unrelated reports got slower every afternoon and recovered after the weekly failover. The DBA found it in `sys.dm_exec_cached_plans` filtered on `usecounts = 1`; the application team had been looking at their own endpoint's latency, which was fine. The fix on that version was a temp table joined on the ids for large lists; the fix on EF 8+ is largely free, because the default translation stopped inlining. The transferable lesson is that a LINQ idiom can degrade a database for tenants who never call your endpoint.

### Projection shape decides the join strategy

The single most useful thing to know about EF Core's translator is that **the shape of your query decides the SQL join operator**, and each shape has a different cost curve. Microsoft's *Complex Query Operators* page states the rules; they are worth memorising because they explain most surprising SQL.

| LINQ shape | SQL |
|---|---|
| Collection selector does not reference the outer element | `CROSS JOIN` |
| Collection selector references the outer element **in a `Where`** (the usual navigation-property case) | `INNER JOIN`, or `LEFT JOIN` with `DefaultIfEmpty` |
| Collection selector references the outer element **anywhere else** | `CROSS APPLY`, or `OUTER APPLY` with `DefaultIfEmpty` |
| `GroupJoin` + `SelectMany` + `DefaultIfEmpty`, in that exact adjacency | `LEFT JOIN` |
| Two sibling collection `Include`s | two `LEFT JOIN`s → cartesian product |

The third row is the one that catches people, and its cousin in a projection is the same idea. "Give me each customer with their most recent order" cannot be a plain join, because the inner query depends on the outer row:

```csharp
var rows = await db.Customers
    .Select(c => new {
        c.Id,
        c.Name,
        LastOrderTotal = c.Orders
            .OrderByDescending(o => o.CreatedAt)
            .Select(o => (decimal?)o.Total)
            .FirstOrDefault()
    })
    .ToListAsync();
```

This is **one** query, not N+1 — EF pushes the correlated subquery into the SQL rather than issuing a query per customer. What that subquery looks like depends on how much you asked for, and the distinction is worth knowing:

- **One scalar column**, as above, becomes a correlated scalar subquery in the `SELECT` list — on SQL Server roughly `(SELECT TOP(1) [o].[Total] FROM [Orders] AS [o] WHERE [c].[Id] = [o].[CustomerId] ORDER BY [o].[CreatedAt] DESC)`. No `APPLY` is needed, and it works on every relational provider.
- **The whole related entity** (`c.Orders.OrderByDescending(o => o.CreatedAt).FirstOrDefault()` with no scalar `Select`) needs several columns back, which a scalar subquery can't return — that is where EF reaches for `OUTER APPLY` on SQL Server and `LEFT JOIN LATERAL` on PostgreSQL.

Confirm which one you got with `.ToQueryString()` rather than assuming; the exact shape moves between providers and versions. Either way the cost model is the same and it is the shape that most needs an index: the inner query runs once per outer row, so an index on `Orders (CustomerId, CreatedAt DESC)` turns each execution into a one-row seek, and its absence turns each into a scan.

**Engine support for `APPLY` is not universal**, which matters the moment your product ships against more than one database:

- **SQL Server**: `CROSS APPLY` / `OUTER APPLY`.
- **PostgreSQL**: `LATERAL` / `LEFT JOIN LATERAL`.
- **MySQL**: `LATERAL` derived tables from **8.0.14** (MySQL Reference Manual, *Lateral Derived Tables*); nothing equivalent before that.
- **SQLite**: no `APPLY`. Microsoft's wording: "Certain databases like SQLite don't support `APPLY` operators so this kind of query may not be translated."

**Split queries** are the escape from the sibling-collection cartesian product, and they buy it with real trade-offs the docs enumerate: no cross-query consistency guarantee ("If the database is updated concurrently when executing your queries, resulting data may not be consistent"), one network round-trip per query, and — because most databases allow only one active query per connection — earlier results must be buffered in application memory before later queries run. SQL Server with MARS and SQLite are the named exceptions. EF 10 fixed a correctness bug here: before EF 10, a split query with `Skip`/`Take` could order the outer subquery differently from the outer query and return the wrong children.

> 🌍 **In the real world**: a product shipped its scheduling service against SQL Server for cloud tenants and MySQL for on-premises ones, from a single codebase. A "each resource with its next booking" projection — a correlated `FirstOrDefault` returning the whole `Booking` entity, which is the variant that needs `APPLY`/`LATERAL` rather than a scalar subquery — worked in CI and in the cloud, and broke on one customer's MySQL 5.7 instance, because `LATERAL` arrived in 8.0.14 and that server predated it. The failure surfaced during the customer's upgrade window as an unhandled exception on a page that had never been exercised against that engine. The engineering fix was small (fetch the resources, then one batched second query for the bookings, keyed by resource id). The process fix mattered more: the integration suite now runs against the oldest engine version the support matrix claims, because "we support MySQL" is not a version, and LINQ translation is exactly the layer where the version shows up.

> 🌍 **In the real world**: an order-detail endpoint that eager-loaded lines and payment attempts was rewritten with `AsSplitQuery()` after the cartesian product was found in a profiler trace. Payload size dropped, latency dropped, and a month later support had a ticket about an order whose payment list included an attempt that its own status said had not happened yet. The two split queries ran under SQL Server's default locking `READ COMMITTED` with no enclosing transaction, and a retry had inserted a row between them. This is documented behaviour, not a bug: split queries give up the single-query consistency guarantee. Wrapping the endpoint in a snapshot transaction closed it, at the cost of a `tempdb` version store the team then had to size. Splitting a query splits its consistency; if the result is a screen where the parts must agree, someone has to choose the isolation level on purpose.

### Collation and case sensitivity

`Where(u => u.Email == input)` is not a case-sensitivity-neutral statement. It is a statement whose meaning is set by the collation of the column, and EF Core deliberately does not intervene. From Microsoft Learn, *Collations and case sensitivity*:

> "EF Core makes no attempt to translate simple equality to a database case-sensitive operation: C# equality is translated directly to SQL equality, which may or may not be case-sensitive, depending on the specific database in use and its collation configuration."

And the defaults differ by engine — the same doc: "while some databases are case-sensitive by default (e.g. Sqlite, PostgreSQL), others are case-insensitive (SQL Server, MySQL)." SQL Server's default server collation for the en-US machine locale is `SQL_Latin1_General_CP1_CI_AS` — `CI` for case-insensitive, `AS` for accent-sensitive.

The three ways to force the comparison, in descending order of preference:

1. **Set the collation on the column or database** (`modelBuilder.Entity<Customer>().Property(c => c.Name).UseCollation("SQL_Latin1_General_CP1_CI_AS")`). Indexes inherit the column's collation, so every query benefits and every index stays usable.
2. **`EF.Functions.Collate(c.Name, "...")` per query**, which emits a `COLLATE` clause. The docs' caution: "Specifying an explicit collation in a query will generally prevent that query from using an index defined on that column, since the collations would no longer match."
3. **`ToLower()`/`ToUpper()`** — the worst option, because it wraps the column in a function and disqualifies the index for the same reason.

`string.Equals(a, b, StringComparison.OrdinalIgnoreCase)` throws rather than translating, and the docs explain the design decision: EF "does not know which case-sensitive or case-insensitive collation should be used", and applying one "would in most cases prevent index usage".

> 🌍 **In the real world**: a team ported a long-lived .NET service from SQL Server to PostgreSQL, ran the full test suite green, and started getting "invalid credentials" reports within a day. Login did `db.Users.SingleOrDefault(u => u.Email == submitted)`; SQL Server's case-insensitive default collation had been silently normalising email case for eight years, and PostgreSQL is case-sensitive by default, so every user who typed a capital letter was now a stranger. The tests were green because the fixtures used lower-case emails throughout. The tempting one-line fix was `u.Email.ToLower() == submitted.ToLower()`, which would have worked and turned the login lookup into a sequential scan of the users table on the hottest path in the product. What shipped was a `citext` column with its unique index rebuilt, so the comparison stays case-insensitive *and* indexed. Collation is part of a schema's behaviour, and a migration between engines migrates the data without migrating that behaviour.

### Reading the plan of a LINQ query

The skill an interviewer is testing is not "can you write LINQ" but "can you follow one query from C# to an execution plan". The loop is three steps and takes about a minute.

**Step 1 — get the SQL without executing it.** `.ToQueryString()` (EF Core 5+) prints the command. `TagWith("...")` prepends a SQL comment that survives into the server's DMVs and the slow-query log, so you can find the statement later without guessing:

```csharp
var q = db.Orders
    .TagWith("OrdersController.GetPage")
    .Where(o => o.CustomerId == customerId && o.Status == "Pending")
    .OrderByDescending(o => o.CreatedAt)
    .Skip(page * 50).Take(50)
    .Select(o => new { o.Id, o.Total, o.CreatedAt });

Console.WriteLine(q.ToQueryString());
```

**Step 2 — read the SQL.** For SQL Server this is roughly:

```sql
-- OrdersController.GetPage

SELECT [o].[Id], [o].[Total], [o].[CreatedAt]
FROM [Orders] AS [o]
WHERE [o].[CustomerId] = @customerId AND [o].[Status] = N'Pending'
ORDER BY [o].[CreatedAt] DESC
OFFSET @p ROWS FETCH NEXT @p0 ROWS ONLY;
```

Note the asymmetry from the previous section already showing up: `customerId` is a captured variable, so it arrives as `@customerId`; `"Pending"` is a constant in the expression tree, so EF inlines it as `N'Pending'`.

Note what LINQ did *not* say and SQL requires: `OFFSET`/`FETCH` is only legal under an `ORDER BY`. If you write `Skip`/`Take` with no `OrderBy`, EF raises `CoreEventId.RowLimitingOperationWithoutOrderByWarning` — "The query uses a row limiting operator ('Skip'/'Take') without an 'OrderBy' operator. This may lead to unpredictable results." Treat that warning as an error. And ordering by `CreatedAt` alone is not enough for stable paging: SQL Server's own guidance for `OFFSET`/`FETCH` paging is that "the `ORDER BY` clause contains a column or combination of columns that are guaranteed to be unique". Ties across a page boundary duplicate one row and drop another. `ThenBy(o => o.Id)` is the fix.

**Step 3 — read the plan.** Get it with `SET STATISTICS XML ON` or SSMS's "Include Actual Execution Plan" on SQL Server, or `EXPLAIN (ANALYZE, BUFFERS)` on PostgreSQL. What the two shapes look like for this query:

```
Without an index on (CustomerId, Status, CreatedAt DESC):

  SELECT
    └─ Top (offset + 50)
         └─ Sort  (ORDER BY CreatedAt DESC)          ← the whole matching set is sorted
              └─ Index Seek on IX_Orders_CustomerId  ← seek returns every order for the customer
                   Seek Predicate: CustomerId = @customerId
                   Predicate:      Status = N'Pending'  ← residual: read then discarded

With (CustomerId, Status, CreatedAt DESC) INCLUDE (Total):

  SELECT
    └─ Top (offset + 50)
         └─ Index Seek on IX_Orders_Cust_Status_Created  ← ordered output, no Sort operator
              Seek Predicate: CustomerId = @customerId AND Status = N'Pending'
```

Three readings that matter and that a LINQ-only engineer usually misses:

- **"Index Seek" is not the finish line.** In the first plan the seek is real, and it still reads every order that customer ever placed. The question is rows *read* per row *returned*. SQL Server's actual plan exposes both as **Number of Rows Read** next to **Actual Number of Rows**; PostgreSQL shows the same split as `Index Cond` versus `Filter` with `Rows Removed by Filter`.
- **A `Sort` operator is a memory grant.** If the estimate is low, the grant is too small and the sort spills to `tempdb`, which the plan reports as a warning on the operator ("Operator used tempdb to spill data during execution"). The second plan has no `Sort` at all because the index already returns rows in the requested order — that is the whole point of putting `CreatedAt DESC` in the key.
- **`Skip(n)` is work.** `OFFSET n` still walks past `n` rows; the `Top` operator's cost is `offset + take`, not `take`. Page 1 and page 500 have the same plan and different costs. This is the mechanical reason keyset pagination (`Where(o => o.CreatedAt < lastSeen)`) is preferred for deep lists.

**One more thing to look for in the seek predicate: `CONVERT_IMPLICIT`.** EF Core maps a `string` property to `nvarchar` on SQL Server by default. If the underlying column is `varchar` — common when the model was hand-written over a schema EF didn't create — the comparison mixes types, and SQL Server's documented rule is that "the data type with the lower precedence is first converted to the data type with the higher precedence". `nvarchar` outranks `varchar` (Microsoft Learn, *Data type precedence*), so the **column** is converted, not the parameter. A converted column cannot be seeked, and the plan shows the conversion inside the predicate:

```
Index Scan on IX_Orders_Reference
  Predicate: CONVERT_IMPLICIT(nvarchar(50), [Reference], 0) = @__ref_0
```

The fix is in the model, not the query: `.Property(o => o.Reference).IsUnicode(false)` (or `.HasColumnType("varchar(50)")`) so EF sends a `varchar` parameter and the types match. This is a SQL Server issue specifically — it follows from that precedence table, and PostgreSQL, which has no `nvarchar`/`varchar` split, doesn't reproduce it.

**Engine note.** The pagination syntax is not portable and EF hides that: `Skip`/`Take` becomes `OFFSET ... ROWS FETCH NEXT ... ROWS ONLY` on SQL Server (2012 and later) and `LIMIT ... OFFSET ...` on PostgreSQL and MySQL. The behaviour of `NULL`s in `ORDER BY` differs too — SQL Server sorts `NULL` first ascending; PostgreSQL defaults to `NULLS LAST` ascending — so an ordered page over a nullable column returns different rows on different engines from identical LINQ.

> 🌍 **In the real world**: a support console listed a customer's tickets newest-first with `OrderByDescending(t => t.UpdatedAt).Skip(...).Take(25)`. The plan showed an Index Seek, so when the page got slow the team's first assumption was database load and their first action was a bigger instance. The seek was on `(CustomerId)`; `Status` was a residual predicate and `UpdatedAt` was not in the index, so every page request read that customer's entire ticket history and sorted it. For most customers that was fifty rows and instant. For the three enterprise accounts with six-figure ticket counts it was a sort that spilled to `tempdb` — and the spill made *other* sessions slower, which is why the problem never correlated with the console's own traffic. The instructive part is the diagnostic order: the plan operator name said "seek" and looked healthy, and the number that told the truth was rows read versus rows returned. Learn to look at that number second, right after the operator name.

### Set-based writes with ExecuteUpdate and ExecuteDelete

Added in **EF Core 7**, these run a single `UPDATE` or `DELETE` against rows selected by a LINQ predicate, without loading or tracking anything:

```csharp
await db.Orders
    .Where(o => o.Status == "Pending" && o.CreatedAt < cutoff)
    .ExecuteUpdateAsync(s => s.SetProperty(o => o.Status, "Expired"));
// UPDATE [o] SET [o].[Status] = N'Expired' FROM [Orders] AS [o] WHERE ... AND [o].[CreatedAt] < @cutoff
```

The alternative — query, materialise, mutate, `SaveChanges` — first pulls every affected entity into the change tracker, then emits one `UPDATE` statement per row (EF batches those statements into fewer round trips, but they remain one statement per row). For an expiry sweep over millions of rows, that difference is the whole design.

Four properties to have ready, all from Microsoft Learn, *ExecuteUpdate and ExecuteDelete*:

1. **Immediate, and invisible to the change tracker.** "They take effect immediately, at the point in which they are invoked... the functions are completely unaware of EF's change tracker, and have no interaction with it whatsoever." A tracked entity loaded before the call keeps the original value it was read with, so if that entity is *also* modified in the same unit of work, `SaveChanges` compares against the stale original and writes the pre-bulk value back over what the bulk statement did. (`SaveChanges` only writes properties it considers modified, so an untouched tracked entity produces no `UPDATE` — the overwrite needs a modification, or an `Update()` call that marks every property modified.) The docs' conclusion: "it is usually a good idea to avoid mixing both tracked `SaveChanges` modifications and untracked modifications via `ExecuteUpdate`/`ExecuteDelete`."
2. **No implicit transaction.** "`ExecuteUpdate` and `ExecuteDelete` do not implicitly start a transaction when they're invoked." Two calls plus a `SaveChanges` are three independent transactions unless you open one with `context.Database.BeginTransaction()`.
3. **No automatic concurrency control**, because concurrency tokens live in the change tracker. Both methods return the affected row count, which you check yourself: put the token in the `Where` and treat a return of `0` as a conflict.
4. **Limitations:** update and delete only (no insert), one table per statement, no batching across calls ("Each invocation performs its own roundtrip"), relational providers only.

> 🌍 **In the real world**: a GDPR job anonymised lapsed accounts by loading them in pages and calling `SaveChanges`, which took most of a night and held long transactions that blocked the deletion queue. Rewriting it as one `ExecuteUpdateAsync` per page turned it into minutes. The regression arrived two sprints later, when a colleague added a "and send them a closing email" step that loaded each account entity first, stamped `LastContactedAt` on it, and let the existing `SaveChanges` at the end of the request run through `context.Update(account)`. Because `ExecuteUpdate` never told the change tracker anything, the tracked entities still held the pre-anonymisation values, and `Update()` marks every property modified — so `SaveChanges` wrote the real names back over the anonymised ones, for exactly the accounts that got an email. Nothing threw. The rule the team wrote down afterwards is the one the docs give: a unit of work either goes through the change tracker or around it, never both.

### Streaming vs buffering

`ToListAsync()` **buffers**: one round trip, the reader is drained, the connection goes back to the pool, and the whole result set is on your heap. `AsAsyncEnumerable()` **streams**: rows arrive as you consume them, and the `DbDataReader` — and therefore the connection — stays open for the entire loop.

That last clause is the senior point, and it is a resource-lifetime argument, not a memory one:

- A slow consumer holds a pooled connection for as long as it takes. A streaming export that writes each row to a network client holds a database connection for the duration of that client's download.
- **You cannot generally run a second query on the same connection while a reader is open.** On SQL Server that requires MARS (`MultipleActiveResultSets=True` in the connection string); most providers allow only one active query at a time. A lookup inside a streaming loop is the classic way to discover this.
- Split queries buffer for the same reason: earlier results "must be buffered in your application's memory before executing later queries" (Microsoft Learn, *Single vs. Split Queries*).

The async LINQ operators you compose after `AsAsyncEnumerable()` were, until recently, not in the framework: they came from the `System.Linq.Async` package. **.NET 10** ships `System.Linq.AsyncEnumerable` in the box, which supersedes it — and if you multi-target, the `System.Linq.AsyncEnumerable` NuGet package backfills earlier targets.

> 🌍 **In the real world**: a CSV export streamed orders with `AsAsyncEnumerable()` and, inside the loop, called `db.Customers.FindAsync(o.CustomerId)` to fill in a name column. It ran fine locally against SQLite, and threw `InvalidOperationException: There is already an open DataReader associated with this Connection` the first time it ran against SQL Server. The available fixes ranked in the opposite order to the obvious one: turning MARS on in the connection string makes the exception go away and leaves a per-row round trip inside a streaming loop, which is an N+1 dressed as an export. Projecting the customer name in the original query — one join, no second query, still streaming — removed both problems. Streaming is a promise that you will not hold the connection doing something else; an exception that says you broke that promise is usually pointing at a query shape, not a connection-string setting.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Deferred vs immediate — when does the query run?

```
var query = db.Orders.Where(o => o.Total > 100);   // ← deferred; no SQL yet
                                                      ╲
                                                       Returns IQueryable
                                                      ╱
var list = await query.ToListAsync();              // ← SQL fires here

await foreach (var o in query.AsAsyncEnumerable()) // ← SQL fires here (streaming)
{
    Process(o);
}

bool any = await query.AnyAsync();                 // ← separate SQL fires
int count = await query.CountAsync();              // ← separate SQL fires
```

Calling `.ToList()` materializes once. Calling `.Any()` then `.Count()` on the same `IQueryable` issues TWO queries. Materialize once if you need multiple aggregates:

```csharp
var orders = await query.ToListAsync();
var any = orders.Any();
var count = orders.Count;   // in-memory now
```

### LINQ operator → SQL mapping

```
LINQ                              → SQL
──────────────────────────────────────────────────────
Where(p)                          → WHERE p
Where(p) on a grouping            → HAVING p
Select(x => new {...})            → SELECT ...
OrderBy(k)                        → ORDER BY k
OrderByDescending(k)              → ORDER BY k DESC
Skip(n).Take(m)                   → engine-specific (see below)
GroupBy(k).Select(g => g.Sum())   → GROUP BY k + SUM
Any(p)                            → EXISTS (... WHERE p)
Count()                           → COUNT(*)
First / Single                    → engine-specific row limit (see below)
Distinct()                        → DISTINCT
Include(x => x.Y)                 → LEFT JOIN Y (INNER JOIN if the nav is required)
AsSplitQuery()                    → multiple SELECTs
ExecuteUpdate(...)                → UPDATE
ExecuteDelete()                   → DELETE
──────────────────────────────────────────────────────

Row limiting is NOT portable SQL — EF hides the difference:

                       SQL Server                 PostgreSQL / MySQL
Take(m)              → SELECT TOP(m)            → LIMIT m
Skip(n).Take(m)      → OFFSET n ROWS            → LIMIT m OFFSET n
                       FETCH NEXT m ROWS ONLY
First / Single       → TOP(1) / TOP(2)          → LIMIT 1 / LIMIT 2

OFFSET/FETCH requires an ORDER BY on SQL Server (2012+).
```

### Common LINQ recipes

```csharp
// "Top 10 customers by total spend"
var topCustomers = await db.Orders
    .GroupBy(o => o.CustomerId)
    .Select(g => new { CustomerId = g.Key, Total = g.Sum(o => o.Total) })
    .OrderByDescending(x => x.Total)
    .Take(10)
    .ToListAsync();

// "Customers who placed > 5 orders in the last month"
var since = DateTime.UtcNow.AddMonths(-1);
var loyalCustomers = await db.Customers
    .Where(c => c.Orders.Count(o => o.CreatedAt >= since) > 5)
    .ToListAsync();

// "Orders without payments (left outer join)"
var unpaidOrders = await db.Orders
    .Where(o => !o.Payments.Any())
    .ToListAsync();

// "Average order total per status"
var stats = await db.Orders
    .GroupBy(o => o.Status)
    .Select(g => new {
        Status = g.Key,
        Count = g.Count(),
        AverageTotal = g.Average(o => o.Total),
        MaxTotal = g.Max(o => o.Total)
    })
    .ToListAsync();

// "Pagination with cursor" — the ordering column must be unique, or a tie
// at the page boundary duplicates one row and hides another
var page = await db.Orders
    .Where(o => o.Id < cursor)
    .OrderByDescending(o => o.Id)
    .Take(50)
    .ToListAsync();

// "Most recent order per customer" — one query. An aggregate over a navigation
// becomes a correlated scalar subquery in the SELECT list:
//   (SELECT MAX([o].[CreatedAt]) FROM [Orders] AS [o] WHERE [c].[Id] = [o].[CustomerId])
// no APPLY/LATERAL involved — that shape appears when you project the whole entity
var latest = await db.Customers
    .Select(c => new {
        c.Id,
        c.Name,
        LastOrderAt = c.Orders.Max(o => (DateTime?)o.CreatedAt)
    })
    .ToListAsync();
```

</details>

## Common pitfalls

1. **`First` instead of `Single` when uniqueness matters.** `First` silently picks one if duplicates exist; `Single` throws — surfacing the bug.
2. **Chained `Count` and `Where`.** `db.Orders.Where(p).Count()` is fine; `db.Orders.Count() > 0` is wasteful — use `Any()`.
3. **Loading entities for a calculation.** `db.Orders.ToList().Sum(o => o.Total)` loads every row to do an in-DB-able sum. Use `db.Orders.SumAsync(o => o.Total)`.
4. **`StartsWith` with leading wildcard.** `Where(o => o.Name.Contains("X"))` translates to `LIKE '%X%'` — non-sargable; can't use index. Use full-text search for substring queries on big tables.
5. **`Where` after `OrderBy`.** Functionally fine but semantically weird. `Where` first, `OrderBy` last in the pipeline.
6. **Forgetting `await` on async LINQ.** `db.Orders.ToListAsync()` returns a `Task<List<Order>>`. Without `await`, you have a Task object, not the data.
7. **Double materialization.** `if (query.Any()) return query.First();` runs SQL twice. Use `FirstOrDefault` and null-check.
8. **`GroupBy` without a `Select`.** `db.Orders.GroupBy(o => o.Status)` returns groups containing full entities — heavy. Project to aggregates immediately. Note the version behaviour: on EF Core 7 and later this no longer throws. EF issues `SELECT ... FROM Orders ORDER BY Status` and builds the groupings **client-side after the rows arrive**, so the failure mode changed from a loud exception to a quiet full-table fetch.
9. **`Include` chains beyond 2-3 levels.** `Include(o => o.Items).ThenInclude(i => i.Product).ThenInclude(p => p.Category)` may exceed JOIN limits or generate unmanageable SQL. Project instead.
10. **Re-evaluating `IQueryable` in loops.** `foreach (var status in statuses) { db.Orders.Where(o => o.Status == status).ToList(); }` — N round-trips. Use `Contains`: `db.Orders.Where(o => statuses.Contains(o.Status)).ToList()`.
11. **Modifying a collection while enumerating.** Adding/removing during `foreach` throws or skips. Snapshot to a list first.
12. **Using `LINQ to Objects` (in-memory) on what should be `IQueryable`.** Calling `.AsEnumerable()` mid-pipeline pulls everything to memory. Place it intentionally.
13. **`Skip`/`Take` without a unique `OrderBy`.** EF warns (`RowLimitingOperationWithoutOrderByWarning`) when there is no ordering at all, but it cannot warn about an ordering that is not *unique* — and a non-unique sort key silently duplicates and drops rows across page boundaries. Always add a tiebreaker: `.OrderByDescending(o => o.CreatedAt).ThenBy(o => o.Id)`.
14. **Wrapping the column in a function.** `Where(o => o.Reference.ToLower() == q)`, `Where(o => EF.Functions.DateDiffDay(o.CreatedAt, now) > 7)`, `EF.Functions.Collate(...)` — all translate, none can seek a plain B-tree index on that column. Put the transformation on the *parameter* side, or index the expression.
15. **`Where` on a nullable column with `!=`.** EF expands it into an OR-chain of `IS NULL` tests to preserve C# semantics. Correct, and hard to seek. Consider a non-nullable column with a sentinel, or pre-filter the nulls explicitly.
16. **Mixing `ExecuteUpdate`/`ExecuteDelete` with tracked changes in one unit of work.** The bulk statement never reaches the change tracker, so a later `SaveChanges` writes stale values over it.
17. **A second query inside a streaming loop.** Enumerating `AsAsyncEnumerable()` holds the reader — and the connection — open; a lookup inside the loop needs MARS on SQL Server, and is an N+1 either way.

## Interview-ready summary

- **`IQueryable`** = composable expression tree, executes against a provider (EF Core → SQL). **`IEnumerable`** = in-memory iteration.
- **Deferred** until materialization (`ToList`, `First`, etc.); chain freely without round-trips.
- **Method syntax** is the modern default; query syntax shines for `join`/`group by`.
- **Top operators:** `Where`, `Select`, `OrderBy`, `Take`, `Skip`, `GroupBy`, `Any`, `Count`, `Sum`, `Include`, `AsNoTracking`.
- **Translation boundary:** not all C# is translatable, and the boundary is *positional* — client evaluation is allowed in the top-level `Select` and throws anywhere else. Verify with `.ToQueryString()`, the provider's function-mappings page, or LINQPad.
- **Constants vs parameters:** EF inlines constants and parameterizes captured variables. That choice decides whether the SQL text — and therefore the database plan cache entry — is stable across calls.
- **Null semantics:** EF adds `IS NULL` compensation so LINQ keeps C# meaning against SQL's three-valued logic. Correct, verbose, and harder to seek.
- **Collation decides what `==` means.** SQL Server and MySQL default to case-insensitive; PostgreSQL and SQLite default to case-sensitive.
- **Set-based writes:** `ExecuteUpdate`/`ExecuteDelete` (EF Core 7+) run immediately, bypass the change tracker entirely, and start no transaction of their own.

**Expected interview questions:**

1. *"`First` vs `FirstOrDefault` vs `Single` vs `SingleOrDefault`?"* — First throws if empty; FirstOrDefault returns null. Single requires exactly one (throws if 0 or 2+); SingleOrDefault requires 0 or 1. Use `Single` when uniqueness is invariant; `First` when picking from a list.
2. *"How does deferred execution affect you?"* — Build query without DB hit; materialize once. Chaining doesn't compound trips. But re-iterating an `IQueryable` re-runs the SQL.
3. *"Why is `.Where(o => MyMethod(o))` problematic in EF Core?"* — Custom methods can't translate to SQL. EF Core throws (since v3) instead of silently fetching everything. Inline the logic or hop to client with `.AsEnumerable()`.
4. *"How does `Include` work?"* — Generates a JOIN to fetch related entities in the same query. `ThenInclude` chains for nested relationships. With multiple `Include` to collections, use `AsSplitQuery` to avoid cartesian explosion.
5. *"When use `AsNoTracking`?"* — Read-only queries. Skips change tracking; faster. Default for query-side in CQRS.
6. *"What's the difference between `Concat` and `Union`?"* — `Concat` appends, preserves duplicates. `Union` deduplicates by `Equals`.
7. *"Implement pagination in LINQ."* — `db.Orders.OrderBy(o => o.Id).Skip((page - 1) * size).Take(size)`. The `OrderBy` is not optional and its key must be unique, or rows duplicate and vanish across page boundaries; SQL Server also requires an `ORDER BY` for `OFFSET`/`FETCH` to be legal at all. For deep lists prefer keyset/cursor pagination: `Where(o => o.Id < cursor).OrderByDescending(o => o.Id).Take(size)` — `OFFSET n` still walks past `n` rows, so offset cost grows with page number while keyset cost does not.
8. *"Why does `.Where(o => ids.Contains(o.Id))` have a reputation for hurting SQL Server?"* — Historically EF inlined the values, so every distinct list produced a distinct SQL text and a distinct cached plan. EF 8 switched the default to a single JSON parameter unpacked with `OPENJSON`, which stabilised the plan but hid the collection's cardinality from the optimizer; EF 10 switched again to one padded scalar parameter per element, which gives stable SQL *and* cardinality. Override per query with `EF.Constant`/`EF.Parameter`.
9. *"Where does EF Core still allow client-side evaluation, and why there?"* — Only in the top-level projection. A projection runs over rows the server already chose to return, so evaluating it in C# transfers nothing extra; a filter decides *which* rows are returned, so evaluating it in C# means transferring all of them. Same helper method, legal in `Select`, throws in `Where`.
10. *"You call `ExecuteUpdate` and then `SaveChanges` in the same request. What happens?"* — They don't know about each other. `ExecuteUpdate` runs immediately and never touches the change tracker, so any entity loaded beforehand still holds its pre-update original values. If that entity is then modified (or passed to `Update()`, which marks everything modified), `SaveChanges` writes the stale values back over the bulk update; if it is left untouched, `SaveChanges` emits nothing for it. There is also no shared transaction unless you open one explicitly.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.

### Drill 1 — Deferred execution

> **Q**: What does "deferred execution" mean in LINQ, and why is it useful?
>
> **A**: A LINQ query is **not executed** when you build it — `var q = db.Orders.Where(o => o.Total > 100)` creates an expression tree describing the query. Execution happens when you **materialize** it: `ToList`, `First`, `Count`, `Any`, `foreach`. Useful because you can compose filters in multiple steps without intermediate round trips and the provider can optimize the final shape.
>
> **Cross-Q**: Show me a deferred-execution bug.
>
> **A**: `var oldOrders = orders.Where(o => o.CreatedAt < cutoff); cutoff = DateTime.Now; foreach (var o in oldOrders) { ... }` — the lambda captures `cutoff` **by reference**, so when the foreach runs, `cutoff` is now the post-mutation value, not the value at definition time. The query returns wrong rows. Fix: capture into a local variable inside the lambda's scope, or materialize earlier with `.ToList()`.
>
> **Cross-Q²**: I enumerate the same `IQueryable` twice in a row. What does EF Core do?
>
> **A**: **Runs the SQL twice**. Each enumeration calls the provider, generates SQL (cached if shape is unchanged), and executes. The second result set might even differ if rows changed between enumerations — **non-repeatable reads** unless wrapped in a transaction with appropriate isolation. Fix: materialize to a `List<T>` once if you'll iterate multiple times: `var orders = query.ToList(); foreach (...) {} foreach (...) {}`.

### Drill 2 — IEnumerable vs IQueryable

> **Q**: Why does it matter whether a method returns `IEnumerable<T>` or `IQueryable<T>`?
>
> **A**: `IQueryable<T>` carries the **expression tree** — downstream `Where`/`Select` calls are appended and translated to SQL by the provider. `IEnumerable<T>` is in-memory — once you cast or call `AsEnumerable`, further LINQ runs **client-side** in C# memory. Returning `IEnumerable<T>` from a repository method silently disables server-side filtering, often blowing memory or perf.
>
> **Cross-Q**: I called `.AsEnumerable()` in the middle of a query and now performance tanked. Why?
>
> **A**: Everything **before** `AsEnumerable` is translated to SQL; everything **after** is C# in-memory. If the pre-AsEnumerable query returns 10M rows and the post-AsEnumerable `Where` filters down to 100, you've transferred 10M rows over the wire and 9.999M of them get discarded client-side. Fix: keep the entire chain as `IQueryable` until materialization, or move the filter before the boundary.
>
> **Cross-Q²**: My repository returns `IEnumerable<Order>` because it's "looser coupling." What's the trade-off?
>
> **A**: Looser coupling for the caller; **no composability** for downstream filters. A controller that calls `repo.GetAll().Where(o => o.IsActive)` has to fetch the full table just to filter to active ones. The fix is to either return `IQueryable<T>` (couples to LINQ-to-SQL semantics but lets the controller compose filters) or **expose specific methods** (`GetActive`, `GetByStatus`) on the repository so the SQL stays server-side. Modern guidance: return `IQueryable<T>` from repositories you control; return `IEnumerable<T>` from public APIs to prevent abuse.

### Drill 3 — Expression trees and provider translation

> **Q**: What's the difference between `Func<Order, bool>` and `Expression<Func<Order, bool>>`?
>
> **A**: `Func<Order, bool>` is a **compiled delegate** — opaque executable code; you can call it but can't inspect it. `Expression<Func<Order, bool>>` is a **tree representation** of the lambda — a structured data object the provider can walk and translate. LINQ-to-SQL providers (EF Core, LINQ-to-Entities) require `Expression<T>`; LINQ-to-Objects accepts `Func<T>`.
>
> **Cross-Q**: How does EF Core translate `Where(o => o.Total > 100)` to SQL?
>
> **A**: It walks the expression tree: sees a `BinaryExpression` (`GreaterThan`), with a `MemberExpression` (`o.Total`) on the left and a `ConstantExpression` (`100`) on the right. The provider's visitor pattern maps each node to SQL — `MemberExpression` → column name (looked up via the model), `BinaryExpression` → SQL operator. A `ConstantExpression` is **inlined as a literal**, so the SQL is `WHERE [o].[Total] > 100.0`, not `@p0`. You get a parameter only when the value comes from a **captured variable**: `var min = 100; ... Where(o => o.Total > min)` produces `WHERE [o].[Total] > @__min_0`. That distinction is not cosmetic — the literal form makes the SQL text vary with the value, which multiplies both EF's compiled-query cache entries and the database's plan cache entries.
>
> **Cross-Q²**: I wrote `.Where(o => MyHelper(o.Status))` where `MyHelper` is a static C# method. EF Core throws. Why?
>
> **A**: The expression tree contains a `MethodCallExpression` for `MyHelper`, but the provider **has no translation rule** for arbitrary C# methods. Since EF Core 3, the provider throws `InvalidOperationException` instead of silently fetching all rows and evaluating client-side (the v2 behavior caused production memory blowups). Fix: inline the method body into the lambda so EF can translate the primitives, or call `.AsEnumerable()` before the filter (if you accept the perf cost), or register a `DbFunction` if the helper maps to a SQL function.

### Drill 4 — AsEnumerable trap

> **Q**: When is `AsEnumerable` the right call, and when is it a trap?
>
> **A**: **Right call**: you've fetched everything you need from the server (filtering, ordering, paging all done in SQL) and want to do an additional projection that doesn't translate — formatting, conditional logic, calling a C# method per row. **Trap**: you call it too early, before server-side filtering, so the unfiltered result set comes over the wire and gets filtered in memory.
>
> **Cross-Q**: Show me the canonical mistake.
>
> **A**: `db.Orders.AsEnumerable().Where(o => o.Total > 100).ToList()` — the `.AsEnumerable()` pulls **every order** into memory, then filters in C#. With 10M orders, you've blown the heap and saturated the network. Fix: `db.Orders.Where(o => o.Total > 100).ToList()` — filter in SQL, materialize the small result set. If you must do post-SQL processing, push it as late as possible: `db.Orders.Where(...).ToList().Select(MyHelper)`.
>
> **Cross-Q²**: How does `AsEnumerable` differ from `ToList`?
>
> **A**: `ToList` **executes immediately** — round trip happens now, results buffered in memory. `AsEnumerable` is a **cast/hint**: tells the compiler to treat the source as `IEnumerable<T>` so subsequent operators bind to LINQ-to-Objects; **doesn't execute yet**. The execution happens on the next materialization. Practical difference: `ToList` separates SQL phase from C# phase **explicitly**; `AsEnumerable` lets you defer until the foreach. Most teams prefer `ToList` because the boundary is obvious in code review.

### Drill 5 — GroupBy translation

> **Q**: How well does EF Core translate `GroupBy` to SQL?
>
> **A**: EF Core 3+ translates `GroupBy` when you **immediately project aggregates**: `Group(o => o.CustomerId).Select(g => new { g.Key, Total = g.Sum(x => x.Total) })` → `GROUP BY CustomerId` in SQL. If you try to materialize the group itself (`.ToList()` on a `IGrouping<TKey, TElement>` without aggregating), EF Core has to fetch all rows and group client-side.
>
> **Cross-Q**: Why can't EF Core just fetch all rows when GroupBy returns groups directly?
>
> **A**: EF Core 2 did, and it caused production outages. A `GroupBy` on a large table that the developer assumed was server-side silently pulled millions of rows. EF Core 3 changed the default to **throw** for non-translatable group queries, surfacing the bug early. The fix is to either project aggregates immediately (server-side group) or call `.AsEnumerable()` first (explicit opt-in to client-side group).
>
> **Cross-Q²**: I want "group by month, return the top 3 customers per month." How do I express that in EF Core LINQ?
>
> **A**: Start by saying what EF Core does *not* have: **there is no window-function support in EF Core's LINQ surface**, through EF 10. The tracking issue, dotnet/efcore#12747 "Support SQL window functions", is an open Epic in the Backlog milestone with no committed release. The hard part is the design question the issue opens with — how a window function would even be expressed in LINQ, given there is no in-memory operator to mirror it — and the issue now carries an active design proposal in its comments, so treat "never" as wrong and "not yet, and not scheduled" as right. Anyone who tells you `EF.Functions.RowNumber` exists in EF Core itself is thinking of a third-party extension package. Practical approaches, in order: (1) `FromSqlInterpolated` with `ROW_NUMBER() OVER (PARTITION BY Month ORDER BY Total DESC)` filtered to `<= 3`, composed on with LINQ afterwards. (2) A correlated projection — for **top 1** per group, `Select(g => g.Orders.OrderByDescending(o => o.Total).FirstOrDefault())` needs no raw SQL; for top *N* the same shape with `.Take(3)` is where translation gets provider-dependent, so check it with `.ToQueryString()`. (3) Two-step: aggregate monthly totals server-side, then one keyed second query. (4) Client-side top-N **only if** the cardinality is small and bounded.

### Drill 6 — Set operators

> **Q**: Walk me through `Union`, `Intersect`, `Except`, and `Concat`.
>
> **A**: **`Union`**: set union, **deduplicates** by equality. SQL `UNION`. **`Intersect`**: set intersection, only elements in both. SQL `INTERSECT`. **`Except`**: set difference, elements in first but not second. SQL `EXCEPT`. **`Concat`**: appends, **preserves duplicates**. SQL `UNION ALL`. Choose based on duplicate semantics: dedup wanted → `Union`; preserve → `Concat`.
>
> **Cross-Q**: Why is `Concat` usually faster than `Union`?
>
> **A**: `Union` adds a dedup step — SQL needs to compare all rows from both sides to drop duplicates, typically requiring a sort or hash-aggregate. `Concat` just streams both sides. If you know there are no duplicates (or they're acceptable), `Concat` saves the dedup cost. For LINQ-to-Objects, the difference is similar: `Concat` is O(n+m); `Union` is O(n+m) with hash-set overhead.
>
> **Cross-Q²**: How does EF Core know what equality to use for `Union`/`Intersect`/`Except`?
>
> **A**: For entities, EF Core uses the **primary key** — the SQL `UNION` / `INTERSECT` / `EXCEPT` compare all columns, but the entity materialization step dedupes by PK. For projections to anonymous types, it compares **all fields** of the projection (SQL operator on all columns). For value objects, it's by the projected column values. Watch out: comparing entities with navigation properties can produce surprising SQL — EF Core 5+ generally projects only key columns for entity set operations.

### Drill 7 — Projection vs entity materialization

> **Q**: Should I return entities or DTOs from queries?
>
> **A**: **DTOs (projections)** for read-only paths and APIs — narrower SELECT (less data over the wire), no change tracking (faster), no risk of accidentally exposing internal fields. **Entities** for write paths where you'll modify and `SaveChanges` — change tracking, validation, and aggregate-level invariants need the full entity graph.
>
> **Cross-Q**: How much faster is projection in practice?
>
> **A**: Don't quote a multiplier — name the mechanisms and say which one dominates for the query in front of you. (1) **Narrower SELECT**: `Select(o => new { o.Id, o.Total })` fetches 2 columns instead of 30, which is both less network and, decisively, the difference between a query a covering index can answer from its leaves and one that needs a lookup per row into the table. (2) **No change-tracker snapshot**: tracking stores an original-values copy of every loaded entity, so a tracked read of N entities is N extra copies plus fixup work. (3) **Fewer allocations**: an anonymous type or record with two fields is smaller than an entity with its navigation collections. The one that matters most is usually (1), because it changes the *plan*, not just the constant factor. The downside is duplicated mapping code unless you use AutoMapper, Mapster, or a source-generated mapper.
>
> **Cross-Q²**: I'm projecting to a DTO but EF Core is still loading all the navigations. Why?
>
> **A**: The `Select` lambda references a navigation property like `o.Customer.Name` — EF Core sees that and generates a `JOIN` for `Customer`, but only fetches the `Name` column from the joined table (not the full Customer entity). If you're seeing extra navigation loads, it's likely because (1) you have `AutoInclude` configured on the model, (2) lazy-loading proxies are enabled and something touches a navigation, or (3) you're using a global query filter that references navigations. Check the generated SQL to confirm.

### Drill 8 — SkipWhile and TakeWhile

> **Q**: What's the difference between `Where(predicate)` and `TakeWhile(predicate)`?
>
> **A**: `Where` evaluates the predicate **for every element**, keeping the ones that match — entire collection scanned. `TakeWhile` evaluates from the start and **stops at the first false** — it short-circuits. Same for `SkipWhile`: skips while true, then yields the rest **regardless of subsequent elements**.
>
> **Cross-Q**: Show me when this matters.
>
> **A**: A sorted log stream where you want "all entries until the first error": `logs.TakeWhile(l => l.Level != "Error")` stops at the first error. `Where(l => l.Level != "Error")` returns all non-error entries, even ones **after** the first error. Different semantics; the second is rarely what you want when the input has order significance.
>
> **Cross-Q²**: Does EF Core translate `TakeWhile`/`SkipWhile` to SQL?
>
> **A**: Generally **no** — they don't map to SQL `TOP`/`LIMIT` because those don't have predicate semantics. On EF Core 3.0 and later that means a runtime `InvalidOperationException`, not a silent client-side fallback, and there is no configuration switch that restores the old behaviour: the `ConfigureWarnings(... QueryClientEvaluationWarning)` knob applies only to versions *before* 3.0 (Microsoft Learn, *Client vs. Server Evaluation*). Client evaluation survives in exactly one position — the top-level projection — and `TakeWhile` in a query is not it. If you need predicate-based limits server-side, express it differently: rank by row number with a window function and filter by rank, or use `OrderBy` + `Where` to bracket the data. `TakeWhile` is fine for in-memory `IEnumerable<T>`; rare in `IQueryable<T>`.

### Drill 9 — Aggregate vs Sum/Count

> **Q**: When would you use `Aggregate` instead of `Sum`, `Count`, `Max`?
>
> **A**: When the reduction isn't a standard aggregate — custom folds like `Aggregate((a, b) => a + "; " + b)` for string joining (though `string.Join` is clearer), running-total computation, or building a non-numeric accumulator. The built-in `Sum`/`Count`/`Min`/`Max` are special-cased and faster; `Aggregate` is the general-purpose escape hatch.
>
> **Cross-Q**: Why is `Sum` faster than `Aggregate((a, b) => a + b)` in LINQ-to-Objects?
>
> **A**: `Sum` over `int`/`long`/`double` uses a typed loop over the source with the addition inlined — no delegate invocation per element. `Aggregate` invokes a delegate per element, so every element pays an indirect call the JIT generally cannot inline. That is the mechanism; the size of the gap depends entirely on element count and element type, so measure it on your data rather than carrying a number into an interview. For LINQ-to-Entities the comparison doesn't arise: `Sum` translates to SQL `SUM` and `Aggregate` has no translation at all.
>
> **Cross-Q²**: Does `Aggregate` translate to SQL in EF Core?
>
> **A**: **No** — there's no general SQL operator for arbitrary fold operations, so on EF Core 3.0+ an `Aggregate` over an `IQueryable` **throws** rather than quietly evaluating on the client; you opt into the client hop yourself with `AsEnumerable()`/`ToList()` first. Built-in aggregates (`Sum`, `Count`, `Min`, `Max`, `Average`) map to SQL `SUM`/`COUNT`/`MIN`/`MAX`/`AVG`. For custom server-side aggregations, use window functions via raw SQL or compose multiple queries.

### Drill 10 — LINQ to Objects vs LINQ to Entities

> **Q**: A method takes `IEnumerable<Order>`. Is it LINQ to Objects or LINQ to Entities?
>
> **A**: **LINQ to Objects** — `IEnumerable<T>` runs in memory using the `Enumerable` static class operators. **LINQ to Entities** requires `IQueryable<T>`, which carries the expression tree EF Core translates to SQL. Once you have `IEnumerable<T>`, you're past the database boundary.
>
> **Cross-Q**: What operators behave differently between the two?
>
> **A**: Three families. **String comparison**: in memory, `==` is ordinal and case-sensitive; in SQL it means whatever the column's collation means, and EF deliberately does not bridge the gap — "C# equality is translated directly to SQL equality, which may or may not be case-sensitive" (Microsoft Learn, *Collations and case sensitivity*). So the identical predicate can return different rows in memory and in the database, and different rows again on SQL Server (case-insensitive default) versus PostgreSQL (case-sensitive default). The `StringComparison` overloads don't paper over it — EF **throws** on them by design rather than guess a collation. **`DateTime` arithmetic**: in-memory is `TimeSpan` maths; in SQL it's provider-specific functions (`DATEDIFF` on SQL Server via `EF.Functions.DateDiffDay`, different members on Npgsql). **Null semantics**: C# is two-valued, SQL is three-valued, and EF injects compensating `IS NULL` predicates so the LINQ keeps its C# meaning — which is why the generated SQL for `!=` on nullable columns is longer than what you wrote.
>
> **Cross-Q²**: I have a method `IEnumerable<Order> FilterActive(IEnumerable<Order> source)` and want to use it both in memory and against EF Core. What's the trick?
>
> **A**: Express the filter as an `Expression<Func<Order, bool>>` instead of a method body, then have an extension method that applies it to both `IEnumerable<T>` and `IQueryable<T>`. Or use the **Specification pattern** where each specification carries both a `Func<T, bool>` (in-memory) and an `Expression<Func<T, bool>>` (queryable). LinqKit and Ardalis.Specification are libraries that formalize this.

### Drill 11 — EF Core GroupBy evolution

> **Q**: What changed in EF Core's `GroupBy` support over versions?
>
> **A**: EF Core 1-2 had **very limited** `GroupBy` translation — most non-trivial groupings fell back to client-side, often silently pulling huge result sets. EF Core 3 made it stricter: complex groupings throw instead of falling back. EF Core 5-7 added significant translation improvements: more grouping shapes recognized, `Sum`/`Count`/`Min`/`Max`/`Average` over groups translate cleanly, and aggregate predicates land in `HAVING`. **EF Core 7** re-allowed one specific client-side case — `GroupBy` as the *final* operator (efcore#19929). Be careful not to claim window functions anywhere in this timeline: EF Core still has none.
>
> **Cross-Q**: Why did EF Core 3 make `GroupBy` strict?
>
> **A**: Because silent client-side evaluation turned an invisible query-shape detail into an unbounded memory read: a group whose shape didn't translate pulled the whole table into the worker, and nothing in the code said so. EF Core 3 moved the failure from production to first execution. Microsoft frames the same change for `Where`-position client evaluation in *Client vs. Server Evaluation*: "Based on the filter and the amount of data on the server, client evaluation could result in poor performance. So Entity Framework Core blocks such client evaluation and throws a runtime exception."
>
> **Cross-Q²**: On EF Core 7+, `db.Orders.GroupBy(o => o.CustomerId)` no longer throws. Is that good news?
>
> **A**: It's a trap dressed as an improvement. `GROUP BY` in SQL *collapses* rows, so there is no SQL shape that returns "the key plus all its members" — and EF Core 7 didn't invent one. What it does is fetch the rows ordered by the key and build the groupings on the client: `SELECT [b].[Price], [b].[Id], [b].[AuthorId] FROM [Books] AS [b] ORDER BY [b].[Price]` (Microsoft Learn, *Complex Query Operators*). So the query works, the result is correct, and it read the whole table to get there. The pre-7 exception at least told you. If you actually need members per group, the options are unchanged: (1) two queries — keys first, then one query filtered by those keys, (2) accept the ordered fetch deliberately when the set is small and bounded, (3) raw SQL with `ROW_NUMBER()` when you want top-N per group.

### Drill 12 — Multiple Includes vs split queries

> **Q**: I have `Orders.Include(o => o.Items).Include(o => o.ShippingAddress)`. What's the SQL shape?
>
> **A**: A single SQL query with **JOIN**s for both navigations. With one to-many (`Items`) and one to-one (`ShippingAddress`), you get one row per `(Order, Item)` pair, with `ShippingAddress` columns duplicated across each pair. EF Core materializes this into the entity graph and de-duplicates the order header.
>
> **Cross-Q**: When does adding a second to-many `Include` cause cartesian explosion?
>
> **A**: When both included collections are to-many. `Orders.Include(o => o.Items).Include(o => o.PaymentAttempts)` produces `orders × items × payments` rows — a 100-order × 5-items × 3-payments query returns 1,500 rows for 100 orders, and the duplication scales multiplicatively. Network and memory cost explode. EF Core 5+ warns about cartesian patterns.
>
> **Cross-Q²**: When is `AsSplitQuery` the right fix vs projection?
>
> **A**: `AsSplitQuery` runs **one query per Include** (one for orders, one for items, one for payments) — total rows ≈ 100 + 500 + 300 = 900 instead of 1,500. Faster, less memory, but **3 round trips** instead of 1. Use when (1) the cartesian product is genuinely huge, (2) you can't refactor to a projection, (3) network round-trip latency is low (in-region database). **Projection** is better when you don't actually need full entities — fetching only the fields you display is almost always faster than either Include strategy.

### Drill 13 — String operators and indexability

> **Q**: How does `s.Contains("foo")` translate to SQL, and is the column indexable?
>
> **A**: Translates to `WHERE s LIKE '%foo%'` — leading wildcard means the database **cannot use a B-tree index** on `s`. Full table scan. `StartsWith` translates to `LIKE 'foo%'` — no leading wildcard, **can use the index** (range scan from `foo` to `fop`). `EndsWith` translates to `LIKE '%foo'` — leading wildcard again, no index.
>
> **Cross-Q**: How do you do "contains" on a large table efficiently?
>
> **A**: Full-text search. SQL Server `CONTAINS`/`FREETEXT`, PostgreSQL `tsvector`/`tsquery`, MySQL `MATCH AGAINST`, or external indices like Elasticsearch, Meilisearch, Typesense. The DB maintains a separate inverted-index structure that makes word queries cheap on large tables where `LIKE '%x%'` cannot use a B-tree at all. The `EF.Functions` surface is **provider-specific**: the SQL Server provider exposes `EF.Functions.Contains(prop, searchCondition)` → `CONTAINS(...)` and `EF.Functions.FreeText(...)` → `FREETEXT(...)`, both listed in Microsoft Learn's *Function Mappings* page for that provider with no version gate; other providers expose different members or none. Note that these need a full-text index to exist — they are not a drop-in replacement for `string.Contains`. For substring rather than word matching on PostgreSQL, the `pg_trgm` extension with a GIN index is the usual answer.
>
> **Cross-Q²**: I added a B-tree index on `Email` and `Where(e => e.Email.StartsWith("a"))` got fast, but `Where(e => e.Email.ToLower().StartsWith("a"))` is still slow. Why?
>
> **A**: `ToLower()` translates to a SQL function call (`LOWER(Email)`) — applying a function to the indexed column **disqualifies the index** because the index stores raw values, not lowercased ones. Fix options: (1) **expression index** on `LOWER(Email)` (PostgreSQL, SQL Server computed column with index), (2) store a **denormalized `EmailLower` column** populated by a trigger or app code and index that, (3) **case-insensitive collation** at the column level so `Where(e => e.Email.StartsWith("a"))` is case-insensitive without `ToLower`.

### Drill 14 — Query syntax vs method syntax

> **Q**: Are query syntax and method syntax functionally equivalent?
>
> **A**: Yes — the C# compiler translates query syntax to method calls before IL emission. `from o in db.Orders where o.Total > 100 select o` becomes `db.Orders.Where(o => o.Total > 100).Select(o => o)`. Same IL, same performance, same translation by the provider.
>
> **Cross-Q**: When does query syntax read better than method syntax?
>
> **A**: Complex `join` operations — `from o in orders join c in customers on o.CustomerId equals c.Id select new { ... }` reads SQL-like and aligns with the multi-table mental model. Also `group ... by ... into g` for grouping with continuations. Method syntax with `Join`/`GroupJoin` lambdas is more verbose for the same shape. Simple `Where`/`Select`/`OrderBy` chains read better in method syntax.
>
> **Cross-Q²**: My team writes everything in method syntax. Should I push for query syntax?
>
> **A**: Pick one and stick to it for codebase consistency. Method syntax dominates modern .NET style (2026) because it composes better (chainable extension methods), supports operators query syntax doesn't expose directly (`Distinct`, `Take`, `Skip`, `Any`, etc., require `into` continuations), and aligns with how most LINQ documentation and Stack Overflow answers are written. Query syntax is a fine choice if your team prefers it, but rare in greenfield code today.

### Drill 15 — Custom IQueryable providers

> **Q**: What does it take to implement a custom `IQueryable` provider?
>
> **A**: Implement `IQueryProvider` (creates queries, executes them) and a class implementing `IQueryable<T>` (wraps an expression tree and the provider). Walk incoming expression trees, translate each LINQ method call (`Where`, `Select`, etc.) to your backend's query language, execute, and materialize results back into `T`. EF Core, LINQ-to-SQL, OData clients, and MongoDB's C# driver all use this pattern.
>
> **Cross-Q**: What's the hardest part of building one?
>
> **A**: **Expression-tree translation completeness**. Real-world queries combine many operators with arbitrary lambda bodies. You have to handle nested closures (capturing local variables), method-call expressions for built-ins (`string.Concat`, `DateTime.Now`), null-coalescing, type tests (`is`, `as`), and the long tail of LINQ operators. EF Core has spent ~15 years refining its translator and still has gaps. A custom provider is a major undertaking unless your target query language is small.
>
> **Cross-Q²**: I just want a thin LINQ facade over a REST API. Do I need a full provider?
>
> **A**: Often no — implement only the operators you need. Define a **narrow `IQueryable<T>`-like interface** in your codebase (`IApiQuery<T>` with `Where(Expression<Func<T, bool>>)`, `OrderBy(...)`, `Take(int)`, `ToListAsync()`) and translate just those. Skip the full `IQueryable` complexity. This is the pattern used by Refit, FlurlHttp, and many Cosmos DB client libraries — looks like LINQ from the call site, doesn't implement the full provider.

</details>

## Cheat Sheet

- **IQueryable**: expression tree; provider translates to SQL/another store; composable without execution.
- **IEnumerable**: in-memory iteration; `foreach`-driven; once you cross to it, you've left the database.
- **Deferred execution**: query runs on materialization (`ToList`, `First`, `Count`, `Any`); enumerating twice runs SQL twice.
- **First vs Single**: `Single` throws on duplicates and surfaces uniqueness bugs; `First` silently picks one.
- **Any vs Count > 0**: `Any()` translates to `EXISTS`; `Count() > 0` scans all matching rows.
- **GroupBy in EF**: must project aggregates immediately; returning the group itself materializes child rows.
- **AsEnumerable boundary**: explicit hop from SQL to LINQ-to-Objects; everything after runs in memory.
- **Contains** on a list: translation is version-dependent — inlined `IN (1,2,3)` through EF 7, a single `OPENJSON` parameter in EF 8/9, one padded scalar parameter per element by default in EF 10. Know which version you're on before you reason about the plan cache.
- **Constants inline, captured variables parameterize.** That is the lever on both EF's compiled-query cache and the server's plan cache; `EF.Constant`/`EF.Parameter` override it.
- **Include cartesian**: multiple collection `Include` joins multiply rows; use `AsSplitQuery` or projections. Split queries trade the single-query consistency guarantee for it.
- **Correlated projection**: one scalar out of a navigation (`c.Orders.Max(...)`, or `...FirstOrDefault()` after a scalar `Select`) → a correlated scalar subquery, portable everywhere. Projecting the whole related entity needs multiple columns → `OUTER APPLY` (SQL Server), `LEFT JOIN LATERAL` (PostgreSQL), `LATERAL` on MySQL 8.0.14+, and SQLite has no `APPLY` at all.
- **Null semantics**: EF expands `!=` on nullable columns into an `IS NULL` OR-chain to preserve C# meaning; `UseRelationalNulls()` opts out for the whole `DbContext`.
- **Collation**: `==` means what the column's collation means. SQL Server/MySQL default case-insensitive, PostgreSQL/SQLite case-sensitive. `StringComparison` overloads throw by design.
- **Translation gotchas**: custom methods throw at runtime (EF 3+) *except* in the top-level projection; verify with `.ToQueryString()`, `LogTo`, or LINQPad's SQL output.
- **Window functions**: EF Core has none (efcore#12747, open, Backlog). Top-N-per-group needs raw SQL, an `APPLY`-shaped projection, or two queries.

## Walkthrough — Client-side evaluation blowing memory

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: After upgrading from EF Core 2 to 6, a reporting endpoint that listed "high-tax orders" now throws `InvalidOperationException: The LINQ expression ... could not be translated`. A team-mate "fixes" it with `.AsEnumerable()` and now the pod OOMs in production.

**Diagnosis**: The senior reviews the change with `git diff` and sees the predicate now reads `.Where(o => CalculateTax(o) > 10)` after `.AsEnumerable()`. They check the underlying `Orders` table size: `SELECT COUNT(*) FROM Orders` returns 14 million. The hop pulls every row into the worker. Confirmed in `dotnet-counters monitor --process-id <pid> System.Runtime`: `gen-2-size` climbs to 4 GB before the OOM kill. EF query log (`LogTo(Console.WriteLine)`) shows `SELECT * FROM Orders` with no `WHERE`.

**Fix**: Push as much filtering into SQL as possible, then hop:

```csharp
var since = DateTime.UtcNow.AddDays(-30);
var candidates = await db.Orders
    .Where(o => o.CreatedAt >= since && o.Total > 100)  // SQL
    .Select(o => new { o.Id, o.Total, o.TaxRate })       // narrow projection
    .AsAsyncEnumerable()                                 // streaming hop
    .Where(o => CalculateTax(o.Total, o.TaxRate) > 10)   // C#
    .ToListAsync();
```

The SQL filter shrinks the working set to a few thousand rows, and `AsAsyncEnumerable` streams instead of buffering.

Two details that decide whether this compiles and whether it's safe. The `Where`/`ToListAsync` operators applied *after* `AsAsyncEnumerable` are LINQ over `IAsyncEnumerable<T>`, which came from the `System.Linq.Async` package until **.NET 10** shipped `System.Linq.AsyncEnumerable` in the box. And streaming holds the reader — and therefore the connection — open for the whole loop, so `CalculateTax` must not itself query this `DbContext`.

**Why it works**: EF can only translate expressions it understands. By moving the translatable predicates into the `IQueryable` and keeping only the C#-only logic after the boundary, you minimize the data crossing into the runtime.

</details>

## Self-test

<details><summary>1. Why does <code>db.Orders.Where(o =&gt; statuses.Contains(o.Status))</code> sometimes generate slow plans on SQL Server?</summary>

Because the SQL text varies with the list, and SQL Server caches a plan per text. Through EF 7 the values were **inlined** (`IN (1, 2, 3)`), so every distinct *set of values* produced its own single-use plan — the cache fills with garbage and evicts the plans that matter, degrading queries that have nothing to do with yours. EF 8 replaced that with one JSON parameter unpacked by `OPENJSON`, which gives one stable plan but hides the collection's length from the optimizer. EF 10 sends one scalar parameter per element and pads the list, so the SQL is stable *and* the cardinality is visible. Whatever the version, a very large list is still better served by a TVP or a temp-table join. Diagnose it on SQL Server with `sys.dm_exec_cached_plans` filtered on `usecounts = 1`.
</details>

<details><summary>2. <code>query.Any()</code> immediately followed by <code>query.First()</code> — what's the issue?</summary>

Two SQL round-trips for the same logical question. Materialise once with `FirstOrDefault()` and check for null, or load to a list and use in-memory `Any` and indexer.
</details>

<details><summary>3. Trade-off: <code>OrderBy(...).Skip(n).Take(m)</code> vs cursor pagination on a 50M-row table.</summary>

Offset pagination is O(n+m): SQL must walk past `n` rows even if indexed. At page 5000 it crawls. Cursor pagination (`WHERE Id < lastSeenId ORDER BY Id DESC LIMIT m`) is O(m) but loses random access (can't jump to page 100). Pick cursor for infinite scroll, offset for jump-to-page UIs with low max page count.
</details>

<details><summary>4. Why is <code>db.Orders.GroupBy(o =&gt; o.Status).ToList()</code> a code smell?</summary>

`GroupBy` without a projection returns groups holding full entities. EF Core may materialise every order into memory. Always follow `GroupBy` with a `.Select` that emits aggregates only.
</details>

<details><summary>5. A junior writes <code>customer.Orders.Where(o =&gt; o.IsActive).Count()</code>. The <code>customer</code> entity is tracked. What runs?</summary>

If `Orders` is a navigation collection that's already loaded, the predicate runs in memory (LINQ-to-Objects). If it's a lazy proxy or unloaded, the access triggers a full collection load, then the predicate. Either way it scans every order. Better: `db.Orders.CountAsync(o =&gt; o.CustomerId == customer.Id &amp;&amp; o.IsActive)`.
</details>

<details><summary>6. A helper method works inside <code>.Select(...)</code> but throws inside <code>.Where(...)</code>. Is that a bug?</summary>

No — it's the documented boundary. EF Core "supports partial client evaluation in the top-level projection (essentially, the last call to `Select()`)" and throws for untranslatable expressions anywhere else (Microsoft Learn, *Client vs. Server Evaluation*). The reason is economic: client-evaluating a projection post-processes rows the server already selected, while client-evaluating a filter forces every row across the wire so C# can discard most of them.
</details>

<details><summary>7. <code>Where(o =&gt; o.CancelReason != "Duplicate")</code> in EF Core returns more rows than the DBA's <code>WHERE cancel_reason &lt;&gt; 'Duplicate'</code>. Who is wrong?</summary>

Neither — they're different questions. SQL is three-valued: `NULL <> 'Duplicate'` evaluates to `NULL`, and `WHERE` keeps only `true`, so the DBA's query drops every row with a null reason. C# is two-valued and `null != "Duplicate"` is `true`, so EF injects compensation — roughly `([CancelReason] <> @p OR [CancelReason] IS NULL)` — to preserve that meaning. If you want SQL's semantics from LINQ, opt in with `UseRelationalNulls()`; if you want C#'s semantics in hand-written SQL, use `IS DISTINCT FROM` (PostgreSQL, or SQL Server 2022+). MySQL has no `IS DISTINCT FROM` — its null-safe operator `<=>` is the *equality* one, so the `!=` equivalent is `NOT (cancel_reason <=> 'Duplicate')`.
</details>

<details><summary>8. Two teams get different results from <code>Where(u =&gt; u.Email == input)</code> — one on SQL Server, one on PostgreSQL. Why, and what's the wrong fix?</summary>

Collation. EF translates C# `==` straight to SQL `=` and makes no attempt to impose case sensitivity, so the comparison means whatever the column's collation means. SQL Server and MySQL default to case-insensitive collations; PostgreSQL and SQLite are case-sensitive by default. The wrong fix is `u.Email.ToLower() == input.ToLower()`, which wraps the indexed column in a function and disqualifies the index for the entire lookup. Set the collation on the column (or use `citext` on PostgreSQL) so the comparison is both correct and indexed.
</details>

<details><summary>9. Trade-off: <code>Include(o =&gt; o.Items).Include(o =&gt; o.Payments)</code> vs the same with <code>AsSplitQuery()</code>.</summary>

Single query: one round trip, one consistent snapshot, and a cartesian product — `items × payments` rows per order, with the order's own columns repeated in every one of them. Split query: one query per collection, so rows are additive rather than multiplicative, but you pay a round trip each, earlier results must be buffered in memory (most providers allow one active reader per connection), and you lose the single-query consistency guarantee — concurrent writes between the two statements can return data that doesn't agree with itself. If you don't need tracked entities, a projection usually beats both.
</details>

<details><summary>10. You call <code>ExecuteUpdateAsync</code> on rows you already loaded, then <code>SaveChangesAsync</code>. What ends up in the database?</summary>

It depends on whether the tracked entities are also modified — and that is the answer the interviewer wants. `ExecuteUpdate` executes immediately and has no interaction with the change tracker, so the tracked entities still carry the original values read before the bulk statement. `SaveChanges` writes only the properties it considers modified: touch nothing and it emits no `UPDATE` at all, but modify the entity (or call `Update()`, which marks every property modified) and it compares against those stale originals and writes them back, silently undoing the bulk update. There's also no shared transaction — each statement commits on its own unless you open one with `context.Database.BeginTransaction()`.
</details>

<details><summary>11. Your paged endpoint's plan shows an <code>Index Seek</code>, and it's slow. What number do you look at?</summary>

Rows read versus rows returned. A seek only means the engine could position the scan using an index key — it says nothing about how far the scan then ran, or how many of those rows a residual predicate discarded. SQL Server's actual plan shows **Number of Rows Read** alongside **Actual Number of Rows**, and separates **Seek Predicates** from **Predicate**; PostgreSQL shows `Index Cond` versus `Filter` with `Rows Removed by Filter`. Then check for a `Sort` operator: if the index doesn't already return rows in the requested order, the engine sorts the whole matching set under a memory grant, and an underestimate makes it spill to `tempdb`.
</details>

## Cross-references

- **Deep-dive: [LINQ and Data Querying](../01-foundations/01-net-core-deep-dive/05-data-access.md#12-linq-and-data-querying)** — IQueryable vs IEnumerable, deferred vs immediate.
- [EF Core](./01-ef-core.md) — LINQ is what you write; EF Core translates to SQL.
- [SQL](./03-sql/README.md) — what LINQ becomes.
- [Data Structures](../01-foundations/03-data-structures.md) — LINQ-to-Objects operates on these.
- [Searching Algorithms](../01-foundations/04-searching-algorithms.md) — `Where`, `First`, `Any` are linear searches.

_Add chapter-specific notes or extensions below as you study._

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [LINQ overview](https://learn.microsoft.com/en-us/dotnet/csharp/linq/).
- Microsoft Learn — [LINQ to Entities translatability](https://learn.microsoft.com/en-us/ef/core/querying/) (per EF Core version).
- Microsoft Learn — [Client vs. server evaluation](https://learn.microsoft.com/en-us/ef/core/querying/client-eval) — the top-level-projection exception.
- Microsoft Learn — [Comparisons with null values in queries](https://learn.microsoft.com/en-us/ef/core/querying/null-comparisons) — three-valued logic, generated compensation SQL, `UseRelationalNulls`.
- Microsoft Learn — [Complex query operators](https://learn.microsoft.com/en-us/ef/core/querying/complex-query-operators) — `Join`/`GroupJoin`/`SelectMany`/`GroupBy` translation rules, `CROSS APPLY` vs `LEFT JOIN`.
- Microsoft Learn — [Single vs. split queries](https://learn.microsoft.com/en-us/ef/core/querying/single-split-queries) — cartesian explosion and the consistency trade-off.
- Microsoft Learn — [Advanced performance topics](https://learn.microsoft.com/en-us/ef/core/performance/advanced-performance-topics) — query caching and parameterization, compiled queries, dynamically-constructed queries.
- Microsoft Learn — [SQL Server provider function mappings](https://learn.microsoft.com/en-us/ef/core/providers/sql-server/functions) — the authoritative "does it translate" table, with an *Added in* column.
- Microsoft Learn — [Collations and case sensitivity](https://learn.microsoft.com/en-us/ef/core/miscellaneous/collations-and-case-sensitivity) — engine defaults and the index cost of forcing a comparison.
- Microsoft Learn — [ExecuteUpdate and ExecuteDelete](https://learn.microsoft.com/en-us/ef/core/saving/execute-insert-update-delete) — change-tracker and transaction semantics.
- Microsoft Learn — [Query tags](https://learn.microsoft.com/en-us/ef/core/querying/tags) — `TagWith`, `TagWithCallSite`.
- Microsoft Learn — [What's New in EF Core 10](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-10.0/whatsnew) — parameterized-collection translation modes, `LeftJoin`/`RightJoin`, split-query ordering fix.
- Microsoft Learn — [ORDER BY clause (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/select-order-by-clause-transact-sql) — `OFFSET`/`FETCH` requirements and stable-paging conditions.
- Microsoft Learn — [Data type precedence (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/data-types/data-type-precedence-transact-sql) — why an `nvarchar` parameter against a `varchar` column converts the column.
- dotnet/efcore — [#12747, Support SQL window functions](https://github.com/dotnet/efcore/issues/12747) — open Epic, Backlog milestone; why EF Core still has no built-in window functions.
- MySQL Reference Manual — [Lateral derived tables](https://dev.mysql.com/doc/refman/8.0/en/lateral-derived-tables.html) — `LATERAL` from MySQL 8.0.14.
- *Pro LINQ in C#* by Joseph Rattz, Adam Freeman (Apress, 2014) — operator-by-operator reference.
- LINQPad — [linqpad.net](https://www.linqpad.net/) — interactive LINQ playground; shows generated SQL.

<!-- nav-footer-start -->

---

[← Previous: EF Core](01-ef-core.md) · [↑ Back to top](#linq) · [Next: SQL Mastery — Basics to Advanced →](03-sql/README.md)

<!-- nav-footer-end -->

</details>
