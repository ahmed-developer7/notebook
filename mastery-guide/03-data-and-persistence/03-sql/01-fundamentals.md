# SQL Fundamentals

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › [SQL Mastery](./README.md)

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-08-11 |

## Contents
- [Why it matters](#why-it-matters)
- [Core concepts](#core-concepts)
  - [The five SQL sublanguages](#the-five-sql-sublanguages)
  - [Data types](#data-types)
  - [Constraints](#constraints)
  - [SELECT — the workhorse](#select--the-workhorse)
  - [INSERT / UPDATE / DELETE](#insert--update--delete)
  - [Filtering with WHERE](#filtering-with-where)
  - [Sorting and limiting](#sorting-and-limiting)
  - [DISTINCT](#distinct)
  - [NULL semantics](#null-semantics)
  - [Implicit conversion — the index that stops being used](#implicit-conversion--the-index-that-stops-being-used)
  - [Set-based thinking](#set-based-thinking)
  - [TRUNCATE vs DELETE vs DROP](#truncate-vs-delete-vs-drop)
- [Code & diagrams](#code--diagrams)
- [Common pitfalls](#common-pitfalls)
- [Interview-ready summary](#interview-ready-summary)
- [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
- [Cheat Sheet](#cheat-sheet)
- [Walkthrough](#walkthrough--an-update-without-where-in-production)
- [Self-test](#self-test)
- [Cross-references](#cross-references)
- [Sources](#sources)

---

## Why it matters

SQL is the *lingua franca* of relational data — born in 1974, standardized through 12+ ANSI/ISO revisions, still the way most production systems persist business state in 2026. Every senior backend engineer needs to read and write SQL fluently, regardless of how much ORMs hide. The moment you debug a slow query, design a reporting view, or pluck data out of an unfamiliar database, you're in SQL territory.

This file covers the foundational vocabulary: the five sublanguages (DDL, DML, DCL, TCL, DQL), data types and constraints, the four CRUD verbs, and the basic clauses (`WHERE`, `ORDER BY`, `LIMIT`). Everything else in this sub-chapter builds on this surface.

When NOT to memorize: vendor-specific dialect details (T-SQL's `TOP` vs PostgreSQL's `LIMIT`). Get the standard SQL shape right; look up dialect specifics. Most interview questions accept either dialect as long as logic is correct.

## Core concepts

### The five SQL sublanguages

SQL is informally divided into five sublanguages by purpose. You'll see these terms in interviews and documentation.

| Sublanguage | Purpose | Statements |
|---|---|---|
| **DDL** (Data Definition) | Define schema | `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `RENAME` |
| **DML** (Data Manipulation) | Modify rows | `INSERT`, `UPDATE`, `DELETE`, `MERGE` |
| **DQL** (Data Query) | Read rows | `SELECT` |
| **DCL** (Data Control) | Permissions | `GRANT`, `REVOKE` |
| **TCL** (Transaction Control) | Transaction boundaries | `BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT` |

In practice, you'll use DML and DQL daily, DDL during migrations, TCL when you need atomicity, DCL rarely (DBAs handle it). Knowing the names matters in interviews because they signal "this engineer has actually studied SQL, not just copied snippets."

The line that matters operationally is where DDL and TCL meet: whether a schema change can be rolled back. PostgreSQL and SQL Server run most DDL inside a transaction; MySQL and Oracle commit implicitly at each DDL statement. See [Drill 1](#drill-1--ddl-vs-dml-vs-dcl-vs-tcl).

> 🌍 **In the real world**: a release adds a column, backfills it and creates an index as three statements in one migration script. On PostgreSQL that script runs as one transaction, so a timeout on the third statement leaves the database exactly as it started and "re-run the migration" is a safe instruction. The same script on MySQL commits at every DDL boundary — a timeout mid-backfill leaves the column added, some rows populated, no index, and a migration-history row that already says this version was applied. The lesson is not "write a better script": it is that on MySQL every migration step has to be individually re-runnable, because the engine will not undo the earlier ones for you.

### Data types

The big four categories, with .NET-mapping notes:

**Numeric:**
- `INT` / `INTEGER` — 32-bit signed (~ ±2.1 billion). Most common for IDs.
- `BIGINT` — 64-bit signed (~ ±9 quintillion). For counts that might exceed 2B, or for high-cardinality IDs.
- `SMALLINT` — 16-bit (~ ±32k).
- `DECIMAL(p, s)` / `NUMERIC(p, s)` — fixed-point with `p` total digits, `s` after the decimal. Use for money: `DECIMAL(18, 2)` is the standard.
- `FLOAT` / `REAL` / `DOUBLE PRECISION` — IEEE-754. **Avoid for money** (rounding errors); fine for scientific.

**String:**
- `VARCHAR(n)` — variable-length, max `n` characters. Use a sensible cap (`VARCHAR(255)`, `VARCHAR(1000)`).
- `CHAR(n)` — fixed-length, padded with spaces. Rarely the right choice; use `VARCHAR`.
- `TEXT` / `VARCHAR(MAX)` — unbounded. For large free-form content (descriptions, JSON blobs).
- `NVARCHAR(n)` (SQL Server) — Unicode (UTF-16). Always use for any user-facing text. PostgreSQL's `VARCHAR` is Unicode by default.

**Date/Time:**
- `DATE` — date only (no time). YYYY-MM-DD.
- `TIME` — time only (no date).
- `DATETIME` / `TIMESTAMP` — date + time. Behavior on time zones varies by vendor.
- `TIMESTAMPTZ` (PostgreSQL) / `DATETIMEOFFSET` (SQL Server) — with time-zone information. **Use this for events that cross time zones**.

**Boolean and other:**
- `BOOLEAN` — TRUE/FALSE/NULL (PostgreSQL). SQL Server uses `BIT`.
- `UUID` (PostgreSQL) / `UNIQUEIDENTIFIER` (SQL Server) — 128-bit GUID.
- `JSON` / `JSONB` (PostgreSQL) — JSON document.
- `BYTEA` / `VARBINARY` — binary data.

Picking right:
- IDs: `INT` for most apps; `BIGINT` if you'll exceed 2B rows; `UUID` for cross-server uniqueness or client-generated IDs.
- Money: `DECIMAL(18, 2)` (or `NUMERIC(18, 2)`).
- Timestamps: always store as UTC in `TIMESTAMP`/`DATETIMEOFFSET` with TZ info; convert to user's TZ at the edge.
- Free text: `VARCHAR(255)` for short, `TEXT` for long.

Two type choices bite later rather than immediately, so decide them deliberately now:

- **`FLOAT` for money.** Binary floating point cannot represent most decimal fractions exactly, and floating-point addition is not associative — so a `SUM` over the same rows can differ depending on the order they are added, which changes when the optimizer switches to a parallel aggregate. The report disagrees with itself between runs and nothing is corrupt.
- **The .NET type on the other end.** `DECIMAL`/`NUMERIC` maps to `decimal`, `FLOAT`/`DOUBLE PRECISION` to `double`, `REAL` to `float` — a `decimal` property over a `float` column silently rounds on the way through. Check the mapping, not just the column.

> 🌍 **In the real world**: an invoicing service stores line totals as `FLOAT` because someone wanted "fast maths", and for years the only symptom is that the monthly revenue report and the accounting export disagree by a rounding-shaped amount that nobody can attribute to a specific invoice. The migration to `DECIMAL(18, 2)` had to be scheduled with finance, because converting the stored values changes a small number of historical invoice totals — restating figures that have already been sent to customers. This is why the type is chosen on day one: the cost of the wrong one is not the migration, it is that the wrong values are already in other people's spreadsheets.

**Integer arithmetic stays integer, and that is where a report loses its decimals.** Dividing one integer by another is not the same operation in every engine:

| Engine | Integer ÷ integer | Documented as |
|---|---|---|
| **SQL Server** | Truncated to an integer | "If an integer *dividend* is divided by an integer *divisor*, the result is an integer that has any fractional part of the result truncated" (Microsoft Learn, */ (Division)*) |
| **PostgreSQL** | Truncated toward zero | The operator table reads "Division (for integral types, division truncates the result towards zero)" and lists `5 / 2` → `2`, `5.0 / 2` → `2.5000000000000000` |
| **MySQL** | Fractional | `/` produces a fractional result — the manual's own example is `SELECT 3/5` → `0.60`. Integer division is the separate `DIV` operator: `5 DIV 2` → `2` |

SQL Server applies the same rule to aggregates. Its `AVG` return-type table maps `tinyint`, `smallint` and `int` all to `int`, so an average over an `int` column comes back whole — the documentation's own worked example prints `25` for average vacation hours. Both cases have the same fix: widen an operand *before* the arithmetic, not after. `SUM(paid) * 1.0 / COUNT(*)` or `CAST(a AS DECIMAL(18,4)) / b` works; `CAST(a / b AS DECIMAL(18,4))` does not, because the truncation already happened inside the parentheses.

> 🌍 **In the real world**: a conversion-rate tile on an internal dashboard reads 0% for every acquisition channel except one, which reads 1%. The query is `CAST(converted / visits AS DECIMAL(5,2))` over two `int` columns on SQL Server: integer division discards the fraction before the cast ever runs, so any rate below 100% collapses to zero. It went unquestioned for months because "0%" on a new channel reads as a tracking problem, not an arithmetic one — and the single channel showing 1% was the only evidence the pipeline worked at all. `converted * 1.0 / visits` fixed every tile in one edit.

### Constraints

Constraints enforce data integrity at the database level — the last line of defense, after application validation.

```sql
CREATE TABLE customers (
    id          INT PRIMARY KEY,                                    -- ✱ PK = unique + not null
    email       VARCHAR(254) NOT NULL UNIQUE,                       -- ✱ uniqueness
    name        VARCHAR(200) NOT NULL,                              -- ✱ not null
    age         INT CHECK (age >= 0 AND age <= 150),                -- ✱ range
    country     CHAR(2) NOT NULL DEFAULT 'US',                      -- ✱ default
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id            INT PRIMARY KEY,
    customer_id   INT NOT NULL,
    total         DECIMAL(18, 2) NOT NULL CHECK (total >= 0),
    status        VARCHAR(20) NOT NULL CHECK (status IN ('Pending', 'Paid', 'Shipped', 'Cancelled')),
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
```

**Six common constraints:**
- **`PRIMARY KEY`** — unique + not null + indexed. Each table should have exactly one.
- **`FOREIGN KEY`** — references another table's primary key. Enforces referential integrity. `ON DELETE CASCADE`/`SET NULL`/`RESTRICT` controls cascade behavior.
- **`UNIQUE`** — values must be unique. NULL handling differs by engine (below).
- **`NOT NULL`** — value required.
- **`CHECK (expression)`** — arbitrary boolean predicate per row.
- **`DEFAULT value`** — used when INSERT omits the column.

Always declare constraints. Application code is *not* a substitute — DB constraints catch bugs that app code missed, prevent corruption from manual SQL fixes, and remain even when an engineer bypasses the API.

**Four things about constraints that only show up in production.**

**1. A `CHECK` rejects FALSE, not "not TRUE".** Constraints live in the same three-valued logic as `WHERE`, but with the opposite default. Microsoft Learn is blunt about it: "CHECK constraints reject values that evaluate to `FALSE`. Because null values evaluate to UNKNOWN, their presence in expressions might override a constraint." PostgreSQL says the same: "a check constraint is satisfied if the check expression evaluates to true or the null value." So in the DDL above, `age INT CHECK (age >= 0 AND age <= 150)` accepts `NULL` happily — the column is nullable and the predicate is UNKNOWN, which is not FALSE. If you mean "a value, and it must be in range", you need both `NOT NULL` and the `CHECK`.

> 🌍 **In the real world**: a `discount_percent` column carries `CHECK (discount_percent BETWEEN 0 AND 100)` and the pricing service still finds rows it has to treat as "no discount" for customers who were promised one. The constraint is behaving exactly as specified — a bulk import left the field empty, NULL made the predicate UNKNOWN, and every one of those rows was waved through. The team had read the `CHECK` as "this column is always a valid percentage" when it actually says "this column is never an invalid percentage", and the gap between those two sentences is the whole bug.

**2. `UNIQUE` and NULL are not the same everywhere.** The standard treats two NULLs as distinct for uniqueness, so several NULLs should be allowed:

| Engine | NULLs in a `UNIQUE` column |
|---|---|
| **SQL Server** | Only **one** NULL — "as with any value participating in a `UNIQUE` constraint, only one null value is allowed per column" (Microsoft Learn). |
| **PostgreSQL** | **Many** NULLs. PostgreSQL 15+ can opt in to the SQL Server behaviour with `UNIQUE NULLS NOT DISTINCT`. |
| **MySQL (InnoDB)** | **Many** NULLs. |

This bites on soft delete: `UNIQUE (email)` plus a `deleted_at` column means a deleted user's address is blocked forever. The portable fix is a unique index that only covers live rows — a *partial* index in PostgreSQL, a *filtered* index in SQL Server, same syntax in both:

```sql
CREATE UNIQUE INDEX ux_customers_email_live
    ON customers (email)
    WHERE deleted_at IS NULL;      -- PostgreSQL and SQL Server; MySQL has no equivalent
```

MySQL has no filtered index, so the usual workaround there is to fold the deletion marker into the key (`UNIQUE (email, deleted_at)` with a sentinel, not NULL) — which is exactly the "sentinel vs NULL" trade-off from [NULL semantics](#null-semantics).

**3. A `FOREIGN KEY` does not create an index on the child column** — except in MySQL. The constraint indexes nothing on the referencing side in SQL Server, PostgreSQL or Oracle; the *referenced* side is already indexed because it is a PK or UNIQUE. MySQL is the exception and documents it: "In the referencing table, there must be an index where the foreign key columns are listed as the first columns in the same order. Such an index is created on the referencing table automatically if it does not exist" (MySQL 8.4 manual). Everywhere else, you add that index yourself, and the symptom of not doing so is deletes and updates of parent rows scanning the child table.

> 🌍 **In the real world**: deleting one customer from an admin screen takes minutes and blocks the orders table while it runs. The FK on `orders.customer_id` is doing its job — before the parent row can go, the engine has to prove no child row references it, and with no index on `customer_id` proving that means reading every order. It had been fine for years because the orders table used to be small, and it stayed unnoticed because the schema diagram draws the FK as a line between two tables and gives no hint about which side is indexed. One index on the child column turned it back into a seek.

**4. A constraint can exist and still guarantee nothing about the rows already in the table.** Adding a constraint to a populated table means scanning that table, and holding it while you do. Every engine therefore offers a way to skip the scan — and skipping it records the constraint as *unverified*, which is a weaker thing than it looks in the schema.

| Engine | Skip the scan | What is recorded |
|---|---|---|
| **SQL Server** | `ALTER TABLE t WITH NOCHECK ADD CONSTRAINT ...` | `is_not_trusted = 1` in `sys.check_constraints` ("CHECK constraint has not been verified by the system for all rows") and in `sys.foreign_keys` ("FOREIGN KEY constraint has not been verified by the system"). Cleared by `ALTER TABLE t WITH CHECK CHECK CONSTRAINT ALL`. |
| **PostgreSQL** | `ALTER TABLE t ADD CONSTRAINT ... NOT VALID` | `pg_constraint.convalidated = false`. Cleared by `VALIDATE CONSTRAINT`. |

PostgreSQL states the trade-off it is making: "With `NOT VALID`, the `ADD CONSTRAINT` command does not scan the table and can be committed immediately", and the later `VALIDATE CONSTRAINT` "acquires only a `SHARE UPDATE EXCLUSIVE` lock on the table being altered" — so the scan happens without blocking writers. That two-step is the standard online way to add a constraint to a large table, and it is meant to be finished.

Both engines enforce the constraint on new rows either way. What differs is what the engine will *believe*. On SQL Server that belief is also a query-plan input: "The query optimizer doesn't consider constraints that are defined `WITH NOCHECK`" (Microsoft Learn, *ALTER TABLE*).

> 🌍 **In the real world**: a `CHECK (total >= 0)` is added to `orders` with `WITH NOCHECK` because validating it against the full table would have overrun the release window, with a ticket to validate it "next sprint". A year later a reconciliation job finds negative totals and the first theory is that the constraint is broken. It isn't — it has only ever been applied to rows written since it was added, and `is_not_trusted` had been 1 the whole time. The team had been reading the constraint as a statement about the table when it was only a statement about future writes. `ALTER TABLE orders WITH CHECK CHECK CONSTRAINT ALL` is what converts one into the other, and it fails loudly if the historical rows really do violate it — which was the answer they needed a year earlier.

### SELECT — the workhorse

The most-executed SQL statement on Earth. The basic shape:

```sql
SELECT column_list
FROM table_or_join
WHERE row_filter
GROUP BY grouping_columns
HAVING group_filter
ORDER BY sort_columns
LIMIT n OFFSET m;
```

Logical execution order (different from written order!):

```
1. FROM        — source tables, joins
2. WHERE       — filter rows before grouping
3. GROUP BY    — collapse rows into groups
4. HAVING      — filter groups
5. SELECT      — pick / compute columns
6. DISTINCT    — dedupe results
7. ORDER BY    — sort
8. LIMIT/OFFSET — pagination
```

Knowing this order explains many "weird" behaviors — like why `WHERE` can reference table columns but not aliases defined in `SELECT`, or why `HAVING` can reference aggregates but `WHERE` cannot.

```sql
-- Pick specific columns
SELECT id, name, email FROM customers;

-- Compute new columns
SELECT id, name, UPPER(email) AS email_upper, age * 2 AS double_age FROM customers;

-- Filter rows (WHERE), sort (ORDER BY), limit
SELECT id, name FROM customers
WHERE country = 'PK'
ORDER BY name ASC
LIMIT 10;

-- Aliases
SELECT c.id AS customer_id, c.name AS customer_name FROM customers AS c;
```

The column list is not cosmetic. It decides whether an index can answer the query on its own (every column you ask for is in the index) or whether the engine has to go back to the table for each row — a *key lookup* in SQL Server, a heap fetch in PostgreSQL. `SELECT *` opts out of that permanently: the query now asks for whatever columns the table happens to have next year.

> 🌍 **In the real world**: an order-list endpoint is served entirely from a covering index and is quick for a year. Someone adds a `notes NVARCHAR(MAX)` column to `orders` for a support feature and the endpoint starts timing out — no deploy touched it, no query changed. Because it was written as `SELECT *` it now asks for a column the index does not contain, so every row that used to be answered from the index becomes a lookup back into the table. A schema change alone moved a sequential index read into random I/O per row, and the only defence that would have held is naming the columns.

### INSERT / UPDATE / DELETE

```sql
-- INSERT — single row
INSERT INTO customers (id, name, email, country)
VALUES (1, 'Ahmed', 'ahmed@example.com', 'PK');

-- INSERT — multiple rows
INSERT INTO customers (id, name, email, country)
VALUES
    (2, 'Sara', 'sara@example.com', 'US'),
    (3, 'Bob',  'bob@example.com',  'GB');

-- INSERT from a query (bulk copy / archive)
-- Name the columns on both sides: bare SELECT * matches by position, so the day
-- someone adds a column to one table and not the other, this either fails or
-- silently loads the wrong column into the wrong place.
INSERT INTO customers_archive (id, name, email, country, created_at)
SELECT id, name, email, country, created_at
FROM customers WHERE created_at < '2024-01-01';

-- UPDATE — always with WHERE
UPDATE orders
SET status = 'Shipped', shipped_at = NOW()
WHERE id = 42 AND status = 'Pending';

-- UPDATE with computed value, filtered through another table
-- (orders has no country column — country lives on customers)
UPDATE orders
SET total = total * 1.1               -- 10% uplift
WHERE customer_id IN (SELECT id FROM customers WHERE country = 'PK');

-- DELETE — always with WHERE
DELETE FROM orders
WHERE status = 'Cancelled' AND created_at < NOW() - INTERVAL '30 days';

-- TRUNCATE — removes every row by deallocating pages instead of logging each
-- delete. No WHERE, no row triggers, and engine-specific rules about
-- transactions, identity counters and foreign keys (see below).
TRUNCATE TABLE staging_orders;
```

**Always include WHERE on UPDATE and DELETE.** The single missing WHERE is the canonical horror story — "I deleted the entire users table." Some engineers wrap UPDATE/DELETE in transactions during dev so they can ROLLBACK if WHERE was wrong.

```sql
BEGIN;
UPDATE orders SET status = 'Cancelled' WHERE customer_id = 7;
-- inspect result with SELECT first
SELECT COUNT(*) FROM orders WHERE customer_id = 7 AND status = 'Cancelled';
-- if good:
COMMIT;
-- if not:
ROLLBACK;
```

**How many rows one statement touches is a design decision, not an implementation detail.** A single `DELETE` covering a year of history is one transaction: it holds its locks until it commits, and nothing in the log can be reused until it ends. SQL Server also escalates: Microsoft Learn's *Transaction locking and row versioning guide* gives the trigger as a single statement acquiring at least 5,000 locks on one non-partitioned table or index (and re-attempting every 1,250 new locks if the first attempt is blocked), at which point row locks become a table lock and readers of unrelated rows start waiting.

The fix is to keep the work set-based but bound each transaction:

```sql
-- SQL Server: loop until a batch deletes nothing
WHILE 1 = 1
BEGIN
    DELETE TOP (5000) FROM orders
    WHERE status = 'Cancelled' AND created_at < DATEADD(year, -1, SYSUTCDATETIME());

    IF @@ROWCOUNT = 0 BREAK;   -- each batch commits on its own (no open transaction)
END

-- PostgreSQL: one batch, expressed with a CTE. Re-run it from the client
-- (or wrap it in a DO block) until it reports 0 rows deleted.
WITH doomed AS (
    SELECT id FROM orders
    WHERE status = 'Cancelled' AND created_at < NOW() - INTERVAL '1 year'
    LIMIT 5000
)
DELETE FROM orders o USING doomed d WHERE o.id = d.id;
```

Each batch is still set-based — the loop is around statements, not rows.

> 🌍 **In the real world**: a retention job deletes a year of shipped orders as one statement, at 02:00, and for two years nobody notices. Then the table is big enough that the delete escalates to a table lock, and the job stops being "removing rows nobody reads" and becomes "the orders table is unavailable" — checkout included, because the night shift in another region was placing orders. The log also grows for the whole run, since none of it can be reused until the statement commits. Rewritten as batches of a few thousand rows, each committing, the same predicate deletes the same rows with the site up. Nothing about the work changed; what changed is how long a single transaction held what it held.

**A DML statement can hand back the rows it touched.** Going back for them with a follow-up `SELECT` is a second round trip *and* a different point in time — between the two statements someone else can change what you are about to read.

```sql
-- SQL Server: OUTPUT, available on INSERT / UPDATE / DELETE / MERGE
UPDATE orders
SET    status = 'Shipped', shipped_at = SYSUTCDATETIME()
OUTPUT INSERTED.id, DELETED.status AS old_status, INSERTED.status AS new_status
WHERE  status = 'Paid';

-- PostgreSQL: RETURNING
UPDATE orders
SET    status = 'Shipped', shipped_at = NOW()
WHERE  status = 'Paid'
RETURNING id, status;

-- MySQL: neither. Read the generated key back, per connection:
INSERT INTO orders (customer_id, total) VALUES (7, 99.00);
SELECT LAST_INSERT_ID();
```

Three things to know before relying on them:

- **`OUTPUT` exposes both sides of the change.** The `INSERTED` and `DELETED` pseudo-tables mean one `UPDATE` can return the before *and* after values — that is how an audit row gets written without a trigger. PostgreSQL only caught up in **18**, which added the `old`/`new` aliases: "Previously `RETURNING` only returned new values for `INSERT` and `UPDATE`, and old values for `DELETE`" (PostgreSQL 18 release notes). On 17 and earlier, `RETURNING ... old.col` errors out (`old` is not a known table reference) and the before-image has to come from a CTE or a trigger.
- **`LAST_INSERT_ID()` returns the *first* id of a multi-row insert, not the last.** The MySQL manual is blunt: "If you insert multiple rows using a single `INSERT` statement, `LAST_INSERT_ID()` returns the value generated for the *first* inserted row only." It is also maintained "on a per-connection basis", which is what makes it safe under concurrency and useless across connections.
- **SQL Server restricts `OUTPUT` around triggers.** "If the `OUTPUT` clause is specified without also specifying the `INTO` keyword, the target of the DML operation can't have any enabled trigger defined on it for the given DML action." And the `OUTPUT ... INTO` target table itself "can't have enabled triggers defined on it", "participate on either side of a `FOREIGN KEY` constraint", or "have `CHECK` constraints or enabled rules" — which rules out most real tables and is why the destination is usually a table variable or temp table.

> 🌍 **In the real world**: a service upgrades from EF Core 6 to 7, changes no code and no schema, and `SaveChanges` starts throwing on exactly the tables that carry legacy audit triggers. EF 7's SQL Server provider switched to an `OUTPUT`-based save path, and SQL Server refuses `OUTPUT` without `INTO` on a table with an enabled trigger for that action — a constraint from the database that surfaced as an ORM upgrade bug. Microsoft documents the escape as a per-entity opt-out: `ToTable(tb => tb.HasTrigger("SomeTrigger"))` in EF 7, `ToTable(tb => tb.UseSqlOutputClause(false))` from EF 8, which reverts that entity to the older save technique. The lesson worth carrying is that "the ORM changed" and "the database has a rule about this" are frequently the same incident.

**The rows-affected count is a result, not a log line.** Every client hands it back — `SqlCommand.ExecuteNonQuery()` returns it, `@@ROWCOUNT` exposes it in T-SQL, `ROW_COUNT()` in MySQL — and putting the value you expect to find into the `WHERE` clause turns an ordinary `UPDATE` into a compare-and-swap:

```sql
UPDATE orders
SET    status = 'Shipped', version = version + 1
WHERE  id = @id AND version = @expected_version;
-- 1 row affected  → we won; nothing changed the row since we read it
-- 0 rows affected → someone changed it first; our copy is stale
```

Without the version predicate, two users who both loaded the order at 10:00 and both saved at 10:05 each "succeed", and the second silently discards the first — the *lost update*. The predicate does not prevent the race. It detects it, which is the whole of what optimistic concurrency promises.

This is precisely what EF Core does with a concurrency token, and its documentation describes the mechanism in those terms: EF adds the token to the `WHERE` clause, and "if a concurrent update occurred, the UPDATE fails to find any matching rows and reports that zero were affected. As a result, EF Core's `SaveChanges()` throws a `DbUpdateConcurrencyException`". A SQL Server `rowversion` column mapped with `[Timestamp]` is the no-effort version of the same idea, because the database bumps it on every change and you can't forget to.

One trap this creates: after a bulk statement such as `UPDATE ... WHERE status = 'Paid'`, zero rows affected means "nothing matched", which is neither an error nor a conflict. Only when the `WHERE` identifies exactly one row by key does zero mean "someone beat me to it".

**"Insert it if it isn't there" is a race unless the database arbitrates it.** The shape everybody writes first —

```csharp
if (!await db.Prices.AnyAsync(p => p.Sku == sku))   // SELECT
    db.Prices.Add(new Price { Sku = sku, ... });    // INSERT
```

— has a window between the check and the insert in which another connection can insert the same key. Nothing in application code closes that window. The unique index is the only component that can adjudicate two simultaneous inserts, and it adjudicates by raising a duplicate-key error on the loser. So either handle that error deliberately, or use the engine's atomic form:

```sql
-- PostgreSQL: ON CONFLICT. The docs call it what it is — "ON CONFLICT DO UPDATE
-- guarantees an atomic INSERT or UPDATE outcome ... even under high concurrency.
-- This is also known as UPSERT"
INSERT INTO prices (sku, amount, updated_at)
VALUES ('ABC-1', 19.99, NOW())
ON CONFLICT (sku) DO UPDATE
SET amount = EXCLUDED.amount, updated_at = EXCLUDED.updated_at;

-- MySQL: ON DUPLICATE KEY UPDATE
INSERT INTO prices (sku, amount) VALUES ('ABC-1', 19.99) AS new
ON DUPLICATE KEY UPDATE amount = new.amount;

-- SQL Server: MERGE — read the concurrency note below before shipping this
MERGE prices WITH (HOLDLOCK) AS t
USING (VALUES ('ABC-1', 19.99)) AS s (sku, amount) ON t.sku = s.sku
WHEN MATCHED     THEN UPDATE SET t.amount = s.amount
WHEN NOT MATCHED THEN INSERT (sku, amount) VALUES (s.sku, s.amount);
```

What separates these three in an interview:

- **PostgreSQL** requires a conflict target for `DO UPDATE`, and it must be inferable from a unique index or constraint — the atomicity comes from that index, not from the keyword. The row you tried to insert is available as `EXCLUDED`.
- **MySQL** reacts to a collision on *any* unique key on the table, not only the one you had in mind, so a row that clashes on an unrelated unique column is updated rather than rejected. The affected-rows count tells you which branch ran: "1 if the row is inserted as a new row, 2 if an existing row is updated, 0 if an existing row is set to its current values". Refer to the proposed values through a row alias (`AS new`); the older `VALUES()` function is "deprecated and subject to removal in a future version of MySQL".
- **SQL Server** does not make `MERGE` atomic for you. Microsoft Learn: "In some scenarios where unique keys are expected to be both inserted and updated by the `MERGE`, specifying the `HOLDLOCK` will prevent against unique key violations" — `HOLDLOCK` being a synonym for `SERIALIZABLE`. The same page warns that "At scale, `MERGE` might introduce complicated concurrency issues or require advanced troubleshooting", and that where heavy concurrency is expected "separate `INSERT`, `UPDATE`, and `DELETE` logic might perform better, with less blocking, than a `MERGE` statement". Knowing that `MERGE` needs `HOLDLOCK` is a reliable senior signal, because it means you have hit the problem rather than read the syntax.

> 🌍 **In the real world**: a price-import job does `SELECT`-then-`INSERT` per SKU, and the day the vendor starts delivering the feed on two threads it begins failing a handful of rows per run with duplicate-key errors. The first fix is a retry, which converts the errors into a slower job that still occasionally persists the older of two concurrent updates, because the retry re-reads and re-decides from scratch. The unique index on `sku` had been doing its job throughout — it is the only thing in the system that can settle two simultaneous inserts, and the application was asking it, via `SELECT`, a question it cannot answer atomically. Rewritten as a single `INSERT ... ON CONFLICT (sku) DO UPDATE`, the same feed on the same two threads produced no errors and no lost updates, because the decision now happens inside the statement holding the index entry.

### Filtering with WHERE

```sql
-- Equality
WHERE country = 'PK'
WHERE status <> 'Cancelled'         -- not equal; some dialects use !=

-- Range
WHERE age BETWEEN 18 AND 65          -- inclusive
WHERE created_at >= '2025-01-01' AND created_at < '2026-01-01'

-- Set membership
WHERE country IN ('PK', 'US', 'GB')
WHERE status NOT IN ('Cancelled', 'Refunded')

-- NULL checks (= NULL doesn't work!)
WHERE notes IS NULL
WHERE notes IS NOT NULL

-- Pattern match (LIKE)
WHERE name LIKE 'A%'                 -- starts with A
WHERE name LIKE '%son'               -- ends with son
WHERE name LIKE '_ohn'               -- exactly one char + 'ohn' (John, Cohn)
WHERE name ILIKE 'a%'                -- case-insensitive (PostgreSQL)

-- Boolean combinations
WHERE country = 'PK' AND age > 18
WHERE country = 'PK' OR country = 'US'
WHERE NOT (status = 'Cancelled')
WHERE country = 'PK' AND (status = 'Pending' OR status = 'Paid')   -- precedence
```

**Performance tip:** `LIKE 'A%'` (no leading wildcard) can use a B-tree index, because a prefix is a range: everything from `'A'` up to the next letter sits contiguously in the index. `LIKE '%A%'` cannot — there is no range that contains "has an A somewhere", so every row must be examined. For substring search on big tables, use full-text search (`CONTAINS` in SQL Server, `tsvector` in PostgreSQL) or a trigram index (`pg_trgm`).

One engine caveat that costs people an afternoon: **in PostgreSQL a plain B-tree index only serves `LIKE 'A%'` if the database uses the C locale.** The docs put it as a condition on the optimizer's use of a B-tree for `LIKE`: "if your database does not use the C locale you will need to create the index with a special operator class" (*Index Types*). That class is `text_pattern_ops` / `varchar_pattern_ops` — `CREATE INDEX ... ON customers (name text_pattern_ops)` — which compares "strictly character by character rather than according to the locale-specific collation rules", so a prefix is a clean range again. Note the trade-off the operator-class page states: you should "also create an index with the default operator class if you want queries involving ordinary `<`, `<=`, `>`, or `>=` comparisons to use an index", because those "cannot use the `xxx_pattern_ops` operator classes" — two indexes on one column.

> 🌍 **In the real world**: an internal admin search box runs `WHERE customer_name LIKE '%' + @q + '%'` against the live orders database and fires on every keystroke. It was written when the customer table was small and stayed correct forever — it just quietly became the top CPU consumer in the plan cache, which nobody looked at because "search" was not on anyone's list of expensive features. The permanent fix was a full-text index; the fix that bought the afternoon was requiring three characters before searching and anchoring the pattern to a prefix.

**`AND` in SQL is not `&&` in C#: there is no guaranteed evaluation order and no left-to-right short-circuit.** In C#, `a != null && a.Length > 0` is safe because the language defines the order. SQL defines no such thing, and both engines say so in their own words.

PostgreSQL, *Expression Evaluation Rules*: "The order of evaluation of subexpressions is not defined ... It is particularly dangerous to rely on side effects or evaluation order in `WHERE` and `HAVING` clauses, since those clauses are extensively reprocessed as part of developing an execution plan. Boolean expressions (`AND`/`OR`/`NOT` combinations) in those clauses can be reorganized in any manner allowed by the laws of Boolean algebra." Its worked example is the division-by-zero guard everyone has written:

```sql
-- Untrustworthy: nothing forces x > 0 to be evaluated first
SELECT ... WHERE x > 0 AND y/x > 1.5;

-- Safe: CASE is the one construct with a defined order
SELECT ... WHERE CASE WHEN x > 0 THEN y/x > 1.5 ELSE false END;
```

The same docs add the better answer wherever one exists — rewrite the predicate so no guard is needed at all, here `y > 1.5*x` — because forcing order with `CASE` also blocks the optimizer from reordering for speed.

SQL Server behaves the same way. Its archived engineering post *Predicate ordering is not guaranteed* (2006) walks through a view that filters `WHERE category = 'ID'` and casts a `varchar` column to `int`; querying that view by the cast column raises a conversion error, because "`ID = 123` is expanded into `convert(int, value) = 123`, and it gets evaluated before the predicate `category = 'ID'`". The conclusion has not aged: "the order of evaluation for predicates is never guaranteed, so application logic should not depend on such order." The post's fix is the same `CASE` expression; on SQL Server 2012 and later the tidier one is `TRY_CONVERT` / `TRY_CAST`, which "returns a value cast to the specified data type if the cast succeeds; otherwise, returns `NULL`" instead of raising.

Note what the post itself observes: the error appeared on SQL Server 2000 and not on 2005, because the optimizer happened to pick the other order. A predicate order that works is a property of one plan, not of your query — and plans change when statistics, indexes or the engine version change.

> 🌍 **In the real world**: a settings table keeps every value in one `value VARCHAR(50)` column with a `data_type` discriminator, and `WHERE data_type = 'int' AND CAST(value AS INT) > 100` has worked for three years. Someone adds an index for an unrelated report, the plan changes, the cast now runs against rows the type filter used to remove first, and the query starts failing on data nobody touched. The defect was present from the day it was written; the new index only chose a plan that exposed it. `TRY_CAST` got results flowing again within the hour, and the durable fix was a typed column — because the query was relying on a correlation between two columns that the optimizer has no way to know about.

### Sorting and limiting

```sql
-- Basic sort
ORDER BY name ASC                    -- ASC is default; can omit
ORDER BY created_at DESC

-- Multi-column sort
ORDER BY country ASC, name DESC      -- by country, then by name within each country

-- Sort by computed column
SELECT id, name, total * 1.1 AS adjusted_total FROM orders
ORDER BY adjusted_total DESC

-- Pagination
LIMIT 10                             -- first 10 rows (PostgreSQL, MySQL)
LIMIT 10 OFFSET 20                   -- rows 21-30
SELECT TOP 10 * FROM orders ORDER BY total DESC   -- SQL Server
SELECT * FROM orders ORDER BY id OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY  -- ANSI

-- NULL sort handling (vendor-specific)
ORDER BY name ASC NULLS FIRST        -- PostgreSQL (also Oracle)
ORDER BY name ASC NULLS LAST
```

**Where NULLs land is not standard**, and the `NULLS FIRST`/`NULLS LAST` syntax that would let you say what you mean is not available everywhere:

| Engine | Default for `ORDER BY col ASC` | `NULLS FIRST`/`LAST` syntax |
|---|---|---|
| **SQL Server** | NULLs **first** — "NULL values are treated as the lowest possible values" (Microsoft Learn, *ORDER BY clause*) | Not supported; emulate with `ORDER BY CASE WHEN col IS NULL THEN 1 ELSE 0 END, col` |
| **PostgreSQL** | NULLs **last** — "null values sort as if larger than any non-null value" | Supported |
| **MySQL** | NULLs **first** — "NULL values are presented first if you do ORDER BY ... ASC" | Not supported; `ORDER BY col IS NULL, col` is the idiom |

Port a query between engines and the same `ORDER BY ... LIMIT 10` can return a page of NULLs instead of a page of data.

For pagination beyond a few thousand rows, prefer **cursor-based** (`WHERE id < last_seen_id`) — see [API Design Principles](../../02-api-development/03-api-design-principles.md#5-pagination). `OFFSET` requires the DB to skip rows physically; gets slower as offset grows.

Whichever style you use, **the sort must be deterministic or the pages overlap**. Microsoft's guidance on `OFFSET`/`FETCH` states the conditions for stable results plainly: the underlying data must not change between page requests (or all pages must run in one snapshot/serializable transaction), and the `ORDER BY` must contain "a column or combination of columns that are guaranteed to be unique". A tiebreaker on the primary key is the cheap half of that. Note also that in SQL Server `OFFSET`/`FETCH` is part of the `ORDER BY` clause — it is a syntax error without one, which is the engine forcing you to at least name a sort.

> 🌍 **In the real world**: a support tool pages an order list newest-first on `created_at`, and agents keep reporting orders that appear on two consecutive pages while others never appear at all. Orders imported in the same batch share a timestamp to the second, so the sort is ambiguous, and every page is a separate query free to break the tie a different way — nothing is broken and nothing reproduces on a developer machine with forty rows in the table. `ORDER BY created_at DESC, id DESC` closed three tickets that had already been marked "cannot reproduce".

**An `ORDER BY` inside a view, derived table or subquery does not survive into the outer query.** Microsoft Learn states the rule and its exception together: "The `ORDER BY` clause isn't valid in views, inline functions, derived tables, and subqueries, unless you also specify either the `TOP` or `OFFSET` and `FETCH` clauses. When you use `ORDER BY` in these objects, the clause is used only to determine the rows returned by the `TOP` clause or `OFFSET` and `FETCH` clauses. The `ORDER BY` clause doesn't guarantee ordered results when these constructs are queried, unless `ORDER BY` is also specified in the query itself."

That exception is what makes `CREATE VIEW ... AS SELECT TOP 100 PERCENT ... ORDER BY ...` such a durable piece of folklore: it is legal, it looks like it pre-sorts the view, and the sort is free to disappear the moment the outer query gets a plan that doesn't need it. Sort in the statement that returns rows to the client, every time. The same page also notes that an `ORDER BY` on an `INSERT ... SELECT` "doesn't guarantee the rows are inserted in the specified order" — worth knowing before you try to control identity assignment by sorting the source.

### DISTINCT

Removes duplicates from the result.

```sql
SELECT DISTINCT country FROM customers;
-- Returns each country once, regardless of how many customers per country.

SELECT DISTINCT country, status FROM orders;
-- Returns unique (country, status) tuples.
```

`DISTINCT` is a sort/hash operation under the hood — has cost. If you're applying it to every query "just in case," investigate why duplicates exist; often there's a join you can fix.

`COUNT(DISTINCT col)` counts unique values:
```sql
SELECT COUNT(DISTINCT country) FROM customers;
-- Number of distinct countries represented.
```

**NULLs behave differently in the two.** `SELECT DISTINCT country` returns NULL as one of the rows — for deduplication and grouping, two NULLs are treated as the same value, even though `NULL = NULL` is UNKNOWN everywhere else (MySQL's manual states the grouping rule directly: "Two NULL values are regarded as equal in a GROUP BY"). `COUNT(DISTINCT country)` skips NULL entirely, because it is an aggregate and aggregates ignore NULL inputs. So the number of rows from the first query and the number from the second can legitimately differ by one, and "our country count is off by one" has caught out more than one dashboard.

> 🌍 **In the real world**: a revenue-by-region report starts showing every order twice after a join is added to `customer_addresses`, where a customer can have both a billing and a shipping row. `DISTINCT` goes on the detail query, the row count looks right again, and it ships. The duplicated rows were never the defect — the join produced two copies of each order, and the summary query built on the same join keeps `SUM(total)` counting each order twice, which `DISTINCT` on a different query does nothing about. Finance found it weeks later. The fix was to collapse addresses to one row per customer before joining; `DISTINCT` had only removed the symptom that would have led someone to the join.

### NULL semantics

NULL means "unknown." It doesn't mean zero, empty string, or false. The big surprises:

```sql
-- Equality with NULL is NEVER true
SELECT NULL = NULL;          -- NULL (not TRUE)
SELECT NULL = 'x';           -- NULL
SELECT NULL <> 'x';          -- NULL

-- IS NULL / IS NOT NULL
SELECT * FROM users WHERE notes IS NULL;       -- correct
SELECT * FROM users WHERE notes = NULL;        -- always returns 0 rows!

-- Three-valued logic
TRUE AND NULL  → NULL
FALSE AND NULL → FALSE
TRUE OR NULL   → TRUE
FALSE OR NULL  → NULL
NOT NULL       → NULL

-- Aggregates IGNORE NULL
SELECT AVG(age) FROM users;   -- average of non-NULL ages
SELECT COUNT(*) FROM users;   -- counts all rows (NULL included)
SELECT COUNT(age) FROM users; -- counts non-NULL ages

-- COALESCE — first non-NULL argument
SELECT COALESCE(nickname, name, 'Anonymous') FROM users;

-- NULLIF — return NULL if two values are equal (useful for avoiding division by zero)
SELECT total / NULLIF(quantity, 0) FROM orders;  -- NULL instead of error if quantity=0
```

Two notes on running those probes yourself. The bare `SELECT NULL = NULL;` lines work in PostgreSQL, which has a real `boolean` type, and in MySQL, which returns a comparison as `1`/`0`/`NULL` (its `BOOL`/`BOOLEAN` are synonyms for `TINYINT(1)`, not a distinct type). **T-SQL has no boolean data type at all**, so in SQL Server you need to wrap the comparison: `SELECT CASE WHEN NULL = NULL THEN 'true' ELSE 'not true' END;` (it prints `not true`, because UNKNOWN is not TRUE). And if you meet a legacy SQL Server codebase where `= NULL` appears to work, that is `SET ANSI_NULLS OFF` — under which `{expression} = NULL` evaluates to TRUE when the expression is NULL. It is deprecated and, per Microsoft Learn, "starting with SQL Server 2017 (14.x), ANSI_NULLS is always set to ON", so that code is on borrowed time.

**Every construct handles UNKNOWN, and they don't agree.** This one table explains most NULL surprises:

| Construct | Rule for NULL / UNKNOWN |
|---|---|
| `WHERE`, `HAVING`, join `ON` | Keeps the row only when the predicate is **TRUE**. UNKNOWN drops it — same outcome as FALSE, different meaning. |
| `CHECK` constraint | Rejects the row only when the predicate is **FALSE**. UNKNOWN **passes**. The exact opposite default to `WHERE`. |
| `UNIQUE` | Standard: NULLs are distinct, so duplicates of NULL are allowed. SQL Server allows only one; PostgreSQL 15+ can opt in with `NULLS NOT DISTINCT`. |
| `GROUP BY`, `DISTINCT`, `UNION` | NULLs are treated as **equal** and collapse into a single group/row. |
| `ORDER BY` | NULLs sort first in SQL Server and MySQL, last in PostgreSQL (ascending). |
| Aggregates | Ignore NULL inputs. `COUNT(*)` counts rows; `COUNT(col)` counts non-NULLs; `SUM` of all-NULL is NULL, not 0. |
| `NOT IN (subquery)` | One NULL in the subquery makes the whole predicate UNKNOWN — **zero rows**, always. Use `NOT EXISTS`. |

NULL handling is the source of countless bugs. When designing a column, decide deliberately: should it allow NULL, or should it default? `NOT NULL DEFAULT 0` avoids the entire NULL category at the cost of conflating "zero" and "unknown."

> 🌍 **In the real world**: a nightly job emails customers who have not ordered in a year, selected with `WHERE customer_id NOT IN (SELECT customer_id FROM recent_orders)`. It runs fine for months and then sends nothing — and sends nothing *silently*, because "no customers matched" is an ordinary result and the job exits successfully. A release had made `recent_orders.customer_id` nullable to support guest checkout, one NULL arrived, and `NOT IN` over a list containing NULL can never be TRUE for any row. It surfaced through a marketing report, not through monitoring. `NOT EXISTS` would have kept working unchanged; so would `WHERE customer_id IS NOT NULL` inside the subquery.

**When you genuinely want "same value, NULLs included", there is a predicate for that.** Change detection written as `WHERE old.email <> new.email` silently skips every row where one side is NULL, so a column being cleared or first populated does not register as a change. The standard's answer is `IS DISTINCT FROM`, which always returns TRUE or FALSE and never UNKNOWN:

| Engine | Syntax | Availability |
|---|---|---|
| **PostgreSQL** | `a IS [NOT] DISTINCT FROM b` | Long-standing |
| **SQL Server** | `a IS [NOT] DISTINCT FROM b` | **SQL Server 2022 (16.x)** and Azure SQL Database. Earlier versions need the expansion below. |
| **MySQL** | `a <=> b` — NULL-safe equal. The manual notes it "is equivalent to the standard SQL `IS NOT DISTINCT FROM` operator" | Long-standing |

Microsoft Learn's truth table is the clearest statement of what changes:

| A | B | `A = B` | `A IS NOT DISTINCT FROM B` |
|---|---|---|---|
| 0 | 0 | True | True |
| 0 | 1 | False | False |
| 0 | NULL | Unknown | **False** |
| NULL | NULL | Unknown | **True** |

On SQL Server 2019 and earlier, the portable rewrite is the one the docs themselves generate when sending the predicate to a linked server that can't parse the syntax: `A IS NOT DISTINCT FROM B` becomes `(NOT (A <> B OR A IS NULL OR B IS NULL) OR (A IS NULL AND B IS NULL))`. The commonly-seen shortcut `COALESCE(a, '~') = COALESCE(b, '~')` works only while the sentinel can never be a real value, and it wraps the column in a function — so the index goes too.

### Implicit conversion — the index that stops being used

Every comparison has two sides and they have to end up the same type. When they don't, the engine converts one of them — and *which* side it converts decides whether your index is still usable. This is the most common way a .NET application breaks its own indexes without changing a line of SQL.

SQL Server decides by **data type precedence**: "the data type with the lower precedence is first converted to the data type with the higher precedence" (Microsoft Learn, *Data type precedence (Transact-SQL)*). The relevant slice of that list, higher first: `bigint` → `int` → … → `nvarchar` → `nchar` → `varchar` → `char`. Two cases fall out of it:

```sql
-- Column INT, literal a string. int outranks varchar → the LITERAL converts.
WHERE order_id = '4711'          -- converted once; index seek survives

-- Column VARCHAR, parameter NVARCHAR. nvarchar outranks varchar → the COLUMN converts.
WHERE sku = @p0                  -- CONVERT_IMPLICIT applied to every row → scan
```

Only the second one hurts. Converting a constant happens once, before the scan starts. Converting a column happens per row, and once the indexed column is wrapped in a function the engine can no longer match it against the keys stored in the index — a seek becomes a scan. The plan shows exactly this: the predicate reads `CONVERT_IMPLICIT(nvarchar(50),[sku],0)=[@p0]` and SQL Server attaches a warning that the type conversion may affect the cardinality estimate.

The reason this hits .NET specifically is that both mainstream data-access libraries default to Unicode parameters:

| Client | Default for a `string` | How to send `varchar` |
|---|---|---|
| **EF Core** (SQL Server) | `nvarchar(max)`, or `nvarchar(450)` for a key column | `IsUnicode(false)` / `[Unicode(false)]`, or `HasColumnType("varchar(50)")` |
| **Dapper** | `DbType.String` → `nvarchar` | `new DbString { Value = sku, IsAnsi = true, Length = 50 }` |

The rule: **the model and the column must agree.** A `varchar` column queried through an `nvarchar` parameter is a mismatch that never raises an error — it only spends CPU.

Other engines arrive at different places:

- **PostgreSQL** mostly refuses to guess. `WHERE sku = 42` against a `varchar` column raises `operator does not exist: character varying = integer`; you get an error instead of a silent scan. A *quoted* literal is untyped and takes the column's type, so `WHERE order_id = '4711'` on an `integer` column is fine. There is no `nvarchar` — `text` and `varchar` are stored the same way in the same database encoding, so there is no Unicode-versus-ANSI mismatch to create.
- **MySQL** is the one to watch. "For comparisons of a string column with a number, MySQL cannot use an index on the column to look up the value quickly" — because many strings convert to the same number (MySQL 8.4 manual, *Type Conversion in Expression Evaluation*). Worse, the comparison is done as floating-point numbers, so `WHERE varchar_col = 0` matches every row whose text converts to zero — anything without a leading number, which in the manual's own worked example is all five rows of fruit names — and the manual notes that "this occurs even when using strict SQL mode". Quote the literal (`= '0'`) and it compares as a string again.

> 🌍 **In the real world**: a `sku VARCHAR(32)` lookup has been served by an index for years. A team ports the query from Dapper to EF Core, changes no SQL, and the endpoint starts timing out under ordinary traffic. The entity's `string` property mapped to `nvarchar`, `nvarchar` outranks `varchar` in the precedence list, and so the engine converted the column on every row rather than the parameter once. `IsUnicode(false)` on the property put the seek back. The tell was visible in the plan cache from the first deploy — a `CONVERT_IMPLICIT` wrapped around a column somebody had deliberately indexed — which is worth knowing because the incident looks like a capacity problem right up until you read the plan.

### Set-based thinking

The C# instinct is to fetch rows and loop. SQL asks you to *describe the result* and let the optimizer choose how to get there — and the moment you write the loop yourself, you have taken that choice away from it permanently. A cursor (or a `foreach` in application code issuing one statement per row) commits the engine to nested-loop-shaped work: no hash join, no parallel scan, no read-ahead over a range, one plan execution and one set of locks per row, and a round trip per row if the loop is in your process.

The same job, three ways:

```sql
-- Row by row: one statement per customer, N round trips, N transactions
-- (this is what a foreach + SaveChanges() produces)
UPDATE customers SET tier = 'Gold' WHERE id = @id;   -- executed N times

-- Set-based, SQL Server
UPDATE c
SET    c.tier = 'Gold'
FROM   customers c
JOIN   (SELECT customer_id FROM orders
        WHERE created_at >= DATEADD(year, -1, SYSUTCDATETIME())
        GROUP BY customer_id HAVING SUM(total) > 10000) q ON q.customer_id = c.id;

-- Set-based, PostgreSQL
UPDATE customers c
SET    tier = 'Gold'
FROM   (SELECT customer_id FROM orders
        WHERE created_at >= NOW() - INTERVAL '1 year'
        GROUP BY customer_id HAVING SUM(total) > 10000) q
WHERE  c.id = q.customer_id;

-- Set-based, MySQL
UPDATE customers c
JOIN   (SELECT customer_id FROM orders
        WHERE created_at >= NOW() - INTERVAL 1 YEAR
        GROUP BY customer_id HAVING SUM(total) > 10000) q ON q.customer_id = c.id
SET    c.tier = 'Gold';
```

The aggregate always goes in a derived table or CTE — an `UPDATE` cannot carry its own `GROUP BY`. The dialects differ only in shape: SQL Server updates an alias declared in a `FROM`, PostgreSQL uses `SET … FROM … WHERE`, MySQL puts the join before `SET`. All three send one statement, and all three let the optimizer pick the join strategy.

Set-based is not the same as "unbounded". A statement touching millions of rows is one transaction holding one set of locks, which is the problem the [batched delete above](#insert--update--delete) solves. The correct shape for large maintenance work is a **loop around set-based batches**: procedural at the top, set-based inside, each batch its own transaction.

Loops are still right when the work genuinely is per row and has an outside effect — calling a payment provider, sending a message, anything that can't be expressed as a single result set. That belongs in application code, not in a cursor.

On the .NET side, the same principle has a name: **N+1**. LINQ that materializes a list and then touches a navigation property per element issues one query per row, which is the loop written by accident — see [EF Core](../01-ef-core.md) and [LINQ](../02-linq.md). EF Core 7 added `ExecuteUpdateAsync` / `ExecuteDeleteAsync`, which emit one set-based statement instead of loading entities and saving them back.

> 🌍 **In the real world**: a monthly statement job loads every active customer, loops in C#, and calls `SaveChanges()` inside the loop. It fits the maintenance window in year one and overruns it in year three, at which point someone kills it — leaving the month half-processed, because each iteration committed on its own and there is no single thing to roll back. Rewritten as one `UPDATE … FROM` against a staging table it finished inside the window, but the reason the on-call rota cared was the other half: as one statement it either completes or it doesn't, and "run it again" became a safe instruction instead of a question about which customers were already done.

### TRUNCATE vs DELETE vs DROP

`DELETE` is DML: it removes rows one at a time, logs each one, fires row triggers, respects `WHERE`, and participates in your transaction like any other statement. `TRUNCATE` removes every row by **deallocating the pages** — the log records the deallocations, not the rows. `DROP TABLE` removes the definition as well.

The interview question is "DELETE vs TRUNCATE"; the senior answer is that TRUNCATE's behaviour is engine-specific in the four ways that matter operationally:

| | SQL Server | PostgreSQL | MySQL (InnoDB) |
|---|---|---|---|
| **Rollback** | Yes — "a TRUNCATE TABLE operation can be rolled back within a transaction" | Yes — "transaction-safe with respect to the data in the tables" | **No** — "truncate operations cause an implicit commit, and so cannot be rolled back" |
| **Identity / sequence** | Reset to the seed value | Unchanged unless you write `RESTART IDENTITY` (`CONTINUE IDENTITY` is the default) | `AUTO_INCREMENT` reset to its start value |
| **Foreign keys** | Refused if the table is referenced by an FK constraint — even when the child table is empty | Refused unless every referencing table is truncated in the same statement, or you pass `CASCADE` | Refused if other tables have FK constraints referencing it |
| **Triggers** | Cannot fire triggers (no per-row logging) | Does not fire `ON DELETE` triggers, but **does** fire `ON TRUNCATE` triggers | Does not invoke `ON DELETE` triggers |

(Sources: the `TRUNCATE TABLE` reference pages for each engine — see [Sources](#sources).)

Two more things people learn the hard way:

- **TRUNCATE is not a low-impact operation, it is a short one.** SQL Server "always locks the table (including a schema (`SCH-M`) lock)"; PostgreSQL "acquires an `ACCESS EXCLUSIVE` lock on each table it operates on, which blocks all other concurrent operations". Fast, but exclusive — if you need the table to stay readable, `DELETE` is the tool.
- **The permission is different.** In SQL Server, `TRUNCATE TABLE` needs `ALTER` on the table, not `DELETE`. Application service accounts usually don't have it, which is why a cleanup routine that works on a developer's box fails in production.

Also worth knowing: SQL Server refuses to truncate tables published for transactional or merge replication, participating in an indexed view, or system-versioned (temporal) — use `DELETE` there.

> 🌍 **In the real world**: an integration-test harness resets fixtures with `TRUNCATE TABLE staging_orders` inside the transaction it rolls back after each test. That works on SQL Server and PostgreSQL, where truncation is transactional. Ported to MySQL to support a second database, the suite starts leaking rows between tests and failing in a different order every run: on MySQL, `TRUNCATE` is DDL and commits implicitly, so the rollback at the end of the test has nothing left to undo — and the implicit commit also ended the transaction everything else in the test was relying on. The fix was `DELETE FROM` in the harness, which is slower per test and correct on all three.

## Code & diagrams

<details>
<summary>🧩 Click to expand — code samples and diagrams</summary>

### Logical execution order (with example)

```sql
SELECT country, COUNT(*) AS customers      -- step 5: pick / compute
FROM customers c                            -- step 1: source
JOIN orders o ON c.id = o.customer_id      -- step 1 (cont.): joins
WHERE c.created_at > '2024-01-01'           -- step 2: filter rows
GROUP BY country                             -- step 3: collapse
HAVING COUNT(*) > 100                        -- step 4: filter groups
ORDER BY customers DESC                      -- step 7: sort
LIMIT 10;                                    -- step 8: paginate
```

Mental model:
1. Build cross-product / join input rows.
2. Apply WHERE — drop rows.
3. Apply GROUP BY — collapse remaining rows by group key.
4. Apply HAVING — drop groups.
5. Compute SELECT columns (aggregates already exist from step 3).
6. Apply DISTINCT if specified.
7. Sort.
8. Paginate.

This is why `WHERE country = (SELECT MAX(country) FROM ...)` works but `WHERE customers > 100` doesn't (the `customers` alias from SELECT doesn't exist yet at step 2).

### Constraint cascade — visualizing FK behavior

```
ON DELETE CASCADE:
  Customer 7 → DELETE
       │
       ▼
  ALL orders WHERE customer_id = 7 also DELETE.

ON DELETE SET NULL:
  Customer 7 → DELETE
       │
       ▼
  Orders.customer_id = NULL for affected rows.

ON DELETE RESTRICT (or NO ACTION, default):
  Customer 7 → DELETE attempted
       │
       ▼
  Error if any orders.customer_id = 7. Delete refused.
```

Pick by domain:
- **Cascade** for child rows that have no meaning without the parent (line items of a deleted order).
- **Set NULL** if children can survive without the parent (orders where customer was anonymized).
- **Restrict** when manual intervention is required (financial records).

### Visual: simple SELECT vs SELECT with WHERE

```
Table: customers
+----+-------+--------+---------+
| id | name  | country| age     |
+----+-------+--------+---------+
| 1  | Ahmed | PK     | 30      |
| 2  | Sara  | US     | 25      |
| 3  | Bob   | GB     | 45      |
| 4  | Cara  | PK     | 35      |
+----+-------+--------+---------+

SELECT name, age FROM customers WHERE country = 'PK';
+-------+-----+
| name  | age |
+-------+-----+
| Ahmed | 30  |
| Cara  | 35  |
+-------+-----+
```

### Worked plan — the same filter, with and without its index

Plans below are shown as operator shape only; costs and row estimates are elided because they depend on your data.

**PostgreSQL — a function wrapped around the column.** `EXPLAIN` on the two forms of "orders created on 8 May":

```
EXPLAIN SELECT id FROM orders WHERE created_at::date = DATE '2026-05-08';

 Seq Scan on orders
   Filter: ((created_at)::date = '2026-05-08'::date)      ← every row read, then tested


EXPLAIN SELECT id FROM orders
WHERE  created_at >= TIMESTAMP '2026-05-08'
  AND  created_at <  TIMESTAMP '2026-05-09';

 Index Scan using ix_orders_created_at on orders
   Index Cond: ((created_at >= '2026-05-08 00:00:00'::timestamp)
            AND (created_at <  '2026-05-09 00:00:00'::timestamp))   ← range walked in the index
```

Read the operator names first, then the line under them. `Filter:` means "rows arrived and were then thrown away". `Index Cond:` means "the index was used to decide which rows to fetch at all". That distinction is the whole of query tuning at this level.

**SQL Server — the conversion is on the wrong side.** Same query, same index; the only difference is the declared type of the parameter:

```
-- @sku declared varchar(32): the parameter matches the column
  |--Nested Loops
     |--Index Seek(OBJECT:(orders.ix_orders_sku), SEEK:([sku] = [@sku]))
     |--Key Lookup(OBJECT:(orders.PK_orders))

-- @sku declared nvarchar(4000): the client sent a Unicode string
  |--Index Scan(OBJECT:(orders.ix_orders_sku),
                WHERE:(CONVERT_IMPLICIT(nvarchar(32),[sku],0) = [@sku]))
     Warning: type conversion may affect "CardinalityEstimate" in query plan choice
```

Which side gets converted is the whole story:

```
   WHERE sku = @p0
         │      │
   varchar    nvarchar
   (LOWER)    (higher)
         │
         ▼   the lower-precedence side is converted — and here that is the column
   CONVERT_IMPLICIT runs on every row  →  index key no longer matches  →  SCAN


   WHERE order_id = '4711'
              │       │
            int     varchar
         (higher)   (LOWER)
                      │
                      ▼   the lower side is the literal, so it converts once
   column untouched  →  index key still matches  →  SEEK
```

### Common WHERE patterns

```sql
-- Active records
WHERE deleted_at IS NULL

-- Created in the last 7 days
WHERE created_at >= NOW() - INTERVAL '7 days'           -- PostgreSQL
WHERE created_at >= DATEADD(day, -7, GETDATE())          -- SQL Server

-- Top-K by some column (without window functions, use ORDER BY + LIMIT)
SELECT * FROM orders ORDER BY total DESC LIMIT 5;

-- Anti-set
WHERE status NOT IN ('Cancelled', 'Refunded')
WHERE country NOT LIKE 'X%'

-- Conditional column
SELECT id, name,
       CASE WHEN age >= 18 THEN 'Adult' ELSE 'Minor' END AS category
FROM users;

-- Multiple conditions with CASE
CASE
    WHEN total > 1000 THEN 'High'
    WHEN total > 100  THEN 'Medium'
    ELSE                   'Low'
END
```

### A "SELECT cheat sheet" reference card

```
SELECT [DISTINCT] columns
FROM   table [AS alias]
       [JOIN ...]
WHERE  row predicates                  -- pre-grouping filter
GROUP BY columns                       -- aggregate by groups
HAVING group predicates                -- post-aggregate filter
ORDER BY columns [ASC|DESC]
LIMIT n [OFFSET m];

Predicates:
  =, <>, <, <=, >, >=
  BETWEEN x AND y
  IN (a, b, c)         /  NOT IN (a, b, c)
  LIKE 'pattern'        /  ILIKE (case-insensitive, PostgreSQL)
  IS NULL              /  IS NOT NULL
  AND, OR, NOT
  EXISTS (subquery)    /  NOT EXISTS

Functions:
  Strings: UPPER, LOWER, LENGTH/LEN, TRIM, SUBSTRING, CONCAT, REPLACE, COALESCE
  Numbers: ABS, ROUND, FLOOR, CEILING, MOD, POWER, SQRT
  Dates:   NOW(), CURRENT_DATE, CURRENT_TIMESTAMP, EXTRACT, DATEDIFF, DATEADD
  Logic:   CASE WHEN ... THEN ... ELSE ... END
  NULL:    COALESCE, NULLIF, IS NULL
```

</details>

## Common pitfalls

1. **`UPDATE` / `DELETE` without `WHERE`.** Updates / deletes the entire table. Always test with `SELECT` first; consider wrapping in `BEGIN`/`COMMIT`.
2. **`SELECT *` in production code.** Slows queries; breaks when columns added; couples to schema. List columns explicitly.
3. **`= NULL` instead of `IS NULL`.** Always returns 0 rows. NULL never equals anything, including itself.
4. **Implicit type conversion in WHERE.** The damage depends on *which side* converts, not on the mismatch itself. In SQL Server `int` outranks `varchar`, so `WHERE int_col = '123'` converts the literal once and still seeks; `WHERE varchar_col = @nvarchar_param` converts the **column** on every row and scans. Match the parameter type to the column type in the ORM mapping — see [Implicit conversion](#implicit-conversion--the-index-that-stops-being-used).
5. **`LIKE '%X%'`.** Leading wildcard prevents index use. Use full-text search if you need substring queries on large tables.
6. **No `ORDER BY` on paginated queries.** Without `ORDER BY`, "page 2" might return overlapping rows with "page 1." Always sort by a stable key.
7. **`DISTINCT` to mask join bugs.** Slap `DISTINCT` on a query returning duplicates — but the duplicates are the symptom of a wrong join. Fix the join.
8. **Storing money as `FLOAT`.** Floating-point rounding errors. Use `DECIMAL(18, 2)` (or vendor equivalent).
9. **Storing local times.** Always store UTC; convert at the edge. Time zones are a nightmare otherwise.
10. **Forgetting `NOT NULL` defaults to nullable.** Most columns should be `NOT NULL`. Default to NOT NULL; allow NULL explicitly when it has meaning.
11. **No primary key.** Every table needs one (even with surrogate `INT IDENTITY` / `BIGSERIAL`). PK is the basis of indexing, replication, ORM mapping.
12. **Schema-less columns of `TEXT` for "future flexibility."** Untyped data → uncatchable bugs. Define types up front; alter later if needed.
13. **Expecting a `CHECK` to keep NULLs out.** A CHECK rejects only what evaluates to FALSE; NULL makes the predicate UNKNOWN, which passes. Add `NOT NULL` when you mean it.
14. **Assuming `TRUNCATE` is rollback-able.** It is on SQL Server and PostgreSQL; on MySQL it is DDL and commits implicitly, taking your open transaction with it.
15. **Foreign key without an index on the child column.** SQL Server and PostgreSQL don't create one (MySQL does). Parent deletes and key updates then scan the child table.
16. **One enormous `DELETE`/`UPDATE` instead of batches.** One statement, one transaction, one lock set held to the end — and on SQL Server a candidate for escalation to a table lock. Loop around set-based batches instead.
17. **Sorting a paginated query on a non-unique column.** Ambiguous order means pages can overlap or skip. Always add a unique tiebreaker (`ORDER BY created_at DESC, id DESC`).
18. **Integer division in a percentage or ratio.** SQL Server and PostgreSQL truncate integer ÷ integer; SQL Server's `AVG` over an `int` column returns an `int`. Widen an operand *before* the arithmetic (`x * 1.0 / y`), not after. MySQL's `/` is fractional — the trap moves rather than disappearing.
19. **Assuming `AND` short-circuits left to right.** It doesn't, in any engine. A guard predicate (`WHERE x > 0 AND y/x > 1.5`) is not a guard. Use `CASE`, `TRY_CAST`, or rewrite the condition so no guard is needed.
20. **`SELECT`-then-`INSERT` as an upsert.** The gap between the two statements is a race no application code can close. Use `ON CONFLICT` (PostgreSQL), `ON DUPLICATE KEY UPDATE` (MySQL), or `MERGE WITH (HOLDLOCK)` (SQL Server) — and rely on the unique index, which is what actually arbitrates.
21. **Trusting a constraint you added with `WITH NOCHECK` / `NOT VALID`.** It governs new rows only until you validate it, and SQL Server's optimizer ignores it entirely while it is untrusted.
22. **`ORDER BY` inside a view or subquery.** It does not survive into the outer query. Sort in the statement that returns rows to the client.

## Interview-ready summary

- **Five sublanguages:** DDL (define), DML (modify), DQL (query), DCL (permissions), TCL (transactions).
- **CRUD verbs:** SELECT / INSERT / UPDATE / DELETE.
- **Always WHERE on UPDATE/DELETE.** Wrap in transactions during development.
- **Logical execution order:** FROM → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY → LIMIT.
- **NULL is "unknown"** with three-valued logic. Use `IS NULL`, never `= NULL`.
- **Constraints:** PRIMARY KEY, FOREIGN KEY, UNIQUE, NOT NULL, CHECK, DEFAULT.
- **Data types** chosen for purpose: `DECIMAL(18,2)` for money, `TIMESTAMPTZ`/`DATETIMEOFFSET` for time-zone-aware times, `VARCHAR(n)` with sensible cap for strings, `INT`/`BIGINT` for IDs.
- **Constraints are three-valued too:** `WHERE` keeps only TRUE, `CHECK` rejects only FALSE. UNKNOWN passes a CHECK and fails a WHERE.
- **Type mismatches move the conversion, not the meaning:** the lower-precedence side converts. When that side is your indexed column, the seek is gone.
- **Set-based by default,** with a loop only around batches — the loop is a transaction-size tool, not a way to process rows.
- **DML can return its own rows:** `OUTPUT` (SQL Server, with `INSERTED`/`DELETED`), `RETURNING` (PostgreSQL), neither in MySQL. One statement instead of two, and no window in between.
- **Rows affected is the concurrency primitive.** `WHERE id = @id AND version = @expected` plus a rows-affected check is compare-and-swap, and is exactly what EF Core's concurrency token does.
- **Upsert belongs to the unique index,** not to the application: `ON CONFLICT`, `ON DUPLICATE KEY UPDATE`, or `MERGE WITH (HOLDLOCK)`.
- **No evaluation order in `WHERE`.** `AND` is not `&&`; only `CASE` fixes the order, and rewriting the predicate is usually better.

**Expected interview questions:**

1. *"Difference between WHERE and HAVING?"* — WHERE filters rows before grouping. HAVING filters groups after aggregation. Aggregate functions can only appear in HAVING (or SELECT).
2. *"What's the logical execution order of a SELECT?"* — FROM → WHERE → GROUP BY → HAVING → SELECT → DISTINCT → ORDER BY → LIMIT. (Written order vs evaluated order differs.)
3. *"`NULL = NULL` — what does it return?"* — `NULL`, not TRUE. Use `IS NULL` to check.
4. *"Why is `LIKE '%X%'` slow?"* — Leading wildcard means the DB can't use a B-tree index on the column. Must scan every row. Use full-text search for substring needs.
5. *"DELETE vs TRUNCATE?"* — DELETE removes rows (logs each, can WHERE-filter, fires triggers). TRUNCATE deallocates the entire table's pages (faster, can't filter, can't fire row triggers, sometimes blocked by replication).
6. *"FLOAT vs DECIMAL for money?"* — DECIMAL — exact, no rounding errors. FLOAT loses precision (`0.1 + 0.2 = 0.30000000000000004`).
7. *"Should every column be NOT NULL?"* — No, but default to NOT NULL. Allow NULL only when it carries meaning (truly unknown vs a sentinel value). Each NULL column doubles your branching code.
8. *"Your query has an index on the column and still scans. Name three reasons."* — A function or cast wrapped around the column; a leading wildcard in `LIKE`; an implicit conversion of the column caused by a mismatched parameter type (`nvarchar` parameter against a `varchar` column in SQL Server). Fourth if they want one: the optimizer decided the range is large enough that a scan is cheaper — which is a correct decision, not a bug.
9. *"Does a `CHECK` constraint stop NULLs?"* — No. A CHECK rejects only what evaluates to FALSE; a NULL operand makes the expression UNKNOWN, which passes. You need `NOT NULL` as well.
10. *"Can you roll back a `TRUNCATE`?"* — On SQL Server and PostgreSQL, yes, inside a transaction. On MySQL, no: it is DDL and causes an implicit commit. Follow-up worth volunteering: it also resets identity/`AUTO_INCREMENT` on SQL Server and MySQL, while PostgreSQL leaves the sequence alone unless you say `RESTART IDENTITY`.
11. *"Does creating a foreign key create an index?"* — On the child column, only in MySQL/InnoDB, which requires one and creates it for you. SQL Server, PostgreSQL and Oracle index the referenced (parent) side because it's a PK or UNIQUE, and leave the referencing column to you — so parent deletes scan the child table until you add it.
12. *"Two users open the same order and both save. How do you stop the second from silently overwriting the first?"* — Put the value you read into the `WHERE` clause (`WHERE id = @id AND version = @expected`) and check rows affected: 1 means you won, 0 means someone changed it first. That's optimistic concurrency — it detects the conflict rather than preventing it. EF Core does exactly this with a concurrency token and turns the 0-row result into `DbUpdateConcurrencyException`; on SQL Server a `rowversion` column with `[Timestamp]` gets you the token for free.
13. *"How do you write an upsert, and why isn't check-then-insert good enough?"* — Check-then-insert has a window between the two statements in which another connection can insert the same key; only the unique index can settle that, and it settles it with a duplicate-key error. Atomic forms: `INSERT ... ON CONFLICT (col) DO UPDATE` (PostgreSQL), `INSERT ... ON DUPLICATE KEY UPDATE` (MySQL, which fires on *any* unique key collision), `MERGE` with `HOLDLOCK` on SQL Server — Microsoft's own docs say `HOLDLOCK` is what prevents unique-key violations when a `MERGE` both inserts and updates the same keys.
14. *"Does `WHERE a > 0 AND b/a > 1.5` protect you from divide-by-zero?"* — No. Predicate evaluation order is undefined in every engine; PostgreSQL's docs call this exact query "untrustworthy" and SQL Server's guidance is that "the order of evaluation for predicates is never guaranteed". `CASE` is the one construct with a defined order; `TRY_CAST`/`TRY_CONVERT` handles the conversion variant on SQL Server 2012+; best of all, rewrite it as `b > 1.5*a` so there is nothing to guard.

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**. Practice answering the cross-questions without re-reading. If you stumble on any cross-Q², go re-read the relevant section.

### Drill 1 — DDL vs DML vs DCL vs TCL

> **Q**: Name the five SQL sublanguages and one statement each.
>
> **A**: **DDL** (Data Definition) — `CREATE`, `ALTER`, `DROP`. **DML** (Data Manipulation) — `INSERT`, `UPDATE`, `DELETE`. **DQL** (Data Query) — `SELECT`. **DCL** (Data Control) — `GRANT`, `REVOKE`. **TCL** (Transaction Control) — `BEGIN`, `COMMIT`, `ROLLBACK`.
>
> **Cross-Q**: Which of these auto-commit and which require explicit transaction handling?
>
> **A**: **DDL auto-commits in most engines** — `CREATE TABLE`, `ALTER TABLE`, `DROP` end any open transaction implicitly in MySQL and Oracle. PostgreSQL is the exception: DDL is fully transactional, so you can `BEGIN`, run `ALTER TABLE`, and `ROLLBACK`. **DML** is transaction-controlled — you start a transaction with `BEGIN`, run inserts/updates, then `COMMIT` or `ROLLBACK`. **DCL** (`GRANT`/`REVOKE`) is typically auto-committed and not safely rolled back. SQL Server splits the difference: most DDL is transactional but some (`CREATE DATABASE`, `BACKUP`) is not.
>
> **Cross-Q²**: Why does it matter that DDL auto-commits in MySQL but not PostgreSQL?
>
> **A**: Migration safety. In PostgreSQL, you can wrap a complex migration (`ALTER TABLE`, data backfill, `CREATE INDEX`) in a single transaction; if any step fails, the whole change rolls back atomically — schema and data stay consistent. In MySQL, each DDL statement commits; a half-completed migration leaves the database in a partial state. This is why PostgreSQL is often preferred for blue-green migrations, and why MySQL migrations need careful step-by-step idempotency design.

### Drill 2 — NULL semantics

> **Q**: What does `WHERE Status = NULL` return?
>
> **A**: **Zero rows.** `Status = NULL` evaluates to `UNKNOWN`, not `TRUE`, regardless of whether `Status` is actually NULL. Use `IS NULL` to check for null: `WHERE Status IS NULL`. Same trap for `!=`, `>`, `<`, `LIKE` — any comparison with NULL yields UNKNOWN.
>
> **Cross-Q**: Why three-valued logic and not just `NULL = NULL → TRUE`?
>
> **A**: NULL means "unknown value" in SQL semantics. Two unknowns can't be proven equal — they might or might not be the same. Returning TRUE would say "yes, these are equal," which is a stronger claim than the data supports. Three-valued logic (TRUE, FALSE, UNKNOWN) preserves the distinction: equality is *unknown*, not *false*. The `WHERE` clause filters to rows where the predicate is TRUE, so UNKNOWN rows are excluded — that's why `= NULL` returns zero rows.
>
> **Cross-Q²**: How does `NOT IN (subquery)` interact with NULL in the subquery?
>
> **A**: **Famous gotcha**: `WHERE x NOT IN (SELECT y FROM t)` returns **zero rows if any `y` is NULL**. Because `x NOT IN (a, b, NULL)` is equivalent to `x <> a AND x <> b AND x <> NULL`, and `x <> NULL` is UNKNOWN, so the whole expression is UNKNOWN, and the row is filtered out. Fix: filter NULLs out of the subquery: `WHERE x NOT IN (SELECT y FROM t WHERE y IS NOT NULL)`, or use `NOT EXISTS` which has cleaner NULL semantics.

### Drill 3 — Three-valued logic in WHERE

> **Q**: A `WHERE` predicate evaluates to UNKNOWN for some rows. Are those rows included or excluded?
>
> **A**: **Excluded.** `WHERE` keeps rows where the predicate is TRUE; UNKNOWN and FALSE rows are filtered out. This means any predicate involving a column that could be NULL silently drops rows you might expect. To include NULLs, use `WHERE expr OR expr IS NULL` or `WHERE COALESCE(expr, ...) = ...`.
>
> **Cross-Q**: How does `HAVING` differ from `WHERE` regarding NULLs?
>
> **A**: Same semantics — UNKNOWN excludes the group. But `HAVING` runs **after grouping**, so it operates on aggregate values, where NULL behavior is different: `COUNT(*)` counts all rows; `COUNT(col)` counts non-NULLs; `SUM(col)` ignores NULLs (treats them as zero for the sum, but returns NULL if all values are NULL). Aggregate functions are NULL-tolerant in a way scalar comparisons aren't.
>
> **Cross-Q²**: I want "all customers who don't have any active orders." How do I write it correctly?
>
> **A**: `SELECT * FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id AND o.is_active = TRUE)`. **Not** `WHERE c.id NOT IN (SELECT customer_id FROM orders WHERE is_active = TRUE)` — if any `customer_id` is NULL in the subquery, the whole `NOT IN` returns no rows. `NOT EXISTS` is correlated subquery and naturally handles NULLs by ignoring rows where the join predicate is UNKNOWN.

### Drill 4 — Constraint types

> **Q**: List the six standard constraint types.
>
> **A**: **PRIMARY KEY** (unique + not null + clustered usually), **FOREIGN KEY** (references another table's PK or unique key), **UNIQUE** (alternate keys; NULLs allowed — exactly one in SQL Server, any number in PostgreSQL and MySQL), **CHECK** (custom validation expression), **NOT NULL** (column-level mandatory), **DEFAULT** (value used when omitted).
>
> **Cross-Q**: What's the difference between PRIMARY KEY and UNIQUE NOT NULL?
>
> **A**: Functionally similar — both enforce uniqueness and prohibit NULL. Differences: (1) only **one** PRIMARY KEY per table; can have many UNIQUE. (2) PRIMARY KEY is **the** identity; it's what foreign keys reference and what the engine clusters on by default (SQL Server). (3) Semantically, PK is the row identity; UNIQUE is an alternate identifier. Use PK for the row's canonical ID, UNIQUE for natural keys like email or username.
>
> **Cross-Q²**: Can a FOREIGN KEY reference a UNIQUE column instead of a PRIMARY KEY?
>
> **A**: **Yes**, but rare. SQL allows FK to reference any column with a `UNIQUE` constraint or `PRIMARY KEY`. Discouraged because (1) PK is the **canonical** identifier — if you have a separate FK target, you've introduced two ways to identify the row, (2) FK to UNIQUE is harder to reason about for maintainers, (3) some ORMs (EF Core, Hibernate) prefer FK-to-PK conventions and need extra config for FK-to-UNIQUE. Defensible only when the parent table has no integer surrogate PK and you must FK against a natural key.

### Drill 5 — VARCHAR vs NVARCHAR vs TEXT

> **Q**: When do you pick `VARCHAR` over `NVARCHAR`?
>
> **A**: **SQL Server**: `VARCHAR` is 1-byte-per-char (or variable for UTF-8 since 2019); `NVARCHAR` is 2-byte UTF-16. Use `VARCHAR` for ASCII-only fields (codes, statuses) to save space; `NVARCHAR` for any user-facing text that might contain non-ASCII (names, addresses, comments). **PostgreSQL**: `VARCHAR` is already Unicode (UTF-8), no `NVARCHAR` needed. **MySQL**: `VARCHAR` is Unicode if the column's charset is UTF-8; the type itself doesn't dictate encoding.
>
> **Cross-Q**: What's the trade-off of `TEXT` vs `VARCHAR(MAX)`?
>
> **A**: `TEXT` (legacy in SQL Server, current in PostgreSQL) is unbounded large-object storage. `VARCHAR(MAX)` (SQL Server, modern) is unbounded but with `VARCHAR`-like semantics. In SQL Server, `TEXT` is deprecated — it has limitations (can't be indexed, requires `READTEXT`/`WRITETEXT` for some operations). Use `VARCHAR(MAX)` or `NVARCHAR(MAX)`. In PostgreSQL, `TEXT` and `VARCHAR` without length spec are identical and idiomatic.
>
> **Cross-Q²**: How does collation affect string comparisons?
>
> **A**: Collation defines **how the engine compares and sorts strings** — case-sensitivity, accent-sensitivity, kana-sensitivity, width-sensitivity. `SQL_Latin1_General_CP1_CI_AS` (SQL Server default) is **case-insensitive**, accent-sensitive. So `'Hello' = 'HELLO'` returns TRUE, but `'café' = 'cafe'` returns FALSE. Picking the wrong collation causes silent bugs: emails should be CI for login lookup, but user-content text fields might want accent-sensitive equality. PostgreSQL uses `COLLATE` per-column or per-query; MySQL uses character set + collation on the column.

### Drill 6 — ORDER BY without LIMIT

> **Q**: `SELECT * FROM orders` without `ORDER BY` — what order are rows returned in?
>
> **A**: **Undefined.** The SQL standard doesn't guarantee any order without an explicit `ORDER BY`. The engine returns rows in whatever order is most efficient for its execution plan — usually clustered-index order if no joins, but it can change between queries based on index usage, parallelism, or storage engine.
>
> **Cross-Q**: I have a clustered PK on `id`. Doesn't `SELECT *` return in `id` order then?
>
> **A**: Often yes, but **not guaranteed**. The engine is free to use a covering index, parallel scan, or hash join that returns rows out of clustered order. Production code that assumes implicit order silently breaks when the engine picks a different plan after a stats update or index addition. Always add `ORDER BY id` if you need a specific order — the cost is small, the correctness gain is real.
>
> **Cross-Q²**: What about `ORDER BY x` where `x` has duplicates — is the secondary order defined?
>
> **A**: **No.** Rows with the same `x` value come back in arbitrary order. For deterministic pagination, you must add a **tiebreaker**: `ORDER BY x, id`. Without a tiebreaker, `LIMIT 10 OFFSET 0` and `LIMIT 10 OFFSET 10` can return overlapping or missing rows if the engine re-evaluates order between queries. This is the classic "pagination shows duplicate items" bug — always include a unique column in `ORDER BY` for paginated queries.

### Drill 7 — ANSI SQL vs vendor dialects

> **Q**: Name three places where SQL Server's T-SQL differs from PostgreSQL's PL/pgSQL.
>
> **A**: (1) **Pagination**: SQL Server `OFFSET N ROWS FETCH NEXT M ROWS ONLY` or `TOP M`; PostgreSQL `LIMIT M OFFSET N`. (2) **String concatenation**: SQL Server `+` or `CONCAT`; PostgreSQL `||`. (3) **Identity columns**: SQL Server `IDENTITY(1,1)` or `INT IDENTITY`; PostgreSQL `SERIAL` (legacy) or `GENERATED BY DEFAULT AS IDENTITY` (modern, ANSI standard since SQL:2003).
>
> **Cross-Q**: Why doesn't ANSI standardization fix this?
>
> **A**: It does, slowly. SQL:1992 standardized core syntax; SQL:1999 added recursive CTEs; SQL:2003 added window functions and standard identity; SQL:2016 added JSON. But (1) vendors had pre-existing dialects they couldn't deprecate without breaking customers, (2) some features are inherently vendor-specific (storage engines, partitioning, hints), and (3) optimizers behave differently even on standard syntax. Cross-vendor SQL is a real cost of multi-database support.
>
> **Cross-Q²**: How would you write a portable pagination query?
>
> **A**: Use the **ANSI-standard `OFFSET ... FETCH`** syntax, supported by SQL Server (2012+), PostgreSQL (8.4+), Oracle (12c+): `SELECT ... ORDER BY id OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY`. MySQL still requires `LIMIT 10 OFFSET 20`. For maximum portability, use a query builder (Dapper.Contrib, EF Core, Knex.js) that handles dialect mapping. Or accept some duplication and have one query per dialect.

### Drill 8 — BIT vs BOOLEAN vs INT vs BIGINT

> **Q**: For a "is_active" flag, what type do you pick in SQL Server vs PostgreSQL?
>
> **A**: **SQL Server**: `BIT` (0/1/NULL, stored efficiently — multiple BITs share a byte). **PostgreSQL**: `BOOLEAN` (TRUE/FALSE/NULL, stored as a byte). Both are the right choice over `INT` because they encode intent — readers see `is_active` and know it's a flag, not a count.
>
> **Cross-Q**: When would you use `INT` for a flag?
>
> **A**: When you might add more states later. `status INT` with `0=draft, 1=published, 2=archived` is more flexible than `is_draft BIT, is_published BIT, is_archived BIT`. Or use an `ENUM` (MySQL, PostgreSQL) or a small lookup table (`status_id` FK to `statuses`). The mistake is starting with `BIT`, then needing a third state, and being forced to either add columns or migrate the type.
>
> **Cross-Q²**: When does `INT` overflow matter and `BIGINT` become necessary?
>
> **A**: `INT` is ~2.1 billion. Approaching this threshold for: (1) auto-incrementing PKs on **high-volume insert tables** (event logs, audit trails, IoT data — Twitter's status IDs crossed the signed 32-bit limit in June 2009), (2) **counters** like Facebook likes globally summed, (3) **timestamps in seconds** since 1970 (`int32` overflows in 2038 — the Y2038 problem; use `BIGINT` or `TIMESTAMP`). For most app data (users, orders, products), `INT` is fine. Migrate proactively when you cross 1B rows to give yourself headroom; the schema change while live is painful.

### Drill 9 — CHAR vs VARCHAR

> **Q**: What's the difference between `CHAR(10)` and `VARCHAR(10)`?
>
> **A**: `CHAR(10)` is **fixed-length, padded with spaces** to 10 characters. `'hi'` is stored as `'hi        '` (8 trailing spaces). `VARCHAR(10)` is **variable-length**, max 10 characters. `'hi'` is stored as 2 characters plus a length header.
>
> **Cross-Q**: How does this affect comparisons?
>
> **A**: **This is a collation property, not a universal rule, and the engines disagree.** For `CHAR(n)` the answer is consistent — trailing spaces are ignored, and PostgreSQL says so directly: "Trailing spaces are treated as semantically insignificant and disregarded when comparing two values of type `character`." For variable-length strings it splits:
>
> | Engine | `'hi' = 'hi   '` on a `VARCHAR`/`TEXT` column |
> |---|---|
> | **PostgreSQL** | **FALSE.** "Note that trailing spaces *are* semantically significant in `character varying` and `text` values, and when using pattern matching, that is `LIKE` and regular expressions." |
> | **SQL Server** | **TRUE** — it follows the ANSI/ISO SQL-92 padding rule, padding the shorter string to match before comparing, so `'abc'` and `'abc '` are equivalent for most comparisons (Microsoft KB 316626, *INF: How SQL Server Compares Strings with Trailing Spaces*). The documented exception is `LIKE`: when the pattern on the right carries a trailing space, SQL Server does *not* pad. Note also that `SET ANSI_PADDING` governs whether trailing blanks are trimmed on insert — it does not change comparison. |
> | **MySQL** | **Depends on the collation's pad attribute.** "For `PAD SPACE` collations, trailing spaces are insignificant in comparisons" and "Most MySQL collations have a pad attribute of `PAD SPACE`" — but "`NO PAD` collations treat trailing spaces as significant in comparisons, like any other character", and "The Unicode collations based on UCA 9.0.0 and higher have a pad attribute of `NO PAD`", which is the `utf8mb4_0900_*` family introduced in MySQL 8.0. |
>
> So the same `WHERE code = 'AB '` can match on SQL Server, miss on PostgreSQL, and change behaviour on MySQL when someone modernises a column's collation. Concatenation still reveals the padding everywhere: `'X' || CHAR_COL || 'Y'` produces `'Xhi        Y'` from `CHAR(10)` but `'XhiY'` from `VARCHAR(10)`. Trim on input rather than relying on comparison semantics you would have to look up.
>
> **Cross-Q²**: When is `CHAR` actually the right choice?
>
> **A**: Almost never in modern schemas. Two narrow cases: (1) **truly fixed-length codes** like ISO country codes (`CHAR(2)`), USPS state codes (`CHAR(2)`), MICR routing numbers — the data is always exactly that length, and you save a few bytes per row by not storing the length header. (2) **alignment-sensitive bulk-load data** where downstream consumers expect fixed-width records. Otherwise, prefer `VARCHAR` — modern engines handle variable-length storage efficiently, and the space savings of `CHAR` are negligible for typical data.

### Drill 10 — DATE vs DATETIME vs DATETIME2 vs DATETIMEOFFSET

> **Q**: Walk me through SQL Server's date/time types.
>
> **A**: **`DATE`**: date only, 3 bytes. **`TIME`**: time only, 3-5 bytes (precision-dependent). **`DATETIME`**: legacy date+time, 8 bytes, 3.33 ms precision, range 1753-9999, **no timezone**. **`DATETIME2`**: modern replacement, 6-8 bytes, 100 ns precision, range 0001-9999, no timezone — **always prefer over `DATETIME`**. **`DATETIMEOFFSET`**: `DATETIME2` plus a `±HH:MM` timezone offset, 8-10 bytes. **`SMALLDATETIME`**: 4 bytes, minute precision, rarely used.
>
> **Cross-Q**: Why prefer `DATETIME2` over `DATETIME`?
>
> **A**: (1) **Wider range** (back to year 0001), (2) **higher precision** (100 ns vs 3.33 ms — `DATETIME` rounds to .000, .003, or .007 second fractions, causing subtle bugs in timestamp comparisons), (3) **smaller storage** at lower precisions (`DATETIME2(0)` is 6 bytes vs `DATETIME`'s 8), (4) ANSI-compliant. `DATETIME` is legacy; `DATETIME2` is the post-2008 standard. EF Core defaults to `DATETIME2` for new mappings.
>
> **Cross-Q²**: When do you need `DATETIMEOFFSET` vs `DATETIME2` with UTC convention?
>
> **A**: **`DATETIMEOFFSET`** when you need to preserve the **original local time** plus the offset — e.g., recording when a user submitted a form in their local timezone, where both "2:00 PM their time" and "the UTC equivalent" matter. **`DATETIME2` with UTC convention** (always store UTC, convert at the edge) when you only care about the absolute instant and the user's local time is computed on display. Most apps choose the latter — simpler, no timezone confusion. `DATETIMEOFFSET` shines for audit logs across regions, scheduling apps, and anywhere "what time was it locally" is part of the data.

### Drill 11 — Character encoding and UTF-8 in SQL Server

> **Q**: Is `VARCHAR` in SQL Server Unicode-safe?
>
> **A**: **Depends on the version and column collation.** Pre-2019: `VARCHAR` was code-page-based (single byte, locale-specific), only `NVARCHAR` was Unicode (UTF-16). SQL Server **2019+** added **UTF-8 collations** (e.g., `Latin1_General_100_CI_AS_SC_UTF8`) — when applied to `VARCHAR`, it stores UTF-8, supporting full Unicode at smaller storage cost than UTF-16 for mostly-ASCII text.
>
> **Cross-Q**: Why would I pick UTF-8 `VARCHAR` over `NVARCHAR` (UTF-16)?
>
> **A**: Storage savings for ASCII-heavy text. UTF-8 uses 1 byte for ASCII characters and 2-4 for non-ASCII; UTF-16 uses 2 bytes for everything in the BMP and 4 for supplementary. For mostly-English content, UTF-8 `VARCHAR` can be **half the storage** of `NVARCHAR`. Trade-off: comparisons and length calculations are slightly more complex (variable-byte encoding), and joins with `NVARCHAR` columns require collation conversion that disables index seeks.
>
> **Cross-Q²**: I migrated from `NVARCHAR` to UTF-8 `VARCHAR` and a join is now slow. Why?
>
> **A**: **Implicit collation conversion** disables index seeks. If you join `t1.utf8_varchar = t2.nvarchar_col`, the engine must convert one side to the other's collation, which makes the predicate non-sargable — full scan. Fix: either migrate **both** columns to matching collation, or **explicitly convert** with `CAST` on the small side. The same trap exists for any cross-collation comparison, not just UTF-8/UTF-16.

### Drill 12 — Identity vs sequence vs GUID for PKs

> **Q**: I need to generate unique IDs for a new table. Identity, sequence, or GUID?
>
> **A**: **Identity** (SQL Server `IDENTITY(1,1)`, PostgreSQL `GENERATED AS IDENTITY`): auto-increment per insert, simple, fast, sequential — index-friendly. **Sequence** (`CREATE SEQUENCE`): independent of any table, can be shared, can pre-allocate ranges for batch inserts. **GUID/UUID** (`UNIQUEIDENTIFIER` / `UUID`): 128-bit, generated client-side or server-side, globally unique without coordination, but non-sequential by default (causes index fragmentation).
>
> **Cross-Q**: When does GUID beat identity?
>
> **A**: (1) **Distributed systems** where multiple writers can't coordinate to assign IDs — every node can generate locally without conflict. (2) **Client-generated IDs** for offline-first apps that sync later. (3) **Security**: identity IDs leak count info (`/orders/12345` tells you there are ~12k orders); GUIDs don't enumerate. (4) **Merge scenarios** where data from multiple sources combines without collision. Trade-off: 16 bytes vs 4-8, slower joins, fragmented indexes unless using sequential GUIDs (`NEWSEQUENTIALID` in SQL Server, UUIDv7 in modern stacks).
>
> **Cross-Q²**: What's `NEWSEQUENTIALID` / UUIDv7 and why does it matter?
>
> **A**: Standard random GUIDs (UUIDv4) cause **index fragmentation** because new rows insert at random positions in the clustered index — pages split, B-tree rebalances, write amplification spikes. `NEWSEQUENTIALID` (SQL Server) and UUIDv7 (RFC 9562, 2024) produce GUIDs that are **time-ordered** in the first bits, so new rows append to the end of the clustered index like identity does. You get GUID benefits (uniqueness across nodes, no enumeration) without the index pain. UUIDv7 is becoming the new default for distributed systems.

### Drill 13 — Integer overflow and BIGINT thresholds

> **Q**: At what row count should I switch from `INT` to `BIGINT` for a PK?
>
> **A**: Practical threshold: **proactively migrate before crossing 1 billion rows** to give yourself headroom. INT max is 2,147,483,647 (~2.1B). Migrating a heavily-trafficked column while live is **expensive** — every row's PK changes, foreign keys cascade, indexes rebuild, downstream caches invalidate. Do it when you have time, not when you're at 1.9B and panicking.
>
> **Cross-Q**: What's the classic public example of int overflow in production?
>
> **A**: **Twitter, June 2009 — the "Twitpocalypse"**: status IDs crossed the signed 32-bit maximum (2,147,483,647). Twitter itself was fine; what broke were the **third-party clients** that had stored those IDs in signed 32-bit integers, where the next ID appeared as a negative number. Twitter forced the rollover at a chosen hour (12 June 2009) rather than let it happen overnight, so that engineers on all sides were awake for it. A second round followed in September 2009 as IDs approached the *unsigned* 32-bit limit and clients that had "fixed" it by switching to unsigned hit the same wall again. (Twitter's Snowflake scheme — 64-bit, time-ordered IDs — came later, in 2010, and was about generating IDs across many machines without a central auto-increment; it is a different problem that happens to be solved by a wider type.) The transferable lesson: the overflow breaks whoever holds the narrowest copy of the value, which includes clients, caches and export files you don't control. For any table that might reach billions of rows (events, messages, audit logs, IoT readings), start at `BIGINT`.
>
> **Cross-Q²**: What about counter columns that go negative when they overflow?
>
> **A**: In SQL Server, integer overflow on increment throws an arithmetic overflow error and **aborts the statement** — the increment fails, the row stays at MAX. In MySQL, it depends on `sql_mode`: `STRICT_TRANS_TABLES` raises an error; without it, the column is **clamped to MAX** (silent saturation) or wraps (engine-dependent). PostgreSQL throws. The safe defaults are strict modes everywhere. For counters that might exceed INT, switch to `BIGINT` proactively; for application-level counters, use atomic increment with overflow checks.

### Drill 14 — DEFAULT value gotchas

> **Q**: I added a `created_at` column with `DEFAULT CURRENT_TIMESTAMP`. Does it backfill existing rows?
>
> **A**: **Depends on the engine, and on whether the new column is nullable.** SQL Server draws the line at `WITH VALUES`: "If the new column allows null values and you add a default definition with the new column, you can use `WITH VALUES` to store the default value in the new column for each existing row in the table." Omit `WITH VALUES` and the existing rows keep the NULL they would have had anyway — the same page's baseline case is that "if the new column allows null values and you don't specify a default, the new column contains a null value for each row in the table". For a `NOT NULL` column there is no choice: "If the new column doesn't allow null values and the table isn't empty, you must add a `DEFAULT` definition with the new column. The new column automatically loads with the default value in the new columns in each existing row."
>
> PostgreSQL **does backfill**, nullable or not: "When a column is added with `ADD COLUMN` and a non-volatile `DEFAULT` is specified, the default value is evaluated at the time of the statement and the result stored in the table's metadata, where it will be returned when any existing rows are accessed." Existing rows show the default — one value, evaluated once, with no table rewrite. A *volatile* default (`clock_timestamp()`, `random()`) is the expensive case: it "will cause the entire table and its indexes to be rewritten". MySQL likewise applies the default to existing rows.
>
> The rule to carry: only SQL Server leaves existing rows NULL, and only when the column is nullable and you omitted `WITH VALUES`. "The default applies to new rows only" is not the general behaviour.
>
> **Cross-Q**: How do you safely add a NOT NULL column with a default?
>
> **A**: Phased. (1) Add as **nullable** with no default: `ALTER TABLE t ADD created_at DATETIME2 NULL`. (2) **Backfill**: `UPDATE t SET created_at = GETUTCDATE() WHERE created_at IS NULL` — in batches if the table is large to avoid blocking. (3) **Tighten** to NOT NULL with default for future inserts: `ALTER TABLE t ALTER COLUMN created_at DATETIME2 NOT NULL` + add the default constraint. This pattern works across engines and is online-friendly. Worth saying out loud that it isn't always necessary: on PostgreSQL a non-volatile default stores one evaluated value in the table's metadata with no rewrite, so `ADD COLUMN ... NOT NULL DEFAULT now()` is already a cheap operation there — the phased version earns its keep when the default is volatile, or when you're on an engine or version that rewrites the table.
>
> **Cross-Q²**: What's the gotcha with `DEFAULT CURRENT_TIMESTAMP` and replication?
>
> **A**: Replicated databases that re-execute statements (statement-based replication, like older MySQL) can produce **different timestamps on each replica** because `CURRENT_TIMESTAMP` evaluates at execution time on each node. Row-based replication ships the actual values, avoiding this. For correctness, prefer (1) computing timestamps in the application layer once and inserting the literal value, or (2) row-based replication mode, or (3) `DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')` to at least pin the timezone. The "same default everywhere" assumption breaks in statement-replicated clusters.

### Drill 15 — Putting it together: schema design for a new entity

> **Q**: Design the columns for a new `audit_logs` table. Walk me through your type choices.
>
> **A**: `id BIGINT IDENTITY PRIMARY KEY` (high-volume table, INT would overflow), `actor_id INT NOT NULL` (FK to users, INT plenty for user count), `action NVARCHAR(50) NOT NULL` (short codes, Unicode-safe), `details NVARCHAR(MAX)` (variable-length JSON or text), `created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()` (UTC, ns precision), `created_at_offset DATETIMEOFFSET NULL` (preserve original timezone if relevant), `ip_address VARCHAR(45) NULL` (max IPv6 length, ASCII-only so VARCHAR not NVARCHAR).
>
> **Cross-Q**: Why not just one `created_at DATETIMEOFFSET`?
>
> **A**: Two reasons. (1) Most queries filter on UTC time (`WHERE created_at BETWEEN ... AND ...`) — a separate `DATETIME2 UTC` column is leaner for indexing and comparisons. (2) `DATETIMEOFFSET` joins and indexes can be tricky if some rows have offsets and others don't. The split lets the UTC column be the canonical sort/filter axis while the offset column is optional context. If you only ever query UTC, drop `created_at_offset` entirely.
>
> **Cross-Q²**: How would you add an index for "show recent audit logs for a user"?
>
> **A**: `CREATE INDEX IX_audit_logs_actor_created ON audit_logs(actor_id, created_at DESC) INCLUDE (action, details)`. The composite key (`actor_id`, `created_at DESC`) supports `WHERE actor_id = X ORDER BY created_at DESC LIMIT N` as an index seek + range scan, no sort. `INCLUDE (action, details)` makes it a **covering index** — the query is satisfied entirely from the index without touching the table. For a high-traffic audit table, this is the difference between sub-millisecond and hundreds of milliseconds. Watch the index size; covering indexes on `NVARCHAR(MAX)` can balloon storage.

</details>

## Cheat Sheet

- **Five sublanguages**: DDL/DML/DQL/DCL/TCL; the names show up in interviews and reviews.
- **Logical execution**: FROM -> WHERE -> GROUP BY -> HAVING -> SELECT -> DISTINCT -> ORDER BY -> LIMIT.
- **NULL semantics**: three-valued logic; `= NULL` always returns 0 rows; use `IS NULL`.
- **DECIMAL for money**: never `FLOAT`/`REAL`; binary rounding makes 0.1 + 0.2 != 0.3.
- **TIMESTAMPTZ / DATETIMEOFFSET**: store UTC + offset; never naive `TIMESTAMP` for events.
- **Six constraints**: PRIMARY KEY, FOREIGN KEY, UNIQUE, NOT NULL, CHECK, DEFAULT.
- **Cascades**: CASCADE for owned children, SET NULL for severable, RESTRICT for protected.
- **LIKE with leading %**: non-sargable; index unusable; use FTS or trigram (`pg_trgm`) instead.
- **OFFSET pagination**: O(N+M); deteriorates as offset grows; cursor pagination is O(M).
- **NOT NULL by default**: each nullable column doubles branching code; opt in to nullable explicitly.
- **CHECK rejects only FALSE**: UNKNOWN passes, so a nullable column slips through its own range check. Pair CHECK with NOT NULL.
- **UNIQUE + NULL**: one NULL in SQL Server; many in PostgreSQL/MySQL (PostgreSQL 15+ can say `NULLS NOT DISTINCT`). Soft delete wants a filtered/partial unique index.
- **FK ≠ index**: only MySQL/InnoDB indexes the referencing column for you; elsewhere the parent delete scans the child.
- **Implicit conversion**: lower precedence converts. `nvarchar` outranks `varchar` in SQL Server, so an EF Core/Dapper `string` parameter against a `varchar` column converts the column and loses the seek.
- **TRUNCATE**: rollback-able on SQL Server and PostgreSQL, implicit commit on MySQL; resets identity on SQL Server/MySQL, not on PostgreSQL unless `RESTART IDENTITY`; takes an exclusive table lock everywhere.
- **NULL sort order**: first in SQL Server and MySQL ascending, last in PostgreSQL; `NULLS FIRST/LAST` syntax is available in PostgreSQL and Oracle but not in SQL Server or MySQL.
- **Batch the big DML**: loop around set-based batches; SQL Server escalates to a table lock at 5,000 locks on one table (Microsoft Learn).
- **Integer division truncates** on SQL Server and PostgreSQL (`5/2` → `2`); MySQL's `/` is fractional and `DIV` is the integer form. SQL Server's `AVG(int_col)` returns `int`. Widen before dividing, not after.
- **DML returns rows**: `OUTPUT` with `INSERTED`/`DELETED` (SQL Server), `RETURNING` (PostgreSQL), `LAST_INSERT_ID()` (MySQL — first id of a multi-row insert, per connection).
- **Rows affected = compare-and-swap**: `WHERE id = @id AND version = @v`; 0 rows means someone else won. EF Core turns that into `DbUpdateConcurrencyException`.
- **Upsert**: `ON CONFLICT` (PostgreSQL, needs an inferable unique index), `ON DUPLICATE KEY UPDATE` (MySQL, fires on any unique key), `MERGE WITH (HOLDLOCK)` (SQL Server — without the hint it can raise duplicate-key errors).
- **No predicate ordering**: `AND` doesn't short-circuit; use `CASE` or `TRY_CAST`, or rewrite so no guard is needed.
- **Untrusted constraints**: `WITH NOCHECK` (SQL Server, `is_not_trusted`) and `NOT VALID` (PostgreSQL, `convalidated`) govern new rows only; SQL Server's optimizer ignores them until validated.
- **`IS DISTINCT FROM`**: NULL-safe equality — PostgreSQL always, SQL Server 2022+, MySQL spells it `<=>`.
- **`ORDER BY` in a view/subquery** doesn't survive into the outer query, even with `TOP 100 PERCENT`.

## Walkthrough — An UPDATE without WHERE in production

<details>
<summary>📖 Click to expand — worked walkthrough scenario</summary>

**Problem**: A junior runs `UPDATE orders SET status = 'Cancelled';` against the production replica via `psql` instead of staging. Two million orders flip status; customer support phones are ringing within minutes.

**Diagnosis**: The on-call senior immediately checks if a transaction is open: `SELECT pid, state, xact_start, query FROM pg_stat_activity WHERE state LIKE '%transaction%';`. The session shows `idle in transaction` — there's no open transaction wrapping the bad UPDATE, so it's already committed. They check `pg_stat_database` for the database's `tup_updated` to confirm the scale, then look at backup recency: `SELECT backup_label, time FROM pg_stat_archiver`. Last full base backup was 6 hours ago; WAL archiving is current, so PITR is feasible.

**Fix**: Restore the affected rows from PITR to a sandbox cluster, then re-apply the correct status:

```bash
# 1. Spin up a temp cluster restored to T-1 minute
pg_basebackup -D /tmp/restore -X stream
recovery_target_time = '2026-05-08 14:32:00'

# 2. Extract just the orders that were touched
COPY (SELECT id, status FROM orders WHERE updated_at >= '2026-05-08 14:32:00')
TO '/tmp/orders_pre.csv' CSV HEADER;

# 3. Apply back to prod inside a transaction
BEGIN;
UPDATE orders o
SET status = pre.status
FROM tmp_orders_pre pre
WHERE o.id = pre.id;
COMMIT;
```

Then enforce a guard: `idle_in_transaction_session_timeout` and a `psql` profile that aliases destructive commands inside `BEGIN`.

**Why it works**: PITR replays the WAL up to a point in time, so an authoritative pre-disaster snapshot exists. Joining back via `id` lets you fix only the affected rows without restoring the whole DB.

</details>

## Self-test

<details><summary>1. Why can't <code>WHERE</code> reference an alias defined in <code>SELECT</code>?</summary>

Logical execution order: WHERE evaluates at step 2, before SELECT computes at step 5. The alias literally doesn't exist yet. To filter on a computed value, repeat the expression in WHERE, use a CTE/subquery, or filter in HAVING after grouping.
</details>

<details><summary>2. Trade-off: <code>FOREIGN KEY ... ON DELETE CASCADE</code> vs application-level cascade.</summary>

DB-level cascades are atomic and bypass-proof: any path that deletes a parent (manual SQL, batch jobs, ETL) cleans children. App cascades add flexibility (logging, soft-delete, conditional behaviour) but break when bypassed. Mature systems use DB cascades for correctness invariants and app logic for soft-delete or audit needs.
</details>

<details><summary>3. <code>SELECT COUNT(*)</code> vs <code>SELECT COUNT(col)</code> on a column with NULLs.</summary>

`COUNT(*)` counts every row (NULL-included); `COUNT(col)` counts non-NULL values of `col`. The difference is the count of NULLs in that column. Use `COUNT(*)` for "how many rows" and `COUNT(col)` for "how many have a value here".
</details>

<details><summary>4. Why is <code>WHERE created_at::date = '2026-05-08'</code> slower than <code>WHERE created_at &gt;= '2026-05-08' AND created_at &lt; '2026-05-09'</code>?</summary>

The cast wraps `created_at` in a function call; B-tree indexes on the raw column become unusable, forcing a sequential scan. Range predicates over the raw column allow index-range seek. Same lesson applies to `LOWER(name)`, `EXTRACT(year FROM ...)`, etc. - either rewrite the predicate or build an expression index.
</details>

<details><summary>5. A column has 95% NULLs. What's the trade-off between leaving it nullable and replacing with a sentinel?</summary>

NULL preserves the "unknown" semantic but forces every consumer to handle three-valued logic and `COALESCE` everywhere. Sentinels (e.g., empty string, 0, sentinel date) simplify queries but conflate "unknown" with a real value, eventually breaking queries when the sentinel is itself a valid input. The right answer depends on whether the distinction matters; most teams pick NOT NULL with a sentinel only when nothing else makes sense.
</details>

<details><summary>6. In SQL Server, <code>WHERE order_id = '4711'</code> on an <code>int</code> column seeks, but <code>WHERE sku = @p</code> on a <code>varchar</code> column scans when <code>@p</code> is <code>nvarchar</code>. Why the difference?</summary>

Data type precedence decides which side of the comparison converts, and the lower-precedence side is the one that moves. `int` outranks `varchar`, so the string literal is converted once, before the seek — the column is untouched and the index still works. `nvarchar` outranks `varchar`, so in the second case the *column* is converted, on every row, which wraps the indexed key in `CONVERT_IMPLICIT` and forces a scan. Fix it at the source: `IsUnicode(false)` (EF Core) or `DbString { IsAnsi = true }` (Dapper) so the parameter matches the column.
</details>

<details><summary>7. Your table has <code>CHECK (discount_percent BETWEEN 0 AND 100)</code> and you still find rows with no usable discount value. What happened?</summary>

The column is nullable and a NULL arrived. A CHECK constraint rejects a row only when the predicate evaluates to FALSE; with a NULL operand the predicate is UNKNOWN, which is not FALSE, so the row is accepted. This is the mirror image of `WHERE`, which keeps a row only when the predicate is TRUE. If the intent is "always a valid percentage", you need `NOT NULL` alongside the CHECK.
</details>

<details><summary>8. Can you roll back a <code>TRUNCATE</code>? What else changes between engines?</summary>

SQL Server and PostgreSQL: yes, inside a transaction. MySQL: no — TRUNCATE is DDL there and causes an implicit commit, which also ends any transaction you had open. Identity: reset on SQL Server and MySQL, untouched on PostgreSQL unless you write `RESTART IDENTITY`. Foreign keys: all three refuse to truncate a table other tables reference (PostgreSQL will do it with `CASCADE` or if every referencing table is truncated in the same statement). Triggers: none of them fire row-level delete triggers; PostgreSQL alone offers `ON TRUNCATE` triggers. And in every engine TRUNCATE takes an exclusive table lock — it is short, not gentle.
</details>

<details><summary>9. <code>SELECT DISTINCT country</code> returns 12 rows; <code>SELECT COUNT(DISTINCT country)</code> returns 11. Both are right — why?</summary>

Some rows have a NULL country. `DISTINCT` treats NULLs as equal to each other and returns one NULL row among the 12. `COUNT(DISTINCT country)` is an aggregate, and aggregates ignore NULL inputs entirely, so it counts only the 11 real values. The same split explains `COUNT(*)` versus `COUNT(col)`.
</details>

<details><summary>10. The same <code>ORDER BY name ASC ... 10 rows</code> query returns different rows on SQL Server and PostgreSQL. The data is identical. Why?</summary>

`name` is nullable and the engines disagree about where NULLs belong. SQL Server treats NULL as the lowest possible value, so the first page is full of NULLs; PostgreSQL sorts NULLs as if larger than any value, so they land at the end (MySQL matches SQL Server). PostgreSQL and Oracle let you say which you want with `NULLS FIRST`/`NULLS LAST`; SQL Server and MySQL have no such syntax, so you emulate it with a leading sort expression such as `ORDER BY CASE WHEN name IS NULL THEN 1 ELSE 0 END, name`.
</details>

<details><summary>11. A conversion-rate column computed as <code>converted / visits</code> reads 0 for nearly every row. Both columns are <code>INT</code>. What's happening, and does the answer change by engine?</summary>

Integer division. On SQL Server "if an integer *dividend* is divided by an integer *divisor*, the result is an integer that has any fractional part of the result truncated"; PostgreSQL's operator table says the same ("division truncates the result towards zero", `5 / 2` → `2`). Any true ratio below 1 becomes 0. MySQL is the exception — `/` produces a fractional result there, and `DIV` is the separate integer-division operator. The fix is to widen an operand before dividing (`converted * 1.0 / visits`), because casting the result is too late. The same trap hits SQL Server's `AVG` over an `int` column, which the return-type table maps back to `int`.
</details>

<details><summary>12. Two users load the same order and both save 30 seconds apart. Both saves report success and the first user's change is gone. What mechanism was missing, and how would you add it?</summary>

The lost update. Nothing in the second `UPDATE` referenced the state the user actually read, so it overwrote it. Add the read value to the predicate — `UPDATE orders SET ... WHERE id = @id AND version = @expected_version` — and treat the rows-affected count as the result: 1 means you won, 0 means the row changed under you. That's optimistic concurrency: it detects the conflict rather than preventing it. EF Core implements exactly this with a concurrency token, and its docs describe the outcome — "the UPDATE fails to find any matching rows and reports that zero were affected. As a result, EF Core's `SaveChanges()` throws a `DbUpdateConcurrencyException`". On SQL Server, a `rowversion` column mapped with `[Timestamp]` supplies the token automatically. Note the count only carries this meaning when the `WHERE` targets one row by key; after a bulk update, 0 rows just means nothing matched.
</details>

<details><summary>13. Your import does <code>SELECT</code> then <code>INSERT</code> per key and starts throwing duplicate-key errors when it goes multi-threaded. Why can't you fix this in application code, and what does each engine offer?</summary>

Between the `SELECT` and the `INSERT` another connection can insert the same key; the application has no way to hold anything across that gap. The unique index is the only component that can settle two simultaneous inserts, and it settles it by rejecting one. Atomic forms: PostgreSQL `INSERT ... ON CONFLICT (col) DO UPDATE`, which "guarantees an atomic INSERT or UPDATE outcome ... even under high concurrency" and needs a conflict target inferable from a unique index; MySQL `INSERT ... ON DUPLICATE KEY UPDATE`, which triggers on *any* unique key collision on the table, not just the intended one; SQL Server `MERGE`, which per Microsoft's own docs needs `HOLDLOCK` — "specifying the `HOLDLOCK` will prevent against unique key violations" — because `MERGE` alone is not safe when it both inserts and updates the same keys.
</details>

<details><summary>14. <code>WHERE data_type = 'int' AND CAST(value AS INT) > 100</code> ran for three years, then started failing with conversion errors after an unrelated index was added. Explain.</summary>

SQL has no guaranteed predicate evaluation order and `AND` does not short-circuit left to right. The type filter was never protecting the cast; it just happened to be applied first in the plan the optimizer had been choosing. PostgreSQL states the rule plainly — evaluation order "is not defined", and boolean expressions in `WHERE` "can be reorganized in any manner allowed by the laws of Boolean algebra" — and SQL Server's own guidance is that "the order of evaluation for predicates is never guaranteed". The new index changed the plan, the cast moved ahead of the filter, and rows that were never meant to reach it did. `CASE` is the one construct with a defined order; `TRY_CAST`/`TRY_CONVERT` (SQL Server 2012+) returns NULL instead of raising; the durable fix is a typed column, because the query depends on a correlation between two columns that the optimizer cannot know about.
</details>

<details><summary>15. A constraint is present in the schema, the data violates it, and nothing ever raised an error. How?</summary>

It was added without validating the existing rows — `WITH NOCHECK` on SQL Server, `NOT VALID` on PostgreSQL — so it only ever governed rows written after it appeared. SQL Server records this as `is_not_trusted = 1` in `sys.check_constraints` and `sys.foreign_keys` ("has not been verified by the system"), and additionally stops reasoning from it: "The query optimizer doesn't consider constraints that are defined `WITH NOCHECK`." PostgreSQL records `pg_constraint.convalidated = false`. Both offer the completion step — `ALTER TABLE t WITH CHECK CHECK CONSTRAINT ALL` and `VALIDATE CONSTRAINT` respectively — and both will fail loudly if the historical rows really are bad, which is the point of running it.
</details>

## Cross-references

- [Joins & Set Operations](./02-joins-and-set-operations.md) — combining tables.
- [Aggregation & Grouping](./03-aggregation-and-grouping.md) — GROUP BY / HAVING.
- [Schema Design & Normalization](./08-schema-design-and-normalization.md) — applying constraints in real schemas.
- [Indexes & Query Optimization](./06-indexes-and-query-optimization.md) — making queries fast.
- [EF Core](../01-ef-core.md) — the ORM that generates these queries.
- [LINQ](../02-linq.md) — what becomes SQL.

## Sources

<details>
<summary>📚 Click to expand — sources and further reading</summary>

- *SQL in 10 Minutes a Day* by Ben Forta — concise intro for absolute beginners.
- PostgreSQL [Tutorial](https://www.postgresql.org/docs/current/tutorial.html) — vendor-neutral foundation.
- Microsoft Learn — [T-SQL Basics](https://learn.microsoft.com/en-us/sql/t-sql/) for SQL Server specifics.
- *Learning SQL* by Alan Beaulieu (O'Reilly, 3rd ed.) — comprehensive vendor-neutral tour.

Cited on this page:

- Microsoft Learn — [Data type precedence (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/data-types/data-type-precedence-transact-sql) — which side of a comparison converts.
- Microsoft Learn — [/ (Division) (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/divide-transact-sql) and [AVG (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/functions/avg-transact-sql) — integer division truncates; `AVG` of an `int` returns `int`.
- Microsoft Learn — [OUTPUT clause (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/output-clause-transact-sql) — `INSERTED`/`DELETED`, the trigger restriction, and the limits on an `OUTPUT INTO` target.
- Microsoft Learn — [MERGE (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/statements/merge-transact-sql) — the concurrency-considerations section, `HOLDLOCK`, and when discrete statements beat `MERGE`.
- Microsoft Learn — [ALTER TABLE (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/statements/alter-table-transact-sql) — `WITH VALUES` when adding a column with a default; `WITH NOCHECK` and the optimizer ignoring untrusted constraints.
- Microsoft Learn — [sys.check_constraints](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-check-constraints-transact-sql) and [sys.foreign_keys](https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/sys-foreign-keys-transact-sql) — the `is_not_trusted` flag.
- Microsoft Learn — [IS \[NOT\] DISTINCT FROM (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/queries/is-distinct-from-transact-sql) — SQL Server 2022+, the truth table, and the portable expansion.
- Microsoft Learn — [TRY_CONVERT (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/functions/try-convert-transact-sql) — returns NULL instead of raising on a failed cast.
- Microsoft (archived engineering blog) — [Predicate ordering is not guaranteed](https://learn.microsoft.com/en-us/archive/blogs/sqlprogrammability/predicate-ordering-is-not-guaranteed) (2006) — the worked conversion-error example and the `CASE` fix.
- Microsoft KB 316626 — [INF: How SQL Server Compares Strings with Trailing Spaces](https://mskb.pkisolutions.com/kb/316626) — ANSI SQL-92 padding on comparison, and the `LIKE` exception.
- Microsoft Learn — [Unique constraints and check constraints](https://learn.microsoft.com/en-us/sql/relational-databases/tables/unique-constraints-and-check-constraints) — one NULL per UNIQUE column; CHECK rejects only FALSE.
- Microsoft Learn — [TRUNCATE TABLE (Transact-SQL)](https://learn.microsoft.com/en-us/sql/t-sql/statements/truncate-table-transact-sql) — rollback inside a transaction, identity reseed, FK and replication limits, table lock.
- Microsoft Learn — [Transaction locking and row versioning guide](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-transaction-locking-and-row-versioning-guide) — the 5,000-lock escalation threshold.
- Microsoft Learn — [ORDER BY clause](https://learn.microsoft.com/en-us/sql/t-sql/queries/select-order-by-clause-transact-sql) — NULLs as lowest values; stable `OFFSET`/`FETCH` paging requires a unique sort.
- Microsoft Learn — [SET ANSI_NULLS](https://learn.microsoft.com/en-us/sql/t-sql/statements/set-ansi-nulls-transact-sql) — `= NULL` under ANSI_NULLS OFF, and its deprecation (always ON from SQL Server 2017).
- PostgreSQL docs — [Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html), [TRUNCATE](https://www.postgresql.org/docs/current/sql-truncate.html), [Sorting Rows](https://www.postgresql.org/docs/current/queries-order.html), [Index Types](https://www.postgresql.org/docs/current/indexes-types.html) (B-tree with `LIKE`, the C-locale condition) and [Operator Classes](https://www.postgresql.org/docs/current/indexes-opclass.html) (`text_pattern_ops`).
- PostgreSQL docs — [PostgreSQL 18 release notes](https://www.postgresql.org/docs/release/18.0/) — `OLD`/`NEW` support added to `RETURNING`.
- PostgreSQL docs — [ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html) (`ADD COLUMN` defaults, `NOT VALID` / `VALIDATE CONSTRAINT`), [INSERT](https://www.postgresql.org/docs/current/sql-insert.html) (`ON CONFLICT`, `EXCLUDED`), [Expression Evaluation Rules](https://www.postgresql.org/docs/current/sql-expressions.html), [Mathematical Functions and Operators](https://www.postgresql.org/docs/current/functions-math.html), [Character Types](https://www.postgresql.org/docs/current/datatype-character.html) (trailing spaces), [pg_constraint](https://www.postgresql.org/docs/current/catalog-pg-constraint.html).
- MySQL 8.4 Reference Manual — [Type Conversion in Expression Evaluation](https://dev.mysql.com/doc/refman/8.4/en/type-conversion.html), [FOREIGN KEY Constraints](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html), [TRUNCATE TABLE](https://dev.mysql.com/doc/refman/8.4/en/truncate-table.html), [Working with NULL Values](https://dev.mysql.com/doc/refman/8.4/en/working-with-null.html).
- MySQL 8.4 Reference Manual — [Arithmetic Operators](https://dev.mysql.com/doc/refman/8.4/en/arithmetic-functions.html) (`/` vs `DIV`), [INSERT ... ON DUPLICATE KEY UPDATE](https://dev.mysql.com/doc/refman/8.4/en/insert-on-duplicate.html), [Information Functions](https://dev.mysql.com/doc/refman/8.4/en/information-functions.html) (`LAST_INSERT_ID()`), [Comparison Functions and Operators](https://dev.mysql.com/doc/refman/8.4/en/comparison-operators.html) (`<=>`), [Binary Collations](https://dev.mysql.com/doc/refman/8.4/en/charset-binary-collations.html) (`PAD SPACE` vs `NO PAD`).
- EF Core docs — [SQL Server provider](https://learn.microsoft.com/en-us/ef/core/providers/sql-server/) and [entity properties](https://learn.microsoft.com/en-us/ef/core/modeling/entity-properties) — default `nvarchar` string mapping and `IsUnicode(false)`.
- EF Core docs — [Handling concurrency conflicts](https://learn.microsoft.com/en-us/ef/core/saving/concurrency) (rows-affected check → `DbUpdateConcurrencyException`) and [Breaking changes in EF Core 7](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-7.0/breaking-changes) (`OUTPUT`-based saves, tables with triggers, `HasTrigger` / `UseSqlOutputClause`).

<!-- nav-footer-start -->

---

[← Previous: SQL Mastery — Basics to Advanced](README.md) · [↑ Back to top](#sql-fundamentals) · [Next: Joins & Set Operations →](02-joins-and-set-operations.md)

<!-- nav-footer-end -->

</details>
