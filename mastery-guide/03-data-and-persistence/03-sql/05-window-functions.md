# Window Functions

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › [SQL Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-08 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [The `OVER (...)` clause](#the-over--clause)
  - [Ranking functions: ROW_NUMBER, RANK, DENSE_RANK, NTILE](#ranking-functions-row_number-rank-dense_rank-ntile)
  - [Value functions: LAG, LEAD, FIRST_VALUE, LAST_VALUE](#value-functions-lag-lead-first_value-last_value)
  - [Aggregate windows: SUM/AVG/COUNT OVER](#aggregate-windows-sumavgcount-over)
  - [PARTITION BY — group within window](#partition-by--group-within-window)
  - [Window frame: ROWS vs RANGE](#window-frame-rows-vs-range)
  - [Common patterns](#common-patterns)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--running-total-killing-a-correlated-subquery)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

Window functions are the senior-tier SQL feature. They compute aggregates *without collapsing rows* — every row stays in the result, and each gets a value computed over a "window" of related rows. Running totals, moving averages, percent rank, "previous and next value" comparisons, top-N-per-group — all become one-liners.

Before window functions (introduced in SQL:2003 but only widely supported by ~2012), these problems required correlated subqueries, self-joins, or application-layer post-processing. Window functions reduced them to clear, fast SQL. Knowing them is the line between "solid SQL" and "SQL fluent."

For interviews, expect at least one window-function problem at the senior level. The patterns below cover the bar.

When NOT to use: simple aggregations that *do* collapse rows (use `GROUP BY`). Top-1 retrievals where `ORDER BY ... LIMIT 1` is enough. Don't reach for window functions when a simpler form works.

The second-order thing interviewers probe is not "can you write `ROW_NUMBER`" but "do you know what the window can see, what it costs, and where the engines disagree". Those three questions run through the rest of this page.

> 🌍 **In the real world**: a revenue-share tile computed each product's contribution as `100.0 * sales / SUM(sales) OVER ()`, and it was right for a year. Then a category filter was added to the screen, and every product's share went up — support logged it as "the percentages don't add up any more", which was exactly backwards: they still added to 100%, just to 100% of the filtered set. The window function runs *after* `WHERE`, so its population is whatever survived the filter, and the denominator had quietly become "sales in the selected category" instead of "sales overall". The fix was to compute the grand total in its own CTE over the unfiltered table and cross-join it in, so the denominator stopped depending on the screen state. The durable lesson: `OVER ()` does not mean "the whole table", it means "the whole row set this query produced by the time the window runs".

## Core concepts

### The `OVER (...)` clause

Every window function is a normal aggregate or value function followed by `OVER (...)`. The `OVER` clause defines the *window* — the set of rows the function operates on for each row in the result.

```sql
SELECT
    id,
    name,
    salary,
    AVG(salary) OVER ()  AS company_avg
FROM employees;
```

`OVER ()` with no clauses means "the whole result set is the window." Every row gets the same `company_avg`.

`OVER (...)` accepts three optional clauses:
- **`PARTITION BY`** — group the rows into windows by the partition key.
- **`ORDER BY`** — order rows within the partition.
- **frame clause** (`ROWS BETWEEN ... AND ...`) — restrict the window to rows in a range.

```sql
SELECT
    id, department, salary,
    AVG(salary) OVER (PARTITION BY department)             AS dept_avg,
    RANK()      OVER (PARTITION BY department ORDER BY salary DESC) AS rank_in_dept
FROM employees;
```

Now `dept_avg` is averaged per department, and `rank_in_dept` ranks each employee within their department.

**Two things the `OVER` clause does not do.**

*It does not order the result.* The `ORDER BY` inside `OVER` sequences rows for the *computation* only. Microsoft's `OVER` clause documentation spells out the split in its `ROW_NUMBER` example: "The `ORDER BY` clause specified in the `OVER` clause orders the rows in each partition by the column `SalesYTD`. The `ORDER BY` clause in the `SELECT` statement determines the order in which the entire query result set is returned." Rows often come back in window order because the engine had to sort them anyway — that is an artefact of the plan, not a guarantee, and it changes the day the plan goes parallel or an index removes the sort. If the caller needs an order, write a query-level `ORDER BY`.

*It does not see rows the query already discarded.* The window's input is the row set as it exists after `FROM`, `WHERE`, `GROUP BY` and `HAVING`. `SUM(x) OVER ()` is the total of the surviving rows, not of the table. Same reasoning in reverse: a window function cannot be referenced in `WHERE` or `HAVING`, because it has not been computed yet. On PostgreSQL the rule is stated flatly — "Window function calls are permitted only in the `SELECT` list and the `ORDER BY` clause of the query."

Reusing one window definition across several functions is standard SQL, spelled `WINDOW`:

```sql
SELECT id, department, salary,
       AVG(salary) OVER w AS dept_avg,
       RANK()      OVER w AS rank_in_dept
FROM employees
WINDOW w AS (PARTITION BY department ORDER BY salary DESC);
```

PostgreSQL and MySQL 8 have supported this for years. SQL Server got it in **2022 (16.x)**, and the documentation is explicit that it "requires database compatibility level `160` or higher" — on a 2022 instance still running at level 150 the query is rejected, which is a confusing first encounter.

### Ranking functions: ROW_NUMBER, RANK, DENSE_RANK, NTILE

Assign a numeric rank to each row, ordered by the `ORDER BY` clause inside `OVER`.

```sql
SELECT
    id, name, salary,
    ROW_NUMBER() OVER (ORDER BY salary DESC) AS row_num,
    RANK()       OVER (ORDER BY salary DESC) AS rank,
    DENSE_RANK() OVER (ORDER BY salary DESC) AS dense_rank
FROM employees;
```

Differences shown when there are ties (same salary):

```
salary | ROW_NUMBER | RANK | DENSE_RANK
-------+------------+------+-----------
 100k  |     1      |  1   |    1
 100k  |     2      |  1   |    1        ← tied; RANK both 1
  90k  |     3      |  3   |    2        ← RANK skips to 3 (gap); DENSE_RANK is 2 (no gap)
  85k  |     4      |  4   |    3
```

- **`ROW_NUMBER`**: always unique 1, 2, 3, ... within the partition. When the `ORDER BY` has ties, *which* tied row gets the lower number is undefined — not "insertion order", not "clustered index order", just undefined. It can differ between two runs of the same statement on the same data if the plan changes (a new index, a parallel plan, a different row on a replica).
- **`RANK`**: ties get same rank; gap to next ("Olympic" ranking — bronze can be 4 if two silvers).
- **`DENSE_RANK`**: ties get same rank; no gap (sequential).

That "undefined" is not pedantry. `ROW_NUMBER` is the standard de-duplication tool — rank the duplicates, delete everything with `rn > 1` — and a `PARTITION BY` with an ambiguous `ORDER BY` makes the statement pick an arbitrary survivor. SQL Server says so outright: "`ROW_NUMBER()` is nondeterministic", and "There is no guarantee that the rows returned by a query using `ROW_NUMBER()` will be ordered exactly the same with each execution" — the article's conditions for that guarantee are that the partitioning values, the `ORDER BY` values, and their combinations are all unique. PostgreSQL does not use the word, but the same follows from what it *does* guarantee — the ranking functions "give the same answer for all rows of a peer group", which says nothing about which peer is numbered first. Add enough `ORDER BY` columns to make the ordering total (usually the primary key as the last tie-breaker) whenever the row number decides which row *lives*.

> 🌍 **In the real world**: a nightly job de-duplicated an imported `customers` staging table with `ROW_NUMBER() OVER (PARTITION BY email ORDER BY created_at DESC)` and deleted `rn > 1`. Bulk imports wrote whole batches with the same `created_at` to the millisecond, so within a batch the ordering was a tie and the engine picked a survivor at whim. Nobody noticed while the job ran on one server. When a second worker was added and the same batch got re-processed after a retry, the two runs kept different rows — different `customer_id`, so the downstream orders that referenced the deleted id were orphaned. The fix was a single extra column, `ORDER BY created_at DESC, id DESC`, which made the ordering total and the choice reproducible. The review rule that came out of it: any `ROW_NUMBER` whose value drives a `DELETE` or a `MERGE` must have a tie-breaker that is unique by construction.

`NTILE(n)` divides rows into `n` roughly-equal buckets:

```sql
SELECT id, name, salary,
       NTILE(4) OVER (ORDER BY salary DESC) AS quartile
FROM employees;
-- quartile = 1 for top 25% by salary, 2 for next 25%, etc.
```

Used for: percentiles ("top decile customers"), cohort analysis ("which quartile by spend").

`NTILE` divides by *row count*, not by value, and that is the whole of its danger — two customers who spent the same amount can land in different buckets, and a bucket is not a range of values but a range of positions.

> 🌍 **In the real world**: a loyalty programme granted its top tier to `NTILE(10) = 10` by annual spend. The tier was therefore always exactly 10% of the customer base by construction — so in a quiet quarter, customers who had spent very little got the top tier, and in a strong quarter, customers who had spent well were pushed out of it. Support fielded both complaints and could not explain either, because the query was "obviously" correct. Worse, the boundary between deciles 9 and 10 frequently split customers with identical spend into different tiers, since `NTILE` breaks ties by position. The programme's actual intent was a threshold ("spend over £X"), and once that was written as a plain `WHERE`, the tier stopped moving under customers' feet. `NTILE` answers "where does this row sit in the ordering"; it never answers "is this row above a value", and business rules are almost always the second question.

### Value functions: LAG, LEAD, FIRST_VALUE, LAST_VALUE

Reference values from other rows in the window without joining the table to itself.

**`LAG(col, offset, default)`** — value from a previous row.

```sql
SELECT
    id, created_at, total,
    LAG(total) OVER (PARTITION BY customer_id ORDER BY created_at) AS prev_order_total,
    total - LAG(total) OVER (PARTITION BY customer_id ORDER BY created_at) AS delta
FROM orders;
-- For each order, see the previous order's total and compute the delta.
```

`LAG(total, 2)` for two rows back; default offset is 1.

**`LEAD(col, offset, default)`** — value from a following row. Same shape, opposite direction.

```sql
LEAD(total) OVER (PARTITION BY customer_id ORDER BY created_at)
-- The customer's NEXT order total; NULL on the most recent.
```

**`FIRST_VALUE(col)` / `LAST_VALUE(col)`** — value at the start / end of the window.

```sql
SELECT
    id, customer_id, created_at, total,
    FIRST_VALUE(total) OVER (PARTITION BY customer_id ORDER BY created_at) AS first_order_total
FROM orders;
-- Every row of a customer's orders shows the customer's first order total.
```

`LAST_VALUE` is trickier — by default the frame ends at the *current row*, so `LAST_VALUE` returns the current row's value. To get the actual last value of the partition:

```sql
LAST_VALUE(total) OVER (
    PARTITION BY customer_id
    ORDER BY created_at
    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
)
```

The frame clause matters; covered below.

**`NTH_VALUE(col, n)`** — the n-th row of the frame. Same frame trap as `LAST_VALUE`: with the default frame, `NTH_VALUE(x, 3)` is `NULL` until the frame has three rows in it. The standard's `FROM LAST` variant is nowhere to be had — MySQL "permits only `FROM FIRST`" and parses `FROM LAST` into an error, PostgreSQL likewise implements only the default `FROM FIRST`, and SQL Server has no `NTH_VALUE` at all. Both manuals give the same workaround: reverse the `ORDER BY`.

**Null treatment is the least portable corner of this whole topic.** The standard defines `IGNORE NULLS` / `RESPECT NULLS` for `LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE` and `NTH_VALUE`. Where you actually get it:

| Engine | `IGNORE NULLS` |
|---|---|
| SQL Server | 2022 (16.x) and later, on `LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE`. Also Azure SQL Database / MI. Patch before you trust it: CU4 for SQL Server 2022 (KB5026717) fixed incorrect results from `LAG`/`LEAD` with `IGNORE NULLS` |
| PostgreSQL | Not implemented as of 18. The manual says so explicitly: the option "is not implemented in PostgreSQL: the behavior is always the same as the standard's default, namely `RESPECT NULLS`" |
| MySQL 8 | Only `RESPECT NULLS`. The manual notes `IGNORE NULLS` "is parsed, but produces an error" — same treatment it gives `FROM LAST` on `NTH_VALUE` |
| Oracle | Supported (this is where most `IGNORE NULLS` sample code on the internet comes from) |

"Carry the last non-null value forward" is the query everyone eventually writes, and the portable shape does not use `IGNORE NULLS` at all. Number the non-null values into a group key, then take the group's first value:

```sql
-- Works on PostgreSQL, MySQL 8, SQL Server 2012+: last known price at each timestamp
WITH marked AS (
    SELECT ts, price,
           -- COUNT(col) skips NULLs, so this only increments on a real tick.
           -- Explicit ROWS frame: the default RANGE would give same-ts rows
           -- the same count, and on SQL Server it also costs a tempdb spool.
           COUNT(price) OVER (ORDER BY ts ROWS UNBOUNDED PRECEDING) AS grp
    FROM price_ticks
)
SELECT ts, price,
       FIRST_VALUE(price) OVER (PARTITION BY grp ORDER BY ts) AS price_filled
FROM marked;
```

`grp` stays constant across a run of nulls and increments on each real value, so every null row lands in the same group as the last real value before it, and `FIRST_VALUE` within that group is that value. Rows before the first real tick get `grp = 0` and stay null, which is the correct answer — there is nothing to carry forward yet.

Two more restrictions worth knowing before an interviewer asks: on SQL Server, `LAG` and `LEAD` accept `OVER ( [partition_by_clause] order_by_clause )` and **no frame clause** — writing `ROWS BETWEEN ...` inside a `LAG` is a syntax error, and `ORDER BY` is mandatory. And the offset must be non-negative: "previous row" is `LAG`, never `LEAD(x, -1)`.

> 🌍 **In the real world**: a pricing service materialised "current price per SKU" into a cache table with `LAST_VALUE(price) OVER (PARTITION BY sku ORDER BY effective_from)` and no frame clause. Because the default frame ends at the current row, `LAST_VALUE` returned each row's *own* price, so the cache was correct for every SKU with exactly one price row and wrong for every SKU that had ever been repriced — and since the loader wrote one cache row per SKU by taking whichever row came back first, "wrong" meant "the oldest price". The checkout total came from the base table, so customers saw one price on the listing page and another at checkout, and only for products that had been discounted, which is the subset the marketing team was actively looking at. Adding `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` fixed it in one line. The team then replaced the whole query with `ROW_NUMBER() OVER (PARTITION BY sku ORDER BY effective_from DESC)` filtered to `= 1`, because a pattern with no default-frame trap is worth more than a clever one-liner.

### Aggregate windows: SUM/AVG/COUNT OVER

Standard aggregates work as window functions when followed by `OVER`.

```sql
SELECT
    id, customer_id, created_at, total,
    SUM(total) OVER (PARTITION BY customer_id ORDER BY created_at) AS running_total,
    AVG(total) OVER (PARTITION BY customer_id) AS avg_for_customer,
    COUNT(*)   OVER (PARTITION BY customer_id) AS orders_for_customer
FROM orders;
```

Three different windows:
- `running_total` — sum from start of partition through current row (running sum).
- `avg_for_customer` — average across all customer's orders (same value on every row of that customer).
- `orders_for_customer` — count across all customer's orders.

**Without `ORDER BY`** in the window: the function applies to the entire partition (or whole result if no PARTITION). Result is the same on every row of the partition.

**With `ORDER BY`** (and default frame): the window goes from the first row of the partition through the current row — naturally produces "running" / cumulative aggregates.

**`DISTINCT` is not available inside a window aggregate.** `COUNT(DISTINCT customer_id) OVER (PARTITION BY region)` looks obvious and is rejected almost everywhere. SQL Server's `OVER` documentation lists it under Limitations: "You can't use the `OVER` clause with the `DISTINCT` aggregations." PostgreSQL raises `ERROR: DISTINCT is not implemented for window functions`. MySQL rejects it too. Oracle is the notable engine that allows it, and only in the narrow form: with `DISTINCT` you may specify the partitioning clause and nothing else — no `ORDER BY`, no frame.

The portable substitute for "distinct count per partition, on every row" is a pair of dense ranks:

```sql
SELECT region, customer_id,
       DENSE_RANK() OVER (PARTITION BY region ORDER BY customer_id)
     + DENSE_RANK() OVER (PARTITION BY region ORDER BY customer_id DESC)
     - 1 AS distinct_customers_in_region
FROM sales;
```

Each distinct value gets rank *k* counting up and rank *(d − k + 1)* counting down, so the two ranks sum to *d + 1* for every row. Caveat: nulls receive a rank of their own, so filter or `COALESCE` them first if a null should not count as a value. The alternative — aggregate in a CTE with a real `GROUP BY` and join back — is longer but reads better and gives the optimizer a normal aggregate to plan.

> 🌍 **In the real world**: an order-detail report showed each line item next to "total for this order", written as `SUM(oi.line_total) OVER (PARTITION BY o.id)` over a query that joined `orders` to `order_items` *and* to `order_shipments`. Orders with two shipments had every line item duplicated by the join, so the window summed each line twice and the order total came out double — but only for split shipments, which was about one order in thirty and none of them in the test fixtures. Finance caught it in a monthly reconciliation, six weeks in. The mechanical lesson is that a window function is defined over the rows the `FROM` clause produced, and a fan-out join changes those rows before the window ever sees them; the practical rule the team adopted was to aggregate each one-to-many relationship in its own CTE and join the *aggregates*, never to window over a query that joins two child tables at once.

### PARTITION BY — group within window

`PARTITION BY` divides the result into independent groups, like `GROUP BY` but without collapsing rows.

```sql
SELECT
    id, department, salary,
    AVG(salary) OVER (PARTITION BY department) AS dept_avg,
    salary - AVG(salary) OVER (PARTITION BY department) AS diff_from_dept_avg
FROM employees;
```

Each row keeps its data; the window function aggregates per partition.

`PARTITION BY` is the bridge between row-level info (each employee's salary) and group-level info (their department's average). One result row per input row, enriched with group context.

Multiple partition keys work too:
```sql
PARTITION BY department, year
```

**Median per group is where `PARTITION BY` and the engines part company.** `PERCENTILE_CONT` / `PERCENTILE_DISC` exist in two mutually exclusive shapes and no engine offers both:

```sql
-- SQL Server: ONLY a window function. OVER is mandatory, ORDER BY and a frame
-- are forbidden inside it, and you get one row per input row — hence DISTINCT.
SELECT DISTINCT department,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary)
           OVER (PARTITION BY department) AS median_salary
FROM employees;

-- PostgreSQL: ONLY an ordered-set aggregate. Adding OVER raises
-- "ERROR: OVER is not supported for ordered-set aggregate percentile_cont".
SELECT department,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY salary) AS median_salary
FROM employees
GROUP BY department;
```

MySQL 8 has neither — its window-function list stops at `CUME_DIST` and `PERCENT_RANK`, so median there is a hand-rolled `ROW_NUMBER`/`COUNT` construction. Porting a "median by group" query between SQL Server and PostgreSQL is therefore a rewrite, not a search-and-replace, and the SQL Server form is the one that surprises people: it computes the same value for every row of the partition and the `DISTINCT` is doing real work.

> 🌍 **In the real world**: a "median order value per region" tile was ported from a PostgreSQL prototype to the SQL Server production database. The developer got `PERCENTILE_CONT` compiling by wrapping it in `OVER (PARTITION BY region)` and dropping the `GROUP BY`, which is the syntactically correct T-SQL — and the endpoint then returned one row per order rather than one per region, tens of millions of rows, all of them duplicates of six distinct values. The API gateway killed the request on response size, so the symptom was a timeout on a tile that had worked in staging against a seeded database of a few thousand orders. `SELECT DISTINCT` fixed the output; the better fix was to compute the six medians in a CTE and join, because it lets the plan aggregate rather than expand.

### Window frame: ROWS vs RANGE

The frame clause restricts which rows in the partition contribute to the window function. Default depends on whether `ORDER BY` is in the OVER clause.

**With `ORDER BY`, default frame is:**
```
RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
```
"From start of partition through current row" — produces running sums.

**Without `ORDER BY`, frame is the whole partition.**

You can override with explicit frame syntax:

```sql
-- Last 3 rows including current
SUM(total) OVER (
    PARTITION BY customer_id
    ORDER BY created_at
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
)

-- 7-day moving average (PostgreSQL interval literal; MySQL 8 writes
-- INTERVAL 6 DAY PRECEDING, Oracle INTERVAL '6' DAY PRECEDING.
-- Not available at all on SQL Server — see below.)
AVG(amount) OVER (
    ORDER BY created_at
    RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
)

-- Whole partition (good for LAST_VALUE)
ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
```

Frame keywords:
- `UNBOUNDED PRECEDING` — partition start.
- `n PRECEDING` — `n` rows before current.
- `CURRENT ROW`.
- `n FOLLOWING` — `n` rows after current.
- `UNBOUNDED FOLLOWING` — partition end.

`ROWS` counts physical rows; `RANGE` counts based on `ORDER BY` value (works for dates, numbers).

```sql
-- ROWS — current row + previous 2 rows
ROWS BETWEEN 2 PRECEDING AND CURRENT ROW

-- RANGE — every row whose ORDER BY value is within 1 day of current
-- (PostgreSQL spelling; MySQL 8: INTERVAL 1 DAY PRECEDING)
RANGE BETWEEN INTERVAL '1 day' PRECEDING AND INTERVAL '1 day' FOLLOWING
```

`RANGE` semantics handle ties differently from `ROWS` — both with the same `ORDER BY` value get the same window. For most queries, `ROWS` is the safer default.

**The frame clause is where the dialects diverge most.** Three separate features get lumped together as "RANGE support":

| Feature | PostgreSQL | SQL Server | MySQL 8 |
|---|---|---|---|
| `ROWS n PRECEDING/FOLLOWING` | yes | yes (2012+) | yes |
| `RANGE` with an offset — `RANGE BETWEEN 5 PRECEDING`, `RANGE BETWEEN INTERVAL '6 days' PRECEDING` | yes (11+) | **no** | yes |
| `GROUPS n PRECEDING` (frame counted in peer groups) | yes (11+) | no | no |
| `EXCLUDE CURRENT ROW / GROUP / TIES / NO OTHERS` | yes (11+) | no | no |

SQL Server's restriction is explicit in the `OVER` documentation: "You can't use `RANGE` with `<unsigned value specification> PRECEDING` or `<unsigned value specification> FOLLOWING`." `RANGE` there is limited to `UNBOUNDED PRECEDING`, `CURRENT ROW` and `UNBOUNDED FOLLOWING`. So the calendar-window idiom — "the last 7 *days*, however many rows that is" — has no direct T-SQL spelling. On SQL Server you either densify the date axis first (left-join a calendar table so every day has a row, then `ROWS 6 PRECEDING` is exactly 7 days) or fall back to a correlated `APPLY`.

`EXCLUDE` is the PostgreSQL-only piece that solves a real problem cleanly: "average of this customer's *other* orders". Note that `EXCLUDE` is part of the frame clause, so it needs an explicit frame unit — you cannot bolt it onto a bare `PARTITION BY`:

```sql
-- PostgreSQL 11+
AVG(total) OVER (PARTITION BY customer_id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                 EXCLUDE CURRENT ROW)
```

Elsewhere you write `(SUM(total) OVER (PARTITION BY customer_id) - total) / NULLIF(COUNT(*) OVER (PARTITION BY customer_id) - 1, 0)` — correct, and a reminder of why the guard matters: a customer with exactly one order has no "other" orders, and without `NULLIF` that is a divide-by-zero rather than a null.

**`RANGE` is not just a semantic choice on SQL Server — it changes the physical plan.** In row mode, a windowed aggregate is implemented by a `Window Spool` operator that, in Microsoft's words, "expands each row into the set of rows that represents the window associated with it" and "stores all input rows in a hidden worktable in the tempdb database or in memory". With `ROWS UNBOUNDED PRECEDING` the engine takes a fast path and writes a fixed, tiny number of rows into an in-memory worktable per input row. With `RANGE`, it cannot know in advance how many peers share the current ordering value, so it uses the on-disk worktable in `tempdb`. Itzik Ben-Gan's write-up of this puts the switch-over at 10,000 rows per underlying row — "if the number of rows that need to be written to the spool per underlying row could exceed 10,000, or if SQL Server cannot predict the number, it will use the slower on-disk spool" — and measured the `RANGE` version of a running total taking more than four times as long as the `ROWS UNBOUNDED PRECEDING` version on his test data. Treat that multiple as one measurement on one dataset, not a law; the mechanism (memory worktable versus `tempdb` worktable) is the part that transfers.

Which is why the advice "always write the frame explicitly" is stronger on SQL Server than anywhere else: omitting it gives you `RANGE`, and `RANGE` gives you the disk spool. `SUM(x) OVER (ORDER BY d)` and `SUM(x) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING)` return identical results whenever `d` is unique, and only one of them is cheap.

> 🌍 **In the real world**: a settlement report on SQL Server computed a running balance with `SUM(amount) OVER (PARTITION BY account_id ORDER BY posted_date)` — no frame clause, and `posted_date` was a `date`, so every transaction on the same day was a peer. Two things went wrong at once. Semantically, all of a day's transactions got the *same* running balance (the end-of-day figure), so the statement PDF showed a balance that did not move down the page within a day and did not match the per-line arithmetic; accounting had been manually "correcting" it for months. Physically, the default `RANGE` frame pushed the window spool onto the `tempdb` worktable, and once the table grew the report's `tempdb` usage started colliding with everything else on the instance. Changing the frame to `ROWS UNBOUNDED PRECEDING` and the ordering to `posted_date, transaction_id` fixed the arithmetic and the spool in the same edit — which is the useful thing to remember, because the two symptoms arrived on different tickets, filed by different teams, months apart.

### Common patterns

**Top N per group** — a near-universal pattern. Use `ROW_NUMBER()` and filter:

```sql
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY total DESC) AS rn
    FROM orders
)
SELECT * FROM ranked WHERE rn <= 3;
-- Top 3 orders per customer.
```

The window form reads best and is the right default when you need every group. When the driving set is small — a single customer's detail page, a filtered list of twenty accounts — the alternatives are usually the faster plan, because they can seek instead of sort:

```sql
-- PostgreSQL: DISTINCT ON — the most recent order per customer, one row each
SELECT DISTINCT ON (customer_id) customer_id, id, created_at, total
FROM orders
ORDER BY customer_id, created_at DESC;

-- PostgreSQL: LATERAL, driven by a small list of customers
SELECT c.id, o.*
FROM customers c
CROSS JOIN LATERAL (
    SELECT * FROM orders o
    WHERE o.customer_id = c.id
    ORDER BY o.created_at DESC
    LIMIT 3
) o;

-- SQL Server: the same shape
SELECT c.id, o.*
FROM customers c
CROSS APPLY (
    SELECT TOP (3) * FROM orders o
    WHERE o.customer_id = c.id
    ORDER BY o.created_at DESC
) o;
```

The decision is cardinality, not taste. `LATERAL` / `CROSS APPLY` does *n* index seeks — one per driving row — so it wins when the driving set is small relative to the fact table and an index on `(customer_id, created_at DESC)` exists. The window function reads and sorts the whole fact table once, so it wins when you genuinely need every group and there is no usable index. `DISTINCT ON` is PostgreSQL-only and can walk a matching index directly.

One optimizer detail worth knowing on PostgreSQL: since **version 15** the planner can push a filter like `WHERE rn <= 3` down into the `WindowAgg` node as a *run condition*, letting the executor stop emitting rows for a partition once the row number can no longer satisfy it. The release note is terse — "Improve the performance of window functions that use `row_number()`, `rank()`, `dense_rank()` and `count()`" — but `EXPLAIN` shows it directly (PostgreSQL 15–17 print the window as `(?)`; PostgreSQL 18's release notes list "Add details about window function arguments to `EXPLAIN` output", so newer output is more informative):

```
->  WindowAgg
      Run Condition: (row_number() OVER (?) <= 3)
```

It applies only to those monotonic functions (`row_number`, `rank`, `dense_rank`, `count`), not to `sum`, `min` or `max`, and it saves the *evaluation* work, not the sort. There is no documented equivalent on SQL Server, which is part of why `CROSS APPLY ... TOP (N)` is the more common T-SQL answer to top-N-per-group.

> 🌍 **In the real world**: a "last 3 orders per customer" panel on a customer-detail screen was written with the `ROW_NUMBER` CTE because that is the pattern everyone knows. It ranked the whole `orders` table — hundreds of millions of rows by then, on a table whose clustered index was still the identity `id` from the original schema — and threw away all but three rows per customer, for a screen that displays exactly one customer. The plan was a full clustered-index scan plus a sort that spilled, and the endpoint was the slowest in the service. Rewriting it as `CROSS APPLY (SELECT TOP (3) ... ORDER BY created_at DESC)` against a nonclustered index on `(customer_id, created_at DESC) INCLUDE (total)` turned it into three key lookups. The window function was not the wrong tool in general — it was the wrong tool for a query whose driving set was one row, and the giveaway was in the plan the whole time: rows read in the millions, rows returned in single digits.

**Running total:**
```sql
SELECT customer_id, created_at, total,
       SUM(total) OVER (PARTITION BY customer_id ORDER BY created_at) AS running_total
FROM orders;
```

**Moving average (last 7 days):**
```sql
SELECT day, daily_revenue,
       AVG(daily_revenue) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS ma_7
FROM daily_revenue;
```

**Compare to previous (delta):**
```sql
SELECT month, revenue,
       revenue - LAG(revenue) OVER (ORDER BY month) AS delta_from_prev,
       (revenue - LAG(revenue) OVER (ORDER BY month))
       / NULLIF(LAG(revenue) OVER (ORDER BY month), 0) * 100 AS pct_change
FROM monthly_revenue;
```

**Percentile / Quartile:**
```sql
SELECT id, salary,
       NTILE(100) OVER (ORDER BY salary) AS percentile,
       NTILE(4)   OVER (ORDER BY salary) AS quartile
FROM employees;
```

**First and most recent per group (without LIMIT):**
```sql
SELECT
    customer_id,
    FIRST_VALUE(total)  OVER (PARTITION BY customer_id ORDER BY created_at) AS first_order,
    LAST_VALUE (total)  OVER (PARTITION BY customer_id ORDER BY created_at
                              ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS latest_order
FROM orders;
```

**Cumulative percentage of total:**
```sql
SELECT product_name, sales,
       SUM(sales) OVER (ORDER BY sales DESC) AS cumulative,
       SUM(sales) OVER ()                     AS total,
       1.0 * SUM(sales) OVER (ORDER BY sales DESC) / SUM(sales) OVER () AS cumulative_pct
FROM products
ORDER BY sales DESC;
-- Pareto-style: products contribute 80% of revenue?
```

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Visualizing PARTITION BY + ORDER BY + frame

```
Source orders for customer 7 (already filtered):
+----+------------+-------+
| id | created_at | total |
+----+------------+-------+
| 1  | 2025-01-15 |  100  |
| 2  | 2025-02-01 |   50  |
| 3  | 2025-03-10 |   80  |
| 4  | 2025-04-22 |  200  |
+----+------------+-------+

SUM(total) OVER (PARTITION BY customer_id ORDER BY created_at):
  Default frame = UNBOUNDED PRECEDING TO CURRENT ROW
   - Row 1 (id=1): SUM of just id=1 = 100 → running_total = 100
   - Row 2 (id=2): SUM of {1,2} = 150     → running_total = 150
   - Row 3 (id=3): SUM of {1,2,3} = 230    → running_total = 230
   - Row 4 (id=4): SUM of {1,2,3,4} = 430  → running_total = 430

SUM(total) OVER (PARTITION BY customer_id ORDER BY created_at
                 ROWS BETWEEN 1 PRECEDING AND CURRENT ROW):
   - Row 1: previous + current = NULL+100 = 100
   - Row 2: previous+current = 100+50 = 150
   - Row 3: previous+current = 50+80 = 130   ← only last 2
   - Row 4: previous+current = 80+200 = 280
```

Visualization is essential — sketch the frame for each row.

### Ranking comparison on a tied dataset

```
employees (sorted by salary DESC):
+-----+----------+--------+
| id  | name     | salary |
+-----+----------+--------+
| 5   | E        | 100k   |
| 3   | C        | 100k   |
| 1   | A        |  90k   |
| 7   | G        |  80k   |
| 2   | B        |  80k   |
| 4   | D        |  75k   |
+-----+----------+--------+

ROW_NUMBER():        1, 2, 3, 4, 5, 6
RANK():              1, 1, 3, 4, 4, 6   ← gap after ties
DENSE_RANK():        1, 1, 2, 3, 3, 4   ← no gap
NTILE(3):            1, 1, 2, 2, 3, 3   ← split into 3 buckets
```

Pick:
- `ROW_NUMBER` when you need a stable unique number (e.g., picking "the" row for a tied group).
- `RANK` for "Olympic medals" semantics (ties share rank; next has gap).
- `DENSE_RANK` for compact ranking (ties share, no gap).
- `NTILE` for percentile bucketing.

### LAG/LEAD for time-series analysis

```sql
-- Per customer, time between consecutive orders
SELECT
    customer_id, created_at,
    LAG(created_at) OVER (PARTITION BY customer_id ORDER BY created_at) AS prev_order,
    EXTRACT(DAY FROM created_at - LAG(created_at) OVER (PARTITION BY customer_id ORDER BY created_at)) AS days_between
FROM orders;
```

```
+-------------+-------------+-------------+--------------+
| customer_id | created_at  | prev_order  | days_between |
+-------------+-------------+-------------+--------------+
|     7       | 2025-01-15  | NULL        | NULL         |  ← first order
|     7       | 2025-02-01  | 2025-01-15  | 17           |
|     7       | 2025-03-10  | 2025-02-01  | 37           |
|     7       | 2025-04-22  | 2025-03-10  | 43           |
+-------------+-------------+-------------+--------------+
```

Customer's purchase intervals — useful for churn modeling, "average days between orders."

The date arithmetic is the non-portable half. The query above is PostgreSQL: `timestamp - timestamp` yields an `interval` and `EXTRACT(DAY FROM ...)` pulls the day component out of it — which also means it truncates the hours, and if `created_at` were a `date` the subtraction would yield a plain integer and `EXTRACT` would fail. SQL Server writes `DATEDIFF(DAY, LAG(created_at) OVER (...), created_at)`; MySQL writes `DATEDIFF(created_at, LAG(created_at) OVER (...))`. Same window function, three different scalar expressions around it.

### Top-3 per group — the canonical pattern

```sql
WITH ranked AS (
    SELECT
        category, product_name, sales,
        ROW_NUMBER() OVER (PARTITION BY category ORDER BY sales DESC) AS rn
    FROM products
)
SELECT category, product_name, sales
FROM ranked
WHERE rn <= 3
ORDER BY category, sales DESC;
```

Result: top 3 best-selling products per category. The CTE ranks; the outer SELECT filters.

If you want ties (Olympic semantics), use `RANK()` instead of `ROW_NUMBER()`. If you want "top 3 distinct values" (no gaps), `DENSE_RANK()`.

### Moving average — 7-day rolling

```sql
SELECT
    day,
    daily_revenue,
    AVG(daily_revenue) OVER (
        ORDER BY day
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS ma_7day
FROM daily_revenue
ORDER BY day;
```

```
+-----------+----------------+----------+
| day       | daily_revenue  | ma_7day  |
+-----------+----------------+----------+
| 2025-05-01|     1000       |  1000.0  |  ← only 1 value in window
| 2025-05-02|     1200       |  1100.0  |  ← 2 values
| 2025-05-03|     1100       |  1100.0  |
| 2025-05-04|     1300       |  1150.0  |
| 2025-05-05|     1500       |  1220.0  |
| 2025-05-06|     1600       |  1283.3  |
| 2025-05-07|     1800       |  1357.1  |  ← 7 values
| 2025-05-08|     1400       |  1414.3  |  ← 7 values, sliding
+-----------+----------------+----------+
```

The window slides as the row advances. For datasets with gaps in dates, use `RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW` instead of `ROWS` — on PostgreSQL 11+ or MySQL 8. On SQL Server that syntax does not exist; join a calendar table so every day has a row, and then `ROWS 6 PRECEDING` is genuinely 7 days.

> 🌍 **In the real world**: an ops dashboard tracked a 7-day rolling error rate with `ROWS BETWEEN 6 PRECEDING AND CURRENT ROW` over a table that only had a row for days on which at least one error occurred. During a quiet fortnight the "7-day window" silently stretched across a month, so the rolling average kept including a bad day from three weeks earlier and the tile stayed amber long after the incident was resolved. Nobody trusted it, so nobody looked at it, so a genuine regression went unnoticed for two days. The fix was to generate the date axis (`generate_series` on PostgreSQL, a calendar dimension table on SQL Server) and left-join the counts onto it, which made the window mean seven days again *and* made the zero-error days visible as zeros rather than as absences. Sparse fact tables and `ROWS` frames do not mix, and the failure is silent — the query never errors, it just answers a different question.

### Percent of total

```sql
SELECT
    product, sales,
    100.0 * sales / SUM(sales) OVER () AS pct_of_total,
    100.0 * sales / SUM(sales) OVER (PARTITION BY category) AS pct_of_category
FROM products;
```

`SUM(sales) OVER ()` is total across all products (same value on every row). `SUM(sales) OVER (PARTITION BY category)` is total within the category.

### Gaps and islands — bonus pattern

A classic interview problem: identify consecutive sequences in time-stamped data.

```sql
-- Find consecutive days a user logged in (ignoring gaps)
WITH numbered AS (
    SELECT user_id, login_date,
           login_date - INTERVAL '1 day' * (ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date)) AS grp
    FROM logins
)
SELECT user_id, MIN(login_date) AS streak_start, MAX(login_date) AS streak_end, COUNT(*) AS days
FROM numbered
GROUP BY user_id, grp
ORDER BY user_id, streak_start;
```

The trick: subtract the row number (incrementing by 1) from the date — consecutive days collapse to the same `grp` value; gaps create new `grp` values. Then group by `grp` to find the runs.

The date arithmetic is PostgreSQL. SQL Server writes `DATEADD(DAY, -ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date), login_date)`; MySQL writes `DATE_SUB(login_date, INTERVAL rn DAY)`, easiest to build by numbering the rows in an inner query and subtracting in the next, so the interval operand stays a plain column reference. And the pattern only works when the input has at most one row per user per day — duplicate days break the one-to-one correspondence between the date step and the row-number step, so de-duplicate (or `DENSE_RANK` instead of `ROW_NUMBER`) first.

> 🌍 **In the real world**: a subscription business paid a retention bonus based on "longest unbroken run of active months", computed with exactly this gaps-and-islands pattern over a `subscription_months` table. The table turned out to contain two rows for any month in which a customer changed plan mid-month. Because `ROW_NUMBER` incremented twice while the month incremented once, the `grp` key changed inside what was really a continuous run, and every plan upgrade looked like a churn-and-return. The customers penalised were precisely the ones who had upgraded — the best customers. It survived a quarter because the numbers were plausible and nobody reconciled a single account by hand. The fix was one line, `SELECT DISTINCT user_id, month` in the inner query, and the lesson was that gaps-and-islands assumes a grain it never states: one row per entity per step. Assert that grain before trusting the answer.

### Window function execution order

```
1. FROM / JOIN (build input rows)
2. WHERE        (filter rows)
3. GROUP BY     (collapse for non-window aggregates)
4. HAVING       (filter groups)
5. SELECT       — including WINDOW FUNCTIONS
6. DISTINCT
7. ORDER BY
8. LIMIT

Implication: window functions run AFTER WHERE and GROUP BY, but BEFORE the final ORDER BY / LIMIT.
You can't filter on a window function in WHERE — it doesn't exist yet.
Use a CTE / subquery to filter on a window function value:
```

```sql
-- ❌ Doesn't work
SELECT *, ROW_NUMBER() OVER (PARTITION BY ...) AS rn
FROM orders
WHERE rn <= 3;
-- Error: rn doesn't exist in WHERE.

-- ✅ Works (CTE)
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY ...) AS rn FROM orders
)
SELECT * FROM ranked WHERE rn <= 3;

-- ✅ Works (QUALIFY — Teradata originally; also Snowflake, BigQuery,
--    Databricks SQL, DuckDB)
SELECT *, ROW_NUMBER() OVER (PARTITION BY ...) AS rn
FROM orders
QUALIFY rn <= 3;
```

`QUALIFY` is the cleanest syntax but isn't in the SQL standard — it began as a Teradata extension. None of SQL Server, PostgreSQL or MySQL support it, so in a .NET shop the CTE form is the one you will actually write.

One more consequence of the ordering: `DISTINCT` runs *after* the window functions. `SELECT DISTINCT customer_id, ROW_NUMBER() OVER (ORDER BY id) FROM orders` never collapses anything, because the row number makes every row unique before `DISTINCT` looks at them. The SQL Server `PERCENTILE_CONT` idiom earlier is the one case where that ordering is exactly what you want.

### Reading a window-function execution plan

Two engines, two vocabularies for the same work. Query: `SUM(total) OVER (PARTITION BY customer_id ORDER BY created_at ROWS UNBOUNDED PRECEDING)`.

```
PostgreSQL, no supporting index
  WindowAgg
    ->  Sort
          Sort Key: customer_id, created_at
          ->  Seq Scan on orders

PostgreSQL, with an index on (customer_id, created_at)
  WindowAgg
    ->  Index Scan using ix_orders_cust_created on orders
    (no Sort node — the index already delivers the required order)
```

```
SQL Server, row mode (abridged — real plans often show two Segment operators,
one for the partition boundary and one for the frame)

  Compute Scalar
    |-- Stream Aggregate
          |-- Window Spool
                |-- Segment                  (marks the first row of each customer)
                      |-- Sort               (customer_id ASC, created_at ASC)
                            |-- Clustered Index Scan
```

The operators, in Microsoft's own descriptions: **Segment** "divides the input set into segments based on the value of one or more columns … The input is sorted by these columns"; **Window Spool** "expands each row into the set of rows that represents the window associated with it" and "stores all input rows in a hidden worktable in the tempdb database or in memory"; **Sequence Project** "adds columns to perform computations over an ordered set" — that is the operator that appears instead of Window Spool for `ROW_NUMBER`, `RANK` and `DENSE_RANK`, which have no frame and so need no window spool. (`NTILE` is the exception among the ranking functions: it needs the partition's row count before it can assign a bucket, so its plan picks up a spool and a nested loop to supply that count.) Seeing `Window Spool` at all tells you the query has a frame; seeing `Segment` + `Sequence Project` alone tells you it is only ranking.

Three things to look for when a window query is slow:

1. **A `Sort` under the window operator.** That is the whole cost on large inputs, and it is the one thing an index can remove.
2. **A spill.** PostgreSQL: `Sort Method: external merge  Disk: …` in `EXPLAIN (ANALYZE, BUFFERS)`. SQL Server: a spill warning on the Sort, and an actual row count far above the estimate. Microsoft's own mitigations are the mundane ones — statistics that cover the partitioning and ordering columns, memory grant feedback (compatibility level 140+), and reducing the input with `WHERE`.
3. **Row mode where batch mode was possible.** On SQL Server the **Window Aggregate** operator can run in batch mode, which the documentation says "might run faster … than in row mode". It becomes available when the query touches a columnstore index, or — since SQL Server 2019 (15.x), at database compatibility level 150 or higher — on plain rowstore heaps and B-trees. You cannot force it; you check the operator's `Actual Execution Mode` property in the actual plan and see whether it says `Batch`.

**The index that removes the sort** has a name in Itzik Ben-Gan's material: the **POC index** — Partitioning, Ordering, Covering. Key columns are the `PARTITION BY` columns first, then the `ORDER BY` columns in the same direction the window asks for; everything else the query touches goes in `INCLUDE` so the index covers the query without widening the key. Both SQL Server and PostgreSQL 11+ support `INCLUDE` on a B-tree index. Microsoft's `OVER` documentation states the rule without the acronym: "the position of the key columns in the new nonclustered index must match the `PARTITION BY` columns followed by the `ORDER BY` columns … If an `ORDER BY` clause is present, the order of the index key columns must also match the order specified in the `ORDER BY` clause."

```sql
-- SQL Server
CREATE INDEX ix_orders_poc ON orders (customer_id, created_at) INCLUDE (total);

-- PostgreSQL
CREATE INDEX ix_orders_poc ON orders (customer_id, created_at) INCLUDE (total);
```

Direction matters and is the detail people miss. A backward index read reverses *every* key column at once, never one of them — so an index on `(created_at)` serves an unpartitioned `ORDER BY created_at DESC`, but nothing serves a window whose ordering mixes directions, like `ORDER BY region ASC, revenue DESC`, except an index declared so that it can be read straight through or reversed as a whole, e.g. `(region ASC, revenue DESC)`. When a `PARTITION BY` is combined with a `DESC` ordering, read the plan rather than assuming: whether the optimizer will take an ascending index backwards to serve it is engine- and version-specific, and the index that matches the window's declared directions exactly always works.

And the count that matters for a query with many `OVER` clauses is the number of **distinct `(PARTITION BY, ORDER BY)` pairs**, not the number of window functions. Five windows sharing one key cost one sort. Two windows with unrelated keys cost two. (When one window's ordering is a prefix of another's, the planner may serve both from a single sort — check the plan rather than counting on it.)

> 🌍 **In the real world**: a month-end analytics query on SQL Server carried eleven `OVER` clauses across four different partition/order combinations, so four sorts of a large fact table. The cardinality estimate on the partitioning column was stale, the memory grant was sized for a fraction of the real row count, and every one of those sorts spilled to `tempdb`. The report itself completed — slowly, and it looked unremarkable in the logs — but while it ran, `tempdb` was saturated and *other people's* queries were the ones that failed: anything needing a sort, a hash, or a version store. The on-call engineer spent the first hour looking at the failing OLTP queries, which were innocent. What actually found it was reading the actual execution plan and seeing four spill warnings with actual row counts orders of magnitude above estimated. Three changes stuck: updated statistics on the partitioning and ordering columns, consolidating the eleven windows onto two shared window definitions, and moving the job to a read-only replica. Two of those three came straight out of Microsoft's own list of spill mitigations.

### Why a sliding frame is cheap on one column type and expensive on another (PostgreSQL)

A frame with a moving *start* — `ROWS BETWEEN 29 PRECEDING AND CURRENT ROW` — is the case where the aggregate has to forget rows as well as remember them. PostgreSQL handles this with what the manual calls **moving-aggregate mode**: an aggregate can supply an *inverse transition function* that removes a row's contribution from the running state. With one, "the run time is only proportional to the number of input rows"; without one, "the window function mechanism must recalculate the aggregate from scratch each time the frame starting point moves", giving run time "proportional to the number of input rows times the average frame length".

The catch is arithmetic, not implementation. The manual names `sum` over `float4`/`float8` as the aggregate for which "adding an inverse transition function seems easy at first, yet where this requirement cannot be met", and shows exactly why with a deliberately unsafe user-defined aggregate:

```sql
-- The documented counter-example: subtracting is not the inverse of adding
-- in floating point.
SELECT unsafe_sum(x) OVER (ORDER BY n ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING)
FROM (VALUES (1, 1.0e20::float8), (2, 1.0::float8)) AS v (n, x);
-- second row returns 0, not 1: 1e20 + 1 = 1e20, and 1e20 - 1e20 = 0
```

So the practical consequence for a 30-day moving sum over a money column: on `numeric` (or the integer types) the built-in `sum` ships an inverse transition function and the sliding frame is a linear pass; on `float8` it deliberately does not, so the engine rebuilds each window. That is a second, independent reason to store money as `numeric`/`decimal` rather than `float` — the first being that `float` sums are not reproducible when the addition order changes. Check rather than assume for any other aggregate: the catalog column `pg_aggregate.aggminvtransfn` holds the "inverse transition function for moving-aggregate mode (zero if none)", so a zero there means every frame move is a rebuild.

SQL Server has no user-visible equivalent knob; the analogous lever there is the frame you write, since `ROWS UNBOUNDED PRECEDING` is the shape that gets the in-memory spool fast path.

### Version gates and dialect support

| | PostgreSQL | SQL Server | MySQL |
|---|---|---|---|
| Window functions at all | 8.4 | ranking functions in 2005; `LAG`/`LEAD`/`FIRST_VALUE`, aggregate `ORDER BY`, and frames in **2012 (11.x)** | **8.0** (MariaDB: 10.2) |
| `ROWS` frame | yes | 2012+ | yes |
| `RANGE` with offset / `INTERVAL` | 11+ | **no** — documented limitation, still current | yes |
| `GROUPS` frame mode | 11+ | no | no |
| `EXCLUDE` frame exclusion | 11+ | no | no |
| Named `WINDOW` clause | yes | **2022 (16.x)**, compat level 160 | 8.0 |
| `IGNORE NULLS` | not implemented (18) | 2022 (16.x) | parsed, then errors |
| `FILTER (WHERE …)` on a window aggregate | yes | no — use `CASE` | no — use `CASE` |
| `DISTINCT` inside a window aggregate | no | no (documented limitation) | no |
| `PERCENTILE_CONT` | aggregate only (`WITHIN GROUP`, no `OVER`) | window only (`OVER` required) | absent |
| `QUALIFY` | no | no | no |
| `NTH_VALUE` | yes (`FROM FIRST` only) | no | yes (`FROM FIRST` only) |

The row that catches most people moving between a PostgreSQL prototype and a SQL Server production database is `RANGE` with an offset, because the query is valid, readable, and simply will not parse on the other side.

> 🌍 **In the real world**: a reporting library shared between two products was written against PostgreSQL and used `RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW` for every rolling metric — the correct choice there, because the source table skips days with no activity. When the second product's customer insisted on SQL Server, that clause did not degrade or behave differently; it failed to compile, on every rolling metric in the library, on the first run. The port took a fortnight it had not been budgeted: each metric had to be joined to a calendar dimension so that every day had a row, after which `ROWS 29 PRECEDING` covered exactly the 30 days it was supposed to. The team's retrospective note was worth more than the fix — "supports window functions" had been treated as a single checkbox during the platform assessment, when the frame clause, the null-treatment clause and the percentile functions are three separate checkboxes and the engines score differently on each.

### Window functions from .NET

There is no LINQ translation for `OVER` in EF Core. The tracking issue, [dotnet/efcore#12747 "Support SQL window functions"](https://github.com/dotnet/efcore/issues/12747), is open and sitting in the Backlog milestone with no assignee, so as of EF Core 10 the options are:

```csharp
// 1. Raw SQL. The normal answer. Database.SqlQuery<T> returns an unmapped
//    CLR type from EF Core 8 onward; before that, FromSql onto a keyless
//    entity type configured with HasNoKey().
var page = await db.Database
    .SqlQuery<OrderRankRow>($"""
        WITH ranked AS (
            SELECT o.Id, o.CustomerId, o.Total,
                   ROW_NUMBER() OVER (PARTITION BY o.CustomerId ORDER BY o.Total DESC) AS Rn
            FROM Orders o
        )
        SELECT Id, CustomerId, Total FROM ranked WHERE Rn <= {n}
        """)
    .ToListAsync();

// 2. A database view or table-valued function that contains the window
//    function, mapped with ToView(...) / HasDbFunction(...). Keeps the
//    window SQL in migrations rather than in string literals.

// 3. A third-party translator package if you need it composable in LINQ.
```

What you must not do is the shape that looks like LINQ working: pulling the group into memory (`.ToList()` then `.GroupBy(...).Select(g => g.OrderByDescending(...).Take(3))`) turns one indexable query into a full table read. EF Core 3.0 onward throws on queries it cannot translate rather than silently evaluating them client-side, so the failure mode today is usually an explicit exception — but a `.ToList()` placed before the grouping defeats that protection, because from EF's point of view the query ended there.

Two related notes. `ROW_NUMBER`-based paging is not the same as `Skip`/`Take`: EF emits `OFFSET … FETCH NEXT` (SQL Server 2012+, PostgreSQL `LIMIT/OFFSET`), and both that and a `ROW_NUMBER` filter must still produce and discard every row before the offset, so deep pages get linearly worse. Keyset pagination — on PostgreSQL or MySQL, `WHERE (created_at, id) < (@lastDate, @lastId) ORDER BY created_at DESC, id DESC LIMIT 20` — is the fix, and it needs no window function at all. T-SQL has no row-value comparison, so the same predicate there is spelled out longhand (`WHERE created_at < @lastDate OR (created_at = @lastDate AND id < @lastId)`) with `OFFSET 0 ROWS FETCH NEXT 20 ROWS ONLY` or `TOP (20)`. And when you do write raw window SQL, parameterise it: string-concatenating a `PARTITION BY` column name from user input is a SQL injection hole that no `SqlQuery` interpolation will catch, because identifiers cannot be parameterised.

</details>

## Common pitfalls

1. **Filtering on a window function in `WHERE`.** Window functions evaluate after `WHERE`. Use a CTE or subquery; or `QUALIFY` if your dialect supports it.
2. **`LAST_VALUE` returns current row's value.** Default frame ends at `CURRENT ROW`. Override with `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` to get the actual last.
3. **Assuming `RANGE` with an offset is portable.** It is not, and it does not degrade gracefully — SQL Server rejects `RANGE n PRECEDING` / `RANGE INTERVAL … PRECEDING` outright, so the query fails to compile rather than falling back to `ROWS`. PostgreSQL 11+ and MySQL 8 support it; PostgreSQL additionally requires exactly one `ORDER BY` column and an offset type it can add to it (an `interval` for date/timestamp ordering).
4. **`ROW_NUMBER` ties broken arbitrarily.** If multiple rows have the same `ORDER BY` value, which one gets the lower number is undefined — not "storage order", not stable across runs. Add tie-breaker columns until the ordering is total, especially when the row number decides which row gets deleted.
5. **`PARTITION BY` confused with `GROUP BY`.** GROUP BY collapses rows; PARTITION BY doesn't. Both can coexist in one query.
6. **No `ORDER BY` in window for cumulative aggregates.** `SUM(x) OVER (PARTITION BY y)` (no ORDER BY) computes the same value on every row of the partition. Add ORDER BY for running totals.
7. **Filtering window functions vs ranking.** `WHERE row_number = 1` doesn't work directly. Use CTE; understand window functions execute mid-pipeline.
8. **Ignoring NULL behavior in `LAG`.** `LAG(x)` returns NULL on the first row of partition. `LAG(x, 1, 0)` provides a default.
9. **Frame clause confusion.** `ROWS` is rows physical; `RANGE` is value-based. Stick to `ROWS` unless you specifically need value-based (e.g., date ranges with gaps).
10. **Sequence problems with non-unique `ORDER BY`.** Two rows tied; `ROW_NUMBER` picks one arbitrarily. If reproducibility matters, ORDER BY all distinguishing columns.
11. **Performance: window functions over huge datasets.** There is no hash-based window operator — each distinct `(PARTITION BY, ORDER BY)` pair needs its input *sorted*, and on a large table that sort is the whole cost. A POC index (partition keys, then order keys in the matching direction, covering the rest) removes it; nothing else does.
12. **Mixing aggregates and window functions.** `SUM(x)` is a regular aggregate (collapses); `SUM(x) OVER ()` is a window. Easy to typo and miss the OVER clause.
13. **Relying on the window's `ORDER BY` to order the output.** It orders the computation. The result set order is only guaranteed by a query-level `ORDER BY`; the coincidence holds until the plan goes parallel or an index removes the sort.
14. **Forgetting that `WHERE` shrinks the window's population.** `SUM(x) OVER ()` totals the rows that survived the filter, not the table. Percent-of-total tiles silently re-base themselves when someone adds a filter to the screen.
15. **Windowing over a fan-out join.** A join to two child tables multiplies rows before the window sees them, so `SUM(child.amount) OVER (PARTITION BY parent.id)` double-counts. Aggregate each child relationship in its own CTE and join the aggregates.
16. **Omitting the frame on SQL Server.** The default is `RANGE`, which forces the on-disk `tempdb` worktable for the Window Spool; `ROWS UNBOUNDED PRECEDING` gets the in-memory fast path and, when the ordering column is unique, the identical answer.
17. **`COUNT(DISTINCT x) OVER (...)`.** Rejected by SQL Server (documented limitation), PostgreSQL and MySQL. Use the two-`DENSE_RANK` trick or a `GROUP BY` CTE joined back.
18. **Assuming `IGNORE NULLS` exists.** SQL Server has it from 2022; PostgreSQL does not implement it at all as of 18; MySQL parses it and then errors. Write the `COUNT(col) OVER (...)` grouping trick if the query has to run on more than one engine.

## Interview-ready summary

- **Window functions** = aggregate or value functions over a window of rows, *without collapsing*. Each row keeps its identity.
- **`OVER (...)`** defines the window: `PARTITION BY` (group), `ORDER BY` (sequence within group), frame clause (range of rows).
- **Ranking:** `ROW_NUMBER` (unique), `RANK` (ties + gap), `DENSE_RANK` (ties, no gap), `NTILE(n)` (n buckets).
- **Value:** `LAG` / `LEAD` (previous / next row), `FIRST_VALUE` / `LAST_VALUE` (window edges).
- **Aggregate windows:** `SUM/AVG/COUNT/MIN/MAX OVER (...)`. With `ORDER BY`, default frame produces running aggregates.
- **Frame:** `ROWS BETWEEN N PRECEDING AND M FOLLOWING` for sliding windows.
- **Pattern: top N per group** — `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` then filter `rn <= N` in CTE. For top-1 with a small driving set, `LATERAL`/`CROSS APPLY` against an index usually beats it.
- **Window functions execute after WHERE** — filter on them via CTE or `QUALIFY`. That also means the window's population is the *post-filter* row set, and that the window's `ORDER BY` does not order the result.
- **Cost model:** one sort per distinct `(PARTITION BY, ORDER BY)` pair. A POC index — partition columns, then order columns in the matching direction, covering the rest — removes the sort.
- **Engine fault lines to name unprompted:** `RANGE` with an offset (no SQL Server), `GROUPS` and `EXCLUDE` (PostgreSQL only), `IGNORE NULLS` (SQL Server 2022+, not PostgreSQL), `FILTER` (PostgreSQL only), `PERCENTILE_CONT` (window-only on SQL Server, aggregate-only on PostgreSQL, absent in MySQL), `DISTINCT` in a window aggregate (nowhere), `QUALIFY` (none of the three).

**Expected interview questions:**

1. *"Find the top 3 highest-paid employees per department."* — `ROW_NUMBER() OVER (PARTITION BY department ORDER BY salary DESC)` in a CTE, filter `rn <= 3`.
2. *"`ROW_NUMBER` vs `RANK` vs `DENSE_RANK`?"* — ROW_NUMBER unique 1,2,3,...; RANK ties same + gap (1,1,3); DENSE_RANK ties same + no gap (1,1,2).
3. *"Calculate running total of monthly sales."* — `SUM(sales) OVER (ORDER BY month)`. Default frame is unbounded preceding to current row.
4. *"7-day moving average."* — `AVG(x) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)`.
5. *"Find each customer's previous order date."* — `LAG(created_at) OVER (PARTITION BY customer_id ORDER BY created_at)`.
6. *"Find Nth highest salary using window functions."* — `DENSE_RANK() OVER (ORDER BY salary DESC)` in CTE; filter where rank = N.
7. *"Why doesn't `WHERE row_number > 5` work?"* — Window functions execute after WHERE. Use a CTE: `WITH ranked AS (SELECT *, ROW_NUMBER() OVER ... FROM ...) SELECT * FROM ranked WHERE row_number > 5;`.
8. *"Does the `ORDER BY` inside `OVER` order my result set?"* — No. It orders the computation. Add a query-level `ORDER BY` if the caller needs an order; the rows often *arrive* in window order because of the sort in the plan, and that stops being true the moment the plan changes.
9. *"What index would make this window query fast?"* — Partition columns first, then order columns in the same direction, covering the rest — the POC index. It converts `Sort → WindowAgg` into `Index Scan → WindowAgg`. Count distinct `(PARTITION BY, ORDER BY)` pairs to know how many sorts you are paying for.
10. *"You wrote `SUM(x) OVER (ORDER BY d)` with no frame. What did you actually get?"* — `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`, meaning all peers sharing the current `d` value get the same total. If `d` is a date and several rows share a day, that is usually a bug; on SQL Server it is also the slow spool path. Write `ROWS UNBOUNDED PRECEDING`.
11. *"Median salary per department."* — Engine-dependent, and saying so is the answer. SQL Server: `SELECT DISTINCT department, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) OVER (PARTITION BY department)`. PostgreSQL: `percentile_cont(0.5) WITHIN GROUP (ORDER BY salary)` with `GROUP BY department` and no `OVER`. MySQL 8: neither exists.
12. *"How would you do this in EF Core?"* — You wouldn't, in LINQ: there is no `OVER` translation (`dotnet/efcore#12747`, still open). Raw SQL via `Database.SqlQuery<T>`, or a view / table-valued function mapped with `ToView` / `HasDbFunction`. And do not "solve" it by materialising the group in memory first.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — OVER clause anatomy

> **Q**: What are the three optional clauses inside `OVER (...)` and what does each one control?
>
> **A**: `PARTITION BY` splits rows into independent windows by key (like `GROUP BY` but without collapsing rows). `ORDER BY` sequences rows inside each partition (and implicitly engages a default frame). The frame clause (`ROWS`/`RANGE`/`GROUPS BETWEEN ... AND ...`) restricts which rows in the partition feed the function for the current row.
>
> **Cross-Q**: If I write `SUM(x) OVER ()` with completely empty parentheses, what window does each row see?
>
> **A**: The whole result set — no partitioning, no ordering, no frame restriction. Every row gets the same grand total. It's the cheapest window: the engine computes the aggregate once and broadcasts it. Useful for "% of overall total" without a self-join.
>
> **Cross-Q²**: Can two window functions in one `SELECT` share a window definition without retyping it?
>
> **A**: Yes — use the named `WINDOW` clause (standard SQL): `SELECT ..., SUM(x) OVER w, AVG(x) OVER w FROM t WINDOW w AS (PARTITION BY g ORDER BY d)`. Supported by PostgreSQL, MySQL 8, Oracle, and SQL Server from **2022 (16.x)** — where it additionally requires database compatibility level 160, so a 2022 instance left at level 150 rejects it. The optimizer can also collapse identical inline definitions into a single sort, but the explicit `WINDOW` clause makes the intent obvious and prevents drift if you tweak the definition. You can extend a named window in the `OVER` clause (`OVER (w ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)`) but you can't redefine a component it already specifies.

### Drill 2 — PARTITION BY vs GROUP BY

> **Q**: I've already got `GROUP BY department` doing department totals. Why would I ever switch to `PARTITION BY department`?
>
> **A**: `GROUP BY` collapses every employee in a department to one output row — you lose per-employee detail. `PARTITION BY` keeps every employee row and *adds* the department aggregate as an extra column. You want it whenever you need both row-level and group-level data side by side ("show each employee with their department's average").
>
> **Cross-Q**: Can I have `GROUP BY` and `PARTITION BY` in the *same* query?
>
> **A**: Yes. `GROUP BY` runs first (collapsing rows); window functions then run on the post-aggregation rows. Example: `SELECT department, COUNT(*) AS headcount, SUM(COUNT(*)) OVER () AS company_total FROM employees GROUP BY department`. Each row is one department, and the window adds the company-wide total to every row.
>
> **Cross-Q²**: What runs first inside the engine: the `WHERE`, the `GROUP BY`, or the `PARTITION BY`?
>
> **A**: `FROM` → `WHERE` → `GROUP BY` → `HAVING` → window functions → `DISTINCT` → `ORDER BY` → `LIMIT`. Window functions run *after* `GROUP BY` and `HAVING`, which is why you can't reference a window alias in `WHERE` or `HAVING` — they don't exist yet. You filter on window output via a CTE/subquery or `QUALIFY` (BigQuery/Snowflake/DuckDB).

### Drill 3 — ROW_NUMBER vs RANK vs DENSE_RANK on ties

> **Q**: Three employees earn the same top salary. How does each ranking function number them?
>
> **A**: `ROW_NUMBER` gives 1, 2, 3 — ties broken arbitrarily (or by any secondary `ORDER BY`). `RANK` gives 1, 1, 1, then 4 for the next (gap = number of tied rows). `DENSE_RANK` gives 1, 1, 1, then 2 (no gap, compact sequence).
>
> **Cross-Q**: I need exactly the top 5 paid employees, no more, no less. Which function and why?
>
> **A**: `ROW_NUMBER`. `RANK` could return 7 rows if there's a three-way tie at rank 5; `DENSE_RANK` could return more if multiple groups share ranks. `ROW_NUMBER` is deterministic-cardinality — exactly N rows when filtered `WHERE rn <= 5`. The caveat: which member of a tie you keep is undefined unless you add a tie-breaker column to the `ORDER BY`.
>
> **Cross-Q²**: My CTO wants "everyone tied with the top earner included." Now which function?
>
> **A**: `RANK` or `DENSE_RANK`, filtered `WHERE rank = 1`. Both put every top-tied row at rank 1; you keep all of them. Choose `RANK` if you also want gap-aware semantics elsewhere ("everyone in the top 3 ranks" including ties pushing the bottom rank past 3 — Olympic medals); choose `DENSE_RANK` for compact "top 3 distinct salaries" semantics.

### Drill 4 — Frame specification ROWS vs RANGE vs GROUPS

> **Q**: What's the difference between `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` and `RANGE BETWEEN 2 PRECEDING AND CURRENT ROW`?
>
> **A**: `ROWS` counts physical rows — exactly the two rows before the current one plus the current row. `RANGE` counts by value relative to the `ORDER BY` column — every row whose ordering value is within 2 of the current row's value. With dates: `ROWS 6 PRECEDING` gives the last 7 *rows*; `RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW` gives the last 7 *calendar days* regardless of how many rows fall in that range.
>
> **Cross-Q**: When does `ROWS` and `RANGE` give different answers on the same dataset?
>
> **A**: Whenever the `ORDER BY` column has duplicates, or when rows are unevenly distributed across the ordering values. With ties, `RANGE BETWEEN ... AND CURRENT ROW` includes *all* rows that share the current row's ordering value (peer rows), while `ROWS` only includes the physical N preceding rows. For running totals on a column with duplicates, `RANGE` produces matching running totals for tied rows; `ROWS` doesn't.
>
> **Cross-Q²**: What does `GROUPS` mode do, and which engines support it?
>
> **A**: `GROUPS BETWEEN N PRECEDING AND CURRENT ROW` counts in *peer groups* — rows sharing the same `ORDER BY` value count as one "group." `GROUPS 1 PRECEDING` means "the current peer group plus the previous peer group." Supported in PostgreSQL 11+ and SQL standard; SQL Server doesn't support `GROUPS`. Use it when you want frame boundaries in "distinct ordering values" rather than physical rows or interval ranges.

### Drill 5 — Default frame trap

> **Q**: If I write `SUM(x) OVER (ORDER BY d)` without any frame clause, what frame does the engine assume?
>
> **A**: `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` — from the start of the partition through the current row (including peer ties on the ordering column). This produces running totals, which is usually what people want.
>
> **Cross-Q**: What if I drop the `ORDER BY` entirely — `SUM(x) OVER ()`?
>
> **A**: With no `ORDER BY`, there's no frame concept; the function applies to the entire partition (or whole result set if no `PARTITION BY`). Every row gets the same value. It's the right form for "% of total" or "row's share of department total."
>
> **Cross-Q²**: Why does `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` sometimes outperform the default `RANGE` equivalent?
>
> **A**: `RANGE` requires the engine to detect peer ties on the `ORDER BY` value (so all peers get the same aggregate), which adds bookkeeping. `ROWS` is purely positional — increment a running sum row by row, no peer logic. On large partitions with unique `ORDER BY` values, the results are identical but `ROWS` is faster and uses less memory. Many teams default to explicit `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` for that reason.

### Drill 6 — LAG/LEAD for time-series gaps

> **Q**: I want days-between-orders per customer. Walk me through the query.
>
> **A**: `LAG(created_at) OVER (PARTITION BY customer_id ORDER BY created_at)` returns the previous order's date for the same customer. Subtract: `created_at - LAG(created_at) OVER (...)`. First order in each partition gets `NULL` because there's no previous row.
>
> **Cross-Q**: How do I find customers whose last order is more than 90 days ago without a self-join?
>
> **A**: `LEAD` peeking at the next order identifies it — rows where `LEAD(created_at)` is `NULL` are the customer's most recent order. But you cannot filter on that in `WHERE`, for the same reason as every other window function, so the predicate goes in an outer query: `WITH t AS (SELECT customer_id, created_at, LEAD(created_at) OVER (PARTITION BY customer_id ORDER BY created_at) AS next_order FROM orders) SELECT * FROM t WHERE next_order IS NULL AND created_at < NOW() - INTERVAL '90 days'`. `MAX(created_at) OVER (PARTITION BY customer_id)` works the same way and needs the same wrapper. Either avoids a self-join and runs in one pass. (If the question is only "which customers", a plain `GROUP BY customer_id HAVING MAX(created_at) < …` is simpler still — no window needed.)
>
> **Cross-Q²**: What does the third parameter of `LAG(col, offset, default)` do, and why does it matter for arithmetic?
>
> **A**: It's the value returned when the offset would fall outside the partition (instead of `NULL`). `LAG(total, 1, 0)` returns 0 instead of `NULL` for the first row, which means `total - LAG(total, 1, 0)` produces the first row's total instead of `NULL`. Critical for queries where downstream consumers (BI tools, reports) don't handle `NULL` arithmetic gracefully. Without the default, every arithmetic expression with a `NULL` operand returns `NULL`.

### Drill 7 — FIRST_VALUE / LAST_VALUE frame trap

> **Q**: Why does `LAST_VALUE(total) OVER (PARTITION BY c ORDER BY d)` keep returning the current row's value instead of the last value in the partition?
>
> **A**: The default frame with `ORDER BY` is `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`. "Last value" in *that* frame is the current row, because the frame ends there. To get the actual partition-end value, override the frame: `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`.
>
> **Cross-Q**: Does `FIRST_VALUE` have the same problem?
>
> **A**: No, because the default frame *starts* at `UNBOUNDED PRECEDING`. The first value in `[start, current]` is always the partition's first row, regardless of where the current row sits. `FIRST_VALUE` "just works" with the default frame; `LAST_VALUE` is the one that needs explicit framing.
>
> **Cross-Q²**: Is there a substitute pattern that avoids the frame issue entirely?
>
> **A**: Yes — `NTH_VALUE` with the appropriate frame, or `MAX(...) OVER (PARTITION BY ...)` if "last" means "largest by some ordering column" rather than "physically last in the sequence." Many teams prefer `MAX/MIN OVER (PARTITION BY ...)` precisely because the frame trap doesn't apply — there's no ordering inside the OVER, so the aggregate runs across the whole partition by default.

### Drill 8 — Running totals + moving averages

> **Q**: Show me a single query that returns both a running total and a 7-row moving average.
>
> **A**: `SELECT day, x, SUM(x) OVER (ORDER BY day) AS running, AVG(x) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS ma7 FROM t`. The first window uses default frame (unbounded preceding to current = running total); the second uses an explicit sliding 7-row frame.
>
> **Cross-Q**: How does the engine execute that — one sort or two?
>
> **A**: One sort. The optimizer recognizes both window functions share the same `ORDER BY` (and any compatible `PARTITION BY`) and reuses the sorted input for both aggregates. You can verify in `EXPLAIN ANALYZE` — single `Sort` node feeding a `WindowAgg` operator (or two stacked WindowAgg nodes with no intermediate sort).
>
> **Cross-Q²**: If I add a third window with a *different* `ORDER BY`, what changes in the plan?
>
> **A**: A second sort node appears. Each distinct `(PARTITION BY, ORDER BY)` pair requires its own sort; different framings of the same key share one. This is the main performance cost of stacking many window functions: count the distinct sort keys, not the number of `OVER` clauses. Indexes that pre-sort on the partition+order keys eliminate one or more of these sorts.

### Drill 9 — NTILE bucketing

> **Q**: What does `NTILE(4)` do?
>
> **A**: Divides the partition into 4 roughly-equal buckets numbered 1..4 by the `ORDER BY` sequence. Bucket 1 holds the lowest 25% (or highest if you `ORDER BY ... DESC`); bucket 4 holds the top 25%. If the partition has 103 rows, three buckets get 26 rows and one gets 25 — the extra rows go to the lower-numbered buckets.
>
> **Cross-Q**: How does `NTILE(100)` differ from `PERCENT_RANK`?
>
> **A**: `NTILE(100)` is *bucket assignment* — discrete integers 1..100 with ties broken arbitrarily; rows close to bucket boundaries can fall into different buckets despite near-identical values. `PERCENT_RANK` is *continuous percentile position* — a value in `[0, 1]` computed as `(rank - 1) / (total_rows - 1)`. For "top 1% customers," `NTILE(100) = 100` is roughly equivalent but `PERCENT_RANK >= 0.99` is more precise on ties.
>
> **Cross-Q²**: When does `NTILE` produce uneven buckets in a way that surprises users?
>
> **A**: When the partition has fewer rows than the bucket count: `NTILE(10)` on 7 rows gives one row per bucket 1-7 and empty buckets 8-10 — there's no bucket 8/9/10 in the output at all. Also when there are massive ties at a bucket boundary: rows with identical ordering values can split across two buckets despite being equal. Document the tie-break behavior or add a secondary `ORDER BY` for determinism.

### Drill 10 — PERCENT_RANK and CUME_DIST

> **Q**: What's the formula for `PERCENT_RANK` and how does it differ from `CUME_DIST`?
>
> **A**: `PERCENT_RANK = (rank - 1) / (N - 1)` where `rank` is the row's rank (with ties) and `N` is the partition size; values range `[0, 1]`. `CUME_DIST` is the cumulative distribution: fraction of rows with value `<=` current row's value, range `(0, 1]`. The lowest row has `PERCENT_RANK = 0` but `CUME_DIST > 0` (always at least `1/N`); the highest row has both `= 1`.
>
> **Cross-Q**: Which one matches "what percentile is this customer's spend"?
>
> **A**: `CUME_DIST` — "what fraction of customers spent the same or less than me?" matches the intuition of percentile. `PERCENT_RANK` matches "where do I sit between min and max on a 0-to-1 scale, by rank position." For business-facing percentile metrics, `CUME_DIST` is usually the right pick; `PERCENT_RANK` is often confused with `CUME_DIST` and reported incorrectly.
>
> **Cross-Q²**: How do they treat ties differently?
>
> **A**: `PERCENT_RANK` uses `RANK()` semantics — tied rows share the same percent rank value. `CUME_DIST` uses peer-group semantics — tied rows share the *higher* cumulative distribution value (because all peers count as "the same or less"). On a partition with three tied lowest values, all three get `PERCENT_RANK = 0` (they're rank 1) but `CUME_DIST = 3/N` (three rows at or below).

### Drill 11 — Top-N per group with ROW_NUMBER

> **Q**: How do I get the top 3 orders per customer by total?
>
> **A**: CTE pattern: `WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY total DESC) AS rn FROM orders) SELECT * FROM ranked WHERE rn <= 3`. Window numbers each customer's orders 1..N by descending total; outer query keeps the top 3.
>
> **Cross-Q**: How would you do this without a window function — and what's the performance penalty?
>
> **A**: Correlated subquery: `SELECT * FROM orders o WHERE (SELECT COUNT(*) FROM orders o2 WHERE o2.customer_id = o.customer_id AND o2.total > o.total) < 3`. Each row triggers a re-scan of that customer's orders, so the work is quadratic *in the partition size*: a customer with 1,000 orders costs about 10⁶ comparisons on its own, and that repeats per customer. The window function sorts once and makes a single pass — O(N log N) overall. Quote the complexity, not a speed-up multiple: the ratio depends entirely on how large the partitions are, and for tiny partitions the two are indistinguishable.
>
> **Cross-Q²**: How would `RANK` change the result, and when does that matter?
>
> **A**: `RANK` returns *all* rows tied at rank ≤ 3, which could be 5+ rows for a customer with multiple identical totals at the top. Use `RANK` when "top 3" means "everyone tied with the top 3 values"; use `ROW_NUMBER` when you need exactly 3 rows per customer. For reports where customers care about "my best 3 orders," `ROW_NUMBER` matches user intuition; for fairness ("all top performers count"), `RANK`/`DENSE_RANK`.

### Drill 12 — Sliding window aggregates

> **Q**: Compute a 30-day rolling sum of daily revenue with one query.
>
> **A**: `SELECT day, daily_revenue, SUM(daily_revenue) OVER (ORDER BY day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS rolling_30 FROM daily_revenue`. The frame slides one row per output row. First 29 rows have partial windows (fewer than 30 rows preceding). Use `RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW` for calendar-day windows when there are gaps in the dates.
>
> **Cross-Q**: Why might `ROWS` give wrong answers for sparse data?
>
> **A**: `ROWS 29 PRECEDING` counts physical rows, ignoring calendar gaps. If your daily_revenue table is missing weekends, "30 rows back" spans 42 calendar days, not 30. For a true 30-day rolling sum on PostgreSQL 11+ or MySQL 8, use `RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW` — the engine uses the `ORDER BY` value (the date) to compute the window; PostgreSQL requires a single `ORDER BY` column of a type it can add the offset to. **SQL Server has no such form** — `RANGE` there accepts only `UNBOUNDED` and `CURRENT ROW`, so the T-SQL answer is to left-join a calendar table first so every day has a row, after which `ROWS 29 PRECEDING` means exactly 30 days again.
>
> **Cross-Q²**: How do I handle the "warm-up" period where the window has fewer than 30 days?
>
> **A**: Two clean options. (1) Return the partial sum — the default behaviour, correct if the consumer understands it. (2) Suppress incomplete windows with a `CASE` over a second window function counting the frame: `CASE WHEN COUNT(*) OVER (ORDER BY day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) < 30 THEN NULL ELSE SUM(x) OVER (ORDER BY day ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) END`. Both windows must carry the *same* frame or the count describes a different set of rows than the sum. Choose based on whether downstream consumers can interpret partial windows or need uniform 30-day data.

### Drill 13 — FILTER clause (Postgres)

> **Q**: What does Postgres's `FILTER (WHERE ...)` do to a window aggregate?
>
> **A**: Restricts which rows in the frame contribute to the aggregate without restricting which rows appear in the output. `SUM(amount) FILTER (WHERE status = 'paid') OVER (PARTITION BY customer_id)` sums only paid amounts per customer, but every row of the customer (paid or unpaid) still gets the aggregate. It's a cleaner replacement for `SUM(CASE WHEN status='paid' THEN amount ELSE 0 END) OVER (...)`.
>
> **Cross-Q**: Which engines support `FILTER` on window functions?
>
> **A**: Standard SQL (SQL:2003), supported by PostgreSQL, SQLite 3.30+, and DuckDB. SQL Server and MySQL don't — you fall back to `CASE WHEN ... THEN ... END` inside the aggregate. The portable form is the `CASE` version; the `FILTER` form is cleaner and the optimizer can sometimes skip non-matching rows entirely.
>
> **Cross-Q²**: Does `FILTER` affect the *frame*, the *partition*, or just the aggregation function?
>
> **A**: Only the aggregation — the frame and partition are unchanged. The function sees the same rows; it just ignores ones that don't match the FILTER predicate when computing the result. This means `COUNT(*) FILTER (WHERE ...)` doesn't affect rolling-window denominators unless you specifically design it to. For a ratio like "paid fraction over a 7-day window", both halves need their own `OVER` with the same window: `1.0 * COUNT(*) FILTER (WHERE status = 'paid') OVER w / NULLIF(COUNT(*) OVER w, 0)` with `WINDOW w AS (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)` — which is also the tidiest argument for the named `WINDOW` clause, since a frame typed twice is a frame that will drift.

### Drill 14 — Window vs aggregate in one query

> **Q**: Can I use both `GROUP BY` (regular aggregate) and a window function in the same `SELECT`?
>
> **A**: Yes. `GROUP BY` runs first, collapsing input rows into one row per group. The window function then runs *on the post-grouped rows*. Example: `SELECT department, COUNT(*) AS dept_count, RANK() OVER (ORDER BY COUNT(*) DESC) AS dept_rank FROM employees GROUP BY department`. Each row is one department; the window ranks departments by headcount.
>
> **Cross-Q**: Can the window function reference columns *not* in the `GROUP BY`?
>
> **A**: Only via aggregates. After `GROUP BY`, the only valid expressions are the grouping columns and aggregate functions over the original columns. The window's `PARTITION BY` / `ORDER BY` / function arguments must use grouping columns or aggregates. `OVER (ORDER BY COUNT(*))` works; `OVER (ORDER BY employee_name)` doesn't compile because `employee_name` was collapsed.
>
> **Cross-Q²**: What if I want both per-employee detail *and* department totals?
>
> **A**: Drop the `GROUP BY` and use `PARTITION BY`: `SELECT employee_name, department, COUNT(*) OVER (PARTITION BY department) AS dept_count FROM employees`. No collapsing, each row keeps its identity, the department total is computed via window. Combining `GROUP BY` *and* window functions is for "group-level data with rank-among-groups" semantics — different use case from "row-level data with group context."

### Drill 15 — Performance vs correlated subqueries

> **Q**: My slow report uses `(SELECT SUM(...) FROM t t2 WHERE t2.cust = t.cust AND t2.date <= t.date)` for running totals. Why is it slow and what's the fix?
>
> **A**: It's O(N²) per partition — for each row, it scans every earlier row in the same customer's history. The window-function equivalent (`SUM(...) OVER (PARTITION BY cust ORDER BY date)`) is O(N log N) total: one sort plus a single linear pass computing the running sum incrementally. For 1M rows, that's the difference between minutes and seconds.
>
> **Cross-Q**: Are there cases where the correlated subquery actually wins?
>
> **A**: Rarely, but yes when the result is sparse and the optimizer can use an index seek to skip most rows: very selective predicates on a small subset, where only a handful of rows per partition match. In those cases the correlated subquery touches few rows and the window function still sorts the entire partition. That is the same reasoning that makes `LATERAL`/`CROSS APPLY` beat a window function for top-N over a small driving set. For a report that genuinely needs every group, the window function wins; profile both on production-shaped data before committing.
>
> **Cross-Q²**: What index would best support a window function `SUM(x) OVER (PARTITION BY cust ORDER BY date)`?
>
> **A**: A composite index on `(cust, date)` — the POC shape: **P**artitioning columns first, then **O**rdering columns in the direction the window asks for, **C**overing the rest via `INCLUDE (x)`. The index pre-sorts by the window's partition and order keys, so the engine skips the sort step entirely. The plan changes from `Sort → WindowAgg` to `Index Scan → WindowAgg` on PostgreSQL, and drops the `Sort` beneath `Segment` on SQL Server. Microsoft's `OVER` documentation states the rule directly: the index key columns must match the `PARTITION BY` columns followed by the `ORDER BY` columns, and the key order must match the `ORDER BY` order. How much it saves depends on whether the sort was spilling — measure it; the mechanism (one less sort of the whole input) is what to say in the interview.

### Drill 16 — What the window can see, and what it orders

> **Q**: My query is `SELECT product, sales, 100.0 * sales / SUM(sales) OVER () AS pct FROM products WHERE category = 'Bikes'`. What is the denominator?
>
> **A**: Total sales of bikes, not total sales. Window functions run after `FROM`/`WHERE`/`GROUP BY`/`HAVING`, so the window's population is whatever survived the filter. To get a share of the *company* total you compute it separately — a CTE with the unfiltered `SUM`, cross-joined in — or you keep every row and move the restriction into the numerator as conditional aggregation — `SUM(sales) FILTER (WHERE category = 'Bikes')` on PostgreSQL, `SUM(CASE WHEN category = 'Bikes' THEN sales END)` on SQL Server and MySQL.
>
> **Cross-Q**: My rows come back sorted by the window's `ORDER BY` even though I never wrote a query-level `ORDER BY`. Can I rely on that?
>
> **A**: No. The window `ORDER BY` sequences the computation; presentation order is only guaranteed by a query-level `ORDER BY`. Microsoft's `OVER` clause documentation draws the line explicitly — the `OVER` clause's `ORDER BY` "orders the rows in each partition", while "the `ORDER BY` clause in the `SELECT` statement determines the order in which the entire query result set is returned". The `ROW_NUMBER` article puts the same point negatively: "There is no guarantee that the rows returned by a query using `ROW_NUMBER()` will be ordered exactly the same with each execution" unless the partitioning and ordering values are unique. The rows arrive sorted because the plan happened to sort them; add an index that removes the sort, or let the plan go parallel, and the coincidence ends.
>
> **Cross-Q²**: Where in a statement *can* a window function legally appear?
>
> **A**: The `SELECT` list and the query's `ORDER BY` — PostgreSQL's manual says exactly that, and the other engines behave the same way. Not `WHERE`, not `HAVING`, not `GROUP BY`, not a `CHECK` constraint, not the `ON` clause of a join. Wrap it in a CTE or derived table to filter on it. Note also that `DISTINCT` runs *after* window functions, so `SELECT DISTINCT x, ROW_NUMBER() OVER (...)` deduplicates nothing.

### Drill 17 — Portability: what breaks when this query moves engines

> **Q**: I have a working PostgreSQL query using `AVG(x) OVER (ORDER BY d RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW)`. What happens on SQL Server?
>
> **A**: It doesn't compile. SQL Server's documentation lists it as a limitation — "You can't use `RANGE` with `<unsigned value specification> PRECEDING` or `<unsigned value specification> FOLLOWING`" — so `RANGE` there is only `UNBOUNDED PRECEDING`, `CURRENT ROW`, `UNBOUNDED FOLLOWING`. The workaround is to densify the date axis with a calendar table so every day has a row, then `ROWS 6 PRECEDING` is exactly 7 days. MySQL 8 *does* support the offset form, spelled `INTERVAL 6 DAY PRECEDING`.
>
> **Cross-Q**: Name three other window features that differ between SQL Server and PostgreSQL, and say which way each goes.
>
> **A**: `FILTER (WHERE …)` — PostgreSQL yes, SQL Server no (use `CASE`). `EXCLUDE CURRENT ROW / TIES / GROUP` and `GROUPS` frame mode — PostgreSQL 11+ only. `IGNORE NULLS` — SQL Server 2022+ only; PostgreSQL's manual says it "is not implemented in PostgreSQL". And the sharpest one: `PERCENTILE_CONT` is a *window function only* on SQL Server (`OVER` mandatory, one row out per row in, hence the `SELECT DISTINCT`) and an *ordered-set aggregate only* on PostgreSQL, where adding `OVER` raises "OVER is not supported for ordered-set aggregate percentile_cont".
>
> **Cross-Q²**: What is the same everywhere and therefore safe to assume?
>
> **A**: `ROW_NUMBER`/`RANK`/`DENSE_RANK`/`NTILE`, `LAG`/`LEAD`/`FIRST_VALUE`/`LAST_VALUE`, aggregate functions with `OVER`, `PARTITION BY`, `ORDER BY`, `ROWS` frames with numeric offsets, and the default frame rules (`RANGE UNBOUNDED PRECEDING AND CURRENT ROW` with `ORDER BY`, whole partition without). Also absent from all three: `DISTINCT` inside a window aggregate, and `QUALIFY`. That common core is enough for almost every interview problem — which is exactly why the exceptions are what gets asked.

### Drill 18 — Window functions in a .NET codebase

> **Q**: How do you express `ROW_NUMBER() OVER (PARTITION BY …)` in EF Core LINQ?
>
> **A**: You don't. EF Core has no translation for the `OVER` clause; the tracking issue `dotnet/efcore#12747` is open in the Backlog with no assignee. The realistic options are raw SQL through `Database.SqlQuery<T>` (unmapped types, EF Core 8+) or `FromSql` onto a keyless entity, a database view or table-valued function mapped with `ToView`/`HasDbFunction` so the SQL lives in migrations, or a third-party translator package.
>
> **Cross-Q**: A colleague "solves" top-3-per-customer with `db.Orders.ToList().GroupBy(o => o.CustomerId).Select(g => g.OrderByDescending(o => o.Total).Take(3))`. What's wrong with it?
>
> **A**: The `ToList()` ends the query. Everything after it runs in the application over the whole `Orders` table — a full read, all columns, all rows, per request. EF Core 3.0 removed automatic client evaluation precisely so untranslatable queries throw instead of doing this silently, but an explicit `ToList()` opts back out of that protection. The database is the only place that can use the index.
>
> **Cross-Q²**: Is `ROW_NUMBER`-based paging better or worse than `Skip`/`Take`?
>
> **A**: The same, and both degrade the same way. EF's `Skip`/`Take` emits `OFFSET … FETCH NEXT` (or `LIMIT/OFFSET`), and a `ROW_NUMBER() BETWEEN` filter does the equivalent work: the engine still produces and discards every row before the offset, so page 5,000 costs proportionally more than page 1. Keyset (seek) pagination — `WHERE (created_at, id) < (@lastDate, @lastId) ORDER BY created_at DESC, id DESC LIMIT 20` on PostgreSQL/MySQL, or the longhand `created_at < @lastDate OR (created_at = @lastDate AND id < @lastId)` on SQL Server, which has no row-value comparison — is flat regardless of depth, needs a matching index, and uses no window function at all. The trade is that you lose random access to page N.

</details>

## Cheat Sheet

- **OVER ()**: window function operates over the result; rows aren't collapsed.
- **PARTITION BY**: groups rows into independent windows; like `GROUP BY` but without row collapse.
- **ORDER BY in OVER**: defines window sequence; default frame becomes "from start to current row".
- **ROW_NUMBER vs RANK vs DENSE_RANK**: unique sequence vs ties+gap vs ties+no-gap.
- **LAG / LEAD**: peek backward / forward N rows; cleanest pattern for delta and "previous value".
- **LAST_VALUE gotcha**: default frame ends at current row; explicitly set `UNBOUNDED FOLLOWING` for true last.
- **ROWS vs RANGE**: physical row count vs value-based range; use ROWS by default.
- **Top-N per group**: `ROW_NUMBER() OVER (PARTITION BY g ORDER BY x DESC)` in a CTE, then `WHERE rn <= N`.
- **Filtering windows**: not allowed in WHERE; wrap in CTE or use `QUALIFY` (Teradata/Snowflake/BigQuery/Databricks/DuckDB — none of SQL Server, PostgreSQL, MySQL).
- **Gaps and islands**: subtract `ROW_NUMBER()` from a date to collapse consecutive runs into the same group key.
- **Window `ORDER BY` ≠ result order**: only a query-level `ORDER BY` guarantees presentation order.
- **Window population = post-`WHERE` rows**: `SUM(x) OVER ()` totals what survived the filter, not the table.
- **POC index**: Partition columns, then Ordering columns in matching direction, Covering the rest — the one thing that removes the sort.
- **One sort per distinct `(PARTITION BY, ORDER BY)` pair**, not per `OVER` clause.
- **SQL Server**: no `RANGE` offsets, no `GROUPS`, no `EXCLUDE`, no `FILTER`; `IGNORE NULLS` and `WINDOW` from 2022; default `RANGE` frame forces the `tempdb` window spool.
- **PostgreSQL**: has `GROUPS`, `EXCLUDE`, `RANGE` offsets, `FILTER`; no `IGNORE NULLS` (as of 18); `percentile_cont` is `WITHIN GROUP` only, never `OVER`.
- **No `DISTINCT` inside a window aggregate** on any of the three — use two `DENSE_RANK`s or a `GROUP BY` CTE.
- **EF Core**: no `OVER` translation (`efcore#12747`); raw SQL, a view, or a TVF.

## Walkthrough — Running total killing a correlated subquery

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A finance dashboard shows monthly customer running totals. The query takes 8 seconds for 50k orders and crushes the database. Looking at the query, every row references a correlated subquery summing all prior orders for that customer.

**Diagnosis**: Senior pulls the query:

```sql
SELECT o.id, o.customer_id, o.created_at, o.total,
       (SELECT SUM(total) FROM orders o2
        WHERE o2.customer_id = o.customer_id
          AND o2.created_at <= o.created_at) AS running_total
FROM orders o;
```

`EXPLAIN ANALYZE` confirms the shape: a `SubPlan` with `loops` equal to the outer row count — the inner `SELECT` runs once per order. The work per execution is proportional to how many of *that customer's* orders precede the current one, so the total is quadratic in the size of each customer partition. With most customers holding a handful of orders that would be harmless; here a few wholesale accounts hold tens of thousands each, and those partitions dominate the runtime. An index on `(customer_id, created_at)` makes each inner scan a range seek instead of a table scan, but it cannot change the number of executions, which is where the time goes.

**Fix**: Replace with a window function:

```sql
SELECT id, customer_id, created_at, total,
       SUM(total) OVER (
           PARTITION BY customer_id
           ORDER BY created_at
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
       ) AS running_total
FROM orders;
```

`EXPLAIN ANALYZE` now shows a single `Sort` feeding one `WindowAgg` node — no `SubPlan`, and `loops = 1` everywhere. Adding the POC index `(customer_id, created_at) INCLUDE (total)` removes the `Sort` too, leaving `Index Scan → WindowAgg`.

**Why it works**: The window function makes one pass through the table, sorted by partition + order key, computing the running aggregate incrementally. The correlated subquery instead re-evaluates from scratch per row. The cost difference is O(n log n) versus O(n²) *in the partition size* — so it is invisible for customers with three orders and brutal for the customer with fifty thousand. If you quote a speed-up in an interview, quote it as "on this table, at this size", because the ratio is a property of the data, not of the rewrite.

**The frame detail that matters here**: the fix writes `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` rather than leaving the frame off. On PostgreSQL that mostly avoids the peer-tie semantics (two orders at the same `created_at` would otherwise share a running total). On SQL Server the same edit also changes the physical plan — explicit `ROWS` gets the in-memory window spool, the default `RANGE` gets the `tempdb` worktable.

</details>

## Self-test

<details><summary>1. <code>WHERE ROW_NUMBER() OVER (...) = 1</code> errors. Why and what's the fix?</summary>

Window functions execute after WHERE in the logical pipeline. The result column doesn't exist when WHERE runs. Wrap in a CTE/subquery and filter outside, or use `QUALIFY` if your dialect supports it (BigQuery, Snowflake, DuckDB).
</details>

<details><summary>2. Trade-off: <code>ROW_NUMBER</code> vs <code>RANK</code> for "find the top N salary in each department".</summary>

ROW_NUMBER picks exactly N rows even when there are ties (deterministic but arbitrary tie-breaking). RANK keeps all ties at rank N, possibly returning more than N rows. DENSE_RANK is similar but without gaps. Pick by business need: "exactly 3 winners" -> ROW_NUMBER; "everyone tied at top 3" -> RANK or DENSE_RANK.
</details>

<details><summary>3. Why is <code>LAST_VALUE(total) OVER (PARTITION BY c ORDER BY d)</code> returning the same as the current row's total?</summary>

The default frame with ORDER BY is `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`, so "last value" is the current row's value. Override the frame to `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` to peek to the partition's actual end.
</details>

<details><summary>4. <code>ROWS BETWEEN 6 PRECEDING AND CURRENT ROW</code> for a 7-day moving average works for daily data, but not for weekly or sparse data. Why?</summary>

ROWS counts physical rows, not time. With sparse data (e.g., a customer logs in only on weekdays), 6 preceding rows might span 8 calendar days. Use `RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW` to get a true 7-day window based on the ORDER BY value.
</details>

<details><summary>5. Sketch a "gaps and islands" query to find consecutive login streaks per user.</summary>

```sql
WITH numbered AS (
  SELECT user_id, login_date,
         login_date - INTERVAL '1 day' * ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date) AS grp
  FROM logins)
SELECT user_id, MIN(login_date) AS streak_start, MAX(login_date) AS streak_end, COUNT(*) AS days
FROM numbered GROUP BY user_id, grp;
```
The `grp` value is constant within a consecutive run because the date and the row number both increment by 1; gaps break the synchrony.
</details>

<details><summary>6. Does the <code>ORDER BY</code> inside <code>OVER</code> determine the order of the rows returned to the client?</summary>

No. It determines the order in which the window function is computed. Presentation order is guaranteed only by a query-level `ORDER BY`. Microsoft's `OVER` clause documentation states both halves: the `OVER` clause's `ORDER BY` "orders the rows in each partition", while "the `ORDER BY` clause in the `SELECT` statement determines the order in which the entire query result set is returned". Rows commonly *do* arrive in window order because the plan sorted them — until an index makes the sort unnecessary or the plan goes parallel.
</details>

<details><summary>7. <code>SUM(sales) OVER ()</code> in a query that has <code>WHERE category = 'Bikes'</code> — what is the total over?</summary>

Bikes only. Window functions execute after `FROM`/`WHERE`/`GROUP BY`/`HAVING`, so the window's population is the rows that survived the filter. For a share of the unfiltered total, compute the grand total in a separate CTE and join or cross-join it in, or drop the `WHERE` and use conditional aggregation.
</details>

<details><summary>8. Which of these run on SQL Server: <code>RANGE BETWEEN INTERVAL '6 days' PRECEDING</code>, <code>GROUPS 1 PRECEDING</code>, <code>EXCLUDE CURRENT ROW</code>, <code>COUNT(*) FILTER (WHERE …) OVER ()</code>, <code>WINDOW w AS (…)</code>?</summary>

Only the last, and only from SQL Server 2022 (16.x) at compatibility level 160. The `OVER` documentation lists the `RANGE` restriction explicitly — no `<unsigned value specification> PRECEDING`/`FOLLOWING` with `RANGE` — and `GROUPS`, `EXCLUDE` and `FILTER` are absent from the T-SQL grammar entirely. `GROUPS` and `EXCLUDE` are PostgreSQL 11+; `FILTER` is PostgreSQL (also SQLite and DuckDB); on SQL Server and MySQL you write `SUM(CASE WHEN … THEN … END) OVER (…)`.
</details>

<details><summary>9. On SQL Server, why is <code>SUM(x) OVER (ORDER BY d)</code> slower than <code>SUM(x) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING)</code> when both return the same numbers?</summary>

Omitting the frame gives you the default `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`. In row mode the aggregate is computed by a `Window Spool` operator that, per Microsoft, "expands each row into the set of rows that represents the window associated with it" and stores them "in a hidden worktable in the tempdb database or in memory". With `ROWS UNBOUNDED PRECEDING` the engine writes a fixed tiny number of rows per input row and can use the in-memory worktable; with `RANGE` it cannot predict how many peers share the current ordering value, so it uses the on-disk `tempdb` worktable. Itzik Ben-Gan documents the 10,000-rows-per-underlying-row threshold and measured a multi-fold difference on his test data. The results differ too, whenever `d` has duplicates: `RANGE` gives all peers the same running total.
</details>

<details><summary>10. Write "count of distinct customers per region, on every row" without <code>COUNT(DISTINCT …) OVER (…)</code>. Why can't you use the obvious form?</summary>

`DISTINCT` inside a window aggregate is rejected by SQL Server (its `OVER` documentation lists it under Limitations), by PostgreSQL (`DISTINCT is not implemented for window functions`) and by MySQL. The portable trick is two dense ranks in opposite directions:

```sql
DENSE_RANK() OVER (PARTITION BY region ORDER BY customer_id)
+ DENSE_RANK() OVER (PARTITION BY region ORDER BY customer_id DESC) - 1
```

Each distinct value gets rank *k* ascending and *d − k + 1* descending, so the sum is always *d + 1*. Nulls get their own rank, so exclude them first if a null shouldn't count. The readable alternative is a `GROUP BY` CTE joined back.
</details>

<details><summary>11. Give the median order value per region on SQL Server, then on PostgreSQL.</summary>

SQL Server — `PERCENTILE_CONT` exists only as a window function, `OVER` is mandatory, and it returns one row per input row, so you deduplicate:

```sql
SELECT DISTINCT region,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total) OVER (PARTITION BY region) AS median
FROM orders;
```

PostgreSQL — it exists only as an ordered-set aggregate; adding `OVER` raises `OVER is not supported for ordered-set aggregate percentile_cont`:

```sql
SELECT region, percentile_cont(0.5) WITHIN GROUP (ORDER BY total) AS median
FROM orders GROUP BY region;
```

MySQL 8 has neither function.
</details>

<details><summary>12. A 30-day moving average over a <code>double precision</code> column is far slower than the same query over <code>numeric</code> on PostgreSQL. Why?</summary>

Moving-aggregate mode. A frame whose *start* moves needs the aggregate to remove rows as well as add them, which PostgreSQL does via an inverse transition function — with one, "the run time is only proportional to the number of input rows"; without one, the aggregate is recalculated from scratch at every frame move, giving run time "proportional to the number of input rows times the average frame length". Sum and average over `float4`/`float8` deliberately have no inverse transition function, because floating-point subtraction does not undo floating-point addition (the manual's example: `1e20 + 1 = 1e20`, so subtracting `1e20` yields `0`, not `1`). It is a second reason, on top of reproducibility, to store money as `numeric`.
</details>

<details><summary>13. What index makes <code>SUM(total) OVER (PARTITION BY customer_id ORDER BY created_at)</code> avoid a sort, and what does the plan look like before and after?</summary>

A POC index: `(customer_id, created_at) INCLUDE (total)` — partition columns first, then ordering columns in the direction the window asks for, covering the remaining columns. Microsoft's `OVER` documentation states the rule: the index key columns must match the `PARTITION BY` columns followed by the `ORDER BY` columns, in the `ORDER BY`'s order. Before: PostgreSQL `WindowAgg → Sort → Seq Scan`; SQL Server `Stream Aggregate → Window Spool → Segment → Sort → Scan`. After: the `Sort` disappears and the scan becomes an index scan. Mixed directions (`ORDER BY a ASC, b DESC`) need an index declared with those directions — reading an index backwards flips *all* the columns, not one.
</details>

<details><summary>14. How do you express a window function in EF Core LINQ?</summary>

You don't — there is no `OVER` translation, and `dotnet/efcore#12747` is still open in the Backlog. Use raw SQL (`Database.SqlQuery<T>` for unmapped types from EF Core 8, or `FromSql` onto a keyless entity), or push the query into a view / table-valued function mapped with `ToView` / `HasDbFunction`. Materialising with `ToList()` and grouping in memory is not a workaround — it turns an indexable query into a full table read, and it bypasses the EF Core 3.0+ behaviour of throwing on untranslatable queries.
</details>

## Cross-references

- [Subqueries & CTEs](./04-subqueries-and-ctes.md) — CTEs are the typical wrapper for window-function filtering.
- [Aggregation & Grouping](./03-aggregation-and-grouping.md) — `GROUP BY` aggregates collapse rows; window aggregates don't.
- [Joins & Set Operations](./02-joins-and-set-operations.md) — window functions often replace self-joins.
- [Advanced Patterns & Interview Problems](./09-advanced-patterns-and-interview-problems.md) — gaps & islands, top-N per group, hierarchical.
- [Indexes & Query Optimization](./06-indexes-and-query-optimization.md) — indexing partition + order keys.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *SQL Window Functions* by Bruce Momjian (PostgreSQL conference talks; available on YouTube).
- PostgreSQL — [Window Functions tutorial](https://www.postgresql.org/docs/current/tutorial-window.html) and [4.2.8 Window Function Calls](https://www.postgresql.org/docs/current/sql-expressions.html) — frame modes `ROWS`/`RANGE`/`GROUPS`, `EXCLUDE` options, the default frame, and the "permitted only in the SELECT list and the ORDER BY clause" rule.
- PostgreSQL — [9.22 Window Functions](https://www.postgresql.org/docs/current/functions-window.html) — the function list, and the note that `RESPECT NULLS`/`IGNORE NULLS` "is not implemented in PostgreSQL".
- PostgreSQL — [38.12 User-Defined Aggregates → Moving-Aggregate Mode](https://www.postgresql.org/docs/current/xaggr.html) — the inverse transition function, the run-time comparison, and the `float8` counter-example quoted above.
- PostgreSQL — [15.0 Release Notes](https://www.postgresql.org/docs/release/15.0/) — "Improve the performance of window functions that use `row_number()`, `rank()`, `dense_rank()` and `count()`" (the `Run Condition` optimization; commit `9d9c02ccd`).
- Microsoft Learn — [OVER clause (T-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/select-over-clause-transact-sql) — the `RANGE`-offset and `DISTINCT` limitations, the default-frame rules, the supporting-index guidance, batch-mode Window Aggregate, and spill mitigation.
- Microsoft Learn — [WINDOW clause (T-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/select-window-transact-sql) — SQL Server 2022 (16.x), compatibility level 160.
- Microsoft Learn — [LAG](https://learn.microsoft.com/en-us/sql/t-sql/functions/lag-transact-sql) and [FIRST_VALUE](https://learn.microsoft.com/en-us/sql/t-sql/functions/first-value-transact-sql) — `IGNORE NULLS` from SQL Server 2022, and the `OVER ( [partition_by_clause] order_by_clause )` syntax that admits no frame clause on `LAG`/`LEAD`.
- Microsoft Learn — [ROW_NUMBER](https://learn.microsoft.com/en-us/sql/t-sql/functions/row-number-transact-sql) — "`ROW_NUMBER()` is nondeterministic" and the conditions under which repeat executions may order rows differently. The window-order-vs-result-order wording quoted on this page is from the `OVER` clause article's `ROW_NUMBER` example.
- Microsoft Learn — [PERCENTILE_CONT](https://learn.microsoft.com/en-us/sql/t-sql/functions/percentile-cont-transact-sql) — `OVER` mandatory, no `ORDER BY` or frame inside it, and the `SELECT DISTINCT` idiom in Microsoft's own example.
- Microsoft Learn — [Showplan logical and physical operators reference](https://learn.microsoft.com/en-us/sql/relational-databases/showplan-logical-and-physical-operators-reference) — the quoted descriptions of **Segment**, **Sequence Project**, **Window Spool** and **Window Aggregate**.
- Itzik Ben-Gan — [T-SQL bugs, pitfalls, and best practices — window functions](https://sqlperformance.com/2019/08/sql-performance/t-sql-bugs-pitfalls-and-best-practices-window-functions), SQLPerformance — the implicit-`RANGE` trap, the 10,000-rows-per-underlying-row spool threshold, and the measured `ROWS` vs `RANGE` comparison.
- *T-SQL Querying* by Itzik Ben-Gan — comprehensive window-function chapter. The POC (Partitioning, Ordering, Covering) index acronym comes from his window-functions books, *Microsoft SQL Server 2012 High-Performance T-SQL Using Window Functions* and its successor *T-SQL Window Functions*.
- MySQL 8.4 Reference Manual — [Window function frame specification](https://dev.mysql.com/doc/refman/8.4/en/window-functions-frames.html) (RANGE with `INTERVAL`, default frames) and [Window function descriptions](https://dev.mysql.com/doc/refman/8.4/en/window-function-descriptions.html) (`IGNORE NULLS` and `FROM LAST` parsed but rejected).
- [dotnet/efcore#12747 — Support SQL window functions](https://github.com/dotnet/efcore/issues/12747) — open, Backlog milestone; the reason window SQL in EF Core is raw SQL or a mapped view.
- LeetCode SQL Hard problems — most use window functions.

<!-- nav-footer-start -->

---

[← Previous: Subqueries & CTEs](04-subqueries-and-ctes.md) · [↑ Back to top](#window-functions) · [Next: Indexes & Query Optimization →](06-indexes-and-query-optimization.md)

<!-- nav-footer-end -->

</details>
