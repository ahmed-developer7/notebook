# MS SQL Server

> [Mastery Guide](../README.md) › [Data & Persistence](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-08 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Editions and licensing](#editions-and-licensing)
  - [T-SQL extensions over standard SQL](#t-sql-extensions-over-standard-sql)
  - [Indexes — clustered vs non-clustered](#indexes--clustered-vs-non-clustered)
  - [Execution plans and statistics](#execution-plans-and-statistics)
  - [Stored procedures, functions, triggers](#stored-procedures-functions-triggers)
  - [Locking, blocking, deadlocks](#locking-blocking-deadlocks)
  - [Backup, restore, point-in-time recovery](#backup-restore-point-in-time-recovery)
  - [Always On Availability Groups](#always-on-availability-groups)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--key-lookups-tanking-the-orders-search)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

SQL Server is Microsoft's flagship RDBMS and the dominant database in .NET shops. It has had decades of polish: world-class query optimizer, integrated full-text search, in-memory tables (Hekaton), columnstore indexes for analytics, Always On for HA, and tight tooling integration with Azure. If you're building enterprise .NET apps, you're going to deploy on SQL Server (or Azure SQL).

Why interviewers ask: SQL Server proficiency separates engineers who treat the DB as a black box from those who can read execution plans, design indexes, and tune for production load. T-SQL is its own dialect with rich features (window functions before standard SQL had them, JSON support, temporal tables) — knowing the strengths is part of the value.

When NOT to choose: cross-platform / Linux-first projects where Postgres is more idiomatic. Tiny apps where SQLite suffices. Massive analytics where a columnar store (Snowflake, BigQuery) wins.

> 🌍 **In the real world**: the question that separates candidates on this topic is not "what is a clustered index" — everyone has that answer. It is "here is the plan, tell me why it chose that." Ten-year .NET engineers routinely fail it, not because they don't know what a Key Lookup is, but because they have never once opened a plan for a query they wrote and had to defend the shape of it. The tell in an interview is the pronoun: candidates who have done it say "the optimizer estimated 50 and got 180,000"; candidates who haven't say "SQL Server was being slow." Everything else on this page is downstream of being able to read one plan properly.

## Core concepts

### Editions and licensing

| Edition | Use case | Cost notes |
|---|---|---|
| **SQL Server Express** | Dev, small apps (10 GB max DB) | Free |
| **SQL Server Developer** | Full features, dev/test only | Free |
| **SQL Server Standard** | Mid-tier production | Per-core, sold in 2-core packs |
| **SQL Server Enterprise** | All features, large deployments | Per-core, several times Standard |
| **Azure SQL Database** | PaaS managed | Per-vCore or DTU |
| **Azure SQL Managed Instance** | Lift-and-shift to PaaS | Per-vCore |

Licensing is per-core, sold in two-core packs, with **a minimum of four core licenses per physical processor** (not per server — the minimum applies to each socket). Don't quote per-core list prices from memory in an interview; quote the model and say prices change.

The documented scale limits, from Microsoft Learn's *Editions and supported features of SQL Server 2022*, are the ones worth remembering because they change architecture:

| Limit | Enterprise | Standard | Express |
|---|---|---|---|
| Max relational database size | 524 PB | 524 PB | 10 GB |
| Max buffer pool memory per instance | OS maximum | 128 GB | 1,410 MB |
| Max compute capacity | OS maximum | lesser of 4 sockets / 24 cores | lesser of 1 socket / 4 cores |

Editions gate features, not just size, and several of the gates catch teams mid-incident. From the same source: **Always On availability groups are Enterprise-only** (Standard gets *basic availability groups* — two replicas, one database, no readable secondary); **online index create and rebuild is Enterprise-only**, as are **resumable online index rebuilds**, **Resource Governor**, **memory-optimized tempdb metadata**, and most of the batch-mode Intelligent Query Processing features. Scalar UDF inlining, Query Store, PSP optimization, columnstore, In-Memory OLTP, Always Encrypted, row-level security and Accelerated Database Recovery are available on Standard.

For new projects, **Azure SQL** (PaaS) is the modern default — automatic backups, point-in-time restore, geo-replication, all without managing VMs.

> 🌍 **In the real world**: a team sized a new production instance on Standard edition because the licensing spreadsheet said Standard, and the design review only checked database size against the 524 PB figure. Two things bit them, six months apart. First, the server had 512 GB of RAM and the buffer pool refused to use more than 128 GB, so the hot working set kept getting evicted and `PAGEIOLATCH_SH` climbed while the OS reported gigabytes of free memory — the machine was not memory-starved, the *edition* was. Second, the runbook for the quarterly index rebuild had `WITH (ONLINE = ON)` copied from a blog post, and the maintenance window failed with an edition error at 2am, so the on-call engineer removed `ONLINE = ON` to make it run — and took an exclusive lock on the largest table for forty minutes. The transferable lesson: edition is a design input, not a procurement detail. Before you write `ONLINE = ON`, `ALTER RESOURCE GOVERNOR RECONFIGURE`, or an availability-group topology, check which column of the editions table you are actually in.

### T-SQL extensions over standard SQL

Microsoft's dialect adds significant features:

```sql
-- Variables & control flow
DECLARE @customerId INT = 7;
IF EXISTS (SELECT 1 FROM customers WHERE id = @customerId)
    PRINT 'Found';
ELSE
    PRINT 'Not found';

-- TOP with ties (ANSI: LIMIT)
SELECT TOP 10 WITH TIES * FROM orders ORDER BY total DESC;

-- MERGE (upsert)
MERGE INTO target_orders AS t
USING source_orders AS s ON t.id = s.id
WHEN MATCHED THEN UPDATE SET t.total = s.total
WHEN NOT MATCHED THEN INSERT (id, total) VALUES (s.id, s.total);

-- TRY...CATCH for error handling
BEGIN TRY
    BEGIN TRANSACTION;
    UPDATE accounts SET balance = balance - 100 WHERE id = 1;
    UPDATE accounts SET balance = balance + 100 WHERE id = 2;
    COMMIT;
END TRY
BEGIN CATCH
    ROLLBACK;
    THROW;   -- re-raise to caller
END CATCH;

-- OUTPUT clause — return modified rows from INSERT/UPDATE/DELETE
INSERT INTO audit_log (action, order_id)
OUTPUT inserted.id, inserted.timestamp
VALUES ('shipped', 42);

-- Table-valued parameters (pass a table to a stored proc)
CREATE TYPE OrderItemList AS TABLE (
    product_id INT, quantity INT
);

CREATE PROCEDURE InsertOrderItems @items OrderItemList READONLY AS
INSERT INTO order_items (product_id, quantity)
SELECT product_id, quantity FROM @items;
```

**Engine caveat on `MERGE`.** It is ANSI, but the dialects diverge on what you'd actually reach for. SQL Server has had `MERGE` since 2008 and it is the idiom most .NET codebases use. **PostgreSQL** only gained `MERGE` in **version 15**; before that (and still, for most upserts) the idiom is `INSERT ... ON CONFLICT (key) DO UPDATE`. **MySQL** has no `MERGE` at all — the idiom is `INSERT ... ON DUPLICATE KEY UPDATE`. If you say "I'd just use MERGE" in an interview about a Postgres system, expect the follow-up.

> 🌍 **In the real world**: an order-import job used `MERGE` to upsert line items and ran cleanly for a year on a single worker. Scaling the importer to four parallel workers produced duplicate-key violations on a table with a unique constraint — intermittently, on maybe one batch in fifty. The team's first theory was a bug in their partitioning of the input. It was not: two sessions can both evaluate `WHEN NOT MATCHED` before either one's `INSERT` commits, because under the default `READ COMMITTED` the read half of the `MERGE` takes no lock that survives to the write. The unique constraint was the only thing catching it, which is why it surfaced as an exception rather than as duplicate rows. `MERGE INTO target WITH (HOLDLOCK)` closed it by taking a range lock on the key being probed. The durable point is that `MERGE` reads as one atomic statement and is not one by default — a lot of seniors avoid it for upserts entirely and write `INSERT ... WHERE NOT EXISTS` under `SERIALIZABLE`, precisely so the locking is visible in the code.

JSON support (since SQL Server 2016):

```sql
-- Generate JSON from a query
SELECT id, name, email FROM customers FOR JSON AUTO;
-- → [{"id":1,"name":"Ahmed","email":"..."}, ...]

-- Query inside JSON columns
SELECT id, JSON_VALUE(metadata, '$.region') AS region
FROM orders
WHERE JSON_VALUE(metadata, '$.priority') = 'high';
```

Temporal tables (system-versioned):

```sql
CREATE TABLE orders (
    id INT PRIMARY KEY,
    total DECIMAL(10,2),
    valid_from DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
    valid_to   DATETIME2 GENERATED ALWAYS AS ROW END   NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
) WITH (SYSTEM_VERSIONING = ON);

-- Query the table as it was at a point in time
SELECT * FROM orders FOR SYSTEM_TIME AS OF '2025-01-01 00:00:00';
```

Free time-travel queries — invaluable for audit, debugging, "what changed?" investigations. Not free in storage, though: every `UPDATE` and `DELETE` writes a row to the history table, and nothing removes it unless you say so. SQL Server 2017 added a retention policy for exactly this:

```sql
ALTER TABLE orders
SET (SYSTEM_VERSIONING = ON (
    HISTORY_TABLE = dbo.ordersHistory,
    HISTORY_RETENTION_PERIOD = 6 MONTHS));
```

Microsoft Learn notes that a finite retention policy requires the history table to have a clustered index (B+ tree or columnstore); cleanup then runs as a background task.

> 🌍 **In the real world**: a team turned system versioning on for an `orders` table to satisfy an audit requirement, and the feature did exactly what it promised. Eighteen months later the database was several times its expected size and nobody could account for it, because the history table doesn't appear in the object explorer under the same name people were looking at and `sp_spaceused` on `orders` doesn't include it. The row that made it expensive was a nightly job that re-stamped a `LastSyncedAt` column on every order every night — an update that changed nothing anybody cared about, and wrote a full historical version of every row, every night. Two changes fixed it: move the churn column out of the versioned table, and set a `HISTORY_RETENTION_PERIOD`. The generic lesson is that system versioning charges you per *update*, not per meaningful change, so before you enable it, go and find out which columns your application writes on a timer.

### Indexes — clustered vs non-clustered

Every SQL Server table has at most **one clustered index**. The clustered index *is* the table — rows are physically stored in clustered-index order. By default, the primary key is clustered (so rows are stored in PK order).

```sql
-- Clustered index on Id (default for PK)
CREATE TABLE orders (id INT PRIMARY KEY, ...);

-- Non-clustered index — separate B-tree pointing back to clustered key
CREATE NONCLUSTERED INDEX ix_orders_customer ON orders(customer_id);
-- Lookup: scan ix_orders_customer for matching customer → use Id pointer → fetch row

-- Composite index
CREATE NONCLUSTERED INDEX ix_orders_customer_status
    ON orders(customer_id, status, created_at);

-- Covering index with INCLUDE — non-key columns to avoid lookup
CREATE NONCLUSTERED INDEX ix_orders_customer_covering
    ON orders(customer_id) INCLUDE (status, total);

-- Filtered index — only rows matching predicate
CREATE NONCLUSTERED INDEX ix_orders_pending
    ON orders(customer_id) WHERE status = 'Pending';
```

**Choosing a clustered key** is one of the most consequential design decisions. Microsoft Learn's *Index Architecture and Design Guide* tabulates six properties of a good clustered index key and gives the mechanical reason for each. Four of them drive the design:

- **Narrow.** "The clustered index key is a part of any nonclustered index on the same base table." Every extra byte in the clustered key is paid for again in every non-clustered index on the table. An `int` costs 4 bytes, a `bigint` 8, a `uniqueidentifier` 16.
- **Unique.** "If the clustered index isn't unique, a 4-byte internal uniqueifier column is automatically added to the index key to ensure uniqueness" — and it is then carried in every non-clustered index too.
- **Ever-increasing.** Inserts land on the last page, so pages fill rather than split.
- **Immutable.** Changing a clustered key column rewrites the entry in every non-clustered index, because the clustered key is the row locator.

The other two are cheaper wins the guide also lists: **not nullable only** (a nullable column forces a 3–4 byte NULL block per row) and **fixed-width columns only** (`varchar`/`nvarchar` cost an extra 2 bytes per value versus a fixed-width type).

Learn's own worked conclusion: "a clustered index key with a single **int** or **bigint** not nullable column has all of these properties if it's populated by an `IDENTITY` clause or a default constraint using a sequence and isn't updated after a row is inserted." A `uniqueidentifier` fails narrow at 16 bytes and, unless generated with `NEWSEQUENTIALID()`, fails ever-increasing too.

**What the non-clustered leaf actually contains** is the part most candidates get half-right, and it is what makes covering indexes make sense:

| Base table | Non-clustered index | Where the row locator goes |
|---|---|---|
| Heap | non-unique | **RID** (file:page:slot) added to the key columns |
| Heap | unique | RID added to the **included** columns |
| Unique clustered index | non-unique | clustered index key added to the **key** columns |
| Unique clustered index | unique | clustered index key added to the **included** columns |
| Non-unique clustered index | either | as above, plus the uniqueifier when present |

The rule underneath the table: the row locator has to make each non-clustered index row unique, so it joins the key when the index is not itself unique, and rides along as an included column when it is.

So a non-clustered index on `orders(customer_id)`, over a table clustered on `id`, physically stores `(customer_id, id)`. That's why `WHERE customer_id = 7` can return `id` for free, and why asking for `total` as well forces a Key Lookup into the clustered index — once per qualifying row.

**Key column order is not arbitrary.** The design guide's rule: "The column that is used in the query predicate in an equality (`=`), inequality (`>`,`>=`,`<`,`<=`), or `BETWEEN` expression, or participates in a join, should be placed first. Additional columns should be ordered based on their level of distinctness, that is, from the most distinct to the least distinct." In practice this means: **equality predicates first, then the one range predicate, then `INCLUDE` for everything the query merely returns.** For `WHERE status = 'Pending' AND created_at >= @from`, an index on `(status, created_at)` seeks straight to `status = 'Pending'` and then reads one contiguous `created_at` range inside it — both predicates are seek predicates. Reverse the key to `(created_at, status)` and you still get a *seek*, but only on `created_at >= @from`; `status` degrades to a residual predicate applied to every row in that range. Be precise about this in an interview: the wrong key order usually doesn't turn a seek into a scan, it turns a narrow seek into a wide one, and the plan still says "Index Seek" while reading a hundred times the rows. Compare **Seek Predicates** with **Predicate** in the operator's properties to tell them apart.

**SARGability — and the .NET trap.** A predicate is *searchable* (SARGable) if the engine can compare the parameter against the indexed column as stored. Wrap the column in anything and it can't:

```sql
-- Not SARGable: the column is wrapped in an expression → scan
WHERE YEAR(created_at) = 2025
WHERE LEFT(email, 5) = 'ahmed'
WHERE ISNULL(status, 'Pending') = 'Pending'
WHERE total * 1.2 > 100

-- SARGable rewrites (same result set, seekable)
WHERE created_at >= '2025-01-01' AND created_at < '2026-01-01'
WHERE email LIKE 'ahmed%'            -- a leading wildcard, '%ahmed', is NOT SARGable
WHERE status = 'Pending' OR status IS NULL
WHERE total > 100 / 1.2              -- move the arithmetic to the literal side
```

The one that actually bites .NET teams is invisible in the C#. ADO.NET sends a .NET `string` as `nvarchar` unless you tell it otherwise. SQL Server's documented data-type precedence ranks **`nvarchar` above `varchar`**, and "the data type with the lower precedence is first converted to the data type with the higher precedence" — so comparing an `nvarchar` parameter to a `varchar` column converts *the column*, on every row:

```sql
-- Plan shows: CONVERT_IMPLICIT(nvarchar(50), [email], 0) = @p0
--             Index Scan, plus a PlanAffectingConvert warning
```

The fix is on the .NET side, not the SQL side:

```csharp
// Dapper / raw ADO.NET
cmd.Parameters.Add("@email", SqlDbType.VarChar, 200).Value = email;
// or: new { email = new DbString { Value = email, IsAnsi = true, Length = 200 } }

// EF Core — declare the column non-Unicode so parameters are typed varchar
modelBuilder.Entity<Customer>().Property(c => c.Email).IsUnicode(false).HasMaxLength(200);
```

There is a collation nuance worth knowing because it explains why this bug is intermittent across servers: Jonathan Kehayias (SQLskills, *Implicit Conversions that cause Index Scans*) shows that with a **Windows** collation on the `varchar` column the optimizer can still seek despite the conversion, while with a **SQL** collation (`SQL_Latin1_General_CP1_CI_AS`, still the default on many legacy instances) it degrades to a scan. Same code, same schema, different server, different plan.

**Engine differences.** "The clustered index *is* the table" is a SQL Server and MySQL/InnoDB fact, not a general SQL one:

| | SQL Server | MySQL (InnoDB) | PostgreSQL |
|---|---|---|---|
| Table storage | clustered index, or a heap if none | always clustered by PK (or a hidden rowid) | always a heap |
| Secondary index leaf | clustered key (or RID) | primary key value | physical tuple id (`ctid`) |
| "Cluster the table" | `CREATE CLUSTERED INDEX`, maintained | implicit, maintained | `CLUSTER` — a **one-off** reorganisation, not maintained |
| Covering index | `INCLUDE` (non-key columns) | no `INCLUDE`; extra columns must be key columns | `INCLUDE` since PostgreSQL 11 |

The practical consequence: PostgreSQL's index-only scans depend on the visibility map rather than on the index owning the rows, and PostgreSQL has no permanently-clustered table — advice about "choose your clustered key carefully" simply doesn't transfer.

> 🌍 **In the real world**: an `Orders` table used `uniqueidentifier` defaulting to `NEWID()` as its primary key, and therefore as its clustered key, because the architects wanted IDs generated in the application. It behaved for two years at low volume. What changed was not the schema but the insert rate: at a few hundred orders a minute, each new random key landed in the middle of the B-tree, split a page, and the table's page density collapsed while write latency climbed — and every one of the six non-clustered indexes on the table got 16 bytes wider per row, because the clustered key is the row locator. The team's first instinct was to schedule index rebuilds nightly, which restored density for about four hours a day. The actual fix was to keep the GUID as a unique non-clustered key for the external contract and add an `INT IDENTITY` as the clustered key. Nothing above the data layer changed. The lesson is that "we generate IDs client-side" is a requirement about *uniqueness*, and people satisfy it by accidentally making a decision about *physical storage order* as well.

> 🌍 **In the real world**: a customer-lookup endpoint went from milliseconds to seconds after a release that "only added Dapper alongside EF Core". The SQL was identical to the EF query, the index on `Email` was untouched, and `SET STATISTICS IO ON` showed logical reads that matched a full scan of the table. The plan had `CONVERT_IMPLICIT(nvarchar(200),[Email],0)` on the column side and a yellow warning triangle on the SELECT operator. EF Core had been configured with `IsUnicode(false)` in the model years earlier, so its parameters arrived as `varchar`; the hand-written Dapper query passed a bare `string` and got `nvarchar`. Both were "parameterised" — the security property everyone checks was fine, and the performance property nobody checks was not. The permanent fix was a Dapper type handler that maps `string` to `DbString { IsAnsi = true }` by default. The diagnostic worth keeping: when a query scans an index that clearly covers it, read the *predicate* text in the plan, not just the operator name.

> 🌍 **In the real world**: a Database Engine Tuning Advisor run on a reporting workload produced eleven index recommendations, and a well-meaning engineer applied all eleven to the OLTP `Orders` table over a weekend. Reports got faster. Checkout got slower, and the pattern was maddening — p50 unchanged, p99 up by an order of magnitude, worst during the nightly import. Every `INSERT` now had to maintain twelve B-trees, every `UPDATE` to an indexed column had to move entries in several of them, and the import's lock footprint grew with the write amplification. `sys.dm_db_index_usage_stats` after two weeks showed four of the new indexes with zero `user_seeks` and millions of `user_updates`: pure cost. The lesson is that missing-index tooling scores the benefit to one query and never scores the cost to the write path, so its output is a list of candidates, not a plan. Read `user_seeks + user_scans + user_lookups` against `user_updates` before you keep an index, and remember that the DMV resets on instance restart — judge it over a full business cycle, not a Monday.

### Execution plans and statistics

Read execution plans to understand query performance.

```sql
-- Show actual plan for the next query
SET STATISTICS XML ON;
SELECT ... FROM ... ;
SET STATISTICS XML OFF;
```

In SQL Server Management Studio (SSMS): Ctrl+M (include actual execution plan), then run. The plan diagram shows:

```
SELECT ──┬── Hash Match (Aggregate) ──┬── Clustered Index Scan (orders)
         │                            │   "predicate: status = 'Pending'"
         │                            │   "rows: 50,000"
         │                            └── (estimates 25,000)
         │                                Difference → stale stats; UPDATE STATISTICS
```

Look for:
- **Index Scan** on big tables = missing or unusable index.
- **Sort** consuming most of the cost = consider an index that already sorts that way.
- **Hash Match** for joins is fine for big sets; **Nested Loops** for small.
- **Estimated vs Actual rows** widely different = stale statistics. `UPDATE STATISTICS table_name;` or `EXEC sp_updatestats;`.
- **Key Lookup** = non-covering index forced row fetches. Add covering INCLUDE.

`sys.dm_db_missing_index_details` and `sys.dm_db_index_usage_stats` show suggested and actual index usage.

**What an "estimate" actually is.** Every estimated row count traces back to a statistics object. Per Microsoft Learn's *Statistics* article, a statistics object holds two things: a **histogram** on the *first* key column only, aggregated into "a maximum of 200 contiguous histogram steps", and a **density vector** — one density per prefix of the key columns, where density is defined as "1/(number of distinct values)". Multiply density by the row count and you get the average number of rows per distinct value, which is the estimate the optimizer actually uses. It reads the histogram when it knows the value it is looking for, and falls back to the density vector when it doesn't. That single sentence explains most cardinality surprises, including the next one.

**Parameter sniffing** is the mechanism a senior interview will actually push on, and it is worth being able to explain end to end.

The optimizer compiles a plan for a parameterised statement *once*, using the parameter values present at compile time — Microsoft Learn's *Query Processing Architecture Guide* calls this sniffing: the engine "sniffs" the current parameter values during compilation and passes them to the optimizer "so that they can be used to generate potentially more efficient query execution plans." Values are sniffed for stored procedures, `sp_executesql`, and prepared queries. The resulting plan goes in the cache and is reused for every subsequent set of values.

That is a feature when the data is evenly distributed and a landmine when it is skewed:

```sql
CREATE OR ALTER PROCEDURE GetOrdersByCustomer @customerId INT AS
SELECT id, total, created_at, status, shipping_city
FROM orders WHERE customer_id = @customerId;
```

- Compiled first with `@customerId = 90210`, a customer with 3 orders → the histogram says 3 rows → **Index Seek + Key Lookup**, nested loops. Correct and fast.
- Reused with `@customerId = 1`, the house account with 4 million orders → the same plan does 4 million Key Lookups, one per row. The plan is not wrong for the value it was built for; it is catastrophic for this one.
- Compile it the other way round first and you get the mirror image: a scan-and-hash plan that is right for the house account and needlessly heavy for everybody else.

The symptom in production is the giveaway: **a procedure that is fast for months, then slow after a restart, a failover, a statistics update, or an index rebuild** — all of which evict or invalidate the cached plan, so the next caller's values become the ones the plan is built for. Nothing in the application changed, which is why it gets reported as "the database got slow."

Diagnosing it: pull the cached plan and compare the compiled parameter values with the runtime ones.

```sql
-- Showplan XML uses a default namespace, so WITH XMLNAMESPACES is mandatory —
-- without it every XPath below silently returns nothing.
WITH XMLNAMESPACES (DEFAULT 'http://schemas.microsoft.com/sqlserver/2004/07/showplan')
SELECT  qs.execution_count,
        qs.total_worker_time / qs.execution_count      AS avg_cpu_microseconds,
        p.n.value('@Column',                 'nvarchar(128)') AS parameter,
        p.n.value('@ParameterCompiledValue', 'nvarchar(256)') AS compiled_value
FROM    sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) qp
CROSS APPLY qp.query_plan.nodes('//ParameterList/ColumnReference') AS p(n)
WHERE   p.n.exist('@ParameterCompiledValue') = 1
ORDER BY avg_cpu_microseconds DESC;
```

The *cached* plan only carries `ParameterCompiledValue`. To see both sides of the comparison you need an **actual** plan — SSMS's "Include Actual Execution Plan" (Ctrl+M), then right-click the SELECT operator → Properties → Parameter List, which shows `Parameter Compiled Value` next to `Parameter Runtime Value`. A large gap between them is the diagnosis.

The remedies, in the order a senior would reach for them:

| Remedy | What it does | Cost |
|---|---|---|
| Fix the real cause | An index that makes both shapes cheap; refresh stale stats | Best, slowest |
| `OPTION (RECOMPILE)` | Compiles per execution with the actual values as constants; no plan is cached | CPU per call; fine for a low-frequency report, bad for a 10k/s endpoint |
| `OPTIMIZE FOR (@p = <value>)` | Pins the plan to a value you choose | You now own that choice forever |
| `OPTIMIZE FOR UNKNOWN` | Ignores the sniffed value; estimates from the **density vector** (average rows per distinct value) | Deliberately mediocre for everyone — a fair plan, never a great one |
| Local variable copy inside the proc | Same effect as `OPTIMIZE FOR UNKNOWN`, by accident | Invisible in the code; the classic "why is this slow" landmine |
| Query Store plan forcing | Freezes a known-good plan | A stopgap; audit `is_forced_plan = 1` or it rots |
| Split the procedure | Branch on the skewed value into two procs, each with its own cache entry | Ugly, effective, entirely under your control |

Note the local-variable row, because it is the trick people apply without knowing what it does. Assigning a parameter to a local variable defeats sniffing, and the guide is explicit about what you get instead: "When a query uses local variables, SQL Server can't sniff their values at compile time, so it estimates cardinality using available statistics or heuristics... it typically uses the **All Density value (also known as average density)**." If no statistics exist at all it falls back to fixed guesses — 10% selectivity for equality, 30% for inequality and range predicates.

**Version gate worth knowing.** SQL Server 2022 (16.x) under **database compatibility level 160** adds **Parameter Sensitive Plan (PSP) optimization**: the first compilation produces a *dispatcher plan* that bucketises at-risk predicates into cardinality ranges and routes each execution to a *query variant* with its own cached plan. Microsoft Learn states the limits plainly — it "currently only works with equality predicates", it evaluates "up to three" at-risk predicates, and it is disabled if parameter sniffing is off (`PARAMETER_SNIFFING` scoped configuration, trace flag 4136, or the `DISABLE_PARAMETER_SNIFFING` hint). SQL Server 2025 (17.x) at compatibility level 170 extends it to `INSERT`/`UPDATE`/`DELETE`/`MERGE`. So "SQL Server 2022 fixed parameter sniffing" is wrong in an interview; "2022 fixes the equality-predicate case if you're on compat 160" is right.

**Memory grants and spills.** Every plan with a Sort or a Hash operator asks for a memory grant *before* it runs, sized from the estimated row count and row width. Two failure modes follow directly:

- **Under-estimate → spill.** The grant is too small, the operator spills its workspace to `tempdb`, and the actual plan marks that operator with a spill warning ("Operator used tempdb to spill data during execution"); the matching Extended Events are `sort_warning` and `hash_warning`. A query with a good plan can still be slow purely because it is sorting on disk.
- **Over-estimate → queueing.** The grant is far larger than needed, and because grants come from a fixed pool, other queries wait for one. That wait is `RESOURCE_SEMAPHORE`, and it looks like the whole instance stalled rather than one query misbehaving.

`sys.dm_exec_query_memory_grants` shows what is granted and what is waiting. SQL Server 2017 (batch mode, compat 140) and 2019 (row mode, compat 150) added **memory grant feedback**, which corrects a repeating query's grant on subsequent executions. Know the limitation, because it is the follow-up question: in 2017 and 2019 the corrected grant lives **in the cached plan only** — "feedback isn't persisted if the plan is evicted from cache", and it is also lost on failover. SQL Server 2022 added *persistence and percentile mode*, which stores the feedback in Query Store (so it survives eviction) and sizes from a percentile of recent executions rather than only the last one; that variant requires Query Store enabled and in read-write state. All of these are Enterprise-edition features.

**Start with waits, not with queries.** Before opening any plan, ask the instance what it spent its time waiting on. `sys.dm_os_wait_stats` accumulates since the last restart or `DBCC SQLPERF('sys.dm_os_wait_stats', CLEAR)`; `sys.dm_exec_session_wait_stats` scopes it to a session. The waits that change your diagnosis:

| Wait | Documented meaning | Where to look |
|---|---|---|
| `PAGEIOLATCH_SH` | waiting on a buffer that "is in an I/O request... a mode used when the buffer is being read from disk" | storage, or a working set that doesn't fit in the buffer pool |
| `PAGELATCH_UP` | latch on an in-memory page, "commonly... when a system page (buffer) like PFS, GAM, SGAM is latched" | tempdb allocation contention |
| `LCK_M_X` | "waiting to acquire an Exclusive lock" | blocking — go to `sys.dm_exec_requests` |
| `RESOURCE_SEMAPHORE` | waiting for a memory grant | over-estimating plans |
| `CXPACKET` / `CXCONSUMER` | parallelism exchange | MAXDOP and cost threshold, not necessarily a problem |
| `ASYNC_NETWORK_IO` | "the task is blocked waiting for the client application to acknowledge that it has processed all the data sent to it" | **your .NET app**, not the database |

That last row is the one .NET engineers should have memorised. Microsoft Learn's own list of causes reads like a code review of a data-access layer: "writing results to a file while the results arrive, waiting for user input, client-side filtering on a large dataset instead of server-side filtering."

> 🌍 **In the real world**: a nightly billing procedure ran in about ninety seconds for a year, then started taking forty minutes — always after a Sunday-night failover, never on a Monday when the team looked at it, and never reproducible on a restored copy. Query Store showed two plans for the same query with a hundredfold difference in duration and no change to the SQL text. The parameter list in the slow plan's XML told the story: `Parameter Compiled Value = 1`, the internal system tenant with most of the rows, because the first call after failover was a health-check job that always passed tenant 1. Every other tenant then ran a plan built for the biggest one. The fix that shipped was two lines — the health check stopped using the production procedure, and the procedure got `OPTIMIZE FOR UNKNOWN` on the tenant parameter — and the lesson the team kept was subtler: *whatever calls your procedure first after a plan-cache eviction decides the plan for everybody*, so a synthetic monitoring call is a production performance decision.

> 🌍 **In the real world**: a support escalation said "the database is slow" and pointed at a report endpoint taking two minutes. `sys.dm_exec_requests` showed the session in `ASYNC_NETWORK_IO` for almost the entire duration and the query's own CPU time was under a second. The database had finished; it was waiting for the client to consume rows. The application was streaming 400,000 rows into a `List<T>`, then filtering and aggregating them in C# because that code predated the reporting requirement and nobody had revisited it. The database team was three days into a storage investigation before anyone read the wait type. Moving the filter and the aggregate into the query took the result set to a few hundred rows and the endpoint to under a second. The transferable habit: read the wait type before you form a theory, because `ASYNC_NETWORK_IO` is the engine telling you the bottleneck is on your side of the wire.

### Stored procedures, functions, triggers

> T-SQL syntax below. For vendor-neutral coverage (PostgreSQL `plpgsql`, when stored procs are the right choice vs. when they're an anti-pattern), see [SQL Mastery › Stored procedures, functions, triggers](./03-sql/09-advanced-patterns-and-interview-problems.md#stored-procedures-functions-triggers).

**Stored procedure:** named T-SQL block, compiled and cached:

```sql
CREATE OR ALTER PROCEDURE GetCustomerOrders
    @customerId INT,
    @startDate  DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;   -- skip rowcount messages
    SELECT id, total, created_at
    FROM orders
    WHERE customer_id = @customerId
      AND (@startDate IS NULL OR created_at >= @startDate);
END;

-- Call from .NET
EXEC GetCustomerOrders @customerId = 7, @startDate = '2025-01-01';
```

**Stored proc vs ad-hoc SQL** — debate that's mostly resolved. Modern .NET apps with EF Core mostly use ad-hoc SQL (parameterized). Stored procs still useful for:
- Complex multi-step business logic that needs to run server-side.
- Performance-critical queries where you want hand-tuned SQL.
- Security (grant EXEC on procs without table access).

**Dynamic SQL: `EXEC` vs `sp_executesql`.** Any procedure that builds SQL as a string has to choose, and the choice is both a security and a performance decision:

```sql
-- Wrong on both counts: injectable, and a new plan-cache entry per distinct value
EXEC('SELECT * FROM orders WHERE customer_email = ''' + @email + '''');

-- Right: parameterised, so the value is data, and one plan serves all values
EXEC sp_executesql
     N'SELECT id, total FROM orders WHERE customer_email = @e',
     N'@e nvarchar(200)',
     @e = @email;
```

Concatenation gives you an injection vector *and* a plan cache full of single-use plans, which evicts the plans that matter. `sys.dm_exec_cached_plans WHERE usecounts = 1` is where that shows up; the server-level `optimize for ad hoc workloads` setting caches a small stub on first execution instead of the full plan, which limits the damage without fixing the cause.

**User-defined functions:**

- **Scalar:** returns a single value. Microsoft Learn's *Scalar UDF Inlining* article gives four reasons they historically performed badly — "iterative invocation" (once per qualifying row, with context switching), "lack of costing" (the optimizer costs relational operators, not scalar ones), "interpreted execution" (statement by statement, no cross-statement optimization), and "serial execution": "SQL Server doesn't allow intra-query parallelism in queries that invoke UDFs."
  **Version gate.** SQL Server 2019 (15.x) at **database compatibility level 150** automatically inlines eligible scalar UDFs, transforming them into scalar expressions or subqueries so the optimizer can cost them and the plan can go parallel. Eligibility is narrow and has been tightened by cumulative updates — a UDF that calls `GETDATE()` or `NEWSEQUENTIALID()`, references table variables, uses `EXECUTE AS` other than `CALLER`, or contains multiple `RETURN` statements (CU5) is not inlineable. Check `sys.sql_modules.is_inlineable`, and confirm per-query by looking for the absence of a `<UserDefinedFunction>` node in the plan XML. So "scalar UDFs kill parallelism" is a **pre-2019 / pre-compat-150** claim, and saying it flatly is a good way to get corrected.
- **Inline table-valued (iTVF):** a parameterised view — the body is expanded into the calling query and optimized with it. Still the right answer when you want reusable logic without a performance cliff.
- **Multi-statement table-valued (mTVF):** the optimizer can't see inside, so it uses a **fixed cardinality guess of 100 rows** (and 1 row before SQL Server 2014) regardless of what the function actually returns. SQL Server 2017 (compat level 140) added **interleaved execution**: optimization pauses, the function is materialised, the real row count is fed back, and optimization resumes for everything downstream. It only helps read-only MSTVFs, and only when the skew actually changes the plan — Microsoft Learn notes "a basic `SELECT *` from an MSTVF doesn't benefit."

> 🌍 **In the real world**: a `dbo.fn_GetCustomerTier(@customerId)` scalar function was written for a display column, then reused in a `WHERE` clause on a reporting query — the same function, in a different position. On the display query it ran once per returned row and nobody noticed. In the predicate it ran once per *candidate* row, over the whole table, and the plan went serial because a scalar UDF was present. The report took eleven minutes on an instance with 32 cores that were doing nothing. The engineer who inherited it upgraded to SQL Server 2019 expecting inlining to fix it and it didn't, because the function called `GETDATE()` to decide the tier as of today — a time-dependent intrinsic, which the documentation lists as disqualifying. `sys.sql_modules.is_inlineable` returned 0 and said so in a second. The fix was to pass the date in as a parameter, which made the function inlineable and the plan parallel. The transferable point: a scalar UDF's cost depends on *where in the query it appears*, and inlining is a checklist you can query, not a promise.

**Triggers:** auto-fire on INSERT/UPDATE/DELETE. Use sparingly:
- Audit logging (better as a separate event-sourcing pattern).
- Cascading updates (often handled by FK constraints).
- Enforcing complex constraints not expressible in CHECK.

Triggers add hidden behavior; modern preference is to do this in app code or events.

### Locking, blocking, deadlocks

SQL Server uses pessimistic locking by default. Operations acquire locks:
- **Shared (S):** for reads.
- **Exclusive (X):** for writes.
- **Update (U):** intent to upgrade to X.
- **Intent (IS / IX):** signal at higher granularity.

**Isolation levels — what SQL Server actually does.** The engine implements the four ISO levels plus two row-versioning levels. From Microsoft Learn's *Transaction Locking and Row Versioning Guide*:

| Level | Dirty read | Non-repeatable read | Phantom | Mechanism |
|---|---|---|---|---|
| `READ UNCOMMITTED` | yes | yes | yes | no shared locks; `NOLOCK` is this per-table |
| `READ COMMITTED` (default) | no | yes | yes | shared locks held only for the duration of the read |
| `REPEATABLE READ` | no | no | yes | read and write locks held to end of transaction; no range locks |
| `SERIALIZABLE` | no | no | no | adds range locks on `WHERE` ranges |
| `READ COMMITTED SNAPSHOT` (RCSI) | no | yes | yes | row versions; **statement-level** read consistency |
| `SNAPSHOT` | no | no | no | row versions; **transaction-level** read consistency |

Two things in that table decide real designs:

- **RCSI is a database option, not a level you `SET`.** `ALTER DATABASE ... SET READ_COMMITTED_SNAPSHOT ON` changes what `READ COMMITTED` *means* for every existing query — no code changes. Readers stop taking shared locks (only a schema-stability `Sch-S` lock) and read the last committed version instead, so readers no longer block writers and writers no longer block readers.
- **`SNAPSHOT` is opt-in per transaction** (`SET TRANSACTION ISOLATION LEVEL SNAPSHOT`, after `ALTER DATABASE ... SET ALLOW_SNAPSHOT_ISOLATION ON`) and gives the whole transaction one consistent view. The price is a failure mode RCSI doesn't have: if two snapshot transactions modify the same row, the second gets **error 3960, "Snapshot isolation transaction aborted due to update conflict"** — a first-committer-wins abort your application must catch and retry, exactly like a deadlock. Update conflicts arise only when you *write* under `SNAPSHOT`; RCSI readers can't hit them.

Both versioning modes store the versions in `tempdb`, which is why enabling either one turns `tempdb` sizing into a capacity decision.

**Engine differences — the trap.** None of the defaults above are "how SQL works":

| | Default level | Reads block writers? | `READ UNCOMMITTED` | `REPEATABLE READ` phantoms |
|---|---|---|---|---|
| **SQL Server** | `READ COMMITTED` with locking (RCSI **off**) | yes, unless RCSI is on | genuine dirty reads | possible |
| **Azure SQL Database** | `READ COMMITTED` with RCSI **on** by default | no | as above | possible |
| **PostgreSQL** | `READ COMMITTED`, MVCC always | no, for plain reads | "behaves like Read Committed" — dirty reads are not implemented | **not possible**; PostgreSQL's Repeatable Read is snapshot isolation |
| **MySQL / InnoDB** | `REPEATABLE READ`, MVCC | no, for plain reads | supported | prevented for locking reads via gap / next-key locks |

Two of these are direct interview traps. First: the same code deployed to SQL Server on-premises and to Azure SQL Database runs at different effective isolation, because Azure SQL Database ships with `READ_COMMITTED_SNAPSHOT ON` and SQL Server and Managed Instance ship with it `OFF`. Second: "add `NOLOCK` for a fast dirty read" is meaningless advice on PostgreSQL, whose documentation states that Read Uncommitted "behaves like Read Committed" because that "is the only sensible way to map the standard isolation levels to PostgreSQL's multiversion concurrency control architecture."

**Lock escalation** is the mechanism behind most "one query took the whole database out" incidents, and it is a specific, documented threshold rather than a vague resource limit. From the same guide: escalation triggers when "a single Transact-SQL statement acquires at least **5,000 locks** on a single nonpartitioned table or index"; if escalation is blocked by a conflicting lock, the engine retries "at every 1,250 new locks acquired." There's also a memory trigger — with the default `locks` setting of 0, escalation fires when lock objects consume 24 percent of Database Engine memory.

Escalation goes row/page → **table** (or partition, with `LOCK_ESCALATION = AUTO` on a partitioned table). It does not go to page first. So a `DELETE` that touches 5,000 rows on a busy table can convert thousands of harmless row locks into one exclusive table lock, and every other session on that table stops.

```sql
-- Delete in batches so no single statement crosses the threshold
WHILE 1 = 1
BEGIN
    DELETE TOP (2000) FROM dbo.orders WHERE created_at < '2023-01-01';
    IF @@ROWCOUNT = 0 BREAK;
    WAITFOR DELAY '00:00:00.100';   -- let other sessions in
END

-- Per-table control (AUTO honours partitioning; TABLE forces it; DISABLE tries to avoid it)
ALTER TABLE dbo.orders SET (LOCK_ESCALATION = AUTO);
```

Note what RCSI does *not* fix: it removes shared locks from readers, so escalation on a read is no longer a concern, but a `DELETE` or `UPDATE` still takes exclusive locks and still escalates. Row versioning is not a substitute for batching your writes.

**Blocking** = one transaction waiting for another's lock. Normal for short transactions; problematic when long-running blockers stall the system.

```sql
-- Find blocking sessions
SELECT
    blocking_session_id, session_id, wait_time, wait_type, wait_resource
FROM sys.dm_exec_requests
WHERE blocking_session_id != 0;

-- Inspect what a session is doing
SELECT t.text FROM sys.dm_exec_requests r
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE r.session_id = 53;
```

**Deadlock** = two transactions each holding a lock the other wants. SQL Server auto-detects and kills one (the "deadlock victim").

Mitigations:
- **Consistent lock order.** If T1 locks A then B, T2 must do the same.
- **Short transactions.** Long ones widen the deadlock window.
- **Lower isolation level** if business logic permits.
- **Read Committed Snapshot Isolation (RCSI):** versioning-based reads, no shared locks for SELECT. Often dramatically reduces blocking.

```sql
-- Requires exclusive access to the database; without the ROLLBACK clause this
-- statement blocks until every other session disconnects, and typically hangs.
ALTER DATABASE MyDb SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
```

RCSI is the most-recommended default tweak for high-concurrency apps. Three things to say about it in an interview so it doesn't sound like a slogan:

1. It shifts cost to `tempdb` — every version chain lives there, and a long-running reader keeps versions alive for as long as it runs. `sys.dm_tran_version_store_space_usage` and `sys.dm_tran_active_snapshot_database_transactions` are where you watch it.
2. It adds **14 bytes** of versioning overhead to each modified row — a 6-byte transaction sequence number plus an 8-byte pointer to the versioned row, per Microsoft's *Overhead of Row Versioning* engine post. On tables whose pages were previously packed full, the first update of each row grows it and can split the page, so a one-off burst of fragmentation after enabling RCSI is expected, not a bug.
3. It changes read semantics: a reader now sees the state at the start of *its statement*, not the state after the blocking writer commits. Code that relied on readers queueing behind writers — a poll-and-claim queue table, say — can start handing the same row to two workers. Under locking `READ COMMITTED` the second reader waited; under RCSI it reads the old version and proceeds. If a query's correctness depends on blocking, say so explicitly with `UPDLOCK, READPAST` rather than relying on the isolation level to enforce it.

> 🌍 **In the real world**: a monthly reconciliation report was moved into a maintenance window because "it locks the database", and it did — a single `SELECT` across a year of `orders` under the default locking `READ COMMITTED` took shared locks, and because the scan covered essentially the whole table the engine ended up holding a table-level shared lock rather than millions of row locks — which blocked every writer for the eleven minutes it ran. (Worth being precise in an interview: escalation is counted on locks a statement *holds*, and locking `READ COMMITTED` releases each shared lock as soon as the row is read, so escalation is far more often a *writer's* problem. A big reader gets you there by the lock manager choosing table granularity for a full scan.) Checkout timed out; the incident was filed against checkout. The team's first fix was `WITH (NOLOCK)` on the report, which worked in the sense that the blocking stopped and failed in the sense that the finance numbers stopped reconciling — allocation-order scans under read-uncommitted can miss rows and count others twice when pages move underneath them. What actually fixed it was enabling RCSI, after which the report took no shared locks at all and needed no hint. The lesson is that `NOLOCK` and RCSI look like the same fix from the outside — "readers stop blocking writers" — and only one of them still returns correct rows.

> 🌍 **In the real world**: a data-retention job deleted old rows with a single `DELETE FROM events WHERE created_at < @cutoff`, which had been fine for two years because the nightly volume was a few thousand rows. Someone paused the job for a fortnight during a migration. When it resumed it matched about 900,000 rows in one statement, escalated to an exclusive table lock, and held it while the transaction log grew to fill the disk — at which point the delete rolled back, taking roughly as long again, still holding the lock. Total outage on that table: over an hour, for a maintenance job nobody thought of as risky. The rewrite was five lines: `DELETE TOP (2000)` in a loop with a short `WAITFOR` between batches, each batch its own transaction, so no statement approached 5,000 locks and the log could be truncated between them. The habit worth taking: any statement whose row count depends on how long since it last ran needs a batch loop, because "it has always been small" is not a property of the statement.

### Backup, restore, point-in-time recovery

Three backup types:
- **Full:** entire database.
- **Differential:** changes since last full.
- **Log:** transaction log (only meaningful in FULL recovery model).

**Recovery models:**
- **Simple:** log truncated automatically; no point-in-time recovery. OK for dev.
- **Bulk-Logged:** for bulk operations.
- **Full (production default):** log preserved; can restore to any point in time.

**Why the transaction log exists, and why it grows.** SQL Server is a write-ahead logging engine: a change is written to the log and hardened to disk *before* the data page is written, which is what makes `COMMIT` durable without waiting for a random write to the data file. The log is a circular structure of virtual log files (VLFs); a VLF can be reused once its records are no longer needed for recovery, replication or a backup. "The log file is full" almost never means the disk is full — it means something is preventing reuse, and SQL Server will tell you what:

```sql
SELECT name, recovery_model_desc, log_reuse_wait_desc
FROM sys.databases WHERE name = 'MyDb';
```

| `log_reuse_wait_desc` | What it means | What to do |
|---|---|---|
| `LOG_BACKUP` | FULL recovery model, and nobody is taking log backups | take log backups on a schedule — this is the most common answer by a wide margin |
| `ACTIVE_TRANSACTION` | an open transaction is pinning the log | find it (`DBCC OPENTRAN`, `sys.dm_tran_active_transactions`) — usually a `BEGIN TRAN` someone never committed |
| `AVAILABILITY_REPLICA` | a secondary hasn't hardened the log records yet | fix replication lag or the replica's health |
| `REPLICATION` / `CHECKPOINT` | log reader agent behind, or checkpoint pending | investigate the specific subsystem |
| `NOTHING` | log is reusable | your growth is genuine — size the file properly |

The mistake to avoid: shrinking the log file. Shrinking releases space that the workload immediately re-grows, and log growth is expensive because the new space has to be zero-initialised — instant file initialization skips that zeroing for data files, but only when the service account holds the *Perform volume maintenance tasks* (`SE_MANAGE_VOLUME_NAME`) privilege, and only from **SQL Server 2022 (16.x)** does it apply to log autogrowth at all — then only for growth events up to 64 MB, and without needing that privilege. Repeated shrink-and-grow also produces thousands of tiny VLFs, which slows recovery and log backups. Shrink once after a genuine one-off event, then set the file to the size it actually needs and give it a fixed growth increment rather than a percentage.

**A backup you have not restored is not a backup.** `BACKUP ... WITH CHECKSUM` and `RESTORE VERIFYONLY` catch media problems but do not prove the chain restores; only restoring it does. The two numbers to be able to state in an interview are **RPO** (how much data you can afford to lose — set by log-backup frequency) and **RTO** (how long a restore takes — set by database size, and by whether anyone has ever timed it).

```sql
-- Backup
BACKUP DATABASE MyDb TO DISK = 'C:\Backups\MyDb_full.bak'
WITH FORMAT, INIT, COMPRESSION;

BACKUP LOG MyDb TO DISK = 'C:\Backups\MyDb_log.trn';

-- Point-in-time restore (full + diff + logs up to target time)
RESTORE DATABASE MyDb FROM DISK = '...\MyDb_full.bak' WITH NORECOVERY;
RESTORE LOG MyDb FROM DISK = '...\MyDb_log.trn'
    WITH STOPAT = '2025-05-06 14:30:00', RECOVERY;
```

Azure SQL automates this: every database gets automatic full, differential and log backups, with point-in-time restore retention of **7 days by default, configurable between 1 and 35 days** (Basic-tier databases: 1 to 7 days), per Microsoft Learn's *Automatic, geo-redundant backups* article. Longer retention needs a separate long-term retention policy, up to 10 years. You cannot download or directly access those backups — they exist only to restore from, which matters if your compliance requirement is "hand the auditor a `.bak`."

> 🌍 **In the real world**: a team discovered during an incident that their production database had been in `SIMPLE` recovery for three years. It was restored from a template created for a development environment, and nothing in the deployment pipeline asserted the recovery model. Nightly full backups were running and monitored and green, so every dashboard said backups were healthy. They were: the team could restore to 01:00 and no later, and the incident happened at 16:00. Fifteen hours of orders were unrecoverable from backups and had to be reconstructed from the payment provider's records over four days. The two-line postmortem action was a nightly check comparing `sys.databases.recovery_model_desc` and the age of the last log backup against expectations, alerting on drift. Backup monitoring that only watches the backup *job* answers "did it run", which is not the question — the question is "what is my worst-case data loss right now", and that is a query, not a job status.

> 🌍 **In the real world**: an on-call engineer was paged for "transaction log full, database read-only" on a Sunday, found a 400 GB log next to a 60 GB database, and did the thing every search result suggests: switched to `SIMPLE`, shrank the log, switched back to `FULL`. Service returned in ten minutes and the incident was closed. It had also silently broken the log chain, so the next log backup had nothing to chain to and point-in-time recovery was gone until the next full backup ran — twelve hours later, a window nobody knew existed. `log_reuse_wait_desc` would have said `ACTIVE_TRANSACTION` and `DBCC OPENTRAN` would have named a session left open by a deployment script that had crashed on Friday. Killing that one session would have released the log in seconds with no side effects. The point isn't that shrinking is always wrong; it's that the field telling you the actual cause takes five seconds to read and the reflex fix costs you your recovery point.

### Always On Availability Groups

High availability + disaster recovery feature, **Enterprise edition only** — Standard edition gets *basic availability groups*, which are two replicas, one database, and no readable secondary. On Enterprise:
- Up to 8 secondary replicas (nine availability replicas in total). Read the synchronous limit carefully, because it is stated *including the primary*: SQL Server 2019 (15.x) raised the maximum to **five synchronous-commit replicas including the current primary** — one primary plus four synchronous secondaries — up from three in SQL Server 2017 (14.x). Everything above that count must be asynchronous.
- Synchronous (commit waits for the secondary to harden the log — RPO 0) or asynchronous (commit returns immediately — RPO > 0) replication.
- **Automatic failover** requires all of: synchronous-commit availability mode, failover mode set to automatic on both the primary and that secondary, the secondary already synchronized, and WSFC quorum plus the availability group's flexible failover policy conditions. There is no approval step — if those conditions hold, the cluster fails over on its own; if any of them doesn't, the AG will not fail over automatically no matter what the configuration screen says. Anything else is a manual (or forced, with possible data loss) failover. Note also that a replica hosted on a failover cluster instance can only be configured for manual failover.
- Read-only routing for read replicas.

```
Primary (datacenter A)
    │ synchronous
    ▼
Secondary 1 (datacenter A) ← auto-failover target
    │ asynchronous
    ▼
Secondary 2 (datacenter B) ← DR replica
```

The .NET side of an AG is two connection-string keywords, and both are routinely missed:

```csharp
// Connect through the AG listener, not a node name.
// MultiSubnetFailover=True makes SqlClient try all listener IPs in parallel —
// without it, a cross-subnet failover waits on TCP timeouts to the dead subnet.
"Server=tcp:ag-listener,1433;Database=MyDb;MultiSubnetFailover=True;..."

// Read-only routing only happens if the client asks for it.
"Server=tcp:ag-listener,1433;Database=MyDb;ApplicationIntent=ReadOnly;..."
```

In Azure SQL: built-in geo-replication serves the same purpose with simpler ops.

> 🌍 **In the real world**: a team built an availability group specifically to move reporting off the primary, configured read-only routing, ran the reports, and measured no change in primary CPU. The reports were connecting through the listener with a default connection string, so `ApplicationIntent` was absent and every query landed on the primary — read-only routing had been configured correctly and was never invoked, because routing is triggered by the *client's* declared intent, not by the query. Nothing errored, nothing logged, and the secondary sat idle for four months. `sys.dm_exec_sessions` on the primary, grouped by `program_name`, found it in a minute once someone thought to look. The second half of the lesson arrived a week after they fixed the connection string: an async secondary is behind by an amount that varies with write load, so an operations report that had always agreed with the admin screen started disagreeing during the nightly import. Read replicas are a consistency decision wearing the costume of an infrastructure decision.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Clustered vs non-clustered index storage

```
Clustered index on orders(id):

Leaf level = the table itself, sorted by id:
[id=1, customer_id=7, total=...] [id=2, ...] [id=3, ...]
B-tree index above points to leaf pages by id range.

Non-clustered index on orders(customer_id):

Separate B-tree:
[customer_id=7, id=1] [customer_id=7, id=42] ...   ← sorted by customer_id
                  │
                  ▼ (id is pointer back to clustered index)
[id=1, customer_id=7, total=...]   ← row in table

Lookup "all orders for customer 7":
1. Seek into ix_orders_customer (B-tree) for customer_id = 7
2. For each match, look up the row by id (Key Lookup)
3. Return data

Costly if many matches. Fix: add INCLUDE columns to make it a covering index.
```

### Index-tuning workflow

```
1. Identify slow query (SSMS, app logs, sys.dm_exec_query_stats)

2. Get actual execution plan
   ↓
3. Check for:
     - Sequential scans on big tables
     - Sort operations that match no index
     - Key Lookups (non-covering index)
     - High estimated vs actual row count (stale stats)

4. Try: add index suggested by sys.dm_db_missing_index_details
   ↓
5. Verify: re-run query, check plan, measure latency

6. Watch: sys.dm_db_index_usage_stats for unused indexes (write cost no benefit)
```

### A worked plan, before and after

The query: "orders for one customer in the last 30 days, newest first."

```sql
SELECT id, status, total, shipping_city
FROM   dbo.orders
WHERE  customer_id = @customerId
  AND  created_at >= DATEADD(day, -30, SYSUTCDATETIME())
ORDER BY created_at DESC;
```

**Before** — the only useful index is `ix_orders_customer ON orders(customer_id)`:

```
                                                  est.   actual
SELECT
 └─ Sort  (ORDER BY created_at DESC)                 50    1,200   cost 22%
     └─ Nested Loops (inner join)
         ├─ Index Seek  ix_orders_customer          50    28,400   cost  3%
         │    Seek Pred: customer_id = @customerId
         └─ Key Lookup  PK_orders (clustered)        1         1   cost 75%
              Predicate: created_at >= ...    ← the filter lives HERE, not on the seek
              executed 28,400 times, returned 1,200 ─────────────┘
```

Three separate signals, all visible without touching a stopwatch:

1. **Estimate 50, actual 28,400.** The optimizer chose Nested Loops + Key Lookup because it expected 50 rows; a lookup per row is cheap 50 times and ruinous 28,400 times. Either the statistics are stale or the parameter was sniffed for a customer with almost no orders.
2. **The date filter can't be evaluated at the seek at all.** `created_at` isn't in `ix_orders_customer` — not as a key column, not as an included column — so it can't be a seek predicate *or* a residual predicate on the seek. It becomes a predicate on the Key Lookup: the engine fetches all 28,400 of the customer's rows from the clustered index and *then* throws away the 27,200 that fall outside the window. Reading which operator carries the predicate is the whole diagnosis.
3. **A Sort at 22% of cost** for an `ORDER BY` that an index could have satisfied for free.

**After** — one index that carries the range column in the key and the projection in `INCLUDE`:

```sql
CREATE NONCLUSTERED INDEX ix_orders_customer_created
    ON dbo.orders (customer_id, created_at DESC)
    INCLUDE (status, total, shipping_city);
```

```
SELECT
 └─ Index Seek  ix_orders_customer_created       1,200   1,200    cost 100%
      Seek Pred: customer_id = @customerId
                 AND created_at >= ...           ← now part of the seek
      Ordered: True  (DESC matches the ORDER BY)
```

No Key Lookup (the `INCLUDE` columns cover the projection), no Sort (the index is already in the requested order), and the seek reads only the qualifying range instead of the customer's whole history. Note the key order — equality column first, range column second — and that `DESC` in the index definition is what removes the Sort rather than merely reducing it.

### Connection from .NET

```csharp
// Connection string with key options
var conn = "Server=tcp:myserver.database.windows.net,1433;" +
           "Database=MyDb;" +
           "Authentication=Active Directory Default;" +    // managed identity in Azure
           "Encrypt=True;TrustServerCertificate=False;" +
           "Connection Timeout=30;" +
           "MultipleActiveResultSets=False;";

// In Program.cs
builder.Services.AddDbContext<AppDbContext>(opt =>
    opt.UseSqlServer(builder.Configuration.GetConnectionString("Default"),
        sql =>
        {
            sql.EnableRetryOnFailure(maxRetryCount: 3);   // for transient Azure SQL failures
            sql.CommandTimeout(30);
        }));
```

For Azure SQL: use **Microsoft Entra (Active Directory)** authentication via Managed Identity — no passwords in config.

</details>

## Common pitfalls

1. **GUID clustered key without `NEWSEQUENTIALID`.** Random inserts cause massive page splits. Use INT/BIGINT identity, or sequential GUIDs.
2. **Leaving tables as heaps.** No clustered index = a "heap". The specific problem isn't that scans are inherently slower — it's *forwarded records*: when an update widens a row past what its page can hold, the row moves and a forwarding pointer is left behind, so every read that arrives via a non-clustered index (whose leaf holds a RID) takes an extra hop, forever, until the heap is rebuilt. `sys.dm_db_index_physical_stats(..., 'DETAILED')` reports `forwarded_record_count`. Add a clustered key (the PK usually works).
3. **Indexing every column.** Each index has insert/update/delete cost. Profile actual query patterns; remove unused indexes (`sys.dm_db_index_usage_stats`).
4. **Stale statistics.** Optimizer picks bad plans. Auto-update stats helps; for very large tables, add scheduled `UPDATE STATISTICS WITH FULLSCAN`.
5. **Implicit type conversion in WHERE.** `WHERE int_column = '7'` (string literal) forces conversion → no index seek. Match types exactly.
6. **`NOLOCK` everywhere.** "Magic faster" hint = read uncommitted = potentially incorrect data (dirty reads, double-count rows due to scans). Use RCSI instead.
7. **Long open transactions.** Acquired locks held → blocking spreads. Keep transactions narrow; never include user-input wait inside.
8. **Mixing transactions with HTTP calls.** "Begin TX → call payment API → commit" — connection held for the API duration. Pre-commit, then call; or use sagas.
9. **`MERGE` in concurrency.** Has known race conditions in some isolation levels. Use explicit `INSERT ... WHERE NOT EXISTS` or `MERGE` with `HOLDLOCK` hint when needed.
10. **Stored procs with sensitive logic but no version control.** "Last edited in SSMS by some intern in 2017." Treat schema and procs as code; check into git.
11. **Recovery model "Simple" in production.** No log backups → no point-in-time recovery. Use FULL with regular log backups.
12. **Never running DBCC CHECKDB.** Detects on-disk corruption. Run weekly on production.
13. **.NET strings against `varchar` columns.** ADO.NET sends `string` as `nvarchar`; `nvarchar` outranks `varchar` in data-type precedence, so the *column* gets converted and the seek becomes a scan. Fix in the client (`SqlDbType.VarChar`, Dapper's `DbString { IsAnsi = true }`, EF Core's `IsUnicode(false)`), not by rewriting the SQL.
14. **Single-statement bulk deletes and updates.** At 5,000 locks on one table SQL Server escalates to a table lock. Batch anything whose row count grows with elapsed time since the last run.
15. **Assuming Azure SQL Database and SQL Server behave the same under concurrency.** Azure SQL Database ships with `READ_COMMITTED_SNAPSHOT ON`; SQL Server and Managed Instance ship with it `OFF`. The same code runs at different effective isolation in each.
16. **Scheduled shrinks.** `DBCC SHRINKDATABASE` / `SHRINKFILE` on a timer releases space the workload immediately re-grows, and shrinking a data file fragments every index in it as a side effect (the shrink moves pages to the front of the file with no regard for index order). Shrink once after a genuine one-off deletion, then leave it alone.
17. **Treating a green backup job as a recovery plan.** The job status answers "did it run", not "what is my worst-case data loss" and not "how long does a restore take". Both of those are only answerable by restoring.

## Interview-ready summary

- **Editions:** Express (free, 10 GB), Standard (128 GB buffer pool, no Always On AGs, no online index rebuild), Enterprise (full features). Azure SQL = PaaS.
- **Indexes:** clustered = the table itself (one per table). Non-clustered = separate B-tree whose leaf holds the clustered key (or a RID on a heap). Key order: equality columns, then the range column, then `INCLUDE` for the projection.
- **T-SQL extras:** TOP, MERGE, OUTPUT, table-valued parameters, JSON support, temporal tables.
- **Statistics:** histogram of at most 200 steps on the leading column, plus a density vector. The optimizer uses the histogram when it knows the value and the density vector when it doesn't.
- **Parameter sniffing:** one plan is compiled for the first values seen and reused for all. Remedies: `RECOMPILE`, `OPTIMIZE FOR`, `OPTIMIZE FOR UNKNOWN`, plan forcing, splitting the proc — or PSP optimization on SQL Server 2022 at compat 160, equality predicates only.
- **Locking:** S/X/U/IS/IX. RCSI = versioned reads, no shared locks for SELECT, statement-level consistency. `SNAPSHOT` = transaction-level consistency plus update conflicts (error 3960). Escalation to a table lock at 5,000 locks in one statement.
- **HA/DR:** Always On Availability Groups (Enterprise, on-prem); geo-replication (Azure SQL).
- **Backups:** Full + Differential + Log → point-in-time recovery (FULL recovery model). `log_reuse_wait_desc` tells you why the log won't truncate.

**Expected interview questions:**

1. *"Clustered vs non-clustered index?"* — Clustered: rows physically sorted by index key; one per table. Non-clustered: separate B-tree with pointers (clustered key) back to rows. Covering index with INCLUDE avoids the lookup.
2. *"What's RCSI and when to use it?"* — Read Committed Snapshot Isolation: SELECTs use row versions instead of shared locks, dramatically reducing blocking. Enable on most production databases.
3. *"How do you find slow queries?"* — `sys.dm_exec_query_stats` for top consumers; SSMS Activity Monitor; Query Store (built-in performance history); execution plans.
4. *"How do you avoid deadlocks?"* — Consistent lock ordering across transactions. Keep transactions short. Use RCSI to reduce shared-lock contention. Set deadlock priority for important sessions.
5. *"GUID vs INT for primary key?"* — INT identity for performance and clustered-key efficiency. GUID if you need cross-server uniqueness or to generate IDs client-side. If GUID, use `NEWSEQUENTIALID` to avoid fragmentation.
6. *"What's the difference between TRUNCATE and DELETE?"* — TRUNCATE deallocates pages (fast, can't filter, can't be in some replication scenarios). DELETE removes rows (logs each, can WHERE-filter, triggers fire).
7. *"What's a Key Lookup and how do you eliminate it?"* — Non-clustered index has a key but query needs additional columns → SQL Server fetches each row from clustered index. Eliminate with `INCLUDE` covering index, or use index intersection.
8. *"A stored procedure was fast for months and is slow since Sunday, with no code change. What happened?"* — Parameter sniffing. A restart, failover, statistics update or index rebuild evicted the cached plan, and whoever called first supplied atypical values. Confirm by comparing "Parameter Compiled Value" with "Parameter Runtime Value" in the plan properties, or by diffing the two plans in Query Store. Then choose a remedy deliberately rather than sprinkling `RECOMPILE`.
9. *"Difference between RCSI and SNAPSHOT isolation?"* — Both read row versions from `tempdb`. RCSI is a database option that redefines `READ COMMITTED` and gives *statement*-level consistency; SNAPSHOT is opt-in per transaction and gives *transaction*-level consistency. Only SNAPSHOT produces update conflicts (error 3960), because only SNAPSHOT lets a transaction write against a snapshot taken earlier.
10. *"One report brought the whole database to a halt. How?"* — Table-level shared locking under locking `READ COMMITTED`: a full-table scan either takes table granularity outright or escalates to it (escalation triggers at 5,000 locks held by one statement, retried every 1,250 thereafter), and a shared table lock blocks every writer for as long as the statement runs. The mirror-image answer for writes is the same mechanism: a bulk `DELETE`/`UPDATE` holds its exclusive row locks to the end of the transaction, so it reaches 5,000 easily. Fixes: RCSI so readers take no shared locks, batching for writes, or a readable secondary for reporting. `NOLOCK` also stops the blocking, and gives you dirty reads, missed rows and double-counted rows in exchange.
11. *"Why might a query with a perfect index still be slow?"* — Several answers, and a good candidate names more than one: it spilled its sort or hash to `tempdb` because the memory grant was undersized (warning on the operator in the actual plan); it waited on `RESOURCE_SEMAPHORE` for a grant; it's SARGable in appearance but the plan shows `CONVERT_IMPLICIT` on the column; or the wait is `ASYNC_NETWORK_IO` and the engine finished long ago while the client consumed rows one at a time.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — Query Store

> **Q**: What is Query Store and what problem does it solve?
>
> **A**: A built-in feature (SQL Server 2016+, on by default in Azure SQL, and **on by default for all newly created databases from SQL Server 2022 (16.x)** — older databases upgraded in place still need it enabled) that captures query plans and runtime statistics over time. It records every query's compile time, execution count, CPU, IO, and stores the plans themselves. The problem it solves: "the query was fast yesterday and slow today" — without Query Store you have no plan history; with it, you can see exactly which plan was used when and force the old plan if a regression hits. Persistent across restarts and contained in user databases.
>
> **Cross-Q**: A query that ran in 50ms now runs in 8s after a SQL Server upgrade. How does Query Store help you fix it?
>
> **A**: Open the "Regressed Queries" report in SSMS — it ranks queries by performance change. Find the offender; you'll see two plans: yesterday's fast one and today's slow one. The cardinality estimator (CE) likely picked a different plan after the upgrade (CE versions change between SQL Server major releases). Force the old plan: `EXEC sp_query_store_force_plan @query_id, @plan_id`. The optimizer will use that plan for matching queries until you unforce or it becomes invalid. Buy time to investigate the root cause without rolling back the upgrade.
>
> **Cross-Q²**: When does forcing a plan backfire?
>
> **A**: When the forced plan is good for the parameter values you tested but bad for others (parameter sniffing in reverse). Or when underlying data distribution changes — the forced plan was great for 1M rows but is terrible at 50M. Or when you forget about the forced plan and it silently slows down years later as workloads evolve. Forced plans are a **stopgap**, not a fix. The real fix is updating stats, adding indexes, or rewriting the query so the optimizer naturally picks the right plan. Periodically audit `sys.query_store_plan WHERE is_forced_plan = 1` to find forced plans that should be retired.

### Drill 2 — Columnstore indexes and segment elimination

> **Q**: What's the difference between a clustered columnstore and a non-clustered columnstore index?
>
> **A**: **Clustered columnstore** — the entire table is stored in columnar format. Best for fact tables in data warehouses that are append-mostly and queried with aggregates. **Non-clustered columnstore** — a secondary index alongside a regular B-tree rowstore. Used for hybrid transactional/analytical workloads (HTAP) — the row-store handles OLTP point lookups; the columnstore handles analytical queries on the same table without ETL to a separate warehouse.
>
> **Cross-Q**: Explain segment elimination in a columnstore.
>
> **A**: Columnstore data is stored in **row groups** of ~1M rows each. For every column in every row group, SQL Server records min/max in metadata. When a query has `WHERE order_date >= '2025-01-01'`, the optimizer checks each row group's min/max for `order_date` and skips groups whose max is before 2025 — never reads those segments. Massively reduces IO for date-filtered queries on time-series fact tables.
>
> **Cross-Q²**: Segment elimination only works if data is loaded in a way that aligns with query filters. What does that mean in practice?
>
> **A**: Load `fact_sales` in date order (or partition by date) so each row group contains a contiguous date range. Then `WHERE date BETWEEN A AND B` prunes to a few segments. Load randomly (interleaved dates across all row groups) and every segment spans the entire date range — segment elimination is useless because every group's min/max covers the filter. The practical pattern: partition by date, load partitions in batch order, and the columnstore naturally aligns. Since **SQL Server 2022 (16.x)** you can also state the intent directly with an ordered clustered columnstore index — `CREATE CLUSTERED COLUMNSTORE INDEX cci ON dbo.fact_sales ORDER (order_date)` — which sorts during the build so row-group min/max ranges are tight and overlap less. Note the option syntax: `MAXDOP` is an *index* option, so it goes in the `WITH` clause of `CREATE INDEX` (`WITH (MAXDOP = 1)`), not in a query `OPTION` clause. Use it, because "when `MAXDOP` is greater than 1, each thread... sorts it locally. There's no global sorting across data sorted by different threads" — parallel threads finish faster but leave more overlapping segments, which is the opposite of the point. A *fully* ordered index with no overlap needs either `WITH (ONLINE = ON, MAXDOP = 1)` (SQL Server 2025, which spills the sort to `tempdb`) or an offline build at `MAXDOP = 1` where the sort fits in workspace memory; everything else yields a partial order — which still eliminates segments, just less well. SQL Server 2022 also extended segment elimination to string, binary and GUID types (and `datetimeoffset` with scale greater than two), and added row-group elimination for prefix `LIKE` predicates such as `column LIKE 'string%'` — but not for `LIKE '%string'`. Existing indexes don't get the string min/max benefit until they're rebuilt. (Do **not** reach for `OPTIMIZE_FOR_SEQUENTIAL_KEY` here — that is an unrelated SQL Server 2019 index option for last-page insert contention on B-tree indexes, and it does nothing for columnstore ordering.)

### Drill 3 — In-memory OLTP (Hekaton)

> **Q**: What are memory-optimized tables and when do you use them?
>
> **A**: Tables stored entirely in memory with lock-free / latch-free access (uses optimistic multi-version concurrency control internally). Originally codenamed Hekaton. Designed for ultra-high-throughput OLTP scenarios — staging tables, session state, IoT ingestion buffers, hot caches. The reason it can be faster for write-heavy concurrent workloads is structural rather than a matter of degree: disk-based tables serialise concurrent writers on page latches, and memory-optimized tables have no pages and therefore no page latches. Don't quote a multiplier — the honest answer is "it removes a specific bottleneck", and the follow-up question is whether that bottleneck is the one you have.
>
> **Cross-Q**: If they're so fast, why isn't everything memory-optimized?
>
> **A**: Trade-offs. (1) **Memory constraint** — the table must fit in RAM (with overhead for the in-memory engine). 100GB tables don't fit on 32GB servers. (2) **Limited features** — no clustered indexes (only hash and range), no FILESTREAM, no FK to disk tables in some versions, some T-SQL constructs unsupported. (3) **Backup and restore are harder** — durability is via SCHEMA_AND_DATA or SCHEMA_ONLY; the latter loses data on restart (acceptable for cache scenarios). (4) **Operational complexity** — sizing memory, monitoring, knowing when a workload outgrows it. The sweet spot is narrow: hot write workloads on small tables.
>
> **Cross-Q²**: When would you choose memory-optimized over just adding more RAM and letting buffer pool cache the disk tables?
>
> **A**: When the bottleneck is **latching** (page latch contention), not IO. Adding RAM lets the buffer pool keep more pages cached, eliminating disk reads. But page latches (lightweight in-memory locks on each 8KB page) still serialize writers to the same page — a hot table with 1000 concurrent inserts gets latch waits even when fully cached. Memory-optimized tables use lock-free data structures — per the Hekaton SIGMOD paper, hash indexes are lock-free hash tables and range indexes are Bw-trees, a lock-free B-tree variant — so there is no page to latch. So: buffer pool fixes IO; memory-optimized fixes latch contention. Profile `sys.dm_os_wait_stats` — if you see PAGELATCH_EX as a top wait on a hot table, Hekaton is one answer; on a B-tree index with an ever-increasing key, the cheaper answer is often the SQL Server 2019 index option `OPTIMIZE_FOR_SEQUENTIAL_KEY = ON`, which throttles threads competing for the last page instead of re-architecting the table.

### Drill 4 — AlwaysOn AG vs Mirroring vs FCI

> **Q**: SQL Server has Failover Cluster Instances (FCI), Database Mirroring, and AlwaysOn Availability Groups. What's the difference and which do you use in 2026?
>
> **A**: **FCI** (Failover Cluster Instance) — Windows clustering at the instance level; shared storage; one active node at a time. Whole-instance failover. **Mirroring** — deprecated since SQL Server 2012 but still shipping (it is still listed in the SQL Server 2022 editions table, marked deprecated); database-level mirror with witness; superseded by AG. **AlwaysOn AG** — modern (SQL 2012+); database group with up to 8 secondary replicas; readable secondaries; automatic failover within a group; no shared storage; **Enterprise edition** (Standard gets basic AGs: two replicas, one database, no readable secondary). In 2026, AG is the default for HA/DR; FCI for niche cases requiring shared-storage semantics (some legacy apps); Mirroring is deprecated and only seen in old systems, so plan migrations off it rather than building on it.
>
> **Cross-Q**: Synchronous vs asynchronous replicas in an AG — what's the trade-off?
>
> **A**: **Synchronous** — the primary waits for the secondary to harden the log before acknowledging the commit. Zero data loss on failover (RPO = 0) but commits are slow (network round-trip per transaction). Limited to ~5 synchronous replicas. **Asynchronous** — primary commits immediately; secondary catches up best-effort. Commits are fast but failover can lose seconds of transactions (RPO > 0). Practical pattern: one synchronous secondary in the same datacenter for zero-loss HA + one or more async secondaries in remote datacenters for DR.
>
> **Cross-Q²**: A readable secondary serves read queries — what's the gotcha?
>
> **A**: (1) **Latency** — async secondaries can be seconds or minutes behind; queries see stale data. Even synchronous secondaries have small delays after the log block hardens but before the redo thread applies it. (2) **Snapshot isolation forced on secondary** — readable secondaries automatically use snapshot, which means tempdb grows on the secondary (version store) — sizing must account for this. (3) **Auto-create statistics on secondaries** — happens on primary only and replicates; secondaries get the stats too but you can't `UPDATE STATISTICS` on a readable secondary. (4) **Connection routing** — apps need `ApplicationIntent=ReadOnly` in the connection string to route to the secondary; otherwise they hit the primary. Many bugs surface from forgetting this.

### Drill 5 — TempDB contention

> **Q**: What is PFS/GAM/SGAM contention in tempdb and why does it matter?
>
> **A**: TempDB uses three allocation bitmaps per data file: **PFS** (Page Free Space — one bit per page tracking free vs used), **GAM** (Global Allocation Map — tracks 64-page extents that are entirely free), **SGAM** (Shared GAM — tracks mixed-use extents with at least one free page). Every allocation/deallocation hits these pages. Under high concurrency (many transactions creating temp tables simultaneously), workers serialize on PFS/GAM/SGAM latches, showing up as `PAGELATCH_UP` waits on pages `2:1:1`, `2:1:2`, `2:1:3` etc. Manifests as overall slowness, not localized to a query.
>
> **Cross-Q**: How do you fix it?
>
> **A**: Three steps. (1) **Multiple tempdb data files** — historically 1 file per CPU core up to 8; modern guidance is "equal-sized files, 4-8 to start, increase if PFS waits persist." This spreads allocation across multiple bitmap pages. (2) **Trace flag 1118** (pre-SQL 2016) or **MIXED_PAGE_ALLOCATION OFF** (default in SQL 2016+) — disables mixed-extent allocation so SGAM contention disappears. (3) **Reduce temp table usage** — table variables in some cases, or restructure the query. SQL Server 2019+ has **memory-optimized tempdb metadata** which reduces metadata contention further.
>
> **Cross-Q²**: A query is slow and `sys.dm_exec_session_wait_stats` shows `PAGELATCH_SH` on `tempdb` — but it's not on the bitmap pages. What now?
>
> **A**: That's tempdb metadata contention — SQL Server tracks every temp object in `tempdb.sys.objects` (and friends). Workers creating/dropping temp tables fight over the metadata pages. Fix: enable **memory-optimized tempdb metadata** (SQL Server 2019+ Enterprise) — moves metadata to in-memory tables that have lock-free access. Without that feature, reduce temp object churn: prefer table variables for small results, reuse cached temp tables in stored procs (they're cached if eligible), avoid creating temp tables inside loops.

### Drill 6 — sp_who2 vs sp_whoisactive

> **Q**: When investigating blocking, why do most DBAs reach for `sp_whoisactive` instead of `sp_who2`?
>
> **A**: `sp_who2` is built-in but shows minimal info — session_id, login, host, command, status, blocked_by. You see *that* session 53 is blocked by 51, but not what either is doing. `sp_whoisactive` is a community tool by Adam Machanic (free, widely deployed) that shows the actual SQL text, query plan, wait stats, transaction state, tempdb usage, and blocking chains — all in one row per active session. It's the single most useful third-party tool in the SQL Server world.
>
> **Cross-Q**: How do you install and use it in production?
>
> **A**: Download the latest `sp_whoisactive.sql` from whoisactive.com, run it once in `master` (or a admin database) to install the procedure. Then `EXEC sp_whoisactive` shows current activity. Parameters: `@get_plans = 1` to include execution plans, `@get_locks = 1` for lock info, `@find_block_leaders = 1` to highlight the root blocker in a chain. Many shops have it pre-installed on every server and bind a keyboard shortcut in SSMS to it.
>
> **Cross-Q²**: A senior says "use Extended Events instead of sp_whoisactive for production monitoring." Why?
>
> **A**: `sp_whoisactive` is a *point-in-time* snapshot — you run it when something is happening. For continuous monitoring or post-mortem analysis ("why was the system slow last Tuesday at 3am?"), you need historical data. Extended Events (XE) is the modern lightweight tracing mechanism that can capture sessions, deadlocks, blocking, query stats over time. Configure XE to log to a file or ring buffer; query historical data later. `sp_whoisactive` for interactive investigation; XE for production observability. They complement each other.

### Drill 7 — Deadlock graph analysis

> **Q**: SQL Server tells you "transaction was deadlocked." How do you investigate?
>
> **A**: Enable deadlock capture via the **system_health** Extended Event session (on by default since SQL 2012). Query the XML deadlock report: `SELECT XEvent.query('.') FROM (SELECT CAST(target_data AS XML) AS x FROM sys.dm_xe_session_targets WHERE target_name = 'ring_buffer') t CROSS APPLY x.nodes('//event[@name="xml_deadlock_report"]') AS X(XEvent)`. Open the XML graphically in SSMS (right-click, "View Deadlock Graph") — shows the two processes, the resources they hold, the resources they want, and which one was killed (the victim).
>
> **Cross-Q**: The deadlock graph shows two UPDATEs on `orders` and `customers` deadlocking. What's the most common root cause?
>
> **A**: **Inconsistent lock order**. Transaction T1 updates customers then orders; T2 updates orders then customers. T1 holds customers' X lock and wants orders'; T2 holds orders' X lock and wants customers'. Classic deadly embrace. The fix: pick a canonical order (e.g., always lower-numbered table first, or always by table ID) and refactor all transactions to follow it. The other common cause is a long-running scanning transaction acquiring locks on many rows and short transactions blocking on those.
>
> **Cross-Q²**: Deadlock recovery makes T1 the victim. T1's user sees an error. How do you handle this in app code?
>
> **A**: Catch SqlException with `Number = 1205` (deadlock victim) and **retry the transaction** — deadlocks are transient. The retry must include the entire transaction (BEGIN ... COMMIT), not just the failed statement, because all of T1's prior work was rolled back. Use exponential backoff (50ms, 100ms, 200ms) to avoid retry storms when many sessions deadlock simultaneously. EF Core's `EnableRetryOnFailure` handles this. Don't retry beyond 3-5 attempts — at that point something deeper is wrong (lock-order bug, hot row).

### Drill 8 — SQL Server vs Azure SQL DB vs Managed Instance

> **Q**: A team is choosing between SQL Server on VM, Azure SQL DB, and Azure SQL Managed Instance. What are the trade-offs?
>
> **A**: **SQL Server on VM (IaaS)** — full control; you manage OS, patches, backups, HA. Most flexible, most operationally heavy. Choose for: legacy apps needing specific configs, compliance requiring full control, lift-and-shift with no changes. **Azure SQL Database (PaaS)** — Microsoft manages everything; you get a database endpoint. Single database or elastic pool. Limited surface — no cross-DB queries, no SQL Agent, no FILESTREAM. Best for new cloud-native apps. **Azure SQL Managed Instance (PaaS)** — closest to on-prem SQL Server; supports SQL Agent, cross-DB queries, CLR, Service Broker. Designed for lift-and-shift to PaaS without code changes.
>
> **Cross-Q**: What specifically doesn't work in Azure SQL DB that works in Managed Instance?
>
> **A**: (1) **SQL Agent jobs** — Azure SQL DB has Elastic Jobs (separate service); MI has built-in SQL Agent. (2) **Cross-database queries** — MI supports them; DB requires Elastic Queries or app-side joins. (3) **Server-level objects** — logins, server roles, linked servers — MI has them; DB has only database-level. (4) **CLR and Service Broker** — MI yes; DB no. (5) **Mail (sp_send_dbmail)** — MI yes; DB requires Azure Logic Apps. The rule: if your existing app uses these features, MI; if you're greenfield and don't, DB is simpler and cheaper.
>
> **Cross-Q²**: Cost models differ — explain DTU vs vCore.
>
> **A**: **DTU** (Database Throughput Unit) — bundled metric combining CPU, IO, memory into a single "tier" (Basic, Standard, Premium). Simpler pricing; you pick a tier. Hard to right-size because you can't independently scale CPU vs IO. **vCore** — explicit vCPU count, with separate storage and IO tier choices. Maps to physical resources, supports Azure Hybrid Benefit (bring your existing SQL Server licenses), allows up to 80 cores per database. Modern recommendation: vCore for production; DTU for small dev/test where simplicity wins. Most large customers are on vCore.

### Drill 9 — CDC vs Change Tracking

> **Q**: SQL Server has both Change Data Capture (CDC) and Change Tracking (CT). When do you use each?
>
> **A**: **Change Tracking (CT)** — lightweight; records *that* a row changed and which columns, with version numbers. Consumer queries current state. Used for sync scenarios: mobile apps pulling deltas since last sync token, cache invalidation, search index updates. **Change Data Capture (CDC)** — heavyweight; records the before-and-after values of every UPDATE plus INSERT/DELETE. Provides full change history. Used for: replication, audit, event sourcing, feeding Debezium/Kafka pipelines.
>
> **Cross-Q**: How do they differ in performance overhead?
>
> **A**: CT adds a few bytes per row change (version numbers in shadow tables). Negligible overhead. CDC reads the transaction log asynchronously and writes change rows to CDC tables — so the writing transaction isn't slowed, but the CDC capture process consumes CPU and storage. For high-throughput systems, CDC's storage grows fast and the capture job can lag. CT is the right default unless downstream consumers genuinely need the full change history.
>
> **Cross-Q²**: A team uses triggers on every table to audit changes. Why might you replace them with CDC?
>
> **A**: Triggers run **synchronously inside the writing transaction** — every UPDATE pays the trigger cost in commit latency, and the trigger's own locks are held until the writer commits, so trigger cost is also blocking cost. CDC reads asynchronously from the transaction log, so the writer's critical path is unaffected; the cost moves to a capture job that consumes CPU and storage and can fall behind. The other advantage: triggers can be silently bypassed (`DISABLE TRIGGER`, or `BULK INSERT` without `FIRE_TRIGGERS`, which does not fire them by default); the log records everything regardless. The trade-off: CDC is harder to configure, is Enterprise or Standard edition only, and is less selective than custom trigger logic — it captures the configured columns for every change, where a trigger can decide what is worth recording.

### Drill 10 — Partition switching

> **Q**: How does partition switching let you archive old data without a DELETE?
>
> **A**: A partitioned table can `SWITCH` an entire partition to another empty table — metadata operation, instant, no row-by-row IO. Workflow: (1) Create archive table with identical schema and matching partition function. (2) `ALTER TABLE orders SWITCH PARTITION 5 TO orders_archive PARTITION 5` — the partition's data is now "in" the archive table; the original partition is empty. (3) Backup or detach the archive table. (4) Drop the partition definition from the source if no longer needed. The data move is instantaneous because only metadata changes — the data pages stay where they are, just owned by a different table.
>
> **Cross-Q**: What are the requirements for partition switching to work?
>
> **A**: (1) Both tables must be on the same filegroup. (2) Schemas must match exactly — same columns, types, constraints, indexes (including index alignment with the partition). (3) Target partition must be empty. (4) CHECK constraints on the source must guarantee values fit the target partition's range. The "schemas must match" requirement is the most painful in practice — even a missed default on one column blocks the switch. Many teams have automation that builds the archive table from the source with `SELECT * INTO ... WHERE 1=0` plus index recreation.
>
> **Cross-Q²**: How does this compare to PostgreSQL's `DETACH PARTITION`?
>
> **A**: PostgreSQL 11+ has `ALTER TABLE ... DETACH PARTITION` which is conceptually similar — the partition becomes a standalone table. Modern Postgres (14+) supports `CONCURRENTLY` for non-blocking detach. SQL Server's SWITCH is older (2005+), more mature, and supports SWITCH IN (moving a standalone table into a partition slot) as well as SWITCH OUT. Both engines treat partition swap as a metadata operation; the operational pattern is the same: archive old data instantly without DELETE storms.

### Drill 11 — Filegroups and FILESTREAM

> **Q**: What are filegroups and when do you create multiple?
>
> **A**: A **filegroup** is a logical container for data files. By default a database has one filegroup (`PRIMARY`). Multiple filegroups let you (a) place tables/indexes on different physical storage (hot data on SSD, archive on spinning disk), (b) parallelize backup/restore (backup individual filegroups), (c) implement filegroup-level recovery (restore one filegroup independently). For large databases (>1TB), multiple filegroups are standard.
>
> **Cross-Q**: What's FILESTREAM and when do you use it?
>
> **A**: FILESTREAM stores BLOB data (PDFs, images, videos) on the NTFS filesystem while keeping it transactionally consistent with the database. You declare `varbinary(max) FILESTREAM` and SQL Server stores the data as a file in a designated FILESTREAM filegroup, with the file path managed internally. Benefits: BLOBs > 1MB don't bloat the data files; native Windows file APIs can read them (low latency). Trade-offs: complex backup, requires NTFS, not available in Azure SQL DB.
>
> **Cross-Q²**: For a modern app needing to store user-uploaded files, would you use FILESTREAM?
>
> **A**: Usually no. The 2026 default is **object storage** (Azure Blob Storage, S3) — store BLOBs there, store the blob URL/key in the DB. Benefits: cheaper storage, CDN integration, independent scaling, doesn't bloat backups, works with PaaS DBs (Azure SQL DB doesn't support FILESTREAM). FILESTREAM made sense in 2008-2015 when on-prem SQL Server was the default and BLOB storage was per-instance. Now object storage is universal. FILESTREAM is reserved for legacy systems, regulated environments where files must live in the transactional database, or specific compliance requirements.

### Drill 12 — Statistics auto-update threshold

> **Q**: When does SQL Server automatically update column statistics, and why does it sometimes update too late?
>
> **A**: The documented thresholds (Microsoft Learn, *Statistics*) are exact, so quote them exactly. Up to SQL Server 2014, or on compatibility level 120 and below, a permanent table with more than 500 rows recomputes at `500 + (0.20 * n)` modifications. For a 1M-row table that is 200,500 rows — easy to hit. For a 1B-row table it is 200 million, so the statistics can be wildly stale for the first 199 million changes. Starting with **SQL Server 2016 (13.x) at compatibility level 130**, the threshold becomes the *minimum* of the old value and a square-root term: `MIN( 500 + (0.20 * n), SQRT(1000 * n) )`. Learn's own worked example: at 2 million rows that is `MIN(400,500, 44,721) = 44,721` modifications, so large tables update roughly an order of magnitude more often. Where the dynamic threshold doesn't apply — SQL Server 2008 R2 through 2014, or 2016 and later running at compatibility level 120 or lower — **trace flag 2371** turns it on. Note the second half of that sentence: an instance on SQL Server 2022 left at compat 120 for an old application is still on the legacy threshold.
>
> **Cross-Q**: Auto-update fires synchronously by default. Why is that a problem?
>
> **A**: When the auto-update triggers, the query that requested the stat **waits** for the stat to refresh — which on a billion-row table can be seconds or minutes (full scan to compute the histogram). The user-facing query that happened to be the first to need the stat takes the latency hit. The fix: enable `AUTO_UPDATE_STATISTICS_ASYNC ON` so updates happen in the background; the triggering query uses the stale stat (mild plan suboptimality) but doesn't pay the update cost. Almost always the right choice for production.
>
> **Cross-Q²**: When do you manually update stats vs trust auto-update?
>
> **A**: Manual update via `UPDATE STATISTICS table_name WITH FULLSCAN` (or `WITH SAMPLE 50 PERCENT` for big tables) when: (1) Bulk loads — after inserting millions of rows that didn't trigger the threshold. (2) Deployment validation — after a release, refresh stats so the new query patterns get accurate cardinality. (3) Investigating regressions — if a plan went bad, refreshed stats might fix it. Auto-update is fine for steady-state OLTP; manual updates are for known-disruption events. Set up a weekly Ola Hallengren-style maintenance plan to refresh fragmented stats and indexes.

### Drill 13 — Resource Governor

> **Q**: What is Resource Governor and what does it solve?
>
> **A**: Resource Governor (Enterprise edition) lets you partition CPU, memory, and IO among workload groups within a single SQL Server instance. You define **resource pools** (e.g., "report users get max 30% CPU"), **workload groups** (e.g., "ETL jobs"), and a **classifier function** that assigns incoming sessions to groups based on login name, app name, etc. Solves the noisy-neighbor problem: a runaway report can't starve OLTP.
>
> **Cross-Q**: A consultant says "use it to throttle the reports team." What's the practical pattern?
>
> **A**: Create a resource pool `Reports` with `MAX_CPU_PERCENT = 30` and `MAX_MEMORY_PERCENT = 40`. Create a workload group `Reports_WG` in that pool. Write a classifier function that returns `Reports_WG` when `APP_NAME() = 'Tableau'` or `LOGIN_NAME() LIKE 'rpt%'`. Activate Resource Governor. Now Tableau queries can't consume more than 30% CPU regardless of how many run, and OLTP keeps the rest. The "MAX" is a **cap when others need it** — if OLTP is idle, Reports can use 100%. So it's a fairness mechanism, not a hard reservation.
>
> **Cross-Q²**: Why do most shops not use Resource Governor even though it's free with Enterprise?
>
> **A**: (1) **Operational complexity** — classifier functions, pools, groups; mis-configuration silently degrades performance. (2) **Modern alternative is separate instances or replicas** — readable secondary in an AG isolates reports from OLTP at the infrastructure level. (3) **Resource Governor doesn't isolate everything** — tempdb, transaction log, lock manager are shared across groups. So a runaway report can still pollute tempdb. (4) **Enterprise-only** — Standard edition customers can't use it. The modern answer is usually "separate workloads onto separate replicas/instances" rather than partitioning one instance.

### Drill 14 — Extended Events vs SQL Trace

> **Q**: SQL Trace and Profiler are deprecated. What replaces them and why?
>
> **A**: **Extended Events (XE)** introduced in SQL 2008 and the recommended tracing mechanism since 2012. SQL Trace and Profiler are deprecated (still functional but marked for removal). XE is lightweight (lower overhead per event), more granular (capture only what you need), and runs in-process with the engine — Profiler was a separate process consuming the trace stream over the network, which dropped events under load.
>
> **Cross-Q**: How do you set up a long-running XE session to capture deadlocks?
>
> **A**: Use SSMS: Object Explorer → Management → Extended Events → New Session. Pick the `xml_deadlock_report` event, add a file target writing to disk, start the session. Or T-SQL: `CREATE EVENT SESSION deadlocks ON SERVER ADD EVENT sqlserver.xml_deadlock_report ADD TARGET package0.event_file (SET filename = 'C:\xe\deadlocks.xel') WITH (STARTUP_STATE = ON); ALTER EVENT SESSION deadlocks ON SERVER STATE = START`. Note `system_health` session already captures deadlocks by default — most teams don't need a custom one for deadlocks specifically.
>
> **Cross-Q²**: A team wants to monitor every query exceeding 5 seconds with the full SQL text and plan. What XE session do you build?
>
> **A**: Event: `sqlserver.rpc_completed` and `sqlserver.sql_batch_completed` with a filter (`WHERE duration > 5000000` — XE durations are microseconds, so 5s = 5,000,000). Actions: `sql_text`, `client_app_name`, `query_plan_hash`, `database_name`. Target: ring_buffer or event_file. Be careful about overhead — capturing the full query plan on every long query has cost. Most production sessions log just the lightweight fields and let users join to Query Store for the plan. The combo "XE for events, Query Store for plans" covers most observability needs.

### Drill 15 — Accelerated Database Recovery (ADR)

> **Q**: What is Accelerated Database Recovery and what problem does it solve?
>
> **A**: SQL Server 2019+ feature that makes database recovery (after crash, restart, or failover) near-instant regardless of transaction log size. Traditionally, recovery has three phases: **analysis** (read log to find committed/uncommitted txns), **redo** (replay committed changes), **undo** (rollback uncommitted txns). The undo phase scales with the longest open transaction — a stuck transaction can take hours to roll back, delaying database availability after restart. ADR uses a persistent version store + logical revert to make undo instant.
>
> **Cross-Q**: How does ADR achieve instant undo?
>
> **A**: ADR stores **row versions** in a persistent version store (`sys.dm_tran_persistent_version_store`) for every modified row. Instead of rolling back by walking the transaction log backwards, ADR's "logical revert" looks up the prior version and stamps the row back to it — O(1) per modified row. The version store is persistent (survives restarts), so even after a crash, recovery can find the right versions. Transaction log can be truncated even with long open transactions because rollback no longer needs the log.
>
> **Cross-Q²**: ADR sounds free — what's the cost?
>
> **A**: (1) **Disk space** for the persistent version store — versioned rows are stored in the database, so a write-heavy workload trades log space and recovery time for data-file space. Size it from your own workload; published percentages vary too much to be worth memorising. (2) **Write overhead** — every update writes both the new row and a version, so there is a per-modification cost on the hot path. (3) **Long-running open transactions hold versions** — a transaction open for hours keeps the version store growing until it commits or rolls back, which is the same failure mode as RCSI's `tempdb` growth, just in a different place. Mitigation: hunt and kill long open transactions. ADR is on by default in Azure SQL Database and Managed Instance; opt-in on the boxed product (`ALTER DATABASE ... SET ACCELERATED_DATABASE_RECOVERY = ON`), and available on Enterprise, Standard and Web editions.

### Drill 16 — Encrypting sensitive columns

> **Q**: The compliance team says "encrypt the customer PII". Walk me through the options in SQL Server and what each one actually protects against.
>
> **A**: Four features that are routinely confused because they all say "protect data", and they defend against different attackers. **TDE (Transparent Data Encryption)** encrypts the data files, log files and backups at rest. It defends against someone walking off with a `.bak` or a detached `.mdf`. It does nothing against anyone who can connect and run `SELECT` — including the DBA — because decryption happens in the engine, below the query. **Always Encrypted** encrypts values in the *client driver*; per Microsoft Learn, it ensures "encryption keys are never exposed to the Database Engine", separating "those who own the data and can view it, and those who manage the data but should have no access: on-premises database administrators, cloud database operators". That is the only one of the four that defends against a privileged insider on the server. **Row-Level Security** is an access-control predicate, not encryption — it filters which rows a principal sees. **Dynamic Data Masking** obfuscates values in query results for users without the `UNMASK` permission; the data on disk is unchanged.
>
> **Cross-Q**: A colleague proposes Dynamic Data Masking to hide salaries from the support team. Is that sufficient?
>
> **A**: No, and Microsoft Learn says so directly: DDM "shouldn't be used alone to fully secure sensitive data from users running ad hoc queries". Its own documented example is a user with `SELECT` but not `UNMASK` running `SELECT ID, Name, Salary FROM Employees WHERE Salary > 99999 AND Salary < 100001` — the `Salary` column comes back masked as `0`, but the `WHERE` clause is evaluated against the real value, so the rows that come back tell you the salary anyway. Binary-search that predicate and you have the exact figure in a handful of queries. DDM is appropriate for preventing *accidental* exposure in an application that issues known queries; it is not a boundary against anyone who can write their own SQL. Also note that admins with `CONTROL SERVER` or database-level `CONTROL` (sysadmin, db_owner) see unmasked data by design. SQL Server 2022 added granular `UNMASK` grants at database, schema, table and column scope, which makes the permission model usable, but doesn't change the inference weakness.
>
> **Cross-Q²**: What breaks in the application when you turn on Always Encrypted?
>
> **A**: More than teams expect, and the restrictions are the reason it is often rejected. Encryption type decides everything: **deterministic** encryption produces the same ciphertext for the same plaintext, so it supports equality point lookups, `IN`, `GROUP BY`, `DISTINCT`, and indexing — and nothing else, at the cost of leaking equality patterns (a Yes/No column encrypted deterministically has two distinct ciphertexts). **Randomized** encryption leaks nothing and supports no operations at all — no searching, sorting, joining, or indexing. Beyond that: you can't compare an encrypted column to a literal or to a plaintext column (you get "Operand type clash"), so every value must arrive as a `SqlParameter`; string columns must use a `_BIN2` collation; `IDENTITY`, computed columns, and check constraints on encrypted columns are out; table-valued parameters targeting encrypted columns aren't supported; and initial encryption moves all the data out of the database and back, which for a large table is an outage-shaped operation. On the .NET side it is one keyword — `Column Encryption Setting=enabled` in the connection string (or `SqlConnectionStringBuilder.ColumnEncryptionSetting`) — and the driver then calls `sys.sp_describe_parameter_encryption` per query shape and caches the result. **Always Encrypted with secure enclaves** (SQL Server 2019+ and Azure SQL Database) relaxes the big restrictions: pattern matching, comparison operators and in-place encryption become possible because the engine can process the values inside a protected memory region.

### Drill 17 — Parallelism: MAXDOP and cost threshold

> **Q**: An instance shows `CXPACKET` as its top wait. Is that a problem, and what do you change?
>
> **A**: On its own, no — `CXPACKET` means parallel plans are running, which is what parallelism looks like. Microsoft Learn's description is "waiting to synchronize the Query Processor Exchange Iterator... and when producing and consuming rows", and since SQL Server 2016 SP2 / 2017 CU3 the *consumer* side is tracked separately as `CXCONSUMER`, which is explicitly "a normal part of parallel query execution". The signal to act on is `CXPACKET` dominating **alongside** evidence that trivial queries are going parallel. Two knobs: **cost threshold for parallelism** decides *whether* a query goes parallel (the optimizer only considers parallel plans when the best serial plan's estimated cost exceeds it), and **MAXDOP** decides *how wide* it goes when it does.
>
> **Cross-Q**: What are the defaults, and are they right?
>
> **A**: `cost threshold for parallelism` defaults to **5**, and the documentation is unusually blunt about it: "The default value of `5` is a starting point, not a recommendation. On modern SQL Server systems, raising it can help to keep smaller OLTP queries executing with serial plans." Note what the number is: Learn defines cost as "the sum of *estimated* operator costs in a query plan" and "a relative measure used only for plan selection; it doesn't measure actual runtime" — so `5` is not five seconds, and the default has not moved in decades of hardware improvement, which is why so many OLTP instances parallelise queries that would finish serially in milliseconds and pay thread-coordination cost for nothing. MAXDOP defaults to 0 (all processors up to 64), which the docs also call out as "not the recommended value for most cases"; SQL Server 2019 setup began recommending a value based on detected cores. Learn's guidance table: single NUMA node with ≤ 8 logical processors, MAXDOP at or under that count; single node with more, keep it at 8; multiple NUMA nodes with ≤ 16 logical processors per node, at or under the per-node count; more than 16 per node, half the per-node count with a maximum of 16. Azure SQL Database and Managed Instance default MAXDOP to 8 for new databases, and Azure SQL Database doesn't expose cost threshold at all.
>
> **Cross-Q²**: How do you tell whether you set them too high?
>
> **A**: Learn gives the symptom pairs. Cost threshold **too low**: many Query Store plans with `is_parallel_plan = 1`, `CXPACKET`/`CXCONSUMER` dominating, possibly `THREADPOOL` and `SOS_SCHEDULER_YIELD`. Cost threshold **too high**: CPU-heavy queries stuck serial, CPU utilisation higher than it should be, `SOS_SCHEDULER_YIELD` dominating. Change in small increments and watch a full business cycle — a Tuesday afternoon proves nothing about a month-end close. Also know the newer options before you reach for the server-wide knobs: MAXDOP can be set per database (scoped configuration), per query (`OPTION (MAXDOP n)`), per Query Store hint, and per Resource Governor workload group, and SQL Server 2022 added **DOP feedback**, which lowers the degree of parallelism for repeating queries that demonstrably don't benefit from it — Enterprise edition, Query Store required.

### Drill 18 — Index fragmentation and the maintenance ritual

> **Q**: Your predecessor left a nightly job that rebuilds every index with fragmentation above 5%. Keep it?
>
> **A**: Almost certainly not as written. Two distinct things get conflated under "fragmentation". **Logical fragmentation** — leaf pages out of physical order — mattered enormously when read-ahead on spinning disks depended on sequential IO. On SSDs and on SANs that virtualise the layout anyway, it matters much less, and the job is paying real cost for it: a rebuild is a full write of the index, which means transaction log, which means log backups, which on an availability group means replicating all of it to every secondary. **Low page density** (rows per page) is the part that still matters on any storage, because a half-empty index costs you buffer pool: the same rows occupy twice the memory. `sys.dm_db_index_physical_stats` reports both — `avg_fragmentation_in_percent` and `avg_page_space_used_in_percent` — and a 5% threshold on the first one rebuilds essentially everything, every night, for nothing.
>
> **Cross-Q**: What replaces it?
>
> **A**: A tiered policy on real numbers, which is what the widely-used Ola Hallengren maintenance scripts implement: leave indexes below a low fragmentation threshold alone, `REORGANIZE` in the middle band, `REBUILD` only at the top, and only above a minimum page count (fragmentation percentages on an index of eight pages are noise). Reorganize is online, incremental and interruptible; rebuild is a single operation that is only online on Enterprise edition (`WITH (ONLINE = ON)`), and Enterprise also offers `RESUMABLE = ON` so a rebuild interrupted by the end of a maintenance window can continue rather than roll back. Critically, keep the statistics update — the *reason* the nightly rebuild often appears to help is that a rebuild updates that index's statistics with a full scan as a side effect, so teams who delete the job without adding an explicit statistics job see regressions and conclude fragmentation mattered after all.
>
> **Cross-Q²**: How does `FILLFACTOR` relate to this?
>
> **A**: Fill factor is the deliberate creation of free space in the leaf pages at build time, so that later inserts and row-widening updates have somewhere to go without splitting a page. The default is 0, which means 100% — pack the pages full. That is right for an index on an ever-increasing key, where new rows go on the end and interior pages never split; it is wrong for an index on something like `customer_id` or a GUID, where inserts land in the middle. Lowering fill factor there trades memory and IO (every page is partly empty, always, including in the buffer pool) for fewer page splits. It is a per-index decision driven by the insert pattern, and setting it globally to a folk value like 80 is how instances end up using 20% more memory than they need for indexes that never split. Note the interaction with the earlier RCSI point: enabling row versioning adds 14 bytes per modified row, which can start causing splits in indexes built at 100% fill factor that were previously stable.

</details>

## Cheat Sheet

- **Clustered index**: one per table; leaf level *is* the rows; choose narrow, monotonic, stable keys.
- **Non-clustered**: separate B-tree; leaf stores clustered key as pointer; lookups become Key Lookups without `INCLUDE`.
- **RCSI**: `READ_COMMITTED_SNAPSHOT ON` makes readers use row versions; eliminates blocking on SELECT.
- **Filtered index**: `WHERE` clause on the index; small, focused, ideal for "active" rows in a sea of soft-deleted ones.
- **Implicit conversion**: type mismatch in WHERE forces table scan; check `WarningType="ConvertIssue"` in the plan.
- **Statistics**: optimizer uses these; stale stats cause cardinality misestimates; `UPDATE STATISTICS WITH FULLSCAN` for big tables.
- **NOLOCK**: read uncommitted; allows dirty reads, missed rows, double-counted rows during scans.
- **Query Store**: built-in plan history; `sys.query_store_*` DMVs to find regressed plans after upgrades.
- **TVPs**: pass a table to a stored proc with one round trip; far faster than 1000 individual `INSERT`s.
- **DBCC CHECKDB**: detects on-disk corruption; schedule weekly; run on a restored backup to avoid IO hit on prod.
- **Index key order**: equality predicates first, then the single range predicate, then `INCLUDE`. `(status, created_at)` seeks for `status = @s AND created_at >= @d`; `(created_at, status)` does not.
- **Lock escalation**: 5,000 locks in one statement on one table → table lock; retried every 1,250 further locks. Batch big DML.
- **Isolation defaults**: SQL Server `READ COMMITTED` + locking; Azure SQL Database `READ COMMITTED` + RCSI; PostgreSQL `READ COMMITTED` + MVCC; MySQL/InnoDB `REPEATABLE READ`.
- **SNAPSHOT conflict**: error 3960, "Snapshot isolation transaction aborted due to update conflict" — retryable, like 1205.
- **Parameter sniffing**: compare `ParameterCompiledValue` and `ParameterRuntimeValue` in the plan XML. `OPTIMIZE FOR UNKNOWN` = estimate from the density vector.
- **Statistics thresholds**: `500 + 0.20n` legacy; `MIN(500 + 0.20n, SQRT(1000n))` from SQL Server 2016 at compat 130.
- **`log_reuse_wait_desc`**: the one column that tells you why the transaction log won't truncate. Read it before shrinking anything.
- **`ASYNC_NETWORK_IO`**: the server is waiting for your application to consume rows. Not a database problem.
- **Version gates worth quoting**: scalar UDF inlining 2019/compat 150; interleaved execution for MSTVFs 2017/compat 140; table variable deferred compilation 2019/compat 150; PSP optimization 2022/compat 160; ordered clustered columnstore 2022.

## Walkthrough — Key Lookups tanking the orders search

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A customer-facing search "orders by customer email last 30 days" used to take 200ms; today it takes 11s. No code or schema change since last week.

**Diagnosis**: The senior pulls the actual plan in SSMS (Ctrl+M, then run). The plan shows a non-clustered Index Seek on `IX_Orders_CustomerEmail` followed by a Key Lookup that consumes 92% of the cost. Estimated rows: 50; Actual rows: 180,000. Stale stats. `sys.dm_db_index_usage_stats` confirms the index is heavily used; `sys.dm_db_missing_index_details` suggests an INCLUDE list. The statistics age comes from `sys.dm_db_stats_properties`, not from `sys.stats` (which has no date column):

```sql
SELECT s.name, sp.last_updated, sp.rows, sp.rows_sampled,
       sp.steps, sp.modification_counter
FROM   sys.stats s
CROSS APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) sp
WHERE  s.object_id = OBJECT_ID('dbo.Orders');
-- STATS_DATE(object_id, stats_id) gives just the date if that's all you need.
```

`last_updated` is three weeks old and `modification_counter` is large but under the threshold — on a table this size, `MIN(500 + 0.20n, SQRT(1000n))` still needs tens of thousands of modifications, and the churn is concentrated in new rows rather than spread across the table.

**Fix**: Two changes. First refresh stats, then add a covering index:

```sql
UPDATE STATISTICS dbo.Orders WITH FULLSCAN;

CREATE NONCLUSTERED INDEX IX_Orders_Email_CreatedAt
    ON dbo.Orders(CustomerEmail, CreatedAt DESC)
    INCLUDE (Status, Total, ShippingCity)
    WITH (ONLINE = ON);   -- Enterprise / Azure SQL only. On Standard this statement
                          -- fails outright; drop the option and the build instead
                          -- holds a lock that blocks writes for its duration.
```

Latency drops to 80ms. The plan now shows pure Index Seek, no Key Lookup, no Sort.

**Why it works**: A covering index satisfies the query entirely from the non-clustered B-tree leaves, skipping the Key Lookup back to the clustered index. `CustomerEmail` is the equality predicate so it leads the key; `CreatedAt DESC` is the range predicate *and* the sort order, so it follows and removes the Sort. Refreshed stats let the optimizer pick the right access path in the first place.

</details>

## Self-test

<details><summary>1. You enable RCSI and now <code>tempdb</code> growth alerts fire daily. Why?</summary>

RCSI stores row versions in `tempdb` for the duration of any reading transaction. Long-running readers force version chains to grow. Look for sessions with `transaction_begin_time` minutes old via `sys.dm_tran_active_snapshot_database_transactions`; usually it's a forgotten `BEGIN TRAN` or a reporting query that should have used a read replica.
</details>

<details><summary>2. Trade-off: clustered key on identity INT vs natural key (e.g., OrderNumber).</summary>

Identity INT is narrow, monotonic, and stable -> ideal for clustering and minimal page splits. Natural keys are searchable directly but often wider and may change. Modern preference: identity for the clustered key, unique non-clustered index on the natural key. The natural key still gets fast lookups; the clustered tree stays compact.
</details>

<details><summary>3. <code>MERGE</code> sometimes produces duplicate rows under concurrency. Why and what's the fix?</summary>

Without `HOLDLOCK` or `SERIALIZABLE`, two sessions can both pass the "WHEN NOT MATCHED" check before either insert commits. Add `MERGE INTO target WITH (HOLDLOCK)` or use `INSERT ... WHERE NOT EXISTS` inside `SERIALIZABLE`. Many seniors avoid `MERGE` entirely for upserts because of these footguns.
</details>

<details><summary>4. How would you investigate a sudden CPU spike to 95% on a SQL Server VM with no schema change?</summary>

Pull `sys.dm_exec_query_stats` ordered by `total_worker_time` to find top CPU consumers. Cross-reference with Query Store regressions (`sys.query_store_runtime_stats`). Common culprits: a parameter-sniffed plan compiled for a rare value, a deployment that increased call rate, or stats refresh that flipped a join order.
</details>

<details><summary>5. When would you choose Always On AG over Azure SQL geo-replication?</summary>

Always On AG when you need cross-AZ HA on self-managed SQL Server (Linux/Windows VMs, on-prem, or specific compliance demands) — and note it is an Enterprise edition feature; Standard only offers basic availability groups (two replicas, one database, no readable secondary). Azure SQL geo-replication when you're already on PaaS and want managed failover with a built-in DNS endpoint. The decision is mostly ops-model rather than capability.
</details>

<details><summary>6. A query filters <code>WHERE Email = @email</code> on an indexed <code>varchar</code> column and the plan shows an Index Scan with <code>CONVERT_IMPLICIT</code>. What happened, and where do you fix it?</summary>

ADO.NET sent the .NET `string` as `nvarchar`. SQL Server's data type precedence ranks `nvarchar` above `varchar`, and the lower-precedence side is converted — which is the *column*, on every row, so the predicate stops being SARGable. Fix it on the client: `SqlDbType.VarChar` on the parameter, Dapper's `DbString { IsAnsi = true }`, or EF Core's `IsUnicode(false)` on the property. The reverse direction (a `varchar` parameter against an `nvarchar` column) is harmless — there the parameter is converted, not the column. There's also a collation nuance: with a Windows collation on the column the optimizer can often still seek; with a SQL collation it scans, which is why the same code performs differently on different servers.
</details>

<details><summary>7. Your <code>DELETE</code> archival job blocked the whole application. Explain the mechanism, and what changes.</summary>

Lock escalation. A single statement acquiring at least 5,000 locks on one table escalates them to a table lock (retried every 1,250 further locks if escalation is initially blocked), so an exclusive table lock replaces thousands of row locks and every other session on the table stops. It also ran as one transaction, so the log couldn't truncate until it finished. The change is a batch loop — `DELETE TOP (n)` per transaction, each below the threshold, with a short delay between batches — not a hint and not an isolation-level change. RCSI does not help here: it removes shared locks from *readers*, and this is a writer.
</details>

<details><summary>8. Someone proposes Dynamic Data Masking so the support team can't see salaries. What's your objection?</summary>

DDM masks the value in the result set, but predicates are evaluated against the real value, so anyone who can write ad hoc SQL can infer it: `WHERE Salary BETWEEN 99999 AND 100001` returns the row with a masked `0` in the column and tells you the salary anyway. Microsoft Learn documents exactly this and states DDM "shouldn't be used alone to fully secure sensitive data from users running ad hoc queries." It's a defence against accidental exposure in an application with known queries, not a security boundary. Also, `sysadmin`, `db_owner`, and anyone with `CONTROL` see unmasked data by design. If the requirement is that privileged operators genuinely cannot see the values, that's Always Encrypted — with the application changes it implies.
</details>

<details><summary>9. Why is <code>sp_executesql</code> preferred over <code>EXEC('...' + @value)</code> for dynamic SQL — give two reasons, not one.</summary>

Injection is the first and obvious one: concatenation makes the value part of the statement text. The second is the plan cache. Every distinct concatenated string is a distinct batch, so each gets its own cached plan; a high-cardinality parameter produces thousands of single-use plans that evict the plans other workloads depend on. You find it with `sys.dm_exec_cached_plans WHERE usecounts = 1`, and the symptom is that *unrelated* queries get slower. `optimize for ad hoc workloads` at the server level caches a stub instead of a full plan on first execution, which limits the memory damage without fixing the cause.
</details>

<details><summary>10. Trade-off: you can enable RCSI tonight with one statement. What do you tell the change board?</summary>

Benefit: readers stop taking shared locks and stop blocking writers, which removes a whole class of blocking without touching application code. Costs and risks, in order: (1) version chains live in `tempdb`, so `tempdb` sizing and monitoring become load-bearing, and a long-running reader pins versions for its whole duration; (2) 14 bytes of versioning overhead per modified row can cause page splits in indexes built at 100% fill factor, so expect a one-off fragmentation event; (3) read semantics change — code that relied on readers *queueing* behind a writer, such as a poll-and-claim queue table, may now hand the same row to two workers, and needs explicit `UPDLOCK, READPAST`; (4) the `ALTER DATABASE` statement itself requires exclusive database access, so it needs `WITH ROLLBACK IMMEDIATE` and a real maintenance window. Also worth stating: if this is Azure SQL Database, RCSI is already on by default and there is nothing to change.
</details>

## Cross-references

- [SQL](./03-sql/README.md) — standard SQL fundamentals (this file is the dialect-specific layer).
- [EF Core](./01-ef-core.md) — runs against SQL Server in most .NET shops.
- [LINQ](./02-linq.md) — generates the T-SQL.
- [Configuration Deep Dive](../01-foundations/01-net-core-deep-dive/15-configuration.md) — connection strings, secrets.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- Microsoft Learn — [SQL Server documentation](https://learn.microsoft.com/en-us/sql/sql-server/).
- Microsoft Learn — [Azure SQL documentation](https://learn.microsoft.com/en-us/azure/azure-sql/).
- Microsoft Learn — [Transaction locking and row versioning guide](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-transaction-locking-and-row-versioning-guide) — source for the isolation-level table, the 5,000-lock escalation threshold, and the RCSI/SNAPSHOT distinction.
- Microsoft Learn — [Index architecture and design guide](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-index-design-guide) — clustered-key properties, row locator composition, key column ordering.
- Microsoft Learn — [Statistics](https://learn.microsoft.com/en-us/sql/relational-databases/statistics/statistics) — 200-step histogram, density vector, auto-update thresholds.
- Microsoft Learn — [Query processing architecture guide](https://learn.microsoft.com/en-us/sql/relational-databases/query-processing-architecture-guide) — parameter sensitivity, plan reuse, local-variable estimation.
- Microsoft Learn — [Parameter Sensitive Plan optimization](https://learn.microsoft.com/en-us/sql/relational-databases/performance/parameter-sensitive-plan-optimization) and [Intelligent query processing details](https://learn.microsoft.com/en-us/sql/relational-databases/performance/intelligent-query-processing-details) — version and compatibility-level gates.
- Microsoft Learn — [Scalar UDF inlining](https://learn.microsoft.com/en-us/sql/relational-databases/user-defined-functions/scalar-udf-inlining) — why scalar UDFs were slow, and what SQL Server 2019 changed.
- Microsoft Learn — [Editions and supported features of SQL Server 2022](https://learn.microsoft.com/en-us/sql/sql-server/editions-and-components-of-sql-server-2022) — the scale-limit and feature-gate tables.
- Microsoft Learn — [Data type precedence](https://learn.microsoft.com/en-us/sql/t-sql/data-types/data-type-precedence-transact-sql) — why an `nvarchar` parameter converts a `varchar` column.
- Microsoft Learn — [Dynamic data masking](https://learn.microsoft.com/en-us/sql/relational-databases/security/dynamic-data-masking) and [Always Encrypted](https://learn.microsoft.com/en-us/sql/relational-databases/security/encryption/always-encrypted-database-engine).
- Microsoft Learn — [Automatic, geo-redundant backups (Azure SQL Database)](https://learn.microsoft.com/en-us/azure/azure-sql/database/automated-backups-overview) — PITR retention defaults and range.
- Microsoft Learn — [What is an Always On availability group?](https://learn.microsoft.com/en-us/sql/database-engine/availability-groups/windows/overview-of-always-on-availability-groups-sql-server) — replica counts, the five-synchronous-replicas-including-primary limit, and the automatic-failover conditions.
- Microsoft Learn — [Memory grant feedback](https://learn.microsoft.com/en-us/sql/relational-databases/performance/intelligent-query-processing-memory-grant-feedback) — cached-plan feedback in 2017/2019 versus Query Store persistence and percentile mode in 2022.
- Microsoft Learn — [max degree of parallelism](https://learn.microsoft.com/en-us/sql/database-engine/configure-windows/configure-the-max-degree-of-parallelism-server-configuration-option) and [cost threshold for parallelism](https://learn.microsoft.com/en-us/sql/database-engine/configure-windows/configure-the-cost-threshold-for-parallelism-server-configuration-option) — defaults, the NUMA guidance table, and the too-low/too-high symptom lists.
- Microsoft Learn — [Performance tuning with ordered columnstore indexes](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/ordered-columnstore-indexes) and [What's new in columnstore indexes](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/columnstore-indexes-what-s-new) — `ORDER`, the `MAXDOP` build option, and 2022 segment-elimination changes.
- Microsoft Learn (archived engine blog) — [Overhead of row versioning](https://learn.microsoft.com/en-us/archive/blogs/sqlserverstorageengine/overhead-of-row-versioning) — the 14-byte per-row cost of enabling RCSI or SNAPSHOT.
- Microsoft Learn — [`sys.dm_os_wait_stats`](https://learn.microsoft.com/en-us/sql/relational-databases/system-dynamic-management-views/sys-dm-os-wait-stats-transact-sql) — the wait-type descriptions quoted above, including `ASYNC_NETWORK_IO`.
- PostgreSQL documentation — [Transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html) — for the engine-difference claims about MVCC, Read Uncommitted, and Repeatable Read.
- Jonathan Kehayias (SQLskills) — [Implicit conversions that cause index scans](https://www.sqlskills.com/blogs/jonathan/implicit-conversions-that-cause-index-scans/) — the Windows vs SQL collation nuance.
- Diaconu et al., [*Hekaton: SQL Server's Memory-Optimized OLTP Engine*](https://www.microsoft.com/en-us/research/wp-content/uploads/2013/06/Hekaton-Sigmod2013-final.pdf) (SIGMOD 2013) — lock-free hash tables and Bw-trees.
- *SQL Server 2022 Query Performance Tuning* by Grant Fritchey (Apress) — definitive query-tuning book.
- *Pro SQL Server Internals* by Dmitri Korotkevitch (Apress) — deep architectural reference.
- Brent Ozar's blog ([brentozar.com](https://www.brentozar.com/)) — practical real-world SQL Server advice.
- Ola Hallengren's [SQL Server Maintenance Solution](https://ola.hallengren.com/) — the de facto standard index and statistics maintenance scripts.

<!-- nav-footer-start -->

---

[← Previous: Advanced Patterns & Interview Problems](03-sql/09-advanced-patterns-and-interview-problems.md) · [↑ Back to top](#ms-sql-server) · [Next: Redis →](05-redis.md)

<!-- nav-footer-end -->

</details>
