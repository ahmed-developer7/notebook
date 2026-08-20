# Aggregation & Grouping

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › [SQL Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-08-11 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Aggregate functions](#aggregate-functions)
  - [GROUP BY mechanics](#group-by-mechanics)
  - [HAVING — filtering groups](#having--filtering-groups)
  - [DISTINCT inside aggregates](#distinct-inside-aggregates)
  - [String aggregation (STRING_AGG / GROUP_CONCAT)](#string-aggregation-string_agg--group_concat)
  - [Conditional aggregation (CASE inside aggregate)](#conditional-aggregation-case-inside-aggregate)
  - [ROLLUP, CUBE, GROUPING SETS](#rollup-cube-grouping-sets)
  - [How the engine groups — hash vs sort](#how-the-engine-groups--hash-vs-sort)
  - [When the estimate is wrong — spills and memory grants](#when-the-estimate-is-wrong--spills-and-memory-grants)
  - [Indexing for GROUP BY](#indexing-for-group-by)
  - [The zero-row trap — aggregates over an empty set](#the-zero-row-trap--aggregates-over-an-empty-set)
  - [Aggregation under concurrency](#aggregation-under-concurrency)
  - [Pre-aggregation — summary tables, indexed views, materialized views](#pre-aggregation--summary-tables-indexed-views-materialized-views)
  - [Approximate distinct counts](#approximate-distinct-counts)
  - [Which aggregates roll up — distributive, algebraic, holistic](#which-aggregates-roll-up--distributive-algebraic-holistic)
  - [The grouping key is a comparison — collation, case, NULLs](#the-grouping-key-is-a-comparison--collation-case-nulls)
  - [Ordering, limiting, and Top-N over groups](#ordering-limiting-and-top-n-over-groups)
  - [Aggregating from .NET — what EF Core actually sends](#aggregating-from-net--what-ef-core-actually-sends)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--double-counted-revenue-from-a-bad-join-shape)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Aggregations turn raw data into insights. "How many orders this month?" is `COUNT`. "Total revenue per customer?" is `SUM` + `GROUP BY`. "Customers who spent more than $10k last year?" is `SUM` + `GROUP BY` + `HAVING`. Every reporting query, dashboard, and metric is an aggregation.

For interviews, GROUP BY questions are second only to joins in frequency. The bar isn't "I can count rows" — it's "I can write a query producing the per-customer running totals with averages, distinct counts, and conditional sums in one pass." The patterns below cover that bar.

When NOT to aggregate: row-level operations (filters, joins) come first; aggregate only when you need group-level results. Don't pre-aggregate "just in case" — aggregations cost CPU.

## Core concepts

### Aggregate functions

The standard set:

| Function | Returns | Notes |
|---|---|---|
| `COUNT(*)` | row count | counts rows including NULLs |
| `COUNT(col)` | count of non-NULL values | NULLs excluded |
| `COUNT(DISTINCT col)` | unique non-NULL count | costs a sort/hash |
| `SUM(col)` | total | NULLs ignored; result is NULL if all input NULL |
| `AVG(col)` | mean | NULLs ignored |
| `MIN(col)` / `MAX(col)` | extremes | works on numbers, dates, strings |
| `STRING_AGG(col, sep)` | concatenated string | PostgreSQL; SQL Server 2017+ — ordering syntax differs, see below |
| `GROUP_CONCAT(col SEPARATOR sep)` | same | MySQL |
| `STDDEV` / `VAR_SAMP` | statistical | population vs sample variants per dialect |
| `BIT_AND` / `BIT_OR` | bitwise | rare |

```sql
SELECT
    COUNT(*) AS total_orders,
    COUNT(DISTINCT customer_id) AS unique_customers,
    SUM(total) AS total_revenue,
    AVG(total) AS avg_order_value,
    MIN(created_at) AS first_order,
    MAX(created_at) AS latest_order
FROM orders;
```

`COUNT(*)` vs `COUNT(col)`:
- `COUNT(*)` is "how many rows?" — the cheapest of the three, but not free, and no MVCC engine answers it from a stored counter. PostgreSQL and InnoDB have to decide, row by row, whether each version is visible to *your* snapshot: PostgreSQL consults the heap, or the visibility map when the plan is an index-only scan; InnoDB checks the record's transaction id and follows the undo log where the row has been modified. SQL Server scans the narrowest index that covers the table, and only pays a version-chain cost when row versioning is switched on (`READ_COMMITTED_SNAPSHOT`, `SNAPSHOT`). (The historical exception is MySQL's MyISAM, which keeps an exact row count in the table header and answers an unfiltered `COUNT(*)` from it — one of the few things it does better than InnoDB, and not a reason to use it.) "Fast" means "no per-value work", not "constant time".
- `COUNT(col)` skips rows where `col` is NULL.
- `COUNT(DISTINCT col)` adds dedup cost — a sort or a hash table over the values. Careful with the usual "equivalent" rewrite: `SELECT COUNT(*) FROM (SELECT DISTINCT col FROM t) s` counts NULL as one distinct value; `COUNT(DISTINCT col)` does not. The honest equivalent adds `WHERE col IS NOT NULL`.

If a number is for a dashboard rather than an invoice, ask the catalog instead of the table. PostgreSQL keeps `pg_class.reltuples` — the docs describe it as "Number of live rows in the table. This is only an estimate used by the planner. It is updated by `VACUUM`, `ANALYZE`, and a few DDL commands such as `CREATE INDEX`. If the table has never yet been vacuumed or analyzed, `reltuples` contains `-1` indicating that the row count is unknown." SQL Server exposes `sys.dm_db_partition_stats.row_count`, documented as "The approximate number of rows in the partition" — sum it across `index_id IN (0, 1)` for a whole table.

> 🌍 **In the real world**: an admin screen shows "Orders: N" from `SELECT COUNT(*) FROM orders` and it is instant for two years. Then the table crosses a few hundred million rows and the page starts timing out at 30 seconds, because on PostgreSQL that count reads every visible row — an index-only scan over the narrowest index will cut the I/O when the visibility map is set, but it still touches one entry per row, so the cost tracks the table size and no index makes it constant. The team splits the requirement in two: the header badge reads `reltuples` from `pg_class` and says "≈", while the month-end reconciliation keeps the exact `COUNT(*)` and runs on the reporting replica where nobody is waiting on a page render. The lesson is not "counting is slow" — it is that "exact" was never a requirement of the header badge, and nobody had asked.

`COUNT` also has a return type. In SQL Server `COUNT` returns **int** and overflows past 2,147,483,647 with `Msg 8115, Arithmetic overflow error converting expression to data type int` — the docs say to use `COUNT_BIG` for those results. PostgreSQL's `count()` returns **bigint** already, so the problem never appears there.

### GROUP BY mechanics

`GROUP BY` collapses rows that share the same values for the group columns into a single output row.

```sql
SELECT customer_id, COUNT(*) AS order_count, SUM(total) AS total_spent
FROM orders
GROUP BY customer_id;
```

For each unique `customer_id`, you get one row. `COUNT(*)` is the count of orders for that customer; `SUM(total)` is their total spend.

**The "all non-aggregated columns must be in GROUP BY" rule:**

```sql
-- ✅ Valid
SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id;

-- ❌ Invalid (in standard SQL and most dialects)
SELECT customer_id, name, COUNT(*) FROM orders GROUP BY customer_id;
-- Error: "name" is neither aggregated nor in GROUP BY.
```

Exception: PostgreSQL and MySQL allow `name` if it's *functionally dependent* on the GROUP BY columns — that is, if `customer_id` determines `name`, so one `customer_id` can only mean one `name`. This is optional feature T301 of SQL:1999, and the two engines detect it to different depths: PostgreSQL's docs say it "recognizes functional dependency (allowing columns to be omitted from `GROUP BY`) only when a table's primary key is included in the `GROUP BY` list", while MySQL also accepts a `UNIQUE NOT NULL` key and chains dependencies through joins. **SQL Server does not implement it at all**: it rejects the query with error 8120, "Column ... is invalid in the select list because it is not contained in either an aggregate function or the GROUP BY clause." Oracle rejects it too.

MySQL's older behaviour — accepting *any* non-aggregated column and silently picking a value — is controlled by the `ONLY_FULL_GROUP_BY` SQL mode, which is on by default in modern MySQL. With it off, the manual's warning is blunt: "the server is free to choose any value from each group, so unless they are the same, the values chosen are nondeterministic ... the selection of values from each group cannot be influenced by adding an `ORDER BY` clause."

> 🌍 **In the real world**: a team lifts a reporting service off MySQL 5.6 onto a managed MySQL 8 instance, and a dozen queries that had run for years start failing at boot with "Expression #2 of SELECT list is not in GROUP BY clause and contains nonaggregated column". Their first move is to switch `ONLY_FULL_GROUP_BY` off in the parameter group and ship. Reading the failures afterwards showed why that was the wrong instinct: three of the twelve were selecting `product.name` grouped by `order_id`, which had been quietly returning one arbitrary product name per order to a customer-facing invoice PDF for two years. The mode had not broken the queries — it had found a bug the old server was hiding.

**Multi-column GROUP BY:**

```sql
SELECT country, status, COUNT(*) AS cnt, SUM(total) AS revenue
FROM orders o
JOIN customers c ON c.id = o.customer_id
GROUP BY country, status;
```

Groups by every unique `(country, status)` tuple. If you have `('PK', 'Pending')`, `('PK', 'Paid')`, `('US', 'Pending')`, you get three groups.

**`GROUP BY` is not `ORDER BY`.** No engine promises an order for grouped output. A hash-based aggregate emits groups in hash-bucket order; a sort-based one emits them sorted, and which of the two you get is a costing decision that can flip when the table grows or statistics change. MySQL used to sort as a side effect and documents the removal explicitly: "Previously (MySQL 5.7 and lower), `GROUP BY` sorted implicitly under certain conditions. In MySQL 8.0, that no longer occurs, so specifying `ORDER BY NULL` at the end to suppress implicit sorting (as was done previously) is no longer necessary. However, query results may differ from previous MySQL versions." If you want an order, write `ORDER BY`.

> 🌍 **In the real world**: a nightly job exports a grouped CSV to a partner SFTP site, and the partner diffs each file against the previous night to find changes. It works for years on MySQL 5.7, where the GROUP BY happened to come back sorted by the grouping column. After the 8.0 upgrade the totals are identical and every diff is a full-file rewrite, because the row order now follows a hash. The partner's alerting reads "100% of records changed" and someone gets paged at 03:00. One `ORDER BY country, status` on the export query — three seconds of work — was the whole fix; the expensive part was the two days spent looking for a data bug that did not exist.

### HAVING — filtering groups

`WHERE` filters rows before grouping. `HAVING` filters groups after aggregation. Aggregate functions can only appear in `HAVING` (or `SELECT` / `ORDER BY`).

```sql
-- High-value customers (spent > $10k)
SELECT customer_id, SUM(total) AS spent
FROM orders
GROUP BY customer_id
HAVING SUM(total) > 10000;

-- Customers with > 5 orders in 2025
SELECT customer_id, COUNT(*) AS order_count
FROM orders
WHERE created_at >= '2025-01-01' AND created_at < '2026-01-01'   -- pre-group filter
GROUP BY customer_id
HAVING COUNT(*) > 5;                                                -- post-group filter
```

The evaluation order is fixed:
```sql
WHERE   row_predicate           -- 1. drop rows
GROUP BY group_columns           -- 2. collapse
HAVING  group_predicate          -- 3. drop groups
```

Often, a query *can* be written with either WHERE or HAVING; pick the one that filters more aggressively earlier (WHERE on row-level columns; HAVING on aggregates). PostgreSQL's planner will move a HAVING qual into WHERE for you when it is safe to — `subquery_planner` in `src/backend/optimizer/plan/planner.c` does it for quals containing no aggregate, no volatile function, no subplan and no grouping-set reference — but write it in WHERE anyway: it is portable, and it says what you meant.

The important half of this is not performance. **Moving a predicate between WHERE and HAVING can change the answer**, because one filters the rows that feed the aggregate and the other filters the finished aggregate. `WHERE created_at >= :d GROUP BY customer_id HAVING COUNT(*) > 5` means "more than five orders *since d*". `GROUP BY customer_id HAVING COUNT(*) > 5 AND MAX(created_at) >= :d` means "more than five orders *ever*, and active since d". Different customers, same shape.

> 🌍 **In the real world**: a marketing segment called "loyal, recently active" was defined by a query that grouped the whole `orders` table and filtered with `HAVING COUNT(*) > 5 AND MAX(created_at) >= NOW() - INTERVAL '30 days'`. Someone tuning slow queries moved both predicates into WHERE to get the date filter under the aggregate, the runtime dropped, and the segment quietly shrank by a third — because the rewrite now demanded five orders *within the last 30 days* rather than five orders lifetime. Nobody noticed for a fortnight; the campaign that went out in the meantime targeted the wrong list. When a predicate moves across the grouping boundary, it is a semantic change that needs the same review as a schema change, and the fastest way to prove it is to run both versions and diff the key sets.

### DISTINCT inside aggregates

`COUNT(DISTINCT col)` and `SUM(DISTINCT col)` aggregate over unique values only.

```sql
-- How many unique customers placed orders?
SELECT COUNT(DISTINCT customer_id) FROM orders;

-- Per country, how many distinct customers ordered?
SELECT country, COUNT(DISTINCT customer_id) AS unique_buyers
FROM orders o
JOIN customers c ON c.id = o.customer_id
GROUP BY country;

-- Sum of distinct order values (rare; usually SUM is what you want)
SELECT SUM(DISTINCT total) FROM orders;
-- If two orders both totaled $99.50, only counted once.
```

`COUNT(DISTINCT)` is the most common; `SUM(DISTINCT)` and `AVG(DISTINCT)` exist but rarely make business sense.

Know why it costs what it costs. `SUM`, `COUNT`, `MIN`, `MAX` are **streaming** aggregates: one running value per group, constant memory, and the row can be forgotten as soon as it is added. `COUNT(DISTINCT col)` cannot forget — it has to remember every value it has already seen in that group, so its memory is proportional to the number of distinct values *per group*, and a second `COUNT(DISTINCT other_col)` in the same SELECT needs its own separate structure. That is the reason a query with three distinct-counts behaves nothing like the same query with three sums.

The other property that catches teams out is arithmetic, not performance: **distinct counts are not additive**. Summing seven daily unique-user counts does not give the weekly unique-user count, because a user who visited on three days is counted three times. Sums and counts roll up; distinct counts have to be recomputed over the wider window, or approximated with a mergeable sketch (see [Approximate distinct counts](#approximate-distinct-counts)).

> 🌍 **In the real world**: a product dashboard built its monthly-active-users tile by summing the 30 daily-active-user rows from a pre-aggregated table, because the daily table was already there and the query was fast. MAU therefore ran roughly at the level of "total visits", and the growth curve looked wonderful right up until finance compared it with the billing system's account count and found MAU exceeding the number of accounts that existed. The fix was two-part: recompute MAU as a real `COUNT(DISTINCT user_id)` over the month for the reported number, and store an HLL sketch per day for the exploratory dashboards, because sketches — unlike counts — can be merged across days.

### String aggregation (STRING_AGG / GROUP_CONCAT)

Combine string values within a group, separated by a delimiter.

```sql
-- PostgreSQL / SQL Server 2017+
SELECT
    customer_id,
    STRING_AGG(product_name, ', ') AS products
FROM order_items
GROUP BY customer_id;
-- Result: customer_id=7, products='Laptop, Mouse, Keyboard'

-- With ordering inside the aggregate — PostgreSQL: ORDER BY goes after ALL the arguments
SELECT
    customer_id,
    STRING_AGG(product_name, ', ' ORDER BY product_name) AS products_sorted
FROM order_items
GROUP BY customer_id;
-- string_agg(a ORDER BY a, ',') is the classic mistake; the PostgreSQL docs call it out.

-- SQL Server 2017+: ordering is a WITHIN GROUP clause, not an argument
SELECT customer_id,
       STRING_AGG(CONVERT(NVARCHAR(MAX), product_name), ', ')
           WITHIN GROUP (ORDER BY product_name) AS products_sorted
FROM order_items
GROUP BY customer_id;

-- MySQL: ORDER BY comes BEFORE SEPARATOR
SELECT customer_id, GROUP_CONCAT(product_name ORDER BY product_name SEPARATOR ', ')
FROM order_items GROUP BY customer_id;
```

Useful for:
- Email reports: "Order #42 contains: Laptop, Mouse, Keyboard."
- Tag aggregation: collapsing many tags-per-row into one display string.
- CSV exports of grouped data.

Every engine caps the result, and they fail in different ways — this is the part that bites in production, because it only triggers for your largest group:

| Engine | Cap | Failure mode |
|---|---|---|
| MySQL | `group_concat_max_len`, default 1024 bytes, session-settable | **Silently truncates** (a warning is raised; most drivers never surface it) |
| SQL Server | Return type follows the input: a non-`MAX` `varchar`/`nvarchar` input yields `varchar(8000)`/`nvarchar(4000)`; non-string inputs yield `nvarchar(4000)` | **Error 9829**, "STRING_AGG aggregation result exceeded the limit of 8000 bytes. Use LOB types to avoid result truncation." Fix by converting the input: `STRING_AGG(CONVERT(NVARCHAR(MAX), col), ', ')` — which is what most of the examples in Microsoft's own documentation do |
| PostgreSQL | `text`, bounded by the 1 GB field limit | No practical cap for this use |
| Oracle | `LISTAGG` returns `VARCHAR2` (4000 bytes by default) | `ORA-01489` unless you write `ON OVERFLOW TRUNCATE` (12.2+) |

> 🌍 **In the real world**: an order-confirmation service built its "items in this order" line with `STRING_AGG(item_name, ', ')` on SQL Server and shipped fine for months. The first customer to order 300 line items got no email at all: the aggregate's return type was `nvarchar(4000)`, the concatenation crossed it, and error 9829 killed the whole statement — so a wholesale account's confirmations failed while every retail order kept working. Because the failure was inside a background job with a generic retry, the alert said "job failed" and not "one customer is too big". Wrapping the column in `CONVERT(NVARCHAR(MAX), ...)` fixed it permanently; the durable lesson was to seed the test data with one absurdly large group instead of a hundred typical ones.

### Conditional aggregation (CASE inside aggregate)

The most powerful pattern: pivot-like results without `PIVOT` syntax.

```sql
-- Order count by status, per customer
SELECT
    c.id, c.name,
    SUM(CASE WHEN o.status = 'Pending'   THEN 1 ELSE 0 END) AS pending,
    SUM(CASE WHEN o.status = 'Paid'      THEN 1 ELSE 0 END) AS paid,
    SUM(CASE WHEN o.status = 'Shipped'   THEN 1 ELSE 0 END) AS shipped,
    SUM(CASE WHEN o.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled,
    COUNT(o.id) AS total       -- NOT COUNT(*): see below
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.id, c.name;
```

Result is a wide table with one row per customer + a column per status — exactly what most reports want.

**`COUNT(*)` after a LEFT JOIN is almost always a bug.** A customer with no orders still produces one row — every `orders` column NULL — and `COUNT(*)` counts rows, so that customer reports `total = 1`. `COUNT(o.id)` counts non-NULL values of a column from the outer side and reports `0`. The conditional `SUM(CASE ...)` columns are already safe, because no status matches NULL; it is the innocent-looking `COUNT(*)` that lies.

> 🌍 **In the real world**: an account-health screen listed every customer with their order count, and support kept escalating tickets about customers whose profile said "1 order" but whose order list was empty. The query was `SELECT c.id, COUNT(*) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id GROUP BY c.id`. Nothing about it looks wrong, and it is right for every customer who has ever ordered — only the empty ones are off, and only by one. It survived code review twice. Changing `COUNT(*)` to `COUNT(o.id)` fixed it, and the team added a test fixture containing a customer with no children, which is the fixture most seed scripts forget.

`COUNT(CASE ...)` works too (since `COUNT` ignores NULLs):

```sql
SELECT
    customer_id,
    COUNT(CASE WHEN status = 'Pending' THEN 1 END) AS pending,
    COUNT(CASE WHEN status = 'Paid'    THEN 1 END) AS paid
FROM orders
GROUP BY customer_id;
-- Note: no ELSE; non-matching rows produce NULL → not counted.
```

For boolean-style aggregates (in PostgreSQL):

```sql
-- Did the customer ever cancel an order?
SELECT customer_id, BOOL_OR(status = 'Cancelled') AS has_cancelled
FROM orders GROUP BY customer_id;
```

Standard SQL has a dedicated syntax for this — the `FILTER` clause, added in SQL:2003 — and PostgreSQL (9.4+) and SQLite implement it:

```sql
-- PostgreSQL / SQLite
SELECT customer_id,
       COUNT(*) FILTER (WHERE status = 'Pending') AS pending,
       COUNT(*) FILTER (WHERE status = 'Paid')    AS paid,
       COUNT(*)                                    AS total
FROM orders GROUP BY customer_id;
```

SQL Server has no `FILTER` clause — not in 2022, and not in the 2025 language additions either, which brought `PRODUCT`, `JSON_ARRAYAGG`, `JSON_OBJECTAGG` and the `REGEXP_*` family but nothing here. So `SUM(CASE ...)` / `COUNT(CASE ...)` stays the portable form, and on PostgreSQL `FILTER` is the readable one. They express the same thing.

### ROLLUP, CUBE, GROUPING SETS

For multi-level subtotals — generating "country totals" + "country+status totals" + "grand total" in one query.

**ROLLUP** — hierarchical subtotals (left-to-right):

```sql
SELECT country, status, SUM(total) AS revenue
FROM orders o JOIN customers c ON c.id = o.customer_id
GROUP BY ROLLUP (country, status);
```

Result includes:
- Each `(country, status)` group.
- Each `country` subtotal (with `status` as NULL).
- Grand total (with both NULL).

```
country | status     | revenue
--------+------------+--------
PK      | Pending    |   1500
PK      | Paid       |  10000
PK      | Cancelled  |    200
PK      | NULL       |  11700   ← PK subtotal
US      | Pending    |   3200
US      | Paid       |  18000
US      | NULL       |  21200   ← US subtotal
NULL    | NULL       |  32900   ← grand total
```

**CUBE** — every combination of subtotals:

```sql
GROUP BY CUBE (country, status)
```

Adds `status` subtotals (across all countries) on top of what ROLLUP gives.

**GROUPING SETS** — explicit list of grouping combinations:

```sql
GROUP BY GROUPING SETS (
    (country, status),    -- per country+status
    (country),             -- per country
    (status),              -- per status
    ()                     -- grand total
);
```

Semantically the same result as `UNION ALL`-ing the separate GROUP BYs — Microsoft's documentation says exactly that, "the results are the same as using `UNION ALL` on the specified groups" — but the engine gets to compute several sets from one read of the input instead of one read per set. PostgreSQL 10 and later can even mix strategies inside one node: a plan for grouping sets shows `MixedAggregate` with several `Hash Key` lines and a `Group Key`, meaning it filled hash tables for some sets while walking a sorted input for another. Don't promise "one pass" in an interview; promise "one read of the input feeding several accumulators", which is the part that is actually true.

Two engine limits worth knowing before you design a report around this:

- **SQL Server caps the lattice.** "For a `GROUP BY` clause that uses `ROLLUP`, `CUBE`, or `GROUPING SETS`, the maximum number of expressions is 32. The maximum number of groups is 4,096 (2^12)." `CUBE` over 13 columns produces 8,192 grouping sets and fails outright — not slowly, but with an error.
- **Duplicate sets are not merged.** "SQL doesn't consolidate duplicate groups generated for a `GROUPING SETS` list" — `GROUP BY GROUPING SETS ((), CUBE(a, b))` emits the grand total twice, because `CUBE` already contains `()`. Two identical rows in a report is the kind of bug that gets blamed on the join.

`GROUPING(col)` distinguishes "subtotal NULL" from "actual data NULL":

```sql
SELECT
    CASE WHEN GROUPING(country) = 1 THEN 'TOTAL' ELSE country END AS country,
    SUM(total)
FROM orders ...
GROUP BY ROLLUP (country);
```

**Engine support is not uniform, and this is a portability trap.** PostgreSQL (9.5+), SQL Server (2008+) and Oracle have all three: `ROLLUP()`, `CUBE()`, `GROUPING SETS()`. **MySQL has only ROLLUP** — written either as `GROUP BY year WITH ROLLUP` or, in MySQL 8, `GROUP BY ROLLUP(year)` — plus `GROUPING()`. There is no `CUBE` and no `GROUPING SETS` in MySQL; the fallback is `UNION ALL` of separate GROUP BY queries, which costs one pass per set instead of one pass total.

> 🌍 **In the real world**: a finance report was written on PostgreSQL with `GROUPING SETS ((region, product), (region), (product), ())` — one query, one pass, four levels of subtotal, and a `GROUPING()` call labelling each row. When the same reporting module had to run against a customer's on-premises MySQL, the query would not parse. Rewriting it as four `UNION ALL` branches produced identical numbers but read the fact table four times, and the nightly job moved from minutes to most of an hour. The team ended up materialising the finest grain (`region, product`) into a small table and computing the three coarser levels from *that* — which is the answer whenever the sets form a hierarchy, and would have been the better design on PostgreSQL too.

These are advanced features; many teams reach for app-level aggregation or reporting tools instead. Know they exist for interview / DBA scenarios.

### How the engine groups — hash vs sort

Everything above is semantics. Under it there are only two algorithms, and being able to name the one in your plan is most of what "can you read an execution plan" means for aggregation.

```
HASH AGGREGATE                              SORT (STREAM) AGGREGATE
─────────────────────────────               ─────────────────────────────
Read rows in any order.                     Input must already be ordered
Hash the group key; keep one                by the group key (from an index,
accumulator per key in a hash               or from an explicit Sort).
table.                                      Walk it; when the key changes,
                                            emit the finished group.

  row → hash(customer_id)                     ...,7 | 7 | 7 | 8 | 8, ...
      → bucket → {count+=1,                            ▲       ▲
                  sum+=total}                       emit 7   emit 8

Memory: proportional to the                 Memory: one accumulator. Ever.
NUMBER OF GROUPS.                           Cost is in getting sorted input.
Output order: undefined.                    Output order: the sort order,
                                            free for ORDER BY / merge joins.
```

The names differ by engine, the operators do not:

| Engine | Hash form | Sorted form |
|---|---|---|
| PostgreSQL | `HashAggregate` | `GroupAggregate` (with a `Sort` or ordered index scan beneath) |
| SQL Server | `Hash Match (Aggregate)` | `Stream Aggregate` (with `Sort` or an ordered index seek/scan beneath) |
| MySQL/InnoDB | temporary table (`Using temporary` in `EXPLAIN`) | index scan (`Using index for group-by` = loose index scan) |

The optimizer picks by estimated group count and by whether ordered input is already available. Hash wins when there are few groups relative to rows and nothing is sorted; sort wins when an index already delivers the order, when the group count is huge, or when the query needs that order anyway for `ORDER BY`.

```sql
-- PostgreSQL, no useful index: hash
EXPLAIN SELECT customer_id, SUM(total) FROM orders GROUP BY customer_id;
--  HashAggregate  (cost=..., rows=50000 width=12)
--    Group Key: customer_id
--    ->  Seq Scan on orders  (cost=..., rows=4000000 width=12)

-- After CREATE INDEX ix ON orders (customer_id, total): sorted, no Sort node, no hash table
--  GroupAggregate
--    Group Key: customer_id
--    ->  Index Only Scan using ix on orders
```

**Parallelism changes the shape again.** A parallel aggregate is computed in two phases: each worker aggregates its slice (PostgreSQL shows `Partial HashAggregate`; SQL Server shows a partial `Hash Match` below the exchange), then one node combines the partials (`Finalize GroupAggregate` under a `Gather`, or the global `Hash Match` above the exchange). This is why `AVG` parallelizes at all — the partial result is a (sum, count) pair, combined by summing both and dividing once at the end — and why `COUNT(DISTINCT)` is so much harder to parallelize: partial *sets* have to be merged, not partial numbers.

One consequence worth carrying into an interview: **a parallel `SUM` over `float`/`real` is not bit-for-bit deterministic**. IEEE-754 addition is not associative, so a different split of rows across workers can change the last digits. That is a mechanism, not a bug — and it is one of the reasons money belongs in `decimal`/`numeric`, where addition is exact until it overflows.

> 🌍 **In the real world**: a "revenue by day" tile on an internal dashboard disagreed with itself between refreshes — the same day would read `18,244.31999999998` and `18,244.32` in alternate loads. The column was `double precision` because whoever created the table years earlier had typed `float` out of habit, and the plan had recently gone parallel as the table grew, so the addition order changed run to run. Nobody had lost money; the ledger was correct. But a finance dashboard that visibly disagrees with itself destroys trust in every other number on the page, and the migration to `numeric(12,2)` was signed off the same week — which had been sitting in the backlog, unloved, for a year.

### When the estimate is wrong — spills and memory grants

A hash aggregate's memory is proportional to the number of *groups*, and the engine has to guess that number before it runs. When the guess is far too low, the hash table does not fit in the memory it was given, and the operator spills to disk.

**PostgreSQL** allows each hash node `work_mem × hash_mem_multiplier` (defaults: 4 MB and 2.0 in current versions — and note the docs' warning that a complex query "might perform several sort and hash operations at the same time", each entitled to that much). Beyond it, PostgreSQL 13 and later spill. The release note for that change is worth quoting because it also describes the *old* failure mode:

> "Previously, hash aggregation was avoided if it was expected to use more than `work_mem` memory. Now, a hash aggregation plan can be chosen despite that. The hash table will be spilled to disk if it exceeds `work_mem` times `hash_mem_multiplier`. This behavior is normally preferable to the old behavior, in which once hash aggregation had been chosen, the hash table would be kept in memory no matter how large it got — which could be very large if the planner had misestimated."

`EXPLAIN (ANALYZE, BUFFERS)` tells you it happened: a `HashAggregate` node reports `Planned Partitions`, `Batches`, `Memory Usage` and `Disk Usage`, and a `Sort` reports `Sort Method: external merge  Disk: …kB`. Anything above `Batches: 1`, or any `Disk:` line, means the aggregate went to storage.

**SQL Server** decides differently: the query gets a *memory grant* fixed at compile time from the estimated rows and row size, and it cannot grow while the query runs. Too small a grant and the hash aggregate or sort spills to `tempdb`, which the plan flags with a spill warning on the operator; `sys.dm_exec_query_memory_grants` shows what was asked for versus used while it runs. Too *large* a grant is its own outage — the query holds memory it never uses, and other queries queue behind it waiting for a grant. Memory grant feedback (part of intelligent query processing) corrects a grant that was badly wrong, but it does so for *later* executions of the same plan, not the one currently spilling.

The root cause is nearly always the group-count estimate on multiple columns. Single-column statistics know how many distinct countries there are and how many distinct statuses, but not how many *combinations* actually occur. PostgreSQL states the problem and the fix directly:

> "Estimates of the number of distinct values when combining more than one column (for example, for `GROUP BY a, b`) are frequently wrong when the planner only has single-column statistical data, causing it to select bad plans. To improve such estimates, `ANALYZE` can collect n-distinct statistics for groups of columns."

```sql
-- PostgreSQL: teach the planner about the real combination count
CREATE STATISTICS orders_geo (ndistinct) ON country, status FROM orders;
ANALYZE orders;
```

The docs add the discipline that goes with it: "It's advisable to create `ndistinct` statistics objects only on combinations of columns that are actually used for grouping, and for which misestimation of the number of groups is resulting in bad plans." SQL Server's equivalent lever is a multi-column statistics object, whose density vector serves the same purpose for the leading columns.

> 🌍 **In the real world**: a nightly rollup grouped an events table by `(tenant_id, event_type)` and ran for months on PostgreSQL 12. Then a large tenant onboarded, the real number of combinations grew far beyond what single-column statistics implied, and the job stopped being slow and started being fatal: the hash table kept growing in memory — exactly the pre-13 behaviour described above — until the OOM killer took the postmaster down and every connection on the box died with it. The immediate fix was `SET enable_hashagg = off` for that one job, which forced a sort-based aggregate that spills gracefully. The real fixes came in the next sprint: an `ndistinct` extended statistic on the pair, and the version upgrade that makes hash aggregation spill instead of dying.

> 🌍 **In the real world**: on SQL Server, the same class of bug looks nothing like an OOM. A month-end report estimated a few thousand groups, was granted memory to match, and produced tens of millions; the hash aggregate spilled to `tempdb`, `tempdb` filled the volume, and the queries that failed were *other people's* — anyone whose session needed `tempdb` for a sort or a version store while the report ran. The report itself finished, slowly, and looked innocent in the logs. Reading the actual plan showed the spill warning and an estimate three orders of magnitude below actual; a filtered multi-column statistic on the grouping keys, plus moving the job to the read-only replica, ended the pattern.

### Indexing for GROUP BY

An index helps a GROUP BY in three distinct ways, and they are worth separating because they need different indexes.

1. **Order** — an index on the grouping columns delivers rows already sorted, so the engine can use a stream aggregate with no `Sort` node and constant memory. The grouping columns must be a *leading prefix* of the index: an index on `(customer_id, created_at)` serves `GROUP BY customer_id`, but not `GROUP BY created_at`.
2. **Covering** — if every column the query touches is in the index, the aggregate never reads the base table. `CREATE INDEX ix ON orders (customer_id) INCLUDE (total)` (SQL Server) or `CREATE INDEX ix ON orders (customer_id, total)` (PostgreSQL, MySQL) turns "scan the whole row" into "scan a narrow index".
3. **Skipping** — some engines can jump between distinct key values instead of reading every row. MySQL calls this a **loose index scan** and shows `Using index for group-by` in `EXPLAIN`; the manual's conditions are strict: single table, the `GROUP BY` names a leftmost prefix of one index and nothing else, and the only aggregates are `MIN()`/`MAX()` over one column that immediately follows the grouping columns in that index. PostgreSQL applies a related trick to ungrouped `MIN()`/`MAX()`, rewriting `SELECT MAX(created_at) FROM orders` into an `ORDER BY … LIMIT 1` index scan visible as an `InitPlan` in the plan — a `WHERE` clause is fine, but a `GROUP BY` disables it entirely: `SELECT customer_id, MAX(created_at) … GROUP BY customer_id` gets no such shortcut.

**Grouping by an expression discards all of this.** `GROUP BY DATE_TRUNC('month', created_at)` cannot use a plain index on `created_at`, because the index stores timestamps and the query groups on a function of them. The fix is an index on the same expression — with a PostgreSQL-specific catch:

```sql
-- Fails: "functions in index expression must be marked IMMUTABLE".
-- date_trunc over timestamptz is only STABLE — which month a given instant
-- falls in depends on the session's TimeZone setting.
CREATE INDEX ON orders (date_trunc('month', created_at));

-- Works: pin the zone, which makes the expression immutable.
CREATE INDEX ON orders (date_trunc('month', created_at AT TIME ZONE 'UTC'));
-- The query must then use the identical expression, or the index won't match.
```

SQL Server's route is a computed column marked `PERSISTED`, which can then be indexed. MySQL 8 supports functional indexes on expressions.

> 🌍 **In the real world**: an `orders` table with a clustered index on `id` (an identity column) backed a page that showed each customer's order count and lifetime spend. At a few million rows the query was a clustered-index scan and nobody minded. At a few hundred million, that scan was reading every column of every order — addresses, JSON blobs, the lot — to compute two numbers, and the page was the slowest endpoint in the system. Adding `(customer_id) INCLUDE (total)` did not change a line of application code and turned it into a narrow, ordered, covering scan feeding a stream aggregate. The instructive part is the diagnosis: the clustered index was not "wrong", it was simply not the shape this query needed, and no amount of query rewriting could have substituted for the missing index.

### The zero-row trap — aggregates over an empty set

This is the highest-frequency production bug in this whole topic, and it is pure semantics.

```sql
-- No GROUP BY: ALWAYS returns exactly one row, even with no input rows
SELECT COUNT(*), SUM(total) FROM orders WHERE 1 = 0;
--  count | sum
--      0 | NULL          ← COUNT is 0, SUM is NULL, not 0

-- With GROUP BY: returns ZERO rows for no input
SELECT customer_id, COUNT(*) FROM orders WHERE 1 = 0 GROUP BY customer_id;
--  (0 rows)
```

Three consequences a senior candidate should be able to state without thinking:

- **`SUM` of nothing is NULL, not 0.** Any arithmetic downstream turns NULL too. `COALESCE(SUM(total), 0)` is the fix, and it belongs in the query, not the C# mapping.
- **A grouped query returns nothing for groups that do not exist.** "Revenue per day for the last 30 days" silently skips days with no orders — the chart shows 29 points and the line joins across the gap as though nothing happened. Generate the axis and outer-join the aggregate onto it (`generate_series` in PostgreSQL, a calendar table in SQL Server) if a zero is meant to be visible.
- **`HAVING` without `GROUP BY` treats the whole table as one group**, and can remove that single row: `SELECT COUNT(*) FROM orders HAVING COUNT(*) > 5` returns one row or none. A caller written as `ExecuteScalar()` gets `null` in the "none" case and generally throws or coerces to zero — which is the opposite of what the predicate meant.

> 🌍 **In the real world**: a payments team monitored failures with `SELECT COUNT(*) AS failures FROM payments WHERE status='Failed' AND created_at > NOW() - INTERVAL '5 minutes' HAVING COUNT(*) > 10`, and wired the alert to fire "if the query returns a row". It worked in testing. In the incident it did not fire — the gateway had gone down so completely that no payment rows were being *written* at all, so the count was 0, `HAVING` dropped the row, the alert saw an empty result and concluded "nothing wrong". The rule that came out of it: alerting queries must always return a row, with the predicate applied by the alerting layer, not by `HAVING`. `SELECT COALESCE(COUNT(*), 0) …` with no `HAVING`, and a threshold in the monitor.

> 🌍 **In the real world**: an ops dashboard rendered "Orders today: —" every morning until the first order arrived, because the tile bound to `SUM(total)` and the API returned `null`. Support treated it as an outage indicator ("the dashboard is broken again") and stopped trusting the tile, so when a genuine ingestion failure produced the same dash at 11:00 nobody escalated. `COALESCE(SUM(total), 0)` plus a separate freshness indicator ("last order 4 minutes ago") made the two states distinguishable: zero is a number, unknown is not.

### Aggregation under concurrency

Long aggregate queries and OLTP traffic on the same tables is where "the report locked the database" comes from — and the answer is entirely engine-specific.

**SQL Server** with the default `READ COMMITTED` and `READ_COMMITTED_SNAPSHOT` OFF reads by *locking*. Microsoft's own description: "If the database option `READ_COMMITTED_SNAPSHOT` is OFF, the Database Engine acquires shared locks as data is read and releases those locks when the read operation is completed. If the database option `READ_COMMITTED_SNAPSHOT` is ON, the Database Engine doesn't acquire locks and uses row versioning." A report that scans ten million rows therefore takes and releases shared locks over ten million rows, and any writer wanting a row the scan is currently holding waits for it. Once a scan accumulates enough locks, SQL Server escalates — and note *where to*: the documentation is explicit that the engine "doesn't escalate row or key-range locks to page locks, but escalates them directly to table locks" (or to the partition's HoBT, if `LOCK_ESCALATION` is set to `AUTO` on a partitioned table). After that, writers to the whole object wait wholesale rather than one row at a time. Note the default differs by product: SQL Server ships with RCSI off, **Azure SQL Database ships with it on** — the same query, the same code, different blocking behaviour after a migration.

The reflex fix, `WITH (NOLOCK)`, is worse than its reputation for a *report*, because it does not merely permit dirty reads. The documentation is explicit that it "might generate errors for your transaction, present users with data that was never committed, or cause users to see records twice (or not at all)" — and "twice (or not at all)" applied to a `SUM` is a total that is wrong by an unknown amount, with no error and no way to detect it after the fact. A financial number produced under `NOLOCK` cannot be defended.

**PostgreSQL and InnoDB** do not have this problem in the same shape, because readers use MVCC snapshots and do not take row locks for plain `SELECT`s: the report does not block checkout, and checkout does not block the report. What they have instead is a *duration* problem. A statement that runs for an hour holds back the oldest snapshot the system must preserve, so `VACUUM` (or InnoDB's purge) cannot clean up row versions that the report might still need, and the table bloats while it runs. On a PostgreSQL hot standby the same query hits the opposite failure — the standby has to apply WAL that removes rows the query is reading, and the query dies with `ERROR: canceling statement due to conflict with recovery` unless `max_standby_streaming_delay` or `hot_standby_feedback` is tuned for it.

The senior answer to "how do you stop the report locking production" is therefore a short list, in order: run it on a replica; if it must run on the primary, use row versioning (RCSI or `SNAPSHOT` on SQL Server — where it is a *snapshot*, not a "no locking" hint, so the totals are still consistent); make the query cheap enough not to matter with a covering index or a pre-aggregated table; and only then consider chunking it into ranges, accepting that chunks are separate snapshots and the totals no longer represent a single instant.

> 🌍 **In the real world**: a finance team ran a month-end report against the production SQL Server at 09:00 on the first of the month. It scanned the whole `orders` table under locking READ COMMITTED, checkout writes queued behind its shared locks, request threads piled up waiting on the database, and the site was effectively down for eleven minutes — with an application error rate that pointed at the web tier rather than at the query. The first "fix" was `NOLOCK`, which stopped the blocking and started a subtler problem: the report's totals no longer reconciled with the ledger, and it took a fortnight to work out that the query was reading rows moved by concurrent updates. Enabling RCSI made the report non-blocking *and* consistent — at the cost of version-store space in `tempdb`, which is a capacity decision to make deliberately rather than discover.

### Pre-aggregation — summary tables, indexed views, materialized views

When the same aggregate is asked for repeatedly, stop computing it repeatedly. Three levels, with real differences:

**A summary table you maintain.** A `daily_revenue(day, currency, gross, refunds, order_count)` table written by a job or by the application. Total control, total responsibility: the hard part is not the insert, it is late-arriving data. If the job refreshes "yesterday" on a watermark and a refund is backdated to last week, the summary is now wrong and nothing tells you. Either re-derive a trailing window every run, or record a `source_max_updated_at` per row so you can prove what the summary was built from.

**SQL Server indexed views** — the engine maintains the aggregate for you, synchronously, as part of every write to the base tables. The restrictions in Microsoft's documentation are the whole story of what "synchronously maintainable" means: `WITH SCHEMABINDING`, a unique clustered index, and "if `GROUP BY` is present, the VIEW definition must contain `COUNT_BIG(*)` and must not contain `HAVING`". `COUNT` (use `COUNT_BIG`), `AVG` (store `SUM` and `COUNT_BIG` and divide at read time), `MIN`/`MAX`, `STRING_AGG`, `DISTINCT`, outer joins, subqueries, CTEs, `UNION`, `ROLLUP`/`CUBE`/`GROUPING SETS` and `TOP` are all disallowed. The pattern is consistent: anything the engine cannot update incrementally from a single row change is banned — a `SUM` can be adjusted by a delta, a `MAX` cannot when the maximum row is the one being deleted. Two more practicalities: the optimizer can use an indexed view *without the query naming it*, but automatic matching is edition-dependent — Standard edition needs `WITH (NOEXPAND)`, while Azure SQL Database and Managed Instance match automatically — and every `INSERT`/`UPDATE`/`DELETE` on a base table now maintains the view too, which the docs warn "can degrade significantly" for tables under many indexed views.

**PostgreSQL materialized views** — the opposite trade. No maintenance cost on writes, because there is no incremental maintenance at all: `REFRESH MATERIALIZED VIEW` re-runs the whole query and replaces the contents. Plain `REFRESH` "could block other connections which are trying to read from the materialized view"; `REFRESH … CONCURRENTLY` does not lock out readers, but requires "at least one `UNIQUE` index on the materialized view which uses only column names and includes all rows", and only one refresh at a time may run. So the data is exactly as fresh as your last refresh, and you own the schedule. MySQL has no materialized views at all — there, the summary table is the only option.

> 🌍 **In the real world**: a pricing page was backed by a materialized view refreshed by cron every 15 minutes, which was fine until a promotion went live and support started getting calls that the checkout total did not match the advertised price — the page was reading a view refreshed before the price change, and checkout was reading the base table. The refresh had also been failing for two hours after a schema change, and because cron mailed the error to an unread alias, "stale" had quietly become "stale by hours" rather than "stale by minutes". Two changes fixed the class of problem, not just the instance: the page now shows prices from the same source checkout uses (correctness before speed), and the materialized view carries a `refreshed_at` column that the health check compares against `now()`, so a refresh that stops running is an alert rather than a rumour.

### Approximate distinct counts

`COUNT(DISTINCT user_id)` over a very large set is the aggregate most worth approximating, because its cost is exactly the thing that cannot be streamed: remembering every value seen.

HyperLogLog is the standard answer. Hash each value, and use the position of the first 1-bit in the hash to estimate cardinality — a value whose hash starts with *k* zeros turns up roughly once every 2^k distinct values — then split the input across *m* registers by the leading hash bits and combine the per-register maxima. The result is a fixed-size sketch, a few kilobytes, whose relative accuracy is 1.04/√m (Flajolet, Fusy, Gandouet and Meunier, *HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm*, 2007). Two properties matter in practice: memory does not grow with cardinality, and **sketches merge** — the union of two sketches is the sketch of the union, so daily sketches can produce a correct-to-within-the-error monthly unique count, which raw daily counts cannot.

- **SQL Server 2019+** has it built in as `APPROX_COUNT_DISTINCT(expr)`, returning `bigint`. Microsoft's documented guarantee: "The function implementation guarantees up to a 2% error rate within a 97% probability." The docs position it for "data sets that are millions of rows or higher" with high-cardinality columns, and note it is "less likely to spill memory to disk compared to a precise COUNT DISTINCT operation".
- **PostgreSQL has no built-in approximate distinct count.** It comes from an extension — `postgresql-hll`, which adds an `hll` column type you can store and union, or Apache DataSketches' PostgreSQL extension. Storing the sketch is the point: it is what lets tomorrow's dashboard answer a question over a range nobody pre-computed.

Use it where the number is directional — unique visitors, cardinality checks before designing an index, "roughly how many distinct devices". Never where the number is a count of things people are paid or billed for.

### Which aggregates roll up — distributive, algebraic, holistic

Several rules already on this page are the same rule wearing different clothes: why `AVG` parallelizes but `COUNT(DISTINCT)` doesn't, why an indexed view must contain `COUNT_BIG(*)` and may not contain `AVG`, why daily unique-user counts can't be summed into a monthly one. The classification that explains all of them comes from the paper that introduced `CUBE` to SQL — Gray, Chaudhuri, Bosworth, Layman, Reichart, Venkatrao, Pellow and Pirahesh, *Data Cube: A Relational Aggregation Operator Generalizing Group-By, Cross-Tab, and Sub-Totals* (1997):

| Class | Definition | Examples | Combine partial results? |
|---|---|---|---|
| **Distributive** | the aggregate over a set can be computed from the aggregates over its disjoint subsets | `SUM`, `COUNT`, `MIN`, `MAX` | Yes — one running value per partition |
| **Algebraic** | computable from a *fixed number* of distributive sub-aggregates | `AVG` (= `SUM`/`COUNT`), `STDDEV`, `VAR`, regression functions | Yes — carry the tuple, not the answer |
| **Holistic** | no constant bound on the size of the intermediate state | `COUNT(DISTINCT)`, `MEDIAN`/`PERCENTILE_CONT`, `MODE` | No — the intermediate state *is* the set |

Everything else follows from the last column.

**Parallelism.** A parallel plan splits rows across workers and combines their partial results. `SUM` combines by adding. `AVG` combines by carrying `(sum, count)` per worker and dividing once at the end — that is what makes it algebraic, and why the plan can show `Partial HashAggregate` under a `Gather` for an average. `COUNT(DISTINCT)` has no such tuple: the partial result is the set of values seen, so the partials have to be merged as sets.

**Pre-aggregation.** A summary table can only hold measures you can re-combine later. `daily_revenue(day, gross, order_count)` rolls up to a week, a month or a quarter by summing two columns. `daily_revenue(day, avg_order_value)` rolls up to nothing at all:

```
Mon:  100 orders, 10,000 total  → AVG =  100
Tue:    1 order,     500 total  → AVG =  500

Average of the two daily averages: (100 + 500) / 2      = 300
Actual two-day average order value: (10000 + 500) / 101 = 103.96…
```

The mean of the means weights Tuesday's single order as heavily as Monday's hundred. Store `SUM` and `COUNT`; divide at read time. The same rule applies one level up: `AVG(daily_avg)` in a dashboard, `orders.Average()` over a list of per-customer averages in C#, and `AVG` in a rolled-up materialized view are all the same mistake.

**Incremental maintenance is stricter than distributivity.** `MIN`/`MAX` are distributive — you can combine partial maxima — but they cannot be maintained *incrementally under deletion*, because deleting the current maximum row means re-reading the group to find the new one. That asymmetry is exactly why SQL Server's indexed views allow `SUM` (adjustable by a delta on every insert, update and delete) and forbid `MIN`/`MAX`, and why they require `COUNT_BIG(*)`: without it the engine cannot tell when a group has become empty and the row should disappear.

**Weighted rollups.** When the measure is a ratio — conversion rate, error rate, margin — never average the ratios. Store the numerator and the denominator as separate distributive columns and divide at the end. `SUM(errors) / SUM(requests)` is the error rate; `AVG(error_rate)` is a number with no meaning.

> 🌍 **In the real world**: a support dashboard reported "average handling time by region" from a daily summary table that stored a per-region average. The quarterly board number was produced by averaging the daily averages, and it looked stable and healthy. It was neither: a region processing forty tickets on a quiet Sunday contributed exactly as much to the quarter as a region processing forty thousand on a Monday, so the reported figure tracked the *small* regions. Nobody caught it from the chart, because a wrong average still looks like an average. It surfaced when a team lead added up the raw ticket durations for their own region and got a materially different number. The rebuild stored `sum_handling_seconds` and `ticket_count` per region per day, and every consumer divided at read time — the summary table now held only distributive measures, and every rollup became a `SUM`.

> 🌍 **In the real world**: a payments team's "authorisation success rate by acquirer" panel averaged the per-day rates. During an outage one acquirer processed eleven transactions in a day and failed nine of them; that day contributed an 18% rate with the same weight as a normal day's two million transactions, and the monthly rate on the panel dropped by far more than the incident had actually cost. The number went into a contractual review with the acquirer before anyone rechecked it. Rates are ratios of two distributive measures, and the panel had been storing the ratio.

### The grouping key is a comparison — collation, case, NULLs

`GROUP BY` puts two rows in the same group when their keys *compare equal*. That comparison is not byte equality, and it is not the same on every engine — which makes the row count of a grouped query a portability question.

**NULLs group together.** `NULL = NULL` is UNKNOWN in a `WHERE` clause, but grouping does not use `=`; it uses the standard's "not distinct" notion, under which two NULLs belong together. Microsoft states it plainly: "If a grouping column contains `NULL` values, the Database Engine treats all `NULL` values as equal and collects them into a single group." PostgreSQL and MySQL behave the same way. So `GROUP BY country` over customers with no country gives you one NULL bucket — usually what you want, occasionally a silent merge of "unknown" records that a reader reads as a real category. And after `ROLLUP`/`CUBE` you can no longer tell that bucket from a subtotal row without `GROUPING()`.

**Strings group under the column's collation.** The three defaults disagree on both axes that matter:

| Engine | Typical default | Case | Trailing spaces |
|---|---|---|---|
| SQL Server | server collation, commonly `SQL_Latin1_General_CP1_CI_AS` (`_CI` = case-insensitive) | `'ACME'` and `'Acme'` in **one** group | **Ignored** — `'abc'` and `'abc '` in one group |
| MySQL 8 | `utf8mb4_0900_ai_ci` — "based on UCA 9.0.0 and CLDR v30, is accent-insensitive and case-insensitive" | one group, **and** `'café'` groups with `'cafe'` | **Significant** — UCA 9.0.0 collations are `NO PAD`, and "`NO PAD` collations treat trailing spaces as significant in comparisons, like any other character" |
| PostgreSQL | the database's collation, which is deterministic | `'ACME'` and `'Acme'` are **two** groups | **Significant** |

The SQL Server padding rule is not a quirk but the standard: the engine "follows the ANSI/ISO SQL-92 specification (Section 8.2, *Comparison Predicate*, General rules #3) on how to compare strings with spaces … Transact-SQL considers the strings `'abc'` and `'abc '` to be equivalent for most comparison operations." MySQL 8's newer collations deliberately went the other way. PostgreSQL can be told to behave like the other two — nondeterministic ICU collations arrived in PostgreSQL 12, listed in the release notes as "Nondeterministic ICU collations, enabling case-insensitive and accent-insensitive grouping and ordering" — but the docs warn that "their use leads to a performance penalty", that B-tree deduplication is unavailable on indexes using them, and that some pattern-matching operations are not possible. The older, narrower alternative is the `citext` type.

Three consequences:

1. **The same query returns a different number of rows on different engines.** A migration that changes engine, or a database restored with a different collation, changes the *cardinality* of every grouped report over a string key. No error is raised.
2. **Which spelling appears in the output is not specified by the query.** Group by a case-insensitive column and the engine returns one representative from `{'ACME', 'Acme', 'acme'}`; nothing in the SQL says which. If you need a canonical form, say so: `GROUP BY lower(name)`, or select `MIN(name)` alongside.
3. **An index only supplies grouping order for its own collation.** An index built under collation A cannot deliver ordered input for a `GROUP BY … COLLATE B`, so the plan grows a `Sort` — the same effect as grouping on an expression.

The durable fix is to make the key explicit instead of inheriting it from the collation: normalise once (`lower(btrim(email))`), store or index that expression, and group on it. Then the grouping is defined by your code and behaves identically everywhere.

> 🌍 **In the real world**: a customer-deduplication job ran `SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1` against a SQL Server staging copy and reported several thousand duplicate email groups. The same script against the PostgreSQL production replica reported far fewer, and the two teams spent a week arguing about which extract was corrupt. Neither was: SQL Server's case-insensitive collation had been collapsing `Bob@x.com` with `bob@x.com`, and PostgreSQL had not. The number of duplicates was a property of the collation, not of the data. They settled it by defining the identity key in one place — `lower(btrim(email))` — creating an index on that expression, and grouping on it on both systems.

> 🌍 **In the real world**: a CSV importer had been writing country codes with a trailing space for years (`'GB '`), and nobody knew, because on SQL Server `'GB'` and `'GB '` group together under SQL-92 padding and every report looked right. After the move to PostgreSQL the revenue-by-country report grew a second, half-sized `GB` row, and the first instinct was that the migration had duplicated data. It had not — the migration had stopped hiding a four-year-old import bug. The lasting change was a `CHECK (country = btrim(country))` constraint on the column, so the next importer that does it fails at the write instead of at the report.

### Ordering, limiting, and Top-N over groups

`LIMIT`/`TOP`/`FETCH` bounds the number of rows you receive. It does not bound the aggregation, and confusing the two is behind a whole family of "but I only asked for ten rows" incidents.

```sql
-- Every group must be complete before ANY group can be ranked.
SELECT customer_id, SUM(total) AS spend
FROM orders
GROUP BY customer_id
ORDER BY spend DESC
LIMIT 10;
```

To know the top ten spenders the engine must finish the sum for *every* customer — the very last row read could belong to the customer who ends up first. So the scan, the grouping, and the memory for the hash table are all unaffected by the `LIMIT`. What the limit does buy is a **bounded sort**: the sort keeps only the best ten rows. PostgreSQL reports that in `EXPLAIN (ANALYZE)` as `Sort Method: top-N heapsort`; SQL Server uses a distinct showplan operator, **TopN Sort**, documented as "similar to the **Sort** iterator, except that only the first *N* rows are needed, and not the entire result set". That saves the sort's memory, not the aggregate's.

Contrast the case where the order *is* the grouping key:

```sql
-- With an index on (customer_id), a GroupAggregate can emit groups
-- in key order and stop after ten. The LIMIT is real work saved.
SELECT customer_id, SUM(total) FROM orders
GROUP BY customer_id ORDER BY customer_id LIMIT 10;
```

MySQL has one more early-exit worth knowing, and it applies to deduplication rather than aggregation: "When combining `LIMIT row_count` with `DISTINCT`, MySQL stops as soon as it finds `row_count` unique rows." A `GROUP BY` carrying aggregates can never do that.

**Pagination over an aggregate is the version of this that reaches production.** `ORDER BY SUM(...) DESC OFFSET 200 LIMIT 20` re-aggregates the entire table to produce page eleven, and it does it again for page twelve. Keyset pagination — the usual cure for deep `OFFSET` — does not help either, because the sort key is a computed aggregate that exists nowhere on disk, so there is no index to seek into. The answers, in order: filter first (`HAVING` and a date range shrink what has to be sorted, though not what has to be grouped); materialise the ranked result once into a table or temp table with a stored `rank` column and paginate on that; or pre-aggregate the measure so each page is a cheap read.

> 🌍 **In the real world**: a partner portal had a "top merchants by volume" leaderboard, paged twenty at a time, backed by `GROUP BY merchant_id ORDER BY SUM(amount) DESC` with `OFFSET`/`FETCH`. It was fast in every test and in production, because page one was cached and nobody went further. During a quarterly review an analyst clicked through to page forty; each click re-aggregated the whole `payments` table, the query took the connection pool's whole budget, and checkout latency spiked for the duration. The endpoint was rewritten to compute the ranked list once into a `merchant_rank(rank, merchant_id, volume, computed_at)` table on a schedule, with pages served by `WHERE rank BETWEEN :a AND :b`. The interesting part is the class of bug: the query wasn't slow, it was *linear in the table and independent of the page size*, and only a usage pattern nobody tested exposed it.

### Aggregating from .NET — what EF Core actually sends

Most of the aggregates a senior .NET engineer ships are written in LINQ, and the interesting failures are in the gap between LINQ's semantics and SQL's.

**What translates.** EF Core turns a `GroupBy` into SQL `GROUP BY` only when what you project is the key plus scalar aggregates, and an aggregate predicate becomes `HAVING`. The documentation states the constraint and the reason: "Since no database structure can represent an `IGrouping`, GroupBy operators have no translation in most cases. When an aggregate operator is applied to each group, which returns a scalar, it can be translated to SQL `GROUP BY` in relational databases."

```csharp
var q = from p in context.Set<Post>()
        group p by p.AuthorId into g
        where g.Count() > 5
        select new { g.Key, Count = g.Count() };
```
```sql
SELECT [p].[AuthorId] AS [Key], COUNT(*) AS [Count]
FROM [Posts] AS [p]
GROUP BY [p].[AuthorId]
HAVING COUNT(*) > 5
```

**What compiles, runs, returns the right answer, and reads the whole table.** If `GroupBy` is the *final* operator — you want the groups themselves, not scalars — there is nothing to translate. Before EF Core 7 that threw as untranslatable (tracked as dotnet/efcore#19929). Since 7.0 it succeeds, by doing the grouping on the client: "In this case, the GroupBy operator doesn't translate directly to a `GROUP BY` clause in the SQL, but instead, EF Core creates the groupings after the results are returned from the server." The SQL for `context.Books.GroupBy(s => s.Price)` is `SELECT [b].[Price], [b].[Id], [b].[AuthorId] FROM [Books] AS [b] ORDER BY [b].[Price]` — every row, every projected column, over the wire. Correct results; memory proportional to the table.

**`Any()` versus `Count() > 0`.** They compile to different shapes: `Any()` becomes `EXISTS (SELECT 1 …)`, which the engine may stop evaluating at the first matching row; `Count() > 0` becomes an aggregate that has to finish before the comparison happens. That is the mechanism, and it is the reason to prefer `AnyAsync` for existence checks. It is not a universal speed law — dotnet/efcore#27953 is a reported case where rewriting `Count() == 0` as `!Any()` inside a grouped projection made things *worse*, because the `EXISTS` became a correlated subquery evaluated per group while the `COUNT(*)` was already being computed by the `GROUP BY`. Check the generated SQL; the rule to carry is "`EXISTS` can stop early, `COUNT` cannot", not "`Any` is faster".

**The empty-set mismatch is the one that bites.** SQL and LINQ-to-Objects disagree about aggregates over nothing:

| Over an empty input | SQL | `System.Linq.Enumerable` |
|---|---|---|
| `SUM` | `NULL` | `0` |
| `MAX` / `MIN` | `NULL` | throws `InvalidOperationException` (non-nullable overloads) |
| `AVG` | `NULL` | throws `InvalidOperationException` (non-nullable overloads) |
| `COUNT` | `0` | `0` |

The provider has to paper over that, and where exactly it injects the `COALESCE` has moved between versions and been argued over in the tracker for years (dotnet/efcore#17492, #28158, #35950). Don't rely on it: project to a nullable and coalesce yourself — `Sum(x => (decimal?)x.Total) ?? 0m` — or write the aggregate in SQL with an explicit `COALESCE`. The same discipline applies to `Max()` on a filtered set that might be empty.

**Return types.** The provider decides, and the two documentation pages read differently. The provider-agnostic table in *Complex query operators* lists both `Count()` and `LongCount()` against `COUNT(*)`; the SQL Server provider's own function-mapping page is more specific and maps `group.Count()` to `COUNT(*)` and `group.LongCount()` to `COUNT_BIG(*)`. So on SQL Server, `LongCount()` does avoid the `int` overflow described [above](#aggregate-functions) — but the guarantee comes from the provider, not from LINQ, so on any other provider read the generated SQL before assuming a 64-bit count on the server.

> 🌍 **In the real world**: a health endpoint on a busy service ran `if (db.Orders.Count(o => o.Status == "Pending") > 0)` — a `SELECT COUNT(*)` over a large filtered set, executed by every pod on every probe interval. The pending set was small but the index scan to count it was not free, and at thirty pods with a five-second probe the database was answering it thousands of times a minute for a boolean. Switching to `AnyAsync` produced an `EXISTS`, which the same index satisfies by finding one row and stopping. Nothing about the endpoint's behaviour changed; the query simply stopped asking a question ("how many?") whose answer was thrown away.

> 🌍 **In the real world**: a reporting endpoint was written as `db.Orders.GroupBy(o => o.CustomerId).ToList()` followed by LINQ aggregation in memory. On EF Core 6 it threw "could not be translated", the developer rewrote it as a translatable `GroupBy … select new { Key, Sum }`, and that was that. After the EF Core 7 upgrade someone reintroduced the original shape in a new endpoint — and it worked, because 7.0 added client-side grouping. It stayed in for two releases, silently pulling the whole `Orders` table into the web tier on every call, until a memory alert during a traffic peak led back to it. The lesson is uncomfortable and worth saying out loud in an interview: EF Core 7 turned a loud failure into a quiet one, so "it compiles and the numbers are right" stopped being evidence that the query is sane. Log the SQL (`LogTo`, or the `Microsoft.EntityFrameworkCore.Database.Command` category) and read it.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Logical group operation flow

```
Input rows:
  +---+----------+-----+-------+
  | id| customer | total| status|
  +---+----------+-----+-------+
  | 1 |     7    |  100|Pending|
  | 2 |     7    |   50|Paid   |
  | 3 |     7    |   75|Paid   |
  | 4 |     8    |  200|Paid   |
  | 5 |     8    |   30|Pending|
  +---+----------+-----+-------+

GROUP BY customer:
  Group customer=7: rows 1, 2, 3
  Group customer=8: rows 4, 5

Apply aggregates:
  customer=7: COUNT=3, SUM(total)=225
  customer=8: COUNT=2, SUM(total)=230

Apply HAVING (e.g., HAVING SUM(total) > 200):
  customer=7: 225 > 200 ✓ keep
  customer=8: 230 > 200 ✓ keep

Apply ORDER BY (e.g., total DESC):
  customer=8 (230)
  customer=7 (225)

Final result:
  +----------+-------+-----+
  | customer | count | sum |
  +----------+-------+-----+
  |    8     |   2   | 230 |
  |    7     |   3   | 225 |
  +----------+-------+-----+
```

### "Top spenders per country" — combining GROUP BY + HAVING + ORDER BY

```sql
SELECT
    c.country,
    c.id AS customer_id,
    c.name,
    SUM(o.total) AS total_spent,
    COUNT(o.id) AS order_count
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE o.created_at >= '2025-01-01'
GROUP BY c.country, c.id, c.name
HAVING SUM(o.total) > 5000
ORDER BY c.country, total_spent DESC;
```

Reads as: "Per country, per customer, sum and count their orders since 2025; keep only those who spent > $5k; sort by country then spend."

### Conditional aggregation — KPI dashboard query

```sql
-- Single query produces:
--   - Total orders today
--   - Total revenue today
--   - Number of new customers today
--   - Number of cancelled orders today
--   - Average order value today

SELECT
    COUNT(*) AS total_orders,
    SUM(total) AS total_revenue,
    COUNT(DISTINCT CASE WHEN c.created_at >= CURRENT_DATE THEN c.id END) AS new_customers,
    SUM(CASE WHEN o.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled,
    AVG(o.total) AS avg_order_value
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.created_at >= CURRENT_DATE AND o.created_at < CURRENT_DATE + INTERVAL '1 day';
```

One query, five KPIs. Saves five round-trips to the DB and reads the data once.

### Apdex-like query — fraction of fast requests

```sql
-- "What fraction of requests completed under 100 ms?"
SELECT
    1.0 * SUM(CASE WHEN duration_ms < 100 THEN 1 ELSE 0 END)
        / COUNT(*) AS fast_fraction
FROM http_requests
WHERE created_at >= NOW() - INTERVAL '1 hour';
```

`1.0 *` forces non-integer division; without it, `int / int` truncates and the answer is always 0 or 1. Note what type you get: a bare `1.0` literal is `numeric` in PostgreSQL and `decimal` in SQL Server, so the result is exact decimal, not floating point. Cast explicitly (`::float8`, `CAST(... AS float)`) if float is what you actually want.

### COUNT(*) vs COUNT(col) vs COUNT(DISTINCT col)

```sql
-- Sample data
+----+----------+
| id | category |
+----+----------+
| 1  | A        |
| 2  | B        |
| 3  | NULL     |
| 4  | A        |
| 5  | B        |
+----+----------+

SELECT
    COUNT(*)                 AS total,            -- 5
    COUNT(category)          AS non_null,        -- 4 (excludes id=3)
    COUNT(DISTINCT category) AS unique_non_null  -- 2 (A, B)
FROM t;
```

Use:
- `COUNT(*)` for row count.
- `COUNT(col)` to skip NULLs.
- `COUNT(DISTINCT col)` for cardinality.

### Multi-window stats per group

```sql
-- Per customer: order count, total spend, biggest order, days since last order
SELECT
    customer_id,
    COUNT(*) AS order_count,
    SUM(total) AS total_spent,
    MAX(total) AS biggest_order,
    EXTRACT(DAY FROM NOW() - MAX(created_at)) AS days_since_last_order,
    ROUND(AVG(total)::numeric, 2) AS avg_order
FROM orders
GROUP BY customer_id
ORDER BY total_spent DESC
LIMIT 100;
```

Each metric is its own aggregate; one pass over the table.

### Simulating PIVOT with conditional aggregation

```sql
-- Source rows
+----+-------+--------+
| id | month | sales  |
+----+-------+--------+
| 1  | Jan   | 1000   |
| 2  | Feb   | 1500   |
| 3  | Mar   | 1200   |
| 4  | Jan   | 800    |
+----+-------+--------+

-- Pivoted result via conditional aggregation
SELECT
    SUM(CASE WHEN month = 'Jan' THEN sales ELSE 0 END) AS jan,
    SUM(CASE WHEN month = 'Feb' THEN sales ELSE 0 END) AS feb,
    SUM(CASE WHEN month = 'Mar' THEN sales ELSE 0 END) AS mar
FROM monthly_sales;

+------+------+------+
| jan  | feb  | mar  |
+------+------+------+
| 1800 | 1500 | 1200 |
+------+------+------+
```

This is the portable approach. T-SQL's `PIVOT` operator is more concise but vendor-specific.

</details>

## Common pitfalls

1. **Mixing aggregated and non-aggregated columns without GROUP BY.** Standard SQL forbids this; older MySQL allowed it (returning indeterminate values). Always group every non-aggregated column.
2. **Using HAVING for row-level filters.** `HAVING age > 18` works but performs a useless aggregation. Use `WHERE age > 18` to filter rows pre-grouping.
3. **Using WHERE for aggregate filters.** `WHERE COUNT(*) > 5` doesn't work — aggregates aren't computed yet. Use `HAVING`.
4. **`COUNT(*)` thinking it counts non-NULL.** It counts rows. For non-NULL count of a column, `COUNT(col)`.
5. **`SUM(NULL)` == 0?** No — `SUM` returns NULL when all input is NULL. Use `COALESCE(SUM(col), 0)` for "default zero."
6. **Integer division in averages.** `SUM(int_col) / COUNT(*)` truncates. Cast first or multiply by 1.0. Engine difference: SQL Server's `AVG` over an `int` column returns `int` and truncates too (`AVG(rating)` of 3 and 4 gives 3); PostgreSQL's `avg(int)` returns `numeric` and doesn't.
7. **`COUNT(DISTINCT col)` on huge data without index.** Requires a sort or a hash table sized by distinct values, and it can't stream. Consider approximate cardinality — `APPROX_COUNT_DISTINCT` on SQL Server 2019+, or the `postgresql-hll` / Apache DataSketches extensions on PostgreSQL, which has no built-in approximate distinct count.
8. **String aggregation length truncation.** Some dialects cap `STRING_AGG` / `GROUP_CONCAT` output. MySQL's default `group_concat_max_len` is 1024; raise if needed.
9. **Multiplying via JOIN before GROUP BY.** Joining to many-side table multiplies rows; per-customer SUM is now wrong (counted once per related row). Aggregate in a subquery first.
10. **Forgetting NULL groups.** GROUP BY treats NULL as a single group. Customers with `country = NULL` form one bucket. May be desired or surprising.
11. **CUBE / ROLLUP results indistinguishable from real NULL.** Use `GROUPING(col)` to differentiate.
12. **`DISTINCT` after aggregation when GROUP BY would do.** Often, `GROUP BY` is more efficient than `SELECT DISTINCT` over the same query.
13. **`COUNT(*)` on the preserved side of an OUTER JOIN.** A parent row with no children still produces one row, so `COUNT(*)` returns 1 where the answer is 0. Count a column from the optional side: `COUNT(child.id)`.
14. **Assuming `GROUP BY` returns rows in order.** A hash aggregate emits groups in bucket order and the plan can flip as the data grows. MySQL removed its incidental sorting in 8.0. Write `ORDER BY`.
15. **Aggregate return types overflowing.** SQL Server's `COUNT` returns `int` and raises `Msg 8115, Arithmetic overflow` past 2,147,483,647 — use `COUNT_BIG`. `SUM(int)` stays `int` in SQL Server (cast to `BIGINT` first) but is promoted to `bigint` in PostgreSQL.
16. **Grouping on an expression, keeping the plain index.** `GROUP BY DATE_TRUNC('month', created_at)` cannot use an index on `created_at`. Index the expression (PostgreSQL: the expression must be `IMMUTABLE`), or a `PERSISTED` computed column on SQL Server.
17. **`NOLOCK` on a reporting aggregate.** It does not just permit dirty reads: rows can be counted twice or skipped entirely as data moves during the scan, so the total is wrong by an unknown amount with no error raised. Use row versioning (RCSI / `SNAPSHOT`) or a replica.
18. **Averaging averages.** `AVG` is algebraic, not distributive: the mean of per-group means weights a group of 1 like a group of 10,000. Store `SUM` and `COUNT` in summary tables and divide at read time; for ratios, store numerator and denominator.
19. **Assuming the grouping key is byte equality.** It is a comparison under the column's collation. SQL Server's usual default is case-insensitive and ignores trailing spaces; MySQL 8's default is case- *and* accent-insensitive but treats trailing spaces as significant; PostgreSQL's default is deterministic. The same `GROUP BY` returns a different number of rows on each. Normalise the key (`lower(btrim(x))`) and index that expression.
20. **Expecting `LIMIT` to make a grouped Top-N cheap.** Every group must be aggregated before any can be ranked; the limit only bounds the sort (`top-N heapsort` / `TopN Sort`). `OFFSET` pagination over an aggregate re-aggregates the whole table per page, and keyset pagination can't help because the sort key isn't stored anywhere.
21. **`GroupBy` as the final operator in EF Core 7+.** It no longer throws — it groups on the client, after selecting every row and column with an `ORDER BY` on the key. Correct answers, memory proportional to the table. Project key + aggregates instead, and read the generated SQL.
22. **Over-wide `CUBE` on SQL Server.** The maximum is 32 expressions and 4,096 grouping sets, and duplicate sets are not consolidated — `GROUPING SETS ((), CUBE(a, b))` emits the grand total twice.

## Interview-ready summary

- **Aggregate functions:** `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `STRING_AGG`/`GROUP_CONCAT`.
- **`GROUP BY`** collapses rows by group columns. **All non-aggregated columns must be in `GROUP BY`** (per standard SQL).
- **`WHERE` filters rows; `HAVING` filters groups.** Aggregates only valid in HAVING / SELECT / ORDER BY.
- **`COUNT(*)`** counts rows (NULLs included). **`COUNT(col)`** skips NULL. **`COUNT(DISTINCT col)`** = unique count.
- **Conditional aggregation** (`SUM(CASE WHEN ...)`) replaces vendor-specific PIVOT.
- **`ROLLUP` / `CUBE` / `GROUPING SETS`** for multi-level subtotals in one query.

**Expected interview questions:**

1. *"WHERE vs HAVING?"* — WHERE filters rows pre-grouping. HAVING filters groups post-aggregation. Aggregate functions can't appear in WHERE.
2. *"Find customers with more than 5 orders."* — `SELECT customer_id FROM orders GROUP BY customer_id HAVING COUNT(*) > 5;`
3. *"How would you find duplicates?"* — `SELECT col, COUNT(*) FROM t GROUP BY col HAVING COUNT(*) > 1;`
4. *"`COUNT(*)` vs `COUNT(col)` vs `COUNT(DISTINCT col)`?"* — Total rows / non-NULL count / unique non-NULL count.
5. *"Calculate average order value, ignoring cancelled orders."* — `SELECT AVG(total) FROM orders WHERE status <> 'Cancelled';` or `SELECT AVG(CASE WHEN status <> 'Cancelled' THEN total END) FROM orders;` (CASE returns NULL for cancelled; AVG ignores NULL).
6. *"Pivot months across columns."* — Conditional aggregation: `SUM(CASE WHEN month = 'Jan' THEN sales END) AS jan, ...`.
7. *"What's `ROLLUP`?"* — Generates hierarchical subtotals: per-key + intermediate aggregates + grand total in one query. (Engine note: MySQL has ROLLUP only — no CUBE, no GROUPING SETS.)
8. *"How does the engine actually execute a GROUP BY?"* — Hash aggregate (one accumulator per group in a hash table, memory proportional to group count, output unordered) or stream/sort aggregate (input already ordered by the key, constant memory, output ordered). The optimizer picks on estimated group count and whether an index already supplies the order.
9. *"This grouped report got slow after the table grew. How do you diagnose it?"* — Read the actual plan. Which aggregate operator? Did it spill (PostgreSQL: `Batches`/`Disk Usage` on the HashAggregate, `Sort Method: external merge`; SQL Server: the spill-to-`tempdb` warning)? Compare estimated versus actual rows on the aggregate — a bad multi-column group estimate is the usual root cause, fixed with extended/multi-column statistics. Then ask whether an index can supply order and coverage, and whether the result should be pre-aggregated at all.
10. *"Why is `SELECT COUNT(*)` slow on a large table?"* — Because it isn't metadata. PostgreSQL and InnoDB must check per-row visibility against your snapshot; SQL Server scans the narrowest covering index. If an estimate is acceptable, read `pg_class.reltuples` or `sys.dm_db_partition_stats.row_count` instead.
11. *"How do you stop a reporting query blocking production?"* — Replica first. Otherwise row versioning (RCSI or SNAPSHOT on SQL Server; PostgreSQL and InnoDB readers already don't block writers), a covering index or a pre-aggregated table to make it cheap, and `NOLOCK` never — it can double-count or skip rows silently.
12. *"Which aggregates can you pre-compute and roll up, and which can't?"* — Distributive ones (`SUM`, `COUNT`, `MIN`, `MAX`) combine from partial results. Algebraic ones (`AVG`, `STDDEV`) combine if you carry the components — store `SUM` and `COUNT`, divide at read. Holistic ones (`COUNT(DISTINCT)`, median, mode) have unbounded intermediate state and cannot be combined at all; approximate them with a mergeable sketch or recompute. Gray et al.'s data-cube taxonomy, and it also explains why indexed views require `COUNT_BIG(*)` and forbid `AVG` and `MIN`/`MAX`.
13. *"Same `GROUP BY country` on SQL Server and PostgreSQL, different row counts. Why?"* — Grouping compares keys under the column's collation. SQL Server's typical default is case-insensitive and pads trailing spaces per SQL-92, so `'GB'`, `'gb'` and `'GB '` collapse into one group; PostgreSQL's default collation is deterministic and keeps them apart; MySQL 8's `utf8mb4_0900_ai_ci` is case- and accent-insensitive but `NO PAD`. NULLs form a single group on all three. Fix by normalising the key explicitly and indexing that expression.
14. *"`GROUP BY x ORDER BY SUM(y) DESC LIMIT 10` — does the limit make it cheaper?"* — Barely. Every group has to be finished before any can be ranked, so the scan and the aggregate are unchanged; the limit only bounds the sort (`Sort Method: top-N heapsort` in PostgreSQL, the `TopN Sort` operator in SQL Server). Paginating with `OFFSET` re-runs the whole aggregation per page. Materialise the ranked list, or pre-aggregate the measure.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — GROUP BY rules

> **Q**: Why does `SELECT customer_id, name, COUNT(*) FROM orders GROUP BY customer_id` fail in standard SQL?
>
> **A**: The "every non-aggregated column must be in GROUP BY" rule. `name` is neither aggregated nor in GROUP BY — the engine doesn't know which `name` to return for a group with multiple rows. Standard SQL rejects it. Old MySQL (non-strict mode) would return an indeterminate value silently.
>
> **Cross-Q**: Why does it work in Postgres even though `name` isn't in GROUP BY?
>
> **A**: Postgres allows it when `name` is **functionally dependent** on the GROUP BY column — concretely, when `customer_id` is the *primary key* of the `customers` table, which is the only case Postgres recognizes (its docs say so explicitly). This is optional feature T301 of SQL:1999; MySQL does the same detection under `ONLY_FULL_GROUP_BY` and goes further, also accepting a `UNIQUE NOT NULL` key. SQL Server does not — it rejects the query with error 8120 — and neither does Oracle. Portable code lists every column.
>
> **Cross-Q²**: What's the cost of writing portable GROUP BY?
>
> **A**: Trivial — just list every non-aggregated SELECT column in GROUP BY. The query reads slightly longer; the plan is identical (the optimizer knows about functional dependencies even when you spell them out). Portability win: query runs on any RDBMS. The only "gotcha" is that adding a non-aggregated column to SELECT later silently requires updating GROUP BY too — your test suite catches this.

### Drill 2 — HAVING vs WHERE

> **Q**: When does HAVING differ from WHERE in practice?
>
> **A**: WHERE filters **rows before grouping**; HAVING filters **groups after aggregation**. Aggregates can only appear in HAVING/SELECT/ORDER BY. Example: `WHERE age > 18` (row predicate, filter early) vs `HAVING COUNT(*) > 5` (group predicate, filter after aggregation).
>
> **Cross-Q**: I write `HAVING age > 18` and it works. Should I have used WHERE?
>
> **A**: Yes. Logically the engine groups every row first, including the under-18s, then drops the groups — so the aggregation is fed rows it will discard, and the penalty scales with how many of them there are. (PostgreSQL's planner actually rescues you here: an aggregate-free HAVING qual is moved into WHERE in `subquery_planner`. Don't rely on that elsewhere, and don't rely on the reader knowing it.) Rule: predicates referencing only row-level columns → WHERE; predicates on aggregates → HAVING. And check the semantics when you move one — `WHERE created_at >= :d … HAVING COUNT(*) > 5` and `HAVING COUNT(*) > 5 AND MAX(created_at) >= :d` are different questions.
>
> **Cross-Q²**: Can WHERE contain an aggregate via a subquery?
>
> **A**: Yes — `WHERE total > (SELECT AVG(total) FROM orders)`. The subquery is computed once (non-correlated), and the outer WHERE compares row values to the scalar result. This is row-level filtering using an aggregate from elsewhere, not aggregating the current row's group. Distinct from `HAVING SUM(total) > 100` which aggregates the current group's rows.

### Drill 3 — GROUPING SETS / ROLLUP / CUBE

> **Q**: What does ROLLUP add over plain GROUP BY?
>
> **A**: Subtotals at every level of the column hierarchy, plus a grand total — in one query. `GROUP BY ROLLUP (country, status)` returns: each `(country, status)` group + each `country` subtotal (status NULL) + the grand total (both NULL). Equivalent to a series of UNION ALL'd GROUP BYs but executed in one pass.
>
> **Cross-Q**: How is CUBE different?
>
> **A**: CUBE gives every combination of subtotals — for two columns, that's `(country, status)`, `(country)`, `(status)`, and `()` (grand total). ROLLUP only goes left-to-right hierarchically: `(country, status)` → `(country)` → `()`, missing the `(status)` aggregate. Use CUBE when every cross-section is interesting; ROLLUP when there's a clear drill-down hierarchy.
>
> **Cross-Q²**: How do you tell "subtotal NULL" apart from a real NULL in your data?
>
> **A**: `GROUPING(col)` returns 1 if the row is a subtotal-NULL, 0 if it's a real value (including a real NULL). Wrap with CASE: `CASE WHEN GROUPING(country) = 1 THEN 'TOTAL' ELSE country END`. Without GROUPING, you can't distinguish "country = NULL because it's the grand total row" from "country = NULL because some customers have no country" — they look identical in the result.

### Drill 4 — NULL handling in aggregates

> **Q**: How does `COUNT(*)` differ from `COUNT(col)`?
>
> **A**: `COUNT(*)` counts **rows** (NULLs included). `COUNT(col)` counts rows where `col` IS NOT NULL. So `SELECT COUNT(*), COUNT(email) FROM users` on a table where 30% of users have NULL email returns total_rows and 70%*total_rows.
>
> **Cross-Q**: What's the gotcha with `SUM` on all-NULL input?
>
> **A**: `SUM` returns **NULL**, not 0. `SELECT SUM(amount) FROM payments WHERE customer_id = 999` (no rows) returns NULL — the entire scalar is NULL. Code that does arithmetic on the result blows up: `revenue - SUM(refunds)` becomes NULL. Defensive: `COALESCE(SUM(amount), 0)` returns 0 for empty/all-NULL input.
>
> **Cross-Q²**: Does `AVG(col)` divide by `COUNT(*)` or `COUNT(col)`?
>
> **A**: `COUNT(col)` — the count of non-NULL values. `AVG` ignores NULLs in both numerator and denominator. So `AVG(rating)` on a table where 80% of `rating` is NULL averages only the 20% non-NULL values, not 80% of (rating-sum / total-rows). This is usually what you want, but it's worth knowing if "average rating across all users (including 0 for unrated)" is your intent — then use `COALESCE(rating, 0)` first or `SUM(rating)/COUNT(*)`.

### Drill 5 — DISTINCT vs GROUP BY

> **Q**: `SELECT DISTINCT customer_id FROM orders` vs `SELECT customer_id FROM orders GROUP BY customer_id` — same result?
>
> **A**: Yes, identical result set. Both produce unique customer_ids. Most modern optimizers also produce identical plans — both hash-dedupe or sort-dedupe the values.
>
> **Cross-Q**: Why might performance differ on some engines?
>
> **A**: Rarely, and not for the reason folklore gives. MySQL's manual is explicit that the two are the same problem — "In most cases, a `DISTINCT` clause can be considered as a special case of `GROUP BY`" — and that "the optimizations applicable to `GROUP BY` queries can be also applied to queries with a `DISTINCT` clause", so the loose index scan is available to both. Where they genuinely diverge is `LIMIT`: the same manual notes that "when combining `LIMIT row_count` with `DISTINCT`, MySQL stops as soon as it finds `row_count` unique rows", which a `GROUP BY` carrying aggregates cannot do because every group must be finished before any of them is correct. Verify with `EXPLAIN` if you care; otherwise either form is fine.
>
> **Cross-Q²**: When is DISTINCT clearly wrong?
>
> **A**: When it's masking a join bug. `SELECT DISTINCT customer_id FROM orders o JOIN order_items oi ON ...` returns unique customers, but if you expected one row per customer, the JOIN is creating duplicates — DISTINCT hides the multiplication. Investigate first: is the JOIN shape right? Should it be a semi-join (`EXISTS`)? DISTINCT after a multi-row JOIN often indicates "I should have written EXISTS."

### Drill 6 — ALL keyword

> **Q**: What does `COUNT(ALL col)` mean?
>
> **A**: `ALL` is the default — counts every non-NULL value including duplicates. `COUNT(ALL col)` ≡ `COUNT(col)`. Same for `SUM(ALL col)` ≡ `SUM(col)`. It exists for explicitness when contrasting with `DISTINCT`: `COUNT(DISTINCT col)` is unique, `COUNT(ALL col)` is everything.
>
> **Cross-Q**: When do you actually see `ALL` used?
>
> **A**: Almost never. It's mostly a SQL-standard formality. The exception is `UNION ALL` vs `UNION DISTINCT` — there ALL is non-default (UNION defaults to DISTINCT, UNION ALL is opt-in). In aggregates, ALL is implicit, so it's redundant. You'll see it in formal SQL textbooks more than in real code.
>
> **Cross-Q²**: Does `ALL` change the plan?
>
> **A**: No — the optimizer treats `COUNT(ALL col)` and `COUNT(col)` identically. Both compile to the same operator. ALL is syntactic noise that some style guides accept and others forbid for clarity.

### Drill 7 — Filtered aggregates with CASE

> **Q**: How do you count "orders with status = 'Cancelled'" in the same query as total order count?
>
> **A**: Conditional aggregation: `SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled, COUNT(*) AS total FROM orders`. The CASE returns 1 for matching rows and 0 otherwise; SUM totals them. Single pass over the table.
>
> **Cross-Q**: Postgres has a cleaner syntax — `FILTER`. Show me.
>
> **A**: `COUNT(*) FILTER (WHERE status = 'Cancelled') AS cancelled, COUNT(*) AS total FROM orders`. The `FILTER` clause restricts which rows feed into each aggregate. Cleaner than CASE for readability; same plan in Postgres. It is standard SQL — SQL:2003, optional feature T612 — but thinly implemented: PostgreSQL (9.4+) and SQLite have it; **SQL Server does not**, including in the 2025 release, whose new aggregate surface added `PRODUCT` and `JSON_ARRAYAGG` but no `FILTER`. The CASE form is the portable fallback, and the one to write in code that has to run on both.
>
> **Cross-Q²**: Is `COUNT(CASE WHEN p THEN 1 END)` equivalent to `SUM(CASE WHEN p THEN 1 ELSE 0 END)`?
>
> **A**: Yes, with the trick: `COUNT` ignores NULLs, so omitting `ELSE` makes non-matching rows produce NULL → not counted. `COUNT(CASE WHEN status='X' THEN 1 END)` is shorter and equivalent. Three forms — SUM(CASE), COUNT(CASE without ELSE), and FILTER — all do the same thing; pick what your team finds readable.

### Drill 8 — Multi-aggregate single-pass

> **Q**: I need order_count, total_revenue, avg_order_value, and max_order in one report. One query or four?
>
> **A**: One. `SELECT COUNT(*), SUM(total), AVG(total), MAX(total) FROM orders WHERE created_at >= '2025-01-01'`. The engine scans the table once and computes all four aggregates in a single pass. Four separate queries scan the same rows four times, and each one pays the round-trip and the plan lookup as well.
>
> **Cross-Q**: Does the optimizer rewrite four separate queries into one?
>
> **A**: No — separate queries are separate plans, separate scans. The optimizer's scope is one statement at a time. Some application-layer ORMs or connection-pool tools can batch round-trips but won't merge the scans server-side. If you control the SQL, combine the aggregates; if you can't (multiple consumers each calling their own aggregate query), consider materializing the source into a temp table once and querying it four times — temp table reads are cheap vs base table.
>
> **Cross-Q²**: When does multi-aggregate hurt rather than help?
>
> **A**: When the aggregates need different WHERE clauses — `SUM(total) WHERE status='Paid'` vs `SUM(total) WHERE status='Refunded'`. You can express these via conditional aggregation (`SUM(CASE WHEN status='Paid' THEN total ELSE 0 END)`), but if the predicates are highly selective, scanning all rows to compute both is wasteful. Sometimes two indexed queries on selective filters beat one scan. Profile both.

### Drill 9 — FIRST_VALUE / LAST_VALUE alternatives

> **Q**: How do you get "the first order date per customer" in standard SQL without window functions?
>
> **A**: `MIN(created_at)` per customer: `SELECT customer_id, MIN(created_at) FROM orders GROUP BY customer_id`. For temporal "first," MIN of the timestamp works. The result is the value of `created_at`, not the row containing it.
>
> **Cross-Q**: What if I need the full row (every column) of the first order, not just the date?
>
> **A**: Two patterns. (1) Self-join: `SELECT o.* FROM orders o JOIN (SELECT customer_id, MIN(created_at) AS first_dt FROM orders GROUP BY customer_id) f ON o.customer_id = f.customer_id AND o.created_at = f.first_dt`. (2) Window function: `SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at) AS rn FROM orders) WHERE rn = 1`. Window function is cleaner and handles ties (with `ROW_NUMBER`); self-join can return multiple rows if `created_at` ties.
>
> **Cross-Q²**: What's the gotcha with ties?
>
> **A**: If two orders have the same `created_at` for one customer, the self-join returns both — sometimes desired, sometimes not. `ROW_NUMBER` picks one (deterministically if the ORDER BY has a tiebreaker like `id`). `RANK`/`DENSE_RANK` would return both. Be explicit about the tiebreaker; "first" is ambiguous without it. Document the rule: "first by created_at, breaking ties on id ascending."

### Drill 10 — Conditional sums for KPI dashboards

> **Q**: Show me a single query that computes today's total revenue, total refunds, and net revenue.
>
> **A**: `SELECT SUM(CASE WHEN type='Sale' THEN amount ELSE 0 END) AS revenue, SUM(CASE WHEN type='Refund' THEN amount ELSE 0 END) AS refunds, SUM(CASE WHEN type='Sale' THEN amount ELSE -amount END) AS net FROM transactions WHERE date = CURRENT_DATE`. Three conditional sums, one scan.
>
> **Cross-Q**: What if "refund" amounts are stored as negative numbers already?
>
> **A**: Then net is just `SUM(amount)`. Schema design matters: signed amounts simplify aggregation, unsigned + type column requires conditional logic. For audit/compliance, separate columns (amount + type) are often required so refunds can't be confused with negative sales. Pick the model that matches your reporting needs.
>
> **Cross-Q²**: How do you avoid integer overflow on a billion-row SUM?
>
> **A**: Cast to a wider type before summing: `SUM(amount::bigint)` (Postgres) or `SUM(CAST(amount AS BIGINT))` (SQL Server). If `amount` is INT (~2.1B max), and you're summing positive values, 1B rows × small average can overflow. Postgres `SUM(int) → bigint` automatically; SQL Server keeps the type. Know your engine's promotion rules; when in doubt, cast.

### Drill 11 — COUNT(*) vs COUNT(1)

> **Q**: Is `COUNT(*)` faster than `COUNT(1)`?
>
> **A**: No — they produce identical plans on every modern engine. Both count rows. The "COUNT(1) is faster" claim is a 1990s myth based on Oracle's early parser behavior. Today, COUNT(1), COUNT(*), and COUNT('any-constant') all compile to the same operator.
>
> **Cross-Q**: What about `COUNT(column)` for a NOT NULL column?
>
> **A**: Logically equivalent to `COUNT(*)` (every row has a non-NULL value), but the optimizer must verify the column is non-NULL — usually trivial with constraint metadata. Plan should match COUNT(*). The only meaningful distinction is `COUNT(nullable_column)` which actually filters NULLs, vs `COUNT(*)` which doesn't.
>
> **Cross-Q²**: Why do you sometimes see `SELECT COUNT(*) FROM (SELECT DISTINCT ...) sub`?
>
> **A**: Counting unique tuples. Engine support for the direct form varies: PostgreSQL takes a row constructor, `COUNT(DISTINCT (col_a, col_b))`; MySQL takes a list, `COUNT(DISTINCT col_a, col_b)`; SQL Server accepts neither, so the subquery *is* the way to write it there. Watch the NULL difference while you're at it — `SELECT COUNT(*) FROM (SELECT DISTINCT col …)` counts a NULL group as one, while `COUNT(DISTINCT col)` ignores NULLs entirely, so on a column that actually contains at least one NULL the two forms differ by exactly one.

### Drill 12 — MEDIAN computation

> **Q**: Standard SQL doesn't have MEDIAN. How do you compute it?
>
> **A**: `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY col)` — the standard "ordered-set" aggregate (Postgres, SQL Server 2012+, Oracle). For older dialects: `SELECT AVG(col) FROM (SELECT col, ROW_NUMBER() OVER (ORDER BY col) AS rn, COUNT(*) OVER () AS cnt FROM t) WHERE rn IN ((cnt+1)/2, (cnt+2)/2)` — picks the middle one (or two for even counts).
>
> **Cross-Q**: What's the difference between PERCENTILE_CONT and PERCENTILE_DISC?
>
> **A**: `CONT` (continuous) interpolates between values — for an even count, it averages the two middle values. `DISC` (discrete) picks one of the actual values — for an even count, the lower of the two middle ones. For median on continuous data (salaries, durations), CONT is conventional; for categorical-ordered data (rankings, grades), DISC is more meaningful.
>
> **Cross-Q²**: Why is median expensive?
>
> **A**: It requires sorting or a quickselect — O(N log N) or O(N) respectively, neither streamable. SUM/AVG/COUNT are streaming aggregates (one pass, constant memory, and the row can be forgotten immediately). MEDIAN has to materialize the whole set to find the middle, so its memory grows with the input and it spills. Approximate quantile sketches (t-digest, KLL — extensions in PostgreSQL, built in to some analytics engines) hold a fixed-size summary instead; the trade is an error bound you choose in advance against memory that no longer depends on row count. Quote the mechanism, not a speedup figure: the honest statement is "bounded memory and one pass, at a stated error tolerance".

### Drill 13 — MODE workaround

> **Q**: Standard SQL doesn't have MODE (most frequent value). How do you compute it?
>
> **A**: `SELECT col FROM t GROUP BY col ORDER BY COUNT(*) DESC LIMIT 1`. Group by the column, sort groups by count descending, take the top one. For ties, you get just the first arbitrarily; for "all modes," remove LIMIT and add `HAVING COUNT(*) = (SELECT MAX(c) FROM (SELECT COUNT(*) AS c FROM t GROUP BY col) sub)`.
>
> **Cross-Q**: Postgres has `MODE() WITHIN GROUP`. How does it work?
>
> **A**: `SELECT MODE() WITHIN GROUP (ORDER BY col) FROM t` — returns the most frequent value of `col`. Ordered-set aggregate, same family as PERCENTILE_CONT. Returns one value (ties broken by ORDER BY tiebreaker if specified, else arbitrarily). Concise but Postgres-only; the GROUP BY approach is portable.
>
> **Cross-Q²**: For categorical data with millions of distinct values, what's the perf cost?
>
> **A**: Grouping requires hashing or sorting every value — O(N) memory for hash or O(N log N) for sort. Plus a top-1 over the resulting groups, which is cheap. The dominant cost is the grouping. For a high-cardinality column (millions of distinct values), the hash table fits poorly in memory; consider sampling or approximate-top-K algorithms (Misra-Gries, Space-Saving) if exact mode isn't required.

### Drill 14 — STRING_AGG / LISTAGG / GROUP_CONCAT

> **Q**: How do you produce a comma-separated list of order IDs per customer?
>
> **A**: Depends on dialect. Postgres/SQL Server 2017+: `STRING_AGG(order_id::text, ',')`. MySQL: `GROUP_CONCAT(order_id SEPARATOR ',')`. Oracle: `LISTAGG(order_id, ',') WITHIN GROUP (ORDER BY order_id)`. Same concept, three syntaxes.
>
> **Cross-Q**: What's the ordering guarantee?
>
> **A**: None by default — the engine concatenates in whatever order rows arrive (often hash-bucket order, not source order). For deterministic output, add ORDER BY inside the aggregate: `STRING_AGG(x, ',' ORDER BY x)`, `GROUP_CONCAT(x ORDER BY x SEPARATOR ',')`, `LISTAGG(x, ',') WITHIN GROUP (ORDER BY x)`. Without it, the same query can produce different strings across runs — flaky tests, mysterious diffs.
>
> **Cross-Q²**: What's the length cap?
>
> **A**: MySQL: `group_concat_max_len`, default 1024 bytes, session-settable — and it **truncates silently** (a warning is raised that most drivers never show you). SQL Server: the return type follows the *input* type, so a plain `varchar`/`nvarchar` column gives `varchar(8000)`/`nvarchar(4000)` and overflow is a hard **error 9829**, "STRING_AGG aggregation result exceeded the limit of 8000 bytes. Use LOB types to avoid result truncation" — convert the input, `STRING_AGG(CONVERT(NVARCHAR(MAX), col), ',')`, exactly as Microsoft's own examples do. PostgreSQL: `text`, bounded by the 1 GB field limit, no practical cap here. Oracle `LISTAGG`: `VARCHAR2`, so `ORA-01489` past 4000 bytes unless you write `ON OVERFLOW TRUNCATE` (12.2+) or switch to `XMLAGG`. Two different failure modes — silent truncation and a hard error — and both only appear for your largest group, so seed the test data with one.

### Drill 15 — Top-N per group: windows vs aggregation

> **Q**: "Top 3 orders per customer by total" — window function or GROUP BY?
>
> **A**: Window function: `SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY total DESC) AS rn FROM orders) WHERE rn <= 3`. Cannot easily be done with GROUP BY alone — GROUP BY collapses rows; you'd lose the individual order details.
>
> **Cross-Q**: When would APPLY/LATERAL beat the window function?
>
> **A**: When N is small (1-10) and there's an index on `(customer_id, total DESC)`. APPLY/LATERAL can seek that index once per customer and stop after N rows — work proportional to *customers × N*. The window function has to read every order, number it, and then discard almost all of them — work proportional to *total rows*. On 1M customers with 1000 orders each, that's roughly 3M rows touched versus 1B: the same asymptotic difference as an index seek versus a scan, which is why it matters here rather than any particular multiplier. Measure it on your data; the point to make in the interview is *why* the two plans differ, not a number.
>
> **Cross-Q²**: How do you handle ties — top 3 including all tied at position 3?
>
> **A**: Use `RANK()` instead of `ROW_NUMBER()`: `RANK() OVER (PARTITION BY customer_id ORDER BY total DESC) AS rk WHERE rk <= 3`. RANK assigns the same value to ties, so all rows tied at rank 3 are included (you might get 4 or 5 rows back if there are ties). `DENSE_RANK` is similar but doesn't skip rank numbers after ties. `ROW_NUMBER` arbitrarily breaks ties — deterministic count, arbitrary selection. Pick based on semantics: "include all tied" → RANK, "exactly N" → ROW_NUMBER + tiebreaker.

### Drill 16 — Rolling up a summary table

> **Q**: You have `daily_stats(day, region, order_count, gross, avg_order_value, unique_customers)`. Which columns can you use to answer a monthly question?
>
> **A**: `order_count` and `gross` — sum them. `avg_order_value` is unusable: `AVG` is *algebraic*, so the mean of daily means weights a quiet Sunday like a peak Monday. Compute it as `SUM(gross) / SUM(order_count)`, which is why storing both components was the right call and storing the average was not. `unique_customers` is *holistic* — a customer active on ten days contributes ten to the sum and one to the truth — so summing it gives an upper bound that grows with engagement, not a monthly figure. That column can only be recomputed over the month, or replaced by a mergeable HLL sketch.
>
> **Cross-Q**: Where does that classification come from, and what else does it explain?
>
> **A**: Gray et al.'s data-cube paper (1997): distributive (`SUM`, `COUNT`, `MIN`, `MAX`) computable from sub-aggregates; algebraic (`AVG`, `STDDEV`) computable from a bounded set of distributive components; holistic (`COUNT(DISTINCT)`, median, mode) with unbounded intermediate state. It's the same reason parallel plans can compute `AVG` as a `(sum, count)` pair per worker but struggle with `COUNT(DISTINCT)`, and the reason SQL Server's indexed views permit `SUM` but not `AVG`.
>
> **Cross-Q²**: `MIN`/`MAX` are distributive. Why does SQL Server still ban them in an indexed view with `GROUP BY`?
>
> **A**: Because incremental *maintenance* is a stricter requirement than distributivity. A `SUM` can be adjusted by a delta for every insert, update and delete without looking at other rows. Deleting the row that currently holds the maximum tells you nothing about the new maximum — the engine would have to re-read the group. Same reason the view definition must contain `COUNT_BIG(*)`: it is how the engine knows a group has emptied and its row must go.

### Drill 17 — Grouping keys and collation

> **Q**: `SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1` finds duplicates on your SQL Server staging box and almost none on the PostgreSQL replica. Same data. What happened?
>
> **A**: Grouping compares keys under the column's collation, not byte-for-byte. SQL Server's common default (`SQL_Latin1_General_CP1_CI_AS`) is case-insensitive, so `Bob@x.com` and `bob@x.com` land in one group. PostgreSQL's default collation is deterministic, so they are two groups and neither is a "duplicate". The duplicate count was a property of the collation, not of the data.
>
> **Cross-Q**: Any other axis where the two disagree?
>
> **A**: Trailing spaces. SQL Server follows the SQL-92 padding rule — the docs say it "considers the strings `'abc'` and `'abc '` to be equivalent for most comparison operations" — so `'GB'` and `'GB '` are one group. PostgreSQL treats them as different. MySQL 8 splits the difference in a way that catches people twice: its default `utf8mb4_0900_ai_ci` is case- *and accent*-insensitive (`café` groups with `cafe`), but because UCA 9.0.0 collations are `NO PAD`, trailing spaces *are* significant there.
>
> **Cross-Q²**: How do you make the grouping mean the same thing everywhere?
>
> **A**: Stop inheriting the semantics from the collation and state them: group on `lower(btrim(email))`, and index that expression so the plan doesn't lose the grouping order (PostgreSQL expression index, SQL Server `PERSISTED` computed column, MySQL 8 functional index). If you want case-insensitivity on PostgreSQL at the type level instead, `citext` or a nondeterministic ICU collation (12+) will do it — with the documented costs: "their use leads to a performance penalty", no B-tree deduplication, and some pattern-matching operations unavailable.

</details>

## Cheat Sheet

- **WHERE vs HAVING**: row-level filter before grouping; group-level filter after aggregation.
- **COUNT(*) vs COUNT(col)**: total rows including NULL vs non-NULL values only.
- **COUNT(DISTINCT)**: forces a sort/hash on the column; expensive on big sets, consider HLL approximation.
- **SUM returns NULL on all-NULL input**: wrap with `COALESCE(SUM(x), 0)` for "default zero".
- **Conditional aggregation**: `SUM(CASE WHEN p THEN 1 ELSE 0 END)`; portable pivot replacement.
- **GROUP BY rule**: every non-aggregated column in SELECT must appear in GROUP BY (standard SQL).
- **ROLLUP / CUBE / GROUPING SETS**: multi-level subtotals in one pass; use `GROUPING()` to label totals.
- **STRING_AGG / GROUP_CONCAT**: collapse strings within a group; watch dialect-specific length caps.
- **JOIN before GROUP BY can multiply rows**: pre-aggregate in a subquery to keep totals correct.
- **Integer division gotcha**: `SUM(int)/COUNT(*)` rounds; cast to float or multiply by 1.0. SQL Server's `AVG(int)` truncates too; PostgreSQL's returns `numeric`.
- **Hash vs stream aggregate**: hash = memory proportional to group count, output unordered; stream = ordered input, constant memory. `HashAggregate`/`GroupAggregate` (PostgreSQL), `Hash Match (Aggregate)`/`Stream Aggregate` (SQL Server).
- **Spills come from bad group-count estimates**: PostgreSQL spills past `work_mem × hash_mem_multiplier` (13+); SQL Server's memory grant is fixed at compile time and spills to `tempdb`. Fix the statistics, not the memory knob.
- **`COUNT(*)` after a LEFT JOIN returns 1 for childless parents**: count a column from the optional side.
- **`GROUP BY` does not order** — write `ORDER BY`. MySQL removed its incidental sorting in 8.0.
- **Empty input**: no `GROUP BY` → one row (`COUNT` 0, `SUM` NULL); with `GROUP BY` → zero rows; `HAVING` without `GROUP BY` can delete the only row.
- **Reporting isolation**: replica, or RCSI/`SNAPSHOT` on SQL Server. `NOLOCK` can count rows twice or not at all.
- **Approximate distinct**: `APPROX_COUNT_DISTINCT` on SQL Server 2019+ ("up to a 2% error rate within a 97% probability"); PostgreSQL needs an extension (`postgresql-hll`, DataSketches). Sketches merge, counts don't.
- **Distributive / algebraic / holistic** (Gray et al. 1997): `SUM`,`COUNT`,`MIN`,`MAX` roll up; `AVG`/`STDDEV` roll up only if you carry the components; `COUNT(DISTINCT)`/median/mode don't roll up at all. Summary tables store `SUM` and `COUNT`, never `AVG`.
- **Grouping key = comparison under the collation**: SQL Server default typically case-insensitive and pads trailing spaces; MySQL 8 `utf8mb4_0900_ai_ci` case- and accent-insensitive but `NO PAD`; PostgreSQL deterministic. NULLs form one group everywhere. Normalise and index the expression.
- **`LIMIT` doesn't shrink a grouped Top-N**: all groups must finish before ranking; the limit only bounds the sort. `OFFSET` paging re-aggregates per page — materialise the ranked list.
- **SQL Server grouping-set caps**: 32 expressions, 4,096 sets, duplicates not consolidated.
- **EF Core**: key + scalar aggregates → `GROUP BY`, aggregate predicate → `HAVING`; `GroupBy` as final operator groups on the *client* since 7.0; `Any()` → `EXISTS` (can stop early), `Count() > 0` → aggregate (can't). SQL `SUM` of nothing is NULL, `Enumerable.Sum` of nothing is 0 — coalesce deliberately.

## Walkthrough — Double-counted revenue from a bad join shape

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A finance dashboard shows monthly revenue 2.3x what the accounting system shows. The query joins orders, order_items, and payments and SUMs `order.total`.

**Diagnosis**: The senior runs the query in `psql` with `EXPLAIN ANALYZE` and inspects sample output:

```sql
SELECT o.id, o.total, oi.id AS item_id, p.id AS payment_id
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN payments p ON p.order_id = o.id
WHERE o.id = 12345
LIMIT 50;
```

Order 12345 has `total = 100`, 3 items, and 2 payment attempts (one declined, one approved). The query produces 6 rows for that order; `SUM(o.total)` becomes 600. The bug isn't visible in the dashboard until an order has multiple items AND multiple payments.

**Fix**: Pre-aggregate the multiplying side in a CTE before joining:

```sql
WITH order_totals AS (
    SELECT o.id, o.total, DATE_TRUNC('month', o.created_at) AS month
    FROM orders o
    WHERE o.created_at >= '2026-01-01'
),
items AS (
    SELECT order_id, COUNT(*) AS item_count
    FROM order_items GROUP BY order_id
),
payments AS (
    SELECT order_id, COUNT(*) FILTER (WHERE status = 'Approved') AS approved_count
    FROM payments GROUP BY order_id
)
SELECT month,
       SUM(ot.total) AS revenue,
       SUM(i.item_count) AS items,
       SUM(p.approved_count) AS approved_payments
FROM order_totals ot
LEFT JOIN items i ON i.order_id = ot.id
LEFT JOIN payments p ON p.order_id = ot.id
GROUP BY month
ORDER BY month;
```

Revenue now matches accounting.

**Why it works**: Each CTE produces one row per order, so the outer join is 1:1:1 instead of 1:N:M. Aggregation no longer multiplies. This pattern - pre-aggregate then join - is the canonical fix for "totals are too big" bugs.

</details>

## Self-test

<details><summary>1. <code>WHERE COUNT(*) &gt; 5</code> doesn't compile. Why?</summary>

Aggregates are computed at step 3 (after grouping). WHERE runs at step 2 - the count doesn't exist yet. Use HAVING (filters groups) or wrap in a subquery and filter outside.
</details>

<details><summary>2. Trade-off: <code>COUNT(DISTINCT user_id)</code> vs HyperLogLog approximation.</summary>

DISTINCT is exact but has to remember every value it has seen, so its memory grows with cardinality and it spills. HyperLogLog holds a fixed-size sketch instead, with relative accuracy 1.04/√m for m registers (Flajolet et al., 2007) — SQL Server's built-in `APPROX_COUNT_DISTINCT` (2019+) documents its own guarantee as "up to a 2% error rate within a 97% probability"; PostgreSQL needs an extension (`postgresql-hll`, Apache DataSketches). Use the exact count for invoices and audits; use a sketch for "approximate unique visitors", and because sketches merge, one stored per day answers any date range later.
</details>

<details><summary>3. Why does <code>SUM(CASE WHEN status='Cancelled' THEN 1 ELSE 0 END)</code> sometimes outperform <code>COUNT(*) FILTER (WHERE status='Cancelled')</code>?</summary>

On the engines that have both, they aren't really in competition: `FILTER` and `COUNT(CASE …)` translate to similar plans, and differences come down to indexes rather than syntax. The real distinction is availability — `FILTER` exists in PostgreSQL (9.4+) and SQLite, and not in SQL Server, so on a codebase that targets both, the CASE form is the only one that compiles.
</details>

<details><summary>4. <code>SELECT customer_id, name, COUNT(*) FROM orders JOIN customers ON ... GROUP BY customer_id</code> works in Postgres but not strict SQL. Why?</summary>

Strict SQL requires all non-aggregated columns in GROUP BY. Postgres relaxes this when `name` is functionally dependent on `customer_id` (PK of customers) — SQL:1999's optional feature T301, which MySQL also implements. SQL Server rejects it with error 8120, and so does Oracle; portable code lists every selected column in GROUP BY.
</details>

<details><summary>5. You need "average revenue per active customer" - active = at least one paid order in the last 30 days. How would you write it?</summary>

Two-step, and note that the metric is *per customer*, not per order — so you must aggregate to the customer grain first and only then average. Averaging `total` directly would answer "average order value among active customers", a different number.

```sql
WITH active AS (
    SELECT DISTINCT customer_id
    FROM orders
    WHERE status = 'Paid' AND created_at >= NOW() - INTERVAL '30 days'
),
per_customer AS (
    SELECT o.customer_id, SUM(o.total) AS revenue
    FROM orders o
    JOIN active a ON a.customer_id = o.customer_id
    GROUP BY o.customer_id
)
SELECT AVG(revenue) FROM per_customer;
```

`AVG` over a per-customer `SUM` is not the same as `AVG` over rows — see [Which aggregates roll up](#which-aggregates-roll-up--distributive-algebraic-holistic). Also put the activeness predicate in `WHERE` inside the CTE rather than in a `HAVING` over the whole table: `HAVING` would group every customer who ever ordered before discarding most of them.
</details>

<details><summary>6. A PostgreSQL plan shows <code>HashAggregate … Planned Partitions: 8  Batches: 9  Disk Usage: 412000kB</code>. What happened, and what are your first two moves?</summary>

The hash table for the groups didn't fit in `work_mem × hash_mem_multiplier`, so the aggregate partitioned itself and spilled to disk — that's what `Batches` above 1 and any `Disk Usage` mean. First move: compare the aggregate's estimated rows with actual. If the estimate is far low, the cause is the group-count estimate, and the fix is statistics — `CREATE STATISTICS … (ndistinct) ON a, b` for a multi-column GROUP BY — not more memory. Second move: check whether an index on the grouping columns lets it use a `GroupAggregate` instead, which needs constant memory and cannot spill for grouping (its `Sort` still can). Raising `work_mem` is the last resort, because it's granted per node per session, not per query.
</details>

<details><summary>7. Why does <code>SELECT c.id, COUNT(*) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id GROUP BY c.id</code> report 1 for a customer with no orders?</summary>

The LEFT JOIN preserves the customer as a single row with every `orders` column NULL. `COUNT(*)` counts rows, and that is a row. `COUNT(o.id)` counts non-NULL values of a column from the optional side and returns 0. The same trap applies to `COUNT(*)` in any query where the outer side can be unmatched.
</details>

<details><summary>8. Your daily table stores unique users per day. Why can't you sum 30 of those rows to get monthly uniques, and what would you store instead?</summary>

Distinct counts aren't additive — a user who visits on ten days contributes ten to the sum and one to the true monthly figure, so the sum is an upper bound that grows with engagement. Either recompute `COUNT(DISTINCT user_id)` over the month, or store a mergeable HyperLogLog sketch per day: the union of the sketches estimates the union of the sets, which is what a distinct count over a range actually is.
</details>

<details><summary>9. A month-end report blocks checkout on SQL Server. A colleague adds <code>WITH (NOLOCK)</code> and the blocking stops. What's your objection, and what do you do instead?</summary>

`NOLOCK` is `READ UNCOMMITTED`, and the documentation warns it "might generate errors for your transaction, present users with data that was never committed, or cause users to see records twice (or not at all)". For a `SUM` that means a total wrong by an unknown amount, with no error — the worst possible failure for a financial report. The blocking exists because the default READ COMMITTED takes shared locks when `READ_COMMITTED_SNAPSHOT` is OFF; turn RCSI on (it's already the default on Azure SQL Database) or run under `SNAPSHOT`, and the read becomes non-blocking *and* consistent. Better still, run it on a replica, and make it cheap with a covering index or a pre-aggregated table.
</details>

<details><summary>10. On SQL Server, a <code>STRING_AGG</code> that builds an item list works for every customer except one, where the statement fails. Why?</summary>

`STRING_AGG`'s return type comes from its input: a non-`MAX` `nvarchar` column yields `nvarchar(4000)`, and exceeding it raises error 9829, "STRING_AGG aggregation result exceeded the limit of 8000 bytes. Use LOB types to avoid result truncation." Only the group whose concatenation crosses the limit fails, which is why it looks customer-specific. Fix: `STRING_AGG(CONVERT(NVARCHAR(MAX), col), ', ')`. On MySQL the same shape of bug is worse to find, because `group_concat_max_len` truncates instead of erroring.
</details>

<details><summary>11. Your daily summary table stores <code>avg_order_value</code>. The monthly tile averages the 30 rows. What's wrong, and what should the table have stored?</summary>

`AVG` is algebraic, not distributive — it cannot be computed from other averages, only from `SUM` and `COUNT`. Averaging daily averages weights a day with 3 orders exactly like a day with 300,000, so the monthly figure tracks the quiet days. Store `gross` and `order_count` and compute `SUM(gross) / SUM(order_count)` at read time. The same rule kills stored ratios: keep numerator and denominator, divide last. `unique_customers` in that table is worse still — it's holistic, so it can't be rolled up by any arithmetic; recompute it or store a mergeable sketch.
</details>

<details><summary>12. The same <code>GROUP BY city</code> report returns 4,812 rows on SQL Server and 5,109 on PostgreSQL against identical data. Explain, without calling either one wrong.</summary>

Grouping puts rows together when their keys compare equal *under the column's collation*. SQL Server's usual default collation is case-insensitive, and it follows the SQL-92 padding rule, so `'York'`, `'york'` and `'York '` all collapse into one group. PostgreSQL's default collation is deterministic: three groups. MySQL 8 would give yet another answer — `utf8mb4_0900_ai_ci` folds case *and* accents but is `NO PAD`, so trailing spaces split groups there. Neither engine is wrong; the query never said what "the same city" means. Say it: `GROUP BY lower(btrim(city))`, with an index on that expression.
</details>

<details><summary>13. Why doesn't <code>ORDER BY SUM(total) DESC LIMIT 10</code> let the engine skip most of the work, and what would?</summary>

Ranking requires every group to be final — the last row read could belong to the customer who ends up first — so the scan and the aggregation are unaffected by the limit. The only saving is a bounded sort that keeps ten rows instead of all of them (`Sort Method: top-N heapsort` in PostgreSQL, the `TopN Sort` operator in SQL Server). What actually reduces the work: shrinking the input with a `WHERE` on a date range, a covering index so the scan is narrow, or pre-aggregating the measure so the ranked list is read rather than computed. And if this is paginated, don't use `OFFSET` — each page re-aggregates the table, and keyset pagination can't rescue it because the sort key is computed, not stored.
</details>

<details><summary>14. In EF Core, <code>db.Orders.GroupBy(o =&gt; o.CustomerId).ToList()</code> throws on version 6 and works on version 7. Is that an improvement?</summary>

It's a trade. There is no SQL construct for an `IGrouping`, so EF Core 7.0 and later build the groups on the client after the fact — the docs say "the GroupBy operator doesn't translate directly to a `GROUP BY` clause in the SQL, but instead, EF Core creates the groupings after the results are returned from the server" — and the SQL is a full `SELECT <columns> FROM Orders ORDER BY CustomerId`. Right answers, memory and network proportional to the table, and no exception to tell you. On version 6 the failure was loud and forced a translatable rewrite (key plus scalar aggregates, which becomes a real `GROUP BY`, with an aggregate predicate becoming `HAVING`). Treat the 7.0 behaviour as a convenience for small sets and read the generated SQL for anything else.
</details>

## Cross-references

- [Fundamentals](./01-fundamentals.md) — basic SELECT mechanics.
- [Joins & Set Operations](./02-joins-and-set-operations.md) — joins precede most aggregations.
- [Subqueries & CTEs](./04-subqueries-and-ctes.md) — pre-aggregating in a subquery before joining.
- [Window Functions](./05-window-functions.md) — non-collapsing aggregations (`SUM() OVER (...)`).
- [Indexes & Query Optimization](./06-indexes-and-query-optimization.md) — covering indexes for GROUP BY queries.
- [EF Core](../01-ef-core.md) — the ORM that generates these GROUP BY statements.
- [LINQ](../02-linq.md) — `GroupBy`, `Sum`, `Any` and what they become.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *SQL Cookbook* by Anthony Molinaro — chapter on grouping and aggregating.
- PostgreSQL — [Aggregate Functions](https://www.postgresql.org/docs/current/functions-aggregate.html) and [aggregate expressions, including `FILTER` and in-aggregate `ORDER BY`](https://www.postgresql.org/docs/current/sql-expressions.html).
- *Joe Celko's SQL for Smarties* — advanced GROUP BY patterns including ROLLUP/CUBE.
- LeetCode SQL Easy/Medium problems on aggregations.

Used for the specifics on this page:

- PostgreSQL — [Resource consumption (`work_mem`, `hash_mem_multiplier`)](https://www.postgresql.org/docs/current/runtime-config-resource.html) and the [13 release notes](https://www.postgresql.org/docs/release/13.0/) for hash aggregation spilling to disk.
- PostgreSQL — [Statistics used by the planner](https://www.postgresql.org/docs/current/planner-stats.html) (multivariate n-distinct for `GROUP BY a, b`), [index-only scans and the visibility map](https://www.postgresql.org/docs/current/indexes-index-only-scans.html), [`pg_class.reltuples`](https://www.postgresql.org/docs/current/catalog-pg-class.html), [`REFRESH MATERIALIZED VIEW`](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html), [`SELECT`](https://www.postgresql.org/docs/current/sql-select.html) (functional dependency recognized only via the primary key).
- Microsoft Learn — [`COUNT`](https://learn.microsoft.com/en-us/sql/t-sql/functions/count-transact-sql) (int overflow, `COUNT_BIG`), [`STRING_AGG`](https://learn.microsoft.com/en-us/sql/t-sql/functions/string-agg-transact-sql) (return types, `WITHIN GROUP`), [`APPROX_COUNT_DISTINCT`](https://learn.microsoft.com/en-us/sql/t-sql/functions/approx-count-distinct-transact-sql), [Create indexed views](https://learn.microsoft.com/en-us/sql/relational-databases/views/create-indexed-views), [Table hints](https://learn.microsoft.com/en-us/sql/t-sql/queries/hints-transact-sql-table) (READCOMMITTED locking vs versioning, NOLOCK), [Transaction locking and row versioning guide](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-transaction-locking-and-row-versioning-guide) (lock escalation goes straight to table locks, never page locks), [`sys.dm_db_partition_stats`](https://learn.microsoft.com/en-us/sql/relational-databases/system-dynamic-management-views/sys-dm-db-partition-stats-transact-sql).
- MySQL 8 manual — [GROUP BY handling and functional dependence](https://dev.mysql.com/doc/refman/8.4/en/group-by-handling.html), [GROUP BY modifiers](https://dev.mysql.com/doc/refman/8.4/en/group-by-modifiers.html) (ROLLUP only), [GROUP BY optimization](https://dev.mysql.com/doc/refman/8.4/en/group-by-optimization.html) (loose/tight index scan), [ORDER BY optimization](https://dev.mysql.com/doc/refman/8.0/en/order-by-optimization.html) (no implicit GROUP BY sort since 8.0).
- Flajolet, Fusy, Gandouet, Meunier — *HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm* (2007), for the 1.04/√m accuracy result.
- Markus Winand — [The FILTER clause](https://modern-sql.com/feature/filter) (SQL:2003 feature T612 and the CASE equivalent).
- Gray, Chaudhuri, Bosworth, Layman, Reichart, Venkatrao, Pellow, Pirahesh — [*Data Cube: A Relational Aggregation Operator Generalizing Group-By, Cross-Tab, and Sub-Totals*](https://link.springer.com/article/10.1023/A:1009726021843), Data Mining and Knowledge Discovery 1(1), 1997 — the distributive / algebraic / holistic classification.
- Microsoft Learn — [`GROUP BY` (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/select-group-by-transact-sql) (NULLs collected into a single group; the 32-expression / 4,096-group limits on `ROLLUP`/`CUBE`/`GROUPING SETS`; duplicate grouping sets not consolidated; `GROUP BY` does not order), [`=` string comparison](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/string-comparison-assignment) (ANSI/ISO SQL-92 padding, `'abc'` = `'abc '`), [Showplan logical and physical operators reference](https://learn.microsoft.com/en-us/sql/relational-databases/showplan-logical-and-physical-operators-reference) (`TopN Sort`, `Hash Match`, `Stream Aggregate`).
- MySQL 8.4 manual — [Character set and collation pad attributes](https://dev.mysql.com/doc/refman/8.4/en/charset-binary-collations.html) (`PAD SPACE` vs `NO PAD`), [Unicode character sets](https://dev.mysql.com/doc/refman/8.4/en/charset-unicode-sets.html) (`utf8mb4_0900_ai_ci`, UCA 9.0.0, accent- and case-insensitive), [DISTINCT optimization](https://dev.mysql.com/doc/refman/8.4/en/distinct-optimization.html) (DISTINCT as a special case of GROUP BY; `LIMIT` early exit).
- PostgreSQL — [Collation support](https://www.postgresql.org/docs/current/collation.html) (deterministic vs nondeterministic collations and their costs) and the [12 release notes](https://www.postgresql.org/docs/release/12.0/) for nondeterministic ICU collations.
- EF Core docs — [Complex query operators](https://learn.microsoft.com/en-us/ef/core/querying/complex-query-operators) (which `GroupBy` shapes translate, `HAVING`, the provider-agnostic aggregate mappings, and client-side grouping from EF Core 7.0) and [SQL Server function mappings](https://learn.microsoft.com/en-us/ef/core/providers/sql-server/functions) (`Count()` → `COUNT(*)`, `LongCount()` → `COUNT_BIG(*)`). Issues referenced: [#19929](https://github.com/dotnet/efcore/issues/19929) (GroupBy as final operator), [#27953](https://github.com/dotnet/efcore/issues/27953) (`Count() == 0` vs `!Any()` translations), [#17492](https://github.com/dotnet/efcore/issues/17492) / [#28158](https://github.com/dotnet/efcore/issues/28158) / [#35950](https://github.com/dotnet/efcore/issues/35950) (where `COALESCE` lands around aggregates and `DefaultIfEmpty`).

<!-- nav-footer-start -->

---

[← Previous: SQL Joins — Deep Dive](02-joins-deep-dive.md) · [↑ Back to top](#aggregation--grouping) · [Next: Subqueries & CTEs →](04-subqueries-and-ctes.md)

<!-- nav-footer-end -->

</details>
