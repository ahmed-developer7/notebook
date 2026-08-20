# EF Core

> [Mastery Guide](../README.md) › [Data & Persistence](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-07 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts (chapter extensions)](#core-concepts-chapter-extensions)
  - [Migrations workflow](#migrations-workflow)
  - [Concurrency control](#concurrency-control)
  - [Performance hot spots beyond AsNoTracking](#performance-hot-spots-beyond-asnotracking)
  - [Splitting reads from writes](#splitting-reads-from-writes)
  - [Reading the SQL EF Core generates](#reading-the-sql-ef-core-generates)
  - [Parameters, constants, and the plan cache](#parameters-constants-and-the-plan-cache)
  - [Transactions, isolation, and the retry trap](#transactions-isolation-and-the-retry-trap)
  - [What SaveChanges actually sends](#what-savechanges-actually-sends)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--n1-killing-the-orders-list-endpoint)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

The deep-dive ([Entity Framework Core](../01-foundations/01-net-core-deep-dive/05-data-access.md#11-entity-framework-ef-and-ef-core)) covers EF Core's core mechanics: DbContext, change tracking, CRUD, the EF vs EF Core comparison, and bulk operations. This file extends with chapter-specific topics that tend to come up in advanced/interview contexts: migrations workflow, concurrency control (optimistic vs pessimistic), performance pitfalls beyond `AsNoTracking`, and CQRS-flavoured read/write separation.

The thing an EF Core interview is usually testing is not EF Core. It is whether you can hold the C# and the SQL in your head at the same time — whether, when someone says "the orders endpoint got slow", you reach for the generated statement and its plan rather than for another `AsNoTracking()`. Every section below is written to that boundary: what the LINQ becomes, what the database does with it, and where the two stop agreeing.

> 🌍 **In the real world**: an interview question that reliably separates candidates is "show me the SQL your last query generated." Plenty of ten-year .NET engineers have never once printed it. The tell isn't ignorance of `ToQueryString()` — it's that when the follow-up comes ("why is that a seek on one column and a scan on the other?") there's nothing to reason from, because the SQL was never a thing they looked at. Reading generated SQL is not an advanced skill; it's the entry price for every other topic on this page.

## Core concepts (chapter extensions)

### Migrations workflow

EF Core migrations track schema changes as code. Each migration is a C# class with `Up()` (apply change) and `Down()` (rollback). The migration history table (`__EFMigrationsHistory`) tracks which have been applied to a database.

```bash
# Add a migration after model changes
dotnet ef migrations add AddOrderStatusIndex

# Apply pending migrations to the DB
dotnet ef database update

# Rollback to a specific migration
dotnet ef database update PreviousMigrationName

# Generate idempotent SQL for production deployment
dotnet ef migrations script --idempotent --output deploy.sql
```

**Production migration patterns:**
1. **Never run `database update` from app startup in production.** Generate SQL scripts in CI; apply via DBA tooling or migration runner pod.
2. **Backward-compatible migrations.** Deploy schema change first (additive), then code that uses it. Allows zero-downtime rolling deploys.
3. **Online schema changes for big tables.** A plain index build holds a lock that blocks writers for as long as the build runs, and on a large table that is not a short time. Each engine's escape hatch is different and none of them is what `migrationBuilder.CreateIndex` emits:
   - **SQL Server** — `CREATE INDEX ... WITH (ONLINE = ON)`. Microsoft documents that "online index operations aren't available in every edition of SQL Server" (Microsoft Learn, *Perform index operations online*), so verify the edition before writing a runbook around it.
   - **PostgreSQL** — `CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction block. EF Core wraps migrations in a transaction by default, so this needs `migrationBuilder.Sql("CREATE INDEX CONCURRENTLY ...", suppressTransaction: true)`.
   - **MySQL** — online DDL where the operation supports it, or `pt-online-schema-change` / `gh-ost` where it doesn't.
4. **Migrations must be idempotent.** The `--idempotent` flag generates `IF NOT EXISTS` checks so re-running is safe.

> 🌍 **In the real world**: a scaffolded migration adding one index to a PostgreSQL orders table was applied at 10am because it was "one line". EF Core ran it inside the migration transaction with a plain `CREATE INDEX`, the build took a lock that queued every writer behind it, and checkout began timing out while the migration job sat there looking healthy. Nothing had failed — the runner was still running. The repair was to hand-edit the migration to `migrationBuilder.Sql(..., suppressTransaction: true)` with `CONCURRENTLY` and re-run it that evening. The generic lesson is that the scaffolder writes correct DDL for an empty table and has no idea how big yours is; the migration file is a draft, not an artefact.

> 🌍 **In the real world**: a team ran `MigrateAsync()` in `Program.cs` for two years without incident, because the deployment had always been one pod. Moving to a rolling deploy with three replicas turned the first migration into three instances racing to apply the same script. Two failed to start, the orchestrator restarted them, they raced again, and the outage was reported as "the new image is broken". Know the version boundary here, because interviewers do: **EF Core 9 and later** acquire a database-wide lock in `Migrate`/`MigrateAsync` so only one application can run migrations at a time; on **EF Core 8 and earlier** there is no such lock and concurrent callers genuinely race. Either way the lock only removes one failure mode. It doesn't stop the app account needing `ALTER TABLE` rights, and it doesn't stop every deploy being coupled to every schema change. The fix was one CI step: `dotnet ef migrations script --idempotent`, applied by a job that runs once, before the app rollout starts.

```csharp
public partial class AddOrderStatusIndex : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.CreateIndex(
            name: "IX_Orders_Status_CreatedAt",
            table: "Orders",
            columns: new[] { "Status", "CreatedAt" });
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropIndex(name: "IX_Orders_Status_CreatedAt", table: "Orders");
    }
}
```

### Concurrency control

Two strategies for "user A and user B both edit the same row":

**Optimistic concurrency** is what EF Core implements: no locks are taken, and the save is arranged to *fail* if the row changed since it was read. The whole mechanism is one extra predicate and one row count. EF adds the concurrency token to the `UPDATE`'s `WHERE`, then compares rows affected against rows expected:

```csharp
public class Order
{
    public int Id { get; set; }
    public string Status { get; set; } = "";

    [Timestamp]                    // SQL Server: maps to a rowversion column
    public byte[] RowVersion { get; set; } = Array.Empty<byte>();
}
```

```sql
-- What SaveChanges sends. Note both predicates.
UPDATE [Orders] SET [Status] = @p0
WHERE [Id] = @p1 AND [RowVersion] = @p2;
```

One row affected → committed. Zero rows affected → the row no longer matches the value we read, and EF throws `DbUpdateConcurrencyException`.

**The default without a token is not optimistic concurrency — it is last-write-wins.** With no concurrency token configured, the `WHERE` clause is the primary key alone. Two users editing the same row both get "1 row affected" and the second silently overwrites the first. EF still checks rows-affected on every update and delete, so it will still throw if the row is *gone*; it cannot possibly notice that the row *changed*, because it never asked. Note also that EF only sends columns it detected as modified, which is why the corruption is usually partial and therefore hard to reproduce: two users editing disjoint fields of the same row both succeed and nothing looks wrong.

**Engine differences, and this one bites.** `[Timestamp]` / `IsRowVersion()` is not portable behaviour, it is a request for a database-generated, self-incrementing token, and each engine answers differently:

| Engine | Automatic token | Property type |
|---|---|---|
| SQL Server | `rowversion` column, incremented by the engine on every update | `byte[]` |
| PostgreSQL (Npgsql) | the `xmin` system column — the ID of the last transaction to update the row | `uint` |
| SQLite | none — Microsoft Learn names it explicitly as a database with no such type | n/a |

Microsoft's own wording is the safe thing to repeat in an interview: "The `rowversion` type shown above is a SQL Server-specific feature; the details on setting up an automatically-updating concurrency token differ across databases, and some databases don't support these at all" (Microsoft Learn, *Handling Concurrency Conflicts*). Where no native type exists, use an **application-managed token** — `[ConcurrencyCheck]` or `.IsConcurrencyToken()` on a `Guid`/`int` you assign yourself. That is also the better choice when you want control over *which* column changes should count as a conflict; a `rowversion` protects the whole row, including the cached-total column you don't care about.

Resolution has three value sets available on the failed entry, and knowing their names is half the answer:

```csharp
try
{
    order.Status = "Cancelled";
    await db.SaveChangesAsync();
}
catch (DbUpdateConcurrencyException ex)
{
    var entry = ex.Entries.Single();
    var proposed = entry.CurrentValues;                        // what we tried to write
    var original = entry.OriginalValues;                       // what we read
    var database = await entry.GetDatabaseValuesAsync();       // what is there now

    // Merge as the domain requires, then make the retry pass the check:
    entry.OriginalValues.SetValues(database);
    await db.SaveChangesAsync();
}
```

That last line is the one people miss, and it is also the one that quietly causes bugs. Refreshing `OriginalValues` from the database is what lets the retry's `WHERE` clause match — without it, the retry fails identically, forever. But it *only* moves the token: `CurrentValues` still holds whatever your handler computed from the values it read before the conflict. If that computation depended on the old value, refreshing the original and retrying will now happily commit a stale answer. That is the difference between a retry loop that recovers and one that launders bad data through a passing concurrency check.

**Pessimistic concurrency:** lock rows during read so others wait. Acceptable for short transactions; deadlock-prone otherwise. There is no EF Core API for it — you drop to provider SQL, and **the lock only lives as long as the transaction**, so an example without a transaction is an example of nothing:

```csharp
await using var tx = await db.Database.BeginTransactionAsync();

// SQL Server: locking hints
var order = await db.Orders
    .FromSql($"SELECT * FROM Orders WITH (UPDLOCK, ROWLOCK) WHERE Id = {id}")
    .SingleAsync();

// PostgreSQL / MySQL InnoDB: standard row-level locking read
// .FromSql($"SELECT * FROM orders WHERE id = {id} FOR UPDATE")

order.Status = "Cancelled";
await db.SaveChangesAsync();
await tx.CommitAsync();          // lock released here, not before
```

(`FromSql` is the EF Core 7+ name; on older versions the interpolating overload is `FromSqlInterpolated`. Both parameterise the holes — see Drill 12 for why the `Raw` variant does not.)

`FromSql` has real constraints worth knowing before you reach for it: the SQL must return **every** column the entity type maps, result column names must match the mapped column names, it can only be called directly on a `DbSet` (not composed onto an arbitrary LINQ query), and it cannot pull in related data — you add `Include` on top instead. Anything EF composes over it becomes a subquery, so a trailing semicolon or a bare `ORDER BY` will produce invalid SQL (Microsoft Learn, *SQL Queries*).

There is also a third option the guide's SQL chapter covers and candidates rarely name: **let the isolation level do it.** Microsoft documents the split precisely — SQL Server's `REPEATABLE READ` takes a shared lock on the row when you query it, so the competing writer *blocks*; SQL Server's `SNAPSHOT` and PostgreSQL's `REPEATABLE READ` let the competing writer proceed and raise a **serialization error** on your update instead. Same isolation level name, opposite failure mode: one waits, the other aborts. See [Transactions & Concurrency](./03-sql/07-transactions-and-concurrency.md). The catch is that it needs a transaction spanning the whole read-modify-write, which rules it out the moment a human sits in the middle of it.

Default to optimistic. Use pessimistic only when conflict rate is high enough that retry storms exceed lock cost (rare in app code; more common in batch jobs).

> 🌍 **In the real world**: an inventory service had `[Timestamp]` on every entity and a textbook retry loop, and still oversold stock during a flash sale. The token was doing its job — the `UPDATE` genuinely failed on conflict — and the retry handler was doing what the sample code does: catch, `entry.OriginalValues.SetValues(await entry.GetDatabaseValuesAsync())`, save again. What it never did was recompute. The handler had read stock as 40 and set `CurrentValues` to 39; refreshing the *original* values made the second `UPDATE` match, and it wrote 39 over a row that was by then at 31. The conflict was detected, reported, handled, and then overwritten anyway. Optimistic concurrency protects the row, not the arithmetic — a retry that doesn't redo the calculation is a retry that turns a caught exception into silent corruption. The fix was to stop reading-and-computing at all: `Where(p => p.Stock >= qty).ExecuteUpdateAsync(s => s.SetProperty(p => p.Stock, p => p.Stock - qty))`, then check the returned rows-affected count. The predicate and the decrement evaluate in one statement, so there is no window to be stale in.

> 🌍 **In the real world**: a service ported from SQL Server to PostgreSQL kept `[Timestamp] public byte[] RowVersion`, and every save started failing with a type error nobody recognised — because Npgsql wants a `uint` mapped to `xmin`, not a `byte[]` mapped to a column that doesn't exist. The team's first instinct was to delete the attribute, which compiled, passed tests, and shipped an application with no concurrency control at all. This is the failure mode worth internalising: concurrency tokens are the one feature where removing it looks exactly like fixing it, because nothing throws afterwards. Nothing throws *ever* again — that's the problem.

### Performance hot spots beyond AsNoTracking

The deep-dive mentions `AsNoTracking()`. Other top-tier optimizations:

**1. Compiled queries — for the translation cost, not the query cost:**
```csharp
private static readonly Func<AppDbContext, int, Task<Order?>> GetOrderByIdQuery =
    EF.CompileAsyncQuery((AppDbContext db, int id) =>
        db.Orders.FirstOrDefault(o => o.Id == id));

public Task<Order?> GetByIdFastAsync(int id) => GetOrderByIdQuery(_db, id);
```

Be exact about what this saves, because the follow-up question is always "how much?". EF already caches compilation output keyed by the query tree's *shape*, so re-running the same LINQ is fast. But EF still has to walk your expression tree and compare it against cached ones to find the entry — that lookup is what a compiled query skips, by handing you the delegate directly. Microsoft's own framing is that "the overhead for this initial processing is negligible in the majority of EF applications, especially when compared to other costs associated with query execution (network I/O, actual query processing and disk I/O at the database)"; the docs publish a benchmark and then tell you to run your own (Microsoft Learn, *Advanced Performance Topics*). Two documented limits: a compiled query works against a **single model** only, and its parameters must be **simple scalars** — member or method accesses on instances aren't supported.

**2. Projections — never load what you won't show:**
```csharp
// ❌ Loads entire Order including 50 columns + relations
var orders = await db.Orders.Where(o => o.Status == "Pending").ToListAsync();

// ✅ Projects to only what the API needs
var orders = await db.Orders
    .Where(o => o.Status == "Pending")
    .Select(o => new OrderListDto(o.Id, o.Total, o.CreatedAt))
    .ToListAsync();
```

Three things happen at once here, and it's worth separating them: the `SELECT` list narrows to three columns; no snapshot is taken because the result isn't an entity; and no identity-map entry is made. **The caveat is that "projection" is about what the projection *contains*, not that you wrote `Select`.** `Select(o => new { o, o.Customer })` projects to an anonymous type but the `Order` and `Customer` inside it are still entities, so they are still tracked and still snapshotted. `AsNoTracking()` after a projection that contains no entity types changes nothing at all.

The other half of "project only what you need" is that a covering index's contract is written in your DTO. Add one property to the record, and the generated `SELECT` grows a column the index doesn't include, and the plan grows a lookup per row. See [Indexes & Query Optimization](./03-sql/06-indexes-and-query-optimization.md#covering-indexes-include).

**3. `ExecuteUpdate` / `ExecuteDelete` (EF Core 7+) for set-based writes:**
```csharp
// ❌ Queries every row, materialises it, tracks it, then emits one DELETE per row
foreach (var order in await db.Orders.Where(o => o.Status == "Cancelled").ToListAsync())
{
    db.Orders.Remove(order);
}
await db.SaveChangesAsync();

// ✅ Single SQL DELETE, nothing materialised, change tracker never involved
await db.Orders.Where(o => o.Status == "Cancelled").ExecuteDeleteAsync();
```

The semantics are genuinely different from `SaveChanges` and the differences are what get asked about:

- **They execute immediately**, at the point of the call — they don't accumulate and they can't be batched with each other. Each invocation is its own roundtrip.
- **They don't start a transaction.** Two `ExecuteUpdate` calls in a row are two independent transactions; if the second fails, the first is committed. Wrap them yourself with `BeginTransactionAsync` when they must be atomic.
- **The change tracker doesn't hear about them.** Microsoft's example is worth memorising: query a blog with `Rating = 5`, `ExecuteUpdate` every blog's rating `+ 1` (database is now 6), then set `blog.Rating += 2` in memory (tracked instance is now 7, original snapshot still 5) and `SaveChanges` — EF writes 7, and the `ExecuteUpdate` is silently overwritten. Don't mix tracked and untracked modification of the same rows in one unit of work.
- **No automatic concurrency check** — there is no token comparison, because there is no tracked original. Both methods return the rows-affected count, which is how you implement the check by hand: put the token in the `Where`, then assert the count.

**4. Avoid N+1 with `Include`, `ThenInclude`, or split queries:**
```csharp
// Single query with JOIN
var orders = await db.Orders
    .Include(o => o.Customer)
    .Include(o => o.Items).ThenInclude(i => i.Product)
    .ToListAsync();

// Or split queries (avoids cartesian explosion when including multiple collections)
var orders = await db.Orders
    .Include(o => o.Items)
    .AsSplitQuery()
    .ToListAsync();
```

Cartesian explosion needs one precision that trips people up in interviews: it happens when the collections are **siblings**, not merely when there are two of them. `Include(b => b.Posts).Include(b => b.Contributors)` cross-products, because both hang off the same parent. `Include(b => b.Posts).ThenInclude(p => p.Comments)` does not, because comments hang off posts — you get one row per comment, which is the number of rows you actually wanted.

And `AsSplitQuery()` is a trade, not a free win. Microsoft lists what you give up: **no consistency guarantee** across the separate queries (a concurrent write between them can produce a result set that never existed — mitigate with a snapshot or serializable transaction, at its own cost), one extra roundtrip per collection, and buffering of all but the last result set into application memory because most databases won't keep two result sets open at once. On EF versions before 10, `AsSplitQuery` with `Skip`/`Take` also requires a **fully unique ordering** — order by date alone and each split query can page differently and return mismatched data.

> 🌍 **In the real world**: a dashboard endpoint was fixed by adding `AsSplitQuery()` to a query with three `Include`d collections, and the row count and the latency both dropped as expected. The bug that came back three weeks later was a support ticket saying an order showed a total that didn't match the sum of its lines — during the seconds between the parent query and the child query, a line had been added. Nobody could reproduce it, because reproducing it requires writing to the row between two statements. Split queries move you from one consistent statement to several independently-consistent ones, and on a busy table that difference is a real, if rare, class of defect. If the numbers have to agree, either project the aggregate in SQL so it is computed in one statement, or run the split query inside a snapshot transaction.

### Splitting reads from writes

Heavy-read workloads (dashboards, search) benefit from a separate read model:

```csharp
// Write side — full DbContext, change tracking
public class OrderCommandService(AppDbContext writeDb) { /* SaveChangesAsync */ }

// Read side — different connection, possibly read replica, AsNoTracking by default
public class OrderQueryService(ReadOnlyDbContext readDb)
{
    public async Task<List<OrderListDto>> ListAsync()
        => await readDb.Orders.AsNoTracking()
            .Select(o => new OrderListDto(o.Id, o.Total))
            .ToListAsync();
}
```

In `Program.cs`:

```csharp
builder.Services.AddDbContext<AppDbContext>(opt =>
    opt.UseSqlServer(builder.Configuration.GetConnectionString("Primary")));

builder.Services.AddDbContext<ReadOnlyDbContext>(opt =>
    opt.UseSqlServer(builder.Configuration.GetConnectionString("ReadReplica"))
       .UseQueryTrackingBehavior(QueryTrackingBehavior.NoTracking));
```

This is the pragmatic step toward CQRS without going full event-sourced — see [CQRS](../04-architecture-and-patterns/05-cqrs.md).

The moment you point reads at a replica you have accepted **replica lag**, and that is a product decision, not an infrastructure detail. The read-your-own-writes case is the one that generates tickets: a user saves a form, gets redirected to a list page served from the replica, and their change isn't there. Nothing is broken; the write simply hasn't arrived yet. The available answers are all boring and all deliberate — route the immediately-following read back to the primary, return the updated resource from the write endpoint so the UI doesn't have to re-fetch, or use the engine's own guarantee where it has one (SQL Server availability groups and PostgreSQL streaming replication both expose synchronous modes, at the cost of write latency). What you must not do is discover the trade-off from a bug report.

> 🌍 **In the real world**: a team split reads onto a replica and shipped it on a Thursday. Everything was fine until the following week's incident, when replication lag spiked to several seconds under a bulk import and the admin UI started showing orders in a state they had already been moved out of. Operations staff, reasonably, clicked the button again. The duplicate actions were the actual damage — the stale reads were merely how it started. Two changes closed it: the write endpoints returned the new resource state instead of redirecting to a list, and the lag metric got an alert so that "the replica is behind" became something the team knew before the users did.

### Reading the SQL EF Core generates

Everything downstream of this section depends on being able to see the statement. Three tools, in increasing order of how much you get:

```csharp
// 1. One query, no execution — prints the SQL that WOULD run. EF Core 5+.
var query = db.Orders.Where(o => o.Status == status).OrderBy(o => o.CreatedAt);
Console.WriteLine(query.ToQueryString());

// 2. Every query the context runs, with timings. Development only.
optionsBuilder
    .LogTo(Console.WriteLine, LogLevel.Information)
    .EnableSensitiveDataLogging();     // includes parameter VALUES — never in production
```

`EnableSensitiveDataLogging` is exactly what its name says: it puts the parameter values into your logs, which means customer data in your logs. It is a development switch. The default redaction is there for a reason, and EF Core 10 extended it — inlined constants are now redacted from logs too unless you opt in.

The third tool is the one senior candidates mention and nobody else does:

```
> dotnet counters monitor Microsoft.EntityFrameworkCore -p <pid>

[Microsoft.EntityFrameworkCore]
    Queries (Total)                                            98,402
    Query Cache Hit Rate (%)                                      100
    Optimistic Concurrency Failures (Total)                         0
    SaveChanges (Total)                                             1
```

Those are the *event counter* names, which Microsoft now documents as the legacy mechanism. EF Core 9 added reporting through `System.Diagnostics.Metrics` under the same `Microsoft.EntityFrameworkCore` meter, where the equivalents are `microsoft.entityframeworkcore.queries` and the hit rate arrives as its two ingredients, `compiled_query_cache_hits` and `compiled_query_cache_misses`. Same signal, different names — know which one your version and your dashboard are actually reading.

**Query Cache Hit Rate is a diagnostic, not a vanity metric.** Microsoft's guidance: "In a normal application, this metric reaches 100% soon after program startup... If this metric remains stable below 100%, that is an indication that your application may be doing something which defeats the query cache." A rate that settles anywhere below 100% and stays there means some code path is producing a new query tree shape on every call — which is the subject of the next section, and which is also quietly poisoning the database's plan cache.

One version note that will save you a confused afternoon: **EF Core 10 renamed generated parameters.** `@__city_0` became `@city`. That is a readability win, but the docs flag the consequence — parameter names are part of the SQL text, so upgrading "may also cause almost all cached query plans to be recompiled on the database server", and large systems should expect a temporary compilation spike immediately after deployment. Snapshot tests that assert on SQL strings break too.

> 🌍 **In the real world**: an endpoint that had been fine for a year got slow after a release that "only changed the DTO". The team spent a day on the C#: profiling the handler, checking allocations, arguing about `AsNoTracking`. `ToQueryString()` on the query would have shown it in a minute — the projection had gained one column, the covering index no longer covered, and the plan had grown a key lookup per row. The lesson isn't about indexes; it's about which artefact you reach for first. When latency changes and the C# looks innocent, the C# usually is innocent. Print the SQL.

### Parameters, constants, and the plan cache

This is the section that connects LINQ to everything a DBA will ask you about, and it is the one most .NET engineers have never had to defend.

EF caches its compilation output keyed by the **shape of the expression tree**. A captured variable becomes a parameter and preserves the shape; a literal becomes a constant and changes it:

```csharp
// Two different trees → EF compiles twice → two different SQL texts → two plans on the server
var post1 = await db.Posts.FirstOrDefaultAsync(p => p.Name == "post1");
var post2 = await db.Posts.FirstOrDefaultAsync(p => p.Name == "post2");
```
```sql
SELECT TOP(1) [b].[Id], [b].[Name] FROM [Posts] AS [b] WHERE [b].[Name] = N'post1'
SELECT TOP(1) [b].[Id], [b].[Name] FROM [Posts] AS [b] WHERE [b].[Name] = N'post2'
```
```csharp
// One tree → compiled once → one parameterised SQL text → one reusable plan
var postName = "post1";
var post1 = await db.Posts.FirstOrDefaultAsync(p => p.Name == postName);
```
```sql
SELECT TOP(1) [b].[Id], [b].[Name] FROM [Posts] AS [b] WHERE [b].[Name] = @__postName_0
```

(These are the SQL fragments Microsoft Learn publishes in *Advanced Performance Topics*, with the captured variable renamed here for consistency — the docs' own example uses `postTitle`, so the parameter there reads `@__postTitle_0`. Two things to take from them: the parameter name shape is pre-EF-10 — EF 10 would render it `@postName` — and `FirstOrDefaultAsync` produces `TOP(1)`, which is the correct answer to a question further down this page.)

**Where this actually goes wrong is dynamic query construction.** Building a `Where` predicate with the `Expression` API and an `Expression.Constant` node produces a new tree shape for every value, so EF recompiles every call *and* the server accumulates a distinct plan per value. Microsoft's own note on the pattern: "Even if the sub-millisecond difference seems small, keep in mind that the constant version continuously pollutes the cache and causes other queries to be re-compiled, slowing them down as well." The fix is to build the node as a captured-variable reference rather than a constant — or, far better, not to touch the `Expression` API at all and compose plain lambdas.

**Engine difference, and it's the one that decides how much you should care.** EF's own compilation cache behaves the same everywhere — that half of the cost is engine-independent. The *server* half is not. SQL Server implicitly maintains an LRU query plan cache, so plan-cache pollution there is a real, shared-resource problem: a flood of single-use plans evicts plans that other queries were relying on. PostgreSQL does not maintain an equivalent server-side cache; prepared statements produce a similar effect, but per connection rather than server-wide. EF's docs say only that plan-cache management "is database-dependent" and point you at your engine's documentation — which is the correct instinct to copy. Same C#, different blast radius.

#### The `Contains` / `IN` translation, and why the default changed twice

This is a great interview question because it has a real history, a real trade-off, and no correct universal answer.

```csharp
int[] ids = [1, 2, 3];
var blogs = await db.Blogs.Where(b => ids.Contains(b.Id)).ToListAsync();
```

| EF version | Generated SQL (SQL Server) | The problem it had |
|---|---|---|
| ≤ 7 | `WHERE [b].[Id] IN (1, 2, 3)` — values inlined as constants | New SQL text per distinct list → recompilation and plan-cache churn |
| 8–9 | `WHERE [b].[Id] IN (SELECT [i].[value] FROM OPENJSON(@__ids_0) WITH ([value] int '$') AS [i])` | One plan for all list sizes — but the optimizer can't see the list's cardinality, and Microsoft records that it "can be dramatically less efficient in a minority of cases, even causing query timeouts". Also unsupported on SQL Server 2014 and below, or at compatibility level < 130 |
| 10 | `WHERE [b].[Id] IN (@ids1, @ids2, @ids3)` — one scalar parameter per element | The stated rationale: it "provides the query planner with cardinality information about the collection, which can lead to better query plans in many scenarios. The multiple parameter approach balances between plan cache efficiency (by parameterizing) and query optimization (by providing cardinality)" |

You control it globally or per query:

```csharp
// Global — EF Core 10 API
opt.UseSqlServer(cs, o => o.UseParameterizedCollectionMode(ParameterTranslationMode.Constant));
// Modes: MultipleParameters (EF10 default) | Parameter (JSON array, EF8–9 default) | Constant (pre-EF8)
// On EF Core 9 the equivalent is o.TranslateParameterizedCollectionsToConstants().
// On EF Core 8, SQL Server only, the lever is o.UseCompatibilityLevel(120).

// Per query
db.Blogs.Where(b => EF.Constant(ids).Contains(b.Id))            // inline constants        (EF8+)
db.Blogs.Where(b => EF.Parameter(ids).Contains(b.Id))           // single JSON parameter   (EF9+)
db.Blogs.Where(b => EF.MultipleParameters(ids).Contains(b.Id))  // one parameter each      (EF10)
```

What the question is really testing: do you understand that **parameterisation is a trade between plan reuse and plan quality**? A parameter lets one plan serve every call, which is what you want when the values are interchangeable. A constant lets the optimizer see the actual value and the actual cardinality, which is what you want when they aren't — a filtered index or a wildly skewed column. That is the same trade as parameter sniffing, arriving through a LINQ operator.

> 🌍 **In the real world**: an upgrade from EF Core 7 to 8 made one report time out and left every other query alone. The report passed a list of a few thousand account IDs to `Contains`. Under EF 7 that list had been inlined, so SQL Server could see it was large and chose a hash join; under EF 8 it became a single `OPENJSON` parameter the optimizer could not size, so it estimated small, picked a nested loop, and then ran it against thousands of rows. Nothing in the application had changed — not the query, not the data, not the indexes. The one-line repair was `EF.Constant(ids)` on that query alone, and the durable lesson was that a translation change is a plan change, and a plan change is a performance change. Read the breaking-change list before a major EF upgrade the way you'd read one for the database itself.

### Transactions, isolation, and the retry trap

**The default.** If the provider supports transactions, everything in one `SaveChanges` call runs in one transaction: it "is guaranteed to either completely succeed, or leave the database unmodified if an error occurs." Note the scope — *one call*. Three `SaveChanges` calls are three transactions.

**Savepoints.** Since EF Core 5, if a transaction is already open when you call `SaveChanges`, EF creates a savepoint first and rolls back to it on failure, leaving the transaction usable so you can resolve a concurrency conflict and retry. The documented exception is worth carrying: savepoints are **incompatible with SQL Server MARS**, and EF simply won't create them when MARS is enabled on the connection — "if an error occurs during SaveChanges, the transaction may be left in an unknown state."

**Isolation.** EF Core does not set an isolation level. `SaveChanges` and your queries run at whatever the connection/server default is, and those defaults are not the same across engines — SQL Server and PostgreSQL default to `READ COMMITTED`, MySQL/InnoDB to `REPEATABLE READ`, and SQL Server's `READ COMMITTED` behaves completely differently depending on whether `READ_COMMITTED_SNAPSHOT` is on (off by default on SQL Server, on by default on Azure SQL Database). The chapter covers this properly in [Transactions & Concurrency](./03-sql/07-transactions-and-concurrency.md); what's EF-specific is only that you ask for something else explicitly:

```csharp
await using var tx = await db.Database.BeginTransactionAsync(IsolationLevel.Snapshot);
```

**The retry trap** — this is the one that produces an exception you'll meet in production and won't recognise. Turn on connection resiliency and then open a transaction by hand:

```csharp
opt.UseSqlServer(cs, o => o.EnableRetryOnFailure());
...
await using var tx = await db.Database.BeginTransactionAsync();   // 💥
```

> InvalidOperationException: The configured execution strategy 'SqlServerRetryingExecutionStrategy' does not support user-initiated transactions. Use the execution strategy returned by 'DbContext.Database.CreateExecutionStrategy()' to execute all the operations in the transaction as a retriable unit.

The reasoning is sound once you see it. With retries on, each query and each `SaveChanges` is independently retriable. A hand-rolled transaction defines a *different* unit that must be replayed as a whole, and the strategy can't know where it begins. So you hand it the whole block:

```csharp
var strategy = db.Database.CreateExecutionStrategy();

await strategy.ExecuteAsync(async () =>
{
    await using var tx = await db.Database.BeginTransactionAsync();
    // ... multiple SaveChanges calls ...
    await tx.CommitAsync();
});
```

Two consequences of `EnableRetryOnFailure` that are easy to miss. First, the delegate **must be idempotent**, because it is replayed from the top — anything non-transactional inside it (a log write, an HTTP call, a message publish) happens again. Second, enabling retries makes EF **buffer result sets internally**, regardless of how you evaluate the query, so that a retry can return the same rows; on a query returning many rows that is a real memory cost, and it stacks on top of any `ToList` you also called.

There is also a genuinely nasty edge the docs name outright: if the connection drops *during* the commit, the transaction's outcome is unknown. The strategy retries as though it rolled back, which "could lead to **data corruption** if the operation does not rely on a particular state, for example when inserting a new row with auto-generated key values." The mitigation is `ExecuteInTransactionAsync` with a `verifySucceeded` predicate, or client-generated keys so a duplicate insert fails loudly instead of succeeding twice.

> 🌍 **In the real world**: a team added `EnableRetryOnFailure()` during an Azure SQL migration because the guidance said to, and the app failed to start — every code path with `BeginTransactionAsync` threw the execution-strategy exception on first use. The quick fix that shipped was to remove `EnableRetryOnFailure()`, which restored startup and removed the resilience they had added it for. What should have shipped was `CreateExecutionStrategy()` around each transactional block, plus an audit of what those blocks did besides touch the database — one of them published to a service bus mid-transaction and would have published twice on every retry. The exception was not the bug; it was the framework refusing to guess at the boundary of a unit of work, and it was right to.

### What SaveChanges actually sends

`SaveChanges` does not emit one statement per entity. It **batches** them into a single command, so a hundred inserts are not a hundred roundtrips. On SQL Server the default cap is 42 statements per batch — a number Microsoft attributes to "an analysis of batching performance" (EF Core 5.0 release notes) — and it is tunable via `MaxBatchSize` in the provider options. Save 100 rows and you get three roundtrips, not one and not a hundred.

The interesting part is how it reads generated keys back. Since EF Core 7 the SQL Server provider uses the T-SQL `OUTPUT` clause, and that produced one of the more disruptive breaking changes in EF's history, because **`OUTPUT` without `INTO` is not permitted on a table that has a trigger**. Applications with audit triggers upgraded to EF 7 and every insert into those tables began failing. The fix is to tell EF the table is special so it falls back to the older technique:

```csharp
// EF Core 8+
modelBuilder.Entity<Order>().ToTable(tb => tb.UseSqlOutputClause(false));

// EF Core 7
modelBuilder.Entity<Order>().ToTable(tb => tb.HasTrigger("trg_Orders_Audit"));
```

**Batching is not bulk loading.** For genuinely large inserts, `SaveChanges` is the wrong instrument no matter how you size the batch — it is still parameterised `INSERT` statements, with change tracking and a snapshot per entity on the way in. Every engine ships a bulk path that bypasses the statement protocol entirely: `SqlBulkCopy` on SQL Server, Npgsql's binary `COPY` on PostgreSQL, `LOAD DATA` on MySQL. `ExecuteUpdate`/`ExecuteDelete` cover the set-based update and delete cases, but note the documented gap — **there is no `ExecuteInsert`**; insertion still goes through `Add` and `SaveChanges` or a provider bulk API.

> 🌍 **In the real world**: a nightly import inserted a few hundred thousand rows with `AddRange` plus one `SaveChanges`, and the job's memory profile looked like a sawtooth ending in an OOM kill. The first fix attempted was raising `MaxBatchSize`, which changed nothing, because the memory was not going into batches — it was going into the change tracker holding every entity and its original-values snapshot until the call returned. Chunking into `DbContext` instances of a few thousand rows each fixed the memory. Switching that path to `SqlBulkCopy` fixed the runtime. The diagnostic worth keeping: if raising the batch size doesn't move the needle, the bottleneck isn't roundtrips, and you should go and find out what it actually is before tuning anything else.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Migration deployment pipeline (zero-downtime)

```
Schema change required: add NOT NULL column "Currency" to Orders

WRONG (causes downtime):
  Step 1: Migration adds NOT NULL column
  Step 2: Code writes Currency on insert
  → Step 1 alone fails: existing rows have no value

RIGHT (zero-downtime, three deploys):
  Deploy 1: Migration adds NULLABLE column
            Code still ignores Currency
  Deploy 2: Backfill existing rows (UPDATE ... SET Currency = 'USD')
            Code writes Currency on new inserts
  Deploy 3: Migration alters column to NOT NULL
            Old code paths gone
```

### Optimistic concurrency flow

```
User A reads Order 42 (RowVersion = 0x01)
User B reads Order 42 (RowVersion = 0x01)
User A updates Status = "Shipped" → DB: SET ... WHERE Id=42 AND RowVersion=0x01
                                    → 1 row affected, RowVersion → 0x02 ✓
User B updates Status = "Cancelled" → DB: SET ... WHERE Id=42 AND RowVersion=0x01
                                      → 0 rows affected ✗
                                    → DbUpdateConcurrencyException raised
                                    → App reloads, merges, retries
```

### Where a LINQ query becomes a plan — and what caches what

Four caches sit between your lambda and the disk. Knowing which one a symptom belongs to is most of diagnosis.

```
  db.Orders.Where(o => o.Status == status)         ← C#: a new expression tree per call
             │
             │  ① EF query cache        (in-process, keyed on TREE SHAPE)
             │       hit  → reuse the translation      → Query Cache Hit Rate 100%
             │       miss → walk tree, generate SQL
             │       a CONSTANT in the tree = a new shape = a miss, every call
             ▼
  "SELECT ... WHERE [Status] = @status"             ← SQL text + parameter values
             │                                        (@__status_0 before EF Core 10)
             │
   ══════════▼══════════ network roundtrip ══════════════════════════
             │
             │  ② Server plan cache     (SERVER-WIDE, shared by everyone)
             │       keyed on the SQL TEXT, so a new text = a new plan
             │       hit  → reuse a plan chosen for whichever value ran FIRST
             │       miss → optimise: read statistics, estimate rows, pick operators
             │       SQL Server: implicit LRU cache — single-use plans evict others'
             │       PostgreSQL: no server-wide equivalent; prepared statements
             │                   give a similar effect, per connection
             ▼
             │  ③ Buffer pool / page cache            (engine memory)
             ▼
           pages  ──────────► rows ──────────► back over the network
                                                        │
             ┌──────────────────────────────────────────┘
             ▼
             │  ④ EF materialiser + change tracker      (per DbContext)
             │       build entities; identity-map lookup per row;
             │       snapshot original values per entity
             │       AsNoTracking skips the last two; a DTO projection
             │       never enters them at all
             ▼
        your objects
```

Read the symptom back through the diagram:

| Symptom | Stage | What to look at |
|---|---|---|
| Query Cache Hit Rate stuck below 100% | ① | A constant in the tree, or `Expression.Constant` in dynamically-built queries |
| Same query fast for one input, slow for another | ② | Parameter sniffing — the cached plan was optimised for a different value |
| Query slowed down after a data load, no deploy | ② | Stale statistics; the estimate no longer matches the data |
| Slow only on the first call after a deploy | ②/③ | Cold plan cache and cold buffer pool — measure the steady state, not the first hit |
| Query is fast in SSMS, slow from the app | ② | Different plan, usually from a different `SET` option set or an implicit conversion on a parameter — compare the two plans, not the two stopwatches |
| SQL is fine, endpoint still slow, CPU in the app | ④ | Materialisation: too many rows, too many columns, or tracking you didn't need |
| `SaveChanges` produced no SQL at all | ④ | Entity not tracked, or the "change" wrote the value that was already there |

</details>

## Common pitfalls

1. **Running `database update` in app startup.** Race conditions during scale-out; no rollback path. Migrate via CI/scripts.
2. **Loading entities just to delete them.** Use `ExecuteDeleteAsync` for bulk.
3. **Including too aggressively.** `Include(o => o.Items).Include(o => o.Customer).Include(o => o.Payments)` = cartesian explosion. Use split queries or projections.
4. **Forgetting `AsSplitQuery()` when including multiple collections.** Single-query Include with two `*` collections multiplies row count.
5. **No concurrency token on hot rows.** Last-write-wins silently corrupts data. Add `[Timestamp]` to anything multiple users edit.
6. **Eager loading by default in repositories.** Returns more than callers need. Let callers choose what to include.
7. **Migrations not reviewed.** A junior dev's "rename column" migration becomes prod schema. Pair-review or require DBA sign-off.
8. **Forgetting to override `OnModelCreating` for non-conventional schemas.** Default conventions assume `Id` PK, plural table names. Real schemas often differ.
9. **DbContext as a long-lived singleton.** It's `Scoped` for a reason — change tracking + connection pooling assume request-scoped lifetime.
10. **Ignoring connection-pool exhaustion symptoms.** "Timeout expired" under load → `MaxPoolSize` (default 100) hit. Either raise the cap or fix the leak (DbContext not disposed, long-running queries).
11. **Not knowing what `Find` is actually for.** It takes primary key *values*, not a predicate, so it can't be used for anything else. Its real point is the one people miss: "if an entity with the given primary key values is being tracked by the context, then it is returned immediately without making a request to the database" (Microsoft Learn). `FirstOrDefaultAsync(o => o.Id == id)` always goes to the database, even when the row is already tracked in this very context. In a handler that loads by ID twice, `FindAsync` is one roundtrip and `FirstOrDefaultAsync` is two.
12. **Migrations with data migrations mixed in.** Schema migrations should be pure DDL. Data migrations belong in idempotent scripts run separately (or as one-off jobs).
13. **`AsSplitQuery()` applied reflexively.** It fixes cartesian explosion and costs you cross-query consistency, a roundtrip per collection, and buffering. It is not the default answer to "there are two Includes" — check whether they're siblings first.
14. **`ExecuteUpdate`/`ExecuteDelete` mixed with tracked changes in one unit of work.** They execute immediately, take no part in `SaveChanges`' transaction, and the change tracker never learns what they did. The tracked instance then overwrites them on the next `SaveChanges`.
15. **`EnableRetryOnFailure` with hand-rolled transactions.** Throws `InvalidOperationException` on the first `BeginTransaction`. Wrap the block in `Database.CreateExecutionStrategy().ExecuteAsync(...)` — and make the block idempotent, because it is replayed whole.
16. **`EnableSensitiveDataLogging` left on in production.** It exists to put parameter values in the log, so it puts customer data in the log. Development only.
17. **Assuming `[Timestamp]` means the same thing on every engine.** It maps to SQL Server's `rowversion` (`byte[]`), to PostgreSQL's `xmin` system column via Npgsql (`uint`), and to nothing at all on SQLite. Porting an app is exactly when someone deletes the attribute to make it compile and silently removes all concurrency control.

## Interview-ready summary

- **Migrations as code** with `Up`/`Down`. Generate idempotent SQL for prod; never auto-run on startup.
- **Optimistic concurrency** is what EF Core implements, but only once you configure a token. Without one the `WHERE` clause is the PK alone and the behaviour is last-write-wins.
- **Performance levers:** `AsNoTracking`, projections, compiled queries, `ExecuteUpdate`/`ExecuteDelete`, split queries.
- **Read/write separation** via two DbContexts pointing at primary + read replica — and you now own replica lag.
- **N+1** is the #1 EF Core production issue. Use `Include`, projections, or split queries.
- **Parameter vs constant** decides both EF's compilation cache and the server's plan cache. A constant in the tree defeats both.
- **`SaveChanges` is one transaction; `ExecuteUpdate` is a different one.** Neither knows about the other.

**Expected interview questions:**

1. *"How do you do zero-downtime schema changes with EF Core migrations?"* — Three-deploy pattern: nullable add → backfill → tighten constraint. Each deploy is backward-compatible with the previous code version.
2. *"Optimistic vs pessimistic concurrency?"* — Optimistic detects at save time via version column (default in EF Core). Pessimistic locks at read time. Optimistic wins for typical web apps; pessimistic for heavy contention or batch jobs.
3. *"How do you deal with N+1 queries in EF?"* — Diagnose with logging or MiniProfiler. Fix with `Include`/`ThenInclude`, projections, split queries (`AsSplitQuery`), or DataLoader-style batching for GraphQL.
4. *"Why is `AsNoTracking` faster?"* — Skips change tracking — no snapshot of entity state, no identity-map lookups, no save-changes overhead. Read-only queries get free speedup.
5. *"What's `ExecuteUpdate` and when do you use it?"* — Issues a single SQL UPDATE without loading or tracking rows. EF Core 7+. Four things it does *not* do: accumulate for a later `SaveChanges` (it executes immediately), start a transaction, update the change tracker, or apply concurrency tokens. It returns the rows-affected count, which is how you do the concurrency check yourself.
6. *"How does EF Core handle transactions?"* — One `SaveChanges` call is one transaction; three calls are three. For multi-`SaveChanges` work, wrap in `db.Database.BeginTransactionAsync()` — and since EF Core 5, a `SaveChanges` inside an open transaction creates a savepoint first and rolls back to it on failure (except with SQL Server MARS enabled, where EF skips savepoints entirely). Distributed transactions across databases are awkward — prefer the outbox pattern.
7. *"Compiled queries — when worth it?"* — They skip EF's cache *lookup*, not the SQL execution. EF already caches translation keyed on the tree's shape; the compiled query hands you the delegate so the tree never has to be walked and compared. Microsoft's docs call that overhead "negligible in the majority of EF applications" next to network and database I/O. Reach for it on a profiled hot path, and know the two limits: one model only, simple scalar parameters only.
8. *"Why did my query get slower after upgrading EF Core?"* — Because a translation change is a plan change. The `Contains`/`IN` translation alone changed twice: inlined constants through EF 7, a single JSON-array parameter in EF 8–9 (expanded with `OPENJSON` on SQL Server, and with the equivalent database-specific function elsewhere), one scalar parameter per element in EF 10. Each was a fix for the previous one's failure mode. `EF.Constant` / `EF.Parameter` / `EF.MultipleParameters` override it per query; `UseParameterizedCollectionMode` sets it globally.
9. *"How would you find an N+1 in production without a profiler?"* — `dotnet counters monitor Microsoft.EntityFrameworkCore` gives Queries (Total) and Query Cache Hit Rate live. A queries-per-request ratio that scales with result-set size is N+1; a cache hit rate stuck below 100% is a different bug — something is producing a new query shape per call.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.

### Drill 1 — DbContext lifecycle

> **Q**: Why is `DbContext` registered as scoped, not singleton or transient, in ASP.NET Core?
>
> **A**: `DbContext` is **not thread-safe** and holds per-request state — the change tracker, identity map, pending change list, and an open database connection (when pooled). A singleton would be shared across concurrent requests and corrupt the change tracker. Transient would create a new context for every injection inside one request, breaking the unit-of-work guarantee that everything saves together.
>
> **Cross-Q**: How does `AddDbContextPool` differ from `AddDbContext`?
>
> **A**: `AddDbContextPool` keeps a pool of `DbContext` instances and **resets** each one when the scope ends (clears change tracker, restores default state) instead of allocating a fresh object. Resolution is still scoped per request — the difference is what happens behind the scenes. What it saves is context *setup*, not query time: Microsoft's own framing is "pay context setup costs only once at program startup, rather than continuously", and the docs publish a benchmark for a single-row fetch alongside the caveat that it is single-threaded and you should measure your own. The trade-off: any state you added to the context (custom fields, cached lookups) **leaks across requests** unless you reset it yourself.
>
> **Cross-Q²**: I added a `_tenantId` field set in my `DbContext` constructor for multi-tenancy. I'm using `AddDbContextPool`. What goes wrong?
>
> **A**: Pooling makes the instance behave, in the docs' words, as though "it's effectively registered as a Singleton, and the same instance is reused across multiple requests (or DI scopes)" — the constructor and `OnConfiguring` run **once, when the pool creates the instance**, not per request. So `_tenantId` is whatever the first request set, and every subsequent request on that pooled instance sees the stale tenant: a **cross-tenant data leak**. The documented fix is not "don't pool" but a scoped shim: register `AddPooledDbContextFactory<T>` as the singleton pool, write a small scoped `IDbContextFactory<T>` wrapper that takes a scoped `ITenant`, pulls a context from the pool and **assigns the tenant onto it** before handing it out, then register the context as scoped via that wrapper. Every consumer gets a pooled instance with the right tenant and knows nothing about either mechanism.

### Drill 2 — Change tracking mechanics

> **Q**: How does EF Core know a property was modified when you write `order.Status = "Cancelled"`?
>
> **A**: When the entity was loaded (without `AsNoTracking`), EF Core stored an **original-values snapshot** in the change tracker. On `SaveChanges`, it compares each property's current value against the snapshot. If they differ, the column is included in the generated `UPDATE`. EF Core 2+ uses snapshot tracking by default; the older proxy-based "notification entities" pattern is rarely seen now.
>
> **Cross-Q**: What if my entity has 50 properties? Does EF Core compare all 50 on every save?
>
> **A**: Yes — that's why **`AsNoTracking` and projection** matter so much for read-heavy workloads. Snapshot comparison is O(properties × tracked entities). On a query that loaded 10,000 entities with 50 columns each, that's 500K field comparisons per `SaveChanges`. For pure reads, skip it entirely with `AsNoTracking`. For partial updates, prefer `ExecuteUpdate` (EF 7+) which skips the tracker entirely.
>
> **Cross-Q²**: I changed a property but `SaveChanges` produced no SQL. What are the four most common reasons?
>
> **A**: (1) Entity was loaded `AsNoTracking` — no snapshot to detect change. (2) Entity was never attached — you created a `new Order` and modified it but never called `Add`/`Update`/`Attach`. (3) The "change" wrote the same value as the original (snapshot comparison sees no diff). (4) Somebody set `ChangeTracker.AutoDetectChangesEnabled = false` as a "performance optimisation" and never called `ChangeTracker.DetectChanges()` — the comparison that would have found the diff never runs. A fifth, rarer one: the property is mapped but has no usable setter or backing field for EF to read the current value from, so the model and the object disagree about where the value lives.

### Drill 3 — AsNoTracking when and why

> **Q**: When would you use `AsNoTracking`?
>
> **A**: For pure read queries that won't be saved back — list pages, dashboards, reports, search results. It removes two specific pieces of per-row work that Microsoft's performance guide names: the identity-map dictionary lookup on every materialised row, and the original-values **snapshot** EF takes of each instance before handing it to you. Both cost time and both cost memory, and they scale with rows × properties. The docs publish a tracking-vs-no-tracking benchmark for 10 blogs with 20 posts each; quote the mechanism in an interview and offer to measure the multiplier, because it depends entirely on entity width and result-set size.
>
> **Cross-Q**: Are there correctness differences, not just perf?
>
> **A**: Yes. With tracking, EF Core's **identity map** ensures one row maps to one C# instance per context — query the same `Order #5` twice and you get the same object reference. With `AsNoTracking`, each query materializes a fresh instance, so reference equality breaks. Also, navigation properties may behave differently: tracked queries fix up navigations across already-loaded entities; no-tracking queries don't (you can opt into `AsNoTrackingWithIdentityResolution` to keep identity but skip change-tracking overhead).
>
> **Cross-Q²**: I added `AsNoTracking` to my list query and now an audit field `LastViewedAt` doesn't update when I call `SaveChanges` later. Why?
>
> **A**: `AsNoTracking` returned a **detached entity**. To save changes, you'd have to `db.Update(entity)` (marks all properties modified) or `db.Attach(entity)` then individually set property state. Without that, the entity isn't in the change tracker and `SaveChanges` is a no-op. Rule of thumb: `AsNoTracking` is read-only; if you might write later, either drop it or re-attach explicitly. For audit-on-read patterns, prefer `ExecuteUpdate` so you don't materialize at all.

### Drill 4 — Lazy vs eager vs explicit loading

> **Q**: Walk me through lazy, eager, and explicit loading for `order.Customer`.
>
> **A**: **Eager** = `Include(o => o.Customer)` — JOIN issued in the original query; `Customer` is populated when `Order` materializes. **Explicit** = `db.Entry(order).Reference(o => o.Customer).LoadAsync()` after the fact — separate query, you control the timing. **Lazy** = navigations are proxied; touching `order.Customer` for the first time issues a query transparently. Requires `UseLazyLoadingProxies()` and `virtual` navigations.
>
> **Cross-Q**: Why is lazy loading discouraged in EF Core?
>
> **A**: It hides query cost behind property access — `foreach (var o in orders) { Console.WriteLine(o.Customer.Name); }` looks innocent but issues N queries (one per order). It also breaks async flow: lazy navigations are **synchronous**, so they block the request thread. And it can fire after the context is disposed, throwing `ObjectDisposedException` in surprising places. Eager loading or projection is almost always the right answer in 2026.
>
> **Cross-Q²**: When is lazy loading actually defensible?
>
> **A**: Three narrow cases. (1) **Long-lived UI contexts** in WinForms/WPF where the user might or might not expand a node — lazy avoids loading data they won't see. (2) **Sparse aggregates** with many navigations where most requests touch only a few — eager would over-fetch. (3) **Prototyping** where you're not yet sure which navigations are needed. Once the app is in production, profile and migrate hot paths to eager/explicit; lazy stays only where measurably better.

### Drill 5 — N+1 detection in production

> **Q**: A list endpoint loads 100 orders and is slow. You suspect N+1. How do you confirm it?
>
> **A**: Enable EF Core query logging at `LogLevel.Information` and inspect the output — if you see 101 queries (1 list + 100 lookups), it's N+1. In production, use a profiler: **MiniProfiler** (per-request SQL list), **Application Insights** dependency tracking, or **OpenTelemetry** with the EF Core instrumentation. SQL Server's Extended Events / Postgres `pg_stat_statements` will also show the repeated query shape.
>
> **Cross-Q**: You confirmed N+1. What are the three fixes, ordered by typical preference?
>
> **A**: (1) **`Include`/`ThenInclude`** for the navigations you need — generates a JOIN, single query. (2) **Projection to a DTO** — `Select(o => new OrderDto { CustomerName = o.Customer.Name, ... })` — usually the smallest, fastest query because you fetch only the columns you need. (3) **`AsSplitQuery()`** when `Include` causes cartesian explosion (multiple to-many includes) — issues one query per Include but avoids the row-multiplication blowup.
>
> **Cross-Q²**: I added `Include(o => o.Items).Include(o => o.Customer.Addresses)` and the result count exploded from 100 orders to 50,000 rows. What happened and what's the fix?
>
> **A**: **Cartesian explosion**: every order is multiplied by (items × addresses). EF Core 5+ warns about this. Two fixes: `AsSplitQuery()` runs the includes as separate queries (one for orders, one for items, one for addresses) and stitches them — total rows ≈ 100 + 1000 + 200 instead of 50,000. Or **project to a DTO** that selectively pulls what you need without materializing the full graph. Split queries cost slightly more on round trips but win massively on payload size.

### Drill 6 — Async pitfalls: Single vs SingleOrDefault

> **Q**: When do you use `SingleAsync` vs `SingleOrDefaultAsync` vs `FirstAsync`?
>
> **A**: **`SingleAsync`**: expects exactly one match; throws if zero or two+. Use to surface uniqueness bugs (PK lookups, business invariants). **`SingleOrDefaultAsync`**: expects zero or one; throws if two+; returns `null`/default if none. Use when "not found" is a normal outcome. **`FirstAsync`**: takes the first row; ignores duplicates silently. Use only when ordering is explicit and "pick any" is intentional (e.g., latest by timestamp).
>
> **Cross-Q**: Why is `FirstOrDefaultAsync` the "popular but often wrong" choice?
>
> **A**: It hides bugs. A query that should return one row but returned two because of a missing `WHERE` clause **silently picks one** instead of surfacing the duplicate. You discover the bug six months later when reports disagree. `SingleOrDefaultAsync` would have thrown immediately. The rule: use `First` only if the query has an `OrderBy` and "first by order" is the intent; otherwise use `Single`.
>
> **Cross-Q²**: What SQL does each generate on SQL Server, and what does the difference tell you?
>
> **A**: `First`/`FirstOrDefault` generate `SELECT TOP(1)`. `Single`/`SingleOrDefault` generate `SELECT TOP(2)`. The extra row is the whole point: to *prove* "at most one" the engine has to be given the chance to return a second row. Zero → throw "no element" (or return default), one → return it, two → throw "more than one". `TOP(1)` cannot detect a duplicate, which is precisely why `First` doesn't. So the choice between them is not a style preference — it is whether you want the uniqueness assertion to run. Reading the generated SQL is the fastest way to confirm which one a codebase is actually using, and Microsoft's own performance docs show the `TOP(1)` form for `FirstOrDefaultAsync`. The cost difference is negligible; both are bounded by the index lookup.

### Drill 7 — Compiled queries

> **Q**: What's a compiled query and when is it worth it?
>
> **A**: `EF.CompileAsyncQuery((MyDb db, int id) => db.Orders.Where(o => o.Id == id).Single())` compiles the LINQ expression once and hands you a delegate. Subsequent calls skip the expression-tree walking and the cache lookup entirely. Worth it on a hot path you have profiled — and say "profiled", because the docs are blunt that the saving is small next to network and database I/O.
>
> **Cross-Q**: EF Core already caches query compilation internally. Why isn't that enough?
>
> **A**: Because the cache is keyed on the *shape* of the expression tree, and EF has to build your tree and compare it against cached ones to find the entry. The translation is reused; the lookup isn't free. Microsoft describes compiled queries as bypassing "the cache lookup", and describes the lookup overhead itself as "negligible in the majority of EF applications, especially when compared to other costs associated with query execution (network I/O, actual query processing and disk I/O at the database)". So the honest answer to "how much does it save?" is "measure it" — the docs publish a benchmark and immediately say to benchmark on your own platform.
>
> **Cross-Q²**: I made everything a compiled query. What did I get wrong?
>
> **A**: Over-optimization, and you probably hit the documented limits. Two of them are hard: a compiled query works against **a single model** only (contexts of the same type configured with different models aren't supported), and its parameters must be **simple scalars** — "more complex parameter expressions, such as member/method accesses on instances, are not supported". Beyond that they're verbose, terminal (you can't compose over them), and useless for dynamically-constructed queries, which the docs note can't use the compiled-query optimisation at all. They're a scalpel for hot paths identified by profiling, not a baseline.

### Drill 8 — Migrations strategy

> **Q**: Code-first vs database-first vs schema-sync (compare `MigrateAsync` vs `EnsureCreatedAsync`)?
>
> **A**: **Code-first**: define entities in C#, scaffold migrations with `dotnet ef migrations add`, apply with `dotnet ef database update` or `MigrateAsync` at runtime. Schema versioned in source control. Industry standard for greenfield .NET apps. **Database-first**: reverse-engineer existing schema with `dotnet ef dbcontext scaffold` — generate entities and `DbContext` from the database. Use when the DBA team owns the schema. **`EnsureCreatedAsync`**: creates the schema directly from the model, no migrations. Use **only** for tests and demos — you can't evolve the schema without dropping it.
>
> **Cross-Q**: When would you avoid `MigrateAsync` in `Program.cs` and prefer SQL scripts?
>
> **A**: In production. `MigrateAsync` at startup couples deploys to schema changes (one bad migration → app won't start), grants the app account `ALTER TABLE` rights (security blast radius), and runs every replica in parallel during a rolling deploy (lock contention, possible duplicate migration application). Generate idempotent SQL with `dotnet ef migrations script --idempotent`, apply via CI/CD or a one-shot migration job, then deploy app code with read/write-only DB grants.
>
> **Cross-Q²**: How do you do a zero-downtime column rename with EF Core migrations?
>
> **A**: The three-deploy pattern. (1) **Add** new column (nullable, no FK constraint changes), deploy code that **writes to both** old and new columns. (2) **Backfill** new column from old via a script; deploy code that **reads from new, writes to both**. (3) **Drop** old column, tighten NOT NULL on new; deploy code that **only reads/writes new**. Each step is backward-compatible with the previous version, so you can roll out and roll back at any point without downtime.

### Drill 9 — Owned types vs value objects vs ValueConverter

> **Q**: I have a `Money(decimal Amount, string Currency)` value. Owned type, value object, or ValueConverter?
>
> **A**: Depends on storage shape. **Owned type**: maps to columns on the parent table (`Amount`, `Currency`). Good when you want both fields queryable and indexable. **ValueConverter**: maps the whole object to a **single column** (e.g., JSON or a formatted string). Good when the storage shape doesn't need to be column-decomposed. **Value object** is the *DDD pattern* — owned types and ValueConverters are EF Core's two implementations of it.
>
> **Cross-Q**: Show me when each picks differently in practice.
>
> **A**: Indexable money fields → owned type (`HasIndex(o => o.Total.Amount)` works). Opaque scalar like `EmailAddress` validated on construction → ValueConverter to `string` (one column, no decomposition). Complex types with internal nullability or methods that don't translate → ValueConverter to JSON (treat as scalar). For multi-currency portfolios where you want to `WHERE Currency = 'USD'`, owned type wins because the column exists.
>
> **Cross-Q²**: I converted `EmailAddress` to a single column via ValueConverter, and now `Where(c => c.Email.Domain == "example.com")` doesn't translate. Why?
>
> **A**: Once converted to a scalar, the **internal structure is invisible to LINQ-to-SQL**. `Email.Domain` is a C# property on the value object, not a column. EF Core can only translate operations on the converted scalar value (string equality, `Contains`, etc.). Fix: either expose `EmailDomain` as a **separate column** (shadow property or owned type), or filter client-side after a coarser SQL filter (e.g., `WHERE Email LIKE '%@example.com'`), or use a **computed column** at the database level.

### Drill 10 — DbContext pooling internals

> **Q**: What does `AddDbContextPool` actually pool?
>
> **A**: The `DbContext` **instances** themselves — not connections. The `poolSize` parameter "sets the maximum number of instances retained by the pool (defaults to 1024)". On request: take an instance, hand it to DI as the scoped `DbContext`. On scope dispose: reset state and return it. Connection pooling is a completely separate mechanism one layer down, managed by the ADO.NET driver (`SqlConnection`, `NpgsqlConnection`) and configured in the connection string. The docs are explicit that the two are "completely orthogonal".
>
> **Cross-Q**: What state does pooling reset, and what does it miss?
>
> **A**: EF resets its own internal state — change tracker and the services it owns. It misses **anything you added**: fields on your derived `DbContext` (`_tenantId` is the canonical example), and crucially `OnConfiguring`, which "is only invoked once — when the instance context is first created — and so cannot be used to set state which needs to vary". It also misses everything below EF: the docs warn that EF "generally does not reset state in the underlying database driver", so if you manually opened a `DbConnection` or changed ADO.NET state, restoring it is your job or it leaks across unrelated requests.
>
> **Cross-Q²**: How big should the pool be, and what happens when you exceed it?
>
> **A**: Note first what *doesn't* happen: exceeding `poolSize` is not an error and doesn't block. "Once `poolSize` is exceeded, new context instances are not cached and EF falls back to the non-pooling behavior of creating instances on demand" — you lose the optimisation, silently, under exactly the load where you wanted it. So sizing is about matching concurrent request count with headroom, and the failure signature is *latency creeping up under load with nothing in the logs*, not timeouts. Contrast with the ADO.NET connection pool one layer down, where exhaustion **does** block and then throws a timeout — that's `Max Pool Size` (default 100 for both SqlClient and Npgsql), and it's a different problem with a different fix.

### Drill 11 — Multi-tenancy with global query filters

> **Q**: How do you implement row-level multi-tenancy in EF Core?
>
> **A**: Add a `TenantId` column to every multi-tenant entity. In `OnModelCreating`, define a **global query filter**: `modelBuilder.Entity<Order>().HasQueryFilter(o => o.TenantId == _tenantAccessor.CurrentTenantId);`. EF Core auto-appends the filter to every query, so a tenant can only see their rows without explicit `WHERE` in every query.
>
> **Cross-Q**: What's the gotcha with `_tenantAccessor` and `DbContext` lifetime?
>
> **A**: Be precise about the mechanism, because the sloppy version of this answer is wrong. The filter expression **references the context instance**, so the tenant value is read from that instance when the query runs — this is the documented multi-tenancy pattern and it works fine per-request. The failure is entirely about **where the field gets its value**. Under `AddDbContextPool` the constructor and `OnConfiguring` run once, when the pool creates the instance, so a `_tenant` assigned in the constructor is frozen at whatever the first request set, and every later request on that instance queries the wrong tenant. Fixes, in the order Microsoft documents them: use `AddPooledDbContextFactory` with a **scoped factory wrapper** that assigns the tenant onto each context as it hands it out; or drop pooling and use a scoped `AddDbContextFactory`. Also note the `IEntityTypeConfiguration<T>` wrinkle — there's no context instance in scope there, so the docs' workaround is a dummy context field on the configuration type to reference from the filter.
>
> **Cross-Q²**: My `Post` query returns 6 rows, but adding `.Include(p => p.Blog)` returns 3. `Post` has no filter. What happened?
>
> **A**: The filter on `Blog` did it. The `Post → Blog` navigation is configured as **required**, so EF generates an `INNER JOIN` to fetch it — and the join's inner side is the filtered `Blog` set. Every post whose blog the filter removed gets removed too. Microsoft flags this directly: "Using required navigation to access entity which has global query filter defined may lead to unexpected results." Two fixes: mark the navigation optional with `IsRequired(false)` so EF emits a `LEFT JOIN`, or put a **matching filter on both entity types** so the two queries agree about which rows exist. This is worth knowing cold, because with soft-delete filters it silently deletes rows from reports. And for the deliberate cross-tenant case, `IgnoreQueryFilters()` removes all of them on that query (EF Core 10 adds *named* filters so you can disable one and keep the others) — guard it at the application layer with a claim check and an audit log, and keep it out of business code behind an explicit method.

### Drill 12 — Raw SQL and injection safety

> **Q**: When would you drop to `FromSqlInterpolated`?
>
> **A**: Three cases: (1) SQL features LINQ can't express — window functions (`OVER`) in **any** EF Core version to date, recursive CTEs, vendor-specific operators, (2) hand-tuned queries where the EF-generated SQL has a bad plan, (3) calling stored procedures. Be precise on the first one, because it is a common interview slip: EF Core has never shipped `OVER` translation — the tracking issue, [dotnet/efcore#12747](https://github.com/dotnet/efcore/issues/12747), is still open in the Backlog milestone, so raw SQL, a view, or a table-valued function remains the answer through EF 10. See [Window Functions](./03-sql/05-window-functions.md). The interpolated variant uses parameterized SQL automatically.
>
> **Cross-Q**: What's the difference between `FromSqlInterpolated($"...{userInput}...")` and `FromSqlRaw($"...{userInput}...")`?
>
> **A**: `FromSqlInterpolated` parses the interpolated string at compile time and **lifts each interpolation hole to a SQL parameter** — injection-safe. `FromSqlRaw` takes a raw string and **concatenates user input directly into the SQL** — injection-prone. If you must use `FromSqlRaw`, pass parameters separately: `FromSqlRaw("SELECT ... WHERE Name = {0}", userInput)` where `{0}` becomes a parameter, not string interpolation.
>
> **Cross-Q²**: A junior wrote `db.Orders.FromSqlRaw($"SELECT * FROM Orders WHERE Status = '{status}'")`. Why is this CVE-class bad?
>
> **A**: C# **interpolation runs before** `FromSqlRaw` sees the string — the user-controlled `status` is concatenated into the SQL literal. An attacker passes `'; DROP TABLE Orders;--` and the DB executes it. Fix: change to `FromSqlInterpolated($"SELECT * FROM Orders WHERE Status = {status}")` (note the `$` is inside the EF method, not pre-evaluated). The method then converts the hole to a `@p0` parameter binding. Roslyn analyzer `EF1002` flags raw SQL with interpolation; treat as a build break.

### Drill 13 — Transactions across multiple SaveChanges

> **Q**: A workflow needs three `SaveChanges` calls. How do you make them atomic?
>
> **A**: Wrap in an explicit transaction: `await using var tx = await db.Database.BeginTransactionAsync(); ... await db.SaveChangesAsync(); ... await db.SaveChangesAsync(); ... await tx.CommitAsync();`. Without the explicit transaction, each `SaveChanges` is its own auto-commit transaction — a failure between them leaves the database in a partial state.
>
> **Cross-Q**: What about transactions across two **different** `DbContext` types in the same operation?
>
> **A**: Two options. (1) **Shared transaction**: open the transaction on the underlying `DbConnection`, then pass it to each context with `context.Database.UseTransaction(...)`. Works only if both contexts use the **same connection** (same database). (2) **Distributed transaction (DTC/MSDTC)**: `using var scope = new TransactionScope(...)`. Cross-database, two-phase commit, slow, brittle, blocked by many platforms. Prefer the **outbox pattern** over DTC.
>
> **Cross-Q²**: Explain the outbox pattern in one paragraph.
>
> **A**: When you need to update your DB and publish a message atomically, write the message into an `OutboxMessages` table in the **same transaction** as the business write. A separate background process polls the outbox, publishes pending messages to the broker, and marks them sent. You get atomicity (DB and outbox commit together) without DTC, and at-least-once delivery (consumers must be idempotent). Trade-off: publishing is no longer synchronous with the commit — the added latency is whatever your poll interval and dispatcher throughput make it, which is a dial you set rather than a number to quote — and the dispatcher becomes a new thing that can be down, be behind, or publish twice.

### Drill 14 — Unit of work pattern fit

> **Q**: Does `DbContext` already implement the unit-of-work pattern?
>
> **A**: Yes. `DbContext` tracks changes across multiple entities and commits them in **one transaction** via `SaveChangesAsync`. It also implements the **repository pattern** in spirit (`DbSet<T>` is a repository facade). Wrapping `DbContext` in your own `IUnitOfWork`/`IRepository<T>` interfaces is usually pointless abstraction over an already-abstracted API.
>
> **Cross-Q**: When does a manual repository/unit-of-work wrapper still pay off?
>
> **A**: Three cases. (1) **Testability against non-EF stores** — if you might swap EF for Dapper or an in-memory test double, a thin repository hides the choice. (2) **Multi-context coordination** — if a business operation spans two `DbContext` types (write-DB + read-replica DB, or two bounded contexts), a `IUnitOfWork` over both makes the boundary explicit. (3) **Domain-driven design** with rich aggregates where you want to express "this query loads an aggregate root" rather than "this query joins three tables."
>
> **Cross-Q²**: I see a codebase with `IOrderRepository` that wraps `DbContext.Orders` and exposes only `GetById`, `Add`, `SaveAsync`. What's the smell?
>
> **A**: It's the **anemic repository anti-pattern** — a wrapper that hides EF Core's power (LINQ composition, projections, `Include`) without adding domain semantics. Either drop the wrapper (use `DbContext` directly), or push real domain operations onto it (`GetOrdersDueForShipment(date)`, `MarkShipped(id, time)`) so the repository encodes business meaning. Pure CRUD wrappers cost developer time and constrain query expressiveness for no benefit.

### Drill 15 — EF Core vs Dapper

> **Q**: When would you pick Dapper over EF Core?
>
> **A**: Three scenarios. (1) **Read-heavy paths where you want the SQL to be the artefact** — you write the statement, you own the plan, and there is no change tracker, no identity map and no snapshot between the reader and your object. (2) **Reporting/analytics** queries that don't fit ORM semantics well (complex window functions, dynamic columns, vendor-specific syntax). (3) **Legacy databases** with stored-procedure-heavy access patterns where you call existing SPs more than you write LINQ. Resist quoting a multiplier: EF's own overhead reduction guidance points out that "even for highly-optimized applications, network latency and database I/O will usually dominate any time spent inside EF Core itself", and much of the gap people attribute to Dapper is really tracking-vs-not, which `AsNoTracking` plus a projection closes for free.
>
> **Cross-Q**: When does Dapper bite back?
>
> **A**: (1) **No change tracking** — every update is hand-written SQL; you lose the unit-of-work safety net and bulk inserts get tedious. (2) **No migrations** — schema lives in the DB; you need a separate tool (Flyway, DbUp, custom). (3) **No identity map** — querying the same row twice returns two different objects; aggregate consistency is your problem. (4) **String SQL** — typos slip past compilation; refactors of column names don't propagate. EF Core's compile-time safety is a real cost saving.
>
> **Cross-Q²**: Can you mix them in one codebase?
>
> **A**: Yes, and many teams do. EF Core for the write-side (commands, aggregate updates, change tracking, migrations) and Dapper for the read-side (queries, projections, reports) — a lightweight CQRS split. They share the connection string and database; you wrap them in the same transaction via `IDbConnection` if needed. The mental cost is two query syntaxes, but each is used where it's strongest. Watch out for migrations: EF Core owns the schema, Dapper just reads/writes — make sure Dapper's hand-written SQL stays in lockstep with EF Core's model.

</details>

## Cheat Sheet

- **DbContext lifetime**: scoped per request; never singleton, change tracking and pooled connections assume short scope.
- **AsNoTracking**: read-only path; skips snapshot, identity map, and save-changes bookkeeping.
- **Projections** (`Select` to DTO): no tracking, narrower SELECT, fewer allocations than entity materialization.
- **Include vs Split**: two **sibling** collection Includes cause cartesian explosion (`ThenInclude` down a chain does not); `AsSplitQuery()` issues N queries instead, and trades away cross-query consistency plus a roundtrip each.
- **ExecuteUpdate/ExecuteDelete** (EF 7+): one round trip, no materialization, executes immediately, starts no transaction, invisible to the change tracker, no automatic concurrency token — returns rows affected so you can check it yourself.
- **[Timestamp]** rowversion: EF appends `WHERE RowVersion = @orig`; 0 rows affected raises `DbUpdateConcurrencyException`. SQL Server `rowversion`/`byte[]`; PostgreSQL `xmin`/`uint`; SQLite has no native equivalent.
- **No concurrency token = last-write-wins.** The `WHERE` is the PK alone; EF can only detect that the row is *gone*, not that it changed.
- **Compiled queries** (`EF.CompileAsyncQuery`): skips EF's cache *lookup*, not the query. One model, scalar parameters only. Profile first.
- **Parameter vs constant**: a captured variable parameterises and preserves the tree shape; a literal becomes a constant, forces recompilation and pollutes the server plan cache (LRU on SQL Server; PostgreSQL has no direct equivalent).
- **`Contains` → `IN`**: constants ≤ EF7, single JSON-array parameter EF8–9 (`OPENJSON` on SQL Server), one parameter per element EF10. Override with `EF.Constant` / `EF.Parameter` / `EF.MultipleParameters`.
- **`First` → `TOP(1)`, `Single` → `TOP(2)`.** The second row is what makes the uniqueness check possible.
- **Retries + transactions**: `EnableRetryOnFailure` + `BeginTransaction` throws. Wrap in `Database.CreateExecutionStrategy().ExecuteAsync(...)`, and make the block idempotent.
- **Batching**: `SaveChanges` batches statements — SQL Server default `MaxBatchSize` 42. Since EF 7 it reads keys back with `OUTPUT`, which breaks on tables with triggers until you call `UseSqlOutputClause(false)` (EF 8+; on EF 7 the lever is `HasTrigger`).
- **Migrations**: `Up`/`Down`; ship with `--idempotent` SQL via CI, never `database update` from app startup. EF 9+ takes a database lock while migrating; EF 8 and earlier do not.
- **Zero-downtime schema**: nullable-add -> backfill -> tighten; each deploy is backward compatible.
- **N+1 detection**: `LogTo` + `EnableSensitiveDataLogging` in dev; one parent select followed by one child select per row is the smoking gun. In production, `dotnet counters monitor Microsoft.EntityFrameworkCore` gives Queries (Total) and Query Cache Hit Rate live.
- **`Find` vs `FirstOrDefault`**: `Find` returns a tracked entity without a roundtrip; `FirstOrDefault` always queries.

## Walkthrough — N+1 killing the orders list endpoint

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: `/api/orders` averaged 80ms in dev with 50 orders. In prod with 500 orders it takes 6s and the SQL Server CPU pegs at 90%.

**Diagnosis**: Senior engineer turns on EF Core query logging (`optionsBuilder.LogTo(Console.WriteLine, LogLevel.Information).EnableSensitiveDataLogging()`) and reproduces locally with seeded data. The log shows one `SELECT * FROM Orders` followed by 500 `SELECT * FROM OrderItems WHERE OrderId = @p0` calls. Confirmed via `SET STATISTICS IO ON` in SSMS: aggregate logical reads in the tens of thousands. MiniProfiler attached to the dev environment shows the same pattern visually.

**Fix**: The handler iterates `order.Items.Count` after a non-eager-loaded query. Replace with a single projection:

```csharp
var dtos = await db.Orders
    .Where(o => o.Status == "Open")
    .Select(o => new OrderListDto(
        o.Id,
        o.CustomerName,
        o.Items.Count,
        o.Items.Sum(i => i.LineTotal)))
    .AsNoTracking()
    .ToListAsync();
```

This compiles to one SQL statement with `COUNT` and `SUM` subqueries. Latency in that environment came back to 95ms.

**Why it works**: EF Core translates aggregate operations inside `Select` to SQL aggregates instead of fetching child collections. Tracking is bypassed because the projection target isn't an entity — which means the `.AsNoTracking()` in that snippet is doing nothing at all. Leaving it in is harmless but it teaches the next reader the wrong lesson: `AsNoTracking` matters when you materialise **entities**, and a projection to a DTO already skipped tracking before you asked.

**The check the walkthrough should end with**: confirm the fix in the plan, not only in the stopwatch. Two `COUNT`/`SUM` subqueries per row is one statement but not necessarily a cheap one — if `OrderItems` has no index on `OrderId`, you have replaced 500 index seeks with one query that scans `OrderItems` twice. Faster, and still wrong. `SET STATISTICS IO ON` on the new statement answers it in seconds.

</details>

## Self-test

<details><summary>1. Why is running <code>database update</code> on app startup risky in a horizontally scaled deployment?</summary>

Multiple instances race to apply migrations against the same database. The migration history table is not strongly serialised across instances, and a partially applied migration on instance A leaves instance B reading inconsistent schema. There is also no rollback path if startup fails mid-migration.
</details>

<details><summary>2. You see <code>DbUpdateConcurrencyException</code> on a checkout endpoint. Walk through resolution options.</summary>

Catch the exception, call `entry.GetDatabaseValuesAsync()` to read current DB state, then either (a) merge fields if the conflict is on disjoint columns, (b) surface a user-visible "someone else updated this" with the new values, or (c) retry with the database snapshot if the operation is commutative (e.g., increment a counter via `ExecuteUpdate`).
</details>

<details><summary>3. <code>AsSplitQuery</code> issues N queries instead of one. When is that better than a single JOIN?</summary>

When the parent has multiple `Include`d collections. A single JOIN multiplies rows by the cartesian of the children: 100 orders, 5 items, 3 payments = 1500 rows materialized for 100 entities. Split queries fetch parent (100) + items (500) + payments (300) = 900 rows.
</details>

<details><summary>4. Trade-off: compiled queries vs query plan caching. When is the manual <code>EF.CompileAsyncQuery</code> worth the boilerplate?</summary>

EF caches the SQL plan but re-runs the LINQ-to-SQL translation per call. For queries called thousands of times per second, that translation is measurable. Compiled queries cache the translated tree. Worth it for hot lookups (cache loaders, auth checks). Not worth it for ad-hoc reports or once-per-request queries.
</details>

<details><summary>5. A junior writes <code>db.Orders.Where(o => o.Items.Any(i => i.Quantity > 5)).ToList().Where(o => o.IsActive).ToList()</code>. What's wrong?</summary>

The first `ToList()` materialises the full result set in memory; the second `Where` runs in LINQ-to-Objects on the client. The `IsActive` filter never reaches SQL. The fix is a single chained `Where` before `ToList`, or move both predicates into the database expression tree.
</details>

<details><summary>6. You have no concurrency token on <code>Order</code>. Two users edit the same order at the same time. Which of them gets an exception, and why?</summary>

Neither. With no token configured the `UPDATE`'s `WHERE` clause is the primary key alone, so both statements report one row affected and the second write wins. EF does check rows-affected on every update and delete, so it would still throw if the row had been *deleted* — but it cannot notice that the row *changed*, because it never put the old value in the `WHERE`. Compounding it: EF only sends columns it detected as modified, so two users editing different fields of the same row both succeed and nothing ever looks wrong. "Optimistic concurrency is the EF Core default" is only true of the *model*; the default *configuration* is last-write-wins.
</details>

<details><summary>7. Why does a literal in a <code>Where</code> clause cost you twice — once in your process and once on the database server?</summary>

EF caches compilation output keyed on the **shape** of the expression tree. A captured variable becomes a SQL parameter and keeps the shape constant across calls; a literal becomes a constant node, so every distinct value is a different tree and a different cache entry — EF recompiles. That same difference then reaches the server as different SQL *text*: `WHERE Name = N'post1'` and `WHERE Name = N'post2'` are two statements, so SQL Server (which maintains an LRU plan cache) compiles and stores two plans, and a high-cardinality version of this evicts plans other queries were relying on. The in-process symptom is Query Cache Hit Rate stuck below 100%; the server-side symptom is single-use plan bloat. PostgreSQL doesn't keep an equivalent server-side cache, so the second cost mostly doesn't apply there — which is a good example of why "is this SQL Server or Postgres?" is a legitimate question to ask an interviewer.
</details>

<details><summary>8. You turn on <code>EnableRetryOnFailure()</code> and the app throws on the first <code>BeginTransactionAsync</code>. What is the framework objecting to, and what's the fix?</summary>

With retries enabled, each query and each `SaveChanges` becomes its own retriable unit. Opening a transaction by hand declares a *different* unit — everything between begin and commit has to be replayed together — and the execution strategy has no way to know where that block starts. So it refuses rather than retrying half of it: *"The configured execution strategy 'SqlServerRetryingExecutionStrategy' does not support user-initiated transactions."* The fix is to hand it the block: `db.Database.CreateExecutionStrategy().ExecuteAsync(async () => { ...begin, save, commit... })`. Two follow-ons a good candidate volunteers: the delegate is replayed from the top so it must be idempotent (a message published inside it gets published again), and enabling retries makes EF buffer result sets internally so a retry can return the same rows — which costs memory on large queries.
</details>

<details><summary>9. Your <code>Posts</code> query returns 6 rows. Adding <code>.Include(p =&gt; p.Blog)</code> returns 3. There is no filter on <code>Post</code>. Explain.</summary>

There is a global query filter on `Blog`, and the `Post → Blog` navigation is **required**. Required navigations let EF use an `INNER JOIN`, and the inner side of that join is the filtered `Blog` set — so any post whose blog the filter excluded is excluded too. Microsoft documents this as a caution on global query filters. Two fixes: configure the navigation as optional (`IsRequired(false)`) so EF emits a `LEFT JOIN`, or define a matching filter on `Post` so both entity types agree about which rows exist. Worth knowing cold because with soft-delete filters it silently removes rows from reports and no exception is ever thrown.
</details>

<details><summary>10. You load an order, then call <code>ExecuteUpdateAsync</code> on that table, then modify the loaded order and call <code>SaveChanges</code>. What ends up in the database?</summary>

Your `SaveChanges` value — the `ExecuteUpdate` is overwritten. `ExecuteUpdate` executes immediately and has no interaction whatsoever with the change tracker, so the tracked instance still holds the values from when it was queried plus your in-memory edit, and its original-values snapshot still holds the pre-`ExecuteUpdate` value. `SaveChanges` compares current against that stale snapshot, sees a difference, and writes. The rule that follows: don't mix tracked and untracked modification of the same rows in one unit of work. Two further consequences of the same design — `ExecuteUpdate` starts no transaction (two calls in a row are two transactions), and it applies no concurrency token, though it returns the rows-affected count so you can put the token in the `Where` and check the count yourself.
</details>

<details><summary>11. An upgrade from EF Core 7 to 8 makes one query with a large <code>Contains</code> list time out, and changes nothing else. What happened?</summary>

The `IN` translation changed. Through EF 7 the list was inlined as constants, which let the optimizer see how many values there were and estimate accordingly. EF 8 switched to passing the list as a single JSON array parameter expanded with `OPENJSON` on SQL Server — one plan for every list size, which fixed plan-cache churn, but the optimizer can no longer see the cardinality and can pick a plan built for a much smaller list. Microsoft records that the new form "can be dramatically less efficient in a minority of cases, even causing query timeouts". Fixes: `EF.Constant(ids)` on that one query, or `UseParameterizedCollectionMode` globally. EF 10 changed the default again — one scalar parameter per element — explicitly to give the planner cardinality back while keeping parameterisation.
</details>

<details><summary>12. Which of these is the SQL Server-only claim: (a) <code>[Timestamp]</code> gives you an auto-incrementing row version; (b) <code>SaveChanges</code> runs in a transaction; (c) a reporting <code>SELECT</code> can block writers?</summary>

(a) and (c) are both SQL Server-flavoured, and that is the point of the question. (a) `rowversion` is a SQL Server type; Npgsql maps a `uint` property to the `xmin` system column instead, and SQLite has no equivalent at all, which is why application-managed tokens (`[ConcurrencyCheck]`) exist. (c) is true of SQL Server under `READ COMMITTED` with `READ_COMMITTED_SNAPSHOT` **off** — the on-premises default, though Azure SQL Database defaults it on — because readers take shared locks; PostgreSQL and InnoDB serve plain `SELECT`s from an MVCC snapshot and don't block writers. (b) is the genuinely general one: EF Core wraps each `SaveChanges` call in a transaction wherever the provider supports transactions, and EF sets no isolation level of its own, so which level that transaction runs at is the engine's default, not EF's choice.
</details>

## Cross-references

- **Deep-dive: [Entity Framework Core](../01-foundations/01-net-core-deep-dive/05-data-access.md#11-entity-framework-ef-and-ef-core)** — full mechanics, CRUD examples.
- [LINQ](./02-linq.md) — querying mechanics that EF Core translates to SQL.
- [SQL](./03-sql/README.md), [MS SQL Server](./04-mssql-server.md) — what EF generates and runs against.
- [CQRS](../04-architecture-and-patterns/05-cqrs.md) — read/write separation taken further.
- [Configuration Deep Dive](../01-foundations/01-net-core-deep-dive/15-configuration.md) — connection strings.

_Add chapter-specific notes or extensions below as you study._

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [EF Core docs](https://learn.microsoft.com/en-us/ef/core/).
- Microsoft Learn — [Migrations](https://learn.microsoft.com/en-us/ef/core/managing-schemas/migrations/).
- *Entity Framework Core in Action* by Jon P. Smith (Manning, 3rd ed. 2023) — the definitive book.
- *EF Core Performance Best Practices* — [learn.microsoft.com/en-us/ef/core/performance/](https://learn.microsoft.com/en-us/ef/core/performance/).

Specific claims on this page trace to:

- Microsoft Learn — [Advanced Performance Topics](https://learn.microsoft.com/en-us/ef/core/performance/advanced-performance-topics): `poolSize` default 1024 and the fall-back-to-unpooled behaviour when exceeded; `OnConfiguring` invoked once for pooled contexts; the scoped-factory multi-tenant pattern; compiled-query limitations (single model, scalar parameters); query caching keyed on tree shape, the constant-vs-parameter SQL comparison including `SELECT TOP(1)` for `FirstOrDefaultAsync`; Query Cache Hit Rate guidance; SQL Server LRU plan cache vs PostgreSQL.
- Microsoft Learn — [Efficient Querying](https://learn.microsoft.com/en-us/ef/core/performance/efficient-querying): identity resolution and snapshotting as the two costs `AsNoTracking` removes; buffering vs streaming; internal buffering under a retrying execution strategy.
- Microsoft Learn — [Handling Concurrency Conflicts](https://learn.microsoft.com/en-us/ef/core/saving/concurrency): the generated `WHERE Id = @p1 AND Version = @p2`; "the `rowversion` type shown above is a SQL Server-specific feature… some databases don't support these at all"; application-managed tokens; `OriginalValues.SetValues` in the retry loop; isolation levels as an alternative (SQL Server `REPEATABLE READ` locks; SQL Server `SNAPSHOT` and PostgreSQL `REPEATABLE READ` raise serialization errors).
- Npgsql — [Concurrency Tokens](https://www.npgsql.org/efcore/modeling/concurrency.html): `uint Version` with `[Timestamp]` / `IsRowVersion()` mapped to the `xmin` system column.
- Microsoft Learn — [ExecuteUpdate and ExecuteDelete](https://learn.microsoft.com/en-us/ef/core/saving/execute-insert-update-delete): immediate execution, no implicit transaction, no change-tracker interaction (with the worked overwrite example), no automatic concurrency control, no `ExecuteInsert`.
- Microsoft Learn — [Transactions](https://learn.microsoft.com/en-us/ef/core/saving/transactions): one transaction per `SaveChanges`; automatic savepoints and the MARS incompatibility; sharing a transaction across contexts.
- Microsoft Learn — [Connection Resiliency](https://learn.microsoft.com/en-us/ef/core/miscellaneous/connection-resiliency): the exact `SqlServerRetryingExecutionStrategy` exception text, the `CreateExecutionStrategy` pattern, and the commit-failure idempotency problem.
- Microsoft Learn — [Global Query Filters](https://learn.microsoft.com/en-us/ef/core/querying/filters): tenant value referenced from the context instance; the required-navigation `INNER JOIN` caution; `IgnoreQueryFilters` and EF 10 named filters.
- Microsoft Learn — [Single vs. Split Queries](https://learn.microsoft.com/en-us/ef/core/querying/single-split-queries): sibling collections vs `ThenInclude` chains; no consistency guarantee across split queries; roundtrip and buffering costs; the unique-ordering requirement with `Skip`/`Take` before EF 10.
- Microsoft Learn — [SQL Queries](https://learn.microsoft.com/en-us/ef/core/querying/sql-queries): `FromSql` limitations (all mapped columns, matching names, `DbSet` only, no related data) and the injection warning on `FromSqlRaw`.
- Microsoft Learn — breaking changes for [EF Core 7](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-7.0/breaking-changes) (`OUTPUT` clause vs triggers, `HasTrigger` / `UseSqlOutputClause`), [EF Core 8](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-8.0/breaking-changes) (`Contains` → `OPENJSON`, the performance-regression note and `EF.Constant`), and [EF Core 10](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-10.0/breaking-changes) (`ParameterTranslationMode`, simplified parameter names and the plan-recompilation spike).
- Microsoft Learn — [What's New in EF Core 5.0](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-5.0/whatsnew): "The default maximum batch size for SQL Server has been changed to 42 based on an analysis of batching performance"; automatic savepoints; `ToQueryString`; `LogTo`; the `dotnet counters` sample output, abridged above (the counter names and figures are the docs' own; rows unrelated to the point are omitted).
- Microsoft Learn — [Metrics](https://learn.microsoft.com/en-us/ef/core/logging-events-diagnostics/metrics): the event-counter names and their meanings, and the `System.Diagnostics.Metrics` instruments that replaced them in EF Core 9.
- Microsoft Learn — [What's New in EF Core 9](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-9.0/whatsnew): "EF9 introduces a locking mechanism to protect against multiple migration executions happening simultaneously"; `EF.Parameter`.
- Microsoft Learn — [DbSet&lt;TEntity&gt;.Find](https://learn.microsoft.com/en-us/dotnet/api/microsoft.entityframeworkcore.dbset-1.find): "If an entity with the given primary key values is being tracked by the context, then it is returned immediately without making a request to the database."
- Microsoft Learn — [Applying Migrations](https://learn.microsoft.com/en-us/ef/core/managing-schemas/migrations/applying) and [IMigrationsDatabaseLock](https://learn.microsoft.com/en-us/dotnet/api/microsoft.entityframeworkcore.migrations.imigrationsdatabaselock): the database-wide migration lock, introduced in EF Core 9.
- Microsoft Learn — [MigrationBuilder.Sql](https://learn.microsoft.com/en-us/dotnet/api/microsoft.entityframeworkcore.migrations.migrationbuilder.sql): the `suppressTransaction` parameter, which is what `CREATE INDEX CONCURRENTLY` needs on PostgreSQL.
- Microsoft Learn — [Perform index operations online](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/perform-index-operations-online): "Online index operations aren't available in every edition of SQL Server."

<!-- nav-footer-start -->

---

[← Previous: 03 — Data & Persistence](README.md) · [↑ Back to top](#ef-core) · [Next: LINQ →](02-linq.md)

<!-- nav-footer-end -->

</details>
