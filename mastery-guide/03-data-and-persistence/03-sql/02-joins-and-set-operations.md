# Joins & Set Operations

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › [SQL Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-08 |

> 📖 **Deep dive available**: For every join type with worked sample tables, internal join algorithms, execution plans, anti-patterns and best practices — see **[Joins Deep Dive](./02-joins-deep-dive.md)**.

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [INNER JOIN](#inner-join)
  - [LEFT JOIN (and RIGHT JOIN)](#left-join-and-right-join)
  - [FULL OUTER JOIN](#full-outer-join)
  - [CROSS JOIN (Cartesian product)](#cross-join-cartesian-product)
  - [SELF JOIN](#self-join)
  - [Anti-join and semi-join](#anti-join-and-semi-join)
  - [Multi-table joins](#multi-table-joins)
  - [Join elimination — the join the optimizer deletes](#join-elimination--the-join-the-optimizer-deletes)
  - [NULL-safe joins on nullable keys](#null-safe-joins-on-nullable-keys)
  - [Set operations: UNION, INTERSECT, EXCEPT](#set-operations-union-intersect-except)
  - [Joins under concurrency](#joins-under-concurrency)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--left-join-silently-becoming-inner-join)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Joins are SQL's defining superpower. Relational databases store data **normalized** — split across tables to eliminate redundancy — and joins recombine it for queries. Knowing the five join types and when each applies separates engineers who write working SQL from those who write *correct* SQL.

Joins are also the most-asked SQL interview topic. "Find customers who haven't placed any orders" → LEFT JOIN with NULL filter (anti-join). "Find pairs of employees with the same manager" → SELF JOIN. "Combine results of two queries" → UNION. The vocabulary is small but the patterns appear everywhere.

When NOT to JOIN: heavy-aggregation queries with single-table sources (no JOIN needed). Document/key-value stores by design (Mongo, Cosmos) — different model. Cross-database queries (use replication or app-level joins).

## Core concepts

### INNER JOIN

Returns only rows that have a match in **both** tables. The default and most common join.

```sql
-- Schema:
-- customers (id, name)
-- orders    (id, customer_id, total)

SELECT c.name, o.id AS order_id, o.total
FROM customers c
INNER JOIN orders o ON c.id = o.customer_id;
```

If a customer has no orders, they're excluded. If an order's customer_id doesn't match any customer (orphan; should be prevented by FK), it's excluded.

`INNER` is optional in most dialects — `JOIN` alone means inner join. But spell it out for clarity.

```sql
-- Same query, less explicit
SELECT c.name, o.id, o.total
FROM customers c
JOIN orders o ON c.id = o.customer_id;
```

**Multiple match conditions** in `ON`:
```sql
JOIN orders o ON c.id = o.customer_id AND o.status = 'Active'
```

An inner join is a **filter as much as it is a combination**. Every unmatched row disappears without a warning, an error, or a row in a log. That is fine when a foreign key guarantees the match and dangerous when nothing does — a reporting warehouse loaded by ETL usually has no FKs at all.

> 🌍 **In the real world**: a monthly revenue report inner-joins `orders` to `customers` in a warehouse that was loaded by nightly ETL with no foreign keys. Orders imported from a channel that was decommissioned carry a `customer_id` that the customer extract no longer contains, so those rows vanish from the join and the report quietly under-states revenue. Nobody spots it, because a revenue figure that is slightly too low still looks like a revenue figure — there is no error, no empty result, nothing to notice. The fix was two lines: a `LEFT JOIN` plus a nightly orphan check (`SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.id = o.customer_id)`) that alerts when it is non-zero. The join type stayed the same in the report; what changed is that the dropped rows now have somewhere to be seen.

### LEFT JOIN (and RIGHT JOIN)

`LEFT JOIN` returns **all rows from the left table**, plus matching rows from the right (or NULL if no match).

```sql
SELECT c.name, o.id AS order_id, o.total
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id;
-- Result includes EVERY customer, even those with no orders.
-- For customers without orders, o.id and o.total are NULL.
```

This is how you preserve "all left rows" while incorporating optional right data. Use cases:
- "All customers, with their orders if any."
- "All employees, with their performance reviews if reviewed."
- "All products, with their sales (zero if none)."

`RIGHT JOIN` is the mirror — all right-table rows kept, left-table NULL if no match. **Avoid `RIGHT JOIN` in practice**; reorder the tables and use `LEFT JOIN` for readability.

```sql
-- These are equivalent
SELECT * FROM A LEFT JOIN B ON ...
SELECT * FROM B RIGHT JOIN A ON ...

-- The first form is clearer.
```

**LEFT JOIN does not mean "at most one row".** It means "at least the left rows". If the right table has two matches, the left row appears twice. Whenever you write `LEFT JOIN` and reason about the result as if it were optional-single-valued, you are relying on a uniqueness guarantee that must exist somewhere — a unique index or a primary key on the join column of the right table. If it exists, say so in the schema; if it does not, your query is one bad row away from a wrong answer.

> 🌍 **In the real world**: an invoicing service joins `invoices` to `customer_addresses` with a LEFT JOIN because the address is "optional". It was also unique, until a release added address history and stopped deleting the old row. From that deploy on, every customer who had ever moved produced two invoice lines, and the batch's control total doubled for exactly those customers — an error too small to look like a crash and too large to survive an audit. The join was never wrong; the assumption underneath it was. The durable fix made the database enforce what the query already believed: a unique index over current rows only (`... WHERE is_current = 1` — a filtered index in SQL Server, a partial index in PostgreSQL; MySQL has neither, so uniqueness there needs a generated column or application enforcement), plus `AND a.is_current = 1` in the `ON` clause.

### FULL OUTER JOIN

Returns rows from **both** tables; matched rows combined, unmatched rows NULL on the missing side.

```sql
SELECT c.name, o.id AS order_id
FROM customers c
FULL OUTER JOIN orders o ON c.id = o.customer_id;
-- Includes:
--   - Customers with orders (matched)
--   - Customers without orders (right side NULL)
--   - Orphan orders (left side NULL — shouldn't exist with FK)
```

Rare in practice. Used for:
- Auditing referential integrity ("which orders have no customer?").
- Set comparison reports.
- Reconciliation between two snapshots.

Many systems don't have a real FULL OUTER need — most "missing on either side" questions are actually one-sided (LEFT JOIN or anti-join).

**Engine note**: SQL Server and PostgreSQL both implement `FULL [OUTER] JOIN`. **MySQL does not have it at all** — the feature request (MySQL worklog WL#1604, "Support FULL [OUTER] JOIN by rewriting with UNION") is still open, so on MySQL you write it yourself:

```sql
-- MySQL: emulate FULL OUTER JOIN
SELECT c.name, o.id FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
UNION ALL
SELECT c.name, o.id FROM customers c RIGHT JOIN orders o ON o.customer_id = c.id
WHERE c.id IS NULL;          -- ← only the right-only rows; UNION ALL then needs no dedup
```

Using plain `UNION` of the LEFT and RIGHT halves produces the right *set*, but its dedup pass removes genuine duplicate rows in your data along with the matched rows both halves produced — so it is only correct when duplicates are impossible or unwanted. The anti-join filter on the second branch removes only the duplicated matches, by construction.

> 🌍 **In the real world**: during a strangler-fig migration, orders were being written by both the legacy monolith and the new .NET service for a two-week dual-run. A nightly `FULL OUTER JOIN` between the legacy extract and the new service's table on `(order_reference)` was the only check that ran: rows with a NULL right side meant the new service had missed an event; rows with a NULL left side meant it had invented one. It caught a mapping bug where cancelled orders were being replayed as new — visible only on the "left NULL" side, which a LEFT JOIN from the legacy table would never have shown. Cutover happened on schedule because the reconciliation was two-sided from day one.

### CROSS JOIN (Cartesian product)

Pairs every row in left with every row in right. No `ON` clause.

```sql
SELECT c.name, p.name AS product
FROM customers c
CROSS JOIN products p;
-- If 1,000 customers and 100 products → 100,000 rows.
```

Intentional uses:
- Generate combinations (every customer × every product, for "did each buy each?").
- Calendar tables: `CROSS JOIN` a date series with categories.
- Producing test data.

**Accidental CROSS JOIN is a disaster.** A query missing the `ON` clause silently becomes a Cartesian product:

```sql
-- ❌ MISSING ON CLAUSE — runs as CROSS JOIN!
SELECT *
FROM customers c, orders o
WHERE c.country = 'PK';
-- Returns customers × orders cross product, then filters.
```

Older dialects allow comma-separated tables (implicit CROSS JOIN); modern style uses explicit `JOIN ... ON ...` to make this impossible.

The most valuable intentional use is **densifying a sparse result**: a report that must show every day (or every status, or every region) including the ones with no data. Aggregating the fact table alone can only produce rows that exist; cross-joining a calendar to the dimension gives you the full grid, and a LEFT JOIN back to the facts fills it in.

```sql
-- PostgreSQL. Every day × every status, zero-filled — no gaps for the client to patch
SELECT d.day, s.status, COUNT(o.id) AS orders   -- COUNT(col) ignores NULLs → 0 for empty days
FROM calendar d
CROSS JOIN (VALUES ('Pending'), ('Paid'), ('Cancelled')) AS s(status)
LEFT JOIN orders o
       ON o.created_at >= d.day
      AND o.created_at <  d.day + INTERVAL '1 day'
      AND o.status = s.status
WHERE d.day >= DATE '2026-01-01'
GROUP BY d.day, s.status;
```

`COUNT(o.id)` rather than `COUNT(*)` is the whole trick on the aggregate side: `COUNT(*)` counts the NULL-padded outer row and reports 1 for a day with nothing in it. On SQL Server the same query needs `DATEADD(day, 1, d.day)` in place of the interval arithmetic, and a plain `'2026-01-01'` (or `CAST(... AS date)`) in place of the `DATE '...'` typed literal, which T-SQL doesn't have; the `VALUES` constructor and `CROSS JOIN` are identical.

> 🌍 **In the real world**: a dashboard's daily-orders chart showed a straight line between two points whenever a quiet day produced no rows, because the front-end plotted whatever the API returned. Three separate fixes had been attempted in TypeScript — filling gaps client-side, then in the API's mapper, then in a caching layer — and each one broke on time zones. Replacing the `GROUP BY date` query with a calendar `CROSS JOIN` and a LEFT JOIN back to orders deleted all three: the query returns a row per day whether or not anything happened, and the zero comes from the aggregate itself rather than from date arithmetic in C#.

### SELF JOIN

Joining a table to itself — useful when rows are related by foreign key to other rows in the same table.

```sql
-- Schema:
-- employees (id, name, manager_id) — manager_id references another employee

-- Find employee + manager
SELECT
    e.id AS employee_id, e.name AS employee_name,
    m.id AS manager_id,  m.name AS manager_name
FROM employees e
LEFT JOIN employees m ON e.manager_id = m.id;
-- LEFT JOIN so top-level employees (no manager) still appear.

-- Find pairs of employees who share a manager
SELECT a.name, b.name
FROM employees a
JOIN employees b ON a.manager_id = b.manager_id AND a.id < b.id;
-- a.id < b.id avoids duplicate pairs and self-pairing.
```

The pattern: alias the table twice (`employees a`, `employees b`), join with the relevant condition. Common in:
- Org charts (employee/manager).
- Hierarchies (category/parent_category).
- Adjacency-list graphs.

For deep hierarchies (more than ~3 levels), use **recursive CTEs** ([Subqueries & CTEs](./04-subqueries-and-ctes.md)) instead of repeated self-joins.

The failure mode of a fixed-depth self-join chain is that it does not fail. Ask for three levels of a five-level tree and you get three levels, with NULLs where the query ran out of joins — a shape indistinguishable from "this person has no manager".

> 🌍 **In the real world**: an approvals service resolved an approver by chaining two self-joins on `employees.manager_id`, because the company was two levels deep when it was written. A reorganisation inserted team leads and regional directors, and the chain now ran out before reaching anyone with signing authority. The query returned NULL, the C# code treated NULL as "no approver required", and expense claims auto-approved for three weeks. The rewrite was a recursive CTE that walks until it finds a role with the authority flag, plus the rule that made the incident impossible to repeat: NULL from the approver lookup throws instead of falling through.

### Anti-join and semi-join

Two patterns built on joins, named for the relational-algebra concept.

**Anti-join** — find rows in A that have NO match in B.

```sql
-- Customers with no orders
SELECT c.id, c.name
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.id IS NULL;
-- The trick: LEFT JOIN keeps all customers; WHERE o.id IS NULL filters to those without a match.

-- Equivalent with NOT EXISTS (recommended — same anti-join plan)
SELECT c.id, c.name
FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id);

-- Equivalent with NOT IN (slower; beware NULL semantics)
SELECT c.id, c.name
FROM customers c
WHERE c.id NOT IN (SELECT customer_id FROM orders WHERE customer_id IS NOT NULL);
```

`NOT EXISTS` is usually the optimizer's friend and handles NULLs cleanly. `NOT IN` can return zero rows if the subquery produces any NULL — a notorious gotcha.

Anti-join and semi-join are **named operations in the plan**, not just a way of writing SQL, and recognising their names is how you confirm the optimizer understood you. (On SQL Server they are *logical* operations carried by a physical operator — see the note under the worked plan below; in PostgreSQL and MySQL the name is baked into the plan node itself.)

| Engine | Anti-join operator in the plan | Semi-join operator |
|---|---|---|
| SQL Server | `Left Anti Semi Join` (on Hash Match / Merge Join / Nested Loops) | `Left Semi Join` |
| PostgreSQL | `Hash Anti Join` / `Nested Loop Anti Join` | `Hash Semi Join` / `Nested Loop Semi Join` |
| MySQL 8.0.20+ | `Hash antijoin` in `EXPLAIN FORMAT=TREE` | `Hash semijoin` |

If you wrote `NOT EXISTS` and the plan shows an anti-join, the engine is doing one pass and stopping at the first match per outer row. If it instead shows a filter over a materialised subquery result, it is not — which is the usual signature of the `NOT IN` form on a nullable column, where the engine has to preserve three-valued semantics and cannot use the anti-join shape.

> 🌍 **In the real world**: a re-engagement email job ran `WHERE customer_id NOT IN (SELECT customer_id FROM orders WHERE created_at > @cutoff)` and sent nothing for eleven days. The cause was one import batch that had written orders with a NULL `customer_id` for guest checkouts; from the first such row onward, `NOT IN` evaluated to UNKNOWN for every candidate and the job's "0 recipients" looked exactly like "nobody qualifies". Nothing errored, no alert fired, and marketing found it. Two changes shipped: `NOT EXISTS` in the query, and a `NOT NULL` constraint on the column that should never have allowed it.

**Semi-join** — find rows in A that have AT LEAST ONE match in B (without duplicating A).

```sql
-- Customers who placed at least one order
SELECT c.id, c.name
FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id);

-- Equivalent with INNER JOIN + DISTINCT (works but inefficient on large data)
SELECT DISTINCT c.id, c.name
FROM customers c
INNER JOIN orders o ON o.customer_id = c.id;
```

`EXISTS` short-circuits — the semi-join stops scanning a customer's orders at the first qualifying row. Inner join + DISTINCT produces every matching pair first, then sorts or hashes them all away. The gap between the two is proportional to the average number of matches per left row: with one order per customer they are nearly identical, and with a customer who has tens of thousands of orders the DISTINCT form does tens of thousands of rows of work to emit one. That ratio, not a fixed multiplier, is the number to quote in an interview.

> 🌍 **In the real world**: an "active customers" tile on an admin dashboard used `SELECT DISTINCT c.id, c.name FROM customers c JOIN orders o ON o.customer_id = c.id` and was fine for two years. Then the platform onboarded a wholesale account that placed orders through an API integration, and that single customer's row count dwarfed the rest of the table; the tile started timing out while every other query on the page stayed fast. Rewriting it as `WHERE EXISTS (...)` fixed it because the semi-join stops at that customer's first order instead of materialising all of them to throw away.

### Multi-table joins

Real queries join 3, 5, 10 tables. Chain `JOIN` clauses; each join builds on the previous result.

```sql
SELECT
    c.name AS customer,
    o.id AS order_id,
    p.name AS product,
    oi.quantity,
    oi.price
FROM customers c
JOIN orders o      ON o.customer_id = c.id
JOIN order_items oi ON oi.order_id = o.id
JOIN products p     ON p.id = oi.product_id
WHERE c.country = 'PK'
  AND o.created_at >= '2025-01-01';
```

Style:
- Indent and align `ON` clauses for readability.
- Filter early — predicates in `WHERE` (or in `ON` for outer joins) reduce intermediate row counts.
- Order joins from "smallest filter result" to "largest" so the optimizer has a hint (most modern optimizers reorder anyway).

**The written order stops being cosmetic once the table count gets high.** Join reordering is a search problem whose space grows factorially, so every optimizer caps it. PostgreSQL makes its caps configurable and documents the defaults: `join_collapse_limit` (default 8) is the point past which the planner stops flattening explicit `JOIN` syntax into a reorderable `FROM` list, `from_collapse_limit` (default 8) does the same for merged subqueries, and `geqo_threshold` (default 12) is the number of `FROM` items at which planning switches to the genetic algorithm — a heuristic search that does not guarantee the best plan. Setting `join_collapse_limit = 1` means "join them exactly as I wrote them". SQL Server does not expose the equivalent knobs, but the same principle holds: it has a compilation time budget and will return the best plan found so far. So for a 3-table query, write it for humans; for a 15-table query, the order you write is one of the inputs to the plan you get.

**Watch out for "multiplying" rows.** If a customer has 5 orders and each order has 4 items, joining all three returns 20 rows per customer. Aggregations need careful HAVING / DISTINCT to avoid double-counting. The rule to internalise: joining a 1:N relationship changes the **grain** of the row set. After `orders JOIN order_items`, one row no longer means one order, so any aggregate over an order-level column (`o.shipping_fee`, `o.total`) is now summing it once per item. `SELECT DISTINCT` does not repair this — it removes duplicate rows, and the duplicated *values* are attached to rows that differ in the item columns. The fix is to aggregate each 1:N branch to the grain you want *before* joining (worked example in [Code & diagrams](#code--diagrams)).

> 🌍 **In the real world**: a finance export joined `orders` to `order_items` and to `payments`, summing `o.total` and `oi.quantity` in the same query. It was correct for a year, because payments were one row per order. Then instalment payments shipped, orders with three instalments produced three copies of every item row, and the export's revenue total climbed above what the payment provider had settled. The reconciliation team found it, not monitoring. The fix was to pre-aggregate payments and items in separate CTEs — each reduced to one row per order — before joining them to `orders`, so the grain of the final result is one row per order by construction rather than by luck.

**On SQL Server, a join hint is also a join-order hint.** This is the trap that catches people who reach for `INNER HASH JOIN` to fix one bad operator. Microsoft's join-hints reference states it in the Remarks: "If a join hint is specified for any two tables, the query optimizer automatically enforces the join order for all joined tables in the query, based on the position of the `ON` keywords." One hint on one pair of tables freezes the entire `FROM` clause — you get an `OPTION (FORCE ORDER)` you never typed. The hints themselves are `LOOP`, `HASH`, `MERGE` and `REMOTE` (the data-movement hints `REDUCE`, `REPLICATE` and `REDISTRIBUTE` are documented for Azure Synapse Analytics and Analytics Platform System, with `REPLICATE` and `REDISTRIBUTE` also listed for Fabric Warehouse), and the docs state `LOOP` "can't be specified together with `RIGHT` or `FULL` as a join type".

The three engines draw the line in different places, which is worth having straight before an interviewer asks how you'd force a plan:

| Engine | Per-query join control |
|---|---|
| SQL Server | `LOOP` / `HASH` / `MERGE` / `REMOTE` join hints — **each one also fixes join order** — and `OPTION (FORCE ORDER)` |
| MySQL | `JOIN_FIXED_ORDER`, `JOIN_ORDER`, `JOIN_PREFIX`, `JOIN_SUFFIX` optimizer hints; the manual describes `JOIN_FIXED_ORDER` as "the same as specifying `SELECT STRAIGHT_JOIN`". `HASH_JOIN`/`NO_HASH_JOIN` worked in 8.0.18 only — from 8.0.19 the manual says use `BNL`/`NO_BNL`, which now enable and disable hash joins |
| PostgreSQL | No per-query join hints in core. Session-level `enable_hashjoin` / `enable_mergejoin` / `enable_nestloop`, or `SET join_collapse_limit = 1` to execute the order you wrote |

> 🌍 **In the real world**: a seven-table month-end report had one hash join spilling, so an `INNER HASH JOIN` hint went in on that pair and the report got faster the same afternoon. Six weeks later a new, highly selective filter was added to a different table in the same query and the report fell off a cliff. The hint had pinned the join order for all seven tables, so the optimizer was no longer allowed to drive from the newly selective table — it had to keep the order the author had typed six weeks earlier. Nobody connected the two changes, because the hint was three words inside a `FROM` clause and the new filter was in the `WHERE`. The fix was to delete the hint and repair the cardinality estimate that had caused the spill in the first place; where a plan genuinely has to be pinned, Query Store plan forcing pins it visibly instead of a hint quietly changing two things at once.

### Join elimination — the join the optimizer deletes

A join that cannot change the result is a join the optimizer is allowed to remove entirely. Two conditions have to hold: **nothing from the joined table is referenced** anywhere in the query (not in the select list, not in a predicate, not in an `ORDER BY`), and the engine can **prove the join changes no row counts** — it cannot duplicate rows (the join column on the other side is unique) and, for an inner join, it cannot remove rows either (something guarantees the match exists).

This is not a micro-optimization. It is why a view that joins twelve lookup tables can be cheap when you select three columns from it, and it is why the same view collapses to twelve real joins the moment someone writes `SELECT *`.

**SQL Server** proves "the match exists" from a **trusted** foreign key. A foreign key is trusted only if the engine has verified every existing row; a constraint created `WITH NOCHECK`, or disabled for a bulk load and re-enabled without revalidation, is *untrusted*, and an untrusted constraint proves nothing:

```sql
-- Find constraints the optimizer will not believe
SELECT OBJECT_NAME(parent_object_id) AS table_name, name
FROM sys.foreign_keys
WHERE is_not_trusted = 1;

-- Re-enabling like this leaves it UNTRUSTED (no revalidation):
ALTER TABLE dbo.orders CHECK CONSTRAINT FK_orders_customers;

-- This revalidates and restores trust — note the doubled CHECK:
ALTER TABLE dbo.orders WITH CHECK CHECK CONSTRAINT FK_orders_customers;
```

Bert Wagner's *Join Elimination: When SQL Server Removes Unnecessary Tables* (SQLPerformance.com, June 2018) walks the cases the optimizer can and cannot handle.

**PostgreSQL** takes a different route: it removes **LEFT JOINs** when the inner side is provably unique on the join columns (a unique index) and none of its columns are used elsewhere — the optimization Robert Haas described in *Why Join Removal Is Cool* when it landed in PostgreSQL 9.0. It does not have SQL Server's foreign-key-driven inner-join elimination, so do not port the assumption across engines; run `EXPLAIN` on the engine you actually ship on.

Three practical consequences for a .NET codebase:

- **Project columns, don't `SELECT *`.** A projection of three columns lets the engine drop joins; `SELECT *` references every column and forbids it. This is a plan-shape argument, not a bandwidth argument.
- **EF Core generates the joins you never wrote** — `Include`, owned types, table-per-type inheritance. When the query only reads scalar properties of the root entity, join elimination is what keeps those generated joins free; a view or a projection that touches one column of each joined table is what makes them expensive.
- **Keep constraints trusted.** Untrusted FKs cost nothing until the day the optimizer needs one.

> 🌍 **In the real world**: a data migration weekend followed the usual runbook — disable constraints, bulk-load, re-enable — and the script re-enabled them with `CHECK CONSTRAINT` rather than `WITH CHECK CHECK CONSTRAINT`. Every foreign key in the database came back untrusted. Nothing failed; queries returned identical results. But a family of reports built on a wide view got slower over the following week as plans recompiled, because the joins that had previously been eliminated were now really executed. The diagnosis took a day and the fix was one query against `sys.foreign_keys WHERE is_not_trusted = 1` plus a loop that revalidated each one. The runbook now ends with that check as a gate.

### NULL-safe joins on nullable keys

`ON a.x = b.x` is not "match when both are the same". It is "match when the comparison is TRUE", and a comparison involving NULL is UNKNOWN. So a NULL never joins — not to a value, not even to another NULL. Rows disappear, and because an outer join is often already in the query, they disappear as NULL-padded rows rather than as an error.

This bites hardest on **composite joins**, where one nullable component is enough to lose the row:

```sql
-- If oi.warehouse_id is NULL for pre-fulfilment rows, those rows never match — 
-- even when o.warehouse_id is also NULL.
JOIN order_items oi
  ON oi.order_id = o.id
 AND oi.warehouse_id = o.warehouse_id
```

Each engine spells the NULL-safe comparison differently, and SQL Server only gained one recently:

| Engine | NULL-safe equality |
|---|---|
| PostgreSQL | `a.x IS NOT DISTINCT FROM b.x` |
| MySQL | `a.x <=> b.x` (NULL-safe equal operator) |
| SQL Server | `a.x IS NOT DISTINCT FROM b.x` — SQL Server 2022 (16.x) and later, and Azure SQL Database (Microsoft Learn, *IS [NOT] DISTINCT FROM (Transact-SQL)*) |

On older SQL Server, the portable idiom exploits the fact that **set operators treat two NULLs as equal** (see the next section) — an `INTERSECT` of two single-row selects is a NULL-safe multi-column comparison:

```sql
-- NULL-safe "these two column lists are the same", any T-SQL version
JOIN order_items oi
  ON oi.order_id = o.id
 AND EXISTS (SELECT oi.warehouse_id INTERSECT SELECT o.warehouse_id);
```

The trade-off is real: none of these are plain equality, so the optimizer may not be able to use them as a hash or merge join key or to seek an index on the column, and you can end up with a nested loop scanning the inner side. Check the plan before shipping one on a large table. Which is the argument for the design fix rather than the query fix — **a join key should be `NOT NULL`**. Where the column genuinely means "not applicable", a sentinel row in the parent table (a `warehouse_id = 0` "unassigned" row) keeps the key non-nullable, keeps equality joins seekable, and makes the semantics explicit.

> 🌍 **In the real world**: an order-fulfilment report joined `orders` to `order_items` on `(order_id, warehouse_id)` because items could be split across warehouses. Items not yet allocated carried a NULL `warehouse_id`, and so did their parent order — so the two NULLs did not match, and unallocated items were missing from the report. Operations had been reconciling the gap by hand for months, assuming the warehouse team was slow to enter data. The fix was an "unallocated" warehouse row with a real id and a `NOT NULL` column, chosen over `IS NOT DISTINCT FROM` specifically because the equality join could still seek the composite index.

### Set operations: UNION, INTERSECT, EXCEPT

Combine the result rows of two SELECTs (which must have compatible column shapes).

```sql
-- UNION: rows from A or B (deduplicated)
SELECT name FROM active_customers
UNION
SELECT name FROM archived_customers;

-- UNION ALL: rows from A or B (preserves duplicates; faster — no dedup)
SELECT name FROM active_customers
UNION ALL
SELECT name FROM archived_customers;

-- INTERSECT: rows in BOTH A and B
SELECT email FROM customers_us
INTERSECT
SELECT email FROM customers_eu;
-- Customers represented in both regions.

-- EXCEPT (or MINUS in Oracle): rows in A but not in B
SELECT email FROM all_customers
EXCEPT
SELECT email FROM email_unsubscribed;
```

**Rules:**
- Same number of columns in both queries.
- Columns must be **type-compatible** position-by-position (column names from the first SELECT win).
- Operators apply set semantics — every one of them deduplicates unless you add `ALL`.

`UNION ALL` avoids the dedup work entirely; `UNION` must sort or hash the combined rowset first. If you know there can't be duplicates, always use `ALL`.

**Where the `ALL` variants exist** — this is the portability trap, because the same query is legal in one engine and a syntax error in the next:

| | SQL Server | PostgreSQL | MySQL |
|---|---|---|---|
| `UNION` / `UNION ALL` | yes | yes | yes |
| `INTERSECT` / `EXCEPT` | yes | yes | 8.0.31+ |
| `INTERSECT ALL` / `EXCEPT ALL` | **no** — the T-SQL grammar has no `ALL` form of either | yes | 8.0.31+ |

(Oracle spells `EXCEPT` as `MINUS`, which is why you see `MINUS` in older material.)

**Two NULLs count as equal here — unlike in a join.** Microsoft's `EXCEPT`/`INTERSECT` reference states it directly: "When comparing column values for determining DISTINCT rows, two NULL values are considered equal." PostgreSQL removes duplicates "in the same way as `DISTINCT`", which has the same NULL-are-equal behaviour. So `SELECT NULL INTERSECT SELECT NULL` returns a row, while `ON a.x = b.x` with two NULLs returns nothing. That asymmetry is what makes the `EXISTS (SELECT … INTERSECT SELECT …)` idiom in the previous section work, and it is a favourite interview question because most people have never had to think about it.

**Precedence is not left-to-right.** All three engines document the same rule — PostgreSQL: "Without parentheses, `UNION` and `EXCEPT` associate left-to-right, but `INTERSECT` binds more tightly than those two operators." SQL Server's reference gives the same order: parentheses, then `INTERSECT`, then `EXCEPT` and `UNION` left to right. MySQL's 8.0.31 notes say the same of its new operators. So:

```sql
-- Reads like "(A UNION B) INTERSECT C". It is not.
SELECT email FROM leads
UNION
SELECT email FROM customers
INTERSECT
SELECT email FROM opted_in;          -- ← binds first: customers ∩ opted_in

-- What you almost certainly meant:
(SELECT email FROM leads UNION SELECT email FROM customers)
INTERSECT
SELECT email FROM opted_in;
```

**`ORDER BY` belongs to the whole expression, not the last branch.** One `ORDER BY` is allowed, at the end, and it can only name output columns (or ordinals) of the *first* query — Microsoft's reference: "Column names or aliases in ORDER BY clauses must reference column names returned by the left-side query." PostgreSQL adds that `ORDER BY` and `LIMIT` attach to a branch only if that branch is parenthesised; without parentheses they apply to the result of the set operation. So a `LIMIT 10` you thought was capping the second half is capping the total.

**In a SQL Server plan, `EXCEPT` shows up as a left anti semi join and `INTERSECT` as a left semi join** — the same operators the `NOT EXISTS` and `EXISTS` forms produce. Which is the honest answer to "EXCEPT or NOT EXISTS?": below the syntax they are frequently the same physical operation, and you choose on semantics (whole-row comparison versus correlated predicate), not on a performance folk theorem.

> 🌍 **In the real world**: a mailing list was built as "all active customers, minus the unsubscribed, minus the hard-bounced" and written as `active EXCEPT unsubscribed UNION bounced`. Left-to-right associativity makes that `(active EXCEPT unsubscribed) UNION bounced` — so the bounced addresses were not removed, they were **added back in**, including addresses that had also unsubscribed. The send went out and the complaint came from the ESP's abuse desk, not from monitoring. What the author meant was `active EXCEPT (unsubscribed UNION bounced)`. Parenthesising every multi-operator set expression became a review rule the same week, and the regression test is one seeded address that appears in both suppression lists and must never appear in the output.

**A set operator is also a plan-shape tool, not only a way to stack results.** A disjunction over columns that live in *different* indexes — `WHERE email = @e OR phone = @p` — cannot be answered by one index seek, because a seek needs a bounded range on the index's leading column and `OR` hands it two unrelated ones. Splitting the predicate into branches gives each branch something seekable:

```sql
-- One statement; neither index can serve both sides of the OR.
SELECT id, name FROM customers WHERE email = @e OR phone = @p;

-- Two seekable branches. UNION, not UNION ALL, because one customer
-- could match on both columns and would otherwise come back twice.
SELECT id, name FROM customers WHERE email = @e
UNION
SELECT id, name FROM customers WHERE phone = @p;
```

Two conditions before reaching for it. Each branch needs an index that actually turns it into a seek — otherwise you have written two scans where there was one. And you have to decide honestly whether a row can satisfy both branches: `UNION ALL` returns it twice, `UNION` removes it and charges you a dedup for the privilege. Optimizers can find this rewrite unaided — SQL Server can produce an "index union" plan with a `Concatenation` operator over two seeks, and PostgreSQL builds a `BitmapOr` over two bitmap index scans — so read the plan first. If the engine already did it, the rewrite buys nothing and costs readability.

`UNION`'s dedup is not one fixed algorithm either. SQL Server exposes the choice as query hints — `{ MERGE | HASH | CONCAT } UNION`, documented as running "all `UNION` operations ... by merging, hashing, or concatenating `UNION` sets", with merge suiting already-sorted inputs, hash suiting large unsorted ones, and concatenation suiting small or already-distinct ones. Two further consequences of the whole set expression being *one* statement: those hints go in a single trailing `OPTION` clause, and Microsoft's query-hints reference is explicit that "if `UNION` is involved in the main query, only the last query involving a `UNION` operation can have the `OPTION` clause" — the same rule you already met with `ORDER BY`.

> 🌍 **In the real world**: a customer-lookup endpoint let support staff search by email *or* phone in one query, and the plan was a clustered index scan of the whole customer table even though both columns were indexed. The first attempted fix was a composite index on `(email, phone)`, which did nothing for the query as a whole — a composite index seeks on a bound for its *leading* column, so it can serve the `email` side but has nothing to offer the `phone` side, and one unseekable branch of an `OR` still forces a scan. Rewriting the query as a `UNION` of two single-column lookups produced two seeks. The lasting lesson for the team was the diagnostic order: the plan said "scan", and the reason was in the shape of the predicate, not in the list of indexes.

### Joins under concurrency

Every join is also a **schedule of reads**, and on a lock-based engine the plan decides what your report holds and for how long. This is the part of joins that only shows up in production, and it is where "SQL is my weak area" gets exposed fastest — because the query is correct, and the incident is still yours.

**SQL Server, on-premises defaults.** The Database Engine's default isolation level is `READ COMMITTED`, and with `READ_COMMITTED_SNAPSHOT` **OFF** — which Microsoft documents as the default in SQL Server and Azure SQL Managed Instance — that level takes **shared locks** as the scan proceeds. Be precise about how long: Microsoft documents that under `READ COMMITTED` "the row or page locks are released after the row is read", so a writer normally blocks only behind the scan's *current* position, not behind the whole report. The failure mode is what happens when those fine-grained locks accumulate faster than they drain. Lock escalation is documented to trigger when "a single Transact-SQL statement acquires at least 5,000 locks on a single nonpartitioned table or index" (and to retry every 1,250 new locks if the first attempt is blocked). Cross that line and your row locks become one table lock — escalation goes **straight to a table lock, never to a page lock** ("Lock escalation always escalates to a table lock, and never to a page lock", Microsoft Learn, KB 323630). Be precise about its lifetime too, because this is where the folklore overshoots: at read committed the escalated lock is still a shared lock, and Microsoft documents that "shared (`S`) locks on a resource are released as soon as the read operation completes, unless the transaction isolation level is set to `REPEATABLE READ` or higher, or a locking hint is used". So the table lock is held for the rest of the *statement*, not to the end of the transaction — which for a single long report is the whole report, and every write to that table queues behind it. It only survives to commit if the read runs at `REPEATABLE READ`/`SERIALIZABLE`, under `HOLDLOCK`, or if the escalated lock is an exclusive one taken by a write.

**Azure SQL Database is not the same engine configuration.** Microsoft documents `READ_COMMITTED_SNAPSHOT` as **ON** by default there, so `READ COMMITTED` uses row versioning and readers do not block writers. A report that behaved perfectly in Azure can block checkout on an on-prem instance restored from the same backup. Know which one you are describing in an interview.

**PostgreSQL and MySQL/InnoDB do not have this failure mode.** Both are MVCC: a plain `SELECT` in PostgreSQL reads a snapshot and takes no row locks, and InnoDB's default `REPEATABLE READ` serves plain `SELECT`s as consistent non-locking reads from a snapshot. The cost moves somewhere else rather than disappearing — a long-running report holds an old snapshot, which keeps PostgreSQL's autovacuum from reclaiming dead tuples and keeps InnoDB's undo history long. Your reporting query does not block writes; it makes the storage engine carry more versions.

**`WITH (NOLOCK)` is not the fix**, and knowing exactly why is a senior differentiator. Microsoft's locking guide is explicit that `READ UNCOMMITTED` risks "missing an updated row or seeing an updated row multiple times": if another transaction changes an index key while your scan is in progress, the row can appear twice (moved ahead of your scan position) or not at all (moved behind it), and with allocation-order scans "you might miss rows if another transaction is causing a page split". Those are wrong *committed* rows, not just uncommitted ones — a financial total that is silently wrong is worse than a report that waits.

What actually works, in the order you should reach for it:

1. **Make the query smaller.** Fewer joined tables, projected columns only, predicates that seek instead of scan. Locks are proportional to rows touched.
2. **Turn on row versioning** — `ALTER DATABASE … SET READ_COMMITTED_SNAPSHOT ON` (SQL Server), which shifts the cost to version storage in `tempdb` rather than to blocking.
3. **Move the read off the write path** — a readable secondary, a replica, or a pre-aggregated reporting table refreshed on a schedule.
4. **Bound it**: `SET LOCK_TIMEOUT` or a query timeout so a runaway report gives up instead of holding a queue behind it.

> 🌍 **In the real world**: a "quick" month-end reconciliation joined orders, order items, payments and refunds with no date filter, on an on-prem SQL Server instance where nobody had enabled RCSI. It ran during business hours, escalated to table locks on `orders`, and checkout requests began timing out — the incident was reported as "the website is down", and the offending session was found holding S locks in `sys.dm_tran_locks`. The first attempted fix, sprinkling `WITH (NOLOCK)`, made the same report produce a different total on two consecutive runs, which is how the team learned what allocation-order scans do during page splits. The real fix was three changes: a date-range predicate that turned the scans into seeks, RCSI enabled after testing `tempdb` headroom, and the report moved to a readable secondary.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Visual: the five JOIN types

```
Tables:
  customers (c)        orders (o)
  +---+-------+        +---+-------------+-------+
  | id| name  |        | id| customer_id | total |
  +---+-------+        +---+-------------+-------+
  | 1 | Ahmed |        | 1 |     1       |  100  |
  | 2 | Sara  |        | 2 |     1       |   50  |
  | 3 | Bob   |        | 3 |     5       |   75  |  ← orphan
  +---+-------+        +---+-------------+-------+


INNER JOIN:                         (only matches)
+----+-------+----+--------+
| id | name  | id | total  |
+----+-------+----+--------+
| 1  | Ahmed | 1  | 100    |
| 1  | Ahmed | 2  | 50     |
+----+-------+----+--------+


LEFT JOIN (customers ←):            (all customers; orders if any)
+----+-------+------+--------+
| id | name  | id   | total  |
+----+-------+------+--------+
| 1  | Ahmed | 1    | 100    |
| 1  | Ahmed | 2    | 50     |
| 2  | Sara  | NULL | NULL   |
| 3  | Bob   | NULL | NULL   |
+----+-------+------+--------+


FULL OUTER JOIN:                    (everything from both)
+------+-------+------+--------+
| id   | name  | id   | total  |
+------+-------+------+--------+
| 1    | Ahmed | 1    | 100    |
| 1    | Ahmed | 2    | 50     |
| 2    | Sara  | NULL | NULL   |
| 3    | Bob   | NULL | NULL   |
| NULL | NULL  | 3    | 75     |  ← orphan order
+------+-------+------+--------+


CROSS JOIN:                         (every pair)
+----+-------+----+--------+
| id | name  | id | total  |
+----+-------+----+--------+
| 1  | Ahmed | 1  | 100    |
| 1  | Ahmed | 2  | 50     |
| 1  | Ahmed | 3  | 75     |
| 2  | Sara  | 1  | 100    |
| 2  | Sara  | 2  | 50     |
| 2  | Sara  | 3  | 75     |
| 3  | Bob   | 1  | 100    |
| 3  | Bob   | 2  | 50     |
| 3  | Bob   | 3  | 75     |
+----+-------+----+--------+
(3 × 3 = 9 rows)


ANTI-JOIN ("customers without orders"):
+----+-------+
| id | name  |
+----+-------+
| 2  | Sara  |
| 3  | Bob   |
+----+-------+
(LEFT JOIN + WHERE o.id IS NULL)
```

### Multi-table join visualization

```
customers c                 orders o                 order_items oi
+---+-------+              +---+-------------+      +---+----------+----+
|id | name  |              |id | customer_id |      |id | order_id |...|
+---+-------+              +---+-------------+      +---+----------+----+
| 1 | Ahmed |    JOIN      | 1 |     1       |  JOIN| 1 |    1     | ..|
| 2 | Sara  |  c.id=o.cust | 2 |     1       |oi.ord| 2 |    1     | ..|
+---+-------+              +---+-------------+      | 3 |    2     | ..|
                                                    +---+----------+----+

Result: 3 rows (Ahmed has 2 orders, one with 2 items, the other with 1 item)
```

### When to use each set operation

```
Need                                  → Use
─────────────────────────────────────────────────────────
Combine two queries (no duplicates)    UNION
Combine two queries (with duplicates)  UNION ALL          ← faster
Common rows only                       INTERSECT
Rows in first not in second            EXCEPT  /  MINUS
─────────────────────────────────────────────────────────
```

UNION ALL example — combining log streams without dedup:
```sql
-- Active and archived sources, all entries
SELECT id, message, 'active' AS source FROM logs_active
UNION ALL
SELECT id, message, 'archive' AS source FROM logs_archive
ORDER BY id;
```

### Anti-join: three equivalent forms

```sql
-- Customers with no orders

-- Form 1: LEFT JOIN + IS NULL
SELECT c.id, c.name FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.id IS NULL;

-- Form 2: NOT EXISTS (recommended)
SELECT c.id, c.name FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id);

-- Form 3: NOT IN (caution with NULL!)
SELECT c.id, c.name FROM customers c
WHERE c.id NOT IN (
    SELECT customer_id FROM orders WHERE customer_id IS NOT NULL  -- ← critical
);
```

Forms 1 and 2 normally compile to the same anti-join plan; form 3 is the odd one out once the column is nullable (see the worked plan below). **`NOT EXISTS` is the safe default** — explicit, NULL-aware, fast.

### Worked plan: what the three anti-join forms actually compile to

Forms 1 and 2 give the optimizer permission to use a single anti-join operator. Form 3, on a nullable column, does not — the engine has to preserve `NOT IN`'s three-valued semantics, and that shape is no longer an anti-join. Run `EXPLAIN` yourself; the operator names are the evidence.

```
PostgreSQL — LEFT JOIN + IS NULL, and NOT EXISTS: same shape
─────────────────────────────────────────────────────────────
Hash Anti Join
  Hash Cond: (c.id = o.customer_id)
  ->  Seq Scan on customers c
  ->  Hash
        ->  Seq Scan on orders o

PostgreSQL — NOT IN over a NULLable column: not an anti-join
─────────────────────────────────────────────────────────────
Seq Scan on customers c
  Filter: (NOT (hashed SubPlan 1))     ← a filter over a materialised set,
  SubPlan 1                              re-checked per row, NULL-poisonable
    ->  Seq Scan on orders o
```

On SQL Server the equivalent operator is a `Hash Match` / `Nested Loops` / `Merge Join` carrying the **`Left Anti Semi Join`** logical operation. The `NOT IN` form typically still reaches an anti-semi join, but with extra operators bolted on to test whether the subquery produced a NULL at all — the plan gets visibly more complicated in exactly the way the semantics demand. Two things to take from this:

- **Read the logical operation, not just the physical one.** `Hash Match` tells you the algorithm; `(Left Anti Semi Join)` next to it tells you the engine understood "rows with no match" and will stop at the first match per row.
- **Declaring the column `NOT NULL` is an optimizer feature, not just data hygiene.** Once the column cannot be NULL, `NOT IN` and `NOT EXISTS` are provably equivalent and the engine is free to use the same plan for both.

### Reading a join plan — the three checks that matter

1. **Estimated versus actual rows at each join.** A large divergence is the root cause of most bad join plans; everything else downstream is a symptom. `EXPLAIN (ANALYZE, BUFFERS)` in PostgreSQL, "Include Actual Execution Plan" or `SET STATISTICS PROFILE ON` in SQL Server, `EXPLAIN ANALYZE` in MySQL 8.0.18+.
2. **The join operator, and which input is the build side.** For a hash join the smaller input should be the build (hash) side. A hash join building on the 50-million-row input is the optimizer telling you its estimates are wrong.
3. **Warnings on the operator.** A hash join whose memory grant is too small spills to disk (`tempdb` in SQL Server — shown as a spill warning on the operator; PostgreSQL reports `Batches: N` above 1 with `work_mem` exceeded). A spilled hash join is doing the same logical work with disk in the middle of it, and the fix is usually a better estimate or a filter, not a bigger memory setting.

SQL Server 2017 and later can also defer the choice: a **batch mode adaptive join** picks nested loops or hash at runtime, after reading the build input, by comparing the actual row count against a threshold computed at compile time. It requires batch mode — a columnstore index in SQL Server 2017; SQL Server 2019 extended batch mode to rowstore under compatibility level 150. Useful to name, but it is a safety net for cardinality-estimate errors, not a substitute for fixing them.

> 🌍 **In the real world**: a nightly settlement job joined `orders` to `payments` on the same key both tables were clustered by, so the plan was a merge join reading two already-sorted streams and the job finished in minutes for years. A migration re-clustered `orders` on a new surrogate key to spread insert hot spots, and the merge join now needed an explicit sort of the whole orders range; the sort's memory grant wasn't enough, it spilled to `tempdb`, and the job started overrunning into the business day. The plan change was visible immediately in the operator list — a Sort that had never been there before — but nobody looked, because the schema change and the batch slowdown were reported as unrelated tickets. The fix was a nonclustered index that restored the sort order the join wanted.

### Performance: filter in JOIN's `ON` vs in `WHERE`

For INNER JOIN, the two are equivalent:

```sql
-- Equivalent
SELECT * FROM a JOIN b ON a.id = b.a_id AND b.status = 'Active';
SELECT * FROM a JOIN b ON a.id = b.a_id WHERE b.status = 'Active';
```

For LEFT JOIN, they differ — filter in `ON` keeps unmatched left rows; filter in `WHERE` drops them.

```sql
-- Keeps customers with no Active orders (Active filter applies before join)
SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id AND o.status = 'Active';

-- Effectively converts to INNER JOIN — drops customers with no Active orders
SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.status = 'Active';
```

The second is a common bug. If you mean "all customers, optionally with their Active orders," put the filter in `ON`. Use `WHERE` only for filters that should drop unmatched left rows.

**The mechanism, so you can defend it.** Microsoft's `FROM` reference states the rule plainly: "the predicates in the ON clause are applied to the table before the join, whereas the WHERE clause is semantically applied to the result of the join." The join produces NULL-extended rows for unmatched left rows; then `WHERE o.status = 'Active'` evaluates `NULL = 'Active'` → UNKNOWN → the row is discarded.

A predicate that cannot be TRUE when its inputs are NULL is called **null-rejecting** (or *strict*), and optimizers use exactly that property: if a `WHERE` predicate on the inner side is null-rejecting, no NULL-extended row can survive, so the outer join is rewritten as an inner join before planning even starts. PostgreSQL performs this as an outer-join reduction step during planning; SQL Server's optimizer applies the same simplification. That is why the plan says `Hash Join` when you wrote `LEFT JOIN` — the engine is not ignoring you, it has proved that your query means an inner join.

```
LEFT JOIN, predicate in ON            LEFT JOIN, predicate in WHERE
──────────────────────────            ─────────────────────────────
1. filter right rows                  1. join
2. join what's left                   2. NULL-extend unmatched left rows
3. NULL-extend unmatched left rows    3. filter — UNKNOWN kills the NULL rows
   → all left rows survive               → outer join collapses to inner
```

Two consequences worth knowing: `IS NULL` is *not* null-rejecting, which is why the anti-join pattern `LEFT JOIN … WHERE o.id IS NULL` survives the rewrite and still works; and inner joins are freely reorderable while outer joins are not, so every `LEFT JOIN` you write that could have been an `INNER JOIN` narrows the optimizer's options.

### Fan-out: the double-counting bug and its fix

The single most expensive join bug in business systems is not a slow query, it is a query that returns a plausible wrong number. Joining two 1:N children of the same parent multiplies them against each other:

```
orders (1 row)
  ├── order_items   : 3 rows
  └── payments      : 2 rows

orders JOIN order_items JOIN payments  →  1 × 3 × 2 = 6 rows

Every order-level value now appears 6 times.
Every item quantity now appears 2 times (once per payment).
Every payment amount now appears 3 times (once per item).
```

```sql
-- ❌ BEFORE: SUM(oi.quantity) is doubled, SUM(p.amount) is tripled,
--    and SUM(o.total) is sextupled. DISTINCT cannot save this.
SELECT o.id, SUM(o.total) AS order_total,
       SUM(oi.quantity) AS units, SUM(p.amount) AS paid
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN payments    p  ON p.order_id  = o.id
GROUP BY o.id;
```

```sql
-- ✅ AFTER: each 1:N branch is collapsed to one row per order BEFORE joining.
WITH item_totals AS (
    SELECT order_id, SUM(quantity) AS units
    FROM order_items GROUP BY order_id
),
payment_totals AS (
    SELECT order_id, SUM(amount) AS paid
    FROM payments GROUP BY order_id
)
SELECT o.id, o.total,
       COALESCE(i.units, 0) AS units,
       COALESCE(p.paid,  0) AS paid
FROM orders o
LEFT JOIN item_totals    i ON i.order_id = o.id
LEFT JOIN payment_totals p ON p.order_id = o.id;
```

Both joins are now 1:1 by construction, so `o.total` needs no aggregate at all — which is the tell that the grain is right. Two alternatives with the same effect: correlated scalar subqueries in the select list (readable, and fine when the parent set is small), or `CROSS APPLY` / `LEFT JOIN LATERAL` per branch. The one thing that never works is `SELECT DISTINCT` — it deduplicates rows, and these rows are not duplicates.

### Range joins on effective-dated rows

Price lists, tax rates, contract terms and SCD-2 dimension tables are all the same shape: a key plus a validity period. Joining to them is a **non-equi join**, and it has two traps that equality joins don't.

```sql
-- Half-open interval [valid_from, valid_to) — the correct default
SELECT o.id, o.sku, p.price
FROM orders o
JOIN prices p
  ON p.sku = o.sku
 AND o.ordered_at >= p.valid_from
 AND o.ordered_at <  p.valid_to;     -- ← strict <, not BETWEEN
```

**Trap 1: `BETWEEN` is inclusive at both ends.** `ordered_at BETWEEN p.valid_from AND p.valid_to` matches *two* versions for an order placed exactly at a changeover instant, because the old row's `valid_to` and the new row's `valid_from` are the same value. Half-open intervals (`>= from AND < to`) make the boundary belong to exactly one row by construction.

**Trap 2: nothing stops overlapping rows unless you make it.** The join says "give me the row whose period contains this timestamp"; if two rows' periods overlap, you get both, the order row is duplicated, and every aggregate above it is wrong. Enforce non-overlap in the schema:

- **PostgreSQL**: an exclusion constraint — `EXCLUDE USING gist (sku WITH =, tsrange(valid_from, valid_to) WITH &&)`, which needs the `btree_gist` extension for the equality part. The database then rejects the overlapping insert.
- **SQL Server**: no exclusion constraints, and no application-time period tables either — system-versioned temporal tables maintain *system* time (`SysStartTime`/`SysEndTime`) for row history, not a business validity period you control. A unique index on `(sku, valid_from)` prevents duplicate starts but not overlap; the options are a trigger, a stored-procedure-only write path, or an application-level check inside a serializable transaction.

Index the child on `(sku, valid_from)`: the seek is bounded on `sku` and one side of the range, and the other side is a residual filter. That is as good as a btree gets for interval containment — which is the reasoning behind PostgreSQL's GiST range indexes for high-volume interval work.

> 🌍 **In the real world**: a pricing service joined `order_lines` to an effective-dated `prices` table and returned the price from `.First()` in C#, because the join "obviously" returned one row. A supplier import wrote a new price row with a `valid_from` a day earlier than intended, overlapping the existing row; the join started returning two rows per SKU, `.First()` picked whichever came back first, and the result was written into a one-hour response cache. Customers saw last month's price for an hour at a time, non-deterministically, and it took two days to reproduce. Two fixes: `.Single()` so the ambiguity throws instead of choosing, and an overlap constraint so the ambiguity can't be stored in the first place.

### Pivoting with conditional aggregation (no PIVOT operator)

Many problems "join + aggregate" that look like pivots are actually one-liners:

```sql
-- "Order count by status, per customer"
SELECT
    c.id, c.name,
    SUM(CASE WHEN o.status = 'Pending'   THEN 1 ELSE 0 END) AS pending,
    SUM(CASE WHEN o.status = 'Paid'      THEN 1 ELSE 0 END) AS paid,
    SUM(CASE WHEN o.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.id, c.name;
```

This is more portable than vendor-specific `PIVOT` syntax (T-SQL) and clearer for review.

### Relational division — "all of", not "any of"

`EXISTS` and `IN` answer **any**. A whole family of requirements — and of interview questions — asks **all**: "customers who have bought every product in the Core line", "users who hold every required permission", "orders where every line has shipped". The relational-algebra name for this is **division**, and none of the three engines has a `DIVIDE` operator. You build it out of pieces already on this page.

**Form 1 — double `NOT EXISTS`.** Read it from the inside: *there is no Core product that this customer has not bought.*

```sql
SELECT c.id, c.name
FROM customers c
WHERE NOT EXISTS (
    SELECT 1
    FROM products p
    WHERE p.product_line = 'Core'
      AND NOT EXISTS (                    -- ← the customer did NOT buy this one
          SELECT 1
          FROM orders o
          JOIN order_items oi ON oi.order_id = o.id
          WHERE o.customer_id = c.id
            AND oi.product_id = p.id
      )
);
```

**Form 2 — count and compare.** Count the distinct Core products each customer bought, compare against how many exist.

```sql
SELECT o.customer_id
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products    p  ON p.id = oi.product_id
                   AND p.product_line = 'Core'    -- ← restrict here, not only below
GROUP BY o.customer_id
HAVING COUNT(DISTINCT oi.product_id) =
       (SELECT COUNT(*) FROM products WHERE product_line = 'Core');
```

Three ways this goes wrong in review:

- **`COUNT(DISTINCT oi.product_id)`, never `COUNT(*)`.** A customer who bought one product on four separate orders contributes four line items. `COUNT(*)` counts line items, so that customer clears a bar of four without owning four products.
- **The `product_line` filter has to be on the join**, not only inside the scalar subquery. Leave it off and you are comparing a count of *any* distinct products against the size of the Core range — a customer with enough unrelated purchases passes.
- **The two forms disagree when the divisor is empty.** If the Core line has no products, the double-`NOT EXISTS` form returns *every* customer — "there is no Core product they failed to buy" is vacuously true — while the counting form returns nobody, because a customer with no Core purchases produces no group to test. Neither is a bug; they answer subtly different questions. Pick the one your requirement means and write a test for the empty case. That is the follow-up a good interviewer asks.

**Exact division** — "bought the Core range *and nothing else*" — needs one more predicate: the customer's distinct product count over *all* products must also equal the size of the Core range.

> 🌍 **In the real world**: the authorisation check guarding a bulk-refund screen asked "does this user hold the required permissions?" and was written `WHERE p.code IN ('refund.issue', 'refund.approve', 'ledger.write')` with an `EXISTS` around it. That is *any*, not *all* — anyone holding one of the three could open the screen. It passed review because the SQL reads like the requirement said out loud, and it passed every test because all the test users had been seeded with the full set. An auditor found it. The rewrite used the counting form against a `required_permissions` table, and the regression test's fixture holds exactly two of the three permissions — the case the original code got wrong and no existing test covered.

### Row goals — why `TOP 1` and `EXISTS` bend the whole plan

A **row goal** is the optimizer planning for "produce the first N rows quickly" rather than "produce all rows quickly". Paul White's *Setting and Identifying Row Goals in Execution Plans* (SQLPerformance.com, 2018) describes the bias it creates: toward "non-blocking navigational operations (for example, nested loops joins, index seeks, and lookups) over blocking, set-based operations like sorting and hashing". For joins that is exactly the difference between a hash join over both inputs and a nested loop that expects to stop early.

What sets one on SQL Server: `TOP`, the `FAST n` hint, `SET ROWCOUNT`, `Top` operators the optimizer introduces itself, and semi/anti joins arising from `IN` and `EXISTS`. Microsoft's own list is visible in the escape hatch — `OPTION (USE HINT('DISABLE_OPTIMIZER_ROWGOAL'))` is documented as generating "a plan that doesn't use row goal modifications with queries that contain these keywords: `TOP`, `OPTION (FAST N)`, `IN`, `EXISTS`" (equivalent to trace flag 4138). So the "`EXISTS` short-circuits" claim earlier on this page is not folklore: the semi-join carries an implicit goal of one row per outer row, and the plan is costed accordingly.

**The mechanism, and the failure mode it implies.** To hit a goal of N rows, the optimizer divides N by the predicate's selectivity to estimate how far it will have to read — which silently assumes qualifying rows are spread evenly through the input. When they are not, nothing about the plan changes; only the outcome does:

```
TOP 1 with a row goal, matches spread evenly     TOP 1 with a row goal, no match exists
───────────────────────────────────────────      ─────────────────────────────────────────
seek → read a few rows → match → stop            seek → read → read → … → end of index
"instant"                                        the entire range, to prove a negative
```

The pathological case is therefore the **negative** answer: a `TOP 1` or `EXISTS` that finds nothing has to read everything to prove it. Same plan, same estimates, catastrophically different runtime — which is why these queries are fast in every test that uses data and slow on the one customer who has none.

Identifying one: since the fix in KB4051361 (shipped to SQL Server 2014, 2016 and 2017 — 2017 CU3 and later) affected operators carry an `EstimateRowsWithoutRowGoal` attribute in the showplan XML. When it is present and much larger than `EstimateRows`, a row goal is in play. On older builds you infer it by comparing the estimate against the table's cardinality.

**PostgreSQL has no feature by that name, but the same behaviour falls out of its cost model.** Every node is costed twice, and the docs define the second one as "estimated total cost. This is stated on the assumption that the plan node is run to completion, i.e., all available rows are retrieved. In practice a node's parent node might stop short of reading all available rows." Add a `LIMIT` and startup cost becomes the deciding term, so the planner can pick a different plan entirely. The upside and the failure mode are identical to SQL Server's; only the vocabulary differs. MySQL likewise costs `LIMIT` into plan choice, but exposes no equivalent showplan attribute for you to point at.

> 🌍 **In the real world**: an "open disputes" badge on a customer page used `context.Disputes.Any(d => d.CustomerId == id && d.Status == "Open")` — EF Core translates `.Any()` to `EXISTS`, which sets a row goal, which produced a nested loop that stopped at the first open dispute. It was fast for two years because almost every account being viewed by support had one. Then the badge was added to a bulk account-review screen that rendered it for accounts chosen precisely because they were *quiet*, and each of those calls had to read the customer's entire dispute history to return `false`. The plan was identical in both cases; the data wasn't. The fix was not a hint — it was a filtered index on `(customer_id) WHERE status = 'Open'`, which makes proving absence a seek that terminates immediately instead of a scan that terminates at the end.

### Inside the hash join: build side, spills and role reversal

The third check in "Reading a join plan" was "warnings on the operator". Here is enough of the mechanism to explain a spill rather than just notice one.

**SQL Server.** Microsoft's Joins article: "The hash join has two inputs: the **build** input and **probe** input. The query optimizer assigns these roles so that the smaller of the two inputs is the build input." The build input is read in full and hashed before a single probe row is processed — a hash join is a **blocking** operator on its build side, which is why the first row of the result can be a long time coming. What happens when the build doesn't fit in its memory grant is a graceful ladder, not a cliff:

```
in-memory hash join      build input fits the grant → one pass, no disk
        ↓  (doesn't fit)
grace hash join          both inputs partitioned to files by the hash key;
                         joining rows are guaranteed into the same file pair
        ↓  (partitions still don't fit)
recursive hash join      partitions re-partitioned, multiple levels
```

The docs say the engine "starts by using an in-memory hash join and gradually transitions to grace hash join, and recursive hash join, depending on the size of the build input", and that "the term **hash bailout** is sometimes used to describe grace hash joins or recursive hash joins". The remediation Microsoft names is not a memory setting: "If you see many Hash Warning events in a trace, update statistics on the columns that are being joined." A spill is usually a cardinality-estimate failure wearing a memory costume.

**Role reversal** is the detail worth knowing because it is invisible. "If the Query Optimizer anticipates wrongly which of the two inputs is smaller and, therefore, should have been the build input, the build and probe roles are reversed dynamically... Role reversal occurs inside the hash join **after at least one spill to the disk**", and — the part that catches people — "role reversal doesn't display in your query plan; when it occurs, it's transparent to the user." So a plan can show the large input on the build side and still not be executing that way. Note also that `OPTION (FORCE ORDER)`, per the query-hints reference, "doesn't affect possible role reversal behavior of the Query Optimizer": forcing join order does not force build/probe roles.

**Merge join has a matching piece of hidden machinery.** It "requires both inputs to be sorted on the merge columns, which are defined by the equality (`ON`) clauses of the join predicate" — so no equality, no merge join. And when both sides have duplicates on the key, "a many-to-many merge join uses a temporary table to store rows", because one input has to rewind to the start of a duplicate run for each duplicate on the other side. A merge join on a non-unique key is doing more work than the operator name suggests.

**PostgreSQL** spells the same story in `EXPLAIN (ANALYZE, BUFFERS)`. A `Hash` node reports `Buckets`, `Batches` and `Memory Usage`; `Batches: 1` means it stayed in memory and anything higher means it partitioned to disk. The budget is not `work_mem` alone: the docs describe `hash_mem_multiplier` as computing "the maximum amount of memory that hash-based operations can use", and say "the final limit is determined by multiplying `work_mem` by `hash_mem_multiplier`" — with `work_mem` defaulting to 4MB and `hash_mem_multiplier` to 2.0. Both are per-operation, not per-query — a plan with several hash nodes can allocate that much several times over, per connection.

**MySQL/InnoDB** sizes hash joins with `join_buffer_size`, and the manual is blunt about the overflow path: "When the memory required for a hash join exceeds the amount available, MySQL handles this by using files on disk." In `EXPLAIN FORMAT=TREE` you see `Inner hash join`, `Left hash join`, `Hash semijoin` or `Hash antijoin`; plain `EXPLAIN` only shows `Using join buffer (hash join)` in the `Extra` column.

> 🌍 **In the real world**: a nightly aggregation job on a shared SQL Server instance began missing its window on the nights a marketing import ran first. The plan had not changed — the same hash join was there every night — but on the affected nights the operator carried a spill warning. The build side was an intermediate result whose estimate came from a statistic last sampled before the import doubled the table, so the memory grant was sized for a build input that no longer existed. The team's first instinct was to raise the instance's memory; what actually fixed it was a statistics update scheduled to run *after* the import instead of before it. The tell was in Microsoft's own guidance — a hash warning points at statistics, not at RAM.

### The joins EF Core writes for you

A senior .NET interview will get here eventually, because the SQL that hurts in a .NET codebase is usually SQL nobody wrote by hand.

**Fan-out has a LINQ spelling: cartesian explosion.** Two `Include`s of collection navigations *at the same level* become two `LEFT JOIN`s off the same root, and the database does what it is told:

```csharp
var blogs = await ctx.Blogs
    .Include(b => b.Posts)          // 1:N off Blog
    .Include(b => b.Contributors)   // also 1:N off Blog — siblings
    .ToListAsync();
```

```sql
SELECT b.Id, b.Name, p.Id, p.BlogId, p.Title, c.Id, c.BlogId, c.FirstName, c.LastName
FROM Blogs AS b
LEFT JOIN Posts AS p        ON b.Id = p.BlogId
LEFT JOIN Contributors AS c ON b.Id = c.BlogId
ORDER BY b.Id, p.Id;
```

The EF Core documentation's own arithmetic: "if a given blog has 10 posts and 10 contributors, the database returns 100 rows for that single blog." This is the fan-out from earlier on this page, arriving through an ORM instead of a hand-written `GROUP BY`. Nested includes are safe — `.Include(b => b.Posts).ThenInclude(p => p.Comments)` is a chain, not a pair of siblings, and produces one row per comment with no cross product. EF Core will warn you when it detects a query loading multiple collections with no splitting behaviour configured.

**The fix EF gives you is `AsSplitQuery()`** (EF Core 5.0 and later), or `UseQuerySplittingBehavior(QuerySplittingBehavior.SplitQuery)` as the context-wide default with `AsSingleQuery()` to opt back out. One SQL statement per collection navigation instead of one statement with N joins. Know the documented costs, because "just use split queries" is the shallow answer:

- **No cross-statement consistency.** "While most databases guarantee data consistency for single queries, no such guarantees exist for multiple queries." A concurrent write between the statements gives you a torn object graph. The documented mitigation is a serializable or snapshot transaction — which brings back exactly the concurrency trade-offs from [Joins under concurrency](#joins-under-concurrency).
- **A roundtrip per query**, which is the wrong direction on a high-latency link to a cloud database.
- **Buffering.** Most providers allow only one active query per connection, so earlier results are held in application memory while later statements run (SQL Server with MARS and SQLite are the exceptions the docs name).
- **Reference navigations are joined into every split query**, so a graph with many `1:1` includes repeats those joins.
- **Ordering must be unique when combined with `Skip`/`Take`** on EF versions before 10, or the separate statements can disagree about which rows they are paging. Order by a unique key, not just a date.

**Data duplication is the quieter cousin.** Even a single collection `Include` repeats every root column on every child row; harmless until the root table has a large `varbinary` or text column, at which point you are sending it once per child. The fix is projection — `Select` the columns you need — which also disables change tracking for the resulting anonymous type.

**Inheritance mapping decides how many joins exist at all.** TPH puts the hierarchy in one table (no join); TPT gives each type its own table, and the EF Core performance docs are direct about the consequence — "TPT queries must join together multiple tables, and joins are one of the primary sources of performance issues in relational databases"; TPC gives each concrete type a full table, so querying the base type reads several tables and combines them rather than joining them. The docs publish a benchmark for a 7-type hierarchy seeded with 5,000 rows per type (35,000 rows total), loading all rows: TPH 149.0 ms, TPT 312.9 ms, TPC 158.2 ms — with their own caveat that "actual results always depend on the specific query being executed and the number of tables in the hierarchy". Quote it as a shape, not a law.

**Finally, know which LINQ shapes produce which join.** From the EF Core complex-operators reference:

| LINQ | SQL |
|---|---|
| `Join(...)` | `INNER JOIN` (key selectors compared for equality; anonymous-type keys compared component-wise) |
| `SelectMany` with no reference to the outer element | `CROSS JOIN` |
| `SelectMany` with a `Where` referencing the outer element | `INNER JOIN`, or `LEFT JOIN` with `DefaultIfEmpty()` |
| `SelectMany` referencing the outer element outside a `Where` | `CROSS APPLY`, or `OUTER APPLY` with `DefaultIfEmpty()` |
| `GroupJoin` alone | **not translated** — EF Core documents that it doesn't translate GroupJoin |
| `GroupJoin` + `DefaultIfEmpty` + `SelectMany`, in that immediate sequence | `LEFT JOIN` — this pattern *is* how you write a left join in LINQ |

That last row is the one to remember: there is no `LeftJoin` operator in the LINQ the pattern was built on, so EF Core recognises the GroupJoin/DefaultIfEmpty/SelectMany shape and emits `LEFT JOIN`. Break the sequence — do anything between the operators — and the docs warn "we may not identify it as a Left Join", at which point you are back to an untranslatable GroupJoin.

> 🌍 **In the real world**: an order-history endpoint returned `Order` with `.Include(o => o.Items).Include(o => o.StatusHistory)`. Both are collections off `Order`, so every order came back as items × history rows; a long-running order with a dozen items and a dozen status transitions produced 144 rows to materialise a dozen objects. The p99 was bad but survivable until a customer-service tool started requesting 200 orders at a time and the endpoint began timing out. The team's first instinct was to add caching. The actual change was one call — `AsSplitQuery()` — plus the thing that made it safe: the endpoint reads inside a snapshot transaction, because two statements can see two different worlds and an order whose items and status disagree is worse than a slow page.

</details>

## Common pitfalls

1. **Implicit CROSS JOIN.** Comma-separated tables in `FROM` without an explicit `WHERE` join condition → Cartesian product. Use explicit `JOIN ... ON ...`.
2. **Filter in WHERE turns LEFT JOIN into INNER JOIN.** Move column filters on the right table into the `ON` clause for true outer joins.
3. **`NOT IN` with NULLs.** If the subquery returns any NULL, the entire `NOT IN` returns no rows. Filter NULLs out, or use `NOT EXISTS`.
4. **Multiplying rows.** Joining 1-to-many in multiple chains explodes the result count. Aggregate in subqueries first when needed.
5. **`SELECT DISTINCT` over a multi-join result.** Often masks a join bug; the duplicates indicate the wrong join. Investigate before slapping DISTINCT.
6. **Joining on type mismatches.** `JOIN ON int_col = varchar_col` triggers per-row conversion → can't use index. Match types.
7. **Joining huge tables without filtering.** A `JOIN` between two billion-row tables without WHERE can run for hours. Filter aggressively first.
8. **Self-join with imprecise predicate.** "Find pairs sharing a manager" needs `AND a.id < b.id` to avoid pairing self and duplicates.
9. **`UNION` instead of `UNION ALL`.** Dedup costs (sort or hash). If you know duplicates are impossible, use `UNION ALL` for speed.
10. **Mismatched columns in set operations.** `SELECT a, b FROM ... UNION SELECT b, a FROM ...` succeeds but produces wrong-typed columns by position. Names must match too if used downstream.
11. **`RIGHT JOIN` for readability.** Hard to read. Reorder tables and use `LEFT JOIN`.
12. **CROSS JOIN to "get all combinations" when a join condition exists.** Always check whether you actually wanted a real join.
13. **Assuming `USING` and `NATURAL JOIN` are portable.** The T-SQL `FROM` grammar contains neither — SQL Server has only `ON`, `CROSS JOIN` and `APPLY`. PostgreSQL and MySQL have both. Code written against Postgres and ported to SQL Server fails at parse time, which is the good outcome; the bad one is a team standard built on a keyword half the fleet can't run.
14. **Set-operator precedence and associativity.** `INTERSECT` binds tighter than `UNION`/`EXCEPT`, and `UNION`/`EXCEPT` associate left to right. `A EXCEPT B UNION C` adds C back in rather than removing it. Parenthesise. Likewise, one `ORDER BY` (and in PostgreSQL, `LIMIT`) at the end applies to the whole expression, not the last branch, unless the branch is parenthesised.
15. **Relying on join elimination with untrusted constraints.** On SQL Server the optimizer only removes an FK-backed join if the constraint is trusted; `sys.foreign_keys.is_not_trusted = 1` after a bulk-load runbook means the joins you assumed were free are now being executed.
16. **Nullable join keys.** `NULL = NULL` is UNKNOWN, so rows with NULL in any join column never match — including composite joins where only one component is NULL. Make join keys `NOT NULL` with a sentinel row, or use the engine's NULL-safe comparison (`IS NOT DISTINCT FROM`, `<=>`) and check the plan, because those predicates may not seek.
17. **Framework-driven implicit conversions.** SQL Server's data type precedence ranks `nvarchar` above `varchar`, so a .NET `string` parameter (which EF Core and ADO.NET send as `nvarchar` unless told otherwise) compared to a `varchar` column converts **the column**, not the parameter — and a converted column can lose its seek. Map the column type explicitly (`.HasColumnType("varchar(50)")` / `SqlDbType.VarChar`) so the types match.
18. **Reporting joins on a lock-based engine.** A wide multi-table report under `READ COMMITTED` with `READ_COMMITTED_SNAPSHOT` OFF (the SQL Server default) takes shared locks as it scans — released row by row, but able to accumulate past the 5,000-lock escalation threshold, at which point escalation replaces them with one table lock (never a page lock) that is held for the rest of the statement and blocks writers for the length of the report. `WITH (NOLOCK)` trades that for silently missing or duplicated rows. Fix the query, enable row versioning, or move the read to a replica.
19. **A join hint is a join-order hint (SQL Server).** `INNER HASH JOIN` on one pair of tables enforces the join order for *every* table in the query. You get a `FORCE ORDER` you never typed, and the query stops adapting to new predicates and new statistics.
20. **`IN`/`EXISTS` answers "any", never "all".** A requirement phrased "has all of the required permissions" written as `IN (list)` passes for anyone holding one of them. Use relational division — double `NOT EXISTS`, or `COUNT(DISTINCT ...)` compared to the divisor's size — and test the empty-divisor case, where the two forms disagree.
21. **Two sibling collection `Include`s in EF Core.** Two `1:N` navigations off the same root become two `LEFT JOIN`s and the database returns their cross product. `AsSplitQuery()` removes the explosion but gives up cross-statement consistency, costing a roundtrip per collection and buffering in application memory.
22. **Assuming a `TOP 1` or `EXISTS` is cheap because it's usually fast.** Both set a row goal, so the plan is built to stop at the first match. Proving there is *no* match reads everything. Index for the negative case, not the happy one.

## Interview-ready summary

- **INNER JOIN** = match in both. **LEFT JOIN** = all left + matches.
- **CROSS JOIN** = Cartesian product (no condition). **SELF JOIN** = table joined to itself.
- **Anti-join** ("rows in A with no match in B"): `LEFT JOIN ... WHERE B.id IS NULL` or `NOT EXISTS`.
- **Semi-join** ("rows in A that have a match in B"): `EXISTS`.
- **Set ops:** UNION (dedup), UNION ALL (no dedup, faster), INTERSECT, EXCEPT.
- **Filter in `ON`** for outer joins to keep unmatched left rows; `WHERE` drops them — a null-rejecting `WHERE` predicate lets the optimizer rewrite the outer join as inner.
- **`NOT EXISTS` > `NOT IN`** (NULL-safe and usually faster).
- **Grain**: joining 1:N changes what one row means. Pre-aggregate each branch before joining; `DISTINCT` does not fix fan-out.
- **NULLs never join** (`NULL = NULL` is UNKNOWN), but **set operators treat two NULLs as equal** (`UNION`/`INTERSECT`/`EXCEPT` dedup counts them as duplicates).
- **Join elimination**: unused join + provable uniqueness (+ trusted FK on SQL Server) = the join disappears. `SELECT *` blocks it.
- **Engine gaps**: no `FULL OUTER JOIN` in MySQL; no `USING`/`NATURAL JOIN` in T-SQL; no `INTERSECT ALL`/`EXCEPT ALL` in T-SQL; `INTERSECT`/`EXCEPT` in MySQL only from 8.0.31.
- **Division**: "all of" is not `IN`. Double `NOT EXISTS` or `COUNT(DISTINCT) = divisor size`; the two disagree when the divisor is empty.
- **Row goals**: `TOP`, `FAST n`, `IN`, `EXISTS` make the optimizer plan to stop early — great when a match exists, worst-case when it doesn't.
- **Hash join**: smaller input builds; in-memory → grace → recursive as it outgrows the grant; role reversal happens after a spill and never shows in the plan. A spill points at statistics.
- **Join hints on SQL Server force join order too** — one hint, two effects.
- **EF Core**: two sibling collection `Include`s = cartesian explosion; `AsSplitQuery()` trades it for cross-statement inconsistency and extra roundtrips.

**Expected interview questions:**

1. *"Find customers who haven't placed any orders."* — Anti-join. `LEFT JOIN orders ON ... WHERE orders.id IS NULL` or `NOT EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id)`.
2. *"Difference between LEFT JOIN and INNER JOIN?"* — INNER returns only matches. LEFT returns all left rows; right columns NULL when unmatched.
3. *"Find employees and their managers (managers are also in the same table)."* — Self-join: `employees e LEFT JOIN employees m ON e.manager_id = m.id`.
4. *"What's the difference between UNION and UNION ALL?"* — UNION removes duplicates (sort/hash cost). UNION ALL preserves duplicates (faster). Use ALL when duplicates are impossible or acceptable.
5. *"Why is `NOT IN` problematic with NULLs?"* — If the subquery's result contains NULL, the entire `x NOT IN (...)` evaluates to NULL (not TRUE), filtering out everything. `NOT EXISTS` handles NULLs correctly.
6. *"How do you find users present in two tables (not just one)?"* — `INTERSECT` of the two queries. Or `INNER JOIN` on the matching column.
7. *"What's a semi-join?"* — Keep rows in A that have at least one match in B, without duplicating A's rows. Use `EXISTS`.
8. *"Your SUM is exactly double. What did you do?"* — Fan-out: two 1:N branches joined to the same parent multiply against each other, so each branch's values repeat once per row of the other. Pre-aggregate each branch to one row per parent (CTE or `APPLY`) before joining. `DISTINCT` doesn't fix it — the rows differ in the other branch's columns.
9. *"Why would the plan show an inner join when the query says LEFT JOIN?"* — A null-rejecting predicate on the inner table in `WHERE` makes NULL-extended rows impossible, so the optimizer simplifies the outer join to an inner one. Move the predicate to `ON` if you meant to keep unmatched left rows.
10. *"When can the optimizer remove a join entirely?"* — When no column of the joined table is referenced and the join can't change row counts: uniqueness on the join column prevents duplication, and (for an inner join on SQL Server) a **trusted** foreign key guarantees the match exists. PostgreSQL does the LEFT JOIN case using a unique index; `SELECT *` prevents it everywhere.
11. *"How does a big reporting join take a production database down?"* — On SQL Server with `READ_COMMITTED_SNAPSHOT` OFF (the on-prem default), `READ COMMITTED` takes shared locks while scanning — each released as soon as its row is read — but at 5,000 locks on one nonpartitioned table or index in a statement, escalation converts them to a single table lock — always a table lock, never a page lock — held for the rest of the statement, and writers queue behind that for the length of the report. PostgreSQL and InnoDB read from an MVCC snapshot instead, so the same query doesn't block writers — it holds an old snapshot and delays cleanup instead.
12. *"Find customers who bought every product in a range."* — Relational division. Double `NOT EXISTS` ("no product in the range that they didn't buy"), or `GROUP BY customer HAVING COUNT(DISTINCT product_id) = (SELECT COUNT(*) FROM products WHERE …)`. `COUNT(DISTINCT)` because the grain is line items; the range filter goes on the join, not just the subquery. The forms differ on an empty divisor.
13. *"A `TOP 1` query is instant most of the time and takes minutes occasionally, with the same plan. Why?"* — Row goal. `TOP` biases the plan toward seeks and nested loops that stop at the first match, sized by dividing the goal by the predicate's selectivity. When a match comes early it stops; when there is no match it reads to the end to prove it. Confirm with `EstimateRowsWithoutRowGoal` in the showplan; fix with an index that makes the negative case a seek, not with a hint.
14. *"Your hash join spilled to `tempdb`. Do you ask for more memory?"* — No. The grant came from an estimate, so a spill is usually an estimate failure; Microsoft's remediation for hash warnings is to update statistics on the joined columns. After that, hash less: filter earlier, project fewer columns, index the join key. Worth naming that the engine degrades gracefully (in-memory → grace → recursive) and can reverse build and probe roles at runtime after a spill without showing it in the plan.
15. *"Your EF Core endpoint returns 144 rows to build 12 objects. What happened and what do you change?"* — Two collection `Include`s at the same level become two `LEFT JOIN`s off one root and the database returns their cross product. `AsSplitQuery()` issues one statement per collection instead; the price is that multiple statements have no consistency guarantee between them, plus a roundtrip each and buffering in application memory. If the root just has one large column, that's data duplication rather than cartesian explosion — project the column away instead.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — LEFT vs INNER vs FULL vs CROSS

> **Q**: When do you choose LEFT JOIN over INNER JOIN?
>
> **A**: When you need to keep every row from the left table regardless of whether a match exists on the right. Typical: "all customers, with their orders if any" — INNER drops customers without orders; LEFT keeps them with NULL columns from the right.
>
> **Cross-Q**: I write `LEFT JOIN orders o ON o.customer_id = c.id WHERE o.status = 'Paid'`. Does this still return customers with no orders?
>
> **A**: No — the `WHERE o.status = 'Paid'` predicate is evaluated after the join produces NULL-padded outer rows, and `NULL = 'Paid'` is UNKNOWN (falsy), so those rows get dropped. The optimizer often detects this and rewrites the LEFT JOIN as an INNER JOIN. To preserve "all customers, optionally with Paid orders," move the predicate into `ON`: `... ON o.customer_id = c.id AND o.status = 'Paid'`.
>
> **Cross-Q²**: When would FULL OUTER JOIN be the right call instead of LEFT?
>
> **A**: Reconciliation between two snapshots where rows can be missing on **either** side: comparing an old-system extract to a new-system extract, or auditing referential integrity ("orphan orders + customers with no orders, in one query"). LEFT alone gives you one-sided diff; FULL gives both. Most "find missing" questions are actually one-sided though, so FULL is rare in practice.

### Drill 2 — NULL semantics on outer joins

> **Q**: After a LEFT JOIN, `o.status = 'Cancelled'` evaluates to what for unmatched rows?
>
> **A**: UNKNOWN, not TRUE and not FALSE. SQL uses three-valued logic; comparing anything to NULL yields UNKNOWN. WHERE treats UNKNOWN as falsy, so the row is dropped.
>
> **Cross-Q**: How do you write "customers whose orders are NOT Cancelled, including customers with no orders"?
>
> **A**: `WHERE o.status <> 'Cancelled' OR o.status IS NULL`. The IS NULL branch catches the unmatched LEFT JOIN rows. Alternative: `WHERE COALESCE(o.status, '') <> 'Cancelled'` — coerces NULL to a non-matching sentinel. Or move the status predicate into the ON clause so unmatched rows survive.
>
> **Cross-Q²**: Does `GROUP BY o.status` collapse all NULL status rows into one group or many?
>
> **A**: One group. GROUP BY treats all NULLs as the same group (this is inconsistent with WHERE's three-valued logic but is the SQL standard). So you'll get a single NULL bucket that combines outer-join NULLs and any actual NULL status values — they're indistinguishable. If you need to tell them apart, add a column like `CASE WHEN o.id IS NULL THEN 'no order' ELSE COALESCE(o.status, 'unknown') END`.

### Drill 3 — Semi-join via EXISTS

> **Q**: Write "customers with at least one order over $1000" three ways. Which is fastest?
>
> **A**: (1) `WHERE EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id AND total > 1000)`; (2) `WHERE c.id IN (SELECT customer_id FROM orders WHERE total > 1000)`; (3) `SELECT DISTINCT c.* FROM customers c JOIN orders o ON ... WHERE total > 1000`. EXISTS is usually fastest because it short-circuits — first match wins, no row multiplication, no DISTINCT sort.
>
> **Cross-Q**: Why does JOIN + DISTINCT lose to EXISTS on a customer with 10,000 orders?
>
> **A**: JOIN produces every matching pair before the engine dedupes. A customer with 10,000 qualifying orders generates 10,000 rows that must be hashed/sorted to dedupe down to 1. EXISTS stops scanning that customer's orders the moment it finds any match — single row out, no dedup.
>
> **Cross-Q²**: Modern optimizers claim to rewrite `IN (SELECT ...)` as a semi-join. So is the choice purely stylistic?
>
> **A**: Mostly. PostgreSQL has had explicit semi-join and anti-join as planner concepts since 8.4 (2009), whose release notes describe formalising the ad-hoc `IN (SELECT …)` handling and extending it to `EXISTS`/`NOT EXISTS` so that logically equivalent `IN` and `EXISTS` forms plan alike; SQL Server's optimizer has had semi-join operators for far longer than that. But two exceptions: (1) `NOT IN` over a nullable column does **not** become `NOT EXISTS`, because NULL semantics differ — `NOT IN` is NULL-poisoned and the optimizer must preserve that behaviour; declare the column `NOT NULL` and the two become provably equivalent; (2) optimizer cost models can still pick the wrong plan on skewed data. Even where they're equivalent in principle, prefer `EXISTS`/`NOT EXISTS` because their semantics are explicit and NULL-safe.

### Drill 4 — Anti-join NULL gotcha

> **Q**: `SELECT * FROM customers WHERE id NOT IN (SELECT customer_id FROM orders)` returns zero rows. There are clearly customers without orders. Why?
>
> **A**: The orders table has at least one row where `customer_id IS NULL`. `x NOT IN (a, b, NULL)` is logically `x <> a AND x <> b AND x <> NULL`; the last comparison yields UNKNOWN, which makes the entire AND chain UNKNOWN, which WHERE treats as falsy. So every row gets filtered out.
>
> **Cross-Q**: How do you fix it?
>
> **A**: Three options. (1) `WHERE customer_id IS NOT NULL` inside the subquery: `... NOT IN (SELECT customer_id FROM orders WHERE customer_id IS NOT NULL)`. (2) Rewrite as `NOT EXISTS`: `WHERE NOT EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id)` — NULL-safe by design. (3) LEFT JOIN + IS NULL: `LEFT JOIN orders o ON o.customer_id = c.id WHERE o.id IS NULL`. NOT EXISTS is the canonical fix.
>
> **Cross-Q²**: Why didn't the SQL standard make `NOT IN` NULL-safe?
>
> **A**: The standard committee chose mathematical purity — `x NOT IN (set)` means "x is not equal to any element," and "x = NULL" is undefined under three-valued logic, so the result is also undefined. Changing this would break millions of existing queries. The pragmatic answer is "use NOT EXISTS"; it's been the recommended pattern since the 1990s and every database textbook flags the NULL trap.

### Drill 5 — Nested loops vs hash vs merge

> **Q**: Three physical join algorithms — when does the optimizer pick each?
>
> **A**: **Nested loop**: small outer (driver) table + indexed inner — for each outer row, index seek the inner. Low memory. **Hash join**: large unsorted inputs, no useful index — build a hash table on the smaller side, probe with the larger. High memory, linear time. **Merge join**: both inputs already sorted on the join key (clustered index or upstream ORDER BY) — walk both streams in parallel. Low memory if pre-sorted.
>
> **Cross-Q**: I have a 1B-row fact table joining a 100-row dimension. Which algorithm wins, and why?
>
> **A**: Nested loop with the 100-row dim as the outer (driver) and an index seek on the fact's foreign-key column for the inner — 100 index seeks total, each touching only the matching rows. Hash would build a tiny hash on the dim but must still probe it with every one of the 1B fact rows, so the whole fact table gets read. Merge would require sorting 1B rows (or scanning a pre-sorted clustered index). The comparison is "100 seeks" versus "read a billion rows" — provided the fact has a usable index on the join column. Without that index, the nested loop is the worst option instead of the best, which is why the answer is always "it depends on the index".
>
> **Cross-Q²**: When does hash join beat the others on the same workload?
>
> **A**: When there's no index on the inner join column (so nested loop degrades to full scan per outer row → quadratic), and the data isn't sorted (so merge would incur sort cost). For two large unsorted tables joined ad hoc — analytical/reporting queries on a data warehouse — hash join is the default winner. The cost: a memory grant proportional to the build side; if it doesn't fit, the hash spills to TempDB/disk and you lose most of the gain.

### Drill 6 — Self joins for hierarchies

> **Q**: How do you list every employee with their manager's name from a single `employees(id, name, manager_id)` table?
>
> **A**: Self-join — alias the table twice, one as the employee and one as the manager: `SELECT e.name, m.name AS manager FROM employees e LEFT JOIN employees m ON e.manager_id = m.id`. LEFT JOIN so top-level employees (manager_id IS NULL) still appear with NULL manager.
>
> **Cross-Q**: What if I need three levels — employee, manager, grand-manager — in one query?
>
> **A**: Chain three self-joins: `FROM employees e LEFT JOIN employees m ON e.manager_id = m.id LEFT JOIN employees gm ON m.manager_id = gm.id`. Works, but the SQL gets ugly fast. Beyond 2-3 levels, switch to a **recursive CTE** (`WITH RECURSIVE org_tree AS (...)`) which traverses an arbitrary-depth tree in one query.
>
> **Cross-Q²**: Why does the recursive CTE outperform a 10-level chain of self-joins?
>
> **A**: Self-joins materialize every level even for nodes that aren't deep — a 10-level chain forces 10 join operations whether your tree is 2 deep or 10 deep. The optimizer can't prune. Recursive CTE iterates only while new rows are produced — a 2-deep tree terminates after 2 iterations regardless of the maximum theoretical depth. Plus, the CTE's iteration count adapts to your actual data, not the SQL author's worst-case estimate.

### Drill 7 — UNION vs UNION ALL performance

> **Q**: Why is `UNION ALL` faster than `UNION` on a 100M-row combined result?
>
> **A**: UNION dedupes the combined rowset — that's a sort or hash over 100M rows. UNION ALL just concatenates the two streams, no dedup work. On large sets the dedup cost can dominate the entire query.
>
> **Cross-Q**: When is it safe to use UNION ALL?
>
> **A**: When duplicates are impossible by construction (the two queries cover disjoint partitions — e.g., `WHERE region='US' UNION ALL WHERE region='EU'` with a region constraint), or when duplicates are semantically acceptable (combining log streams where you want to see every event). The "always use UNION just to be safe" habit adds a blocking sort-or-hash over the combined rowset to every execution of a hot report — and a blocking operator also means the first row can't be returned until the last one has been read.
>
> **Cross-Q²**: I have two queries that could produce duplicates but downstream code deduplicates anyway. Should I still pay for UNION's dedup?
>
> **A**: No — push the dedup to where it's already happening. Use `UNION ALL` in the SQL and let the downstream `SELECT DISTINCT`, application-level set, or `GROUP BY` handle it. Paying for two dedups (SQL's sort + downstream's dedup) is pure waste. If downstream is in-memory hash dedup, it's often faster than SQL's on-disk sort anyway.

### Drill 8 — INTERSECT and EXCEPT

> **Q**: When would you use INTERSECT instead of an INNER JOIN?
>
> **A**: When the two queries share identical column shapes and you want **set semantics** — rows present in both, deduplicated. Example: emails that appear in both `customers_us` and `customers_eu`: `SELECT email FROM customers_us INTERSECT SELECT email FROM customers_eu`. INTERSECT auto-dedupes and treats rows positionally; INNER JOIN requires explicit ON and can multiply if either side has duplicates.
>
> **Cross-Q**: EXCEPT vs NOT EXISTS — which for "customers in old system not in new system"?
>
> **A**: EXCEPT if comparing full-row tuples with matching column shapes: `SELECT id, email FROM old EXCEPT SELECT id, email FROM new`. NOT EXISTS if the comparison is correlated and partial: `SELECT * FROM old o WHERE NOT EXISTS (SELECT 1 FROM new WHERE id = o.id)`. EXCEPT is more concise for full-row comparison; NOT EXISTS handles partial keys and joins on different column names.
>
> **Cross-Q²**: Does INTERSECT preserve duplicates if both sides have them?
>
> **A**: No — INTERSECT (without ALL) dedupes. `INTERSECT ALL` preserves the minimum count of each duplicate across both sides: if A has 3 copies of X and B has 5, `INTERSECT ALL` produces 3 copies, plain `INTERSECT` produces 1. Engine support matters here — PostgreSQL has `INTERSECT ALL` and `EXCEPT ALL`, MySQL gained all of `INTERSECT`/`EXCEPT` plus their `ALL` forms in 8.0.31, and **T-SQL has no `ALL` variant of either operator**: the documented syntax is `{ EXCEPT | INTERSECT }` with nothing between. On SQL Server you emulate `EXCEPT ALL` with a row-numbering trick (`ROW_NUMBER()` per duplicate group on both sides, then `EXCEPT` on the numbered rows). Also worth knowing: in a SQL Server plan `EXCEPT` appears as a left anti semi join and `INTERSECT` as a left semi join.

### Drill 9 — OUTER APPLY vs LEFT JOIN with subquery

> **Q**: When would you reach for OUTER APPLY / LATERAL instead of LEFT JOIN?
>
> **A**: When the right-hand side is a correlated query that depends on the left row — typically "top N per group." Example: "each customer's 3 most recent orders": `FROM customers c OUTER APPLY (SELECT TOP 3 * FROM orders WHERE customer_id = c.id ORDER BY created_at DESC) o`. A plain LEFT JOIN can't reference `c.id` inside a subquery that uses TOP/LIMIT meaningfully.
>
> **Cross-Q**: How does LATERAL in PostgreSQL achieve the same thing?
>
> **A**: `FROM customers c LEFT JOIN LATERAL (SELECT * FROM orders WHERE customer_id = c.id ORDER BY created_at DESC LIMIT 3) o ON true`. LATERAL allows the subquery in FROM to reference earlier FROM-clause aliases. Without LATERAL, the subquery can't see `c.id`. SQL Server's APPLY is the same idea with different syntax — CROSS APPLY ≈ INNER JOIN LATERAL, OUTER APPLY ≈ LEFT JOIN LATERAL.
>
> **Cross-Q²**: Is APPLY/LATERAL faster than window-function top-N (`ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) ... WHERE rn <= 3`)?
>
> **A**: Often yes for small N because APPLY can use an index seek per customer with a LIMIT — touching only the top 3 rows per group. The window-function approach reads every order, computes ROW_NUMBER, then filters — full scan of the source table. For small N + indexed sort key, APPLY/LATERAL wins. For large N or when window calc is cheap, window functions are simpler and often comparable.

### Drill 10 — Equi vs non-equi joins

> **Q**: What's a non-equi join and when do you use one?
>
> **A**: A join with a non-equality predicate — `<`, `BETWEEN`, range overlap. Example: "find salary band for each employee" — `JOIN salary_bands b ON e.salary >= b.min AND e.salary < b.max`. Used for range lookups, version tables (effective-date ranges), interval overlaps.
>
> **Cross-Q**: Why are non-equi joins typically slower than equi-joins?
>
> **A**: Hash join hashes the key and probes with it; merge join walks two sorted streams matching equal values — both are built around an equality, so on **SQL Server and PostgreSQL** a predicate with no equality conjunct falls back to nested loop. **MySQL is the exception**: from 8.0.20 the manual states "it is no longer necessary for the join to contain at least one equi-join condition in order for a hash join to be used." With an indexed inner column, the optimizer can use an index range scan per outer row — still nested loop, but bounded. Without an index on the range column, it's a full scan per outer row — quadratic.
>
> **Cross-Q²**: How do you index a range join like `JOIN bands ON e.salary >= b.min AND e.salary < b.max`?
>
> **A**: Two strategies. (1) Index on `(min, max)` on the bands table and rely on the optimizer to use it for range seeks — the weakness is that a btree can only bound one end of the range, so it seeks on `min` and then filters on `max`. (2) In PostgreSQL, index the interval itself: a **GiST** index on `int4range(min, max)` with the overlap operator, which searches the range structurally instead of scanning a prefix. The mechanism is the claim to make in an interview — btree orders single values, GiST indexes intervals — rather than a speed factor.

### Drill 11 — Join cardinality estimation

> **Q**: The optimizer estimates 1000 rows from a join but the actual is 10M. What goes wrong?
>
> **A**: Cardinality estimation error. Common causes: (1) stale statistics — the histograms don't reflect current data distribution; (2) skewed data — one join key value dominates (e.g., 99% of orders are from one customer); (3) correlated predicates — `WHERE country='PK' AND city='Karachi'` (city implies country, but the optimizer multiplies independent selectivities); (4) join columns with no statistics. Result: optimizer picks nested loop expecting a small driving set, gets 10M rows, runs 10M index seeks instead of one hash join.
>
> **Cross-Q**: How do you diagnose this?
>
> **A**: `EXPLAIN ANALYZE` (Postgres) or `SET STATISTICS PROFILE ON` (SQL Server). Compare estimated vs actual rows at each operator. Massive deltas (10x+) flag the bad node. Then: update statistics (`ANALYZE` / `UPDATE STATISTICS`), increase the histogram bucket count, add multi-column statistics for correlated predicates, or as a last resort, use a hint to force the right join algorithm.
>
> **Cross-Q²**: Why does the optimizer get correlated columns so wrong?
>
> **A**: It assumes independence by default. Take illustrative numbers: if `country='PK'` selects 5% of rows and `city='Karachi'` selects 0.1%, multiplying them as independent gives an estimate of 0.005%. But every Karachi row *is* a PK row, so the true selectivity of the pair is still 0.1% — the arithmetic under-estimates twentyfold, and that is enough to pick a nested loop where a hash join was needed. **The fix is engine-specific, and naming the right one is the senior answer**: PostgreSQL has **extended statistics** — `CREATE STATISTICS cust_geo (dependencies, ndistinct, mcv) ON country, city FROM customers;` followed by `ANALYZE` — which records the functional dependency and a multivariate most-common-values list. SQL Server's nearest equivalent is **multi-column statistics**, `CREATE STATISTICS cust_geo ON dbo.customers (country, city);`, and it is deliberately weaker: the documentation states "only the first column is used for creating the histogram. All columns are used for cross-column correlation statistics called densities" — a density improves the estimate for equality on the whole leading combination, but you do not get a histogram on `city`. MySQL has per-column histograms only (`ANALYZE TABLE customers UPDATE HISTOGRAM ON city;`, 8.0 and later; the column list may name several columns, but you get one independent histogram per column — the manual notes these statements "affect only the named columns"), so it has no multi-column correlation statistics to give you at all.

### Drill 12 — Multi-column joins + composite keys

> **Q**: When do you join on multiple columns?
>
> **A**: When the foreign-key relationship requires more than one column to be unique — typically composite primary keys or natural keys. Example: `JOIN order_items oi ON oi.order_id = o.id AND oi.warehouse_id = o.warehouse_id`. Skip a column, and you may match rows across warehouses, producing wrong results silently.
>
> **Cross-Q**: How does the index strategy change for a two-column join?
>
> **A**: You need a **composite index** on `(order_id, warehouse_id)` on the child table, with column order matching the most selective predicate first. A separate index on `order_id` alone and another on `warehouse_id` alone is **not** equivalent — the optimizer can use only one at a time for the seek, then filter on the other (less efficient). Composite is the right shape; the order matters for prefix matching.
>
> **Cross-Q²**: What if `warehouse_id` is functionally dependent on `order_id` (each order belongs to exactly one warehouse)?
>
> **A**: Then the join on `warehouse_id` is redundant — `JOIN ... ON oi.order_id = o.id` produces the same result. But explicit redundancy isn't wrong; it documents the relationship and protects against future schema drift (if an order ever splits across warehouses, the redundant predicate catches the breakage). Some teams prefer the explicit form; others trust foreign-key enforcement and drop it. Both are defensible.

### Drill 13 — Three-way joins ordering

> **Q**: Does join order in SQL (`A JOIN B JOIN C`) affect performance?
>
> **A**: Not directly — the optimizer reorders joins to find the best plan, considering selectivity, indexes, and cardinality estimates. **Logically**, INNER JOINs are commutative and associative; the optimizer is free to reorder. So `A JOIN B JOIN C` and `C JOIN A JOIN B` produce the same result, with the same plan, in theory.
>
> **Cross-Q**: When does order matter?
>
> **A**: Three cases. (1) **OUTER joins** are not freely reorderable — `A LEFT JOIN B INNER JOIN C` is **not** equivalent to `A LEFT JOIN (B INNER JOIN C)` if the INNER drops B rows. (2) **You told it not to reorder** — `OPTION (FORCE ORDER)` in SQL Server, or `SET join_collapse_limit = 1` in PostgreSQL, which makes the written join order the executed one. (3) **Optimizer limits** — PostgreSQL documents `join_collapse_limit` and `from_collapse_limit` defaulting to 8 (past which explicit `JOIN` syntax is no longer flattened into a reorderable list) and `geqo_threshold` defaulting to 12 (past which it switches to a genetic search). Beyond those points the order you write starts to matter.
>
> **Cross-Q²**: Best practice for writing a 5-table join?
>
> **A**: Write tables in the order you logically think about them — driving table first, then joins that filter/expand. Most modern optimizers reorder correctly. Verify with EXPLAIN; if the plan is bad, the next step is statistics/indexes, not query rewriting. Only use `FORCE ORDER` after exhausting cheaper fixes — it locks you out of future optimizer improvements.

### Drill 14 — USING vs ON clause

> **Q**: What's the difference between `JOIN orders USING (customer_id)` and `JOIN orders ON c.id = o.customer_id`?
>
> **A**: `USING (col)` requires the join column to have the **same name** in both tables; the result column appears once (not twice) in `SELECT *`. `ON cond` is fully general — different column names, multiple conditions, non-equality, computed predicates. USING is sugar for the common case of "same name, equi-join." **Engine caveat first, though: T-SQL doesn't have `USING` at all.** The documented `FROM` grammar for SQL Server offers `<join_type> JOIN … ON <search_condition>`, `CROSS JOIN`, and `APPLY` — nothing else. PostgreSQL and MySQL support `USING`.
>
> **Cross-Q**: Pros and cons of USING?
>
> **A**: Pros: concise, eliminates duplicate columns in `SELECT *` (no `c.customer_id, o.customer_id` confusion). Cons: only works for equi-joins on identically-named columns, requires schema discipline (FK column must match the PK column name), less portable (some old databases don't support it), and harder to grep for when refactoring. Most teams use ON for clarity in production queries.
>
> **Cross-Q²**: Does USING affect performance?
>
> **A**: No — USING and the equivalent ON compile to the same plan. The difference is purely surface syntax + the duplicate-column suppression in the projection. Performance-wise they're identical; the choice is style.

### Drill 15 — NATURAL JOIN pitfalls

> **Q**: Why do most style guides forbid NATURAL JOIN?
>
> **A**: NATURAL JOIN joins on **every column with a matching name** — automatic and invisible. Add a column with a coincidental name (`created_at` in both tables) and your query silently changes meaning at deploy time, joining on more columns than intended. The bug is undetectable in code review because the SQL didn't change — only the schema did. (SQL Server sidesteps the argument by not implementing `NATURAL JOIN`; PostgreSQL, MySQL and Oracle all do.)
>
> **Cross-Q**: Give me a concrete production failure scenario.
>
> **A**: Day 1: `SELECT * FROM customers NATURAL JOIN orders` joins on `customer_id` (the only shared column). Works. Day 30: someone adds `created_at` to both tables for audit. Now the NATURAL JOIN matches on `customer_id AND created_at`, which is almost never both equal — most rows drop. Reports go silently empty; no error, no schema change to the query, just wrong results. Discovered weeks later when finance reconciles.
>
> **Cross-Q²**: Is NATURAL JOIN ever the right call?
>
> **A**: Rarely — only in tightly-controlled ad-hoc analysis where the analyst owns the schema and knows every shared column is intentional (data warehouse star schemas with strict naming conventions). For application code or shared queries, explicit `ON` or `USING (specific_col)` is mandatory. The cost of typing the column names is negligible; the cost of a silent join-bug at deploy time can be massive.

### Drill 16 — Join elimination

> **Q**: A view joins twelve tables. A query selects three columns from it and the plan shows four operators. What happened to the other joins?
>
> **A**: Join elimination. When no column of a joined table is referenced anywhere in the query, and the engine can prove the join changes no row counts — the other side is unique on the join column, so no duplication, and for an inner join a constraint guarantees the match exists, so no row loss — the join is removed at optimization time. That is what makes wide views usable: you pay for the tables you actually touch.
>
> **Cross-Q**: What would stop it happening?
>
> **A**: Referencing any column of the joined table, including in a predicate or `ORDER BY` — which is why `SELECT *` from that view executes all twelve joins. Losing the uniqueness proof (no unique index or PK on the join column) stops it, because then the join could multiply rows. And on SQL Server, an **untrusted** foreign key stops inner-join elimination, because an unverified constraint proves nothing: `SELECT * FROM sys.foreign_keys WHERE is_not_trusted = 1` finds them, and `ALTER TABLE … WITH CHECK CHECK CONSTRAINT …` revalidates.
>
> **Cross-Q²**: Does PostgreSQL behave the same way?
>
> **A**: Not identically. PostgreSQL removes **LEFT JOINs** where a unique index proves the inner side is unique and none of its columns are used elsewhere — the join-removal feature added in 9.0. It doesn't have SQL Server's foreign-key-driven inner-join elimination, so a design that leans on "the FK makes this join free" is a SQL Server design. The portable version of the advice is the same either way: project only the columns you need, and let the planner decide.

### Drill 17 — The report that blocked production

> **Q**: A four-table reporting join runs at month end and checkout starts timing out. What's the mechanism?
>
> **A**: On SQL Server with `READ_COMMITTED_SNAPSHOT` OFF — the documented default for SQL Server and Azure SQL Managed Instance — `READ COMMITTED` acquires shared locks as it scans. Those are short-lived on their own — the docs say "the row or page locks are released after the row is read" — but a wide scan acquires them faster than it releases them, and Microsoft documents lock escalation triggering when a single statement acquires at least 5,000 locks on one nonpartitioned table or index. Once escalated — and escalation goes directly to a **table** lock, never to a page lock — the report holds that table-level lock **for the rest of the statement**, and every writer queues behind it. (It would survive to commit only at `REPEATABLE READ` or higher, or under `HOLDLOCK`; at read committed an `S` lock is released when the read completes.) Naming that two-stage mechanism, rather than "SELECTs block writers", is the senior answer.
>
> **Cross-Q**: The team adds `WITH (NOLOCK)` everywhere and the blocking stops. What did they just buy?
>
> **A**: Wrong answers, occasionally. `READ UNCOMMITTED` doesn't take shared locks, so besides reading uncommitted data it can miss a row or read it twice: if another transaction changes an index key mid-scan, the row moves ahead of or behind the scan position, and an allocation-order scan can skip rows entirely during a page split. Microsoft's locking guide states both hazards. For a financial report those are the two worst possible failure modes, because the output still looks like a number.
>
> **Cross-Q²**: Would this have happened on PostgreSQL?
>
> **A**: Not this way. PostgreSQL is MVCC — a plain `SELECT` reads a snapshot and takes no row locks, so it can't block writers; the same is true of InnoDB's consistent non-locking reads under its default `REPEATABLE READ`. The cost reappears elsewhere: a long-running report pins an old snapshot, so PostgreSQL's autovacuum can't reclaim dead tuples and InnoDB's undo log keeps growing. And on Azure SQL Database, where `READ_COMMITTED_SNAPSHOT` is ON by default, SQL Server behaves like the versioning engines here — which is exactly why "it works in Azure" tells you nothing about the on-prem instance.

### Drill 18 — The `TOP 1` that runs for minutes

> **Q**: A query is `SELECT TOP 1 ... FROM big_table WHERE status = 'Pending' ORDER BY created_at`. It usually returns instantly and occasionally takes minutes. Same plan both times. What is going on?
>
> **A**: A row goal. `TOP` tells the optimizer to optimise for the first row rather than the whole set, which biases it toward navigational operators — index seeks, lookups, nested loops — over blocking ones like sorts and hashes. To decide how far it will read, it divides the goal by the predicate's selectivity, assuming qualifying rows are spread evenly. When a `Pending` row turns up early, the query stops there. When there are none, the same plan reads to the end of the index to prove it. The negative answer is the slow one.
>
> **Cross-Q**: How do you confirm a row goal from the plan rather than guessing?
>
> **A**: On SQL Server, look for `EstimateRowsWithoutRowGoal` in the showplan XML on the affected operators — it was added by KB4051361 and is present in SQL Server 2014, 2016 and 2017 (CU3 and later) onwards. If it's much larger than `EstimateRows`, a goal scaled the estimate down. On older builds you infer it by comparing the estimate to the table's cardinality. On PostgreSQL there's no such attribute because there's no such named feature — you compare the plan with and without the `LIMIT` and watch it change, which happens because a node's total cost is costed "on the assumption that the plan node is run to completion" while `LIMIT` makes startup cost the term that decides.
>
> **Cross-Q²**: What sets a row goal besides `TOP`, and what do you do about it?
>
> **A**: `FAST n`, `SET ROWCOUNT`, `Top` operators the optimizer adds itself, and semi/anti joins from `IN` and `EXISTS` — Microsoft's list is visible in the hint that turns them off, `OPTION (USE HINT('DISABLE_OPTIMIZER_ROWGOAL'))`, documented for queries containing `TOP`, `OPTION (FAST N)`, `IN` and `EXISTS`. Reach for that hint last. The real fix is an index that makes proving absence cheap: if the predicate is `status = 'Pending'`, a filtered/partial index on that status turns "no rows" into a seek that ends immediately instead of a scan that ends at the end of the table.

### Drill 19 — "All of", not "any of"

> **Q**: "Find customers who have bought every product in the Core line." Write it.
>
> **A**: Relational division. Two standard forms. Double `NOT EXISTS` — "there is no Core product this customer failed to buy": `WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.product_line='Core' AND NOT EXISTS (SELECT 1 FROM orders o JOIN order_items oi ON oi.order_id=o.id WHERE o.customer_id=c.id AND oi.product_id=p.id))`. Or count and compare: join through to Core products only, `GROUP BY customer`, `HAVING COUNT(DISTINCT oi.product_id) = (SELECT COUNT(*) FROM products WHERE product_line='Core')`.
>
> **Cross-Q**: In the counting form, why `COUNT(DISTINCT oi.product_id)` and not `COUNT(*)`?
>
> **A**: Because the grain is line items, not products. A customer who bought the same product on four separate orders contributes four rows, so `COUNT(*)` reaches four without them owning four products. The same reasoning says the `product_line = 'Core'` filter has to be on the join and not only inside the scalar subquery — otherwise you are counting distinct products of any kind against the size of the Core range.
>
> **Cross-Q²**: Do the two forms always return the same rows?
>
> **A**: No, and the divergence is the interesting part. If the Core line is empty, the double-`NOT EXISTS` form returns every customer — "there is no Core product they failed to buy" is vacuously true of everyone — while the counting form returns nobody, because a customer with no Core purchases produces no group for `HAVING` to test. Neither is wrong; they answer marginally different questions, so decide which the requirement means and test the empty-divisor case explicitly.

### Drill 20 — Cartesian explosion in EF Core

> **Q**: An endpoint does `.Include(o => o.Items).Include(o => o.StatusHistory)` on `Order` and gets slow as data grows. What's the SQL doing?
>
> **A**: Both are collection navigations off the same root, so EF Core emits two `LEFT JOIN`s off `Orders` and the database returns their cross product per order — the EF Core docs call it cartesian explosion and give the arithmetic: "if a given blog has 10 posts and 10 contributors, the database returns 100 rows for that single blog." It's the fan-out problem from the join section, arriving through an ORM. Nested includes don't do this: `.Include(o => o.Items).ThenInclude(i => i.Adjustments)` is a chain, not a pair of siblings, and yields one row per leaf.
>
> **Cross-Q**: `AsSplitQuery()` fixes it. What did you just trade away?
>
> **A**: Four documented things. Cross-statement consistency — "while most databases guarantee data consistency for single queries, no such guarantees exist for multiple queries", so a concurrent write between statements gives a torn graph unless you wrap them in a serializable or snapshot transaction. A network roundtrip per collection. Buffering, because most providers allow only one active query per connection, so earlier results sit in application memory (SQL Server with MARS and SQLite are the exceptions the docs name). And reference navigations get joined into *every* split query. Also, on EF versions before 10, combining split queries with `Skip`/`Take` requires a fully unique ordering, or the separate statements can page differently.
>
> **Cross-Q²**: The root table has a big `varbinary` column and you only `Include` one collection. Is split query the answer there too?
>
> **A**: Not usually — that's the data-duplication problem, not cartesian explosion, and the docs are clear it "isn't typically significant" unless the principal table has big columns. One `LEFT JOIN` repeats every root column on every child row, so a large blob goes over the wire once per child. The cheaper fix is a projection that just doesn't select the column. The cost of that is losing change tracking, since you've projected to an anonymous type rather than materialising the entity.

### Drill 21 — The hint that did two things

> **Q**: A colleague fixes a spilling hash join by writing `INNER HASH JOIN` on that one pair of tables in a seven-table query. What else did they change?
>
> **A**: The join order of the entire query. Microsoft's join-hints reference: "If a join hint is specified for any two tables, the query optimizer automatically enforces the join order for all joined tables in the query, based on the position of the `ON` keywords." One hint on one pair is an implicit `OPTION (FORCE ORDER)` over all seven tables, so the optimizer can no longer reorder as statistics and predicates change. The query is now hand-planned, permanently, by someone who only meant to change one operator.
>
> **Cross-Q**: Does forcing the order also fix which side of a hash join is the build input?
>
> **A**: No. The query-hints reference notes that `FORCE ORDER` "doesn't affect possible role reversal behavior of the Query Optimizer". Roles are assigned so the smaller input builds, and if the estimate was wrong the engine swaps them at runtime — "after at least one spill to the disk", and invisibly: "role reversal doesn't display in your query plan". So the plan you're reading may not describe what executed, and forcing order gives you no control over it.
>
> **Cross-Q²**: What should they have done about the spill instead?
>
> **A**: Treated it as an estimate problem. A spill means the build input was bigger than the memory grant, and the grant came from an estimate. Microsoft's own remediation for hash warnings is "update statistics on the columns that are being joined" — not a memory setting. After that, reduce what's being hashed: filter earlier, project fewer columns, index the join key so a seek replaces a scan. If a plan genuinely has to be pinned, Query Store plan forcing pins it visibly rather than a hint in the `FROM` clause changing two things at once.

</details>

## Cheat Sheet

- **INNER JOIN**: rows present in both sides; the default and most common.
- **LEFT JOIN**: all left rows + matching right (NULL where no match); use for "with optional".
- **CROSS JOIN**: Cartesian; only intentional - usually for date series, calendar tables, combinatorics.
- **SELF JOIN**: alias the table twice; org charts, peer comparisons, hierarchical 1-2 levels.
- **Anti-join**: `LEFT JOIN ... WHERE r.id IS NULL` or `NOT EXISTS`; both are NULL-safe and normally compile to the same anti-join, so prefer `NOT EXISTS` for clarity.
- **Semi-join**: `EXISTS (...)`; short-circuits on first match instead of materialising every match and deduping, which is what `INNER JOIN + DISTINCT` does.
- **NOT IN with NULL**: returns zero rows if the subquery yields any NULL; prefer `NOT EXISTS`.
- **Filter in ON vs WHERE**: in LEFT JOIN, ON keeps unmatched left rows; WHERE on right columns drops them.
- **UNION ALL > UNION**: skip dedup work when duplicates are impossible or acceptable.
- **Multiplying rows**: chained 1:N:N joins explode result count; aggregate in subqueries before joining.
- **Grain check**: after joining 1:N, one row is no longer one order — any aggregate over parent columns is now counted once per child.
- **NULL keys never match**, not even NULL to NULL; set operators are the opposite and treat two NULLs as duplicates.
- **NULL-safe equality**: `IS NOT DISTINCT FROM` (PostgreSQL; SQL Server 2022+), `<=>` (MySQL) — check the plan, they may not seek.
- **Join elimination**: unreferenced join + uniqueness (+ trusted FK on SQL Server) = removed at compile time; `SELECT *` disables it.
- **Engine gaps to name in an interview**: MySQL has no `FULL OUTER JOIN`; T-SQL has no `USING`, no `NATURAL JOIN`, no `INTERSECT ALL`/`EXCEPT ALL`; MySQL got `INTERSECT`/`EXCEPT` in 8.0.31.
- **Set-op precedence**: `INTERSECT` first, then `UNION`/`EXCEPT` left to right; one trailing `ORDER BY` for the whole expression.
- **Locking**: on SQL Server with RCSI OFF (on-prem default) a big report takes shared locks row by row (released after each read) and can escalate at 5,000 locks to one table lock — never a page lock — held for the rest of the statement; PostgreSQL/InnoDB read a snapshot instead.
- **Division ("all of")**: double `NOT EXISTS`, or `COUNT(DISTINCT x) = (SELECT COUNT(*) …)`. `IN` and `EXISTS` only ever answer "any".
- **Row goal**: `TOP`, `FAST n`, `IN`, `EXISTS` bias the plan toward stopping early; the negative answer is the expensive one.
- **Hash join**: smaller side builds and blocks; in-memory → grace → recursive; role reversal after a spill, invisible in the plan. Spill ⇒ update statistics, not more RAM.
- **Merge join**: needs equality predicates and sorted inputs; many-to-many merge uses a temporary table to rewind duplicates.
- **`OR` across two indexes** can't seek — rewrite as a `UNION` of two seekable branches (or check whether the engine already built an index-union plan).
- **SQL Server join hints force join order for the whole query**; `FORCE ORDER` does not control build/probe role reversal.
- **EF Core**: sibling collection `Include`s = cartesian explosion → `AsSplitQuery()`, at the cost of cross-statement consistency; TPT means joins, TPH means none.

## Walkthrough — LEFT JOIN silently becoming INNER JOIN

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A "customers and their last 30 days of orders" report should list all customers, but only customers who placed orders show up. The query has a LEFT JOIN, so the team is confused.

**Diagnosis**: Senior runs `EXPLAIN ANALYZE` and sees a Hash Join (Inner) where they expected Hash Left Join. The query was:

```sql
SELECT c.id, c.name, o.id AS order_id, o.total
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.created_at >= NOW() - INTERVAL '30 days';
```

The predicate `o.created_at >= ...` references the right table in WHERE. For customers with no orders, `o.created_at` is NULL, and `NULL >= ...` is NULL (falsy), so those rows are dropped. The optimiser even rewrites the LEFT JOIN to INNER JOIN automatically because the WHERE predicate makes outer rows impossible.

**Fix**: Move the predicate into the ON clause:

```sql
SELECT c.id, c.name, o.id AS order_id, o.total
FROM customers c
LEFT JOIN orders o
    ON o.customer_id = c.id
    AND o.created_at >= NOW() - INTERVAL '30 days'
ORDER BY c.id;
```

Now customers with no recent orders return one row with NULL order columns, exactly as intended. The verification is an assertion, not an eyeball: `SELECT COUNT(DISTINCT c.id)` over the fixed query must equal `SELECT COUNT(*) FROM customers`. If it doesn't, a predicate is still dropping left rows somewhere.

**Why it works**: Predicates in ON are evaluated *during* the join and don't disqualify left-side rows. Predicates in WHERE are evaluated after the join produces NULL-padded outer rows, which fail any comparison with the NULL columns.

</details>

## Self-test

<details><summary>1. <code>SELECT DISTINCT c.id FROM customers c JOIN orders o ON ...</code> returns the right values but is slow. Why and what's the fix?</summary>

DISTINCT runs after the join materialises every matching pair, then sorts/hashes to dedupe. For a customer with 1000 orders, you produce 1000 rows then drop 999. Replace with `WHERE EXISTS (SELECT 1 FROM orders ...)` (semi-join) which short-circuits at the first match.
</details>

<details><summary>2. Trade-off: <code>NOT EXISTS</code> vs <code>EXCEPT</code> for "rows in A not in B".</summary>

`NOT EXISTS` is row-by-row anti-join, supports correlated predicates, NULL-safe. `EXCEPT` is a set operator, requires identical column shapes, deduplicates the result automatically. EXCEPT is concise for full-row comparisons; NOT EXISTS is more flexible for partial/correlated checks.
</details>

<details><summary>3. Why does <code>JOIN ON int_col = varchar_col</code> wreck performance even with both columns indexed?</summary>

Type mismatch forces an implicit conversion at every row. The conversion wraps the indexed column in a function, so a seek on that index is no longer possible -> scan on the side that gets converted. Which side that is isn't arbitrary: SQL Server's documented data type precedence decides it, and `int` outranks `varchar`, so the `varchar` column is the one converted. The same rule explains the .NET version of this bug - `nvarchar` outranks `varchar`, so a `string` parameter sent as `nvarchar` against a `varchar` column converts the column. Fix the schema or the parameter type; never wrap the column in `CAST` to make the error go away.
</details>

<details><summary>4. <code>UNION</code> vs <code>UNION ALL</code> on a query joining a 100M-row table to itself.</summary>

UNION dedupes via sort or hash over the combined rowset - every row of both inputs has to be processed by a blocking operator before the first row comes out. UNION ALL just concatenates the streams. If you can prove duplicates are impossible (e.g., the branches cover disjoint date partitions), UNION ALL removes that operator entirely. The "always UNION just in case" habit pays for a dedup nobody needs on every execution.
</details>

<details><summary>5. You join orders -> order_items -> products and SUM(quantity) is double the real number. What happened?</summary>

Start by noticing that the chain as described can't do it on its own. `orders -> order_items` changes the grain to one row per item, which is exactly the grain `SUM(quantity)` wants, and `order_items -> products` is N:1, so it adds no rows — unless `products` has more than one row per `product_id`, which is worth checking before anything else.

Doubling means a **second 1:N branch off the same parent** that the question didn't mention: a `payments`, `shipments` or `order_status_history` join. Two children of `orders` multiply against each other, so each item row repeats once per payment row and `SUM(quantity)` comes back multiplied by the payment count.

The fix is to pre-aggregate each branch to one row per order in its own CTE (or `APPLY`) before joining. What does **not** work is `SUM(DISTINCT quantity)`: `DISTINCT` inside an aggregate deduplicates *values*, not rows, so three items that each have `quantity = 2` collapse to a single 2 and the answer is now wrong in the other direction. It gives a plausible number for the same reason the bug did.
</details>

<details><summary>6. A query says <code>LEFT JOIN</code>; the plan says <code>Hash Join (Inner)</code>. Is the optimizer wrong?</summary>

No - it proved your query means an inner join. A predicate on the right table in `WHERE` that can't be TRUE when its input is NULL (null-rejecting) makes every NULL-extended row fail the filter, so the outer join can't produce anything the inner join wouldn't. PostgreSQL does this as an outer-join reduction during planning; SQL Server applies the same simplification. If you wanted unmatched left rows, move the predicate into `ON`. Note `IS NULL` is not null-rejecting, which is why `LEFT JOIN ... WHERE r.id IS NULL` survives the rewrite and remains an anti-join.
</details>

<details><summary>7. Why does <code>SELECT *</code> from a twelve-table view cost more than selecting three columns from it?</summary>

Join elimination. If nothing in the query references a joined table's columns, and the engine can prove the join can't change row counts (uniqueness on the join column against duplication; on SQL Server, a trusted foreign key against row loss for inner joins), the join is removed at compile time. `SELECT *` references every column, so nothing can be eliminated and all twelve joins execute. PostgreSQL does the LEFT JOIN case using a unique index; it has no FK-driven inner-join elimination.
</details>

<details><summary>8. Your bulk-load runbook disables foreign keys and re-enables them with <code>ALTER TABLE ... CHECK CONSTRAINT ...</code>. What breaks later?</summary>

Nothing breaks correctness - the constraint is enforced for new rows - but it comes back **untrusted**, because re-enabling doesn't revalidate existing data. The optimizer stops using it, so FK-dependent optimizations such as join elimination disappear and plans get more expensive with no code change. Find them with `SELECT * FROM sys.foreign_keys WHERE is_not_trusted = 1` and repair with `ALTER TABLE t WITH CHECK CHECK CONSTRAINT fk;` (SQL Server).
</details>

<details><summary>9. <code>SELECT NULL INTERSECT SELECT NULL</code> returns a row, but <code>ON a.x = b.x</code> with two NULLs matches nothing. Why the difference, and what's it good for?</summary>

Comparison uses three-valued logic - `NULL = NULL` is UNKNOWN, so the join predicate isn't TRUE and no row is produced. Set operators use *distinctness* instead: Microsoft's EXCEPT/INTERSECT reference says "when comparing column values for determining DISTINCT rows, two NULL values are considered equal", and PostgreSQL dedupes "in the same way as DISTINCT", which has the same behaviour. The practical use is a NULL-safe comparison on engines without one: `EXISTS (SELECT a.c1, a.c2 INTERSECT SELECT b.c1, b.c2)` is TRUE when the column lists match, NULLs included.
</details>

<details><summary>10. Which of these are portable: <code>FULL OUTER JOIN</code>, <code>USING (id)</code>, <code>NATURAL JOIN</code>, <code>EXCEPT ALL</code>?</summary>

None of them. MySQL has no `FULL OUTER JOIN` (emulate with `LEFT JOIN` UNION ALL the right-only anti-join half). T-SQL's `FROM` grammar has neither `USING` nor `NATURAL JOIN` - only `ON`, `CROSS JOIN` and `APPLY`. `EXCEPT ALL`/`INTERSECT ALL` exist in PostgreSQL and in MySQL 8.0.31+, but the documented T-SQL syntax is `{ EXCEPT | INTERSECT }` with no `ALL` form; MySQL didn't have `INTERSECT`/`EXCEPT` at all before 8.0.31. Portable across all three: `INNER`/`LEFT`/`RIGHT JOIN ... ON`, `CROSS JOIN`, `UNION`, `UNION ALL`, `EXISTS`/`NOT EXISTS`.
</details>

<details><summary>11. A month-end report joining four tables makes checkout time out on SQL Server, but the identical query on PostgreSQL doesn't. Why?</summary>

Isolation implementation, not query difference. SQL Server's default `READ COMMITTED` with `READ_COMMITTED_SNAPSHOT` OFF (the on-prem default) takes shared locks while scanning - each released once its row is read, so on its own that only blocks a writer momentarily - but Microsoft documents lock escalation at 5,000 or more locks on a single nonpartitioned table or index in one statement, escalating straight to a table lock (never a page lock), and that escalated table lock is held for the rest of the statement, which is what makes writers block for the length of the report. PostgreSQL is MVCC: a plain `SELECT` reads a snapshot, takes no row locks, and can't block writers; it delays vacuuming instead. Azure SQL Database defaults `READ_COMMITTED_SNAPSHOT` to ON, so it behaves like the versioning engines. Fixes in order: narrow the query, enable RCSI, move the read to a replica.
</details>

<details><summary>12. "Users who hold <em>all</em> of the required permissions" is written as <code>EXISTS (SELECT 1 FROM user_permissions WHERE code IN (...))</code>. What's wrong, and what are the two correct forms?</summary>

`IN` and `EXISTS` answer *any*, so anyone holding one permission from the list passes. The requirement is relational division. Form 1 - double `NOT EXISTS`: "there is no required permission that this user does not hold". Form 2 - counting: join to the required set, `GROUP BY user`, `HAVING COUNT(DISTINCT permission_code) = (SELECT COUNT(*) FROM required_permissions)`. `COUNT(DISTINCT ...)` matters because one user can hold the same permission through two roles, and `COUNT(*)` would count grants rather than permissions. The two forms disagree on an empty divisor: with no required permissions the `NOT EXISTS` form returns everyone (vacuously true) and the counting form returns nobody (no group to test).
</details>

<details><summary>13. Same plan, same estimates, one execution instant and one takes minutes. The query starts <code>SELECT TOP 1</code>. Explain.</summary>

A row goal. `TOP` (also `FAST n`, `SET ROWCOUNT`, `IN`, `EXISTS`) makes the optimizer plan for "first row fast", biasing toward seeks, lookups and nested loops over sorts and hashes. It sizes the read by dividing the goal by the predicate's selectivity, which assumes matching rows are spread evenly. A match found early ends the query; no match at all means reading the whole range to prove a negative. Confirm it with the `EstimateRowsWithoutRowGoal` showplan attribute (SQL Server 2014/2016/2017 via KB4051361, 2017 CU3+) - much larger than `EstimateRows` means a goal scaled the estimate down. `OPTION (USE HINT('DISABLE_OPTIMIZER_ROWGOAL'))` exists, but an index that makes the empty case a terminating seek is the better fix. PostgreSQL has no feature by that name; `LIMIT` produces the same behaviour through startup-cost-versus-total-cost planning.
</details>

<details><summary>14. Your hash join spilled. Why is "give the server more memory" the wrong first move, and what does role reversal have to do with it?</summary>

The memory grant is derived from a cardinality estimate, so a spill usually means the estimate was wrong, not that the box is small - Microsoft's guidance for repeated hash warnings is to update statistics on the joined columns. The engine already degrades gracefully: in-memory hash join, then grace hash join (both inputs partitioned to files by the hash key so joining rows land in the same file pair), then recursive hash join. Role reversal is the part you can't see: if the optimizer picked the wrong side to build, the engine swaps build and probe at runtime, but only "after at least one spill to the disk", and it "doesn't display in your query plan". So the plan may not describe what ran, and `OPTION (FORCE ORDER)` doesn't control it either - the query-hints reference says forcing order "doesn't affect possible role reversal behavior". On PostgreSQL the same condition shows as `Batches: N` above 1 on a `Hash` node, with the budget being `work_mem` x `hash_mem_multiplier` (defaults 4MB and 2.0).
</details>

<details><summary>15. A LINQ query with <code>.Include(o =&gt; o.Items).Include(o =&gt; o.Tags)</code> returns far more rows than expected. Which SQL problem is this, and what is the .NET fix and its cost?</summary>

Fan-out, under EF Core's name for it: cartesian explosion. Two collection navigations at the same level become two `LEFT JOIN`s off one root, so the database returns their cross product per root row - the docs' example is 10 posts x 10 contributors = 100 rows for one blog. Nested includes (`Include(...).ThenInclude(...)`) don't do this because they're a chain, not siblings. The fix is `AsSplitQuery()` (EF Core 5.0+), or `UseQuerySplittingBehavior(QuerySplittingBehavior.SplitQuery)` context-wide with `AsSingleQuery()` to opt out. Documented costs: no data-consistency guarantee across the separate statements (mitigate with a serializable or snapshot transaction), one roundtrip per collection, buffering of earlier results in application memory unless the provider supports concurrent readers, reference navigations joined into every split query, and - before EF 10 - a requirement that ordering be fully unique when combined with `Skip`/`Take`.
</details>

## Cross-references

- [Fundamentals](./01-fundamentals.md) — basic SELECT, WHERE, ORDER BY.
- [Aggregation & Grouping](./03-aggregation-and-grouping.md) — combine joins with GROUP BY.
- [Subqueries & CTEs](./04-subqueries-and-ctes.md) — `EXISTS`, correlated subqueries.
- [Window Functions](./05-window-functions.md) — `ROW_NUMBER` for de-dupe alternatives to DISTINCT.
- [Indexes & Query Optimization](./06-indexes-and-query-optimization.md) — index strategy for JOIN keys.
- [Searching Algorithms](../../01-foundations/04-searching-algorithms.md) — joins are conceptually like merging sorted streams.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *SQL Cookbook* by Anthony Molinaro (O'Reilly, 2nd ed.) — every join pattern with examples.
- *Joe Celko's SQL for Smarties* — advanced join patterns; classic.
- PostgreSQL docs — [Joined Tables chapter](https://www.postgresql.org/docs/current/queries-table-expressions.html#QUERIES-FROM).
- LeetCode SQL Easy/Medium problems on joins — drill the patterns.

Used for the engine-specific claims on this page:

- Microsoft Learn — [FROM clause plus JOIN, APPLY, PIVOT (T-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/from-transact-sql): the join grammar (no `USING`, no `NATURAL JOIN`), join hints, and "predicates in the ON clause are applied to the table before the join, whereas the WHERE clause is semantically applied to the result of the join".
- Microsoft Learn — [EXCEPT and INTERSECT (T-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/set-operators-except-and-intersect-transact-sql): no `ALL` variants; "two NULL values are considered equal"; precedence (parentheses → INTERSECT → EXCEPT/UNION left to right); `EXCEPT` shows as a left anti semi join, `INTERSECT` as a left semi join.
- Microsoft Learn — [IS \[NOT\] DISTINCT FROM (T-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/is-distinct-from-transact-sql): SQL Server 2022 (16.x) and later, Azure SQL Database; usable in join conditions.
- Microsoft Learn — [Transaction locking and row versioning guide](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-transaction-locking-and-row-versioning-guide): lock escalation at ≥5,000 locks on one nonpartitioned table/index (retry every 1,250); `READ_COMMITTED_SNAPSHOT` OFF by default in SQL Server and Azure SQL Managed Instance, ON by default in Azure SQL Database; the missing-row / duplicate-row hazards of `READ UNCOMMITTED`.
- Microsoft Learn — [Data type precedence (T-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/data-types/data-type-precedence-transact-sql): `nvarchar` outranks `varchar`, so the `varchar` column is the side that gets converted.
- PostgreSQL docs — [Combining queries](https://www.postgresql.org/docs/current/queries-union.html): "Without parentheses, `UNION` and `EXCEPT` associate left-to-right, but `INTERSECT` binds more tightly than those two operators"; `ALL` variants.
- PostgreSQL docs — [Query Planning (runtime configuration)](https://www.postgresql.org/docs/current/runtime-config-query.html): `join_collapse_limit` and `from_collapse_limit` default 8, `geqo_threshold` default 12, `enable_hashjoin`/`enable_mergejoin`/`enable_nestloop`.
- Robert Haas — [*Why Join Removal Is Cool*](http://rhaas.blogspot.com/2010/06/why-join-removal-is-cool.html): the three conditions for PostgreSQL 9.0 LEFT JOIN removal.
- Bert Wagner — [*Join Elimination: When SQL Server Removes Unnecessary Tables*](https://sqlperformance.com/2018/06/sql-performance/join-elimination-unnecessary-tables) (SQLPerformance.com, June 2018).
- MySQL 8.0 Reference Manual — [Hash join optimization](https://dev.mysql.com/doc/refman/8.0/en/hash-joins.html) (hash join from 8.0.18; block nested loop removed in 8.0.20; hash antijoin/semijoin) and [Set operations with UNION, INTERSECT, and EXCEPT](https://dev.mysql.com/doc/refman/8.0/en/set-operations.html) (`INTERSECT`/`EXCEPT` added in 8.0.31).
- MySQL worklog [WL#1604 — Support FULL \[OUTER\] JOIN by rewriting with UNION](https://dev.mysql.com/worklog/task/?id=1604): still not implemented, which is why MySQL has no `FULL OUTER JOIN`.
- Microsoft Learn — [Join hints (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/hints-transact-sql-join): the hint list (`LOOP`/`HASH`/`MERGE`/`REMOTE`; `REDUCE` and `REDISTRIBUTE` documented for Azure Synapse Analytics and Analytics Platform System, `REPLICATE` and `REDISTRIBUTE` also for Fabric Warehouse), "`LOOP` can't be specified together with `RIGHT` or `FULL` as a join type", and the Remarks sentence that a join hint on any two tables enforces join order for all joined tables.
- Microsoft Learn — [Query hints (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/hints-transact-sql-query): `{ MERGE | HASH | CONCAT } UNION`; only the last query of a `UNION` may carry the `OPTION` clause; `FORCE ORDER` "doesn't affect possible role reversal behavior of the Query Optimizer"; `USE HINT('DISABLE_OPTIMIZER_ROWGOAL')` and the `TOP`/`FAST N`/`IN`/`EXISTS` keyword list it applies to.
- Microsoft Learn — [Joins (SQL Server)](https://learn.microsoft.com/en-us/sql/relational-databases/performance/joins): build versus probe input, in-memory → grace → recursive hash join, hash bailout, role reversal after a spill and invisible in the plan, "update statistics on the columns that are being joined" for repeated hash warnings, merge join requiring sorted inputs and equality clauses, and the many-to-many merge join's temporary table.
- Paul White — [*Setting and Identifying Row Goals in Execution Plans*](https://sqlperformance.com/2018/02/sql-plan/setting-and-identifying-row-goals) (SQLPerformance.com, 2018): what sets a row goal, the bias toward "non-blocking navigational operations ... over blocking, set-based operations like sorting and hashing", and the `EstimateRowsWithoutRowGoal` showplan attribute added by KB4051361.
- PostgreSQL docs — [Resource consumption](https://www.postgresql.org/docs/current/runtime-config-resource.html): `work_mem` default 4MB, `hash_mem_multiplier` default 2.0, and "the final limit is determined by multiplying `work_mem` by `hash_mem_multiplier`".
- PostgreSQL docs — [Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html): total cost "stated on the assumption that the plan node is run to completion", and the worked `LIMIT` example where the planner changes plan.
- PostgreSQL docs — [CREATE STATISTICS](https://www.postgresql.org/docs/current/sql-createstatistics.html): extended statistics syntax and the `ndistinct` / `dependencies` / `mcv` kinds. Compare Microsoft Learn — [CREATE STATISTICS (T-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/statements/create-statistics-transact-sql): "Only the first column is used for creating the histogram. All columns are used for cross-column correlation statistics called densities."
- MySQL 8.0 Reference Manual — [Optimizer hints](https://dev.mysql.com/doc/refman/8.0/en/optimizer-hints.html) (`JOIN_FIXED_ORDER` = `SELECT STRAIGHT_JOIN`, `JOIN_ORDER`/`JOIN_PREFIX`/`JOIN_SUFFIX`; `HASH_JOIN`/`NO_HASH_JOIN` in 8.0.18 only, `BNL`/`NO_BNL` thereafter) and [ANALYZE TABLE](https://dev.mysql.com/doc/refman/8.0/en/analyze-table.html) (`UPDATE HISTOGRAM ON col [, col] ... [WITH N BUCKETS]` builds one independent per-column histogram each, never a multivariate one — the statements "affect only the named columns").
- Microsoft Learn — [Single vs. split queries (EF Core)](https://learn.microsoft.com/en-us/ef/core/querying/single-split-queries): cartesian explosion and the 10 × 10 = 100 rows example, `AsSplitQuery`/`AsSingleQuery`/`UseQuerySplittingBehavior`, and the four documented drawbacks of split queries.
- Microsoft Learn — [Complex query operators (EF Core)](https://learn.microsoft.com/en-us/ef/core/querying/complex-query-operators): the `SelectMany` → `CROSS JOIN`/`INNER JOIN`/`LEFT JOIN`/`CROSS APPLY`/`OUTER APPLY` mapping table, and why `GroupJoin` isn't translated except in the GroupJoin + `DefaultIfEmpty` + `SelectMany` left-join pattern.
- Microsoft Learn — [Modeling for performance (EF Core)](https://learn.microsoft.com/en-us/ef/core/performance/modeling-for-performance): "TPT queries must join together multiple tables", and the published 7-type / 35,000-row inheritance benchmark (TPH 149.0 ms, TPT 312.9 ms, TPC 158.2 ms) with its own caveat that results depend on the query and the number of tables.

<!-- nav-footer-start -->

---

[← Previous: SQL Fundamentals](01-fundamentals.md) · [↑ Back to top](#joins--set-operations) · [Next: SQL Joins — Deep Dive →](02-joins-deep-dive.md)

<!-- nav-footer-end -->

</details>
