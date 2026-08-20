# SQL Mastery — Basics to Advanced

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › SQL Mastery

A comprehensive SQL sub-chapter covering everything from `SELECT` to query-plan tuning. The 9 files below progress from absolute basics to topics you'd discuss in a senior database interview.

The SQL covered here is **vendor-neutral** — the syntax shown works across PostgreSQL, SQL Server, MySQL, and Oracle with minor dialect adjustments. SQL Server-specific features (T-SQL, indexed views, columnstore, Always On) live in [`MS SQL Server`](../04-mssql-server.md). Where dialects diverge meaningfully, this chapter calls it out.

## Why a separate chapter

Even with EF Core / LINQ doing 90% of CRUD, **SQL fluency is non-negotiable** for any senior backend role. The moment you need to debug a slow query, design an index, write a reporting query, or migrate data, you're in raw SQL. Engineers who treat SQL as "the thing the ORM hides" produce slow systems and can't reason about their own database.

This sub-chapter is the deep dive: nine focused files, ~3,500 lines total, structured to be read sequentially or as a reference.

## Topics in this sub-chapter

| # | Topic | Level | Estimated read time |
|---|---|---|---|
| 1 | [Fundamentals](./01-fundamentals.md) | Basics | 15 min |
| 2 | [Joins & Set Operations](./02-joins-and-set-operations.md) | Basics | 20 min |
| 3 | [Aggregation & Grouping](./03-aggregation-and-grouping.md) | Intermediate | 15 min |
| 4 | [Subqueries & CTEs](./04-subqueries-and-ctes.md) | Intermediate | 20 min |
| 5 | [Window Functions](./05-window-functions.md) | Intermediate–Advanced | 25 min |
| 6 | [Indexes & Query Optimization](./06-indexes-and-query-optimization.md) | Advanced | 30 min |
| 7 | [Transactions & Concurrency](./07-transactions-and-concurrency.md) | Advanced | 25 min |
| 8 | [Schema Design & Normalization](./08-schema-design-and-normalization.md) | Intermediate–Advanced | 25 min |
| 9 | [Advanced Patterns & Interview Problems](./09-advanced-patterns-and-interview-problems.md) | Advanced | 30 min |

### Deep-dive companions

For two of the topics above, comprehensive deep-dive documents go further than the survey-level treatment — phone-book analogies, ASCII memory layouts, fragmentation visualizations, and detailed production scenarios:

| # | Companion to | Deep-dive document | Length |
|---|---|---|---|
| 2.D | Joins & Set Operations | [Joins Deep Dive](./02-joins-deep-dive.md) | ~900 lines |
| 6.D | Indexes & Query Optimization | [Indexes Deep Dive](./06-indexes-deep-dive.md) | ~2,500 lines |

Read the survey-level file first to set context, then the deep dive for the depth.

---

## Recommended reading order

**Path A — sequential (best for learning):** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.

**Path B — interview prep (focus on high-yield):** 2 (joins) → 3 (group/having) → 5 (window functions) → 9 (interview problems) → 6 (indexes) → 7 (isolation levels).

**Path C — production tuning lens:** 6 (indexes & plans) → 7 (transactions/locking) → 8 (schema design) → others as needed.

## Cross-references within the broader guide

- **Sibling: [MS SQL Server](../04-mssql-server.md)** — vendor-specific T-SQL deep dive (clustered/non-clustered, RCSI, Always On).
- **Sibling: [EF Core](../01-ef-core.md)** — the ORM that generates much of the SQL you'll write in .NET.
- **Sibling: [LINQ](../02-linq.md)** — the language LINQ translates into SQL (this chapter).
- **[Data Structures](../../01-foundations/03-data-structures.md)** — B-trees, hash tables (the structures DBs use internally).
- **[Searching Algorithms](../../01-foundations/04-searching-algorithms.md)** — binary search underpins B-tree index lookup.
- **[CQRS](../../04-architecture-and-patterns/05-cqrs.md)** — read/write splits often hit SQL nuances directly.
- **[System Design Prep](../../08-craft-and-interview-prep/03-system-design-prep.md)** — schema and capacity decisions in design interviews.

## Sources (chapter-wide)

- *SQL Performance Explained* by Markus Winand (free at [use-the-index-luke.com](https://use-the-index-luke.com/)) — the best book on indexing.
- *SQL Antipatterns* by Bill Karwin (Pragmatic, 2010) — common mistakes and refactors.
- PostgreSQL official documentation — vendor-neutral SQL knowledge; exceptionally clear.
- Microsoft Learn — [SQL Server documentation](https://learn.microsoft.com/en-us/sql/sql-server/).
- *Database Internals* by Alex Petrov (O'Reilly, 2019) — how DBs work under the hood.
- LeetCode SQL problems — [leetcode.com/problemset/database/](https://leetcode.com/problemset/database/) — interview drilling.
- Brent Ozar's blog ([brentozar.com](https://www.brentozar.com/)) — practical SQL Server advice.

<!-- nav-footer-start -->

---

[← Previous: LINQ](../02-linq.md) · [↑ Back to top](#sql-mastery--basics-to-advanced) · [Next: SQL Fundamentals →](01-fundamentals.md)

<!-- nav-footer-end -->
