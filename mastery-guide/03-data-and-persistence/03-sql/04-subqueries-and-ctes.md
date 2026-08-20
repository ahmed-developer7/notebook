# Subqueries & CTEs

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › [SQL Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-08 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Subquery — query inside a query](#subquery--query-inside-a-query)
  - [Scalar, row, table subqueries](#scalar-row-table-subqueries)
  - [Correlated vs non-correlated](#correlated-vs-non-correlated)
  - [EXISTS, IN, ANY, ALL](#exists-in-any-all)
  - [CTEs (Common Table Expressions)](#ctes-common-table-expressions)
  - [Recursive CTEs](#recursive-ctes)
  - [CTEs vs subqueries vs views vs temp tables](#ctes-vs-subqueries-vs-views-vs-temp-tables)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--recursive-cte-runaway-on-a-cyclic-graph)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Subqueries and CTEs are how SQL composes. A single complex business question — "find customers whose largest order exceeds the company average" — is awkward as one giant SELECT but elegant when broken into named building blocks. CTEs especially have transformed modern SQL writing: queries that used to span 30 unreadable lines now read top-to-bottom like prose.

For interviews, "use a CTE" is a frequent recommended path; for production, CTEs (or subqueries) make complex transformations maintainable. Recursive CTEs unlock a category of problems (hierarchies, paths, generated sequences) that flat SQL can't express at all.

When NOT to use: simple queries don't need subqueries or CTEs. Adding them prematurely just adds layers. Use them when the query has a logical *step* you'd want to name.

Composition is free when you write the query and not free when the engine runs it. Whether a named step is computed once, computed again per reference, or dissolved into the surrounding query is not a property of SQL — it is a property of your engine and its version, and the three engines a .NET shop typically meets answer differently. SQL Server's documentation states flatly that "query results from common table expressions aren't materialized. Each outer reference to the named result set requires the defined query to be re-executed." PostgreSQL inlines a CTE referenced once and materialises one referenced twice. MySQL merges a CTE into the parent whenever the definition allows it, and when it cannot, materialises it once and reuses that one temporary table for every reference. Same query text, three execution contracts. The senior version of this topic is knowing which contract you are relying on and being able to point at the line in the plan that proves it.

> 🌍 **In the real world**: a "customers at risk" report grew from one subquery to five nested levels over two years, each level added by a different person. Nobody could say what the innermost `SELECT` filtered. A rewrite into five named CTEs produced an identical plan and identical timings — and in review someone finally noticed that the tenant predicate was applied only at the innermost level, so one tenant's orders had been counted in another tenant's totals wherever the outer levels joined across. The rewrite bought no performance at all. It bought the review that found a data-leak bug.

## Core concepts

### Subquery — query inside a query

A subquery is a SELECT inside another statement. It can appear in:
- **`SELECT` list** (scalar subquery): `SELECT id, (SELECT MAX(total) FROM orders WHERE customer_id = c.id) FROM customers c;`
- **`FROM` clause** (derived table): `SELECT * FROM (SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id) sub WHERE sub.count > 5;`
- **`WHERE` clause** (predicate): `SELECT * FROM customers WHERE id IN (SELECT customer_id FROM orders);`
- **`HAVING` clause** (group predicate): rare but possible.
- **`UPDATE` / `DELETE`** (set values or filter): `UPDATE customers SET active = false WHERE id NOT IN (SELECT customer_id FROM orders);` — *this exact line is the classic landmine: the day `orders.customer_id` becomes nullable, the statement updates nothing. See [`NOT IN` with NULLs](#exists-in-any-all).*

Every subquery is parenthesized and treated as a virtual table or value.

### Scalar, row, table subqueries

Three flavors based on what they return:

**Scalar subquery** — single value (one row, one column):

```sql
-- For each customer, show their last order date
SELECT
    c.id, c.name,
    (SELECT MAX(created_at) FROM orders o WHERE o.customer_id = c.id) AS last_order
FROM customers c;
```

If the subquery returns more than one row, runtime error — and each engine has its own wording, which is worth recognising in a log: PostgreSQL says `more than one row returned by a subquery used as an expression`; SQL Server raises error 512, `Subquery returned more than 1 value. This is not permitted when the subquery follows =, !=, <, <=, >, >= or when the subquery is used as an expression.`; MySQL raises `ERROR 1242 (21000): Subquery returns more than 1 row`.

The asymmetry matters: **zero rows is not an error**. A scalar subquery that matches nothing yields NULL, so a customer with no orders silently produces `NULL` rather than failing, and any arithmetic downstream of it produces NULL too. The multi-row case fails loudly; the no-row case fails quietly. Wrap it in `COALESCE` when the caller expects a number.

**Row subquery** — single row, multiple columns:

```sql
-- Find the customer matching a specific (name, country) pair
SELECT * FROM customers
WHERE (name, country) = (SELECT name, country FROM staging WHERE id = 1);
```

Less common, and the dialect split is sharp: **PostgreSQL and MySQL support row-value comparison; T-SQL has no row constructor in a comparison**, so `WHERE (name, country) = (SELECT ...)` is a syntax error on SQL Server. Rewrite it there as two correlated comparisons, or as `EXISTS (SELECT s.name, s.country INTERSECT SELECT c.name, c.country)` when you want NULL-equals-NULL semantics — `INTERSECT` compares rows with NULL treated as equal, which is the one T-SQL construct that gives you `IS NOT DISTINCT FROM` behaviour across a whole row.

**Table subquery (derived table)** — multiple rows / columns:

```sql
-- Two-step aggregation: per-customer totals, then top 5
SELECT *
FROM (
    SELECT customer_id, SUM(total) AS spent
    FROM orders
    GROUP BY customer_id
) AS sub
ORDER BY spent DESC
LIMIT 5;
```

Derived tables in `FROM` need an alias (`sub` here) — on SQL Server and MySQL always, and on PostgreSQL before 16. PostgreSQL 16 made the alias optional for sub-`SELECT`s and `VALUES` in `FROM` (Dean Rasheed's patch, listed in the PostgreSQL 16 release notes), so the same query that runs on a PG16 dev box can fail with `subquery in FROM must have an alias` on a PG15 box that hasn't been upgraded yet. Keep writing the alias.

### Correlated vs non-correlated

The big mental model.

**Non-correlated subquery** — independent of the outer query. Runs once.

```sql
-- Customers in countries that have any orders
SELECT * FROM customers
WHERE country IN (SELECT country FROM customers WHERE id IN (SELECT customer_id FROM orders));
-- The inner SELECT runs once and is reused.
```

**Correlated subquery** — references the outer query. Runs once per outer row (conceptually).

```sql
-- For each customer, count their orders
SELECT
    c.id, c.name,
    (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id) AS order_count
FROM customers c;
-- The inner SELECT runs once per customer (refers to c.id).
```

Correlated subqueries are slower in principle (per-row execution) but optimizers often rewrite them as joins. How reliably depends on *where* the subquery sits, and the two engines differ in a way that catches people who learned this on one of them.

The "correlation" — the outer-query reference — is what makes the subquery dependent.

#### What actually gets decorrelated

Decorrelation (also called *unnesting*) is the optimizer rewriting "run this per outer row" into a set-based operator. It is reliable in one place and unreliable in another:

- **Correlated predicates in `WHERE` — `EXISTS`, `IN`, `NOT EXISTS`, `NOT IN`.** Both PostgreSQL and SQL Server turn these into semi-joins and anti-joins, which are ordinary hash/merge/loop joins with "stop at the first match" (semi) or "keep rows with no match" (anti) semantics. This is the case where "trust the optimizer" is fair advice.
- **Correlated scalar subqueries in the `SELECT` list.** SQL Server can decorrelate these: its optimizer is built around the `Apply` operator and a family of transformation rules that turn a correlated scalar aggregate into a join plus a group-by (the design is described in Galindo-Legaria and Joshi, *Orthogonal Optimization of Subqueries and Aggregation*, SIGMOD 2001). **PostgreSQL does not unnest correlated scalar subqueries in the target list.** It plans them as a `SubPlan` and executes that subplan once per outer row. No amount of `ANALYZE` changes that; it is a missing transformation, not a costing mistake.

That single difference is why "correlated subqueries are fine, the optimizer handles it" is a dangerous thing to say in an interview without naming the engine. It is broadly true for `EXISTS` on both. It is true for scalar projections on SQL Server and false for them on PostgreSQL.

#### Reading it in the plan

Neither engine prints the word "correlated". You identify it by operator:

| What you see | Engine | What it means |
|---|---|---|
| `InitPlan 1` | PostgreSQL | Uncorrelated subquery, evaluated **once** before the main scan |
| `SubPlan 1` with `loops=N` on its inner nodes | PostgreSQL | Correlated subquery, evaluated **per outer row** |
| `Hash Semi Join` / `Nested Loop Semi Join` | PostgreSQL | `IN` or `EXISTS` successfully turned into a semi-join |
| `Hash Anti Join` / `Nested Loop Anti Join` | PostgreSQL | `NOT EXISTS` turned into an anti-join |
| `hashed SubPlan` | PostgreSQL | `NOT IN` (or `IN`) hashed into memory once — good, but conditional (see below) |
| `Nested Loops` with **Left Semi Join** as the logical operation | SQL Server | `EXISTS` as an apply semi-join |
| `Hash Match` with **Left Anti Semi Join** | SQL Server | `NOT EXISTS` as a set-based anti-join |
| `Index Spool (Lazy Spool)` | SQL Server | The inner side is being cached and replayed per outer row |

The number to look at on a PostgreSQL `SubPlan` is `loops=`. If it equals the outer row count, the subquery is running per row and the only fix is a rewrite.

#### Rewriting a correlated projection

The mechanical rewrite has two forms. Aggregate once and join:

```sql
-- Before: one correlated scan of orders per customer, per column
SELECT c.id, c.name,
       (SELECT MAX(o.total)     FROM orders o WHERE o.customer_id = c.id) AS max_total,
       (SELECT MIN(o.total)     FROM orders o WHERE o.customer_id = c.id) AS min_total,
       (SELECT COUNT(*)         FROM orders o WHERE o.customer_id = c.id) AS order_count
FROM customers c;

-- After: one pass over orders, joined back
SELECT c.id, c.name, o.max_total, o.min_total, o.order_count
FROM customers c
LEFT JOIN (
    SELECT customer_id,
           MAX(total) AS max_total,
           MIN(total) AS min_total,
           COUNT(*)   AS order_count
    FROM orders
    GROUP BY customer_id
) o ON o.customer_id = c.id;
```

Or keep the per-row shape but do the work once with `LATERAL` (PostgreSQL, MySQL 8.0.14+) / `OUTER APPLY` (SQL Server):

```sql
-- PostgreSQL / MySQL 8.0.14+
SELECT c.id, c.name, o.max_total, o.min_total, o.order_count
FROM customers c
LEFT JOIN LATERAL (
    SELECT MAX(total) AS max_total, MIN(total) AS min_total, COUNT(*) AS order_count
    FROM orders WHERE customer_id = c.id
) o ON true;

-- SQL Server
SELECT c.id, c.name, o.max_total, o.min_total, o.order_count
FROM customers c
OUTER APPLY (
    SELECT MAX(total) AS max_total, MIN(total) AS min_total, COUNT(*) AS order_count
    FROM orders WHERE customer_id = c.id
) o;
```

Which one wins depends on selectivity. The pre-aggregating join computes every customer's totals whether or not you need them, so it suits reports over the whole table. `LATERAL`/`APPLY` computes only for the outer rows that survive, so it suits a filtered or paged outer query — one page of customers, an index seek on `orders(customer_id)` per row. The wrong choice here is not the join type; it is aggregating the whole `orders` table to render twenty rows on screen.

#### The correlation you did not write

Everything above assumes you know which subqueries are correlated. You do not, because correlation is not something you declare — it is a *consequence of name resolution*, and name resolution runs from the inside out. An unqualified column inside a subquery is looked for in that subquery's own `FROM` first; if it is not there, the engine looks one block further out, and keeps going. MySQL's manual states the rule plainly — "**Scoping rule:** MySQL evaluates from inside to outside" — and SQL Server and PostgreSQL resolve identically, because this is the standard's rule and not a vendor choice.

Which means a typo in a column name does not produce an error. It produces a correlation.

```sql
-- cancelled_import's column is actually called order_ref.
DELETE FROM orders
WHERE order_id IN (SELECT order_id FROM cancelled_import);
```

`cancelled_import` has no `order_id`, so the inner `order_id` resolves outward to `orders.order_id`. The subquery now means "the current outer row's own id, emitted once per row in `cancelled_import`". The predicate becomes `orders.order_id IN (orders.order_id, orders.order_id, …)`, which is TRUE for every row with a non-NULL id as long as the staging table has at least one row in it. **The statement deletes the table.** It is valid SQL on all three engines; nothing warns.

The behaviour flips on emptiness, which is why this passes review and passes a test run. With `cancelled_import` empty, `IN (empty)` is FALSE and the delete removes nothing — "I ran it in staging and it was fine". With one row in it, the delete removes everything.

The tell in the plan is an absence: **there is no join between the two tables**. Nothing seeks `cancelled_import` by key, because there is no key to seek by. In PostgreSQL, `EXPLAIN (VERBOSE)` prints the subquery's output list and you will see the *outer* relation's column sitting in it; in SQL Server, the inner table's operator is a bare scan with no seek predicate and no join predicate binds the two.

Switching to `EXISTS` does not close the hole, and people assume it does. Writing the outer side explicitly protects only the outer side:

```sql
-- Correlated, yes — and vacuously so. The bare order_id resolves outward too.
WHERE NOT EXISTS (SELECT 1 FROM cancelled_import WHERE order_id = orders.order_id)
--                                                     ^^^^^^^^ is orders.order_id
```

The predicate is `orders.order_id = orders.order_id`, TRUE whenever that id is not NULL. So `EXISTS` is TRUE for every order with a non-NULL id as soon as the staging table holds one row, `NOT EXISTS` is FALSE for all of them, and the anti-join keeps nothing.

The defence is one alias and one prefix, and it is absolute: **alias the inner table and qualify every column inside the subquery with it, on both sides of the correlating predicate.** `SELECT ci.order_id FROM cancelled_import ci` cannot silently bind outward — if `order_id` is not a column of `ci`, the statement fails to compile, which is the outcome you wanted the first time. Running the `SELECT` version first does not save you here: it returns every row too, so only the row count gives it away, and a row count is the one thing nobody reads on a query they expect to be a filter.

> 🌍 **In the real world**: a data-fix script written during an incident ran `DELETE FROM order_lines WHERE order_id IN (SELECT order_id FROM incident_orders)` against production. The temp table built ten minutes earlier had the column as `id`, not `order_id`. The script had been dry-run against a copy where the temp table was still empty, so it reported zero rows and looked safe; in production the table had 47 rows and the statement emptied `order_lines`. Restore from backup plus log replay took most of a night. The change that came out of the post-mortem was not a review checklist — it was a linter rule in CI that fails any subquery containing an unqualified column reference, which finds this class of bug before a human sees the SQL.

> 🌍 **In the real world**: an order-history endpoint projected six correlated scalar subqueries per row — last payment date, shipment count, refund total, and three more — because each was added by a different pull request and each one looked harmless on its own. On SQL Server the plan was six nested-loops seeks per order and nobody complained. The same query against the PostgreSQL reporting replica showed six `SubPlan` nodes with `loops` equal to the page size, and the endpoint started timing out for customers with long histories. Rewriting as one `LATERAL` block returning six columns fixed it in an afternoon — and the review that followed found that two of the six values had never been rendered by the front end.

### EXISTS, IN, ANY, ALL

Predicates that work with subqueries:

**`EXISTS`** — at least one row in the subquery (boolean). Most-used.

```sql
-- Customers with any order
SELECT * FROM customers c
WHERE EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id);
```

The `SELECT 1` is convention — `EXISTS` only checks for row presence, not contents. `SELECT *` works equally well; `SELECT 1` is shorter and clearer of intent.

**`NOT EXISTS`** — anti-join. Often the cleanest "rows in A with no match in B."

```sql
SELECT * FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id);
```

**`IN`** — value matches any in the subquery's single-column list.

```sql
SELECT * FROM customers
WHERE id IN (SELECT customer_id FROM orders WHERE total > 1000);
```

**`NOT IN`** — value doesn't match. **Beware NULLs**: if the subquery returns any NULL, `NOT IN` returns no rows. Use `NOT EXISTS` to be safe.

The NULL rule is only half of why `NOT EXISTS` is the better default. The other half is the plan.

**PostgreSQL, through version 18, cannot convert `NOT IN (subquery)` into an anti-join at all** — precisely because of the NULL semantics above, the transformation would change the answer. (A patch that does the conversion when *both* sides are provably `NOT NULL` landed on the development branch in March 2026, so this is a fact with an expiry date; it is true of every release you will meet in an interview today.) What it does instead is build a *hashed SubPlan*: it runs the subquery once, hashes the result, and probes it per outer row, with a separate structure for the NULLs it found. That is fast, and it is conditional — a hashed SubPlan is only used when the subquery result is estimated to fit in `work_mem` and the subquery is uncorrelated. Cross that threshold and the plan degrades to a plain `SubPlan` re-executed per outer row. `NOT EXISTS` has no such cliff: it becomes a `Hash Anti Join` and stays one.

On **SQL Server** the declared nullability of the column changes the plan. If the subquery's column is `NOT NULL`, the optimizer knows `NOT IN` and `NOT EXISTS` are equivalent and can produce the same anti-semi-join. If it is nullable, the plan carries extra machinery to implement the three-valued logic, and the two forms stop being interchangeable. This is one of the concrete, demonstrable arguments for declaring `NOT NULL` on foreign keys.

There is a second trap on the anti-join side, and it is the classic "it was fast in test" failure. A **row goal** is the optimizer costing an operator as if it only needs the first N rows rather than all of them — which is what makes `EXISTS` cheap, since one matching row is enough. The pathological version, documented by Paul White in *Row Goals, Part 4: The Anti Join Anti Pattern* (SQLPerformance, 2018), is a correlated (apply) anti join whose inner side carries a `Top (1)`: the `Top` introduces a row goal that "is entirely artificial, and has no basis in the original query specification", the optimizer assumes a uniform distribution when guessing how many rows it must read to satisfy that goal, and it re-applies that optimistic assumption on every one of the outer rows. The estimated cost stays tiny; the runtime does not. The tell in the plan is an inner subtree whose actual row count is far above its estimate, under an operator that looked free when the plan was chosen.

**Empty and NULL subquery results** — the cases interviewers use to check whether you actually know three-valued logic:

| Subquery result | `x IN (…)` | `x NOT IN (…)` | `EXISTS` | `NOT EXISTS` | `x > ALL (…)` | `x > ANY (…)` |
|---|---|---|---|---|---|---|
| Empty set | FALSE | **TRUE** | FALSE | **TRUE** | **TRUE** | FALSE |
| Contains a NULL, no match | UNKNOWN | **UNKNOWN** | TRUE | FALSE | FALSE if a non-NULL row fails the test, else UNKNOWN | UNKNOWN |
| Contains a match | TRUE | FALSE | TRUE | FALSE | — | TRUE |

Read the quantifier columns as the AND (`ALL`) or OR (`ANY`) of the individual comparisons under three-valued logic, which is exactly what they are: one FALSE is enough to make `> ALL` FALSE even with a NULL in the set, but with nothing FALSE the NULL leaves the answer UNKNOWN. The empty-set row is the one people get wrong: `NOT IN (empty)` keeps every row, and `> ALL (empty)` is vacuously TRUE. A filter driven by a subquery that returns nothing does not filter — it passes everything through. `EXISTS`/`NOT EXISTS` never return UNKNOWN, which is exactly why they are the safe anti-join spelling.

> 🌍 **In the real world**: a nightly job ran `UPDATE customers SET active = false WHERE id NOT IN (SELECT customer_id FROM orders)`. It worked for two years. Then guest checkout shipped, `orders.customer_id` became nullable, and from that release the job deactivated nobody — because one NULL in the subquery makes the whole predicate UNKNOWN. Nothing errored; "0 rows affected" is not an alert. Dormant accounts kept their entitlements until a licence audit asked why the active-user count didn't match billing. Switching to `NOT EXISTS` fixed the logic, and then created a second problem: the first corrected run deactivated a backlog of accounts in one go and produced a wave of "why am I locked out" tickets. The rollout had to be staged by last-login date.

> 🌍 **In the real world**: a reconciliation query used `WHERE external_id NOT IN (SELECT external_id FROM import_staging)` on PostgreSQL and was instant for months, because the staging table was small enough to hash. A large partner onboarding pushed staging past `work_mem`, the hashed SubPlan stopped being usable, and the same query began re-evaluating the subquery per outer row — same SQL, same data volume in the outer table, plan silently different. The team's first instinct was to raise `work_mem` for the session, which worked until the next partner. Rewriting as `NOT EXISTS` gave a `Hash Anti Join` whose cost degrades gradually instead of falling off a cliff.

**`ANY` / `ALL`** — comparison with subquery results.

```sql
-- Any: this customer's max order exceeds at least one customer's max
SELECT * FROM customers c
WHERE (SELECT MAX(total) FROM orders WHERE customer_id = c.id)
        > ANY (SELECT MAX(total) FROM orders GROUP BY customer_id);
-- Note the subquery includes c's own max, so "at least one" means
-- "at least one OTHER" only because a value is never > itself.
-- Add "WHERE customer_id <> c.id" if you want that stated rather than implied.

-- All: customer's max exceeds every customer's max — including their own,
-- so it is never TRUE: FALSE for any customer who has orders, UNKNOWN for
-- one who has none (their scalar is NULL). To mean "they're #1", exclude the row:
--   > ALL (SELECT MAX(total) FROM orders WHERE customer_id <> c.id GROUP BY customer_id)
WHERE c.max_total > ALL (other_maxes)
```

Less idiomatic; usually rewritten with subqueries returning aggregates. The self-inclusion bug above is the reason: `> ALL` over a set that contains the row's own value can never be true, and nothing in the syntax warns you.

**`EXISTS` vs `COUNT(*) > 0`** — the one `EXISTS` rewrite that is worth doing without measuring. `IF (SELECT COUNT(*) FROM audit_log WHERE user_id = @u) > 0` has to count every matching row before it can compare. `IF EXISTS (SELECT 1 FROM audit_log WHERE user_id = @u)` gives the optimizer a row goal of one row; it can stop at the first match. The bigger the match set, the wider the gap — which is backwards from what people expect, since the "worst" case for `COUNT` is a user with plenty of history.

### CTEs (Common Table Expressions)

A **WITH** clause that names a subquery for reuse and readability.

```sql
WITH high_value_customers AS (
    SELECT customer_id, SUM(total) AS spent
    FROM orders
    WHERE created_at >= '2025-01-01'
    GROUP BY customer_id
    HAVING SUM(total) > 10000
)
SELECT c.name, h.spent
FROM customers c
JOIN high_value_customers h ON h.customer_id = c.id
ORDER BY h.spent DESC;
```

The CTE acts like a temporary named view that exists only for the duration of the query. Benefits:

- **Readability:** name each step. The query reads top-down like prose.
- **Reuse:** reference the CTE multiple times in the main query. Whether that re-evaluates the definition depends entirely on the engine — see the contract below.
- **Recursion:** `WITH RECURSIVE` for hierarchies.

#### The evaluation contract, per engine

This is the single highest-value fact on the page, and it is the one most often stated as if SQL had one answer:

| Engine | Non-recursive CTE referenced once | Referenced twice or more | How to force materialisation |
|---|---|---|---|
| **PostgreSQL 12+** | Folded into the parent query (predicates push in) | **Materialised** — computed once, reused | `AS MATERIALIZED`; force the other way with `AS NOT MATERIALIZED` |
| **PostgreSQL ≤ 11** | Always materialised (an optimization fence) | Always materialised | Nothing to force; it always was |
| **SQL Server** (all versions) | Inlined | **Inlined again — the definition is re-executed per reference** | No syntax for it. Use `#temp` |
| **MySQL 8.0** | Merged if it can be, otherwise materialised | Same rule — merged per reference if mergeable; **if it is materialised, that happens once** and every reference reads the one temp table | `NO_MERGE()` hint; automatic when the CTE has an aggregate or window function, `DISTINCT`, `GROUP BY`, `HAVING`, `LIMIT` or `UNION` |

The rules are documented, not folklore. PostgreSQL's docs say that "if a `WITH` query is non-recursive and side-effect-free (that is, it is a `SELECT` containing no volatile functions) then it can be folded into the parent query, allowing joint optimization of the two query levels. By default, this happens if the parent query references the `WITH` query just once, but not if it references the `WITH` query more than once." Read the parenthesis: *side-effect-free* is defined there as containing no volatile functions, so a CTE calling `random()` or a `VOLATILE` PL/pgSQL function is never folded. SQL Server's docs say "query results from common table expressions aren't materialized. Each outer reference to the named result set requires the defined query to be re-executed. For queries that require multiple references to the named result set, consider using a temporary object instead." MySQL's optimizer chapter says that when a CTE is materialised, "it is materialized once for the query, even if the query references it several times", visible in the optimizer trace as one `creating_tmp_table` followed by `reusing_tmp_table`.

Two consequences follow, and they are what turns this from trivia into an outage:

**1. On SQL Server, a CTE referenced twice can return two different answers.** Re-execution means re-reading. Under the SQL Server default (`READ_COMMITTED_SNAPSHOT OFF`, so read committed via shared locks that are released as the scan moves on) nothing holds the underlying rows still between the two executions of the same statement. Concurrent inserts land between them. With `READ_COMMITTED_SNAPSHOT ON` — which is the default on Azure SQL Database — each statement gets "a transactionally consistent snapshot of the data as it existed at the start of the statement", so both references agree. Same code, different behaviour on-premises and in Azure.

**2. Non-deterministic expressions inside a re-executed CTE are re-evaluated.** A CTE whose definition contains a per-row non-deterministic function — `NEWID()` is the one you meet, usually as `ORDER BY NEWID()` for sampling — produces different values at each reference on SQL Server. PostgreSQL sidesteps this class of bug by refusing to fold any CTE containing a volatile function, so it computes it once.

> 🌍 **In the real world**: a dashboard on SQL Server computed a "totals" card and a "recent rows" grid from one statement referencing a single CTE twice. During quiet hours the two agreed; during the lunchtime order peak the card said one number and the grid listed a different count, and support logged it as a rounding bug. It was neither — the CTE was executed twice within the one statement, and on a busy server orders committed between the two scans. Dropping the CTE into a `#temp` table made the numbers agree, and gave the second half of the query real statistics on the intermediate result instead of an estimate derived through the CTE boundary.

> 🌍 **In the real world**: an experiment-assignment query used `WITH picked AS (SELECT TOP (1000) user_id FROM users ORDER BY NEWID())` and then referenced `picked` twice — once to insert into the treatment arm, once to log the cohort. Two executions, two different random samples. Users appeared in the treatment table who were never logged, and vice versa, and the experiment's results were unusable for a week before anyone questioned the query rather than the analysis. The fix is one line — materialise into a temp table first — but only if you know the CTE is not a variable.

**Multiple CTEs:**

```sql
WITH
    last_year_revenue AS (
        SELECT customer_id, SUM(total) AS revenue
        FROM orders
        WHERE EXTRACT(YEAR FROM created_at) = 2024
        GROUP BY customer_id
    ),
    this_year_revenue AS (
        SELECT customer_id, SUM(total) AS revenue
        FROM orders
        WHERE EXTRACT(YEAR FROM created_at) = 2025
        GROUP BY customer_id
    ),
    growing_customers AS (
        SELECT
            t.customer_id,
            t.revenue AS this_year,
            l.revenue AS last_year,
            (t.revenue - l.revenue) / l.revenue AS growth_pct
        FROM this_year_revenue t
        JOIN last_year_revenue l ON l.customer_id = t.customer_id
        WHERE t.revenue > l.revenue
    )
SELECT c.name, g.last_year, g.this_year, ROUND(g.growth_pct * 100, 1) AS growth_pct
FROM growing_customers g
JOIN customers c ON c.id = g.customer_id
ORDER BY g.growth_pct DESC
LIMIT 10;
```

Each CTE is one named step. Think of the chain as "data flow," not "nested expression."

**Materialization (PostgreSQL):**

```sql
-- Force materialization: compute once, store, reuse.
WITH big_step AS MATERIALIZED (...)

-- Force inlining even with several references (risks recomputation).
WITH big_step AS NOT MATERIALIZED (...)

-- Default from PostgreSQL 12: folded if referenced exactly once and
-- side-effect-free; materialized if referenced more than once.
WITH big_step AS (...)
```

The default is a reference-count rule, not a cost decision — worth being precise about, because "the optimizer decides based on cost" is the version of this that gets corrected in interviews. In SQL Server, CTEs are always inlined (re-evaluated per reference); for repeated heavy CTEs, materialize manually via temp tables.

#### Data-modifying CTEs — PostgreSQL only

PostgreSQL lets a CTE be an `INSERT`, `UPDATE` or `DELETE` with `RETURNING`, which makes "move these rows" a single atomic statement:

```sql
-- Archive and delete in one statement, one snapshot, one transaction
WITH moved AS (
    DELETE FROM events
    WHERE occurred_at < now() - INTERVAL '90 days'
    RETURNING *
)
INSERT INTO events_archive
SELECT * FROM moved;
```

Three rules from the PostgreSQL documentation decide whether your clever version is correct:

1. **One snapshot for everything.** "All the statements are executed with the same snapshot, so they cannot 'see' one another's effects on the target tables." A `SELECT` on `events` in the same `WITH` clause still sees the rows the `DELETE` removed.
2. **No ordering guarantee between sub-statements.** "The sub-statements in `WITH` are executed concurrently with each other and with the main query. Therefore, when using data-modifying statements in `WITH`, the order in which the specified updates actually happen is unpredictable." You cannot chain "update, then read the updated value" inside one statement.
3. **A row may be modified once.** "Trying to update the same row twice in a single statement is not supported. Only one of the modifications takes place, but it is not easy (and sometimes not possible) to reliably predict which one."

SQL Server and MySQL have no equivalent. On SQL Server the same job is `DELETE ... OUTPUT deleted.* INTO events_archive`, which is a genuinely different mechanism with the same effect for this shape. On MySQL you write two statements in one transaction.

> 🌍 **In the real world**: an archive job was rewritten from two statements into "one clean statement" with two CTEs — one deleting expired events, one selecting the day's summary counts from the same table for a report row. Because both share one snapshot, the summary CTE counted the rows the delete was in the middle of removing, so every archived batch was also counted as live. The report drifted upward for weeks. The fix was to stop treating a `WITH` clause as a sequence of steps: the delete-and-archive stayed as one statement, and the summary moved to its own statement in the same transaction, after it.

#### Subqueries that supply values: the many-match rule

A subquery in a `WHERE` clause *filters*, and a duplicate in it is harmless. A subquery or CTE joined into an `UPDATE` *supplies values*, and there a duplicate is a silent correctness bug. This is the highest-frequency way a correct-looking CTE writes wrong data.

```sql
-- SQL Server: apply the latest price from a feed
UPDATE p
SET    p.price = f.price
FROM   products p
JOIN   price_feed f ON f.sku = p.sku;
```

If `price_feed` holds two rows for one SKU, this does not error and it does not apply both. Microsoft's documentation is direct about it: "The results of an `UPDATE` statement are undefined if the statement includes a `FROM` clause that isn't specified in such a way that only one value is available for each column occurrence that is updated, that is if the `UPDATE` statement isn't deterministic."

PostgreSQL's `UPDATE ... FROM` says the same thing in different words: "When using `FROM` you should ensure that the join produces at most one output row for each row to be modified. In other words, a target row shouldn't join to more than one row from the other table(s). If it does, then only one of the join rows will be used to update the target row, but which one will be used is not readily predictable." MySQL's multi-table `UPDATE ... JOIN` guarantees only that the target row is written once — "each matching row is updated once, even if it matches the conditions multiple times" — and says nothing about *which* of the matching source rows supplies the value. Three engines, three wordings, one behaviour: the row is written, exactly once, with a value you did not choose.

Now compare the correlated-scalar-subquery spelling of the same intent:

```sql
UPDATE products p
SET price = (SELECT f.price FROM price_feed f WHERE f.sku = p.sku);
```

This one **errors** on a duplicate SKU — the scalar subquery returns more than one row, and you get error 512 on SQL Server, `more than one row returned by a subquery used as an expression` on PostgreSQL, `ERROR 1242` on MySQL. It also sets `price` to NULL for every product with no feed row, because zero rows is not an error. Same intent, opposite failure modes:

| | Duplicate in the source | No match in the source |
|---|---|---|
| `UPDATE … FROM` / `JOIN` | Silently picks one, unpredictably | Row is left unchanged |
| `SET col = (correlated scalar)` | Runtime error | Silently overwrites with NULL |

Neither is safe by default. Pick the one whose failure you can detect, and make the tie-break a decision rather than an accident — which is the one job a CTE does well here:

```sql
-- SQL Server: the choice of "which feed row wins" is now written down
WITH latest AS (
    SELECT sku, price,
           ROW_NUMBER() OVER (PARTITION BY sku ORDER BY received_at DESC, id DESC) AS rn
    FROM price_feed
)
UPDATE p
SET    p.price = l.price
FROM   products p
JOIN   latest l ON l.sku = p.sku AND l.rn = 1;

-- PostgreSQL: same CTE, PostgreSQL's UPDATE … FROM … WHERE spelling
WITH latest AS (
    SELECT sku, price,
           ROW_NUMBER() OVER (PARTITION BY sku ORDER BY received_at DESC, id DESC) AS rn
    FROM price_feed
)
UPDATE products p
SET    price = l.price
FROM   latest l
WHERE  l.sku = p.sku AND l.rn = 1;
```

The `id DESC` tiebreaker is not decoration. `ROW_NUMBER()` over a non-unique `ORDER BY` is itself non-deterministic, so without it you have moved the arbitrary choice one level down rather than removed it.

> 🌍 **In the real world**: a supplier price sync ran nightly as `UPDATE ... FROM feed JOIN` and was correct for three years because the feed had one row per SKU. A supplier changed their export to include both a list price and a promotional price as separate rows with the same SKU. Nothing failed. Roughly half the affected products picked up the promo price permanently, the other half the list price, and which was which changed between runs — so the finance reconciliation showed a small, drifting, irreproducible discrepancy that was written off twice as a rounding issue before anyone read the `UPDATE`. The fix was the `ROW_NUMBER()` CTE above plus a check constraint the sync asserts first: if the feed contains more than one row per SKU per day, fail the job rather than choose.

#### Claiming rows from a queue

Outbox tables, job queues and "process the next N" endpoints are where a .NET service most often writes a subquery that has to be exactly right, and the correctness condition is not the SQL — it is what two workers running the statement simultaneously do to each other.

**PostgreSQL.** The pattern is a CTE (or plain subquery) that locks the rows as it selects them:

```sql
WITH claimed AS (
    SELECT id
    FROM   jobs
    WHERE  state = 'ready' AND run_at <= now()
    ORDER BY run_at
    LIMIT 20
    FOR UPDATE SKIP LOCKED
)
UPDATE jobs j
SET    state = 'running', claimed_at = now(), claimed_by = $1
FROM   claimed c
WHERE  j.id = c.id
RETURNING j.*;
```

Four things in that statement are load-bearing, and each is documented:

1. **`SKIP LOCKED`.** "With `SKIP LOCKED`, any selected rows that cannot be immediately locked are skipped. Skipping locked rows provides an inconsistent view of the data, so this is not suitable for general purpose work, but can be used to avoid lock contention with multiple consumers accessing a queue-like table." Two workers get disjoint batches instead of one queueing behind the other.
2. **The locking clause must be inside the CTE.** The docs: "these clauses do not apply to `WITH` queries referenced by the primary query. If you want row locking to occur within a `WITH` query, specify a locking clause within the `WITH` query." A `FOR UPDATE` written on the outer statement does not reach in.
3. **`LIMIT` bounds the locking, not just the output.** "If a `LIMIT` is used, locking stops once enough rows have been returned to satisfy the limit (but note that rows skipped over by `OFFSET` will get locked)." The worker locks twenty rows, not the whole ready backlog — so an `OFFSET`-based pager over a queue table locks everything it skips.
4. **Dropping `SKIP LOCKED` does not merely make it slower — it makes it lie.** The second worker blocks on the locked rows, and when the first commits it does not inherit them. Under Read Committed, "the search condition of the command (the `WHERE` clause) is re-evaluated to see if the updated version of the row still matches the search condition." The first worker set `state = 'running'`, the rows no longer match, and the second worker's batch simply comes back short — sometimes empty — with no error and no retry signal. "Why did my worker claim 3 jobs when I asked for 20" is this mechanism, not a bug in your polling loop.

**SQL Server** has no `SKIP LOCKED` keyword. The equivalent is the `READPAST` table hint, and the claim is one statement with `OUTPUT`:

```sql
UPDATE TOP (20) j
SET    state = 'running', claimed_at = SYSUTCDATETIME(), claimed_by = @worker
OUTPUT inserted.*
FROM   jobs AS j WITH (READPAST, UPDLOCK, ROWLOCK)
WHERE  j.state = 'ready' AND j.run_at <= SYSUTCDATETIME();
```

`READPAST` "[specifies] that the Database Engine not read rows that are locked by other transactions", and Microsoft names this exact use case: it "is primarily used to reduce locking contention when implementing a work queue that uses a SQL Server table." Two details decide whether it actually works:

- **Granularity.** "When `READPAST` is specified, row-level locks are skipped, but page-level locks aren't skipped." A worker whose locks escalate blocks every other worker, which is why `ROWLOCK` is in the hint list and why a large claim batch is riskier than a small one. `UPDLOCK` takes the update lock at read time, so two workers cannot both select a row before either writes it.
- **RCSI, and this is the one that catches teams moving to Azure.** "The `READPAST` table hint can't be specified when the `READ_COMMITTED_SNAPSHOT` database option is set to `ON` and either of the following conditions is true: The transaction isolation level of the session is `READ COMMITTED`. The `READCOMMITTED` table hint is also specified in the query." The documented remedy is in the same paragraph — "include the `READCOMMITTEDLOCK` table hint in the query". `READ_COMMITTED_SNAPSHOT` is `OFF` by default on SQL Server and `ON` by default on Azure SQL Database, so the queue statement that has run on-premises for years is precisely the one SQL Server rejects on the first deploy to Azure SQL.

**MySQL 8.0** has `SKIP LOCKED` and `NOWAIT` on locking reads with the same warning attached — "Queries that skip locked rows return an inconsistent view of the data. `SKIP LOCKED` is therefore not suitable for general transactional work. However, it may be used to avoid lock contention when multiple sessions access the same queue-like table" — plus one that matters if you replicate: "Statements that use `NOWAIT` or `SKIP LOCKED` are unsafe for statement based replication."

> 🌍 **In the real world**: an outbox publisher polled with `SELECT TOP (100) ... WHERE published = 0` and then updated the ids it had read, in two statements. With one instance it was correct. Scaling to three instances started publishing duplicate messages to the broker, because all three read the same hundred rows before any of them wrote. The team's first fix was `SERIALIZABLE` on the read, which removed the duplicates and replaced them with deadlocks under load. The version that held was one statement — `UPDATE TOP (100) ... WITH (READPAST, UPDLOCK, ROWLOCK) ... OUTPUT inserted.*` — so the read, the claim and the return are the same atomic operation and the instances step past each other's locked rows. The same service later moved to Azure SQL Database, where RCSI is on by default, and the statement was rejected outright until `READCOMMITTEDLOCK` was added to the hint list. Consumers still had to be idempotent: a worker that crashes after claiming and before publishing leaves rows claimed, so there is a reaper for stale `claimed_at` — and a reaper means at-least-once delivery no matter how good the SQL is.

### Recursive CTEs

The `WITH RECURSIVE` (or in SQL Server, just `WITH`) form lets a CTE refer to itself. Used for:
- Hierarchies (org charts, category trees).
- Path traversal (graphs).
- Generated sequences (date ranges, integer sequences).

**Two-part structure:**
1. **Anchor** — non-recursive base case (one or more rows).
2. **Recursive member** — references the CTE itself; produces additional rows.
3. The two are combined with `UNION ALL` — or, on PostgreSQL and MySQL only, `UNION` to deduplicate against everything produced so far. SQL Server allows `UNION ALL` and nothing else between the last anchor member and the first recursive member.

```sql
-- Org chart: list every employee with their depth in the hierarchy
WITH RECURSIVE org_tree AS (
    -- Anchor: top-level employees (no manager)
    SELECT id, name, manager_id, 0 AS depth
    FROM employees
    WHERE manager_id IS NULL

    UNION ALL

    -- Recursive: employees whose manager is in the tree
    SELECT e.id, e.name, e.manager_id, ot.depth + 1
    FROM employees e
    JOIN org_tree ot ON e.manager_id = ot.id
)
SELECT * FROM org_tree ORDER BY depth, name;
```

The recursion stops when the recursive query produces no new rows.

#### It is iteration, and the recursive member sees only one level

The name is misleading and the mechanism explains most of the restrictions. PostgreSQL's documentation says it outright: "while `RECURSIVE` allows queries to be specified recursively, internally such queries are evaluated iteratively." The algorithm is a working table:

```
1. Run the anchor. Its rows go to the result AND become the working table.
2. While the working table is not empty:
     a. Run the recursive member, with the CTE's self-reference
        bound to the CURRENT WORKING TABLE ONLY.
     b. Its output goes to the result AND becomes the new working table.
     c. The old working table is discarded.
3. Stop when step 2a produces zero rows.
```

Read step 2a again: inside the recursive member, the CTE name means *the rows produced by the previous iteration*, not the accumulated result. That is why:

- You cannot compute a running total or a rank "over everything so far" inside the recursion. SQL Server's own documentation demonstrates this with a `ROW_NUMBER()` in a recursive member that returns `1` on every row, and explains that "analytic and aggregate functions in the recursive part of the CTE are applied to the set for the current recursion level and not to the set for the CTE."
- You cannot join the CTE to itself in the recursive member; SQL Server requires the `FROM` clause of a recursive member to "refer only one time to the CTE", MySQL requires the recursive `SELECT` to "reference the CTE only once and only in its `FROM` clause, not in any subquery".
- De-duplication against everything seen so far is available on PostgreSQL and MySQL through `UNION` instead of `UNION ALL` — PostgreSQL implements it by discarding rows "duplicating any previous result row", which is a real capability with a real cost, since it must keep and probe the whole result set. **SQL Server cannot do this**: its documentation states that "`UNION ALL` is the only set operator allowed between the last anchor member and first recursive member", so on SQL Server the dedup has to be a path column or an outer `DISTINCT`.

What is banned in the recursive member, by engine:

| | SQL Server | PostgreSQL | MySQL 8.0 |
|---|---|---|---|
| Keyword | `WITH` (no `RECURSIVE`) | `WITH RECURSIVE` required | `WITH RECURSIVE` required |
| `DISTINCT` / `GROUP BY` / `HAVING` | All three not allowed | Not rejected in their own right — a bare `GROUP BY` or `SELECT DISTINCT` parses; with an aggregate they hit the rule below | `GROUP BY` and `DISTINCT` not allowed (`UNION DISTINCT` *between* the terms is fine); `HAVING` isn't on MySQL's list |
| Aggregates / window functions | Scalar aggregation not allowed; a window function **is** accepted and silently sees one level (see above) | Aggregates rejected — *"aggregate functions are not allowed in a recursive query's recursive term"*; window functions are **not** rejected | Both not allowed |
| `TOP` / `LIMIT` / `ORDER BY` | `TOP` not allowed | `ORDER BY`, `LIMIT` and `OFFSET` rejected anywhere in the recursive query | `ORDER BY` not allowed; `LIMIT` (with optional `OFFSET`) **is** allowed, but only from MySQL 8.0.19 — it was on the banned list in 8.0.18 and earlier |
| Outer joins | `LEFT`/`RIGHT`/`OUTER JOIN` not allowed (`INNER JOIN` is) | Self-reference must not be on the nullable side of an outer join | The CTE must not be on the right side of a `LEFT JOIN` |
| Subqueries | Not allowed | Self-reference not allowed in a subquery | Self-reference not allowed in a subquery |
| Self-references | Exactly one | Exactly one | Exactly one, in `FROM` |
| Depth cap | `MAXRECURSION` 100 by default | None | `cte_max_recursion_depth`, default 1000 |

Two SQL Server details that surprise people. First: "all columns returned by the recursive CTE are nullable regardless of the nullability of the columns returned by the participating `SELECT` statements" — so a `NOT NULL` column comes back nullable, which matters when you feed the result into a strongly-typed consumer or a `CREATE TABLE AS`-style insert. Second: the data type of each column is fixed by the **anchor**, and a mismatch is a compile error rather than a silent widening — `SELECT '' AS path` in the anchor gives a one-character column, and the moment the recursive member concatenates onto it you get *Types don't match between the anchor and the recursive part in column 'path'*. The fix is an explicit `CAST(... AS VARCHAR(4000))` in the anchor. PostgreSQL has the same requirement and tells you so directly, suggesting a cast to the recursive term's type.

**Generated sequences:**

```sql
-- Generate every date from 2025-01-01 to 2025-12-31
WITH RECURSIVE date_series AS (
    SELECT DATE '2025-01-01' AS d
    UNION ALL
    SELECT d + INTERVAL '1 day' FROM date_series WHERE d < DATE '2025-12-31'
)
SELECT * FROM date_series;
```

PostgreSQL has `generate_series()` as a shortcut; SQL Server uses recursive CTE or a "tally table" for the same purpose.

**Path through a graph:**

```sql
-- Find all paths from node 1 to node 5
WITH RECURSIVE paths AS (
    SELECT from_node, to_node, ARRAY[from_node, to_node] AS path
    FROM edges
    WHERE from_node = 1
    UNION ALL
    SELECT p.from_node, e.to_node, p.path || e.to_node
    FROM paths p
    JOIN edges e ON p.to_node = e.from_node
    WHERE NOT (e.to_node = ANY(p.path))    -- avoid cycles
)
SELECT path FROM paths WHERE to_node = 5;
```

Recursive CTEs need cycle detection in graphs; without it, infinite recursion. What "infinite" means in practice is engine-specific, and this is the part to get right:

- **SQL Server** applies a server-wide default of 100 recursion levels. Exceeding it terminates the statement with error 530: *The statement terminated. The maximum recursion 100 has been exhausted before statement completion.* Override per statement with `OPTION (MAXRECURSION n)` where `n` is 0–32767; `0` means no limit. The hint goes on the outermost statement, never inside the CTE definition.
- **MySQL 8.0** uses the `cte_max_recursion_depth` session/global variable, default 1000, and terminates the CTE when it recurses past it.
- **PostgreSQL has no cap at all.** There is no "recursion limit exceeded" error to catch. A cyclic recursive CTE builds its working table until it exhausts memory and then temp disk space — you will see the query fail on a temp-file or disk-space error, or hang until `statement_timeout` kills it, or fill the data volume if you haven't set one. Set `statement_timeout` on reporting connections and write the cycle guard.

Since **PostgreSQL 14** the guard has first-class syntax, and it replaces the hand-rolled array:

```sql
WITH RECURSIVE deps AS (
    SELECT to_node FROM edges WHERE from_node = 1
    UNION ALL
    SELECT e.to_node FROM deps d JOIN edges e ON e.from_node = d.to_node
) CYCLE to_node SET is_cycle USING path
SELECT to_node FROM deps WHERE NOT is_cycle;
```

`CYCLE col SET flag USING pathcol` maintains the visited-path array for you and marks the row where the cycle closes instead of following it. The companion clause `SEARCH DEPTH FIRST BY col SET ordercol` (or `BREADTH FIRST`) adds a sort key that lets you order the output as a traversal — without it, the iteration is breadth-first by construction and the row order is whatever the plan produces.

Two more things a strong answer mentions. **A recursive CTE is a nested-loop machine.** SQL Server plans it as a `Concatenation` of the anchor and the recursive member with a spool holding the rows being fed back in — Microsoft's documentation notes that for a CTE query "Index Spool/Lazy Spools are displayed in the query plan, and will have the additional `WITH STACK` predicate", and calls that "one way to confirm proper recursion"; PostgreSQL shows `Recursive Union` feeding a `WorkTable Scan`. Either way each iteration probes the base table with the previous level's keys, so **an index on the parent column is not optional** — and neither SQL Server nor PostgreSQL creates one automatically for a foreign key. **And the depth cap is a safety net, not a bug.** `OPTION (MAXRECURSION 0)` on a query that hit error 530 converts a failed query into an unbounded one.

> 🌍 **In the real world**: a bill-of-materials explosion started failing with error 530 after a product-data import. The on-call engineer added `OPTION (MAXRECURSION 0)` because the assembly genuinely was deeper than 100 levels, deployed, and went back to bed. The import had also introduced a part that contained itself. The query ran until tempdb filled, at which point every other write on the instance failed too. The eventual fix was three lines: a real cap (`MAXRECURSION 500`), a path column with a cycle guard, and a nightly check for self-referencing parts that files a data-quality ticket instead of a production incident.

> 🌍 **In the real world**: an org-chart recursion powering a permissions check was instant against the seed data on a laptop and became the slowest operator in every request in production. The plan showed the recursive side scanning `employees` on every iteration: the `manager_id` foreign key had a constraint but no index, because neither SQL Server nor PostgreSQL creates one for you. One index on `employees(manager_id)` turned each iteration into a seek. The lesson generalises — the cost of a recursive CTE is (levels × cost of one lookup), so the lookup is the only lever you have.

### CTEs vs subqueries vs views vs temp tables

Four ways to encapsulate a query. When to use which:

| Mechanism | Scope | When |
|---|---|---|
| **Subquery (inline)** | Single statement | Simple, one-off composition |
| **CTE** | Single statement | Named, multi-step transformation; recursion |
| **View** | Persistent | Reused across queries; encapsulates business logic |
| **Materialized view** | Persistent + cached | Heavy queries; freshness OK with periodic refresh |
| **Temp table** | Session | Multi-step processing in stored procs / scripts |
| **Table variable** (T-SQL) | Statement / batch | Small intermediate sets |

```sql
-- View — persistent virtual table
CREATE VIEW active_customers AS
SELECT * FROM customers WHERE deleted_at IS NULL;

-- Reuse anywhere
SELECT * FROM active_customers WHERE country = 'PK';

-- Materialized view (PostgreSQL) — cached
CREATE MATERIALIZED VIEW monthly_revenue AS
SELECT EXTRACT(MONTH FROM created_at) AS month, SUM(total) AS revenue
FROM orders GROUP BY EXTRACT(MONTH FROM created_at);

-- Refresh
REFRESH MATERIALIZED VIEW monthly_revenue;

-- Temp table
CREATE TEMP TABLE recent_orders AS
SELECT * FROM orders WHERE created_at > NOW() - INTERVAL '7 days';

-- Use as you would any table
SELECT customer_id, COUNT(*) FROM recent_orders GROUP BY customer_id;
```

Pick:
- **Subquery / CTE** for query-internal composition.
- **View** when many queries share the same logic.
- **Materialized view** when the underlying query is expensive and freshness can lag.
- **Temp table** in stored procs / scripts where multiple statements share state.

#### The dimension the table above leaves out: statistics

A CTE or derived table has no statistics of its own. The optimizer estimates the intermediate row count by propagating estimates through the CTE boundary, and every estimate it passes through compounds the error. A five-step CTE chain over a badly-estimated first step produces a final estimate that can be wildly wrong, and the plan is chosen from that number, not from what actually happens at runtime.

A `#temp` table on SQL Server is a real table: it has a real row count, real column statistics, you can index it, and the statement that reads it is compiled after it is populated. That — not "computed once" — is usually the reason breaking a long CTE chain in half fixes a plan. It costs a tempdb write and a recompile.

A **table variable** (`DECLARE @t TABLE`) is the trap in between: it gets no column statistics at all. Before SQL Server 2019 the optimizer assumed one row, which is why table variables were notorious for producing nested-loop plans over large sets. SQL Server 2019 (15.x) added *table variable deferred compilation* under database compatibility level 150, which defers compiling the consuming statement until the variable's actual row count is known — cardinality only, still no column statistics. Know which compatibility level your database is on before repeating either half of this.

#### What a predicate can and cannot cross

When a CTE or derived table is folded into the parent, the outer `WHERE` becomes eligible to be evaluated inside it — which is how a filter written at the top ends up driving an index seek at the bottom. Eligible, not guaranteed, and the rule for eligibility is semantic rather than cost-based: **a predicate may move below an operator only if moving it cannot change that operator's output for any surviving row.** That one sentence answers every "why isn't my index used when I filter the CTE" question, and it holds on all three engines because it is a statement about meaning, not about optimizers.

```
   filter written on the outer query
                │
                ▼   may it be evaluated below…
   ┌───────────────────────────────────────────────────────────────┐
   │ a plain WHERE on base columns    │ yes                        │
   │ GROUP BY, filter on a group key  │ yes  (it is a WHERE)       │
   │ GROUP BY, filter on the aggregate│ no   (it is a HAVING)      │
   │ a window function, filter on a   │ yes, conditionally —       │
   │   PARTITION BY column            │      whole partitions drop │
   │ a window function, filter on the │ no   — the value depends   │
   │   window's own result (rn = 1)   │      on the rows present   │
   │ LIMIT / TOP / OFFSET             │ never — the limit already  │
   │                                  │      chose the rows        │
   │ a volatile function              │ never                      │
   └───────────────────────────────────────────────────────────────┘
```

The window-function row is the one that costs money, because it is the shape of every "latest row per key" CTE a .NET team writes:

```sql
WITH ranked AS (
    SELECT o.*,
           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
    FROM orders o
)
SELECT * FROM ranked
WHERE rn = 1 AND customer_id = 42;
```

`rn = 1` cannot move below the window function: the value of `rn` depends on which rows are in the partition, so filtering first would change it. `customer_id = 42` can, and this is the whole difference — it names a `PARTITION BY` column, so it either keeps or discards a partition entire and no surviving row's `rn` changes. PostgreSQL implements exactly that reasoning; the commit that added it (David Rowley's patch, committed by Tom Lane in June 2014) states the condition and the justification: pushdown is allowed "if (a) the qual references only partitioning columns, and (b) the qual contains no volatile functions", because "window functions act only within a partition, such a case can't result in changing the window functions' outputs for any surviving row."

Take `customer_id` out of the `PARTITION BY` and the same-looking query has to rank the whole table to return one row:

```sql
-- Now nothing can be pushed: customer_id is not a partitioning column
WITH ranked AS (
    SELECT o.*, ROW_NUMBER() OVER (ORDER BY created_at DESC) AS rn
    FROM orders o
)
SELECT * FROM ranked WHERE customer_id = 42 AND rn <= 10;
```

SQL Server cannot evaluate `rn` early either, for the same reason. In its plans the `Filter` on the window result sits *above* the `Segment` and `Sequence Project (Compute Scalar)` pair that computes it, and everything below that Filter has already been read and sorted. Reading the plan top-down and finding the row count collapse only at the very last operator is the signature.

`LIMIT`/`TOP` is the absolute case. A predicate can never be pushed below one, because the limit picks its rows before your filter would run — pushing it in would change which rows the limit keeps. That is why a CTE ending in `LIMIT`/`TOP` is a hard fence on every engine, and why wrapping a query in `TOP (1000)` "to make it safe" also makes every outer filter useless.

> 🌍 **In the real world**: a device-telemetry service exposed "latest reading per device" as a CTE with `ROW_NUMBER() OVER (ORDER BY recorded_at DESC)` — no `PARTITION BY`, because the original query only ever wanted the single newest reading overall, and a later ticket added a `WHERE device_id = @id` on the outside without touching the CTE. It worked, and it read and sorted the entire readings table for every request. Nobody noticed for months because the table was small and the endpoint was rarely called; it surfaced when a dashboard started polling it per tile. Adding `PARTITION BY device_id` made the device filter pushable and turned a full sort into an index range read. The reviewable lesson was smaller than the fix: a filter added to the outer query is not a filter on the data unless it can reach the scan, and the plan is the only place that is visible.

#### The engine difference that matters most here: what a long read does to writers

A big report built from CTEs is still a read, and what a read costs other sessions is not a property of the CTE:

- **PostgreSQL**: a plain `SELECT` never blocks a writer. Read Committed is the default, and "a `SELECT` query sees a snapshot of the database as of the instant the query begins to run". The costs of a long report are elsewhere: it pins old row versions so `VACUUM` can't reclaim them, and its `ACCESS SHARE` lock does block DDL — the migration that "hangs" behind a reporting query is this.
- **SQL Server, on-premises default**: `READ_COMMITTED_SNAPSHOT` is `OFF`, so read committed takes shared locks. Row locks are released as the scan advances, but a large scan can cross the escalation threshold — 5,000 locks on one nonpartitioned table or index in a single statement — at which point the engine escalates **directly to a table lock, never to a page lock** ("Lock escalation always escalates to a table lock, and never to a page lock", Microsoft Learn, KB 323630). That escalated shared table lock is held for the rest of the statement, since read committed releases `S` locks when the read completes rather than at commit. A report that scans the orders table can therefore block the checkout that inserts into it for as long as the scan runs.
- **Azure SQL Database**: `READ_COMMITTED_SNAPSHOT` is `ON` by default. The same report against the same schema behaves like PostgreSQL. This is the single most common reason a query "behaves differently in Azure".
- **MySQL/InnoDB**: default `REPEATABLE READ`, and plain `SELECT`s are consistent non-locking reads served from the undo log. Readers don't block writers here either.

> 🌍 **In the real world**: a month-end revenue report — four CTEs, one big scan of `orders` — was run against the production OLTP database on SQL Server because "it's just a SELECT". It escalated to a table lock and checkout inserts queued behind it; the incident channel filled up with payment timeouts. The first fix was `WITH (NOLOCK)` on every table in the report, which stopped the blocking and started something worse: read-uncommitted scans can see rows appear and disappear mid-scan, so the totals stopped reconciling with the ledger and nobody could say by how much. The durable fix was two changes — enable `READ_COMMITTED_SNAPSHOT` so readers stop taking shared locks, and point the report at a readable secondary. The same report had never caused an incident on the team's PostgreSQL service, and that difference is not a virtue of the report.

#### Materialized views: the freshness contract is not the same either

PostgreSQL's materialized views are snapshots that go stale until you `REFRESH` them. Plain `REFRESH MATERIALIZED VIEW` "could block other connections which are trying to read from the materialized view"; `REFRESH MATERIALIZED VIEW CONCURRENTLY` refreshes "without locking out concurrent selects", but only if the matview already has data and has at least one `UNIQUE` index covering all rows with no `WHERE` clause and no expressions. So you get one of: stale-but-cheap, fresh-but-blocking, or fresh-and-non-blocking-if-you-designed-for-it.

SQL Server's nearest equivalent, the **indexed view**, is the opposite trade: created `WITH SCHEMABINDING` with a unique clustered index, it is maintained *synchronously* by every write to the base tables, so it is never stale — and every insert into `orders` now pays for the aggregate. Microsoft's guidance is explicit that with many or complex indexed views over a table, "DML query performance can degrade significantly, or in some cases, a query plan can't even be produced."

Two constraints matter for this page specifically. The defining `SELECT` **may not contain a CTE, a subquery, a derived table, a self-join, `DISTINCT`, `TOP`, `OVER`, `UNION`, an outer join, `APPLY`, or `ORDER BY`** — so "wrap my nice CTE query in an indexed view" is not a plan; you must flatten it to a single-level `GROUP BY` with `COUNT_BIG(*)`. And automatic matching is edition-dependent: Microsoft's documentation states that "automatic use of an indexed view by the query optimizer is supported only in specific editions of SQL Server. On SQL Server Standard edition, you must use the `NOEXPAND` query hint to query the indexed view directly. Azure SQL Database and Azure SQL Managed Instance support automatic use of indexed views without specifying the `NOEXPAND` hint."

> 🌍 **In the real world**: a pricing dashboard read from a PostgreSQL materialized view refreshed by a nightly cron. A mid-morning price correction went out, the dashboard kept showing yesterday's number, and a support agent quoted the stale price to a customer who then held the company to it. The team's first move was to refresh every fifteen minutes — which froze the dashboard for the duration of each refresh, because a plain `REFRESH` locks out readers. The version that shipped added a unique index so `REFRESH ... CONCURRENTLY` was legal, moved the refresh to a scheduled job with an advisory lock, and put "prices as of HH:MM" on the page. Two separate problems, staleness and blocking, that a single word in the manual distinguishes.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Subquery shapes — visualized

```
Scalar subquery (returns single value):

    SELECT id, (SELECT MAX(total) FROM orders WHERE customer_id = c.id)
    FROM customers c
                    │
                    ▼
              one value per row
              (or NULL if no match)


Derived table (returns table):

    SELECT *
    FROM (SELECT customer_id, SUM(total) AS spent
          FROM orders GROUP BY customer_id) AS sub
    WHERE sub.spent > 10000
                                    │
                                    ▼
              treated as a virtual table named "sub"


EXISTS predicate (boolean):

    WHERE EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id)
                                                            │
                                                            ▼
                                                  TRUE if any row matches
```

### Correlated vs non-correlated execution

```
Non-correlated:
  Outer:   SELECT * FROM customers WHERE country IN (X);
  Inner X: (SELECT country FROM ...)

  Optimizer:
    1. Run inner once → cache the list of countries.
    2. For each customer, check membership in cached list.
  Cost: O(outer + inner once)


Correlated:
  Outer:   SELECT * FROM customers c WHERE EXISTS (Y);
  Inner Y: (SELECT 1 FROM orders WHERE customer_id = c.id)

  Naive execution:
    For each customer:
       Run inner with this customer's id
  Cost: O(outer × inner-per-call)

  Optimizer (modern):
    Often rewrites to a semi-join:
    SELECT c.*
    FROM customers c
    SEMI JOIN orders o ON o.customer_id = c.id;
  Cost: O(outer + inner once, with hash/merge)

  → Trust the optimizer in modern Postgres / SQL Server.
```

### CTE flow — readability

```
WITH a AS (...)               step 1: data prep
,    b AS (...)               step 2: aggregate
,    c AS (...)               step 3: filter
SELECT ... FROM c JOIN ...    step 4: final result

vs equivalent nested subqueries:

SELECT ... FROM (SELECT ... FROM (SELECT ... FROM (SELECT ... FROM ...
   inner inner inner ... ))
WHERE outer outer outer ...

CTE form reads top-down. Nested form reads inside-out.
```

For complex queries, CTEs win on review-ability. Code reviewers can trace each step.

### Recursive CTE — org tree visualized

```
employees:
+----+----------+-----------+
| id | name     | manager_id|
+----+----------+-----------+
| 1  | CEO      | NULL      |
| 2  | CTO      | 1         |
| 3  | VP Eng   | 2         |
| 4  | Director | 3         |
| 5  | Engineer | 4         |
| 6  | CFO      | 1         |
+----+----------+-----------+

Iteration of the recursive CTE:

Anchor (depth 0):  WHERE manager_id IS NULL → only [1, CEO, NULL]

Recursive iteration 1 (depth 1):
   employees whose manager_id is in {1} → CTO (2), CFO (6)
   Add: [2, CTO, 1, depth=1], [6, CFO, 1, depth=1]

Recursive iteration 2 (depth 2):
   employees whose manager_id is in {2, 6} → VP Eng (3)
   Add: [3, VP Eng, 2, depth=2]

Recursive iteration 3 (depth 3):
   employees whose manager_id is in {3} → Director (4)
   Add: [4, Director, 3, depth=3]

Recursive iteration 4 (depth 4):
   employees whose manager_id is in {4} → Engineer (5)
   Add: [5, Engineer, 4, depth=4]

Iteration 5 produces no new rows → terminate.

What the recursive member sees each time (the "working table"):

  iteration 1 : working table = {CEO}              → produces {CTO, CFO}
  iteration 2 : working table = {CTO, CFO}         → produces {VP Eng}
  iteration 3 : working table = {VP Eng}           → produces {Director}
  iteration 4 : working table = {Director}         → produces {Engineer}
  iteration 5 : working table = {Engineer}         → produces {} → stop

  NOT the accumulated result. That is why an aggregate or ROW_NUMBER()
  inside the recursive member is computed over one level only.

Final result:
+----+----------+-----------+-------+
| id | name     | manager_id| depth |
+----+----------+-----------+-------+
| 1  | CEO      | NULL      | 0     |
| 2  | CTO      | 1         | 1     |
| 6  | CFO      | 1         | 1     |
| 3  | VP Eng   | 2         | 2     |
| 4  | Director | 3         | 3     |
| 5  | Engineer | 4         | 4     |
+----+----------+-----------+-------+
```

### Common patterns

**Find Nth highest** with subquery:

```sql
-- 2nd highest salary
SELECT MAX(salary) FROM employees
WHERE salary < (SELECT MAX(salary) FROM employees);
```

(Window functions are usually cleaner; see [Window Functions](./05-window-functions.md).)

**Self-comparison via correlated subquery:**

```sql
-- Find customers whose largest order exceeds the company average
SELECT c.id, c.name
FROM customers c
WHERE (SELECT MAX(o.total) FROM orders o WHERE o.customer_id = c.id)
    > (SELECT AVG(total) FROM orders);
```

**Multi-step transformation in CTE:**

```sql
WITH
    daily_sales AS (
        SELECT DATE(created_at) AS day, SUM(total) AS revenue
        FROM orders GROUP BY DATE(created_at)
    ),
    sales_with_avg AS (
        SELECT
            day, revenue,
            AVG(revenue) OVER () AS overall_avg
        FROM daily_sales
    )
SELECT day, revenue, overall_avg,
       ROUND((revenue - overall_avg) / overall_avg * 100, 1) AS pct_diff
FROM sales_with_avg
ORDER BY day;
```

(Mixing CTE with window function — chapter 5.)

### CTE inlining vs materialization

```sql
-- PostgreSQL 12+: TWO references, so the default is materialize-once.
WITH expensive AS (SELECT ... heavy aggregation ...)
SELECT * FROM expensive WHERE x = 1
UNION ALL
SELECT * FROM expensive WHERE x = 2;
-- Plan shows "CTE expensive" computed once + two "CTE Scan" nodes.

-- ONE reference: the default is to fold it into the parent, so the
-- outer predicate is pushed inside and may change the index used.
WITH expensive AS (SELECT ... heavy aggregation ...)
SELECT * FROM expensive WHERE x = 1;

-- Force either way
WITH expensive AS MATERIALIZED     (SELECT ...)  -- always compute once
WITH expensive AS NOT MATERIALIZED (SELECT ...)  -- always fold in

-- Or: explicit temp table for guaranteed single computation + real statistics
CREATE TEMP TABLE expensive AS SELECT ... ;
SELECT * FROM expensive WHERE x = 1
UNION ALL
SELECT * FROM expensive WHERE x = 2;
DROP TABLE expensive;
```

The three engines to keep straight: **PostgreSQL ≤ 11** always materialised (the CTE was an optimization fence); **PostgreSQL 12+** folds a single-reference, side-effect-free CTE and materialises a multi-reference one; **SQL Server** re-executes the definition at every reference, always, with no syntax to change it — use a temp table. **MySQL 8.0** merges what it can and materialises the rest, and a materialised CTE is computed once for the whole query — so the "compute once" intuition is closest to right there, and only there.

> 🌍 **In the real world**: a PostgreSQL 11 → 13 upgrade made one nightly report dramatically slower and nobody could see why — the SQL had not changed. The report's outer query filtered a CTE that had previously been an optimization fence; with a single reference, PG12+ folded it into the parent, pushed the outer predicate inside, and the planner switched to a nested loop driven by an index that was a poor fit for the range being scanned. `EXPLAIN` on both versions showed it in one line: `CTE Scan` before, no CTE node at all afterwards. Adding `AS MATERIALIZED` restored the old plan in one character-level change — and, more usefully, retired the team's belief that "CTEs are always materialised in Postgres", which by then was in three internal wiki pages.

### When `EXISTS` beats `IN` / `JOIN`

```sql
-- "Customers with at least one order over $1000"

-- Form 1: IN subquery
SELECT * FROM customers c
WHERE c.id IN (SELECT customer_id FROM orders WHERE total > 1000);

-- Form 2: EXISTS
SELECT * FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id AND o.total > 1000);

-- Form 3: INNER JOIN (with DISTINCT — multiplies otherwise)
SELECT DISTINCT c.* FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE o.total > 1000;
```

Modern optimizers often produce identical plans. **`EXISTS` is the most readable** and short-circuits naturally. Prefer it for "at least one" semantics.

### Worked plan — a correlated projection, before and after

The query: "for each customer, their max order, min order, and order count." Written the natural way, it is three correlated scalar subqueries.

```sql
SELECT c.id,
       (SELECT MAX(total) FROM orders o WHERE o.customer_id = c.id) AS max_total,
       (SELECT MIN(total) FROM orders o WHERE o.customer_id = c.id) AS min_total,
       (SELECT COUNT(*)   FROM orders o WHERE o.customer_id = c.id) AS order_count
FROM customers c;
```

PostgreSQL plan, abridged — three `SubPlan` nodes, each executed once per customer row:

```
Seq Scan on customers c
  SubPlan 1
    ->  Aggregate                      (loops = one per customer)
          ->  Index Scan using ix_orders_customer_id on orders o
                Index Cond: (customer_id = c.id)
  SubPlan 2
    ->  Aggregate                      (loops = one per customer)
          ->  Index Scan using ix_orders_customer_id on orders o
                Index Cond: (customer_id = c.id)
  SubPlan 3
    ->  Aggregate                      (loops = one per customer)
          ->  Index Scan using ix_orders_customer_id on orders o
                Index Cond: (customer_id = c.id)
```

Three index scans of `orders` per customer. The tell is the word `SubPlan` and a `loops` value equal to the outer row count. Rewritten as a pre-aggregating join:

```
Hash Left Join
  Hash Cond: (c.id = o.customer_id)
  ->  Seq Scan on customers c
  ->  Hash
        ->  HashAggregate              (one pass over orders, total)
              Group Key: o.customer_id
              ->  Seq Scan on orders o
```

Same result, one pass over each table. On SQL Server the same two shapes read as: *before*, a `Nested Loops` per subquery with an `Index Seek` and `Stream Aggregate` on the inner side — SQL Server may also decorrelate this into an outer join plus aggregate, which PostgreSQL will not; *after*, a `Hash Match (Aggregate)` feeding a `Hash Match (Left Outer Join)`.

Which to prefer is a cardinality question, not a style question:

```
outer query returns FEW rows (paged screen, filtered list)
    → LATERAL / CROSS APPLY: work is done only for surviving rows
outer query returns MANY rows (a report over the whole table)
    → pre-aggregate + join: one pass, no per-row seek
```

### Anti-join, four spellings

```sql
-- 1. NOT EXISTS  — correct with NULLs, becomes an anti-join on both engines
SELECT c.* FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id);

-- 2. NOT IN      — wrong with NULLs; PostgreSQL cannot make it an anti-join
SELECT * FROM customers
WHERE id NOT IN (SELECT customer_id FROM orders);

-- 3. LEFT JOIN / IS NULL — correct, and the plan is usually the same anti-join,
--    but it materialises the join first on some plans and reads worse
SELECT c.* FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.customer_id IS NULL;

-- 4. EXCEPT      — correct, deduplicates the result (that may or may not be wanted)
SELECT id FROM customers
EXCEPT
SELECT customer_id FROM orders;
```

Plan operators to look for:

```
PostgreSQL   NOT EXISTS      →  Hash Anti Join / Nested Loop Anti Join
             NOT IN          →  hashed SubPlan (fits work_mem) or SubPlan (per row)
             LEFT JOIN+NULL  →  Hash Anti Join (recognised) or Hash Left Join + Filter

SQL Server   NOT EXISTS      →  Hash Match / Nested Loops, logical op = Left Anti Semi Join
             NOT IN          →  same, IF the inner column is NOT NULL;
                                extra NULL-handling operators if it is nullable
```

### Deduplicating rows — the same idea, three dialects

`ROW_NUMBER()` in a CTE plus a delete is the standard de-dup. Only SQL Server lets you delete from the CTE itself.

```sql
-- SQL Server: the CTE is the DELETE target. This is legal and idiomatic T-SQL.
WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY email ORDER BY created_at, id) AS rn
    FROM customers
)
DELETE FROM ranked WHERE rn > 1;

-- PostgreSQL: a CTE is never an update/delete target. Delete from the base
-- table, matching on ctid (the physical row id) so duplicates with identical
-- column values are still distinguishable.
WITH ranked AS (
    SELECT ctid, ROW_NUMBER() OVER (PARTITION BY email ORDER BY created_at, id) AS rn
    FROM customers
)
DELETE FROM customers c
USING ranked r
WHERE c.ctid = r.ctid AND r.rn > 1;

-- MySQL 8.0: MySQL rejects modifying a table the same statement also reads
-- (error 1093, "You can't specify target table ... for update in FROM clause").
-- The extra derived-table layer forces materialisation and makes it legal.
DELETE FROM customers
WHERE id IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY email ORDER BY created_at, id) AS rn
        FROM customers
    ) AS ranked
    WHERE rn > 1
);
```

Run the `SELECT` version first, always. A `PARTITION BY` on the wrong column deletes real data, and the statement gives no hint that it is about to.

### Where your `IN` list actually comes from — EF Core

Most `IN (subquery)` and `IN (list)` SQL in a .NET shop is generated, and what it generates has changed three times:

| EF Core | `ids.Contains(b.Id)` becomes | Consequence |
|---|---|---|
| ≤ 7 | `IN (1, 2, 3)` — values inlined as constants | New SQL text per distinct list; plan-cache churn |
| 8, 9 | `IN (SELECT value FROM OPENJSON(@ids))` on SQL Server | Stable SQL, one plan — but the planner no longer knows how many values there are |
| 10 | `IN (@ids1, @ids2, @ids3, …)`, one parameter per element, list length padded | Stable-ish SQL *and* cardinality visible to the planner |

EF 9 added control over which strategy is used; EF 10 exposes it globally as `UseParameterizedCollectionMode(...)` and per query as `EF.Constant(ids)`. `.Any(...)` inside a `Where` still translates to `EXISTS`, which is the one thing that has been stable throughout.

> 🌍 **In the real world**: a batch endpoint that loaded orders for a list of ids was fine on EF Core 6 for short lists and fell over once a caller started sending long ones — every distinct list produced a new SQL string, and the plan cache filled with single-use plans. The team upgraded to EF 8 expecting the `OPENJSON` translation to fix it, and it did fix the cache churn — then a different query regressed, because with the list hidden inside `OPENJSON` the optimizer estimated a fixed row count and chose a nested loop for a list that was sometimes huge. The version that stuck: chunk the ids in application code, and for the genuinely large case pass a table-valued parameter and join to it, so the database sees a real table with real cardinality instead of a list pretending to be a predicate.

</details>

## Common pitfalls

1. **`NOT IN` with NULLs.** Returns 0 rows if subquery yields any NULL. Always use `NOT EXISTS` for anti-join semantics.
2. **Scalar subquery returning multiple rows.** Runtime error. Add `LIMIT 1` or aggregate.
3. **Correlated subquery in `SELECT` list on huge tables.** Per-row execution can be slow; rewrite as JOIN + GROUP BY when possible.
4. **CTE re-evaluated per reference.** SQL Server re-executes the definition at every reference, always. PostgreSQL 12+ does the opposite — two references means materialise once — and PostgreSQL ≤ 11 always materialised. Getting this backwards for Postgres is a common interview miss. Use a temp table when you need a single-evaluation guarantee on any engine.
5. **Recursive CTE without base case termination.** Anchor must produce rows; recursive must eventually produce no new rows. Otherwise infinite (or limit-capped error).
6. **Recursive CTE without cycle detection on graphs.** Graphs can have cycles; tracking visited nodes prevents infinite recursion.
7. **CTE thinking it's a view.** CTE exists only within the statement. To share across queries, use a View.
8. **`WITH RECURSIVE` keyword (PostgreSQL/MySQL) vs SQL Server.** PostgreSQL/MySQL require `RECURSIVE`; SQL Server doesn't.
9. **Subquery alias missing.** Derived tables in `FROM` need an alias (`(SELECT ...) AS sub`) on SQL Server, MySQL, and PostgreSQL ≤ 15. PostgreSQL 16 made it optional, so a query written on a PG16 laptop can fail on a PG15 server.
10. **`WHERE EXISTS` with no correlation.** `EXISTS (SELECT 1 FROM other)` always TRUE if `other` has rows — likely a bug; you forgot the correlating predicate.
11. **Confusing inlined CTE performance.** "I named it; surely it's computed once." Test in your dialect; add `MATERIALIZED` if needed.
12. **Over-using subqueries when JOIN suffices.** "Customers with their order count" via correlated subquery vs `JOIN ... GROUP BY` — usually the JOIN is clearer and faster.
13. **`ORDER BY` inside a CTE or derived table sorts nothing.** SQL Server rejects it outright unless you add `TOP` or `OFFSET/FETCH`, and even then the documentation is explicit: the clause "is used only to determine the rows returned by the `TOP` clause or `OFFSET` and `FETCH` clauses. The `ORDER BY` clause doesn't guarantee ordered results when these constructs are queried, unless `ORDER BY` is also specified in the query itself." A CTE that appears to come back sorted is a coincidence of the current plan.
14. **Assuming a `WITH` clause runs top to bottom.** Non-recursive CTEs are definitions, not steps. In PostgreSQL, data-modifying CTEs are executed "concurrently with each other and with the main query", so ordering between them is unpredictable, and they all see the same snapshot.
15. **Assuming a correlated scalar subquery will be decorrelated.** SQL Server often can. PostgreSQL does not unnest correlated scalar subqueries in the `SELECT` list — it runs a `SubPlan` per outer row, forever, regardless of statistics.
16. **`OPTION (MAXRECURSION 0)` as the fix for error 530.** Removing the cap on a query that has a cycle converts a failed statement into one that fills tempdb. Raise the cap to a real bound *and* add a cycle guard.
17. **Aggregates or `ROW_NUMBER()` inside the recursive member.** They see only the current iteration's rows, not the accumulated result — SQL Server documents exactly this behaviour with a `ROW_NUMBER()` that returns `1` on every row. Do the ranking in the outer query.
18. **Anchor type too narrow in a recursive CTE.** The anchor fixes each column's type. `SELECT '' AS path` gives a one-character column and the recursion fails to compile with a type mismatch; `CAST('' AS VARCHAR(4000))` fixes it.
19. **Reaching for a temp table for "single computation" when the real win is statistics.** A temp table gets a row count, column statistics, and an optional index; the consuming statement is compiled against them. Table variables get no column statistics at all — and only from SQL Server 2019 under compatibility level 150 does deferred compilation give the optimizer their real row count.
20. **Treating a long report as read-only.** On SQL Server with the on-premises default (`READ_COMMITTED_SNAPSHOT OFF`), a big scan takes shared locks that can escalate and block writers. On PostgreSQL, MySQL/InnoDB, and Azure SQL Database (where RCSI is on by default) it does not. `WITH (NOLOCK)` is not the fix — under read uncommitted "rows can appear or disappear in the data set before the end of the transaction", which is how a report starts disagreeing with the ledger.
21. **An unqualified column inside a subquery.** Name resolution runs inside-out on every engine, so a column that does not exist on the inner table silently binds to the outer one and turns your filter into a tautology. `DELETE ... WHERE id IN (SELECT id FROM staging)` where `staging` has no `id` deletes the table. Alias the inner table and qualify every column in the subquery, on both sides of a correlating predicate.
22. **`UPDATE ... FROM` a source with duplicates.** Documented as undefined on SQL Server and "not readily predictable" on PostgreSQL: one arbitrary matching row wins, silently. The correlated-scalar form errors instead but NULLs the unmatched rows. Rank in a CTE and filter `rn = 1` so the tie-break is a decision, with a unique `ORDER BY` so the ranking itself is deterministic.
23. **A queue claim that reads and then writes in two statements.** Two workers read the same rows. One statement, with `FOR UPDATE SKIP LOCKED` inside the subquery (PostgreSQL, MySQL 8.0) or `WITH (READPAST, UPDLOCK, ROWLOCK)` plus `OUTPUT` (SQL Server). And on SQL Server, know that `READPAST` is rejected when RCSI is on and the session is read committed — add `READCOMMITTEDLOCK`. RCSI is on by default on Azure SQL Database.
24. **Expecting an outer filter to reach the scan.** A predicate can only be evaluated inside a CTE if doing so cannot change what the CTE returns. It never crosses `LIMIT`/`TOP`, never crosses a volatile function, and crosses a window function only when it references only `PARTITION BY` columns. A filter on `rn` is evaluated last, after everything below it has been computed.
25. **Rewriting `> ALL`/`> ANY` as `> MAX`/`> MIN`.** The equivalence holds only when the subquery returns at least one row and no NULLs. Aggregates skip NULLs and return NULL over an empty set; the quantifiers use three-valued logic over the whole set. `> ALL` over an empty set is TRUE; `> MAX(empty)` is UNKNOWN.

## Interview-ready summary

- **Subquery** = SELECT inside another SELECT/INSERT/UPDATE/DELETE. Scalar (1 value), row (1 row), table (set).
- **Correlated** subqueries reference the outer query (per-row execution conceptually). **Non-correlated** run once.
- **`EXISTS` / `NOT EXISTS`** for "at least one match" / "no match" — short-circuits, NULL-safe.
- **`NOT IN`** is a gotcha with NULLs; prefer `NOT EXISTS`.
- **CTE (`WITH ...`)** names a query step; chain multiple for readability; supports recursion.
- **Recursive CTE** = anchor + recursive UNION ALL; terminates when recursive produces no new rows.
- **CTE vs View vs Materialized View vs Temp Table:** statement-scope vs persistent vs cached vs session.
- **The evaluation contract differs by engine.** SQL Server re-executes a CTE per reference (documented). PostgreSQL 12+ folds a single-reference CTE and materialises a multi-reference one; ≤ 11 always materialised. MySQL merges when it can, and a CTE it materialises is materialised once for the query.
- **Decorrelation is reliable for `EXISTS`/`IN` and not for scalar subqueries in `SELECT`** — SQL Server can unnest those, PostgreSQL does not.
- **`NOT IN` also has a plan problem, not just a NULL problem:** PostgreSQL can't turn it into an anti-join, so it uses a hashed SubPlan that only works while the subquery fits `work_mem`.
- **Recursion is iteration over a working table:** the recursive member sees only the previous level, which is why aggregates and window functions inside it are meaningless.
- **Depth caps:** SQL Server 100 by default (error 530, `OPTION (MAXRECURSION 0–32767)`); MySQL `cte_max_recursion_depth` 1000; PostgreSQL none.
- **Data-modifying CTEs are PostgreSQL-only:** one snapshot, unpredictable order between sub-statements, one modification per row.
- **Correlation comes from name resolution, not from intent.** Unqualified columns in a subquery resolve inside-out and bind outward when the inner table lacks them — a typo becomes an always-true predicate. Qualify everything.
- **A subquery that supplies values has different failure modes than one that filters.** `UPDATE … FROM` with duplicates is undefined (SQL Server) / "not readily predictable" (PostgreSQL); the correlated-scalar form errors on duplicates and NULLs on no-match.
- **Queue claims are one statement:** `FOR UPDATE SKIP LOCKED` inside the subquery on PostgreSQL/MySQL 8.0, `READPAST, UPDLOCK, ROWLOCK` + `OUTPUT` on SQL Server — and `READCOMMITTEDLOCK` too when RCSI is on.
- **Predicates cross a CTE boundary only when moving them changes nothing:** never past `LIMIT`/`TOP` or a volatile function, past a window function only on `PARTITION BY` columns.

**Expected interview questions:**

1. *"Find customers who haven't placed any orders."* — `WHERE NOT EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id)`. Or LEFT JOIN + IS NULL.
2. *"What's the difference between a CTE and a subquery?"* — CTE is a named subquery using `WITH`. Cleaner for multi-step queries; supports recursion. Subquery is inline; better for simple cases.
3. *"How do you query a hierarchy (e.g., org chart)?"* — Recursive CTE with anchor (top-level rows) and recursive (rows whose parent is in the CTE so far) joined by `UNION ALL`.
4. *"Why is `NOT IN` problematic with NULLs?"* — If the subquery returns any NULL, `x NOT IN (...)` evaluates to NULL (treated as false), filtering everything out.
5. *"`EXISTS` vs `IN`?"* — `EXISTS` checks for row presence (boolean); short-circuits. `IN` compares value to a list. Often equivalent in modern optimizers; `EXISTS` is NULL-safe and often faster.
6. *"How do you generate a sequence of dates in SQL?"* — Recursive CTE: anchor = first date; recursive = previous + 1 day until end. PostgreSQL has `generate_series()`.
7. *"When would you use a temp table over a CTE?"* — When the CTE is heavy and referenced multiple times, and your dialect re-evaluates per reference. Or for multi-statement scripts where the result is reused. The stronger answer adds statistics: a temp table gives the optimizer a real row count and column statistics for the rest of the query, which a CTE boundary cannot.
8. *"Is a CTE computed once?"* — Name the engine before answering. SQL Server: no, re-executed per reference. PostgreSQL 12+: once if referenced more than once, folded if referenced once. MySQL: merged into the parent when the definition allows it, otherwise materialised once for the whole query. If you need a guarantee, use a temp table.
9. *"How would you archive and delete rows in one statement?"* — PostgreSQL: `WITH moved AS (DELETE ... RETURNING *) INSERT INTO archive SELECT * FROM moved`. SQL Server: `DELETE ... OUTPUT deleted.* INTO archive`. Then mention the snapshot rule: other CTEs in the same statement won't see the delete.
10. *"A recursive CTE returns wrong ranks — you added `ROW_NUMBER()` inside the recursive member. Why?"* — The recursive member is evaluated against the previous iteration's working table only, so the window function sees one level at a time. Rank in the outer query.
11. *"Your report blocks checkout on SQL Server. What do you change?"* — Not `NOLOCK`. Either row versioning (`READ_COMMITTED_SNAPSHOT ON`, already the default on Azure SQL Database) or move the report off the primary. Say why `NOLOCK` is worse than the problem: rows can be missed or double-counted, silently.
12. *"`DELETE FROM orders WHERE id IN (SELECT id FROM staging)` deleted every order. The staging table had rows in it. What happened?"* — `staging` has no `id` column, so the inner `id` resolved outward to `orders.id` and the predicate became `orders.id IN (orders.id, …)`, true for every row. Name resolution runs inside-out on all three engines. Fix: alias the inner table and qualify the column, which turns the bug into a compile error.
13. *"How do you hand out work from a jobs table to several workers?"* — One statement that claims and returns. PostgreSQL: a CTE with `FOR UPDATE SKIP LOCKED` and `LIMIT`, then `UPDATE … RETURNING`. SQL Server: `UPDATE TOP (n) … WITH (READPAST, UPDLOCK, ROWLOCK) … OUTPUT inserted.*`. Then the follow-ups worth volunteering: without `SKIP LOCKED` the blocked worker re-evaluates its `WHERE` after unblocking and comes back short rather than inheriting the rows; and `READPAST` is rejected under RCSI at read committed unless you add `READCOMMITTEDLOCK`.
14. *"You added `WHERE customer_id = @id` outside a CTE that ranks rows. Why is it still scanning everything?"* — A predicate can only be evaluated inside the CTE if that cannot change what the CTE returns. A filter on the window's own result (`rn`) never can. A filter on a `PARTITION BY` column can, because it drops whole partitions — PostgreSQL pushes it down when the qual references only partitioning columns and is non-volatile. If `customer_id` is not in the `PARTITION BY`, put it there.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — Correlated vs non-correlated subqueries

> **Q**: What's the difference between correlated and non-correlated subqueries?
>
> **A**: A **non-correlated** subquery is independent of the outer query — it can run by itself and yields the same result regardless of outer rows. Runs once. A **correlated** subquery references the outer query (typically a column alias from the outer FROM) — conceptually runs once per outer row, dependent on outer values.
>
> **Cross-Q**: Does "runs once per outer row" mean correlated subqueries are always slower?
>
> **A**: It depends on where the subquery sits, and the honest answer names the engine. For correlated predicates in `WHERE` — `EXISTS`, `IN`, `NOT EXISTS` — both PostgreSQL and SQL Server reliably produce semi-joins and anti-joins, and "correlated" says nothing about cost. For a correlated scalar subquery in the `SELECT` list, SQL Server can decorrelate it into a join plus aggregate (its optimizer is built on the `Apply` operator; see Galindo-Legaria and Joshi, SIGMOD 2001), while **PostgreSQL does not unnest target-list scalar subqueries at all** — it plans a `SubPlan` and runs it per outer row. Always check the plan.
>
> **Cross-Q²**: How do you spot the failure in a plan, and what do you do about it?
>
> **A**: In PostgreSQL, `SubPlan` with `loops` equal to the outer row count means per-row execution (an `InitPlan` is the harmless uncorrelated case, run once). In SQL Server, look for `Nested Loops` driving a subtree once per outer row, often with an `Index Spool (Lazy Spool)` caching it. The fix is a rewrite, not a hint: pre-aggregate and join when the outer query returns many rows, or `LATERAL`/`CROSS APPLY` when it returns few. Other things that defeat the rewriter: volatile functions in the subquery (`random()`, `now()`-style, anything the planner can't reorder), `LIMIT`/`TOP` inside the subquery, and recursive CTEs, which are never folded.

### Drill 2 — EXISTS vs IN vs JOIN equivalence

> **Q**: Three ways to find "customers with at least one order" — which performs best?
>
> **A**: `EXISTS`: `WHERE EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id)` — short-circuits at first match, no row multiplication. `IN`: `WHERE c.id IN (SELECT customer_id FROM orders)` — equivalent semantically but with NULL-handling caveats. `INNER JOIN + DISTINCT`: produces every matching pair, then dedupes. EXISTS is typically fastest because it short-circuits per outer row; JOIN + DISTINCT materializes all pairs first.
>
> **Cross-Q**: For modern Postgres, are these three plans really different?
>
> **A**: Often identical — the optimizer detects `IN (SELECT)`, `EXISTS`, and `INNER JOIN` semi-join patterns and produces a hash semi-join for all three. The difference shows up in (1) edge cases like NULL handling, (2) older engines that don't unify the plans, (3) compound predicates that confuse the rewriter. EXISTS is the safest semantic choice; performance is usually a wash on modern engines.
>
> **Cross-Q²**: When does `INNER JOIN + DISTINCT` beat EXISTS?
>
> **A**: Almost never for "at least one" semantics — EXISTS short-circuits, JOIN doesn't. The exception is when you also need columns from the right table; then JOIN is necessary regardless. But if you need columns AND uniqueness, take the per-outer-row form: `LEFT JOIN LATERAL (SELECT ... ORDER BY ... LIMIT 1) ON true` or `DISTINCT ON (...)` in PostgreSQL, `OUTER APPLY (SELECT TOP (1) ... ORDER BY ...)` in SQL Server. Those avoid materialising every matching pair only to throw most of them away. (Mixing the dialects — `LATERAL` with `TOP`, or `APPLY` with `LIMIT` — is a syntax error and a giveaway in an interview.)

### Drill 3 — Recursive CTE for hierarchies

> **Q**: Write a recursive CTE that returns every employee with their depth in the org chart.
>
> **A**: ```sql
> WITH RECURSIVE org_tree AS (
>     SELECT id, name, manager_id, 0 AS depth FROM employees WHERE manager_id IS NULL
>     UNION ALL
>     SELECT e.id, e.name, e.manager_id, ot.depth + 1
>     FROM employees e JOIN org_tree ot ON e.manager_id = ot.id
> )
> SELECT * FROM org_tree;
> ```
> Anchor produces top-level (no manager); recursive joins each level to the previous iteration's results; UNION ALL combines all levels.
>
> **Cross-Q**: What if the data has a cycle (A reports to B, B reports to A)?
>
> **A**: Infinite recursion — but the two engines fail differently, and saying so is the point of the question. SQL Server stops at 100 recursion levels by default and raises error 530, *"The statement terminated. The maximum recursion 100 has been exhausted before statement completion."* **PostgreSQL has no cap and no such error**: the working table grows until it exhausts memory and then temp disk, so you get a disk or temp-file failure, a `statement_timeout` cancellation, or a full data volume. Fix: track visited IDs in an array — `path || e.id` in the recursive step plus `WHERE NOT (e.id = ANY(path))` — or, on PostgreSQL 14+, the built-in `CYCLE id SET is_cycle USING cycle_path` clause, which maintains that array for you.
>
> **Cross-Q²**: Why does UNION ALL work but UNION lead to subtle bugs in recursive CTEs?
>
> **A**: First, note that the choice only exists on two of the three engines: `UNION` in a recursive CTE is legal on PostgreSQL and MySQL, and SQL Server rejects it — "`UNION ALL` is the only set operator allowed between the last anchor member and first recursive member". Where you do have the choice: `UNION` deduplicates each iteration's results against all previous iterations. For trees this is usually fine because IDs are unique. But for graphs with shared sub-paths, dedup can drop rows you need (different paths to the same node, where each path should be reported), and it costs a probe of the whole accumulated result on every iteration. UNION ALL keeps everything; you control termination via the recursive predicate. Standard practice: use UNION ALL, carry a path column, and dedup explicitly outside the CTE if needed — which is also the only portable answer.

### Drill 4 — Max recursion depth

> **Q**: What's the default max recursion depth in SQL Server vs Postgres?
>
> **A**: SQL Server: a server-wide default of 100 — the statement is terminated with error 530 after 100 recursion levels unless you specify `OPTION (MAXRECURSION N)`, where N is 0–32767 and 0 means no limit. PostgreSQL: no cap at all, and no equivalent error. MySQL 8.0 sits in between with `cte_max_recursion_depth`, default 1000, adjustable per session.
>
> **Cross-Q**: I have a 50-level org chart in SQL Server — what do I set?
>
> **A**: 50 levels is inside the default 100, so nothing — unless the tree can deepen, in which case set an explicit bound you can defend, say `OPTION (MAXRECURSION 200)`. Do not reach for `OPTION (MAXRECURSION 0)`: "no limit" is only safe if you have proven there are no cycles, and the proof usually doesn't exist because the data is user-entered. Cap at a real bound *and* carry a path column.
>
> **Cross-Q²**: Why does Postgres not have a default cap, and what actually stops a runaway there?
>
> **A**: Philosophy difference — SQL Server defaults to "protect the server", PostgreSQL to "trust the developer". Nothing in the CTE machinery stops it: PostgreSQL's working table spills from `work_mem` to temp files rather than erroring, so a cycle consumes temp disk until it hits `temp_file_limit`, fills the volume, or the query is cancelled. The practical protections are external: `statement_timeout` on the connection, `temp_file_limit`, and a cycle guard in the query. Know which one of those is actually configured on your database before claiming you're protected.

### Drill 5 — Materialized vs inline CTE (Postgres 12+)

> **Q**: In Postgres 12+, when is a CTE inlined vs materialized?
>
> **A**: The rule is a reference count, not a cost estimate. From the PostgreSQL documentation: "if a `WITH` query is non-recursive and side-effect-free (that is, it is a `SELECT` containing no volatile functions) then it can be folded into the parent query... By default, this happens if the parent query references the `WITH` query just once, but not if it references the `WITH` query more than once." A CTE containing a volatile function or a data-modifying statement is never folded. You can force either way: `WITH cte AS MATERIALIZED (...)` to compute once; `WITH cte AS NOT MATERIALIZED (...)` to fold it in regardless of reference count.
>
> **Cross-Q**: Why was this changed in Postgres 12?
>
> **A**: Pre-12, all CTEs were optimization fences — always materialized, no predicate push-down. Users used CTEs as a "make the optimizer stop" hint. This hurt performance when the CTE was actually just a logical naming device and could have been inlined. Postgres 12 made CTEs behave like inline subqueries by default (consistent with SQL Server) — better performance, less surprising for newcomers. The old behavior is now opt-in via `MATERIALIZED`.
>
> **Cross-Q²**: When should you force MATERIALIZED?
>
> **A**: Three cases. (1) **Expensive CTE referenced multiple times** — without materialization the engine recomputes per reference. (2) **Side effects** like calling functions with effects (rare in CTEs but possible). (3) **Optimizer bug workaround** — when inlining causes a bad plan and you want to force materialization as a tuning hint. For (1) and (3), `MATERIALIZED` is the cleanest fix; for many-references and very heavy work, a real temp table is often better still.

### Drill 6 — CTE performance myths

> **Q**: "I named it in a CTE so it computes once" — true or false?
>
> **A**: On SQL Server, false — the documentation states that CTE results "aren't materialized" and that "each outer reference to the named result set requires the defined query to be re-executed". On PostgreSQL it is true by default whenever you reference the CTE more than once (12+), and was true unconditionally before 12. On MySQL 8.0 it is true: a materialised CTE is "materialized once for the query, even if the query references it several times". So the honest answer is "on which engine?" — and the only universal way to guarantee it is a temp table.
>
> **Cross-Q**: How do I guarantee single computation?
>
> **A**: Two that guarantee it and one that doesn't. (1) `WITH cte AS MATERIALIZED (...)` in Postgres 12+. (2) Materialize to a temp table — works on any engine, and additionally gives the consuming statement real statistics. (3) A derived table in `FROM` and hope the engine caches: no guarantee. There is a correctness angle too — on SQL Server, two references means two executions against live data, so a CTE containing `NEWID()` or reading a table that is being written produces two different answers within one statement.
>
> **Cross-Q²**: Why does SQL Server still always inline?
>
> **A**: Its optimizer treats a CTE purely as a named subquery — the definition is substituted at each reference and re-optimized, which lets predicates and join orders cross the CTE boundary and sometimes yields a better plan. The cost is recomputation. Microsoft's documentation says as much and gives the remedy directly: "for queries that require multiple references to the named result set, consider using a temporary object instead." Treat the T-SQL CTE as a readability construct with no performance semantics attached.

### Drill 7 — CTEs vs derived tables

> **Q**: When is a CTE clearly better than a derived table (subquery in FROM)?
>
> **A**: When (1) the same subquery is referenced multiple times (CTE names it once), (2) the query has multiple logical steps that benefit from top-down reading, (3) you need recursion (only CTE supports it), or (4) you want explicit names for review-ability. Derived tables work fine for one-step subqueries with one reference but get hard to read past two levels of nesting.
>
> **Cross-Q**: Is there a performance difference?
>
> **A**: Usually no — modern optimizers treat both as named subqueries and produce identical plans. Exceptions: (a) Postgres pre-12 always materialized CTEs (derived tables sometimes inlined → different plan); (b) Some recursion patterns work only in CTEs. For non-recursive queries on modern engines, choose based on readability.
>
> **Cross-Q²**: Why do code-style guides increasingly favor CTEs?
>
> **A**: Top-down reading. A CTE-based query reads like prose: "step 1 (CTE), step 2 (CTE), final SELECT." Derived-table queries read inside-out: parse the deepest subquery first, work outward. For complex queries reviewed in pull requests, CTEs are much easier to comment, refactor, and reason about. Performance-equivalent + dramatically better review-ability = the modern default.

### Drill 8 — Scalar subquery in SELECT caveats

> **Q**: `SELECT id, (SELECT MAX(total) FROM orders WHERE customer_id = c.id) FROM customers c` — what could go wrong?
>
> **A**: Three risks. (1) If the subquery returns more than one row for some customer (bug in correlation predicate), runtime error: "scalar subquery returns more than one row." (2) Naive execution runs the subquery per outer row — slow on large tables (the optimizer often rewrites this, but not always). (3) NULL semantics: customers with no orders return NULL for the column — caller must handle.
>
> **Cross-Q**: How do you safely return a scalar that might be multi-row?
>
> **A**: Aggregate inside the subquery (`MAX`, `MIN`, `SUM`, etc.) — these return exactly one row. Or `LIMIT 1` + deterministic ORDER BY: `(SELECT total FROM orders WHERE customer_id = c.id ORDER BY created_at DESC LIMIT 1)`. The aggregation pattern is more common; LIMIT 1 is for "newest" or "first" semantics where you want a specific row's value.
>
> **Cross-Q²**: When should you rewrite to JOIN + GROUP BY instead?
>
> **A**: When you need multiple scalar values from the same correlated context — e.g., MAX total, MIN total, and COUNT in one query. Per-column correlated subqueries each scan the orders table; one JOIN + GROUP BY scans it once. Rewrite: `LEFT JOIN (SELECT customer_id, MAX(total) AS max_t, MIN(total) AS min_t, COUNT(*) AS cnt FROM orders GROUP BY customer_id) o ON o.customer_id = c.id`.

### Drill 9 — ANY / ALL / SOME quantifiers

> **Q**: What does `WHERE x > ANY (SELECT y FROM t)` mean?
>
> **A**: True if `x > y` for **at least one** y in the subquery. `ALL`: true if `x > y` for **every** y. `SOME` is a synonym for ANY. The usual shorthand is `> ANY` ≡ `> MIN(subquery)` and `> ALL` ≡ `> MAX(subquery)` — but say the condition out loud, because the shorthand holds only when the subquery returns **at least one row and no NULLs**. Aggregates skip NULLs and return NULL over an empty input; the quantifiers evaluate three-valued logic over the whole set. Two divergences follow: over an empty set `> ALL` is TRUE while `> MAX(…)` is `x > NULL` = UNKNOWN; and over `(1, NULL)` with `x = 5`, `> ALL` is `TRUE AND UNKNOWN` = UNKNOWN while `> MAX(…)` is `5 > 1` = TRUE. The rewrite that "means the same thing" changes which rows survive.
>
> **Cross-Q**: Why are ANY/ALL rarely used in practice?
>
> **A**: They're equivalent to clearer constructs. `x > ANY (...)` → `x > (SELECT MIN(...))` (clearer intent). `x = ANY (...)` → `x IN (...)` (idiomatic). `x <> ALL (...)` → `x NOT IN (...)` (idiomatic). Most code uses MIN/MAX scalars or IN/NOT IN instead. ANY/ALL persist in the SQL standard for completeness but feel verbose in practice.
>
> **Cross-Q²**: What's the gotcha with `<> ALL` and NULLs?
>
> **A**: Same as `NOT IN` — if the subquery returns any NULL, `<> ALL` returns NULL (treated as falsy in WHERE), filtering everything. `x <> ALL (a, b, NULL)` ≡ `x <> a AND x <> b AND x <> NULL`; the last conjunct is UNKNOWN; whole expression UNKNOWN. Same fix: filter NULLs from the subquery or use `NOT EXISTS`. The NULL trap is universal across the "negative" quantifiers.

### Drill 10 — NOT IN + NULL gotcha

> **Q**: `SELECT * FROM customers WHERE id NOT IN (SELECT customer_id FROM orders)` returns zero rows. Some customers clearly have no orders. Why?
>
> **A**: At least one `customer_id` in orders is NULL. `x NOT IN (1, 2, NULL)` becomes `x <> 1 AND x <> 2 AND x <> NULL`; the third conjunct evaluates to UNKNOWN (three-valued logic), and `TRUE AND TRUE AND UNKNOWN` = UNKNOWN, which WHERE treats as falsy. Every outer row is filtered out.
>
> **Cross-Q**: What's the canonical fix?
>
> **A**: Use `NOT EXISTS`: `WHERE NOT EXISTS (SELECT 1 FROM orders WHERE customer_id = c.id)`. NOT EXISTS is row-by-row anti-join semantics — NULL on either side doesn't poison the whole query. Each outer row is checked independently against the subquery's matching rows; if no match, the row is kept regardless of NULLs elsewhere. NULL-safe by design.
>
> **Cross-Q²**: Why did SQL standardize this NULL-poison behavior?
>
> **A**: Mathematical purity. "x is not in set S" formally requires "x is not equal to any element of S." If S contains NULL, and "x = NULL" is undefined under three-valued logic, then "x is not equal to NULL" is also undefined, and the whole conjunction collapses. Changing this would require special-casing NULL in IN, which the standard committee rejected as inconsistent. The pragmatic answer is "use NOT EXISTS"; the textbook answer is "this is the SQL standard."

### Drill 11 — Subquery folding optimization

> **Q**: The optimizer "folds" subqueries — what does that mean?
>
> **A**: It rewrites a subquery into a flat join when semantics permit. `SELECT * FROM a WHERE id IN (SELECT a_id FROM b WHERE x = 1)` folds to `SELECT a.* FROM a JOIN b ON b.a_id = a.id WHERE b.x = 1` (semi-join). The folded form often has better plans (hash join, merge join) than the unfolded form's nested-loop default.
>
> **Cross-Q**: When does folding fail?
>
> **A**: (1) Subquery with aggregates that can't be pushed up: `WHERE id IN (SELECT MAX(a_id) FROM b GROUP BY ...)` — the aggregation must materialize first. (2) Non-deterministic functions in the subquery (random, timestamp): can't be reordered. (3) Subqueries with `LIMIT` and `ORDER BY`: limit semantics can't fold without changing results. (4) Recursive CTEs: never folded.
>
> **Cross-Q²**: How do I check if folding happened?
>
> **A**: EXPLAIN, and read the operator names precisely — three different PostgreSQL nodes get confused for each other here. `Hash Semi Join` / `Nested Loop Semi Join` is a folded `IN`/`EXISTS`; that is the outcome you want. `SubPlan` (or `hashed SubPlan`) is an `IN`/`EXISTS` that was **not** folded and is being executed as a subplan instead — that is the one to chase, and `loops=` on its inner nodes tells you whether it runs once or per outer row. `Subquery Scan` is a different thing entirely: a `FROM`-clause subquery that could not be pulled up into the parent, which is common and often harmless. Chasing `Subquery Scan` when you meant `SubPlan` is how people conclude the optimizer is fine when it isn't.

### Drill 12 — Lateral joins as subquery alternative

> **Q**: When does LATERAL replace a correlated subquery?
>
> **A**: When you need multiple columns from a per-outer-row computation. A correlated scalar subquery in SELECT returns one value per row; for multiple values you'd write multiple scalar subqueries (each scanning the source). LATERAL lets the right-side subquery reference outer aliases AND return multiple columns at once: `FROM customers c JOIN LATERAL (SELECT MAX(total), MIN(total), COUNT(*) FROM orders WHERE customer_id = c.id) o ON true`.
>
> **Cross-Q**: Why is LATERAL often faster than 3 separate scalar subqueries?
>
> **A**: Count the scans. Three correlated scalar subqueries are three separate subplans, each one probing `orders` per outer row; the `LATERAL` block is one subplan producing three columns from a single probe per outer row. Whether that matters depends on the outer cardinality — for one row it is invisible, and the gap widens with every additional outer row, because the work removed is (outer rows × 2 extra probes). Don't quote a multiplier; describe the count.
>
> **Cross-Q²**: What's CROSS APPLY in SQL Server?
>
> **A**: Same concept, different syntax. `FROM customers c CROSS APPLY (SELECT MAX(total), MIN(total) FROM orders WHERE customer_id = c.id) o` ≡ Postgres `JOIN LATERAL ... ON true`. `OUTER APPLY` ≡ `LEFT JOIN LATERAL ... ON true` — keeps outer rows when the subquery returns nothing. APPLY pre-dates standard LATERAL; SQL Server kept the syntax for backward compatibility.

### Drill 13 — CTE referencing CTE chains

> **Q**: Can a CTE reference another CTE defined in the same WITH clause?
>
> **A**: Yes — CTEs are processed top-to-bottom (logically), so later CTEs can reference earlier ones. `WITH a AS (...), b AS (SELECT * FROM a WHERE ...), c AS (SELECT * FROM b ...) SELECT * FROM c`. Each step builds on the previous, and the main SELECT consumes the final step. This is the cleanest way to express multi-step transformations.
>
> **Cross-Q**: Can a CTE reference a later one?
>
> **A**: No, except in recursive CTEs (where the recursive member references the CTE itself, but the lexical order is anchor-first). Forward references would create cycles in non-recursive CTEs — engines reject them.
>
> **Cross-Q²**: What's the plan implication of a 5-step CTE chain?
>
> **A**: Depends on the engine. Postgres 12+ tries to inline each step into the next where it can push predicates through — the final plan might collapse all 5 steps into one optimized query. SQL Server inlines all of them by default. Without inlining (forced MATERIALIZED), each step is computed and materialized in order — clean and predictable, but slower if predicates could have been pushed across step boundaries. For long chains on hot queries, EXPLAIN both forms.

### Drill 14 — View vs CTE vs subquery

> **Q**: When do you choose a View over a CTE?
>
> **A**: When the query is shared across **multiple queries**. CTEs are statement-scoped — they exist only for the duration of one SQL statement. Views are persistent objects in the schema — defined once, referenced from anywhere. If the same "filter active customers" logic appears in 10 queries, create a view; if it's in 1 query, use a CTE.
>
> **Cross-Q**: How does the engine treat a view differently than a CTE?
>
> **A**: For simple views, identically — both are "named subqueries" that get inlined into the calling query. The query referencing `active_customers` is rewritten as if you'd typed the view's SELECT inline. So performance is identical to a CTE with the same definition. Materialized views are different — they store the result and serve queries from the cache. Name the engine: PostgreSQL and Oracle have materialized views refreshed on demand; **SQL Server has no materialized view**. Its equivalent is the *indexed view*, a `SCHEMABINDING` view with a unique clustered index, maintained synchronously by every write to the base tables — never stale, and never free for writers. Calling an indexed view a materialized view in an interview invites the follow-up about refresh scheduling, which for SQL Server does not exist.
>
> **Cross-Q²**: When do you reach for a materialized view?
>
> **A**: When the underlying query is expensive (heavy aggregation, multi-table joins) AND queries are read-heavy AND staleness is tolerable AND you have a refresh strategy. Examples: nightly-refreshed dashboards, monthly financial reports, search-result caches. Trade-off: writes to the base tables don't immediately reflect in the matview; you trade real-time accuracy for query speed. CTEs/regular views give real-time results at every-query cost; matviews give cached results at periodic-refresh cost.

### Drill 15 — Recursive CTE termination + cycle detection

> **Q**: A recursive CTE on a graph runs forever. What are the two failure modes?
>
> **A**: (1) **Unbounded growth**: the recursive predicate produces new rows every iteration but the data is finite — eventually you'd terminate, but if growth is exponential (each node has many children), the iteration count and intermediate row counts explode before reaching a natural fixed point. (2) **Cycles**: A → B → A produces the same nodes endlessly; no natural termination.
>
> **Cross-Q**: How do you detect cycles?
>
> **A**: Maintain a "path" array of visited node IDs in the recursive step: `path := path || e.id`. Add a WHERE filter: `WHERE NOT (e.id = ANY(d.path))` to skip already-visited nodes. Each recursive row carries its own path, so different paths can revisit different nodes — only the current path is checked. Postgres 14+ has built-in `CYCLE id SET is_cycle USING cycle_path` syntax that does this automatically.
>
> **Cross-Q²**: What about graphs with very long paths but no cycles?
>
> **A**: Termination is guaranteed, but the iteration count equals the longest path length. For a 1000-step path, you do 1000 recursive iterations — each one's row set grows linearly. SQL Server's default `MAXRECURSION 100` errors out; use `OPTION (MAXRECURSION 1500)` or `0` for unlimited. Postgres has no default cap but may consume a lot of memory. For very deep graphs, consider iterative algorithms in application code or graph databases (Neo4j) instead — recursive SQL works but isn't the best tool past a few thousand levels.

### Drill 16 — Data-modifying CTEs

> **Q**: Write "archive rows older than 90 days" as a single statement.
>
> **A**: On PostgreSQL, a data-modifying CTE: ```sql
> WITH moved AS (
>     DELETE FROM events WHERE occurred_at < now() - INTERVAL '90 days'
>     RETURNING *
> )
> INSERT INTO events_archive SELECT * FROM moved;
> ```
> One statement, one transaction, no window in which the rows exist in neither table. On SQL Server the equivalent is `DELETE ... OUTPUT deleted.* INTO events_archive`; on MySQL it is two statements inside one transaction, because neither engine allows `DELETE` inside a `WITH`.
>
> **Cross-Q**: In that PostgreSQL statement, if I add a second CTE that counts the remaining rows in `events`, what does it see?
>
> **A**: The rows as they were *before* the delete. The documentation is explicit: "all the statements are executed with the same snapshot, so they cannot 'see' one another's effects on the target tables." A `WITH` clause is not a sequence of steps — the sub-statements are "executed concurrently with each other and with the main query", and the order in which the updates happen "is unpredictable". If you need read-after-write, use two statements in one transaction.
>
> **Cross-Q²**: What happens if two CTEs in the same statement update the same row?
>
> **A**: Undefined-ish, and documented as such: "trying to update the same row twice in a single statement is not supported. Only one of the modifications takes place, but it is not easy (and sometimes not possible) to reliably predict which one." The same applies to deleting a row another CTE has updated. This is why the "one clever statement" version of a state machine is a bug waiting for production data — write the modifications so each row is touched once, or split the statement.

### Drill 17 — Two references, two answers

> **Q**: On SQL Server, a single statement references one CTE twice — once for a total, once for a row list. Can the two disagree?
>
> **A**: Yes. The CTE is not a stored result; each outer reference re-executes the definition. Under the on-premises default (`READ_COMMITTED_SNAPSHOT OFF`) read committed takes shared locks that are released as the scan advances, so committed inserts can land between the two executions and the total will not match the list. It is not a rounding bug, and it does not reproduce on an idle test server.
>
> **Cross-Q**: Does anything make it consistent without changing the query?
>
> **A**: Yes — row versioning. With `READ_COMMITTED_SNAPSHOT ON` the engine "uses row versioning to present each statement with a transactionally consistent snapshot of the data as it existed at the start of the statement", so both references read the same snapshot. That setting is `OFF` by default on SQL Server and `ON` by default on Azure SQL Database, which is why this class of bug often appears only after a move on-premises, or disappears after a move to Azure. A `SNAPSHOT` or `SERIALIZABLE` transaction also fixes it, at a higher cost.
>
> **Cross-Q²**: Same question for PostgreSQL and MySQL.
>
> **A**: Both are consistent here for a different reason. PostgreSQL's Read Committed gives each statement a snapshot taken when the statement begins, and a CTE referenced twice is materialised once anyway. MySQL/InnoDB serves plain `SELECT`s from a consistent non-locking read, and a materialised CTE is computed once and reused for every reference. The failure mode is specific to SQL Server's "re-execute per reference" contract combined with lock-based read committed.

### Drill 18 — Why the recursive member can't aggregate

> **Q**: Why does SQL Server reject `GROUP BY`, `DISTINCT`, `TOP`, outer joins and subqueries inside the recursive member?
>
> **A**: Because recursion is implemented as iteration over a working table. Each pass binds the CTE's self-reference to *the previous pass's output only*, then replaces the working table with the new rows. Operators that need to see the whole set — dedup, grouping, ranking, "top N" — have no whole set to look at, so the engine forbids them rather than returning something meaningless. The other two engines draw the line in the same place but not at the same distance: MySQL bans aggregates, window functions, `GROUP BY`, `ORDER BY` and `DISTINCT`; PostgreSQL only rejects aggregates outright (plus `ORDER BY`/`LIMIT`/`OFFSET`), and will happily parse a bare `GROUP BY`, a `SELECT DISTINCT` or a window function in the recursive term — which does not make the result meaningful, it just means the engine won't stop you. SQL Server's list is the longest of the three, and knowing that it *is* engine-specific is the point of the question.
>
> **Cross-Q**: What if I use a window function anyway, where the engine allows it?
>
> **A**: You get an answer that looks right and isn't. Microsoft's documentation demonstrates this: a `ROW_NUMBER() OVER (PARTITION BY ...)` in a recursive member returns `1` for every row, because "analytic and aggregate functions in the recursive part of the CTE are applied to the set for the current recursion level and not to the set for the CTE" — each iteration hands the function a one-row-per-branch subset. Rank in the outer query, over the finished result.
>
> **Cross-Q²**: How do you compute a per-branch running total then?
>
> **A**: Carry it forward as a column. The recursive member has access to the previous row's values, so `ot.running_total + e.qty` accumulates down a path — that is what the `depth + 1` idiom already does for depth. Anything that needs a *set* rather than a *path* (rank among siblings, count of descendants) belongs in the outer query, typically as a window function over the CTE's output. Path-shaped state goes in the recursion; set-shaped aggregation comes after it.

</details>

## Cheat Sheet

- **Scalar / row / table subquery**: returns one value / one row / a set; the call site dictates which is valid.
- **Correlated**: references outer query columns; conceptually runs per outer row.
- **EXISTS short-circuits**: stops at first match; NULL-safe; usually beats `IN`/`JOIN+DISTINCT` for "at least one".
- **NOT IN with NULLs**: any NULL in the inner result makes the outer return zero rows; use `NOT EXISTS`.
- **CTE**: named query step inside `WITH`; reads top-down like prose.
- **CTE materialization**: Postgres 12+ inlines by default; force with `MATERIALIZED` when expensive and reused.
- **Recursive CTE**: anchor + UNION ALL recursive member; terminates when no new rows are produced.
- **Cycle detection**: graphs need an `ARRAY` of visited nodes or built-in `CYCLE` clause to avoid infinite recursion.
- **CTE vs view**: CTE is statement-scoped; view is reusable across queries; matview is cached and refreshable.
- **Pre-aggregate in CTE**: clean fix for "join multiplication" totals in big reports.
- **Evaluation contract**: SQL Server re-executes per reference; PostgreSQL 12+ folds one reference / materialises two or more; MySQL merges when it can, and materialises once when it can't. Temp table is the only cross-engine guarantee.
- **Plan words**: PostgreSQL `InitPlan` = once, `SubPlan` = per outer row (a `hashed SubPlan` is the exception — built once, probed per row), `Hash Semi/Anti Join` = decorrelated, `CTE Scan` = materialised, `WorkTable Scan` = recursion. SQL Server: `Left Semi Join` / `Left Anti Semi Join` as the logical operation, `Index Spool (Lazy Spool) WITH STACK` inside a recursive CTE.
- **Decorrelation limit**: PostgreSQL never unnests a correlated scalar subquery in the `SELECT` list.
- **`NOT IN` on PostgreSQL**: hashed SubPlan while it fits `work_mem`, per-row SubPlan after that. `NOT EXISTS` has no cliff.
- **Recursion caps**: SQL Server 100 (error 530, `MAXRECURSION 0–32767`); MySQL `cte_max_recursion_depth` 1000; PostgreSQL none.
- **Recursive member sees one level**, not the accumulated result — no aggregates, no ranking, one self-reference.
- **`ORDER BY` in a CTE/derived table/view** does not order the outer result; SQL Server documents this and rejects it without `TOP`/`OFFSET`.
- **Data-modifying CTE** = PostgreSQL only; one snapshot, unpredictable sub-statement order, one modification per row.
- **Reports and writers**: shared locks on SQL Server with RCSI off; no reader/writer blocking on PostgreSQL, MySQL/InnoDB, or Azure SQL Database.
- **Scoping**: subquery columns resolve inside-out. An unqualified name missing from the inner table binds to the outer one and makes the predicate always-true. Alias and qualify.
- **Writing through a subquery**: `UPDATE … FROM` with duplicates picks one row unpredictably (documented on SQL Server and PostgreSQL); correlated scalar errors on duplicates, NULLs on no-match.
- **Queue claim**: PostgreSQL/MySQL 8.0 `FOR UPDATE SKIP LOCKED` *inside* the subquery; SQL Server `WITH (READPAST, UPDLOCK, ROWLOCK)` + `OUTPUT`, plus `READCOMMITTEDLOCK` when RCSI is on.
- **Push-down rule**: a predicate crosses a boundary only if crossing changes nothing. Never past `LIMIT`/`TOP` or a volatile function; past a window function only for `PARTITION BY` columns.
- **`> ALL` ≠ `> MAX`** once the subquery is empty or contains a NULL.

## Walkthrough — Recursive CTE runaway on a cyclic graph

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A "find all downstream dependencies" query on a build-pipeline graph runs forever. On SQL Server it fails fast with error 530 (`The maximum recursion 100 has been exhausted before statement completion`); on PostgreSQL there is no such cap, so it keeps building its working table until temp files fill the disk or `statement_timeout` cancels it. Locally it works; the production graph has cycles introduced by a recent feature.

**Diagnosis**: Senior dumps the edge table to confirm cycles:

```sql
SELECT from_node, to_node FROM edges
WHERE from_node IN (SELECT to_node FROM edges)
  AND to_node IN (SELECT from_node FROM edges)
LIMIT 50;
```

Sees `A -> B`, `B -> C`, `C -> A`. The naive recursive CTE has no cycle guard:

```sql
WITH RECURSIVE deps AS (
    SELECT to_node FROM edges WHERE from_node = $1
    UNION ALL
    SELECT e.to_node
    FROM deps d
    JOIN edges e ON e.from_node = d.to_node
)
SELECT DISTINCT * FROM deps;
```

**Fix**: Track the visited path with an array and exclude already-visited nodes:

```sql
WITH RECURSIVE deps AS (
    SELECT to_node, ARRAY[from_node, to_node] AS path
    FROM edges
    WHERE from_node = $1
    UNION ALL
    SELECT e.to_node, d.path || e.to_node
    FROM deps d
    JOIN edges e ON e.from_node = d.to_node
    WHERE NOT (e.to_node = ANY(d.path))   -- cycle guard
)
SELECT DISTINCT to_node FROM deps;
```

In Postgres 14+ you can also use the built-in `CYCLE` clause: `... CYCLE to_node SET is_cycle USING cycle_path`. In SQL Server, set `OPTION (MAXRECURSION 1000)` *and* maintain a path column.

**Why it works**: Without a guard, a cycle keeps producing new tuples every iteration. The path array gives each row a memory of where it came from; the predicate prevents re-entry into a previously visited node, ensuring termination.

**What the senior does next**: the query fix is half the job. The cycle is a data defect — the schema permits `A → B → A` — so the follow-ups are a constraint or a nightly check that reports cycles as a data-quality ticket, and a `statement_timeout` (PostgreSQL) or explicit `MAXRECURSION` bound (SQL Server) on the reporting path so the next unguarded query fails in seconds instead of taking the instance with it.

</details>

## Self-test

<details><summary>1. <code>WHERE x NOT IN (SELECT y FROM t)</code> returns zero rows even though there are clearly non-matching values. Why?</summary>

The inner SELECT contains at least one NULL. `x NOT IN (a, b, NULL)` is logically `x != a AND x != b AND x != NULL`; the last comparison yields NULL, which propagates and disqualifies every outer row. Filter NULLs from the inner query or use `NOT EXISTS`.
</details>

<details><summary>2. Trade-off: CTE vs subquery vs temp table for a query reused 5 times.</summary>

CTE: most readable, but inlined per reference in some engines (recomputed). Subquery: copy-paste of the same logic - terrible. Temp table: computed once, optimiser has full statistics, costs disk/memory. For a heavy CTE referenced often, temp table or `MATERIALIZED` CTE is right; for a one-off, plain CTE wins on clarity.
</details>

<details><summary>3. <code>SELECT (SELECT MAX(total) FROM orders WHERE customer_id = c.id) FROM customers c</code> — will the optimiser turn that into a join and an aggregate?</summary>

Depends on the engine, and this is the trap. SQL Server can: its optimiser is built around the `Apply` operator and decorrelates correlated scalar aggregates into a join plus group-by. **PostgreSQL does not unnest correlated scalar subqueries in the target list** — it plans a `SubPlan` and executes it once per outer row, whatever the statistics say. Check `EXPLAIN`: `SubPlan` with `loops` equal to the outer row count means per-row execution, and the fix is a manual rewrite (pre-aggregate and join, or `LATERAL`). Correlated does not automatically mean slow, but "the optimiser handles it" is only safe for `EXISTS`/`IN` in `WHERE`.
</details>

<details><summary>4. <code>WITH RECURSIVE</code> is producing 100 million rows on a 1000-row table. What's likely?</summary>

Either an unbounded recursion (no terminating condition), a cycle without guard, or a `UNION ALL` that should be `UNION` (which would dedupe and limit growth). Look at the recursive predicate: it should join only against rows that strictly extend the current state.
</details>

<details><summary>5. When does a materialised view beat a CTE for the same query?</summary>

When the underlying query is expensive, the result is read by many consumers across many transactions, and stale data is acceptable until refresh. Matview pays the compute once; CTE pays it every query. The downside is staleness and the operational cost of refresh scheduling — and on PostgreSQL a plain `REFRESH MATERIALIZED VIEW` blocks readers of the matview, so a frequent refresh needs `CONCURRENTLY`, which in turn needs a unique index covering all rows and a matview that is already populated.
</details>

<details><summary>6. Is a CTE computed once? Answer for SQL Server, PostgreSQL and MySQL.</summary>

SQL Server: no — the documentation states results "aren't materialized" and that each outer reference "requires the defined query to be re-executed". PostgreSQL 12+: folded into the parent if referenced exactly once and side-effect-free, materialised once if referenced more than once; before 12, always materialised. MySQL 8.0: when materialised, "it is materialized once for the query, even if the query references it several times". Only a temp table gives the guarantee everywhere.
</details>

<details><summary>7. On SQL Server, one statement references a CTE twice and the total disagrees with the row list. Explain, and give two fixes.</summary>

Each reference re-executes the CTE, and under the default `READ_COMMITTED_SNAPSHOT OFF` nothing holds the rows still between the two executions — concurrent commits land in between. Fixes: materialise into a `#temp` table (works anywhere), or turn on `READ_COMMITTED_SNAPSHOT` so each statement reads one consistent snapshot (already the default on Azure SQL Database). A `SNAPSHOT` transaction also works, at higher cost. The same statement is not affected on PostgreSQL or MySQL, because both compute the CTE once and both give the statement a consistent read.
</details>

<details><summary>8. Why is <code>NOT EXISTS</code> preferred over <code>NOT IN</code> for reasons beyond NULL semantics?</summary>

Plan stability. PostgreSQL cannot convert `NOT IN (subquery)` into an anti-join — the NULL semantics forbid it — so it builds a hashed SubPlan, which is only available while the subquery result is estimated to fit `work_mem` and the subquery is uncorrelated; past that, it degrades to re-evaluating the subquery per outer row. `NOT EXISTS` becomes a `Hash Anti Join` and degrades gradually. On SQL Server the two can produce the same anti-semi-join, but only when the inner column is declared `NOT NULL`; a nullable column forces extra work to implement three-valued logic.
</details>

<details><summary>9. What does a <code>WITH</code> clause containing a <code>DELETE ... RETURNING</code> guarantee about ordering, and on which engine?</summary>

PostgreSQL only — SQL Server and MySQL have no data-modifying CTEs. It guarantees atomicity, and specifically does *not* guarantee ordering: the sub-statements "are executed concurrently with each other and with the main query", they all see one snapshot so they cannot observe each other's effects, and a row modified twice in the same statement gets only one of the modifications, unpredictably. Use it for the archive-and-delete shape; do not use it to sequence steps.
</details>

<details><summary>10. A recursive CTE's <code>ROW_NUMBER()</code> returns 1 on every row. Why?</summary>

The recursive member is evaluated against the working table — the previous iteration's output — not the accumulated result. Each iteration hands the window function only that level's rows, so the numbering restarts. SQL Server's documentation shows this exact example. Move the ranking into the outer query, over the finished CTE.
</details>

<details><summary>11. Which of these are safe in the recursive member of a recursive CTE: <code>INNER JOIN</code>, <code>LEFT JOIN</code>, <code>GROUP BY</code>, a second reference to the CTE, <code>TOP</code>?</summary>

Only `INNER JOIN`. SQL Server explicitly disallows `SELECT DISTINCT`, `GROUP BY`, `HAVING`, `PIVOT`, scalar aggregation, `TOP`, `LEFT`/`RIGHT`/`OUTER JOIN`, and subqueries in the recursive member, and requires the `FROM` clause to reference the CTE exactly once. MySQL bans aggregates, window functions, `GROUP BY`, `ORDER BY` and `DISTINCT`, and also requires exactly one reference, in `FROM` only. PostgreSQL requires a single self-reference that is not inside a subquery and not on the nullable side of an outer join.
</details>

<details><summary>12. What breaks first if a recursive CTE hits a cycle — on SQL Server, and on PostgreSQL?</summary>

SQL Server: nothing breaks, the statement is terminated at 100 recursion levels with error 530, and you get a clear message. PostgreSQL: nothing stops it — no cap, no error — so the working table grows into temp files until the disk, `temp_file_limit`, or `statement_timeout` intervenes. The SQL Server default is a safety net; `OPTION (MAXRECURSION 0)` removes it and makes SQL Server behave like the PostgreSQL case.
</details>

<details><summary>13. <code>DELETE FROM orders WHERE order_id IN (SELECT order_id FROM staging)</code> deleted every order, and <code>staging</code> was not empty. What happened, and what would have prevented it?</summary>

`staging` has no `order_id` column. Name resolution in a subquery runs inside-out — MySQL states the rule as "MySQL evaluates from inside to outside", and SQL Server and PostgreSQL resolve the same way — so the inner `order_id` bound outward to `orders.order_id`. The predicate became `orders.order_id IN (orders.order_id, …)`, true for every row with a non-NULL id whenever `staging` has at least one row. It is valid SQL and no engine warns. Note the emptiness flip: with `staging` empty the same statement deletes nothing, which is why it passes a dry run. Prevention: alias the inner table and qualify every column inside the subquery (`SELECT s.order_id FROM staging s`), so a missing column is a compile error instead of a correlation. The same hole exists in `EXISTS (SELECT 1 FROM staging WHERE order_id = orders.order_id)` — the left-hand `order_id` also binds outward.
</details>

<details><summary>14. You need to claim 20 jobs for a worker without two workers claiming the same job. Give the statement for PostgreSQL and for SQL Server, and name one failure mode of each.</summary>

PostgreSQL: a CTE containing `SELECT id FROM jobs WHERE state = 'ready' ORDER BY run_at LIMIT 20 FOR UPDATE SKIP LOCKED`, then `UPDATE jobs … FROM claimed … RETURNING`. The locking clause must be inside the `WITH` query — the docs state that locking clauses "do not apply to `WITH` queries referenced by the primary query". Failure mode: drop `SKIP LOCKED` and the second worker blocks, then re-evaluates its `WHERE` against the updated rows ("the search condition of the command (the `WHERE` clause) is re-evaluated to see if the updated version of the row still matches"), finds they no longer match, and returns a short batch with no error.

SQL Server: `UPDATE TOP (20) j SET … OUTPUT inserted.* FROM jobs AS j WITH (READPAST, UPDLOCK, ROWLOCK) WHERE …`. `READPAST` skips row-level locks — but "page-level locks aren't skipped", so lock escalation reintroduces blocking. Failure mode: `READPAST` "can't be specified when the `READ_COMMITTED_SNAPSHOT` database option is set to `ON`" and the session is read committed; add `READCOMMITTEDLOCK`. RCSI is on by default on Azure SQL Database and off by default on SQL Server, so this appears on migration.
</details>

<details><summary>15. A CTE computes <code>ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC)</code>. The outer query filters on <code>rn = 1</code> and on <code>customer_id</code>. Which filter can be evaluated inside the CTE, and why?</summary>

`customer_id`. A predicate may be pushed below an operator only if pushing it cannot change that operator's output for any surviving row. A filter on a `PARTITION BY` column either keeps or discards a whole partition, and window functions act only within a partition, so no surviving row's `rn` changes — PostgreSQL allows the pushdown when "the qual references only partitioning columns" and "contains no volatile functions". A filter on `rn` cannot be pushed at all: `rn` is computed from the rows present, so filtering first would change it. In a SQL Server plan the `Filter` on `rn` sits above `Segment` and `Sequence Project`, after everything below it has been computed. Nothing is ever pushed below a `LIMIT`/`TOP`, on any engine.
</details>

<details><summary>16. <code>UPDATE p SET p.price = f.price FROM products p JOIN price_feed f ON f.sku = p.sku</code> — the feed has two rows for one SKU. What happens?</summary>

One of them is applied, and which one is not predictable. SQL Server documents the result as undefined: "The results of an `UPDATE` statement are undefined if the statement includes a `FROM` clause that isn't specified in such a way that only one value is available for each column occurrence that is updated." PostgreSQL says the same of `UPDATE … FROM`: "only one of the join rows will be used to update the target row, but which one will be used is not readily predictable." No error, and it can differ between runs. The correlated-scalar spelling (`SET price = (SELECT f.price FROM price_feed f WHERE f.sku = p.sku)`) fails loudly on the duplicate instead — but silently writes NULL where there is no match. Make the choice explicit: rank in a CTE with a deterministic `ORDER BY` and join on `rn = 1`.
</details>

## Cross-references

- [Joins & Set Operations](./02-joins-and-set-operations.md) — joins are alternatives to subqueries for many problems.
- [Window Functions](./05-window-functions.md) — often replaces correlated subqueries elegantly.
- [Aggregation & Grouping](./03-aggregation-and-grouping.md) — pre-aggregation CTEs feed downstream queries.
- [Schema Design & Normalization](./08-schema-design-and-normalization.md) — hierarchical data design feeds recursive CTEs.
- [Indexes & Query Optimization](./06-indexes-and-query-optimization.md) — execution plans for subqueries vs joins.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *SQL Cookbook* by Anthony Molinaro — covers correlated/non-correlated patterns.
- PostgreSQL — [WITH Queries (CTEs)](https://www.postgresql.org/docs/current/queries-with.html) — folding vs materialisation rules, the working-table algorithm, `SEARCH`/`CYCLE`, and the data-modifying-CTE snapshot rules quoted above.
- PostgreSQL — [Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html) and [REFRESH MATERIALIZED VIEW](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html).
- Microsoft Learn — [WITH common_table_expression (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/with-common-table-expression-transact-sql) — the "aren't materialized / re-executed per reference" statement, recursive-member restrictions, `MAXRECURSION`, and the `ROW_NUMBER`-in-recursion example.
- Microsoft Learn — [SET TRANSACTION ISOLATION LEVEL](https://learn.microsoft.com/en-us/sql/t-sql/statements/set-transaction-isolation-level-transact-sql) — `READ_COMMITTED_SNAPSHOT` OFF on SQL Server, ON by default on Azure SQL Database.
- Microsoft Learn — [ORDER BY clause](https://learn.microsoft.com/en-us/sql/t-sql/queries/select-order-by-clause-transact-sql) — why `ORDER BY` in a CTE, view or derived table guarantees nothing.
- Microsoft Learn — [Create indexed views](https://learn.microsoft.com/en-us/sql/relational-databases/views/create-indexed-views) — `SCHEMABINDING`, the banned constructs (including CTEs and subqueries), `NOEXPAND`, and the DML cost.
- MySQL — [WITH (Common Table Expressions)](https://dev.mysql.com/doc/refman/8.4/en/with.html) and [Optimizing Derived Tables, View References, and CTEs](https://dev.mysql.com/doc/refman/8.4/en/derived-table-optimization.html) — `cte_max_recursion_depth`, and "materialized once for the query, even if the query references it several times".
- Paul White — [Row Goals, Part 2: Semi Joins](https://sqlperformance.com/2018/02/sql-plan/row-goals-part-2-semi-joins) and [Part 4: The Anti Join Anti Pattern](https://sqlperformance.com/2018/03/sql-performance/row-goals-part-4-anti-join-anti-pattern), SQLPerformance, 2018.
- Galindo-Legaria and Joshi, *Orthogonal Optimization of Subqueries and Aggregation*, SIGMOD 2001 — the `Apply`-based decorrelation SQL Server's optimizer is built on.
- Microsoft Learn — [What's New in EF Core 10](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-10.0/whatsnew) — how a parameterized `Contains` collection is translated, and how that changed across EF 8, 9 and 10.
- *Joe Celko's Trees and Hierarchies in SQL for Smarties* — recursive CTEs and tree representations.
- *T-SQL Querying* by Itzik Ben-Gan — correlated subquery internals and optimization.

Used for the specifics added on scoping, writing through subqueries, queue claims and predicate push-down:

- MySQL — [Correlated Subqueries](https://dev.mysql.com/doc/refman/8.4/en/correlated-subqueries.html): the scoping rule, "MySQL evaluates from inside to outside", and the worked example of a column resolving to the nearest enclosing block.
- Microsoft Learn — [UPDATE (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/update-transact-sql): "The results of an `UPDATE` statement are undefined if the statement includes a `FROM` clause that isn't specified in such a way that only one value is available for each column occurrence that is updated."
- PostgreSQL — [UPDATE](https://www.postgresql.org/docs/current/sql-update.html): "only one of the join rows will be used to update the target row, but which one will be used is not readily predictable."
- MySQL — [UPDATE](https://dev.mysql.com/doc/refman/8.4/en/update.html): "Each matching row is updated once, even if it matches the conditions multiple times"; `ORDER BY` and `LIMIT` are not available in the multiple-table form.
- PostgreSQL — [SELECT, The Locking Clause](https://www.postgresql.org/docs/current/sql-select.html): `SKIP LOCKED` and the queue-like-table use case, "these clauses do not apply to `WITH` queries referenced by the primary query", and the interaction between `LIMIT`/`OFFSET` and locking.
- Microsoft Learn — [Table hints (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/hints-transact-sql-table): `READPAST` (row locks skipped, page locks not; the work-queue use case; the `READ_COMMITTED_SNAPSHOT` restriction and the `READCOMMITTEDLOCK` remedy), `UPDLOCK`, `ROWLOCK`.
- MySQL — [Locking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html): `NOWAIT` and `SKIP LOCKED`, the inconsistent-view warning, and "statements that use `NOWAIT` or `SKIP LOCKED` are unsafe for statement based replication".
- PostgreSQL commit — [*Allow pushdown of WHERE quals into subqueries with window functions*](https://www.postgresql.org/message-id/E1X0lnx-0002b7-Ao%40gemulon.postgresql.org) (David Rowley's patch, committed by Tom Lane, 2014-06-28): pushdown allowed "if (a) the qual references only partitioning columns, and (b) the qual contains no volatile functions".
- PostgreSQL — [14 release notes](https://www.postgresql.org/docs/release/14.0/): "Add SQL-standard `SEARCH` and `CYCLE` clauses for common table expressions (Peter Eisentraut)".

<!-- nav-footer-start -->

---

[← Previous: Aggregation & Grouping](03-aggregation-and-grouping.md) · [↑ Back to top](#subqueries--ctes) · [Next: Window Functions →](05-window-functions.md)

<!-- nav-footer-end -->

</details>
