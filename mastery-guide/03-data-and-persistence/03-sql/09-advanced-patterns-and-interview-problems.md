# Advanced Patterns & Interview Problems

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › [SQL Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-08 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [Find Nth highest value](#find-nth-highest-value)
  - [Top-N per group](#top-n-per-group)
  - [Running totals and moving averages](#running-totals-and-moving-averages)
  - [Gaps and islands](#gaps-and-islands)
  - [Median calculation](#median-calculation)
  - [Pivot and unpivot](#pivot-and-unpivot)
  - [Hierarchical queries](#hierarchical-queries)
  - [Self-joins for pair finding](#self-joins-for-pair-finding)
  - [Anti-patterns rephrased as classics](#anti-patterns-rephrased-as-classics)
  - [Stored procedures, functions, triggers](#stored-procedures-functions-triggers)
  - [Interval overlap and packing](#interval-overlap-and-packing)
  - [Reading the plan: window function vs APPLY](#reading-the-plan-window-function-vs-apply)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--top-3-orders-per-customer-blowing-up-the-app-tier)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

The first eight files cover SQL building blocks. This one applies them to the canonical interview problems and recurring real-world patterns. By the time you finish this file, "find the second-highest salary," "find consecutive login days per user," "find pairs of products often bought together" should be muscle memory.

LeetCode's SQL section is full of these patterns. So is every senior backend interview's SQL whiteboard round. The good news: most problems reduce to a handful of templates, and once you recognize the template, the solution writes itself.

When NOT to memorize: don't grind purely for interview prep if you're already fluent. Use this file to spot patterns you haven't seen and get them in your toolbox.

The part that separates a senior answer from a correct one is the second half: after you write the query, you have to say what the engine will do with it, and where the pattern stops working. Most of these templates have a version that is right on one engine and a syntax error on another, and most of them have a plan shape that is fine at ten thousand rows and fatal at ten million. Both halves are interview material.

> 🌍 **In the real world**: a team standardised on a "recipes" wiki page of exactly these patterns, copied from a PostgreSQL codebase, and used it when they built a reporting module for an on-premises customer running SQL Server. Six of the eight recipes did not compile: `WITH RECURSIVE` (T-SQL has no `RECURSIVE` keyword), `login_date - 1` on a `date` column (SQL Server allows no integer arithmetic on `date`), `LEAST`/`GREATEST` (SQL Server 2022 and later only), `PERCENTILE_CONT` with `GROUP BY` (T-SQL requires `OVER`), `LIMIT` (T-SQL uses `TOP` or `OFFSET/FETCH`), and a `RANGE BETWEEN INTERVAL` frame (T-SQL's `RANGE` accepts only `UNBOUNDED` and `CURRENT ROW`). None of them was a hard problem; all of them were found one at a time, in the customer's environment, over a fortnight. The lesson the team wrote at the top of the page afterwards was that a pattern is not portable until you have named the engine it was written for.

## Core concepts

### Find Nth highest value

The classic. Five solutions; pick the one that fits the dialect and ties policy.

```sql
-- Setup
CREATE TABLE employees (id INT, name VARCHAR, salary DECIMAL(18, 2));
INSERT INTO employees VALUES
  (1, 'A', 100), (2, 'B', 100), (3, 'C', 90), (4, 'D', 80), (5, 'E', 80), (6, 'F', 75);
```

**Method 1 — subquery:** find max smaller than the previous max.
```sql
-- 2nd highest (treats ties as one rank — see DENSE_RANK below)
SELECT MAX(salary) FROM employees
WHERE salary < (SELECT MAX(salary) FROM employees);
-- Returns 90 (since 100 is the highest, 90 is the 2nd highest distinct value)
```

**Method 2 — `LIMIT ... OFFSET`:**
```sql
-- PostgreSQL / MySQL syntax. T-SQL has no LIMIT — use Method 5.
SELECT DISTINCT salary FROM employees
ORDER BY salary DESC
LIMIT 1 OFFSET 1;
-- 2nd distinct salary
```

**Method 3 — `DENSE_RANK` window:**
```sql
WITH ranked AS (
    SELECT salary, DENSE_RANK() OVER (ORDER BY salary DESC) AS rk
    FROM employees
)
SELECT DISTINCT salary FROM ranked WHERE rk = 2;
-- Cleaner; handles ties as you'd expect.
```

**Method 4 — `ROW_NUMBER` (no ties):**
```sql
WITH ranked AS (
    SELECT salary, ROW_NUMBER() OVER (ORDER BY salary DESC) AS rn
    FROM employees
)
SELECT salary FROM ranked WHERE rn = 2;
-- Returns 100 (the second row by salary DESC; tie broken arbitrarily).
-- Different from "2nd distinct salary" — depends on what's asked.
```

**Method 5 — `OFFSET FETCH` (ANSI):**
```sql
SELECT salary FROM employees
ORDER BY salary DESC
OFFSET 1 ROW FETCH NEXT 1 ROWS ONLY;
-- ANSI standard; works in SQL Server 2012+, PostgreSQL.
-- T-SQL requires an ORDER BY on the same SELECT for OFFSET/FETCH. MySQL doesn't support this form.
```

**The interview gotcha**: ask "ties or distinct?" before solving. "2nd highest distinct salary" → DENSE_RANK = 2 or DISTINCT + LIMIT/OFFSET. "Person who has the 2nd highest salary" (Olympic-style) → RANK = 2.

**`WITH TIES` — the clause most people don't know exists.** Both SQL Server and PostgreSQL can extend a row limit to include everything tied with the last row, without a window function:

```sql
-- SQL Server: TOP (n) WITH TIES — requires ORDER BY
SELECT TOP (3) WITH TIES name, salary FROM employees ORDER BY salary DESC;

-- PostgreSQL 13+: FETCH FIRST ... WITH TIES
SELECT name, salary FROM employees
ORDER BY salary DESC
FETCH FIRST 3 ROWS WITH TIES;
```

Both return four rows if the third and fourth salaries are equal. The default is `ONLY` (exactly n rows, tie broken arbitrarily). PostgreSQL added `WITH TIES` in 13 — the release note reads "Allow `FETCH FIRST` to use `WITH TIES` to return any additional rows that match the last result row" — and its docs note `ORDER BY` is mandatory with it and `SKIP LOCKED` is not allowed alongside it. MySQL has no equivalent; there you write `RANK() <= 3` — `RANK`, not `DENSE_RANK`, because `WITH TIES` takes the first n *rows* and then adds whatever ties the nth, which is exactly the set `RANK` numbers. (`DENSE_RANK() <= 3` answers a different question — "the top three distinct values" — and returns more rows whenever there are ties above the cut.)

> 🌍 **In the real world**: a quarterly sales-incentive report picked the top three reps per region with `ROW_NUMBER() ... <= 3` and fed the result straight into the payroll export. Two reps in one region closed the quarter on identical revenue to the cent — an artifact of a single large account being split evenly between them — and `ROW_NUMBER` broke the tie the way it always does, by whatever order the sort happened to emit. One rep was paid the bonus, the other was not, and the difference was invisible in the report because the losing row simply did not appear. It surfaced as an HR complaint, not a bug report. The fix was one clause, `TOP (3) WITH TIES`, plus a decision from the compensation owner that ties are paid to both — which is the part engineering could not decide alone. The general lesson: `ROW_NUMBER` does not report that it made a choice, so anywhere its output drives money or access, ask what the tie policy is before you write the query.

### Top-N per group

A near-universal real-world pattern. The window-function solution is the cleanest.

```sql
-- Top 3 best-selling products per category
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

For ties:
- `ROW_NUMBER()` — exactly N per group, ties broken arbitrarily.
- `RANK()` — ties get the same rank; gap to next; possibly more than N rows.
- `DENSE_RANK()` — ties same rank; no gap; up to N distinct ranks.

**Lateral / CROSS APPLY alternative** (works without window functions):

```sql
-- SQL Server CROSS APPLY (PostgreSQL: LATERAL)
SELECT c.id, c.name, p.product_name, p.sales
FROM categories c
CROSS APPLY (
    SELECT TOP 3 product_name, sales
    FROM products p
    WHERE p.category_id = c.id
    ORDER BY p.sales DESC
) p;

-- PostgreSQL
SELECT c.id, c.name, p.product_name, p.sales
FROM categories c
CROSS JOIN LATERAL (
    SELECT product_name, sales FROM products
    WHERE category_id = c.id ORDER BY sales DESC LIMIT 3
) p;
```

LATERAL/CROSS APPLY runs the inner subquery for each outer row. Useful when you need pagination semantics or when the inner query references the outer.

**Two things about APPLY that catch people.**

First, `CROSS APPLY` is an inner join in disguise: a category with no products vanishes from the result entirely. If the report must list every category, including empty ones, use `OUTER APPLY` (SQL Server) or `LEFT JOIN LATERAL ... ON true` (PostgreSQL), which emit the outer row with NULLs. The window-function version has the same shape difference in reverse — it can only return categories that have at least one product row, because it starts from `products`.

Second, APPLY only wins if the inner query can *seek*. `ORDER BY sales DESC LIMIT 3` against a heap or an index that does not lead with `category_id` still reads every product for the category and sorts it, once per category — which is strictly worse than sorting once. The index that makes APPLY pay is one whose key is `(category_id, sales DESC)` with the projected columns included:

```sql
-- SQL Server
CREATE INDEX ix_products_cat_sales ON products (category_id, sales DESC) INCLUDE (product_name);
-- PostgreSQL 11+ — identical spelling; INCLUDE on btree indexes arrived in 11.
CREATE INDEX ix_products_cat_sales ON products (category_id, sales DESC) INCLUDE (product_name);
```

With that index, each inner call is "seek to the start of the category, read three entries, stop". See [Reading the plan: window function vs APPLY](#reading-the-plan-window-function-vs-apply) for what the two plans look like side by side.

MySQL has no `LATERAL` before 8.0.14 and no `APPLY` at all; on older MySQL the window-function form (8.0+) or a correlated subquery is the only option.

> 🌍 **In the real world**: a "top 10 customers per region" list drove an automated thank-you campaign with a gift card attached. It used `RANK()` rather than `ROW_NUMBER()`, because someone had read that `RANK` "handles ties properly", and the consuming code did `foreach (var row in results)` with no per-region cap. In three regions the tenth and eleventh customers had identical lifetime spend — round numbers from a single annual contract — so `RANK` returned eleven rows for those regions and eleven gift cards went out where the budget said ten. Finance noticed at reconciliation. Nothing was wrong with `RANK`; what was wrong was that the caller assumed a row count the query never promised. The team's fix was to keep `RANK` (the business genuinely wanted ties honoured) and move the cap into the budget check instead of assuming it. The reusable point for an interview: `ROW_NUMBER` guarantees exactly N rows per group, `RANK` and `DENSE_RANK` guarantee at most N *ranks* and any number of rows — so if downstream code depends on the count, only one of the three is safe.

### Running totals and moving averages

Window functions excel at time-series transformations.

```sql
-- Running total of daily revenue
SELECT
    day, revenue,
    SUM(revenue) OVER (ORDER BY day) AS running_total,
    AVG(revenue) OVER (ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS ma_7day,
    revenue - LAG(revenue) OVER (ORDER BY day) AS day_over_day_change,
    100.0 * (revenue - LAG(revenue) OVER (ORDER BY day))
        / NULLIF(LAG(revenue) OVER (ORDER BY day), 0) AS pct_change
FROM daily_revenue
ORDER BY day;
```

One pass over the data; five derived metrics. The pre-window-function era required either correlated subqueries (slow) or app-level computation. Window functions made all this elegant.

**`ROWS 6 PRECEDING` means six rows, not six days.** That distinction is the single most common defect in this pattern. If `daily_revenue` has a row for every calendar day, the two coincide and the query is right. If a day with no sales produces no row — which is what happens when the table is built by `GROUP BY` over a transactions table — then the frame silently reaches further back in time to collect its six rows, and a "7-day moving average" quietly becomes "the last 7 days that had any data".

Two fixes, and they are not equally portable:

```sql
-- PostgreSQL 11+ (offset RANGE frames arrived in 11): a time-based RANGE frame.
-- The frame is defined in calendar terms, so missing days contribute nothing.
AVG(revenue) OVER (ORDER BY day RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW)

-- SQL Server: not available. T-SQL's RANGE accepts only UNBOUNDED PRECEDING /
-- CURRENT ROW / UNBOUNDED FOLLOWING — there is no numeric or interval offset.
-- Join to a calendar (date-dimension) table first so every day has a row,
-- then ROWS 6 PRECEDING means exactly six days again.
```

`LAG`/`LEAD` have the same trap: `LAG(revenue) OVER (ORDER BY day)` is "the previous *row*", which is only "yesterday" if yesterday exists. This is why calendar dimension tables keep turning up in reporting schemas — they turn a row-offset problem back into a date problem.

> 🌍 **In the real world**: an alerting job compared each day's error count against its own 7-day moving average, written with `ROWS BETWEEN 6 PRECEDING AND CURRENT ROW` over a table produced by grouping the raw event log. During a three-week partial outage the ingestion pipeline stopped writing rows on the days it failed, so the "7-day average" was computed from seven scattered days spanning most of a month, most of them pre-outage. The current day was compared against a baseline drawn largely from healthy traffic and, worse, the days with no data raised no alert at all because they produced no row to evaluate. The dashboard was green throughout. The postmortem action was a `dim_date` join so that every day materialises with a zero, which made the missing days visible as zeros — and a zero is exactly the value that should have paged someone.

### Gaps and islands

A classic pattern: identify consecutive sequences in a stream of timestamped data. "How many consecutive days did each user log in?" "Find consecutive runs of OK status before the next error."

The trick: subtract a row number from the date — consecutive items have the same difference; gaps create new groups.

```sql
-- Setup
CREATE TABLE logins (user_id INT, login_date DATE);
INSERT INTO logins VALUES
  (1, '2025-05-01'), (1, '2025-05-02'), (1, '2025-05-03'),  -- 3-day streak
  (1, '2025-05-05'),                                          -- gap; new island
  (1, '2025-05-06'), (1, '2025-05-07'),
  (2, '2025-05-01'), (2, '2025-05-02');                       -- 2-day streak
```

**Solution** (PostgreSQL syntax — see the engine note below):
```sql
WITH grouped AS (
    SELECT
        user_id,
        login_date,
        login_date - INTERVAL '1 day' * (ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date) - 1) AS island_grp
    FROM logins
)
SELECT
    user_id,
    MIN(login_date) AS streak_start,
    MAX(login_date) AS streak_end,
    COUNT(*) AS days
FROM grouped
GROUP BY user_id, island_grp
ORDER BY user_id, streak_start;
```

The math: for consecutive dates, `date - row_number*1day` is constant; for a gap, the row number "skips ahead" of the date, breaking the sequence into a new group.

```
Result:
+---------+-------------+-----------+------+
| user_id | streak_start| streak_end| days |
+---------+-------------+-----------+------+
| 1       | 2025-05-01  | 2025-05-03|  3   |
| 1       | 2025-05-05  | 2025-05-07|  3   |
| 2       | 2025-05-01  | 2025-05-02|  2   |
+---------+-------------+-----------+------+
```

For integers (instead of dates), subtract `ROW_NUMBER` from the value directly. The pattern generalizes.

**The date arithmetic is not portable.** Only the `island_grp` expression changes:

| Engine | Expression |
|---|---|
| PostgreSQL | `login_date - INTERVAL '1 day' * (rn - 1)`, or the shorter `login_date - (rn - 1)::int` — PostgreSQL has a `date - integer → date` operator but no `date - bigint` one, and `ROW_NUMBER()` returns `bigint`, so the cast is what makes the short form compile |
| SQL Server | `DATEADD(day, -(rn - 1), login_date)` — T-SQL raises "Operand type clash: date is incompatible with int" for `date - 1`; only `datetime`/`smalldatetime` support integer arithmetic |
| MySQL | `DATE_SUB(login_date, INTERVAL (rn - 1) DAY)` |

You cannot reference the `ROW_NUMBER()` alias from another expression in the same `SELECT` list on any of the three — a select-list alias simply isn't in scope for its sibling expressions — so the row number and the subtraction go in one expression, or the row number goes in its own CTE first. The second form is easier to read and costs nothing. (`WHERE` and `GROUP BY` can't reference it either, and there the reason is a stronger one: window functions are evaluated after those clauses run, which is why filtering on a window result always needs a wrapping CTE or subquery.)

**Duplicates break the trick, silently.** The whole method rests on "row number advances by exactly one when the date advances by exactly one". If a user can log in twice on the same day, two rows share a date but get consecutive row numbers, so the second one's `date - rn` lands a day *earlier* than the first — a value that looks like a new island, and the streak is cut in half. The pattern needs one row per user per day. Either de-duplicate first (`SELECT DISTINCT user_id, login_date`) or swap `ROW_NUMBER()` for `DENSE_RANK()`, which assigns the same number to same-date rows and leaves the arithmetic intact:

```sql
-- Safe against multiple logins on the same day
DENSE_RANK() OVER (PARTITION BY user_id ORDER BY login_date)
```

Same reasoning applies to the integer version: `ROW_NUMBER` on a column with duplicate values does not produce constant differences.

Variations:
- "Find longest streak per user": add `ORDER BY days DESC LIMIT 1` per user (use ranking).
- "Find current streak": filter `island_grp` to the latest one.

> 🌍 **In the real world**: a fitness app shipped a "consecutive days logged" streak badge built on the classic `date - ROW_NUMBER` island query. It was correct in every test, because the fixtures had one activity row per user per day. In production users sync from two devices — a phone and a watch — and a day with two syncs wrote two rows. Those users' streaks were computed as a chain of one- and two-day islands and the badge reset constantly; the more engaged the user, the more devices, the more broken their streak. Support tickets said "the app forgot my streak" and were closed as unreproducible for weeks, because reproducing it required a second device. The one-word fix was `DENSE_RANK` in place of `ROW_NUMBER`. The durable lesson is that this pattern has an unstated precondition — one row per entity per interval — and a seed script that never violates it will never find the bug.

### Median calculation

Trickier than mean — many dialects have no built-in median.

**Method 1 — `PERCENTILE_CONT` (PostgreSQL, SQL Server 2012+):**
```sql
-- PostgreSQL / Oracle: an ordered-set aggregate, so it works bare or with GROUP BY.
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) AS median
FROM employees;
```

**`_CONT` interpolates; `_DISC` returns a real value.** Microsoft's documentation states the difference plainly: `PERCENTILE_CONT` "interpolates the appropriate value, which might or might not exist in the data set, while `PERCENTILE_DISC` always returns an actual value from the set". For an even number of rows with salaries 100 and 200 in the middle, `_CONT` gives 150 — a salary nobody earns — and `_DISC` gives 100. For statistics that is fine; for anything a human will treat as a real record (a median contract value quoted to a customer, a median price shown in a UI, a representative row to link to) `_DISC` is the honest choice.

MySQL has neither function — [MySQL bug #93234](https://bugs.mysql.com/bug.php?id=93234), "Support percentile_cont (SQL Standard) for median", is still unfixed (status: Verified) — so Method 2 is not merely the portable option there, it is the only option.

**Method 2 — `ROW_NUMBER` + `COUNT` (universal):**
```sql
WITH numbered AS (
    SELECT salary,
           ROW_NUMBER() OVER (ORDER BY salary) AS rn,
           COUNT(*) OVER () AS total
    FROM employees
)
SELECT AVG(salary) AS median
FROM numbered
WHERE rn IN ((total + 1) / 2, (total + 2) / 2);
-- Even count: avg of two middle. Odd count: same row counted twice → still right.
```

**Median per group — and here the engines diverge sharply:**

```sql
-- PostgreSQL / Oracle: ordered-set aggregate + GROUP BY. One row per department.
SELECT
    department,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) AS median_salary
FROM employees
GROUP BY department;
```

In **SQL Server that query does not compile**. T-SQL's `PERCENTILE_CONT` is an analytic function, not an aggregate: its documented syntax is `PERCENTILE_CONT ( numeric_literal ) WITHIN GROUP ( ORDER BY ... ) OVER ( [ <partition_by_clause> ] )` — the `OVER` clause is mandatory and `GROUP BY` is not an option. Because it is a window function it does not collapse rows, so it returns one row *per employee*, each carrying its department's median. Microsoft's own example wraps it in `SELECT DISTINCT`:

```sql
-- SQL Server
SELECT DISTINCT
    department,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) OVER (PARTITION BY department) AS median_cont,
    PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY salary) OVER (PARTITION BY department) AS median_disc
FROM employees;
```

`SELECT DISTINCT` gets the right answer but computes and then discards a row per employee. On a large table, compute the medians in a CTE and join, so the plan aggregates instead of expanding.

> 🌍 **In the real world**: a B2B pricing tool showed sales reps the "median deal size for this customer segment" as a starting anchor for a quote. It used `PERCENTILE_CONT(0.5)`, and for segments with an even number of historical deals it returned the midpoint between the two middle contracts. A rep quoted that figure to a prospect who asked which existing customer it referred to; there wasn't one, and the number sat between two real contracts that were nowhere near each other. The number was not wrong as a statistic — it was wrong as a claim, and the tool presented it as a claim. Switching to `PERCENTILE_DISC` made every displayed figure a real historical deal that a rep could point at, which is what the screen had implicitly promised all along. Choosing between the two is a product decision disguised as a function name.

### Pivot and unpivot

**Pivot** turns rows into columns. **Unpivot** does the reverse.

**Pivot — conditional aggregation (portable):**
```sql
-- Source
+--------+-------+-------+
| month  | type  | sales |
+--------+-------+-------+
| Jan    | A     | 100   |
| Jan    | B     | 50    |
| Feb    | A     | 120   |
| Feb    | B     | 80    |
+--------+-------+-------+

-- Pivot
SELECT
    month,
    SUM(CASE WHEN type = 'A' THEN sales ELSE 0 END) AS a_sales,
    SUM(CASE WHEN type = 'B' THEN sales ELSE 0 END) AS b_sales
FROM sales_table
GROUP BY month;

-- Result
+-------+---------+---------+
| month | a_sales | b_sales |
+-------+---------+---------+
| Jan   | 100     | 50      |
| Feb   | 120     | 80      |
+-------+---------+---------+
```

**SQL Server `PIVOT` operator (less portable):**
```sql
SELECT month, [A], [B]
FROM (SELECT month, type, sales FROM sales_table) src
PIVOT (SUM(sales) FOR type IN ([A], [B])) AS pvt;
```

The derived table `src` is not stylistic — it is load-bearing, and this is the classic `PIVOT` bug. `PIVOT` groups by *every column of its input that is not the aggregated column or the spreading column*, and that grouping list is implicit: it appears nowhere in the syntax. Write `FROM sales_table PIVOT (...)` directly and any extra column on the table — `order_id`, `created_at`, `region` — silently joins the grouping key, so you get one output row per distinct combination instead of one per month, and the totals fragment. The symptom is "my pivot returns too many rows", the cause is a column you forgot the table had, and the fix is always the same: project exactly the three columns you want in a derived table first. Conditional aggregation has no equivalent trap because its `GROUP BY` is written out.

PostgreSQL has no `PIVOT` operator at all (the `tablefunc` extension's `crosstab()` function is the nearest equivalent and requires you to declare the output column list anyway); MySQL has none either. Conditional aggregation is the only form that runs everywhere.

**Unpivot — UNION ALL or vendor operator:**
```sql
-- Portable
SELECT month, 'A' AS type, a_sales AS sales FROM pivoted
UNION ALL
SELECT month, 'B' AS type, b_sales FROM pivoted;

-- SQL Server UNPIVOT
SELECT month, type, sales
FROM pivoted
UNPIVOT (sales FOR type IN (a_sales, b_sales)) unpvt;
```

For dynamic pivots (column count not known at compile time): generate dynamic SQL or do final pivot in the app layer (often cleaner).

> 🌍 **In the real world**: an internal analytics endpoint pivoted "amount by custom attribute" where the attribute names were tenant-supplied strings. The dynamic pivot was built by string concatenation — `SET @cols = @cols + ',[' + a.name + ']'` — and shipped without review because it was "an internal admin tool". A tenant created an attribute whose name contained a closing bracket, which broke out of the identifier and turned the rest of the name into executable T-SQL inside the `EXEC`. Nothing malicious happened; the attribute was a typo and the query just failed with a syntax error, which is how it was found. It was a SQL injection hole reachable by any customer through a normal product feature. The correct primitive was already available — `QUOTENAME()` escapes embedded brackets by doubling them, which is exactly what hand-written concatenation forgets — and the better answer was the one they took instead: return the long form `(month, type, amount)` and pivot in C#, where the attribute name is data and can never be code.

### Hierarchical queries

Recursive CTEs (covered in [Subqueries & CTEs](./04-subqueries-and-ctes.md#recursive-ctes)) handle hierarchies.

**Before the examples, the four things that differ between engines** — all four are routine follow-up questions, and the examples below use PostgreSQL syntax:

| | PostgreSQL | SQL Server | MySQL 8.0+ |
|---|---|---|---|
| Keyword | `WITH RECURSIVE` required | no `RECURSIVE` keyword exists — plain `WITH`; writing `WITH RECURSIVE` is a syntax error | `WITH RECURSIVE` required |
| Runaway guard | none built in | `MAXRECURSION`, server-wide default 100 | `cte_max_recursion_depth`, default 1000 |
| Set operator | `UNION ALL` or `UNION` | "`UNION ALL` is the only set operator allowed between the last anchor member and first recursive member" | `UNION ALL` or `UNION` |
| Cycle handling | `CYCLE` clause (PostgreSQL 14+) | manual — carry a path column and test it | manual |

The runaway-guard row is the important one. SQL Server stops a runaway recursion by itself: exceed the limit and you get `Msg 530, The statement terminated. The maximum recursion 100 has been exhausted before statement completion.` The hint accepts 0 to 32767, where `OPTION (MAXRECURSION 0)` means no limit — and note that a legitimate deep hierarchy trips the default of 100 just as readily as a cycle does, so seeing Msg 530 does not by itself mean your data is broken.

PostgreSQL has no such limit. A cycle in the data runs until the query fills `temp_file_limit`, disk, or memory, and on a busy box that can be a bigger event than a failed query. Two defences:

```sql
-- 1. PostgreSQL 14+: the CYCLE clause. Added in 14 — "Add SQL-standard SEARCH and
--    CYCLE clauses for common table expressions".
WITH RECURSIVE descendants AS (
    SELECT id, parent_id, name FROM categories WHERE id = 5
    UNION ALL
    SELECT c.id, c.parent_id, c.name
    FROM categories c JOIN descendants d ON c.parent_id = d.id
) CYCLE id SET is_cycle USING path
SELECT * FROM descendants WHERE NOT is_cycle;

-- 2. Any version, any engine: carry a depth counter and stop.
--    ... UNION ALL SELECT ..., d.depth + 1 FROM ... WHERE d.depth < 20
```

`UNION` instead of `UNION ALL` also helps in PostgreSQL — it discards rows duplicating any previous result — but the docs warn it is not a general cycle guard: "often a cycle does not involve output rows that are completely duplicate", so two paths reaching the same node with different accumulated data still loop. The `CYCLE` clause tracks the key columns you name, which is the check that actually terminates.

Common interview prompts:

**1. "List all descendants of node X":**
```sql
WITH RECURSIVE descendants AS (
    SELECT id, parent_id, name, 0 AS depth
    FROM categories WHERE id = 5      -- starting node
    UNION ALL
    SELECT c.id, c.parent_id, c.name, d.depth + 1
    FROM categories c
    JOIN descendants d ON c.parent_id = d.id
)
SELECT * FROM descendants;
```

**2. "Find the path from root to a node":**
```sql
WITH RECURSIVE path AS (
    SELECT id, parent_id, name, ARRAY[id] AS path_ids, 0 AS depth
    FROM categories WHERE parent_id IS NULL
    UNION ALL
    SELECT c.id, c.parent_id, c.name, p.path_ids || c.id, p.depth + 1
    FROM categories c
    JOIN path p ON c.parent_id = p.id
)
SELECT * FROM path WHERE id = 42;     -- node we want path to
```

**3. "Bill of materials" (parts and sub-parts):**
```sql
WITH RECURSIVE bom AS (
    SELECT product_id, component_id, quantity FROM components WHERE product_id = 1
    UNION ALL
    SELECT b.product_id, c.component_id, b.quantity * c.quantity
    FROM bom b
    JOIN components c ON b.component_id = c.product_id
)
SELECT product_id, component_id, SUM(quantity) AS total_quantity
FROM bom GROUP BY product_id, component_id;
```

A bill of materials is the case where cycle protection stops being theoretical: a component that transitively contains itself is a data-entry error the schema cannot prevent with a foreign key, and the recursive query is usually the first thing to notice.

> 🌍 **In the real world**: a product-catalogue import let a supplier feed re-parent categories, and one night a feed set a top-level category's `parent_id` to one of its own grandchildren. On the SQL Server instance the effect was a failed nightly report — `Msg 530`, maximum recursion exhausted — an alert at 02:00, and an engineer who found the cycle in twenty minutes because the error named the mechanism. The same schema and the same feed ran on a PostgreSQL instance for a second product, and there the recursive CTE had no ceiling: it ran for hours accumulating rows, filled the temp space on the volume, and the first symptom anyone saw was unrelated queries failing to allocate. The report was not even the thing that paged. Same bug, same data, two very different nights — and the difference was a default. The team added `WHERE depth < 50` to every recursive CTE in the codebase and a `CHECK`-style validation step in the import, because a guard on the query only limits the damage; only the import can stop the cycle existing.

### Self-joins for pair finding

"Find pairs of X that share Y" pattern.

```sql
-- "Find pairs of customers who bought the same product"
SELECT DISTINCT
    LEAST(o1.customer_id, o2.customer_id) AS customer_a,
    GREATEST(o1.customer_id, o2.customer_id) AS customer_b,
    o1.product_id
FROM orders o1
JOIN orders o2 ON o1.product_id = o2.product_id
              AND o1.customer_id < o2.customer_id;
-- LEAST/GREATEST canonicalize the pair to avoid (A,B) and (B,A) duplicates.
```

```sql
-- "Find products often bought together" (basket analysis)
SELECT
    LEAST(oi1.product_id, oi2.product_id) AS p1,
    GREATEST(oi1.product_id, oi2.product_id) AS p2,
    COUNT(*) AS times_together
FROM order_items oi1
JOIN order_items oi2 ON oi1.order_id = oi2.order_id
                     AND oi1.product_id < oi2.product_id
GROUP BY LEAST(oi1.product_id, oi2.product_id), GREATEST(oi1.product_id, oi2.product_id)
ORDER BY times_together DESC
LIMIT 10;
```

**Two notes on those queries.**

First, `LEAST`/`GREATEST` are doing nothing in either one. The join predicate already says `o1.customer_id < o2.customer_id`, so the pair arrives canonical and the functions are a no-op. Pick one mechanism: the inequality in the join (which also halves the work by eliminating half the candidate pairs before they are formed) or `LEAST`/`GREATEST` in the projection (needed when the inequality can't go in the join, for example when you are canonicalising rows that came from a `UNION`). Using both reads as though the author was unsure which one worked.

Second, `LEAST`/`GREATEST` are the least portable functions on this page:

- **SQL Server**: added in **2022 (16.x)** and Azure SQL. Nothing before that — on SQL Server 2019 and earlier you write `CASE WHEN a < b THEN a ELSE b END` or a `VALUES`-based `CROSS APPLY (SELECT MIN(v) AS m FROM (VALUES (a),(b)) AS t(v)) AS x`.
- **NULL semantics differ by engine, in opposite directions.** SQL Server: "If one or more arguments aren't `NULL`, then `NULL` arguments are ignored during comparison. If all arguments are `NULL`, then `GREATEST` returns `NULL`." PostgreSQL behaves the same way. **MySQL is the opposite**: "`GREATEST()` returns `NULL` if any argument is `NULL`." Port a query that uses `GREATEST(a, b)` over a nullable column between MySQL and either of the other two and the rows that change are exactly the ones with a NULL — usually the incomplete records nobody is looking at.

**The cost model to say out loud.** A self-join on `order_id` produces a pair for every combination of lines within an order: with the `<` predicate that is n(n−1)/2 rows for an order with n lines. That is fine when orders have five lines. A wholesale order with 800 lines contributes 319,600 pairs on its own — one row of input, six figures of intermediate result — and the aggregate above has to hash all of them. Market-basket queries do not degrade gradually as the table grows; they degrade suddenly when one atypical order arrives.

> 🌍 **In the real world**: a "frequently bought together" recommendation job ran nightly over `order_items` with exactly the self-join above and finished in a few minutes for two years. The company then onboarded a distributor whose "orders" were restocking manifests with hundreds of lines each. The nightly job stopped finishing: the pair count from those accounts dominated everything, the hash aggregate spilled, and the job was still running when the morning batch window opened and started contending with it. Nothing had changed in the code or the row count of the table — the *shape* of the data had changed. The fix was a `HAVING COUNT(*) >= 2` at the end (which does not help, because it runs after the pairs are formed) and then the real one: exclude orders above a line-count threshold from basket analysis entirely, because a restocking manifest is not a shopping basket and its pairs are not a signal. Worth remembering as an interview answer — the useful move was a domain decision about which rows belong in the query, not a tuning change.

### Anti-patterns rephrased as classics

Common interview problems hidden behind unfamiliar prompts:

**"Find duplicates":**
```sql
SELECT email, COUNT(*) AS cnt FROM customers
GROUP BY email HAVING COUNT(*) > 1;
```

**"Find rows missing in another table" (anti-join):**
```sql
SELECT id FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id);
```

`NOT EXISTS`, not `NOT IN`. If the subquery can produce a single NULL, `NOT IN` returns zero rows — `x <> NULL` is UNKNOWN, so the predicate can never be true — and the query looks like it found nothing rather than like it broke. Standard three-valued logic, identical on all three engines, and the most common way an anti-join silently returns an empty set.

**"Find customers who bought *every* product in this list"** is the other prompt in this family — relational division, where the naive `IN` answers "any of" instead of "all of". Worked through in [Joins & Set Operations](./02-joins-and-set-operations.md#relational-division--all-of-not-any-of).

**"Find consecutive missing IDs" (gaps in sequence):**
```sql
SELECT id + 1 AS gap_start, next_id - 1 AS gap_end
FROM (
    SELECT id, LEAD(id) OVER (ORDER BY id) AS next_id FROM widgets
) t
WHERE next_id IS NOT NULL AND next_id > id + 1;
```

**"Customers who haven't bought in last 90 days":**
```sql
SELECT c.id, c.name FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id AND o.created_at >= NOW() - INTERVAL '90 days'
WHERE o.id IS NULL;
```

**"Most popular item per customer":**
```sql
WITH ranked AS (
    SELECT
        customer_id, product_id,
        COUNT(*) AS purchases,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY COUNT(*) DESC) AS rn
    FROM order_items oi
    JOIN orders o ON o.id = oi.order_id
    GROUP BY customer_id, product_id
)
SELECT customer_id, product_id, purchases
FROM ranked WHERE rn = 1;
```

### Stored procedures, functions, triggers

Programmable schema objects — useful in some scenarios, harmful in others.

**Stored procedure** (SP) — named procedural code that can wrap multiple SQL statements:

```sql
-- PostgreSQL (uses CREATE FUNCTION for procedures too in older versions; CREATE PROCEDURE since 11)
CREATE OR REPLACE PROCEDURE transfer_funds(from_id INT, to_id INT, amount DECIMAL)
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE accounts SET balance = balance - amount WHERE id = from_id;
    UPDATE accounts SET balance = balance + amount WHERE id = to_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Account not found';
    END IF;
END;
$$;

CALL transfer_funds(1, 2, 100);

-- T-SQL
CREATE PROCEDURE TransferFunds @FromId INT, @ToId INT, @Amount DECIMAL(18, 2) AS
BEGIN
    BEGIN TRY
        BEGIN TRANSACTION;
        UPDATE accounts SET balance = balance - @Amount WHERE id = @FromId;
        UPDATE accounts SET balance = balance + @Amount WHERE id = @ToId;
        COMMIT;
    END TRY
    BEGIN CATCH
        ROLLBACK;
        THROW;
    END CATCH;
END;

EXEC TransferFunds 1, 2, 100;
```

**User-defined function (UDF)** — returns a value or table; usable in queries.

```sql
-- PostgreSQL: scalar function
CREATE OR REPLACE FUNCTION calc_tax(amount DECIMAL, rate DECIMAL) RETURNS DECIMAL AS $$
BEGIN
    RETURN amount * rate;
END;
$$ LANGUAGE plpgsql;

SELECT id, total, calc_tax(total, 0.07) AS tax FROM orders;

-- T-SQL: table-valued function
CREATE FUNCTION GetCustomerOrders(@CustomerId INT) RETURNS TABLE AS
RETURN (SELECT * FROM orders WHERE customer_id = @CustomerId);

SELECT * FROM GetCustomerOrders(7);
```

**SQL Server scalar UDFs are slow for four named reasons**, and knowing the reasons is what makes this an answer rather than folklore. Microsoft's own documentation lists them: **iterative invocation** — the engine "invokes UDFs iteratively, once per qualifying tuple", paying a context switch each time; **lack of costing** — the optimizer costs relational operators but not scalar ones, so the UDF is effectively free in the estimate and arbitrarily expensive in reality; **interpreted execution** — the body runs statement by statement with no cross-statement optimization; and **serial execution** — "SQL Server doesn't allow intra-query parallelism in queries that invoke UDFs". That last one is the nastiest, because a single scalar UDF in the `SELECT` list forces the *whole query* to a serial plan, including the scan and join that had nothing to do with it.

**SQL Server 2019 (15.x) added scalar UDF inlining**, which rewrites qualifying UDFs into relational expressions so the optimizer can see and cost them. It requires database compatibility level 150, and it is conditional: the docs carry a long list of disqualifying constructs (time-dependent functions like `GETDATE()`, table variables, `STRING_AGG`, multiple `RETURN` statements after 2019 CU5, and more, several of which were added in cumulative updates). Check with the catalog view rather than assuming:

```sql
SELECT b.name, b.type_desc, a.is_inlineable
FROM sys.sql_modules AS a
JOIN sys.objects  AS b ON a.object_id = b.object_id
WHERE b.type IN ('IF', 'TF', 'FN');
```

`is_inlineable = 1` means the body qualifies; it does not promise inlining happened, because the calling context has its own requirements (a UDF in `ORDER BY` or `GROUP BY`, or a calling query with a CTE, disqualifies it). Confirm in the plan: an inlined UDF leaves no `<UserDefinedFunction>` node in the plan XML. Inline **table-valued** functions were always different — they are expanded into the calling query like a view, and never had the scalar problem. Multi-statement TVFs (`RETURNS @t TABLE ... BEGIN ... END`) do have a related problem: they materialise into a table variable, and the optimizer historically had to guess their row count rather than derive it (a fixed guess of 100 rows on SQL Server 2014 and later, 1 before that). SQL Server 2017 (14.x) at compatibility level 140 addresses this with interleaved execution, which pauses optimization, runs the MSTVF, and feeds the real row count back into the rest of the plan — so on a modern instance at a modern compatibility level this is a much smaller problem than the folklore suggests.

PostgreSQL has two separate levers here and it is worth keeping them apart. The first is **inlining**: the planner can fold a *SQL-language* function whose body is a single `SELECT` into the calling query, the way it folds a view, so the optimizer sees through it. PL/pgSQL functions are never inlined — they always execute as their own black box, whatever their volatility label. The second is **volatility** — `VOLATILE` (the default), `STABLE`, `IMMUTABLE` — which tells the planner how freely it may evaluate the function: only `IMMUTABLE` functions may appear in an index expression, and `STABLE`/`IMMUTABLE` let the planner evaluate a call once instead of per row. So the practical rule for a .NET developer porting a scalar UDF is: express it as a SQL-language function if you want it optimized away, and label its volatility honestly. Mislabelling a function `IMMUTABLE` when it reads tables is worse than a performance bug — the planner is then licensed to evaluate it once and reuse the value, and to build an index on it, so the wrong label can produce wrong answers.

> 🌍 **In the real world**: a reporting query on SQL Server went from seconds to minutes after a release that changed nothing about it. The release had added a computed column to the `orders` table — `TaxAmount AS dbo.CalcTax(Subtotal, TaxRate)` — using an existing scalar UDF, for a completely different feature. Every query touching `orders` now had a scalar UDF in its plan, and every one of them dropped to a serial plan on a server sized for parallel reporting. The report was not slow because it computed tax; it was slow because it was no longer allowed to use more than one core. Nothing in the report's own code or plan cost pointed at the cause — the giveaway was a `DegreeOfParallelism` of 1 on a query that had always gone parallel, and the plan XML's `NonParallelPlanReason` attribute reading `TSQLUserDefinedFunctionsNotParallelizable`. The first attempted fix was to add `PERSISTED` to the computed column, and **it did not work**, which is the part worth remembering. The optimizer loads computed-column definitions during binding, so the UDF is present in the query's metadata whether or not the column is persisted and whether or not the query references it; parallelism is disabled either way. Nor does SQL Server 2019's scalar UDF inlining rescue this case — the documented execution-context requirements exclude a UDF used "in a computed column or a check constraint definition". What actually worked was removing the function from the column definition: the tax expression was inlined into the computed column directly, and the UDF kept only for the call sites that could use it as an inline TVF. The transferable lesson: on SQL Server, a scalar UDF is not local — putting one in a computed column or a check constraint spreads its cost to every statement that touches the table, and no amount of persisting makes it local again.

**Trigger** — auto-fires on INSERT/UPDATE/DELETE.

```sql
-- PostgreSQL example: maintain a counter
CREATE OR REPLACE FUNCTION increment_order_count() RETURNS trigger AS $$
BEGIN
    UPDATE customers SET order_count = order_count + 1 WHERE id = NEW.customer_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_order_insert
    AFTER INSERT ON orders
    FOR EACH ROW EXECUTE FUNCTION increment_order_count();
```

**The trigger question that separates engines — and catches .NET developers hardest.** PostgreSQL lets you choose granularity: "A trigger that is marked `FOR EACH ROW` is called once for every row that the operation modifies... In contrast, a trigger that is marked `FOR EACH STATEMENT` only executes once for any given operation, regardless of how many rows it modifies". `NEW` and `OLD` only exist in the row-level form.

**SQL Server has no `FOR EACH ROW` clause at all.** Look at the `CREATE TRIGGER` syntax: there is nowhere to put it. Every T-SQL DML trigger is statement-level, fires once however many rows changed — including zero, which is why Microsoft's own guidance is to open each trigger with `IF (ROWCOUNT_BIG() = 0) RETURN;` — and sees the affected rows as two *set-valued* pseudo-tables, `inserted` and `deleted`:

```sql
-- WRONG on SQL Server: assumes one row. Compiles, passes every single-row test.
CREATE TRIGGER trg_order_insert ON orders AFTER INSERT AS
    UPDATE customers SET order_count = order_count + 1
    FROM inserted
    WHERE customers.id = inserted.customer_id;   -- adds 1 per customer, not 1 per row

-- RIGHT: aggregate the pseudo-table.
CREATE TRIGGER trg_order_insert ON orders AFTER INSERT AS
BEGIN
    IF (ROWCOUNT_BIG() = 0) RETURN;
    UPDATE c
    SET c.order_count = c.order_count + i.cnt
    FROM customers c
    JOIN (SELECT customer_id, COUNT(*) AS cnt FROM inserted GROUP BY customer_id) i
      ON i.customer_id = c.id;
END;
```

The first version is not a strawman — it is the shape Microsoft's documentation uses as its worked example of the bug, noting that "the expression to the right of an assignment expression in an UPDATE statement can be only a single value, not a list of values", so the trigger silently picks one row from `inserted` and applies it once. It is correct only for a genuinely single-row `INSERT ... VALUES (...)`, and wrong for a multi-row `VALUES` list, `INSERT ... SELECT`, `MERGE`, and EF Core's batched inserts.

`SqlBulkCopy` deserves its own sentence, because the usual claim about it is backwards. **By default `SqlBulkCopy` fires no insert triggers at all** — you have to opt in with `SqlBulkCopyOptions.FireTriggers`, documented as "cause the server to fire the insert triggers for the rows being inserted into the database". So a bulk load against a table with a counter trigger has two possible failure modes depending on one constructor flag: without it the counter never moves, with it the trigger fires once per batch with a multi-row `inserted` and the naive version adds one. Both are wrong, they are wrong in opposite directions, and which one you get is invisible at the SQL layer.

That last one is the trap. EF Core batches multiple `Add`ed entities into a single multi-row `INSERT` statement, so the same application code that behaved correctly with `SaveChanges()` after one `Add` starts corrupting the counter as soon as someone adds two entities before saving. Nothing in the C# looks different. (PostgreSQL is not exposed to this: a `FOR EACH ROW` trigger fires per row regardless of how the rows arrived. Its statement-level triggers can see all affected rows through transition tables declared with `REFERENCING NEW TABLE AS ...`, which the docs restrict to `AFTER` triggers.)

**When to use these:**

- **Stored procedures**: encapsulate multi-step business logic when the logic should run server-side. In modern .NET apps, most logic is in C#; SPs less common.
- **Functions**: clean up repeated expressions in queries; reuse domain calculations. Watch perf on T-SQL scalar UDFs.
- **Triggers**: audit trails, derived columns. Use sparingly — hidden behavior. Most teams prefer app-level interceptors.

For most modern apps: **prefer app-side logic in C#** (testable, version-controlled). Use SPs/triggers when:
- Cross-app integrity needs server enforcement.
- Performance demands hand-tuned T-SQL.
- Legacy schema requires it.

> 🌍 **In the real world**: an inventory service on SQL Server kept a denormalised `products.stock_on_hand` up to date with an `AFTER INSERT` trigger on `stock_movements`, written in the single-row style above. It was correct for four years, because every write came through an API endpoint that inserted one movement at a time. Then a bulk-import feature landed, using `SqlBulkCopy` to load supplier deliveries — hundreds of movements per batch. The first version passed no options, so no trigger fired and imported stock never registered at all; someone spotted that in testing and added `SqlBulkCopyOptions.FireTriggers`, which turned a visible bug into an invisible one. The trigger now fired once per batch, saw a multi-row `inserted`, and incremented stock by the quantity of one arbitrary row in it. Stock levels drifted low, the reorder logic fired against wrong numbers, and the finance reconciliation that eventually caught it was three weeks downstream of the cause. The trigger was never reviewed during the bulk-import work because nobody involved knew there was a trigger. Two things came out of it: the trigger was rewritten set-based against `inserted`, and the team started treating "which triggers fire on this table" as a required section of the design review for any new write path. Hidden behaviour is only hidden until it is wrong.

### Interval overlap and packing

Any schema with a `valid_from`/`valid_to`, `starts_at`/`ends_at`, or `effective_from`/`effective_to` pair generates the same two questions, and they come up in interviews as "find double-booked rooms" and "merge overlapping subscription periods".

**The overlap predicate.** Two intervals overlap if and only if each starts before the other ends:

```sql
-- A and B overlap:
a.starts_at < b.ends_at AND b.starts_at < a.ends_at
```

That is the whole rule, and it is worth being able to derive rather than recall: the negation is "A ends before B starts, or B ends before A starts", and the predicate above is its complement. Candidates usually reach for `BETWEEN` and enumerate cases — "B starts inside A, or B ends inside A" — and the case that gets forgotten is B completely containing A, where neither of B's endpoints falls inside A at all. Enumerating gets you there only if you remember all three; deriving the complement gets you there every time.

**Closed vs half-open is the decision that causes the bugs.** With `<` on both sides you are treating intervals as half-open, `[start, end)`: a booking ending at 10:00 and one starting at 10:00 do not overlap. With `<=` they do. Store times half-open and the arithmetic works out — adjacent intervals meet exactly, there is no ambiguous instant, and `end - start` is the duration. Store them closed (`ends_at = 09:59:59`) and you have baked a granularity assumption into the data that breaks the day someone stores milliseconds.

*Preventing* overlaps is a schema question rather than a query one, and it is covered in [Schema Design](./08-schema-design-and-normalization.md) (PostgreSQL exclusion constraints) and [Joins & Set Operations](./02-joins-and-set-operations.md) (effective-dated joins and what happens when overlaps do get stored). The rest of this section is the query problem the interview actually asks about: given rows that *do* overlap, produce their union.

**Packing intervals** — collapsing overlapping rows into their union — is gaps-and-islands with a different key. An interval starts a new island when its start is later than the greatest end seen so far in the group:

```sql
WITH ordered AS (
    SELECT customer_id, starts_at, ends_at,
           MAX(ends_at) OVER (
               PARTITION BY customer_id ORDER BY starts_at
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
           ) AS prev_max_end
    FROM subscriptions
),
flagged AS (
    SELECT *,
           CASE WHEN prev_max_end IS NULL OR starts_at > prev_max_end THEN 1 ELSE 0 END AS is_new_island
    FROM ordered
),
grouped AS (
    SELECT *,
           SUM(is_new_island) OVER (PARTITION BY customer_id ORDER BY starts_at
                                    ROWS UNBOUNDED PRECEDING) AS island_id
    FROM flagged
)
SELECT customer_id, MIN(starts_at) AS period_start, MAX(ends_at) AS period_end
FROM grouped
GROUP BY customer_id, island_id;
```

The running `MAX(ends_at)` over all *preceding* rows — not `LAG(ends_at)` — is the part people get wrong. `LAG` compares against the immediately previous interval, which fails when a long interval completely contains a short one that sorts after it: the short one's end is earlier, `LAG` says "no overlap", and the containing interval gets split. Note the explicit `ROWS` frames: with `ORDER BY` and no frame clause the default is `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`, which includes the current row's own `ends_at`. `prev_max_end` would then never be earlier than the row's own start, `starts_at > prev_max_end` would never be true, and every row would collapse into a single island. This query runs unchanged on PostgreSQL, SQL Server 2012+, and MySQL 8.0+.

**The related question — "total time covered"** — is why packing matters commercially. Summing `ends_at - starts_at` over raw rows double-counts every overlap; summing it over the *packed* result is the true covered duration. If an interviewer asks for "total hours a machine was down given overlapping incident records", they are asking for packing, and the wrong answer is a `SUM` that looks simpler and reports more downtime than the day contained.

> 🌍 **In the real world**: an SLA credit calculation summed the durations of incident records per customer per month. Incidents were opened by three different systems — synthetic monitoring, the on-call engineer, and the customer's own ticket — so a single outage routinely produced two or three overlapping rows. The sum counted the same minutes two or three times, and once the total crossed the SLA threshold the contract paid an automatic credit. The company had been paying credits for downtime that had not happened, for long enough that the finance team treated it as a normal cost line. It was caught when a customer disputed a credit in their own favour's opposite direction — their engineer pointed out the outage was ninety minutes and the credit was based on four hours. The fix was to pack the intervals before summing. What makes it worth retelling is that the query had no bug in the usual sense: every row was real, the arithmetic was right, and the error was entirely in treating overlapping intervals as if they were disjoint.

### Reading the plan: window function vs APPLY

The reader who can write both forms of top-N-per-group but cannot say which plan each produces is the one who gets stuck on the follow-up. Here are the two shapes, with the operator names each engine actually prints.

**Window function** — `ROW_NUMBER() OVER (PARTITION BY category_id ORDER BY sales DESC)` filtered to `rn <= 3`:

```
SQL Server                                 PostgreSQL
─────────────────────────────────────      ─────────────────────────────────────
Filter  (rn <= 3)                          Subquery Scan  (filter: rn <= 3)
└─ Sequence Project  (ROW_NUMBER)          └─ WindowAgg
   └─ Segment  (on category_id)               └─ Sort  (category_id, sales DESC)
      └─ Sort  (category_id, sales DESC)         └─ Seq Scan on products
         └─ Index Scan on products
```

The names differ, the shape does not. `Segment` marks where each partition begins and `Sequence Project` assigns the numbers — together they are SQL Server's `ROW_NUMBER`, and PostgreSQL does both inside one `WindowAgg`. Being able to say "the `Segment`/`Sequence Project` pair *is* the window function" is a cheap way to show you have read one of these plans rather than read about them.

Read it bottom-up. Every row of `products` is scanned, every row is sorted, `Segment` marks where each partition begins, `Sequence Project` assigns the row numbers, and only then does `Filter` throw most of them away. The two operators to point at in an interview are the `Sort` — its cost is driven by the whole table, not by the three rows per category you asked for — and the `Filter`, which sits *above* the numbering and therefore cannot reduce the work below it. The optimizer has no way to stop early: row number 4 cannot be known to exceed 3 until rows 1 to 3 have been assigned, and that requires the partition sorted.

**APPLY / LATERAL** with an index on `(category_id, sales DESC)`:

```
SQL Server                                 PostgreSQL
─────────────────────────────────────      ─────────────────────────────────────
Nested Loops  (Inner Join,                 Nested Loop
   OUTER REFERENCES: c.id)
├─ Index Scan on categories                ├─ Seq Scan on categories
└─ Top  (3)                                └─ Limit  (3)
   └─ Index Seek                              └─ Index Scan using
      ix_products_cat_sales                      ix_products_cat_sales
      Seek: category_id = c.id                   Index Cond: category_id = c.id
      Ordered: True
```

No `Sort` anywhere — the index already provides `sales DESC` order within each category, so `Top`/`Limit` stops after three index entries. The inner side runs once per category, and each run touches three rows plus the seek.

**What to look at in the actual plan, in priority order:**

1. **Actual rows vs estimated rows** on the scan. Both plans are fine when they agree; the window plan's `Sort` is where a bad estimate turns into a spill.
2. **A `Sort` with a spill warning** (SQL Server shows a warning triangle and `SpillToTempDb`; PostgreSQL's `EXPLAIN (ANALYZE, BUFFERS)` prints `Sort Method: external merge  Disk: NkB`). A sort that spills has stopped being a CPU cost and become an I/O cost.
3. **Rows read vs rows returned.** Millions read, dozens returned, for a screen showing one customer, is the signature of a window function applied to a driving set of one — the case where APPLY wins outright.
4. **Whether the `Index Seek` is `Ordered: True`.** If the index does not supply the order the inner `ORDER BY` needs, a `Sort` reappears *inside* the loop and now runs once per outer row, which is the worst of both plans.

The rule that follows from the shapes rather than from benchmarks: the window function does one pass and one sort over everything, so it wins when you need most of the rows anyway (a full report over all categories). APPLY does a seek per outer row, so it wins when the outer set is small and the index makes each seek cheap (one customer's last three orders). Neither is universally faster, and an interviewer asking "which is faster?" is usually checking whether you say "it depends on the driving set size and whether the index supports the inner sort" rather than picking one.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### "Find Nth highest" decision matrix

```
Question phrasing                              → Approach
─────────────────────────────────────────────────────────────────────
"Nth highest distinct salary"                   DENSE_RANK = N
"Nth row by salary DESC" (no tie semantics)     ROW_NUMBER = N
"Nth Olympic-rank salary" (1, 1, 3, 4, 4 ...)   RANK = N
"Just the value, simplest"                      LIMIT/OFFSET on DISTINCT
─────────────────────────────────────────────────────────────────────
```

Always clarify with the interviewer.

### Top-N per group — full pattern

```
Source data:
+----------+------------+---------+-------+
| category | product    | sales   | ...   |
+----------+------------+---------+-------+
| Books    | "Clean..." |  500    |       |
| Books    | "Refactor" |  450    |       |
| Books    | "DDD"      |  400    |       |
| Books    | "Algos"    |  300    |       |
| Apps     | "Spotify"  | 1000    |       |
| Apps     | "Slack"    |  800    |       |
+----------+------------+---------+-------+

Step 1: Rank within each category
+----------+------------+---------+----+
| category | product    | sales   | rn |
+----------+------------+---------+----+
| Books    | "Clean..." |  500    | 1  |
| Books    | "Refactor" |  450    | 2  |
| Books    | "DDD"      |  400    | 3  |
| Books    | "Algos"    |  300    | 4  |   ← drop
| Apps     | "Spotify"  | 1000    | 1  |
| Apps     | "Slack"    |  800    | 2  |
+----------+------------+---------+----+

Step 2: Filter rn <= 3
+----------+------------+---------+----+
| Books    | "Clean..." |  500    | 1  |
| Books    | "Refactor" |  450    | 2  |
| Books    | "DDD"      |  400    | 3  |
| Apps     | "Spotify"  | 1000    | 1  |
| Apps     | "Slack"    |  800    | 2  |
+----------+------------+---------+----+
```

### Gaps & islands — visualized

```
Source dates:
+------+------------+
| user | login_date |
+------+------------+
| 1    | 2025-05-01 |
| 1    | 2025-05-02 |
| 1    | 2025-05-03 |    ← 3-day streak
| 1    | 2025-05-05 |    ← gap (skipped 5-04); new island
| 1    | 2025-05-06 |
| 1    | 2025-05-07 |
+------+------------+

Compute: login_date - row_number * 1 day
+------+------------+----+--------------------+
| user | login_date | rn | island_grp         |
+------+------------+----+--------------------+
| 1    | 2025-05-01 | 1  | 2025-04-30         |  rn=1, date - 1day = 04-30
| 1    | 2025-05-02 | 2  | 2025-04-30         |  rn=2, date - 2days = 04-30  ← same!
| 1    | 2025-05-03 | 3  | 2025-04-30         |  rn=3, date - 3days = 04-30  ← same!
| 1    | 2025-05-05 | 4  | 2025-05-01         |  rn=4, date - 4days = 05-01  ← gap
| 1    | 2025-05-06 | 5  | 2025-05-01         |  rn=5, date - 5days = 05-01  ← same again
| 1    | 2025-05-07 | 6  | 2025-05-01         |  rn=6, date - 6days = 05-01
+------+------------+----+--------------------+

Group by island_grp:
+------+--------------------+----------+
| user | island_grp         | days     |
+------+--------------------+----------+
| 1    | 2025-04-30         | 3        |  (May 1, 2, 3)
| 1    | 2025-05-01         | 3        |  (May 5, 6, 7)
+------+--------------------+----------+
```

The math: when dates are consecutive, "date - rn" is constant. When there's a gap, rn ticks up one but date ticks up two — so "date - rn" jumps. Each constant value = one "island."

### Recursive CTE — bill of materials

```
Components table:
+------------+--------------+----------+
| product_id | component_id | quantity |
+------------+--------------+----------+
| 1          | 2            | 2        |  product 1 needs 2 of component 2
| 1          | 3            | 1        |  product 1 needs 1 of component 3
| 2          | 4            | 3        |  component 2 itself needs 3 of part 4
| 2          | 5            | 1        |
| 4          | 6            | 5        |  part 4 needs 5 of part 6
+------------+--------------+----------+

Recursive expansion for product 1:

Iteration 0 (anchor):
  product=1, component=2, qty=2
  product=1, component=3, qty=1

Iteration 1:
  Component 2 needs 3 of part 4 → product=1, component=4, qty=2*3 = 6
  Component 2 needs 1 of part 5 → product=1, component=5, qty=2*1 = 2

Iteration 2:
  Part 4 needs 5 of part 6 → product=1, component=6, qty=6*5 = 30

Iteration 3 (no more): terminate.

Aggregate:
+------------+--------------+----------+
| product_id | component_id | total_qty|
+------------+--------------+----------+
| 1          | 2            | 2        |
| 1          | 3            | 1        |
| 1          | 4            | 6        |
| 1          | 5            | 2        |
| 1          | 6            | 30       |
+------------+--------------+----------+

Now you know how many of each leaf-level part product 1 ultimately requires.
```

### "Customers and their last 3 orders" (Top-N per group, real-world)

```sql
WITH ranked_orders AS (
    SELECT
        customer_id, id, total, created_at,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn
    FROM orders
)
SELECT c.name, r.id AS order_id, r.total, r.created_at
FROM customers c
JOIN ranked_orders r ON r.customer_id = c.id
WHERE r.rn <= 3
ORDER BY c.name, r.created_at DESC;
```

Pivots beautifully when generating customer reports — the top-3 history at a glance.

### Year-over-year growth

```sql
SELECT
    EXTRACT(YEAR FROM created_at) AS year,
    SUM(total) AS revenue,
    LAG(SUM(total)) OVER (ORDER BY EXTRACT(YEAR FROM created_at)) AS prev_revenue,
    100.0 * (SUM(total) - LAG(SUM(total)) OVER (ORDER BY EXTRACT(YEAR FROM created_at)))
        / NULLIF(LAG(SUM(total)) OVER (ORDER BY EXTRACT(YEAR FROM created_at)), 0) AS growth_pct
FROM orders
GROUP BY EXTRACT(YEAR FROM created_at);
```

The combination of GROUP BY (year aggregation) + window function (LAG over years) is common in reporting.

### Cohort analysis

```sql
-- "Of users who signed up in each month, how many were still active 1, 2, 3 months later?"
WITH cohorts AS (
    SELECT
        DATE_TRUNC('month', created_at) AS cohort_month,
        id AS user_id
    FROM users
),
activity AS (
    SELECT user_id, DATE_TRUNC('month', login_at) AS active_month
    FROM logins GROUP BY user_id, DATE_TRUNC('month', login_at)
)
SELECT
    c.cohort_month,
    COUNT(DISTINCT c.user_id) AS cohort_size,
    EXTRACT(MONTH FROM AGE(a.active_month, c.cohort_month)) AS months_after,
    COUNT(DISTINCT a.user_id) AS active_users
FROM cohorts c
JOIN activity a ON a.user_id = c.user_id AND a.active_month >= c.cohort_month
GROUP BY c.cohort_month, EXTRACT(MONTH FROM AGE(a.active_month, c.cohort_month))
ORDER BY c.cohort_month, months_after;
```

This is a common analytics problem; the CTE chain makes it manageable.

### Trigger for soft delete cascade

```sql
-- When a customer is soft-deleted, soft-delete their open orders too
CREATE OR REPLACE FUNCTION cascade_customer_soft_delete() RETURNS trigger AS $$
BEGIN
    IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
        UPDATE orders
        SET deleted_at = NEW.deleted_at
        WHERE customer_id = NEW.id AND deleted_at IS NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_customers_soft_delete_cascade
    AFTER UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION cascade_customer_soft_delete();
```

Hidden cascade behavior. Useful but surprising for new engineers — document it. Many teams prefer explicit app-side cascades.

### Dynamic top-N parameter

```sql
-- "Top N orders for customer X" — N as parameter
CREATE OR REPLACE FUNCTION top_n_orders(p_customer_id BIGINT, p_n INT)
RETURNS TABLE (id BIGINT, total DECIMAL, created_at TIMESTAMPTZ) AS $$
BEGIN
    RETURN QUERY
    SELECT o.id, o.total, o.created_at
    FROM orders o
    WHERE o.customer_id = p_customer_id
    ORDER BY o.total DESC
    LIMIT p_n;
END;
$$ LANGUAGE plpgsql;

-- Use
SELECT * FROM top_n_orders(7, 5);
```

Or as a one-shot CTE inside the calling code. Encapsulation in a function makes sense if the same query is reused across many app paths.

</details>

## Common pitfalls

1. **`SELECT TOP 1 / LIMIT 1` for "Nth highest"** — only gets the 1st. Add `ORDER BY DESC OFFSET N-1` for the Nth.
2. **`ROW_NUMBER` when ties matter.** Always asking "what's the tie behavior?" before solving — DENSE_RANK or RANK might be the right answer.
3. **Nested aggregation without CTE.** Pure SQL `SUM(MAX(x))` doesn't work directly. Use a CTE: aggregate first, aggregate again on the result.
4. **Self-join without canonical pair order.** Returns (A, B) and (B, A). Use `WHERE a.id < b.id` or `LEAST/GREATEST` to canonicalize.
5. **Recursive CTE without termination check.** Infinite recursion. Anchor must produce rows; recursive must eventually stop. Add cycle detection on graphs.
6. **PIVOT / UNPIVOT vendor-specific syntax.** Conditional aggregation is portable. Use vendor PIVOT when concise; switch to CASE for portability.
7. **Slow median via `PERCENTILE_CONT` on huge tables.** It's accurate but expensive. Approximate methods or pre-computed percentiles for analytics.
8. **`COUNT(*) FILTER (WHERE ...)`** (PostgreSQL syntax) vs `SUM(CASE ...)` portability. Both work; pick consistency for codebase.
9. **Triggers with cross-table cascade silently breaking later changes.** The trigger does X; six months later, X conflicts with new business rule. Triggers are hidden behavior — document or move to app code.
10. **Stored procs with embedded business logic, no source control.** Live in the DB; not versioned with app code. Treat schema and procs as code (migrations, git).
11. **Functions that hide complex queries.** A function called `get_widget_count_for_customer(...)` that's actually a 200-line query — slow, hard to optimize, hard to debug. Keep functions simple.
12. **`COUNT(DISTINCT)` over huge data.** Forces a sort or hash over every value. The approximate alternative is HyperLogLog, and it is not available everywhere: **SQL Server 2019 (15.x)+** has built-in `APPROX_COUNT_DISTINCT(expr)`, documented as guaranteeing "up to a 2% error rate within a 97% probability" and as being less likely to spill than an exact count. **PostgreSQL has no built-in equivalent** — you install the `postgresql-hll` extension (Citus Data) and use `hll_add_agg()` / `hll_cardinality()`. MySQL has neither. The other reason to reach for a sketch rather than a count: sketches merge, so daily sketches can be combined into a weekly distinct count, which daily *counts* cannot be — but note that only the extension gives you that, because `APPROX_COUNT_DISTINCT` returns a `bigint`, not a storable sketch.
13. **Assuming `WITH RECURSIVE` is portable.** T-SQL has no `RECURSIVE` keyword — the same CTE is written with a plain `WITH`. It is a syntax error, not a behaviour difference, so at least it fails loudly.
14. **A recursive CTE with no ceiling on PostgreSQL.** SQL Server stops at 100 levels by default and MySQL at 1000; PostgreSQL has no limit and will run a cycle until it exhausts disk or memory. Carry a depth counter or use the `CYCLE` clause (14+).
15. **`ROW_NUMBER` in a gaps-and-islands query over data with duplicate keys.** The date-minus-row-number identity only holds with one row per entity per interval. Use `DENSE_RANK`, or de-duplicate first.
16. **`ROWS n PRECEDING` read as "n days".** It is n *rows*. Over a table with missing days the window silently widens in calendar terms. Join a calendar table, or use PostgreSQL's `RANGE ... INTERVAL` frame — which SQL Server does not support.
17. **`NOT IN` against a subquery that can return NULL.** Returns zero rows, always, and looks like a data problem. `NOT EXISTS` instead. Bites hardest in relational-division and anti-join queries.
18. **Writing a SQL Server trigger as if it fires per row.** It fires once per statement with `inserted`/`deleted` as sets. Correct for single-row inserts, wrong for `INSERT ... SELECT`, `MERGE`, and EF Core's batched saves. `SqlBulkCopy` fails the other way: it fires no insert triggers unless you pass `SqlBulkCopyOptions.FireTriggers`, so the counter silently never moves.
19. **Closed intervals for validity periods.** `BETWEEN effective_from AND effective_to` with `effective_to` equal to the next row's `effective_from` matches two rows at the boundary. Store half-open, `[from, to)`, and compare with `>= from AND < to`.
20. **`PIVOT` over a table instead of a projected derived table.** SQL Server's `PIVOT` implicitly groups by every column it can see, so an extra column on the base table fragments the output. Always feed it a derived table containing exactly the grouping, spreading, and aggregated columns.

## Interview-ready summary

- **Find Nth highest:** `DENSE_RANK = N` (handles ties cleanly) or `LIMIT/OFFSET`.
- **Top-N per group:** `ROW_NUMBER() OVER (PARTITION BY group ORDER BY value DESC)` then filter `rn <= N` in CTE.
- **Running totals / moving averages:** `SUM/AVG OVER (ORDER BY ... ROWS BETWEEN ...)`.
- **Gaps & islands:** subtract `ROW_NUMBER` from the date — consecutive values share the same `island_grp`.
- **Median:** `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ...)` or `ROW_NUMBER + COUNT` portable.
- **Pivot:** conditional aggregation (`SUM(CASE WHEN ... THEN ... END)`) is portable; vendor PIVOT operators are concise but tied to dialect.
- **Hierarchical queries:** recursive CTE with anchor + recursive UNION ALL; `ARRAY` for paths; cycle detection for graphs.
- **Self-join pair finding:** `JOIN t1 t2 ON ... AND t1.id < t2.id` for canonical pairs.
- **Stored procs / functions / triggers:** powerful but hidden behavior. Default to app-side logic; use server-side when integrity, perf, or legacy demands.
- **Interval overlap:** `a.start < b.end AND b.start < a.end`, half-open — one predicate, not three cases.
- **Packing intervals:** running `MAX(end)` over all preceding rows — not `LAG(end)` — flags a new island; cumulative `SUM` of the flag is the group key. Sum durations over the packed result, never the raw rows.
- **Ties without a window function:** `TOP (n) WITH TIES` (SQL Server) / `FETCH FIRST n ROWS WITH TIES` (PostgreSQL 13+). No MySQL equivalent.
- **Plan shapes:** window function = scan + sort the whole partition, then filter; APPLY = seek per outer row, no sort, stops at n. Which wins depends on the driving-set size and whether an index supplies the inner ordering.

**Expected interview questions:**

1. *"Find the second-highest salary."* — Show all three: subquery (`MAX < MAX`), `LIMIT 1 OFFSET 1` on `DISTINCT`, `DENSE_RANK = 2`. Mention tie semantics.
2. *"Find top 3 products per category."* — `ROW_NUMBER() OVER (PARTITION BY category ORDER BY sales DESC)` in CTE, filter `rn <= 3`.
3. *"Find consecutive login days per user."* — Gaps and islands: `login_date - ROW_NUMBER * 1 day`, GROUP BY result.
4. *"Find pairs of products often bought together."* — Self-join `order_items` on `order_id` with `p1 < p2` to canonicalize pairs; GROUP BY pair; ORDER BY count DESC.
5. *"Pivot months across columns."* — Conditional aggregation: `SUM(CASE WHEN month = 'Jan' THEN sales END) AS jan, ...`.
6. *"Show org chart with depth."* — Recursive CTE: anchor where `parent_id IS NULL` with depth=0; recursive joins on `parent_id` with depth+1.
7. *"Find duplicate emails."* — `GROUP BY email HAVING COUNT(*) > 1`. To find specific rows: `WHERE email IN (subquery)` or window function `COUNT(*) OVER (PARTITION BY email)`.
8. *"Find double-booked rooms."* — Self-join on `room_id` with `a.starts_at < b.ends_at AND b.starts_at < a.ends_at AND a.id < b.id`. Derive the predicate rather than enumerating cases; the follow-up is always "how do you *prevent* it".
9. *"Total downtime, given overlapping incident records."* — Pack the intervals first (running `MAX(end)` → island flag → `SUM` over the flag → `GROUP BY`), then sum. Summing raw durations double-counts every overlap.
10. *"Which is faster, the window function or `CROSS APPLY`?"* — Describe the two plan shapes, then answer conditionally: APPLY for a small driving set with a supporting index, window function for a full pass. Naming `Segment` / `Sequence Project` / `WindowAgg` is what makes it sound like you have read a plan.
11. *"Your trigger increments a counter. What happens on a bulk insert?"* — On SQL Server, the trigger fires once with a multi-row `inserted` table, and the naive version applies one increment. On PostgreSQL, `FOR EACH ROW` fires per row and is fine; `FOR EACH STATEMENT` has the same problem.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — MERGE / UPSERT race conditions

> **Q**: I use `MERGE INTO target USING source ON target.id = source.id WHEN MATCHED UPDATE ... WHEN NOT MATCHED INSERT ...` for upserts. What's the race condition?
>
> **A**: Two concurrent sessions can both pass the `WHEN NOT MATCHED` check before either commits, then both try to INSERT the same key. Under READ COMMITTED isolation, MERGE doesn't acquire a lock that prevents the second session from seeing "no match" at the moment of its own check. Result: either a primary key violation (one session fails) or duplicate rows (if no unique constraint). The classic race window between the lookup and the insert.
>
> **Cross-Q**: How do you fix it without going to SERIALIZABLE for everything?
>
> **A**: Add `WITH (HOLDLOCK)` to the MERGE target: `MERGE INTO target WITH (HOLDLOCK) USING source ...`. HOLDLOCK takes a range lock that prevents concurrent inserts in the key range until the MERGE commits. The other safe pattern: stop using MERGE and write the upsert as `INSERT ... WHERE NOT EXISTS` inside a `SERIALIZABLE` transaction, or use Postgres's `INSERT ... ON CONFLICT DO UPDATE` which is properly atomic. Many seniors avoid MERGE entirely because it has multiple known footguns beyond just this race (silent NULL handling, trigger ordering surprises).
>
> **Cross-Q²**: Why is `INSERT ... ON CONFLICT DO UPDATE` (Postgres) considered safer than MERGE?
>
> **A**: ON CONFLICT operates at the **index level** — it asks the DB engine "try to insert; if the unique index complains, do this instead." The atomicity is guaranteed by the index's unique constraint, which already serializes concurrent inserts. There's no time window between "check" and "insert" because there's no separate check — the engine atomically attempts the insert and dispatches the conflict path. MERGE's `WHEN NOT MATCHED` is a SQL-level predicate evaluated separately from the insert, which is the source of the race. SQL Server has no `ON CONFLICT` equivalent — there is no upsert syntax there other than `MERGE` — so on SQL Server the choices are `MERGE ... WITH (HOLDLOCK)`, or `INSERT ... WHERE NOT EXISTS` with the same `HOLDLOCK` hint (or under `SERIALIZABLE`) so the check takes a range lock, or simply attempting the `INSERT` and catching error 2627 / 2601 (unique constraint / unique index violation) and falling back to an `UPDATE`. That last one is the closest thing to the index-level semantics and is what most retry-tolerant .NET code ends up doing. Aaron Bertrand's "Use Caution with SQL Server's MERGE Statement" is the standard catalogue of the other footguns.

### Drill 2 — Idempotent inserts

> **Q**: I have a webhook handler that may receive the same event twice. How do I make the insert idempotent at the DB level?
>
> **A**: Unique constraint on the event's natural key (the provider's event ID), then use `INSERT ... ON CONFLICT (event_id) DO NOTHING` (Postgres) or `INSERT ... WHERE NOT EXISTS (SELECT 1 FROM events WHERE event_id = @id)` (SQL Server). The DB enforces uniqueness; duplicate sends silently succeed without inserting. App code can check rows-affected if it needs to know whether this was the first time.
>
> **Cross-Q**: What if the webhook provider doesn't give a stable event ID — they only send timestamp + payload?
>
> **A**: Manufacture one. Hash the payload (`SHA-256` of the canonical JSON) and use that as the deduplication key. The risk: two genuinely different events with identical payloads would collide — usually impossible in practice because timestamps differ, but worth considering. Some teams use `(provider, timestamp_truncated_to_second, hash_of_payload)` as the composite key. The principle: idempotency requires a deduplication key the system can compute deterministically from the input.
>
> **Cross-Q²**: Idempotency at insert is easy. What's the equivalent for updates — making "set status to X" idempotent across retries?
>
> **A**: Two patterns. (1) **State machine guarded transitions** — `UPDATE orders SET status = 'Shipped' WHERE id = @id AND status = 'Paid'`. If a retry runs after the first succeeded, the WHERE filters out the row and rows-affected = 0; the app knows the state already matches. (2) **Version-based optimistic concurrency** — include a `version` or `etag` column; the update specifies `WHERE version = @expected`; retries with a stale version are silently no-ops or fail loudly. The principle is the same as insert idempotency: the operation must be safe to repeat because the DB filters out the no-op case.

### Drill 3 — Pagination: OFFSET vs keyset

> **Q**: What's wrong with `SELECT * FROM orders ORDER BY created_at DESC LIMIT 20 OFFSET 10000`?
>
> **A**: OFFSET is **O(N)** in the offset — the engine still has to compute and discard the first 10000 rows before returning the 20 you want. Page 1 is fast; page 500 is glacial. Worse, results can shift between page requests as new rows arrive at the top, causing duplicates or missing rows (a row at index 99 moves to index 119 when 20 new rows insert, so page 6 still shows it).
>
> **Cross-Q**: What's keyset (cursor) pagination and how does it fix this?
>
> **A**: Instead of "skip N rows," you say "give me rows after this position." `SELECT * FROM orders WHERE (created_at, id) < (@last_created_at, @last_id) ORDER BY created_at DESC, id DESC LIMIT 20`. The `(created_at, id)` tuple is the cursor; the next request passes the last row's values. The cost is one index descent plus a scan of the rows you actually return, so page 1000 costs the same as page 1 — provided an index leads with `(created_at, id)` in that order. Stable under inserts: new rows at the top don't shift the cursor, so no duplicates.
>
> That row-value comparison is the elegant form, and it is **not portable**. Markus Winand's compatibility survey (*use-the-index-luke.com*) puts PostgreSQL (since 8.4) and Db2 in the "supports row values and uses them for index access" column; **SQL Server has no row-value comparison at all**; MySQL evaluates it correctly but cannot use it as an index access predicate; Oracle parses it but rejects range operators on it (`ORA-01796`). On SQL Server you expand it by hand — `WHERE created_at < @last_created_at OR (created_at = @last_created_at AND id < @last_id)` — which is logically identical and gives the optimizer a harder time, since it now has to recognise that the `OR` describes one contiguous index range. EF Core has no LINQ syntax for row values either ([dotnet/efcore#26822](https://github.com/dotnet/efcore/issues/26822)), so keyset pagination in EF Core is written as the expanded predicate or as raw SQL.
>
> **Cross-Q²**: Keyset is great for "next page," but how do you jump to "page 47" directly?
>
> **A**: You can't, cleanly. That's the trade-off — keyset gives you "next" and "previous" but not random access by page number. If random access matters (admin UIs, search-with-pagination), use a hybrid: OFFSET pagination for the first N pages (where OFFSET is cheap), keyset for "next" beyond that, and disable jumping to arbitrary high pages. Many modern apps just hide page numbers entirely ("Load more" or infinite scroll) and avoid the question. For UIs that need it (older admin tools), accept the OFFSET cost or pre-compute page boundaries in a materialized view.

### Drill 4 — Gaps and islands

> **Q**: Explain the trick behind `login_date - (ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date)) * INTERVAL '1 day'` for finding consecutive-login streaks.
>
> **A**: Consecutive dates differ from their row-number-times-one-day by a constant. For login dates `[May 1, May 2, May 3]`, `ROW_NUMBER` is `[1, 2, 3]`, so `date - row_number * 1day` is `[Apr 30, Apr 30, Apr 30]` — same value across the streak. A gap (May 1, May 2, May 4) breaks it: `[Apr 30, Apr 30, May 1]` — the third row jumps to a new group. GROUP BY that derived value and you get one row per streak with `MIN(date), MAX(date), COUNT(*)`.
>
> **Cross-Q**: What if logins are timestamps (not dates) and a "streak" means logins within 30 minutes of the previous one?
>
> **A**: Change the comparison from "same date" to "previous timestamp within 30 minutes." Use `LAG(login_at) OVER (PARTITION BY user_id ORDER BY login_at)` to get the previous timestamp; flag a new session when the gap exceeds 30 minutes; cumulative sum of those flags becomes the session ID. The pattern: `SUM(CASE WHEN login_at - LAG(login_at) OVER (...) > INTERVAL '30 minutes' THEN 1 ELSE 0 END) OVER (...) AS session_id`. That's sessionization — the same gaps-and-islands shape generalized to any "consecutive within X" predicate.
>
> **Cross-Q²**: What if a user's "streak" has to span exactly business days (weekdays, skipping Saturdays/Sundays)?
>
> **A**: The pure date-minus-row-number trick breaks because consecutive business days (Friday → Monday) have a 3-day calendar gap but should count as consecutive. The fix: introduce a `business_day_number` column or computed value — number of business days since some epoch. Use a calendar table (`dim_date` with `is_business_day`) and run a window function on the business_day_number. Then `business_day_number - ROW_NUMBER` gives constant groups for consecutive business days. Calendar tables earn their keep here — the math gets messy without them.

### Drill 5 — Top-N per group

> **Q**: I need the top 3 best-selling products per category. Walk me through the window-function solution and the LATERAL alternative.
>
> **A**: Window function: `WITH ranked AS (SELECT category, product, sales, ROW_NUMBER() OVER (PARTITION BY category ORDER BY sales DESC) AS rn FROM products) SELECT * FROM ranked WHERE rn <= 3`. The optimizer sorts once per partition, assigns row numbers, and the outer query filters. LATERAL (Postgres) / CROSS APPLY (SQL Server): for each category, run an independent inner query. `SELECT c.id, p.* FROM categories c CROSS JOIN LATERAL (SELECT * FROM products WHERE category_id = c.id ORDER BY sales DESC LIMIT 3) p`.
>
> **Cross-Q**: When does LATERAL beat the window function?
>
> **A**: When (a) the inner ORDER BY has a covering index — each LATERAL call is an index-only top-N scan — and (b) the partition is large but you only need a handful of rows per group. The mechanism, not a multiplier, is the answer: the window function must sort the *entire* partition before it can know which rows are numbered 1, 2, 3, so its work is proportional to the partition size; LATERAL seeks into the index and stops after three entries, so its work is proportional to the number of outer rows times the rows you keep. That gap widens with partition size and closes to nothing when you need most of the rows anyway. Where it inverts: if the index does not supply the inner `ORDER BY`, each LATERAL call sorts the category from scratch — now you are doing the same sort, once per outer row, which is strictly worse than doing it once. Check the plan for a `Sort` on the inner side before claiming the win. See [Reading the plan: window function vs APPLY](#reading-the-plan-window-function-vs-apply).
>
> **Cross-Q²**: ROW_NUMBER, RANK, DENSE_RANK — which one for "top 3 with ties"?
>
> **A**: Depends on what "with ties" means. "Top 3 rows, ties broken arbitrarily" → ROW_NUMBER (exactly 3 rows). "Top 3 ranks, including all ties at each rank" → RANK (could return 4 rows if rank 3 has ties; rank 4 is skipped to rank 5). "Top 3 distinct values, all rows at those values" → DENSE_RANK (could return many rows if there are large ties at each of the three ranks). Always ask the interviewer or PM which is wanted — only `ROW_NUMBER` promises a row count, so if the caller loops over the result and does something per row, the other two can hand it more work than it budgeted for. `TOP (3) WITH TIES` / `FETCH FIRST 3 ROWS WITH TIES` expresses the middle case without a window function.

### Drill 6 — Hierarchy modeling

> **Q**: Adjacency list, materialized path, nested set, closure table — when do you use each?
>
> **A**: **Adjacency list** (`parent_id` column) — simplest, easy to insert/update, queries for ancestors/descendants need recursive CTE. Default choice. **Materialized path** (`'/electronics/laptops/gaming'`) — fast descendant queries via prefix LIKE, expensive renames. Good for read-heavy hierarchies that rarely restructure. **Nested set** (lft/rgt values) — extremely fast "all descendants of X" via range query, but inserts are O(N) (shift rgt values). Academic favorite, painful in practice. **Closure table** — separate table with `(ancestor_id, descendant_id, depth)` for every pair. Fast queries in both directions, but write amplification (N inserts per node added at depth N).
>
> **Cross-Q**: When does adjacency list with recursive CTE become too slow?
>
> **A**: When the hierarchy is deep (10+ levels) and queries traverse the whole tree frequently, or when you need "depth of node X" / "all ancestors" in tight loops. Recursive CTE costs scale with tree size — 1000 nodes × 10 levels = 10k row traversal per query. For org charts up to 5 levels deep and 1000s of employees, it's fine; for category trees in a large catalog (10k categories, 6 levels), profile both adjacency list and closure table. Modern Postgres/SQL Server have optimized recursive CTE execution that handles most realistic hierarchies.
>
> **Cross-Q²**: Closure table sounds ideal — why isn't it the default?
>
> **A**: Write amplification. Inserting a leaf node at depth 5 means inserting 5 closure rows (one for each ancestor). Moving a subtree of 1000 nodes one level up means rewriting 1000 closure entries per ancestor — combinatorial. For read-mostly hierarchies (categories, org chart that rarely reorganizes), closure tables are great. For write-heavy hierarchies (threaded comments, dynamic taxonomies), the write cost dominates. Most teams start with adjacency list and migrate to closure table only when query latency on hierarchy traversal becomes a measured problem.

### Drill 7 — Bitemporal modeling

> **Q**: What's bitemporal modeling and what problem does it solve?
>
> **A**: Two independent time dimensions per row: **valid time** (when the fact is true in the real world — "this employee's salary is $80k from Jan 1 to Mar 31") and **system time** (when the system recorded that fact — "we entered this row on Feb 15 at 3pm"). The combination lets you answer two questions independently: "what was true on date X?" and "what did the system know on date Y?" Critical for finance, insurance, and any domain where retroactive corrections happen.
>
> **Cross-Q**: Give me a scenario where the two times diverge meaningfully.
>
> **A**: Insurance claim filed Feb 15 for an accident on Jan 10. System time of the row is Feb 15; valid time is Jan 10. Three days later (Feb 18), the adjuster discovers an error in the claim — they correct it. The new row has system time Feb 18, valid time still Jan 10 (the accident hasn't changed). A query "what did we believe about the Jan 10 claim, *as of Feb 16*?" returns the original (wrong) value. A query "what's the corrected value?" returns the Feb 18 row. Audit and regulatory reports often need exactly this distinction — "show me what we reported at the time" vs "show me what we currently believe."
>
> **Cross-Q²**: How do you implement bitemporal in SQL?
>
> **A**: Each row has four columns: `valid_from`, `valid_to`, `system_from`, `system_to`. UPDATE becomes "close out the current row (set `system_to = NOW()`) and insert a new row with the change (new `system_from = NOW()`)." Validity ranges manage real-world time. Postgres `tstzrange` + EXCLUDE constraints prevent overlapping valid ranges. SQL Server can use temporal tables for the system-time dimension but you implement valid-time manually. The queries are heavyweight ("rows valid at time X *as we knew them* at time Y"), and tooling is sparse — this is why bitemporal is reserved for domains that *need* it. Most apps live happily on system-versioned-only (temporal tables).

### Drill 8 — Slowly changing dimensions

> **Q**: What are SCD types 1, 2, and 3 in dimensional modeling?
>
> **A**: A dimension table (`dim_customer`) describes entities, and those entities change over time. **SCD Type 1** — overwrite the value, no history (just `UPDATE dim_customer SET region = 'EU' WHERE id = 7`). Fast, simple, no audit. **SCD Type 2** — preserve history by adding a new row with the change; old row gets `valid_to = NOW()`, new row gets `valid_from = NOW()` and a fresh surrogate key. The fact table FK references the version that was valid at fact time. **SCD Type 3** — add a column for the previous value (`region`, `previous_region`). Limited history (one prior value), simple queries, no versioning explosion.
>
> **Cross-Q**: When is SCD Type 2 worth the complexity?
>
> **A**: When historical analysis must reflect the dimension state at fact time — "what region was this customer in when they made this purchase?" If the customer moved from US to EU last year, all their old US purchases should still show "US region" in reports, not "EU region." Type 1 would lose that. Type 2 lets the fact table FK to the right historical version. Necessary for: revenue attribution by region over time, regulatory reporting, anything where "rewriting history" is unacceptable.
>
> **Cross-Q²**: SCD Type 2 explodes the dimension table size. How do you keep it manageable?
>
> **A**: (1) **Only version columns that matter for analysis** — don't bump a new dim row when the customer's email changes; only when their `region`, `segment`, or other analytical attribute changes. (2) **Date-granularity changes** — collapse same-day changes into one row. (3) **Archive old versions** — for facts older than 7 years, you may not need every version; keep current + most-recent-prior. (4) **Hash-based change detection** — only insert a new version if a hash of the analytical columns differs from the current row. SCD Type 2 needs governance about *what* changes deserve a new version, otherwise you accumulate noise.

### Drill 9 — Pivot patterns

> **Q**: I have `sales(month, type, amount)` and need columns `(month, A_total, B_total, C_total)`. Walk me through PIVOT, UNPIVOT, and conditional aggregation.
>
> **A**: **Conditional aggregation** (portable, what I'd write): `SELECT month, SUM(CASE WHEN type='A' THEN amount ELSE 0 END) AS a_total, SUM(CASE WHEN type='B' THEN amount ELSE 0 END) AS b_total FROM sales GROUP BY month`. **SQL Server PIVOT operator** (concise, vendor-specific): `SELECT month, [A], [B], [C] FROM sales PIVOT (SUM(amount) FOR type IN ([A], [B], [C])) p`. **UNPIVOT** does the reverse — wide table to narrow `(month, type, amount)`.
>
> **Cross-Q**: What if the set of `type` values isn't known at query time — "pivot whatever types exist this month"?
>
> **A**: Dynamic pivot. Build the SQL string at runtime: `SELECT @cols = STRING_AGG(QUOTENAME(type), ',') FROM (SELECT DISTINCT type FROM sales) t; EXEC('SELECT month, ' + @cols + ' FROM sales PIVOT (SUM(amount) FOR type IN (' + @cols + ')) p')`. Dynamic SQL is brittle — SQL injection if not careful, plan-cache bloat, hard to test. Many teams instead **pivot in the application layer**: query the long-form data, pivot in C#/Python. The DB returns `(month, type, amount)` rows and the app shapes them into the wide format. Cleaner separation, no dynamic SQL.
>
> **Cross-Q²**: A reporting query needs 50 columns from a pivot over the last 50 weeks of data. Is that a smell?
>
> **A**: Strong smell, usually yes. 50 dynamic columns means the **schema of the result depends on the data**, which makes downstream consumers (BI tools, exports, APIs) fragile — every new week shifts column positions. The senior pattern: keep the data long-form `(week, metric)` in the DB and let the presentation layer (BI tool, frontend) pivot for display. Or pre-compute a materialized view with stable column names (`week_minus_1`, `week_minus_2`, ..., `week_minus_50`) refreshed nightly. Pivot is a presentation transform, not a data-modeling one — push it to the edge.

### Drill 10 — Deduplication

> **Q**: A table has duplicate rows on `(email)` and I need to keep one per email. How do I do it safely?
>
> **A**: `WITH dups AS (SELECT id, ROW_NUMBER() OVER (PARTITION BY email ORDER BY created_at ASC) AS rn FROM customers) DELETE FROM customers WHERE id IN (SELECT id FROM dups WHERE rn > 1)`. ROW_NUMBER over the duplicate key assigns 1, 2, 3, ... within each group; deleting everything with `rn > 1` keeps the oldest. The ORDER BY in the OVER clause controls *which* duplicate survives (oldest, newest, lowest id).
>
> **Cross-Q**: What if the duplicates have slightly different data — same email but different `phone` or `name`?
>
> **A**: Now you have to decide *which* row to keep, or merge fields. Common patterns: (1) keep the row with the most recent activity (`ORDER BY last_login_at DESC`); (2) keep the row with the most filled-in fields (`ORDER BY (CASE WHEN phone IS NULL THEN 0 ELSE 1 END) + (CASE WHEN name IS NULL THEN 0 ELSE 1 END) DESC`); (3) merge: keep one row's ID but UPDATE its fields to take the non-null values across all duplicates before deleting the others. The merge is a data-quality decision that needs PM/business input — not a pure technical choice. Document the rule.
>
> **Cross-Q²**: I deduped, but the table will keep getting duplicates inserted because the app doesn't check. How do I prevent future duplicates?
>
> **A**: Add a unique constraint: `ALTER TABLE customers ADD CONSTRAINT uq_email UNIQUE (email)`. This will fail if duplicates still exist — that's why dedup comes first. Once added, every INSERT/UPDATE that would create a duplicate gets a constraint violation, forcing the app to handle it (UPSERT, error message, "use existing account"). Without the DB-level constraint, app-level deduplication is racy — two concurrent inserts both pass the "does this email exist?" check before either commits. The DB is the only place that can serialize this safely. Unique constraint + ON CONFLICT is the durable answer.

### Drill 11 — Star vs snowflake schemas

> **Q**: What's the difference between star and snowflake schema, and when do you choose each?
>
> **A**: **Star** — central fact table FKs to dimension tables; dimensions are flat (no further normalization). `dim_product` has product_id, name, category, sub_category all in one row. Joins are fast (one hop per dimension), denormalization is intentional. **Snowflake** — dimensions are normalized further. `dim_product → dim_category → dim_department`. Saves storage if categories are highly repeated; adds more joins per query.
>
> **Cross-Q**: Modern columnar databases compress dimension columns aggressively. Does snowflake still save storage?
>
> **A**: Marginally. Columnar compression on `category` in `dim_product` already reduces "Electronics" repeated 10000 times to near-zero. The argument for snowflake's storage savings is dramatically weaker in modern warehouses (BigQuery, Snowflake, Redshift) than it was in 2005 row-store DBs. What still differs: query speed (snowflake has more joins, slightly slower), maintainability (snowflake has clearer "what is a category vs a product"), and ETL complexity (snowflake needs more upstream pipelines). Most modern data warehouses default to star or denormalized-wide-table designs for the query simplicity.
>
> **Cross-Q²**: When is neither star nor snowflake — when is "one big table" (OBT) the right choice?
>
> **A**: For event streams in modern warehouses (BigQuery, Snowflake), denormalize everything into a single wide table and forget joins. `fact_sales` already has the customer name, region, product name, category, store details — all duplicated per row. Storage is cheap with columnar compression; query simplicity wins. The OBT pattern works because: (1) ETL pipelines handle the denormalization; (2) columnar compression makes the storage explosion modest; (3) BI tools struggle with multi-table joins for ad-hoc users. The trade-off: dimensions changing (SCD) gets messier because every fact row has the dimension data embedded. For slowly-changing dimensions, snapshot the OBT periodically.

### Drill 12 — Fact table grain

> **Q**: What is "grain" in a fact table, and why is choosing it the first decision?
>
> **A**: The **grain** is "what does one row represent?" — one sale, one order line item, one daily snapshot of inventory per warehouse, one heartbeat per minute. The grain determines what the fact table can answer. If grain is "one row per order," you can't answer "what was the most-purchased product?" because product is inside the order — you'd need to join to a finer grain. Grain choice is irreversible; you can roll up (aggregate to coarser grain) but not drill down (split to finer grain) without re-ingesting source data.
>
> **Cross-Q**: For a retail business, what grain do you choose for `fact_sales`?
>
> **A**: Almost always **one row per line item** (one row per `(order, product)` pair). It's the finest grain that has business meaning. From line items you can roll up to per-order, per-day, per-product, per-region — any analytical question. If you start at per-order grain, you've lost product-level analytics forever. The exception: extremely high-volume systems where line items would explode (e-commerce with billions of items/day) might pre-aggregate to per-order-per-product-category as a starting grain, accepting the trade-off.
>
> **Cross-Q²**: What's an additive, semi-additive, and non-additive fact?
>
> **A**: **Additive** — measures you can sum across any dimension (sale_amount, quantity). Most useful, most common. **Semi-additive** — measures you can sum across some dimensions but not all (inventory_balance: sum across stores yes, sum across dates no — you'd be summing the same inventory multiple times). **Non-additive** — measures you can never sum meaningfully (ratios, percentages, prices). Knowing this matters because BI tools default to SUM aggregations; users build dashboards that silently double-count semi-additive facts. The defense: name semi-additive columns clearly (`inventory_snapshot` not `inventory`) and document the aggregation rules.

### Drill 13 — Queue tables and skip-locked

> **Q**: How do you implement a work queue table in SQL where multiple workers pull jobs without stepping on each other?
>
> **A**: `SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED`. The `FOR UPDATE` row-locks the matched row; `SKIP LOCKED` (Postgres 9.5+, SQL Server `READPAST` hint) tells concurrent SELECTs to skip rows already locked rather than block. So worker 1 locks job 1; worker 2's `SELECT ... SKIP LOCKED` skips it and locks job 2; both proceed in parallel. After processing, update `status = 'done'` and commit (releases the lock).
>
> **Cross-Q**: What if a worker crashes mid-job? The row stays locked and no one else picks it up.
>
> **A**: Two fixes. (1) **Visibility timeout** — instead of relying on the transaction lock, set `processing_started_at = NOW()` on pickup and commit. Workers compete via `WHERE status = 'pending' OR (status = 'processing' AND processing_started_at < NOW() - INTERVAL '5 minutes')`. A crashed worker's row becomes pickable again after 5 minutes. (2) **Heartbeat** — workers update `processing_heartbeat = NOW()` periodically; reclaim rows where heartbeat is stale. Pattern (1) is simpler; pattern (2) handles long-running jobs that legitimately take longer than the timeout.
>
> **Cross-Q²**: Why not use a dedicated message broker (RabbitMQ, SQS, Azure Service Bus) instead?
>
> **A**: Often you should. SQL queue tables are great for: (a) keeping jobs in the same transaction as the data they touch, which removes the dual-write problem outright — the job and the row it describes commit or roll back together, and no outbox is needed; (b) low operational overhead, with no extra service to deploy, monitor, and secure; (c) jobs that need rich SQL to schedule ("pick jobs whose dependency is done"). Message brokers win for: throughput beyond what one database's write path can absorb, fan-out to multiple independent consumers, built-in retry and dead-letter semantics, and decoupling producers from consumers who should not share a database. The honest answer in an interview is that the decision is set by (a) — if the job must be atomic with the data change, a queue table starts as the simpler correct design and a broker requires an outbox to match it. Don't quote a throughput number you haven't measured on your own hardware; the number that matters is your write path's, not a benchmark's.
>
> The syntax differs: PostgreSQL 9.5+ and MySQL 8.0+ have `FOR UPDATE SKIP LOCKED`. SQL Server has no `SKIP LOCKED` keyword — the equivalent is the table hint combination `WITH (UPDLOCK, READPAST, ROWLOCK)`: `UPDLOCK` takes an update lock during the `SELECT` so the row cannot change before you write it, `READPAST` skips rows locked by other workers instead of blocking, and `ROWLOCK` asks for row granularity so a lock escalation doesn't make a worker skip a whole page of jobs. Omit `UPDLOCK` and two workers can read the same row; omit `READPAST` and they queue behind each other instead of working in parallel.

### Drill 14 — Event sourcing in SQL

> **Q**: What is event sourcing and how do you implement it in SQL?
>
> **A**: Store the **events** (state changes) as the source of truth, not the current state. `events(event_id, aggregate_id, event_type, payload, occurred_at)`. Current state is derived by replaying events for an aggregate (`SELECT * FROM events WHERE aggregate_id = X ORDER BY occurred_at`). Provides full audit (every change is an event), time travel (replay up to a point), and decoupling (downstream consumers subscribe to events).
>
> **Cross-Q**: Replaying events for every query is slow. How do you avoid that?
>
> **A**: **Snapshots + projections**. Periodically save the aggregate's state (`snapshots(aggregate_id, state_json, up_to_event_id)`) so replay starts from the snapshot, not from event 1. **Projections** are materialized read models — a `current_orders` table that gets updated by an event handler subscribing to order events. Queries hit the projection (fast, denormalized for the use case), and the event log remains the audit trail. The trade-off is eventual consistency: projections might be milliseconds behind the event log.
>
> **Cross-Q²**: Event sourcing sounds powerful — why don't all systems use it?
>
> **A**: Cost. (1) **Schema evolution is hard** — old events have old payloads; you have to version event types and write upcasters to translate v1 events to v2 shapes. (2) **Storage grows unboundedly** — events are never deleted; archiving old events is complex because replay needs all of them. (3) **Operational complexity** — projections, replay tools, event versioning, snapshot strategies. (4) **Mental load** — every developer has to think in terms of events, not state. Event sourcing is the right call for domains where audit is core (finance, healthcare, compliance-heavy systems) or where the event stream itself is a product (analytics platforms, real-time dashboards). For typical CRUD apps, it's massive overengineering.

### Drill 15 — Change Tracking vs CDC

> **Q**: SQL Server has both Change Tracking and Change Data Capture (CDC). What's the difference?
>
> **A**: **Change Tracking (CT)** records *that* a row changed and the key — but not what the change was. Lightweight, low overhead. Used for sync scenarios where the consumer queries the current row state after notification. **Change Data Capture (CDC)** records *what* changed — the before and after values for every UPDATE, plus INSERTs and DELETEs. Heavier (writes a duplicate of every change to a CDC table) but provides full history. CT is "row 42 changed, go look"; CDC is "row 42 was {x:1} and is now {x:2}".
>
> **Cross-Q**: When do you use which?
>
> **A**: **CT** for sync to a single downstream system that can query current state — caches, search indexes, mobile sync (the client says "give me everything changed since my last sync token," the server responds with current row values). **CDC** when downstream consumers need the change history — replication, audit, event-driven architectures where the CDC stream becomes the event source. CDC is the foundation for Debezium-style change streams that feed Kafka. If you're not sure, CT is cheaper and easier to enable.
>
> **Cross-Q²**: How does CDC compare to trigger-based audit tables?
>
> **A**: CDC is **log-reader based** — it reads the transaction log asynchronously to capture changes, so it doesn't add overhead to the writing transaction. Triggers run synchronously inside the transaction, adding latency proportional to the trigger logic. CDC is the better choice for high-throughput systems; triggers are simpler to set up and easier to understand (they're SQL you write yourself). The other difference: CDC handles bulk operations (TRUNCATE doesn't fire row triggers; CDC captures them via the log). Modern preference for streaming/replication: CDC. For domain-specific audit columns with custom logic: triggers (or app-level interceptors, even cleaner).

</details>

## Cheat Sheet

- **Nth highest**: `DENSE_RANK = N` for distinct values; `LIMIT/OFFSET` for raw rows.
- **Top-N per group**: ROW_NUMBER partitioned + filter in CTE; `LATERAL`/`CROSS APPLY` as alternative.
- **Running total**: `SUM(x) OVER (PARTITION BY g ORDER BY t)`; one pass, no self-join.
- **Moving average**: `AVG(x) OVER (ORDER BY t ROWS BETWEEN N PRECEDING AND CURRENT)` for fixed window.
- **Gaps and islands**: subtract `ROW_NUMBER * step` from the date; constant value = consecutive run.
- **Median**: `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x)`; portable: ROW_NUMBER + COUNT trick.
- **Pivot**: conditional aggregation (`SUM(CASE WHEN ...)`); portable across dialects.
- **Pair finding**: self-join with `t1.id < t2.id` to canonicalise; `LEAST/GREATEST` to dedupe.
- **Hierarchy**: recursive CTE with array path for cycle detection.
- **Stored procs / triggers**: hidden behaviour; document or move to app code unless integrity demands DB enforcement. On SQL Server every trigger is statement-level — write against `inserted` as a set.
- **Interval overlap**: `a.start < b.end AND b.start < a.end`, half-open. **Packing**: running `MAX(end)` over preceding rows → island flag → cumulative `SUM` → `GROUP BY`.
- **Ties**: `TOP (n) WITH TIES` (SQL Server) / `FETCH FIRST n ROWS WITH TIES` (PostgreSQL 13+). Only `ROW_NUMBER` promises a row count.
- **Recursion guards**: SQL Server `MAXRECURSION` default 100; MySQL `cte_max_recursion_depth` default 1000; PostgreSQL none — add a depth column or the `CYCLE` clause (14+).
- **Plan shapes**: window function = `Sort` + `Segment` + `Sequence Project` + `Filter` over the whole partition; APPLY = `Nested Loops` + `Index Seek` + `Top`, no sort, stops at n.

## Walkthrough — Top-3 orders per customer blowing up the app tier

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A backend service builds "customer summary" pages by issuing `SELECT TOP 3 ...` per customer in a loop. For 5000 customers per page, that's 5000 round trips. The endpoint is the slowest in the service and queue depth on the DB connection pool spikes whenever it's called.

**Diagnosis**: Senior runs `pg_stat_statements` and sees the same parametrised query executed 5000+ times per request — high `calls`, low `mean_exec_time`, and a `total_exec_time` near the top of the table, which is the signature of an N+1 rather than a slow query. Application traces (`dotnet-trace collect --providers Microsoft-Diagnostics-DiagnosticSource`) confirm it's the `foreach (var c in customers) { db.Orders.Where(o => o.CustomerId == c.Id).OrderByDescending(o => o.CreatedAt).Take(3).ToList(); }` loop. Each query is individually fast; the cost is 5000 round trips of network and command overhead that no amount of index tuning will remove.

**Fix**: Replace the loop with one query using `ROW_NUMBER() OVER (PARTITION BY ...)`:

```sql
WITH ranked AS (
    SELECT o.id, o.customer_id, o.created_at, o.total,
           ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.created_at DESC) AS rn
    FROM orders o
    WHERE o.customer_id = ANY(@customerIds)
)
SELECT id, customer_id, created_at, total
FROM ranked
WHERE rn <= 3;
```

**From EF Core**: there is no LINQ translation for `OVER`. The tracking issue [dotnet/efcore#12747 "Support SQL window functions"](https://github.com/dotnet/efcore/issues/12747) is still open, and `EF.Functions` exposes no `RowNumber` or `Partition` methods — anything you may have seen that looks like `EF.Functions.RowNumber(...)` does not exist in EF Core. Two documented ways to keep the single round trip:

```csharp
// Map a keyless type for the result shape:
//   modelBuilder.Entity<CustomerOrderRow>().HasNoKey().ToView(null);

var customerIds = customers.Select(c => c.Id).ToArray();

var topPerCustomer = await db.Set<CustomerOrderRow>()
    .FromSql($"""
        WITH ranked AS (
            SELECT o.id, o.customer_id, o.created_at, o.total,
                   ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.created_at DESC) AS rn
            FROM orders o
            WHERE o.customer_id = ANY({customerIds})
        )
        SELECT id, customer_id, created_at, total FROM ranked WHERE rn <= 3
        """)
    .ToListAsync();
```

`FromSql` takes a `FormattableString`, and the docs are explicit that this is not string interpolation in the dangerous sense: "the supplied value is wrapped in a `DbParameter` and the generated parameter name inserted where the `{0}` placeholder was specified. This makes `FromSql` safe from SQL injection attacks." `FromSqlRaw` is the one that concatenates, and its documentation carries the corresponding warning — reach for it only when you are building the SQL text yourself, and then the sanitising is yours to do.

The alternative, if the shape is stable, is a database view containing the window function, mapped with `ToView(...)` and queried with LINQ like any other entity. That keeps the window function in the database, where EF Core cannot translate it, and keeps the call site in C# where the rest of the query composition lives.

**Why it works**: one statement means one round trip, and the window function lets the engine compute "top-3-per-group" in a single pass over the partition keys instead of 5000 separate plans, parses, and network waits. The DB does what it's optimised for; the app stops paying per-customer latency.

**What to check afterwards**: this trades N round trips for one sort over every order belonging to those 5000 customers. If the customer list is small — a single customer's detail screen — the `CROSS APPLY` form against an index on `(customer_id, created_at DESC)` is the better plan, for the reasons in [Reading the plan](#reading-the-plan-window-function-vs-apply). Fixing an N+1 by moving to a window function is right here because the driving set is large; it is not automatically right.

</details>

## Self-test

<details><summary>1. <code>RANK()</code> returns 1, 1, 3 on a 3-row tie. <code>DENSE_RANK()</code> returns 1, 1, 2. Which would you use to find "the third unique highest salary"?</summary>

DENSE_RANK. It compresses ties so the third unique value gets rank 3, regardless of how many shared earlier ranks. RANK would assign rank 4 or higher if the first two had ties, missing the third unique value.
</details>

<details><summary>2. Trade-off: <code>PERCENTILE_CONT(0.5)</code> vs the row_number/count median trick.</summary>

`PERCENTILE_CONT` is portable across modern engines and concise but does an internal sort over the whole partition - expensive for huge groups. The ROW_NUMBER trick is also a sort but lets you build it on top of pre-aggregated data and works on older engines (SQL Server before 2012, MySQL before 8). For approximate medians on streams, t-digest or histograms beat both.
</details>

<details><summary>3. A junior writes <code>SELECT customer_id, MAX(SUM(total)) FROM orders GROUP BY customer_id</code>. Why does it error?</summary>

You can't nest aggregates without an intermediate aggregation. The inner SUM is evaluated, but MAX needs a separate row set to operate on. Wrap in a CTE: `WITH per_customer AS (SELECT customer_id, SUM(total) AS s FROM orders GROUP BY customer_id) SELECT MAX(s) FROM per_customer`.
</details>

<details><summary>4. <code>self-join orders ON o1.product_id = o2.product_id AND o1.order_id != o2.order_id</code> for "products bought by multiple customers" - what's the bug?</summary>

The predicate `!=` allows both `(A, B)` and `(B, A)` pairs and pairs the same row with every other row at scale. Use `o1.order_id < o2.order_id` to get unique pairs and reduce comparisons by half. For "find pairs", LEAST/GREATEST canonicalises after the join.
</details>

<details><summary>5. When would you reach for <code>LATERAL</code> instead of <code>ROW_NUMBER + filter</code> for top-N per group?</summary>

When the inner query needs different LIMIT per outer row, when you can use a covering index for the inner ORDER BY (so each lateral subquery is an index-only scan), or when the partition is huge and you don't want to sort the full set. LATERAL fires once per outer row, so it pays off only when each call is fast.
</details>

<details><summary>6. Two intervals, <code>a</code> and <code>b</code>. Write the overlap predicate in one line, and say what changes if the intervals are closed rather than half-open.</summary>

`a.starts_at < b.ends_at AND b.starts_at < a.ends_at`. It's the negation of "one ends before the other starts", which is why one predicate covers partial overlap in both directions and full containment. With closed intervals you need `<=` on both comparisons, and then two intervals that merely touch (one ends exactly where the next begins) count as overlapping — which is why validity periods should be stored half-open, `[from, to)`.
</details>

<details><summary>7. This gaps-and-islands query is correct in test and wrong in production: <code>login_date - (ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date))</code>. What's in production that isn't in the fixtures?</summary>

More than one login per user per day. The identity "date advances by one, row number advances by one" breaks when two rows share a date: the second gets a higher row number, so its computed group value lands a day earlier and looks like a new island, splitting the streak. Fix with `DENSE_RANK()` (same value for same date) or by de-duplicating to one row per user per day first. Same reasoning for the integer variant over a column with duplicates.
</details>

<details><summary>8. Your median-per-department query runs on PostgreSQL and fails to compile on SQL Server. Why, and what's the T-SQL?</summary>

In PostgreSQL `PERCENTILE_CONT` is an ordered-set aggregate, so `... WITHIN GROUP (ORDER BY salary) ... GROUP BY department` is valid. In T-SQL it is an analytic function whose documented syntax requires `OVER ( [ <partition_by_clause> ] )`; `GROUP BY` is not accepted. The T-SQL is `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) OVER (PARTITION BY department)`, and because a window function doesn't collapse rows you need `SELECT DISTINCT` (or a CTE plus a join, which is cheaper) to get one row per department. MySQL has neither function.
</details>

<details><summary>9. To pack overlapping intervals you compare each row's start against the previous rows' ends. Why a running <code>MAX(end)</code> rather than <code>LAG(end)</code>?</summary>

Because `LAG` only sees the immediately preceding row. Order by `starts_at` and a long interval can be followed by a short one that it completely contains; the short one's `ends_at` is earlier, so `LAG` reports no overlap and the group is split even though the rows overlap. `MAX(ends_at)` over *all* preceding rows in the partition remembers the furthest end reached so far, which is the actual boundary of the island. Use an explicit `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING` frame — the default frame with `ORDER BY` includes the current row, so the running maximum would include the row's own `ends_at`, the new-island test could never fire, and everything would merge into one island.
</details>

<details><summary>10. A SQL Server trigger keeps a running count and is correct in every test. EF Core saves two new entities in one <code>SaveChangesAsync</code> and the count goes wrong by one. Explain.</summary>

T-SQL triggers are statement-level — there is no `FOR EACH ROW` clause — and fire once per statement with `inserted`/`deleted` holding *all* affected rows. EF Core batches the two inserts into one multi-row `INSERT`, so the trigger fires once, and a trigger written as `SET count = count + 1 FROM inserted` applies a single increment for the whole batch. The fix is set-based: aggregate `inserted` (`GROUP BY` the key, `COUNT(*)`) and add that. PostgreSQL's `FOR EACH ROW` triggers don't have this problem; its `FOR EACH STATEMENT` ones do.
</details>

## Cross-references

- [Window Functions](./05-window-functions.md) — the engine of most patterns here.
- [Subqueries & CTEs](./04-subqueries-and-ctes.md) — recursive CTEs for hierarchies.
- [Joins & Set Operations](./02-joins-and-set-operations.md) — self-joins.
- [Aggregation & Grouping](./03-aggregation-and-grouping.md) — conditional aggregation, GROUP BY.
- [MS SQL Server](../04-mssql-server.md) — vendor-specific features (PIVOT operator, T-SQL).
- [Coding Practice](../../08-craft-and-interview-prep/02-coding-practice.md) — sibling chapter for algorithmic problems.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *SQL Cookbook* by Anthony Molinaro (O'Reilly, 2nd ed.) — covers most of these patterns with portable examples.
- *T-SQL Querying* by Itzik Ben-Gan — gaps and islands, advanced window functions.
- *SQL Antipatterns* by Bill Karwin — recognizes common mistakes, suggests refactors.
- LeetCode — [SQL Hard problems](https://leetcode.com/problemset/database/?difficulty=Hard) — the interview drill ground.
- *Joe Celko's SQL Puzzles and Answers* — classic puzzles with clever SQL.
- *Joe Celko's Trees and Hierarchies in SQL for Smarties* — adjacency list, materialized path, nested set.

Primary sources for the engine-specific claims on this page:

- Microsoft Learn — [WITH common_table_expression (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/with-common-table-expression-transact-sql) — `MAXRECURSION` server-wide default of 100, the 0–32767 range, and "`UNION ALL` is the only set operator allowed between the last anchor member and first recursive member".
- Microsoft Learn — [PERCENTILE_CONT (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/functions/percentile-cont-transact-sql) — the mandatory `OVER` clause, and `_CONT` interpolating versus `_DISC` returning "an actual value from the set".
- Microsoft Learn — [GREATEST (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/functions/logical-functions-greatest-transact-sql) — SQL Server 2022 (16.x) and later; NULL arguments ignored unless all are NULL.
- Microsoft Learn — [APPROX_COUNT_DISTINCT (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/functions/approx-count-distinct-transact-sql) — SQL Server 2019 (15.x)+; "guarantees up to a 2% error rate within a 97% probability".
- Microsoft Learn — [Scalar UDF Inlining](https://learn.microsoft.com/en-us/sql/relational-databases/user-defined-functions/scalar-udf-inlining) — the four named causes of scalar UDF slowness, compatibility level 150, and `sys.sql_modules.is_inlineable`.
- Microsoft Learn — [Create DML Triggers to Handle Multiple Rows of Data](https://learn.microsoft.com/en-us/sql/relational-databases/triggers/create-dml-triggers-to-handle-multiple-rows-of-data) — the single-row versus multi-row trigger example this page's trigger section is built on.
- Microsoft Learn — [SqlBulkCopyOptions Enum](https://learn.microsoft.com/en-us/dotnet/api/system.data.sqlclient.sqlbulkcopyoptions) — `FireTriggers` is opt-in; the default fires no insert triggers.
- Paul White — [Properly Persisted Computed Columns](https://sqlperformance.com/2017/05/sql-plan/properly-persisted-computed-columns) — why a scalar UDF in a computed-column definition disables parallelism for the whole query even when the column is `PERSISTED` and unreferenced.
- PostgreSQL docs — [WITH Queries](https://www.postgresql.org/docs/current/queries-with.html) (`SEARCH`/`CYCLE`, and why `UNION` alone is not a cycle guard) and the [PostgreSQL 14 release notes](https://www.postgresql.org/docs/release/14.0/) for when those clauses arrived; the [13.0 release notes](https://www.postgresql.org/docs/release/13.0/) for `FETCH FIRST ... WITH TIES`.
- PostgreSQL docs — [Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html) and [btree_gist](https://www.postgresql.org/docs/current/btree-gist.html) — exclusion constraints and why mixing `=` with `&&` needs the extension.
- MySQL docs — [Comparison Functions and Operators](https://dev.mysql.com/doc/refman/8.4/en/comparison-operators.html) (`GREATEST()` returns NULL if any argument is NULL) and [WITH (Common Table Expressions)](https://dev.mysql.com/doc/refman/8.4/en/with.html) (`cte_max_recursion_depth`, default 1000).
- Markus Winand — [use-the-index-luke.com, "Fetch Next Page"](https://use-the-index-luke.com/sql/partial-results/fetch-next-page) — the row-value-comparison compatibility survey behind the keyset-pagination caveat.
- Microsoft Learn — [SQL Queries (EF Core)](https://learn.microsoft.com/en-us/ef/core/querying/sql-queries) — `FromSql` parameterisation versus `FromSqlRaw`; and [dotnet/efcore#12747](https://github.com/dotnet/efcore/issues/12747) for the absent window-function translation.

<!-- nav-footer-start -->

---

[← Previous: Schema Design & Normalization](08-schema-design-and-normalization.md) · [↑ Back to top](#advanced-patterns--interview-problems) · [Next: MS SQL Server →](../04-mssql-server.md)

<!-- nav-footer-end -->

</details>
