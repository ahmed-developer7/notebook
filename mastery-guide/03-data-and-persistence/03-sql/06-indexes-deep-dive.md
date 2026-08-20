# SQL Indexes — Deep Dive

> [Mastery Guide](../../README.md) › [Data & Persistence](../README.md) › [SQL Mastery](./README.md) › Indexes Deep Dive

| Status | Priority | Phase | Last reviewed |
|---|---|---|---|
| Not Started | High | Phase 5 — Data & Persistence | 2026-05-08 |

> 📖 **Companion topic file**: [Indexes & Query Optimization](./06-indexes-and-query-optimization.md) — the survey-level treatment. This file is the deep dive: phone-book analogies, ASCII memory layouts, fragmentation visualizations, and 14 worked sections from production-grade indexing decisions.

**Level:** Intermediate to Advanced &nbsp;·&nbsp; **Date authored:** April 7, 2026 &nbsp;·&nbsp; **Original scope:** Builder Workflow Definition Table Index Strategy

> ⚠️ **Engine scope, and how to read the numbers on this page.** Unless a passage says otherwise, everything here is **SQL Server** — `INCLUDE`, filtered indexes, a clustered index that keeps the table in key order, `sys.dm_*` DMVs and 8 KB pages are all SQL Server behaviours, and several of them are false on PostgreSQL or MySQL. Where an engine differs materially there is an explicit note; the consolidated comparison is in [Engine differences that change the answer](#engine-differences-that-change-the-answer). Note that "key order" is deliberate: a clustered index does **not** guarantee physical placement on disk — see [the correction under Clustered Index](#1-clustered-index).
>
> The timings and multipliers inside the ASCII blocks and summary tables below (`~30 seconds`, `0.5ms`, `30,000x faster`, `10-1000x faster SELECT`, `200-500MB per covering index`) are **illustrative shapes, not measurements**. They were written to show which quantity grows and which stays flat, and no benchmark backs them. Do not repeat them in an interview. The defensible version of every one of those claims is a *mechanism* — "a seek descends the tree, so work grows with the log of the row count, while a scan grows linearly with it" — and mechanisms are what the added sections below give you. Figures that *are* sourced carry the source inline.

---

## Table of Contents
1. [Introduction](#introduction)
2. [Index Fundamentals](#index-fundamentals)
3. [Storage Space Requirements](#storage-space-requirements)
4. [Clustered vs Non-Clustered Indexes](#clustered-vs-non-clustered-indexes)
5. [Memory Overhead Explained](#memory-overhead-explained)
6. [Why Too Many Indexes Slow Down Queries](#why-too-many-indexes-slow-down-queries)
7. [Composite Index Column Order](#composite-index-column-order)
8. [Index Sorting](#index-sorting)
9. [Covering Indexes](#covering-indexes)
10. [Index Fragmentation](#index-fragmentation)
11. [Query Optimizer](#query-optimizer)
12. [Best Practices](#best-practices)
13. [Monitoring and Maintenance](#monitoring-and-maintenance)
14. [Real-World Scenarios](#real-world-scenarios)
15. [Interview Cross-Questioning Drill](#interview-cross-questioning-drill)
16. [Self-test](#self-test)
17. [Sources](#sources)

---

## Introduction

### What is an Index?
An index is a database structure that improves the speed of data retrieval operations on a table. Think of it like an index in a book:
- **Without Index:** Read every page to find a topic
- **With Index:** Look in index and jump directly to relevant pages

### Why Indexes Matter?
- **Speed:** a seek walks down a tree, so its cost grows with the *depth* of the index — which grows with the logarithm of the row count. A scan reads every page, so its cost grows with the row count itself. That difference in growth rate, not any particular multiplier, is why indexes matter.
- **Scalability:** doubling a table adds at most a level to the tree — usually not even that. It doubles the work of every scan.
- **Concurrency:** an index does not only make a query fast, it makes its *footprint small*. Rows a query never reads are rows it never locks. On SQL Server this is often the real reason an index fixes a production incident — see the report-blocks-checkout example under [Real-World Scenarios](#real-world-scenarios).

> 🌍 **In the real world**: an orders table was created with `OrderId uniqueidentifier PRIMARY KEY DEFAULT NEWID()`, because the .NET service wanted to assign IDs client-side before saving. SQL Server makes a primary key the clustered index by default, so random GUIDs became the key order the table was maintained in. Every insert landed in a random existing page rather than at the end, so pages split constantly, page density fell, and the table grew far faster than the data in it. The team's first instinct was a nightly `REBUILD` job, which reset density every night and let it decay again by lunchtime — the maintenance window grew, the problem didn't move. The actual fix was two changes: an `int IDENTITY` clustered key, and the GUID kept as a *unique non-clustered* index for external references. Then the second problem arrived: every insert now targeted the same rightmost page, and wait stats filled with `PAGELATCH_EX`, which Microsoft documents as last-page insert contention and for which `OPTIMIZE_FOR_SEQUENTIAL_KEY = ON` (SQL Server 2019 and later) exists. There is no free clustered key on a high-insert table: random keys buy you spread and cost you density, sequential keys buy you density and cost you a hot spot. What you can do is choose which one you have tooling for.

---

## Comprehensive Index Fundamentals

### Understanding Indexes: Detailed Concept

#### What Happens Without an Index?

```
Query: SELECT * FROM Table WHERE TenantId = 1

Without Index:
┌─ Table (1,000,000 rows)
│  ├─ Row 1: TenantId=5, WorkflowId=100, ... → Check? No
│  ├─ Row 2: TenantId=3, WorkflowId=200, ... → Check? No
│  ├─ Row 3: TenantId=1, WorkflowId=150, ... → Check? Yes ✓ Match!
│  ├─ Row 4: TenantId=2, WorkflowId=250, ... → Check? No
│  ├─ Row 5: TenantId=1, WorkflowId=160, ... → Check? Yes ✓ Match!
│  │  ... (continue checking all 1,000,000 rows) ...
│  └─ Row 1000000: TenantId=4, WorkflowId=999, ... → Check? No

Result: Examined 1,000,000 rows to find 50 matches
Time: ~30 seconds (full table scan - every single row!)
```

#### What Happens With an Index?

```
Query: SELECT * FROM Table WHERE TenantId = 1

With Index (IX_TenantId):
┌─ Index (sorted by TenantId)
│  ├─ TenantId=1 → [Row Ptr1, Row Ptr5, Row Ptr12, ...] (50 pointers)
│  ├─ TenantId=2 → [Row Ptr2, Row Ptr8, Row Ptr19, ...] (48 pointers)
│  ├─ TenantId=3 → [Row Ptr3, Row Ptr9, Row Ptr23, ...] (52 pointers)
│  └─ TenantId=5 → [Row Ptr4, Row Ptr10, Row Ptr30, ...] (51 pointers)
│
│  Binary search: Check middle → TenantId=3? (too high)
│                 Check lower → TenantId=2? (too low)
│                 Check between → TenantId=1? ✓ Found!
│
└─ Get all 50 row pointers directly!
    Jump to exact table rows (only 50 of them)

Result: Examined ~20 index entries + 50 table rows (70 total)
Time: ~0.001 seconds (30,000x faster!)
```

#### Index Analogy: Phone Book Example

```
OLD PHONE BOOK (Without Index):
┌──────────────────────┐
│ Name | Address | Ph# │
├──────────────────────┤
│ John | 123 St  | xxx │
│ Mary | 456 Ave | yyy │
│ Alex | 789 Rd  | zzz │
│ Zara | 321 St  | aaa │
│ Mike | 654 Ave | bbb │
└──────────────────────┘

Find phone of "Mike":
├─ Read John (not Mike)
├─ Read Mary (not Mike)
├─ Read Alex (not Mike)
├─ Read Zara (not Mike)
├─ Read Mike ✓ Found!
└─ Checked 5 entries (50% of list)

NEW PHONE BOOK (With Alphabetical Index):
┌─────────────────────────┐
│ Name | Address | Ph#    │
├─────────────────────────┤
│ Alex | 789 Rd  | zzz    │ ← Sorted alphabetically
│ John | 123 St  | xxx    │    by name
│ Mary | 456 Ave | yyy    │
│ Mike | 654 Ave | bbb    │
│ Zara | 321 St  | aaa    │
└─────────────────────────┘

Find phone of "Mike":
├─ Go to middle (Mary) - "Mike" comes after
├─ Go to next (Mike) ✓ Found!
└─ Checked 2 entries instead of 5 (60% fewer comparisons)

With Large Database (1 million names):
Without Index: ~500,000 comparisons on average (linear in N)
With Index:    ~20 comparisons (log2 of 1,000,000 ≈ 20)

The point is the shape: linear vs logarithmic. A wall-clock
multiplier depends on page size, caching and hardware, so it
is not a number you can carry between systems.
```

> ⚠️ **Where the phone-book analogy breaks, and why interviewers push on it.** A phone book is one sorted list, so it suggests an index is *the table, sorted*. That is only true of a clustered index. A non-clustered index is a **second, narrower sorted copy** of a few columns, and reaching the rest of the row costs an extra step — the mechanism that costs you is [the lookup](#the-row-locator-what-a-non-clustered-index-leaf-actually-points-at), and it is the thing the analogy hides. The other thing it hides: a phone book is rebuilt once a year, whereas a database index is maintained on every single write. Half of index design is paying for that maintenance in the right places.

### Database Index Types: Detailed Overview

#### 1. **Clustered Index**

**Definition:** The clustered index *is* the table — its leaf level holds the data rows themselves, kept in key order. Only one per table, because a table can only be stored one way.

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ CLUSTERED INDEX Properties          │
├─────────────────────────────────────┤
│ ✓ One per table (maximum)           │
│ ✓ Leaf level IS the data rows       │
│ ✓ Fastest for exact key matches     │
│ ✓ Usually on Primary Key            │
│ ✓ No extra copy of the row          │
│ ✓ Key is copied into every NC index │
│ ✗ Slower INSERT for unsorted data   │
│ ✗ Its key width taxes every index   │
└─────────────────────────────────────┘
```

> ⚠️ **Correction — "physical order on disk" is the wrong phrase, and interviewers listen for it.** A clustered index maintains a *logical* order: leaf pages are chained in key order by a doubly-linked list, and each page's slot array orders the rows within it. Neither guarantees the pages sit next to each other on the storage device. That gap between logical order and physical placement is precisely what `avg_fragmentation_in_percent` measures — Microsoft defines rowstore fragmentation as existing "when indexes have pages in which the logical ordering within the index, based on the key values of the index, doesn't match the physical ordering of index pages" (Microsoft Learn, *Maintain indexes optimally*). If a clustered index really did guarantee physical order, fragmentation could not exist. Say "the rows are stored **in key order**, and the leaf level of the index is the table."
>
> On the version note: online index rebuild has existed since SQL Server 2005 and is an **Enterprise-edition** feature to this day (Microsoft Learn, *Perform index operations online*, which points at the Editions and supported features page rather than naming a version). What changed in SQL Server 2012 was the *LOB restriction* — before it, an index whose leaf held large-object columns could not be rebuilt online at all. Azure SQL Database and Azure SQL Managed Instance have online index operations regardless of tier.

**How It Works:**
```sql
CREATE CLUSTERED INDEX PK_Id ON Orders (OrderId);

Leaf Level = the Table, in OrderId key order:
┌─────────────────────────────────────┐
│ OrderId | TenantId | Amount | Date  │
├─────────────────────────────────────┤
│ 1       | 10       | 100    | 1/1   │ ← Rows held in KEY order,
│ 2       | 20       | 200    | 1/2   │    not physical disk order
│ 3       | 10       | 150    | 1/3   │
│ 4       | 30       | 300    | 1/4   │
│ 5       | 20       | 250    | 1/5   │
└─────────────────────────────────────┘

Query: SELECT * FROM Orders WHERE OrderId = 3
Execution: Descend the tree → land on the leaf entry for OrderId=3
          The leaf IS the row, so it is read there — no second hop,
          and no assumption about where that page sits on disk
Time: Fastest possible
```

**When to Use Clustered:**
```
✅ Good Candidates:
├─ Integer Primary Key (usually)
├─ Often searched columns
├─ Range queries (BETWEEN, >)
├─ Large tables (>1M rows)
└─ Sequential access patterns

❌ Bad Candidates:
├─ GUID Primary Key (causes fragmentation)
├─ Very large columns (BLOB, TEXT)
├─ Frequently updated columns
├─ Random value insertions
└─ Multi-column keys
```

#### 2. **Non-Clustered Index**

**Definition:** Separate structure that contains sorted columns and pointers to table rows. Up to 999 per table.

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ NON-CLUSTERED INDEX Properties      │
├─────────────────────────────────────┤
│ ✓ Up to 999 per table               │
│ ✓ Separate from table structure     │
│ ✓ Extra storage required            │
│ ✓ Fast for specific queries         │
│ ✓ Can include non-key columns       │
│ ✓ Can rebuild online                │
│ ✗ Requires extra disk space         │
│ ✗ Requires extra memory             │
│ ✗ Must update on INSERT/UPDATE      │
└─────────────────────────────────────┘
```

**How It Works:**
```sql
CREATE NONCLUSTERED INDEX IX_TenantId ON Orders (TenantId);

Index Structure:
┌───────────────────────────┐
│ TenantId | Row Pointer    │
├───────────────────────────┤
│ 10       | → Disk Addr 1  │
│ 10       | → Disk Addr 3  │ ← Sorted by TenantId
│ 10       | → Disk Addr 5  │    (not sequential on disk)
│ 20       | → Disk Addr 2  │
│ 20       | → Disk Addr 4  │
│ 30       | → Disk Addr 7  │
└───────────────────────────┘
          ↓ (follow pointers)
┌──────────────────────────────────────┐
│ OrderId | TenantId | Amount | Date   │
│ (actual table rows in scattered      │
│  disk locations)                     │
└──────────────────────────────────────┘

Query: SELECT * FROM Orders WHERE TenantId = 10
Execution: Seek index → Get 3 row locators →
          Follow each locator to the full row →
          Read 3 table rows
Cost: index seek + one lookup PER ROW returned
```

> ⚠️ **Correction — the diagram above is only right for a heap.** "Disk Addr 1", "0x1000" and similar physical addresses in these ASCII blocks describe a table with **no clustered index**. Microsoft Learn (*Index architecture and design guide*) states the rule directly: "If the table has a clustered index, or the index is on an indexed view, the row locator is the clustered index key for the row. If the table is a heap ... the row locator is a pointer to the row ... built from the file identifier (ID), page number, and number of the row on the page. The whole pointer is known as a Row ID (RID)." Mentally substitute *clustered key* for every "disk address" you see below; the mechanism and its consequences are in [the next section](#the-row-locator-what-a-non-clustered-index-leaf-actually-points-at). The per-lookup cost is also not a fixed multiple of a clustered seek — it is *one extra tree descent per row returned*, which is why a lookup plan is cheap for ten rows and ruinous for a hundred thousand.

**When to Use Non-Clustered:**
```
✅ Good Candidates:
├─ Frequently searched columns (not PK)
├─ Foreign Key columns
├─ Filter columns (WHERE clause)
├─ Join condition columns
├─ Reporting queries
└─ Covering specific query patterns

❌ Bad Candidates:
├─ Rarely searched columns
├─ Very low cardinality (few distinct values)
├─ Write-heavy tables (many INSERT/UPDATE)
├─ Low selectivity columns
└─ Duplicate of existing indexes
```

#### 3. **Composite (Multi-Column) Index**

**Definition:** Non-clustered index on multiple columns. Column order is critical.

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ COMPOSITE INDEX Properties          │
├─────────────────────────────────────┤
│ ✓ Covers multiple WHERE conditions  │
│ ✓ Faster than multiple single indexes
│ ✓ Enables covering indexes          │
│ ✗ Column order matters (critical!)  │
│ ✗ Leading column must be in query   │
│ ✗ Large with many columns           │
│ ✗ Complex to maintain               │
└─────────────────────────────────────┘
```

**Example:**
```sql
CREATE INDEX IX_Tenant_Workflow ON Orders (TenantId, WorkflowId);

Index Structure (Sorted):
┌─────────────────────────────────┐
│ TenantId | WorkflowId | RowPtr  │
├─────────────────────────────────┤
│ 10       | 100        | →Addr1  │ ← First sorted by TenantId
│ 10       | 150        | →Addr3  │    Then by WorkflowId
│ 10       | 200        | →Addr5  │
│ 20       | 50         | →Addr2  │
│ 20       | 100        | →Addr4  │
│ 20       | 300        | →Addr7  │
└─────────────────────────────────┘

Query 1: WHERE TenantId = 10 AND WorkflowId = 150
Result: Binary search → 1 match ✅ Very Fast!

Query 2: WHERE TenantId = 10
Result: Scan entries for TenantId=10 → 3 matches ✅ Fast!

Query 3: WHERE WorkflowId = 150
Result: No seek boundary — WorkflowId isn't the leading column,
        so the engine reads the ENTIRE index and checks each entry.
        ⚠️ Slow, but still normally cheaper than reading the table:
        index rows are narrower, so there are far fewer pages.
        What is lost is the SEEK, not the index — see the two
        corrections under Composite Index Column Order.
```

#### 4. **Covering Index**

**Definition:** Non-clustered index that includes all columns needed for a query, eliminating table lookups.

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ COVERING INDEX Properties           │
├─────────────────────────────────────┤
│ ✓ Eliminates table lookups          │
│ ✓ Saves one tree descent PER ROW    │
│ ✓ Removes the tipping-point cliff   │
│ ✓ Useful for specific queries       │
│ ✗ Much larger than normal index     │
│ ✗ Uses significant disk space       │
│ ✗ High memory overhead              │
│ ✗ Slower INSERT/UPDATE              │
└─────────────────────────────────────┘
```

**Example:**
```sql
CREATE INDEX IX_Cover ON Orders (TenantId, WorkflowId)
INCLUDE (DiagramId, BuilderObject, CreatedAt);

Index Leaf Page Content:
┌────────────────────────────────────────────────────┐
│ TenantId|WorkflowId|DiagramId|BuilderObject|Date  │
├────────────────────────────────────────────────────┤
│ 10      | 100     | 50      | {JSON}      | 1/1   │
│ 10      | 150     | 75      | {JSON}      | 1/2   │ ← All data here!
│ 20      | 50      | 25      | {JSON}      | 1/3   │
│ 20      | 100     | 60      | {JSON}      | 1/4   │
└────────────────────────────────────────────────────┘
         (600 bytes per entry)

Query: SELECT TenantId, WorkflowId, DiagramId, BuilderObject
       FROM Orders WHERE TenantId = 10
       
Execution: 
├─ Index seek → TenantId=10
├─ Get all columns from index (no lookup!)
└─ Return to user

Result: the per-row lookup disappears entirely.
        The saving scales with the number of ROWS RETURNED,
        which is why covering matters most for the queries
        that return many rows, and barely at all for the
        ones that return five.
```

> ⚠️ **`BuilderObject` is `NVARCHAR(MAX)` in this schema, so this example is a trap.** `INCLUDE`-ing a LOB column duplicates the whole document into the index leaf. The index then approaches the size of the table, the buffer pool has to hold two copies of the same JSON, and every update to that JSON writes it twice. Before SQL Server 2012 it also made the index ineligible for online rebuild. `INCLUDE` narrow columns you return; leave LOBs to the lookup, which for the handful of rows a good seek returns is cheap.

#### 5. **Unique Index**

**Definition:** Ensures all values in indexed columns are unique.

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ UNIQUE INDEX Properties             │
├─────────────────────────────────────┤
│ ✓ Enforces uniqueness constraint    │
│ ✓ Prevents duplicate values         │
│ ✓ Acts as implicit key              │
│ ✓ Improves query optimization       │
│ ✗ Rejects INSERT if not unique      │
│ ✗ Slower INSERT (uniqueness check)  │
│ ✗ SQL Server: at most ONE NULL      │
└─────────────────────────────────────┘
```

**Example:**
```sql
CREATE UNIQUE INDEX IX_Email ON Users (Email);

-- Valid Insert
INSERT INTO Users VALUES (1, 'john@email.com');  ✅

-- Invalid Insert (duplicate)
INSERT INTO Users VALUES (2, 'john@email.com');  ❌
-- Error: Violation of UNIQUE KEY constraint

-- NULLs — SQL Server treats them as duplicates of each other
INSERT INTO Users VALUES (3, NULL);  ✅  first NULL is fine
INSERT INTO Users VALUES (4, NULL);  ❌  second NULL is rejected
```

> ⚠️ **Correction, and one of the most reliable interview traps on this page.** The original text claimed multiple NULLs are allowed "because `NULL != NULL` in SQL". That is the ANSI reasoning and it is what PostgreSQL and MySQL do — but **SQL Server does not follow it for unique indexes**. Microsoft Learn (*Create a unique index*) is explicit: "You cannot create a unique index on a single column if that column contains NULL in more than one row. Similarly, you cannot create a unique index on multiple columns if the combination of columns contains NULL in more than one row. These are treated as duplicate values for indexing purposes."
>
> | Engine | Multiple NULLs in a unique index? |
> |---|---|
> | SQL Server | **No** — one NULL only. Work around it with a filtered index: `CREATE UNIQUE INDEX ... WHERE Email IS NOT NULL` |
> | PostgreSQL | Yes by default; `NULLS NOT DISTINCT` (PostgreSQL 15+) opts into SQL Server's behaviour |
> | MySQL / InnoDB | Yes — any number of NULLs |
>
> The filtered-index workaround is worth committing to memory, because "nullable but unique when present" is an extremely common shape: optional email, optional external reference, optional SSO subject ID.

> 🌍 **In the real world**: a `Users` table carried a nullable `ExternalSsoId`, unique when present, enforced by `CREATE UNIQUE INDEX IX_Users_ExternalSsoId ON Users (ExternalSsoId)`. It worked in the developers' PostgreSQL containers — several local users had no SSO ID and nothing complained. It worked in the SQL Server test environment too, because exactly one seeded user had a NULL there. It failed in production the first time a second non-SSO user was created, with a unique key violation on a column the application had deliberately left empty, and the stack trace pointed at a `SaveChanges` call that looked completely innocent. The root cause was an engine difference nobody had checked: PostgreSQL allows any number of NULLs in a unique index, SQL Server allows one. The fix was one clause — `WHERE ExternalSsoId IS NOT NULL` — which also made the index smaller, since the excluded rows were the majority. The general lesson is that "it passed locally" means nothing when local and production are different engines, and the differences cluster exactly around NULL, collation, and isolation defaults.

#### 6. **Filtered Index**

**Definition:** Non-clustered index that applies only to subset of rows matching a WHERE condition.

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ FILTERED INDEX Properties           │
├─────────────────────────────────────┤
│ ✓ Smaller size (only subset rows)   │
│ ✓ Faster INSERT/UPDATE              │
│ ✓ Saves storage space               │
│ ✓ Targets specific queries          │
│ ✗ Limited to specific conditions    │
│ ✗ Query must match filter condition │
│ ✗ Complex to design                 │
└─────────────────────────────────────┘
```

**Example:**
```sql
-- Normal index on all rows
CREATE INDEX IX_Normal ON Orders (TenantId);
-- Indexes every row in the table

-- Filtered index on active orders only
CREATE INDEX IX_Active ON Orders (TenantId)
WHERE Status = 'Active';
-- Indexes only rows where Status = 'Active'.
-- The saving is proportional to how few rows match:
-- an index over 3% of the table is roughly 3% of the size,
-- and it is only maintained when a write touches those rows.

Query: SELECT * FROM Orders WHERE TenantId = 10 AND Status = 'Active'
Result: Can use filtered index ✅ (literal predicate implies the filter)

Query: SELECT * FROM Orders WHERE TenantId = 10 AND Status = 'Completed'
Result: Cannot use filtered index ❌
        Falls back to whatever else exists — another index,
        or a scan. Not automatically a full table scan.

Query: SELECT * FROM Orders WHERE TenantId = 10 AND Status = @status
Result: Usually CANNOT use it, even when @status = 'Active' ❌
        The optimizer must prove the implication at COMPILE time,
        and the plan it compiles gets cached for every later value.
```

**The two things that make filtered indexes fail silently in production:**

1. **Parameters defeat them.** The optimizer has to prove the query's predicate implies the index's predicate while compiling, before it knows the parameter value — and the plan it produces will be reused for other values. So it declines. `OPTION (RECOMPILE)`, or a dedicated query with the literal in the SQL, restores the match. SQL Server records the near-miss in the plan XML's `<UnmatchedIndexes>` element, which is the fastest way to confirm the diagnosis. PostgreSQL partial indexes behave the same way for generic cached plans.
2. **SET options.** Filtered indexes require `ANSI_NULLS`, `ANSI_PADDING`, `ANSI_WARNINGS`, `QUOTED_IDENTIFIER`, `ARITHABORT` and `CONCAT_NULL_YIELDS_NULL` ON and `NUMERIC_ROUNDABORT` OFF. With the wrong settings the optimizer will not consider the index at all, *and* any `INSERT`/`UPDATE`/`DELETE` touching indexed rows fails outright. The nasty case: `ANSI_NULLS` and `QUOTED_IDENTIFIER` are baked into a stored procedure at creation time, not taken from the calling session — so a procedure created under the wrong settings keeps failing no matter how the connection is configured.

**Engine note:** filtered indexes are SQL Server 2008+. PostgreSQL calls the same thing a **partial index**. **MySQL has no equivalent** — the usual workaround is a generated column that evaluates to `NULL` for excluded rows, exploiting the fact that InnoDB still indexes NULLs but they cost little and match nothing.

> 🌍 **In the real world**: an outbox table held tens of millions of dispatched rows and a few thousand pending ones, so the obvious filtered index went on — `WHERE Status = 'Pending'`. The dispatcher got no faster. Six weeks later someone checked `sys.dm_db_index_usage_stats` and found the index had never been seeked, not once. The predicate was correct; the *parameter* was the problem. The dispatcher called a shared repository method that passed status as `@status`, so the optimizer could not prove at compile time that the cached plan would only ever run for `'Pending'`, and quietly ignored the index. Meanwhile the index was still being maintained on every insert — pure write cost, zero read benefit, for a month and a half. The fix was a dedicated query with the literal inlined. The lesson is about the failure mode rather than the fix: a filtered index that is not being used does not error, does not warn, and does not show up anywhere except a DMV nobody reads. An index with zero seeks and non-zero updates is always worth a look.

#### 7. **Full-Text Index**

**Definition:** Specialized index for searching text content efficiently.

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ FULL-TEXT INDEX Properties          │
├─────────────────────────────────────┤
│ ✓ Search text without LIKE %x%      │
│ ✓ Natural language queries          │
│ ✓ Stemming (run → running)          │
│ ✓ Phrase search                     │
│ ✗ Cannot use for non-text columns   │
│ ✗ Requires full-text service        │
│ ✗ Extra maintenance required        │
└─────────────────────────────────────┘
```

**Example:**
```sql
-- Create full-text index
CREATE FULLTEXT INDEX ON Articles(Content) 
KEY INDEX IX_ArticleId;

-- Traditional LIKE search (slow)
SELECT * FROM Articles WHERE Content LIKE '%database%';
-- Scans all rows, checks each Content value

-- Full-text search (very fast)
SELECT * FROM Articles 
WHERE CONTAINS(Content, 'database');
-- Uses full-text index: word → locations
```

#### 8. **Columnstore Index**

**Definition:** Specialized index for analytical queries on large datasets (SQL Server 2012+).

**Key Characteristics:**
```
┌─────────────────────────────────────┐
│ COLUMNSTORE INDEX Properties        │
├─────────────────────────────────────┤
│ ✓ Compression + rowgroup skipping   │
│ ✓ Batch mode (many rows per call)   │
│ ✓ Parallel processing               │
│ ✓ Reads only the columns you ask    │
│ ✗ Slower INSERT/UPDATE              │
│ ✗ Bad at OLTP point lookups         │
│ ✗ NC columnstore: 2012+ (see below) │
└─────────────────────────────────────┘
```

**Microsoft's own figures, quoted rather than invented** (Microsoft Learn, *Columnstore indexes: Overview*): columnstore "achieve[s] gains **up to 10 times the query performance** in your data warehouse over traditional row-oriented storage" and "**up to 10 times the data compression** over the uncompressed data size"; batch mode execution "improves query performance typically by **two to four times**." The "100x" and "90% compression" figures the box originally carried have no source and overstate what the vendor claims.

**Mechanism worth knowing.** A **rowgroup** is up to 1,048,576 rows compressed together; each rowgroup holds one **column segment** per column, and each segment carries min/max metadata "to allow for fast elimination of segments without reading them." That is rowgroup elimination: `WHERE OrderDate >= '2026-01-01'` discards whole rowgroups on metadata alone. It works only to the extent that the predicate column's values are *clustered by load order*, so that rowgroups have narrow, non-overlapping min/max ranges — an append-only fact table eliminates well on its date column by accident, and eliminates badly on anything else. Making that property deliberate is what ordered clustered columnstore indexes are for. Writes land in a **delta rowgroup** (a B-tree) until it reaches 1,048,576 rows, then the tuple-mover compresses it; bulk loads under 102,400 rows go entirely to the deltastore and are never compressed until maintenance runs.

**Version gates, precisely.** Non-clustered columnstore arrived in SQL Server 2012 but made the table read-only. Clustered columnstore came in 2014. Updatable non-clustered columnstore — the one that enables real-time operational analytics alongside an OLTP workload — came in SQL Server 2016.

**Example:**
```sql
-- Traditional row store (OLTP optimized)
CREATE INDEX IX_Normal ON Sales (ProductId);
-- Data stored by row: Row1 (ProdId|Date|Amount|...)
-- Good for: Get one customer's purchases

-- Columnstore index (OLAP optimized)
CREATE NONCLUSTERED COLUMNSTORE INDEX IX_ColumnStore 
ON Sales (ProductId, Date, Amount);
-- Data stored by column: ProdIds[1,2,3,4,5...] | 
--                        Dates[1/1,1/2,1/3...]
--                        Amounts[100,200,150...]
-- Good for: Analyze patterns across millions of rows
```

---

### Benefits of Using Indexes

#### Query Performance Benefits

```
✅ WHAT ACTUALLY IMPROVES — expressed as growth rates,
   because the multiplier depends on your hardware:

Access path        Pages read grows with...    Notes
─────────────────  ──────────────────────────  ──────────────────────
Table scan         N (every row)               Doubling data doubles work
Index scan         N, but narrower rows        Fewer pages than the table
Index seek         log(N) + matching rows      Depth grows very slowly
Seek + lookup      log(N) + R × log(N)         R = rows returned. The
                                               lookup is per row, so this
                                               degrades as R grows
Covering seek      log(N) + matching rows      No per-row lookup at all

Read the fourth row carefully — it is why a plan that is fast in
test (R = 12) can be catastrophic in production (R = 120,000)
with no change to the query, the index, or the schema.
```

> ⚠️ **The number the original table gave — "covering index: 60,000x faster" — is unsourced and would not survive a follow-up question.** If an interviewer asks "how much faster?", the honest and stronger answer is a question back: *how many rows does it return, and is the working set in memory?* A seek that returns one row from a cached index and a scan of a 100 GB table off cold storage differ by whatever ratio you like; a seek returning 40% of the table may be *slower* than the scan. See [the tipping point](#the-tipping-point-why-the-optimizer-abandons-your-index) for why.

#### Business Benefits

```
✅ USER EXPERIENCE:
├─ Instant search results
├─ Responsive reports
├─ Fast admin dashboards
└─ Better user satisfaction

✅ SYSTEM SCALABILITY:
├─ Handle more users
├─ Support larger datasets
├─ Grow to millions of records
└─ Maintain performance

✅ RESOURCE EFFICIENCY:
├─ Reduced CPU usage
├─ Lower disk I/O
├─ Less memory thrashing
└─ Better server capacity

✅ COMPETITIVE ADVANTAGE:
├─ Real-time analytics
├─ Faster decision-making
├─ Better customer experience
└─ Reduced operational costs
```

---

### Cons and Disadvantages of Indexes

#### Write Performance Degradation

```
❌ INSERT PERFORMANCE:

Without Indexes:
INSERT (1 million rows): 5 minutes

With 1 Index:
INSERT (1 million rows): 7 minutes (+40%)

With 5 Indexes:
INSERT (1 million rows): 15 minutes (+200%)

With 10 Indexes:
INSERT (1 million rows): 25 minutes (+400%)

Why? Each INSERT must update:
├─ The clustered index (1 write) — this IS the table, so it is
│  not a separate write from "the table"
├─ 9 non-clustered indexes (9 writes)
└─ Total: 10 writes per row
```

#### Storage Space Overhead

```
❌ DISK SPACE USAGE:

Simple Index:
├─ Table: 2GB
├─ Index: 32MB (1.6% overhead)
└─ Total: 2.032GB

Multiple Indexes:
├─ Table: 2GB
├─ IX_Tenant: 32MB
├─ IX_Workflow: 32MB
├─ IX_Diagram: 32MB
├─ IX_Composite1: 64MB
├─ IX_Composite2: 64MB
├─ IX_Covering: 500MB
└─ Total: 2.724GB (36.2% overhead!)
```

#### Memory Requirements

```
❌ MEMORY OVERHEAD:

Each Frequently Used Index:
├─ Loaded into RAM buffer pool
├─ Typical index page: 8KB
├─ Frequently accessed pages: 5,000
└─ Memory per index: 40MB

5 Frequently Used Indexes:
├─ Memory required: 200MB
├─ That's 200MB unavailable for data cache!

Severe on Limited Memory Servers:
├─ 4GB RAM server
├─ OS: 2GB, SQL Server: 2GB
├─ 5 covering indexes: 200MB
├─ Data cache remaining: 1.8GB ❌ TOO SMALL!
└─ Result: Constant disk swapping (very slow)
```

#### Maintenance Overhead

```
❌ MAINTENANCE REQUIREMENTS:

Without Indexes:
├─ Daily fragmentation check: 1 minute
├─ Weekly statistics update: 2 minutes
├─ Monthly maintenance: 10 minutes
└─ Total: Very minimal

With 10 Indexes:
├─ Daily fragmentation check: 5 minutes
├─ Identify fragmented indexes: 3 minutes
├─ Weekly statistics update: 10 minutes
├─ Reorganize fragmented indexes: 30 minutes
├─ Monthly index rebuild: 45 minutes
├─ Monitor index usage: 10 minutes
└─ Total: 1-2 hours/week!

Operational Cost:
├─ DBA time required: 4-8 hours/month
├─ Potential downtime if maintenance delayed
├─ Index fragmentation causes slowdowns
└─ Eventually requires database tuning
```

#### Query Optimizer Confusion

```
❌ TOO MANY CHOICES:

Few Indexes (Good):
Query: WHERE TenantId = 1 AND WorkflowId = 100
Available: 2 indexes
Decision: Clear → Use best index ✅

Many Indexes (Problem):
Query: WHERE TenantId = 1 AND WorkflowId = 100
Available: 15 indexes
├─ IX_Tenant (could work)
├─ IX_Workflow (could work)
├─ IX_Tenant_Workflow (best)
├─ IX_Tenant_Diagram (similar structure)
├─ 10 other indexes...

Optimizer Decision: Uncertain!
├─ May pick wrong index
├─ Query plan becomes unpredictable
├─ Performance varies
└─ Troubleshooting difficult
```

#### Lock Contention

```
❌ CONCURRENT UPDATE PROBLEMS:

Low Contention (Few Indexes):
Thread1: INSERT → Update table + 2 indexes → Done
Thread2: INSERT → Update table + 2 indexes → Done
Thread3: INSERT → Update table + 2 indexes → Done
Throughput: 100,000 inserts/second ✅

High Contention (Many Indexes):
Thread1: INSERT → Update table + 10 indexes
        → Locks on multiple index pages
Thread2: INSERT → Waits for Thread1 to release locks
        → Performance degrades
Thread3: INSERT → Waits in queue
        → Queue growing, timeouts

Throughput: 10,000 inserts/second ❌ (10x slower!)
```

---

### Pros vs Cons Summary Table

| Aspect | Pros | Cons |
|--------|------|------|
| **Query Speed** | 10-1000x faster SELECT | None |
| **INSERT Speed** | None | 2-5x slower with 5-10 indexes |
| **UPDATE Speed** | None | 2-5x slower with 5-10 indexes |
| **Storage** | Compressed data possible | 20-40% overhead with 10+ indexes |
| **Memory** | Frequently used pages cached | 200-500MB per covering index |
| **Maintenance** | Automatic via DBCC | 4-8 hours/month for large systems |
| **Scalability** | Enable growth to millions | Limits concurrent writes |
| **Optimizer** | Can choose best index | Longer compile times, less stable plan choices |
| **Development** | Query optimization easier | Complex index design needed |
| **Operations** | Predictable performance | Fragmentation issues over time |

> ⚠️ Every multiplier in that table is unsourced and none should be quoted in an interview — they are shape, not measurement. The "Optimizer" row originally read "Confused with 15+ options", which is the same folklore corrected under [Query Optimizer Confusion](#query-optimizer-confusion): a cost-based optimizer is never *confused*, it costs every candidate and takes the cheapest. What extra indexes actually cost you is compile time, plan stability, write amplification and buffer pool.

---

### When NOT to Use Indexes

```
❌ DON'T CREATE INDEX WHEN:

1. Table has fewer than 10,000 rows
   ├─ Full scan already fast
   └─ Index overhead not worth it

2. Column rarely appears in WHERE clause
   ├─ Index benefit minimal
   └─ Wasted storage space

3. Very write-heavy table (>1000 inserts/sec)
   ├─ Index update overhead too high
   └─ Performance degradation too severe

4. Column has low selectivity (few distinct values)
   ├─ TenantId = 'A' returns 100k rows
   ├─ Index can't narrow results much
   └─ Better to scan full table

5. Already have composite index covering query
   ├─ Single index on column redundant
   └─ Duplicate indexes waste space

6. Columns updated frequently
   ├─ Every INSERT updates all indexes
   ├─ Every UPDATE might change indexed values
   └─ Too much maintenance overhead
```

---



---

## Index Fundamentals

### Basic Analogy
```
Book Index:
Entry: "Database" → Pages 45, 67, 123
Entry: "SQL" → Pages 12, 34, 56, 78, 99

Database Index:
Entry: TenantId=1 → Row locators (clustered key, or a RID on a heap)
Entry: WorkflowId=100 → Row pointers
Entry: TenantId=1, WorkflowId=100 → Row pointer (composite)
```

### Index Components
```
Index Structure:
├─ Root Node (top of tree)
├─ Intermediate Nodes (branches)
└─ Leaf Nodes (actual data/pointers)

B-Tree Structure (most common):
          Root
         /    \
      Node1  Node2
      / | \   / | \
    L1 L2 L3 L4 L5 L6
    (Leaf nodes contain data)
```

---

## Storage Space Requirements

### Question 1: Why Extra Storage Space Required?

### Index Storage Breakdown

#### Example Scenario
```
Table: WT_Builder_Workflow_Definition

Original Table:
├─ Rows: 1,000,000
├─ Row Size: ~2KB (all columns)
├─ Columns: Id, TenantId, WorkflowId, DiagramId, BuilderObject, 
            CreatedBy, UpdatedBy, CreatedAt, UpdatedAt
└─ Total Size: 2GB

Non-Clustered Index (IX_TenantId):
├─ Entry Size: 16 bytes (8 bytes TenantId + 8 bytes row pointer)
├─ Entries: 1,000,000
└─ Total Size: 16MB

Covering Index (IX_TenantId_WorkflowId_Covering):
├─ Entry Size: 500 bytes (includes TenantId, WorkflowId, DiagramId, 
    BuilderObject, CreatedAt, UpdatedAt)
├─ Entries: 1,000,000
└─ Total Size: 500MB
```

### Storage Impact Calculation
```
Storage Before Indexes:
┌─────────────────────────────────────┐
│ Table: 2GB                          │
└─────────────────────────────────────┘

Storage After Adding 5 Indexes:
┌─────────────────────────────────────┐
│ Table: 2GB                          │
├─ IX_TenantId: 16MB                 │
├─ IX_WorkflowId: 16MB               │
├─ IX_DiagramId: 16MB                │
├─ IX_TenantId_WorkflowId: 32MB      │
├─ IX_TenantId_DiagramId: 32MB       │
└─ Total: 2.112GB (5.6% increase)    │
└─────────────────────────────────────┘

Storage After Adding Covering Index:
┌─────────────────────────────────────┐
│ Previous: 2.112GB                   │
├─ IX_Covering: 500MB                │
└─ Total: 2.612GB (30.6% increase)   │
└─────────────────────────────────────┘
```

### Why Indexes Consume Space
1. **Column Duplication:** Index stores copy of indexed columns
2. **Pointers:** Each entry includes pointer to table row
3. **B-Tree Structure:** Overhead for tree nodes and branches
4. **Covering Indexes:** Store additional non-key columns
5. **Metadata:** Index statistics and page information

### Real Storage Example
```sql
-- Check index size
SELECT 
    i.name AS IndexName,
    ps.page_count * 8 / 1024 AS SizeInMB
FROM sys.indexes i
INNER JOIN sys.dm_db_index_physical_stats(
    DB_ID(), 
    OBJECT_ID('dbo.WT_Builder_Workflow_Definition'), 
    NULL, 
    NULL, 
    'LIMITED'
) ps ON i.object_id = ps.object_id AND i.index_id = ps.index_id
ORDER BY ps.page_count DESC;

Result Example:
IndexName                          SizeInMB
─────────────────────────────────  ────────
PK_builder_workflow_definition     256
IX_TenantId_WorkflowId_Covering    512
IX_TenantId_WorkflowId             64
IX_TenantId_DiagramId              64
IX_TenantId                        32
IX_WorkflowId_DiagramId            32
```

### Storage Impact on Performance
```
Disk I/O Considerations:

More Indexes = More Disk Space
More Disk Space = More Pages to Read
More Pages = Slower Physical Reads

However:
Better Indexes = Fewer Pages to Search
Fewer Pages = Faster Logical Reads
Faster Reads = Overall performance benefit

Balance is key!
```

---

## Clustered vs Non-Clustered Indexes

### Question 2: Is It Clustered or Non-Clustered?

### Syntax Determines Type
```sql
-- ❌ Creates NON-CLUSTERED (default)
CREATE INDEX IX_TenantId ON Table (TenantId)

-- ✅ Explicitly NON-CLUSTERED
CREATE NONCLUSTERED INDEX IX_TenantId ON Table (TenantId)

-- ✅ Creates CLUSTERED (rare!)
CREATE CLUSTERED INDEX IX_Id ON Table (Id)

-- Your indexes are all NON-CLUSTERED:
CREATE INDEX [IX_WT_Builder_Workflow_Definition_TenantId]
ON [dbo].[WT_Builder_Workflow_Definition] ([TenantId]);
-- ^ This is NON-CLUSTERED by default
```

### Clustered Index (Usually Primary Key)

```sql
CREATE CLUSTERED INDEX PK_Id ON Table (Id)
```

**Characteristics:**
- Determines the **key order** the rows are maintained in — the leaf level *is* the
  table. Not physical placement on disk: see [the correction under Clustered Index](#1-clustered-index)
- Only ONE per table
- Fastest access by key value
- Pages split when inserting in the middle

**Structure:**
```
Clustered Index on ID:
┌──────────────────────────────────┐
│ Leaf Level = Entire Table Data   │
│ (held in ID key order)           │
│                                  │
│ ID | TenantId | WorkflowId | ... │
│ 1  | 1        | 100        | ... │
│ 2  | 2        | 200        | ... │
│ 3  | 1        | 150        | ... │
└──────────────────────────────────┘
```

### Non-Clustered Index

```sql
CREATE NONCLUSTERED INDEX IX_TenantId ON Table (TenantId)
```

**Characteristics:**
- Separate structure pointing to rows
- Up to 999 per table
- Fast for specific lookups
- Extra storage required

**Structure:**
```
Non-Clustered Index on TenantId:
┌──────────────────────────┐
│ Leaf Level = Index Data  │
│                          │
│ TenantId | Row Pointer   │
│ 1        | 0x1000        │
│ 1        | 0x2000        │
│ 2        | 0x3000        │
│ 2        | 0x4000        │
└──────────────────────────┘
         ↓ (points to)
┌──────────────────────────────────┐
│ Actual Table Row                 │
│ ID | TenantId | WorkflowId | ... │
└──────────────────────────────────┘
```

### Comparison Table

| Aspect | Clustered | Non-Clustered |
|--------|-----------|---------------|
| Quantity per table | 1 only | Up to 999 (Microsoft Learn, *Maximum capacity specifications*) |
| Storage | No extra copy of the row | A second, narrower copy of the key columns |
| Leaf level contains | The data rows themselves | Key columns, `INCLUDE` columns, and the row locator |
| Reaching other columns | Already there | Costs a lookup, one per row returned |
| Insertion Impact | Page splits if the key isn't sequential | One more structure to maintain per insert |
| Default | Created by `PRIMARY KEY` unless you say `NONCLUSTERED` | Manual creation, or by a `UNIQUE` constraint |
| Row Order | Rows kept in key order (logical, not physical placement) | Its own key order, unrelated to the table's |
| Max key size | 900 bytes | 1,700 bytes since SQL Server 2016 (Microsoft Learn, *CREATE INDEX*) |

### When to Use Clustered
```sql
-- Good: Primary Key on numeric ID
CREATE CLUSTERED INDEX PK_Id ON Table (Id)

-- Good: Often searched column
CREATE CLUSTERED INDEX CIX_TenantId ON Table (TenantId)

-- Bad: Very large column (TEXT, BLOB)
-- CREATE CLUSTERED INDEX CIX_Builder ON Table (BuilderObject)
-- ❌ Wastes space and slows everything down
```

> ⚠️ **`CREATE CLUSTERED INDEX CIX_TenantId ON Table (TenantId)` has a cost the comment doesn't mention.** It is not declared `UNIQUE` and `TenantId` is full of duplicates, so SQL Server silently adds a hidden 4-byte **uniqueifier** to make each key distinct — Microsoft Learn (*Index architecture and design guide*): "If the clustered index isn't unique, a 4-byte internal uniqueifier column is automatically added to the index key to ensure uniqueness." The uniqueifier is only materialised for the second and subsequent rows sharing a key value, and — because the clustered key is the row locator — it is copied into every non-clustered index alongside the key. A non-unique clustered index on a low-cardinality column is the most expensive kind: you pay the width in every index, and you get almost no seek selectivity for it. If you cluster on `TenantId`, cluster on `(TenantId, Id)` and declare it unique.

### The row locator: what a non-clustered index leaf actually points at

This is the single mechanism that explains most SQL Server index design decisions, and it is the one the ASCII diagrams above get wrong. A non-clustered index leaf row does not hold a disk address. It holds a **row locator**, and what the locator *is* depends on how the table is stored:

```
CASE 1 — table is a HEAP (no clustered index)

  NC index leaf row:  [ TenantId ][ RID: file:page:slot ]
                                        │
                                        └─► direct hop to that
                                            physical slot
  Plan operator:  RID Lookup

CASE 2 — table has a CLUSTERED index on (Id)   ← the normal case

  NC index leaf row:  [ TenantId ][ Id ]
                                    │
                                    └─► seek the CLUSTERED index
                                        for that Id — a second
                                        full tree descent
  Plan operator:  Key Lookup
```

Three consequences follow, and they are what a senior candidate is expected to derive on the spot:

**1. The clustered key's width is charged to every non-clustered index.** A `uniqueidentifier` clustered key means 16 bytes are copied into every leaf row of every non-clustered index on that table. Ten non-clustered indexes on a hundred-million-row table means the key is stored a billion times. This is why "make the clustered key narrow" is advice about *the other indexes*, not about the clustered index itself.

**2. The locator columns are added to the index key or to the includes, depending on uniqueness.** Microsoft Learn (*Index architecture and design guide*) tabulates it: on a table with a unique clustered index, a **non-unique** non-clustered index gets the clustered keys "added to key columns", while a **unique** non-clustered index gets them "added to included columns". The engine "never stores a given column more than once in a nonclustered index", and locator columns are appended "at the end of the key, following the columns specified in the index definition."

**3. You can seek and sort on the clustered key for free.** Because the clustered key is physically present in the leaf, the optimizer can use it "regardless of whether they are explicitly specified in the index definition" (same source). An index on `(CustomerId)` over a table clustered on `(Id)` is really `(CustomerId, Id)`, so `WHERE CustomerId = 7 ORDER BY Id` needs no sort — a fact worth knowing before you widen an index to get it.

> 🌍 **In the real world**: an integrations table used the partner's reference string — `varchar(400)`, genuinely unique — as its primary key, because every inbound webhook looked rows up by it. Lookups were fast, code review passed, and nothing surfaced for a year. What eventually surfaced was in the storage graph: the table's indexes together were larger than the table. Nobody had added a big index; the six modest ones had each quietly grown by 400 bytes per row, because the clustered key is the row locator and gets copied into all of them. The buffer pool filled with index pages that were mostly one repeated string, hot data got evicted, and read latency drifted up across endpoints that had nothing to do with webhooks. The fix was structural and boring: `int IDENTITY` clustered primary key, plus a `UNIQUE` non-clustered index on the reference to keep the guarantee. Same constraints, same queries, every secondary index smaller. SQL Server's key ceilings — 900 bytes clustered, 1,700 non-clustered since SQL Server 2016, 32 key columns (Microsoft Learn, *CREATE INDEX*) — are the engine describing what it expects a key to look like, and a 400-byte key is near the edge of that envelope for a reason.

### Engine differences that change the answer

Almost everything above is SQL Server. Carrying it unmodified to another engine produces confidently wrong answers, which is exactly what an interviewer probing "have you worked outside SQL Server?" is testing for.

| | SQL Server | PostgreSQL | MySQL / InnoDB |
|---|---|---|---|
| Table storage | Clustered index **or** heap; you choose | Always a heap. There is no maintained clustered index | Always clustered on the PK — no choice |
| If you don't pick a key | Heap, unless `PRIMARY KEY` creates a clustered index | Heap with `ctid` row identity | InnoDB clusters on the first `UNIQUE NOT NULL` index, else a hidden 6-byte row ID |
| Non-clustered leaf holds | Clustered key, or RID on a heap | `ctid` (physical tuple pointer) | **The primary key value** |
| Rows kept in key order | Yes, by the clustered index (logical order — not physical placement on disk) | No; `CLUSTER` reorders once and then decays — see below | Yes, by the PK |
| Covering columns | `INCLUDE (…)` | `INCLUDE (…)`, PostgreSQL 11+ | No `INCLUDE`; widen the key instead |
| Partial / filtered index | `WHERE` on `CREATE INDEX`, 2008+ | Partial indexes, long supported | **Not supported** |
| `DESC` in a key | Real, stores descending | Real, stores descending | Ignored before MySQL 8.0; real from 8.0 (MySQL Reference Manual, *Descending Indexes*) |

Two of these bite hardest in practice:

- **PostgreSQL has no clustered index.** `CLUSTER table USING index` is a one-shot physical reorder, not a maintained property: "Clustering is a one-time operation: when the table is subsequently updated, the changes are not clustered" (PostgreSQL docs, *CLUSTER*). It also takes an `ACCESS EXCLUSIVE` lock, which "prevents any other database operations (both reads and writes) from operating on the table" for the duration. Answering "I'd add a clustered index" to a PostgreSQL question is an immediate tell.
- **InnoDB's secondary indexes store the primary key**, so consequence (1) above applies to MySQL with even more force than to SQL Server — and MySQL has no `INCLUDE`, so the only way to make an index covering is to add columns to the key, which widens what gets copied. A UUID primary key in InnoDB is doubly expensive: random insert order in the clustered index, and the full UUID duplicated in every secondary index.

---

## Memory Overhead Explained

### Question 3: How Memory Overhead?

### Memory Allocation in SQL Server

#### Server Memory Structure
```
Total Server RAM: 16GB
├─ Operating System: 2GB
├─ SQL Server: 14GB
│  ├─ Buffer Pool (Data Cache): 10GB
│  │  ├─ Table Pages: 6GB
│  │  └─ Index Pages: 4GB ← Memory Overhead!
│  ├─ Procedure Cache: 2GB
│  ├─ Log Buffer: 1GB
│  └─ Other: 1GB
└─ Available: 0GB (fully allocated)
```

### How Indexes Use Memory

```
Every time SQL Server reads an index page:
1. Fetch from disk (slow: 10-20ms)
2. Store in RAM buffer pool (fast: <1ms)
3. Keep in RAM for reuse

More indexes = More pages in RAM
More pages in RAM = Less memory for other uses
```

### Real Memory Consumption Example

```
Index Memory Impact:

Simple Index (Single Column):
├─ Page Size: 8KB per page
├─ Pages in RAM: 100 (frequently accessed)
└─ Memory Used: 800KB (minimal)

Covering Index (Multiple Columns):
├─ Page Size: 8KB per page
├─ Pages in RAM: 5000 (contains much data)
└─ Memory Used: 40MB (significant)

Multiple Covering Indexes:
├─ Index 1: 40MB
├─ Index 2: 40MB
├─ Index 3: 35MB
├─ Index 4: 30MB
└─ Total: 145MB (not counting growth!)
```

### Memory vs Performance Trade-off

```
Low Memory Scenario (4GB Server):
─────────────────────────────────
System: 2GB, SQL: 2GB
Only 1GB for data + indexes

Many indexes = 800MB index cache
Only 200MB for table data ❌ Severe slowdown

High Memory Scenario (64GB Server):
─────────────────────────────────
System: 2GB, SQL: 62GB
50GB available for data + indexes

Many indexes = 2GB index cache
Still 48GB for table data ✅ Optimal
```

### Monitor Memory Usage

```sql
-- Check memory used by each index
SELECT 
    OBJECT_NAME(i.object_id) AS TableName,
    i.name AS IndexName,
    ps.page_count * 8 / 1024 AS SizeInMB,
    ps.page_count * 8 AS SizeInKB
FROM sys.indexes i
INNER JOIN sys.dm_db_index_physical_stats(
    DB_ID(), 
    NULL, 
    NULL, 
    NULL, 
    'LIMITED'
) ps ON i.object_id = ps.object_id AND i.index_id = ps.index_id
WHERE database_id = DB_ID()
ORDER BY ps.page_count DESC;

-- Check buffer pool usage
SELECT 
    COUNT(*) * 8 / 1024 AS BufferPoolMB
FROM sys.dm_os_buffer_descriptors
WHERE database_id = DB_ID();
```

---

## Why Too Many Indexes Slow Down Queries

### Question 4: Why Slow Down Queries if Too Many Indexes?

### Problem 1: Write Performance Degradation

#### INSERT Performance Impact
```sql
-- Scenario: Insert 1 record into table with 10 indexes

WITHOUT INDEXES:
INSERT INTO Table VALUES (...)
├─ Write to table: 5ms
├─ Update indexes: 0ms
└─ Total: 5ms ✅

WITH 10 INDEXES:
INSERT INTO Table VALUES (...)
├─ Write to table: 5ms
├─ Update IX_TenantId: 1ms
├─ Update IX_WorkflowId: 1ms
├─ Update IX_DiagramId: 1ms
├─ Update IX_TenantId_WorkflowId: 2ms
├─ Update IX_TenantId_DiagramId: 2ms
├─ Update IX_WorkflowId_DiagramId: 2ms
├─ Update IX_TenantId_CreatedAt: 1ms
├─ Update IX_CreatedAt_WorkflowId: 1ms
├─ Update IX_Covering1: 3ms
├─ Update IX_Covering2: 3ms
└─ Total: 22ms ❌ (4.4x slower!)
```

#### Bulk Insert Impact
```sql
-- Insert 1,000,000 rows

Without Indexes:
├─ Time: 5 minutes ✅
├─ Indexes: None to maintain

With 10 Indexes:
├─ Time: 22 minutes ❌ (4.4x slower)
├─ Each row updates 10 index structures
├─ Lock contention on index pages
├─ Memory thrashing (indexes exceed cache)
```

### Problem 2: Query Optimizer Confusion

#### Scenario: Multiple Choices
```sql
Query: SELECT * FROM Table 
       WHERE TenantId = 1 AND WorkflowId = 100

Available Indexes:
1. IX_TenantId (covers 30% of table)
2. IX_WorkflowId (covers 10% of table)
3. IX_DiagramId (covers 5% of table)
4. IX_CreatedAt (covers 20% of table)
5. IX_UpdatedAt (covers 15% of table)
6. IX_TenantId_WorkflowId (covers 0.1% of table) ← BEST!
7. IX_TenantId_DiagramId (covers 2% of table)
8. IX_WorkflowId_DiagramId (covers 1% of table)
9. IX_Covering1 (covers 0.1% of table) ← ALSO GOOD
10. IX_Covering2 (covers 0.1% of table) ← ALSO GOOD

Optimizer Decision:
├─ Good choice: Uses IX_TenantId_WorkflowId (fast)
└─ Bad choice: Uses IX_TenantId (slower, unnecessary)

With Too Many Similar Indexes:
├─ More candidate plans to cost → longer compilation
├─ Near-identical costs → small estimate errors flip the choice
└─ Redundancy becomes hard for humans to spot
```

> ⚠️ **"The optimizer chooses randomly" is wrong, and saying it in an interview signals you think the optimizer is a black box.** SQL Server's optimizer is **cost-based**: it enumerates candidate plans, costs each one against the statistics, and takes the cheapest. It never picks at random. What genuinely degrades with many similar indexes is subtler and worth stating precisely:
>
> - **Compilation cost rises.** More candidate access paths means a larger search space; the optimizer works under a time/effort budget and can stop before exploring the plan you wanted.
> - **Plans become unstable.** When `(TenantId, WorkflowId)` and `(TenantId, WorkflowId, CreatedAt)` cost nearly the same, a small change in estimates flips the choice. The plan changed because the cost changed, which is the optimizer working correctly — but the *outcome* is the unpredictability the box describes.
> - **The write path pays for all of them regardless of which one gets chosen.** This is the real cost and it is unrelated to optimizer behaviour.

#### Query Plan Regression
```sql
-- Yesterday
SELECT * FROM Table WHERE TenantId = 1
├─ Used: IX_TenantId (fast)

-- Today
SELECT * FROM Table WHERE TenantId = 1
├─ Optimizer chose a different index
└─ Actual causes, in order of likelihood:
   ├─ Statistics auto-updated, changing the estimates
   ├─ Parameter sniffing: a new first-call value
   │  recompiled the plan for a different distribution
   ├─ The plan cache was cleared (restart, memory
   │  pressure, ALTER on the object, sp_recompile)
   └─ Data distribution genuinely shifted
```

> ⚠️ **"Statistics cache invalidation" is not a SQL Server mechanism and the "250x slower" figure was invented.** The real causes are listed above. To diagnose plan regressions rather than guess at them, use **Query Store** (SQL Server 2016+): it records every plan a query has had along with its runtime metrics, shows you the regression on a timeline, and lets you force the previous plan while you work out what changed. "I'd check Query Store for a plan change" is the answer an interviewer is listening for.

### Problem 3: Index Maintenance Overhead

```
Daily Index Maintenance:

5 Indexes:
├─ Fragmentation check: 30 seconds
├─ Statistics update: 1 minute
├─ Backup time: 5 minutes
└─ Total: ~7 minutes

15 Indexes:
├─ Fragmentation check: 2 minutes
├─ Statistics update: 5 minutes
├─ Reorganize: 10 minutes
├─ Backup time: 15 minutes
└─ Total: ~32 minutes (4.5x slower!)

Nightly Maintenance Window: 2 hours
├─ 5 indexes: Completes in 40 minutes ✅
├─ 15 indexes: Completes in 2 hours 15 minutes ❌ (exceeds window!)
└─ Remaining work spills into business hours
```

### Problem 4: Index Lock Contention

```
Multi-threaded INSERT scenario:

With Few Indexes:
Thread1: INSERT → Updates 3 indexes → Done
Thread2: INSERT → Updates 3 indexes → Done
Thread3: INSERT → Updates 3 indexes → Done
Throughput: 100,000 inserts/second ✅

With Many Indexes:
Thread1: INSERT → Updates 15 indexes → Lock contention!
Thread2: INSERT → Waits for locks → Slow
Thread3: INSERT → Waits for locks → Slow
Throughput: 20,000 inserts/second ❌ (5x slower)
```

### When Indexes Actually Help (vs. Hurt)
```
✅ Good Scenarios (Few Indexes):
├─ Read-heavy workloads (95% SELECT, 5% INSERT)
├─ Data warehouse (mostly inserts overnight)
├─ Tables with specific query patterns
└─ Small number of frequently used columns

❌ Bad Scenarios (Too Many Indexes):
├─ Write-heavy workloads (50% INSERT, 50% SELECT)
├─ OLTP systems with high concurrency
├─ Tables with many possible query patterns
├─ Often-updated columns
└─ Limited disk space or memory
```

### Recommended Index Limits
```
Table Size         Recommended Indexes
─────────────────  ─────────────────────
<100,000 rows      0-3 indexes
100K-1M rows       3-8 indexes
1M-10M rows        5-12 indexes
>10M rows          8-20 indexes

(Plus 1 clustered index)
```

> ⚠️ **Unsourced, and it used to contradict the rest of the document** — the [Index Budget](#index-budget) section originally gave 5-15 indexes for tables over 10M rows where this table gives 8-20. (Index Budget's numbers have since been replaced with the reasoning behind them; these have been left in place as the exhibit.) Neither figure was ever measured, which is the point. Row count is also the wrong axis: a 50-million-row append-only table carries many indexes cheaply because every insert lands at the right-hand edge of each one, while a 2-million-row table taking a thousand updates a second can be crippled by three. If you quote a number in an interview, quote it as "there is no number" and then say what actually binds — write rate, insert ordering, buffer pool pressure, and how many query shapes each index serves. That reasoning is in [Index Budget](#index-budget).

---

## Composite Index Column Order

### Question 5: Composite Index Column Order Explanation

### The Critical Importance of Column Order

#### Concept: Tree Navigation
```
Index: CREATE INDEX IX ON Table (TenantId, WorkflowId)

Index Tree Structure:
Level 1 (Root):
┌────────────────────────────┐
│ Partitions: [1-5], [6-10]  │
└────────────────────────────┘
         ↙            ↘
Level 2 (Intermediate):
[1,2,3,4,5]         [6,7,8,9,10]
TenantId branches
│
Level 3 (TenantId=1):
┌───────────────────────────┐
│ WorkflowId: [10,20,30,40] │
└───────────────────────────┘
│
Leaf Nodes:
TenantId=1, WorkflowId=10 → Row Ptr
TenantId=1, WorkflowId=20 → Row Ptr
TenantId=1, WorkflowId=30 → Row Ptr
TenantId=1, WorkflowId=40 → Row Ptr
```

### Query Performance by Column Order

#### Query 1: WHERE TenantId = 1 AND WorkflowId = 100
```
Index: (TenantId, WorkflowId) ← Matches query perfectly

Execution:
Step 1: Root node → Find TenantId=1 branch
Step 2: Intermediate → Find WorkflowId=100 under TenantId=1
Step 3: Leaf → Get exact row pointer
Step 4: Seek to table row

Access Pattern: Binary search → Exact match
Pages Scanned: 1 (just the exact leaf)
Time: ~0.5ms ✅ VERY FAST
Logical Reads: 3 (root + intermediate + leaf)
```

#### Query 2: WHERE TenantId = 1
```
Index: (TenantId, WorkflowId) ← Can use leading column!

Execution:
Step 1: Root node → Find TenantId=1 branch
Step 2: Intermediate → Get all WorkflowIds under TenantId=1
Step 3: Scan all leaves for TenantId=1
Step 4: Collect all row pointers

Access Pattern: Range scan on TenantId
Pages Scanned: ~100 (all TenantId=1 entries)
Time: ~2ms ✅ FAST
Logical Reads: 102 (root + intermediate + 100 leaf pages)

Key Point: Can use composite index even without second column!
```

#### Query 3: WHERE WorkflowId = 100 (No TenantId filter)
```
Index: (TenantId, WorkflowId) ← WorkflowId not first!

Execution:
Step 1: Root node → Must check all TenantId branches
Step 2: Intermediate → Must scan all WorkflowId sections
Step 3: Scan ENTIRE index tree looking for WorkflowId=100
Step 4: Check every leaf node

Access Pattern: Full index scan — no seek boundary exists
Pages Scanned: the whole index
Time: ❌ SLOW

Key Point: without the leading column, the index cannot
           narrow the search. It can still be READ.
```

> ⚠️ **Two corrections to "the index is useless here".** First, a full scan of a narrow index is normally *cheaper* than a full scan of the table — the index rows are a few columns wide, the table rows are the whole row, so there are far fewer pages. The optimizer often picks exactly this plan and it is not a bug; it's the cheapest scan available. What you have lost is the *seek*, not the index. Second, some engines have an **index skip scan**, which turns the missing leading column into many small seeks — one per distinct leading value. It exists in PostgreSQL 18+, MySQL 8.0.13+ and Oracle; **SQL Server has no such operator**. So on SQL Server the answer really is "add an index led by `WorkflowId` if this query is hot", while on PostgreSQL 18 the honest answer is "it may skip-scan, which is viable while `TenantId` has few distinct values and collapses when it has many."

### Visual Sorting Order

```
Index: (TenantId, WorkflowId)
Internal Sort Order:

TenantId | WorkflowId | Data...
---------|------------|--------
1        | 10         | ...    ← Sorted first by TenantId
1        | 20         | ...
1        | 30         | ...
1        | 100        | ...
1        | 200        | ...
2        | 5          | ...    ← Then within TenantId=2
2        | 15         | ...
2        | 100        | ...    ← WorkflowId=100 appears in multiple places
3        | 10         | ...
3        | 100        | ...    ← Scattered throughout

Query: WHERE WorkflowId = 100
Must scan: Row 5, Row 11, Row 19 (scattered)
Index cannot use binary search!
```

### Comparison of Different Orders

```
Query: WHERE TenantId = 1 AND WorkflowId = 100

Option A: Index (TenantId, WorkflowId)
├─ Query Matches: ✅ PERFECT
├─ Search Efficiency: Binary search on both
├─ Speed: 0.5ms
└─ Logical Reads: 3

Option B: Index (WorkflowId, TenantId)
├─ Query Matches: ⚠️ PARTIAL
├─ Search Efficiency: Binary search on WorkflowId only
│  Then filter TenantId within results
├─ Speed: 5ms
└─ Logical Reads: 100

Option C: Index (CreatedAt, TenantId)
├─ Query Matches: ❌ NO MATCH
├─ Search Efficiency: Full table scan
├─ Speed: 500ms
└─ Logical Reads: 10,000

Best: Option A (matches column order in WHERE clause)
```

### Best Practice: Selectivity Order

> ⚠️ **This section originally taught "most selective column first". That rule is folklore, and it is the single most-repeated wrong answer about composite indexes.** It is corrected below rather than deleted, because you will hear it in interviews and need to be able to say why it's wrong without sounding like you're contradicting for sport.
>
> **Why it's wrong.** For a query with **equality predicates on every key column**, column order does not change how many index rows the seek touches. `WHERE TenantId = 1 AND WorkflowId = 100 AND DiagramId = 50` finds exactly the rows satisfying all three, whether the index is `(DiagramId, WorkflowId, TenantId)` or `(TenantId, WorkflowId, DiagramId)`. The seek descends to one contiguous range either way. The original worked example — "wrong order narrows to 100,000 rows, then 1,000, then 2, so 5,000 pages scanned" — describes something the engine does not do; it does not read 100,000 index rows and then filter them. A composite seek positions on the full key prefix in one descent.
>
> **What actually decides column order**, in priority order:

```
RULE 1 — Equality columns first. Range column LAST.
─────────────────────────────────────────────────────
A seek boundary can use a run of equality predicates plus
AT MOST ONE range predicate. Everything after the range
column in the key stops bounding the seek and becomes a
residual filter — rows are read, then thrown away.

  Query:  WHERE TenantId = 1
            AND CreatedAt >= '2026-01-01'
            AND Status = 'Active'

  Index (TenantId, CreatedAt, Status):
    seek bounds on TenantId=1 AND CreatedAt>=...
    Status is AFTER the range column → residual filter.
    Reads every row for that tenant since Jan 1,
    discards the ones that aren't Active.       ⚠️

  Index (TenantId, Status, CreatedAt):
    seek bounds on TenantId=1 AND Status='Active'
    AND CreatedAt>=...  → all three bound the seek.
    Reads only rows it will return.              ✅

  Same columns. Same "selectivity". Completely
  different amount of work.

RULE 2 — Leading column = the one the most queries filter on.
─────────────────────────────────────────────────────
An index on (A, B, C) can SEEK for queries filtering only on
A, and only on (A, B). It cannot seek for anything filtering
on B or C alone — the best it can do there is be scanned end
to end, which is cheaper than scanning the table but is not
what you built it for. So the leading column determines how
many query shapes this one index can pay for. On a multi-
tenant table, TenantId leads almost everything for exactly
this reason — even though it is the LEAST selective column
in the schema.

RULE 3 — Then order to satisfy ORDER BY, for free.
─────────────────────────────────────────────────────
If the index's remaining columns match the query's sort,
the Sort operator disappears from the plan. A Sort is a
blocking, memory-granting operator that can spill to
tempdb; removing it often beats any I/O saving.

RULE 4 — Only now, if there's still a free choice,
         put the more selective column earlier.
```

**The three-star model.** Lahdenmäki and Leach's *Relational Database Index Design and the Optimizers* gives the standard framework, and it is worth being able to recite:

| Star | Condition | What it buys |
|---|---|---|
| ★1 | Rows the query wants are **adjacent** in the index — equality predicates form the leading key columns | The seek reads a contiguous range instead of filtering |
| ★2 | Index rows are already in the query's **required order** | No Sort operator |
| ★3 | The index contains **all columns the query needs** | No lookups (covering) |

A three-star index is the best possible index for one query shape. You cannot give three stars to every query, and trying is how tables end up with thirty indexes. The judgement is which queries deserve which stars.

> 🌍 **In the real world**: a reporting query on a multi-tenant orders table was tuned by a contractor who applied "most selective first" faithfully. `OrderReference` had the highest cardinality, so the index went in as `(OrderReference, TenantId, CreatedAt)`. It was measurably excellent for the one query used to justify it — which filtered on all three — and useless for everything else in the application, because nothing else knew an order reference up front. The screens that filtered by tenant and date still scanned, so the next sprint added `(TenantId, CreatedAt)`, and now the table carried two indexes where one `(TenantId, CreatedAt, OrderReference)` would have served both plus the tenant-only queries. Nobody had done anything careless; the rule they were following was just the wrong rule. Selectivity decides how *good* an index is for one query. The leading column decides how *many* queries it can serve at all, and that is the decision with the bigger blast radius.

---

## Index Sorting

### Question 6: Are Index Columns Sorted?

### YES - Indexes are Always Sorted!

#### How Sorting Works

```sql
CREATE INDEX IX_TenantId_WorkflowId ON Table (TenantId, WorkflowId)
```

**Leaf Level Layout (Key Order — not physical placement on disk):**
```
Index Leaf Page Content:
┌─────────────────────────────────────┐
│ TenantId | WorkflowId | Row Pointer │
├─────────────────────────────────────┤
│ 1        | 10         | 0x1000      │
│ 1        | 15         | 0x1500      │ ← Sorted ascending
│ 1        | 20         | 0x2000      │    by TenantId first
│ 1        | 25         | 0x2500      │
│ 2        | 5          | 0x3000      │ ← Then by WorkflowId
│ 2        | 10         | 0x3500      │
│ 2        | 15         | 0x4000      │
│ 3        | 8          | 0x4500      │
└─────────────────────────────────────┘
```

### Benefits of Sorting

#### 1. Binary Search
```
Traditional Search (Unsorted):
Check position 1: TenantId=5 (not a match)
Check position 2: TenantId=2 (not a match)
Check position 3: TenantId=1 ✅ (match!)
Result: 3 comparisons

Binary Search (Sorted):
Check position 500: TenantId=5 (target is lower)
Check position 250: TenantId=2 (target is higher)
Check position 375: TenantId=1 ✅ (match!)
Result: eliminates half the remaining range each time
Scale: With 1 million rows
Unsorted: ~500,000 comparisons on average
Sorted:   ~20 comparisons (log2 of 1,000,000)
```

> ⚠️ **A seek is not a binary search over the sorted list — and the difference is why B-trees beat balanced binary trees on disk.** A B+ tree descends level by level. Within each 8 KB page the engine *does* binary-search the rows, but the number of pages it touches is the **depth** of the tree, and depth is governed by **fanout**: how many child pointers fit on one page. With a narrow key, an 8 KB page holds hundreds of entries, so each level multiplies capacity by hundreds rather than by two.
>
> ```
> Binary tree over 1,000,000 rows:  log2(1,000,000)   ≈ 20 node reads
> B+ tree, fanout ~400:             log400(1,000,000) ≈ 3 page reads
> ```
>
> Twenty random reads versus three. That gap — not sortedness in the abstract — is why every disk-backed index in every major engine is a B-tree variant. It also explains why key width matters so much: a wider key means fewer entries per page, which means lower fanout, which means a deeper tree, which means more page reads on **every** seek. "Narrow keys make shallow trees" is the whole argument in five words.

#### 2. Range Queries
```sql
-- Query: WHERE TenantId BETWEEN 1 AND 3
Index (TenantId, WorkflowId):

Sorted Index:
├─ Find first TenantId=1 (binary search)
├─ Scan sequentially: TenantId=1,1,1,2,2,2,3,3
├─ Stop at TenantId=4
├─ Pages Scanned: 10
└─ Time: 1ms ✅

Unsorted Index (hypothetical):
├─ Scan entire index
├─ Check each: TenantId=5? No. TenantId=1? Yes. TenantId=3? Yes.
├─ Pages Scanned: 10,000
└─ Time: 500ms ❌
```

#### 3. ORDER BY Optimization
```sql
Query: SELECT * FROM Table WHERE TenantId=1 ORDER BY WorkflowId

Index: (TenantId, WorkflowId)

With Sorted Index:
├─ Find TenantId=1 (binary search)
├─ Read sequentially: WorkflowId 10,15,20,25,30,...
├─ Results naturally ordered!
├─ No additional sort operation needed
└─ Time: 2ms ✅

Without Index (Table Scan):
├─ Scan entire table
├─ Filter TenantId=1 → 100,000 rows
├─ Sort 100,000 rows by WorkflowId
├─ Sorting overhead: 1000ms
└─ Time: 1500ms ❌
```

### Sort Order Control

```sql
-- Ascending order (default)
CREATE INDEX IX_ASC ON Table (TenantId ASC, WorkflowId ASC)

-- Descending order (rare, specific use case)
CREATE INDEX IX_DESC ON Table (TenantId DESC, WorkflowId DESC)

-- Mixed order (uncommon but possible)
CREATE INDEX IX_MIXED ON Table (TenantId ASC, WorkflowId DESC)

Use Case for DESC:
SELECT TOP 10 * FROM Table ORDER BY CreatedAt DESC
```

> ⚠️ **Correction — for a single-column sort, `DESC` in the index buys you almost nothing, and the reason it sometimes does is not the one usually given.** A B-tree's leaf pages are doubly linked, so SQL Server can read any index backwards; an ascending index serves `ORDER BY CreatedAt DESC` with a **backward ordered scan** at essentially the same cost. There is no "reverse scan penalty" to avoid.
>
> The two cases where `DESC` genuinely matters:
>
> 1. **Mixed sort directions in a composite index.** `ORDER BY TenantId ASC, CreatedAt DESC` cannot be satisfied by `(TenantId ASC, CreatedAt ASC)` in either direction — reading that index backwards gives you `TenantId DESC, CreatedAt DESC`. You need `(TenantId ASC, CreatedAt DESC)` to eliminate the Sort. This is the real use case and it is the one interviewers ask about.
> 2. **Parallelism.** SQL Server cannot use a parallel plan with a backward ordered scan. On a large scan-and-aggregate query, matching the index direction to the query's direction is what lets the plan go parallel. This is well documented in the SQL Server community — Brent Ozar's *When Should You Use DESC in Indexes?* is the accessible write-up — and it is a genuine reason to add `DESC` to a warehouse index.
>
> **Engine note:** MySQL ignored `DESC` in index definitions entirely before 8.0 — "`DESC` in an index definition is no longer ignored but causes storage of key values in descending order. Previously, indexes could be scanned in reverse order but at a performance penalty" (MySQL Reference Manual, *Descending Indexes*). PostgreSQL has stored real `DESC` ordering for far longer, and also has `NULLS FIRST` / `NULLS LAST` as part of the index definition.

### How SQL Maintains Sorting

```
When you INSERT:
INSERT INTO Table VALUES (TenantId=2, WorkflowId=15)

Index Update Process:
1. Descend the tree to find the target leaf page
2. If the page has free space: write the row anywhere on
   the page, and insert its offset into the page's SLOT
   ARRAY at the right position. Nothing is physically
   shifted — the slot array supplies the logical order.
3. If the page is FULL: page split (see below)
4. Propagate upward only if the split forced a new key
   into the parent

Example:
Before: 1|10 → 1|20 → 2|5 → 2|30
Insert (TenantId=2, WID=15)
After: 1|10 → 1|20 → 2|5 → 2|15 → 2|30  ✅ Still sorted!

This is why INSERT is slower with indexes:
Must maintain sorted order in every index, on every write
```

**Page splits — the mechanism behind fragmentation, and behind fill factor.**

```
Leaf page is FULL and a row must go in the middle of it:

  BEFORE                    AFTER
  ┌──────────────┐          ┌──────────────┐   ┌──────────────┐
  │ 10 20 30 40  │   ───►   │ 10 20   ░░   │──►│ 25 30 40 ░░  │
  │ (100% full)  │          │ (~50% full)  │   │ (~50% full)  │
  └──────────────┘          └──────────────┘   └──────────────┘
                            new page allocated wherever there is
                            free space — likely NOT adjacent

Costs, all at once:
  • the split itself is a logged, transactional operation
  • two pages now hold what one held → page density halves
  • the new page is out of physical sequence → logical
    fragmentation
  • the parent gets a new key, and may split in turn
```

Microsoft's guidance on the countermeasure is narrower than folklore suggests: "To avoid lowering page density unnecessarily, Microsoft doesn't recommend setting fill factor to values other than 100 or 0, except in certain cases for indexes experiencing a high number of page splits. For example, this can occur in frequently modified indexes with the leading column that contains nonsequential GUID values" (Microsoft Learn, *Maintain indexes optimally*). A fill factor below 100 reserves empty space *everywhere*, permanently, to absorb inserts that only land in *some* places. On a monotonically increasing key, inserts only ever go to the rightmost page, so the reserved space is never used and you have simply made every scan read more pages.

---

## Covering Indexes

### Question 7: How Covering Index Eliminates Table Access?

### The Problem: Key Lookups

#### Without Covering Index

```sql
CREATE INDEX IX_Normal ON Table (TenantId, WorkflowId)

Query:
SELECT TenantId, WorkflowId, DiagramId, BuilderObject 
FROM Table 
WHERE TenantId = 1 AND WorkflowId = 100
```

**Two-Step Process:**
```
Step 1: Search Index (10 bytes per entry)
├─ Find TenantId=1, WorkflowId=100
├─ Get row pointer: 0x5000
└─ Time: 0.5ms

Step 2: Key Lookup in Table (2KB per row!)
├─ Jump to table position 0x5000
├─ Read entire row into memory
├─ Extract: TenantId, WorkflowId, DiagramId, BuilderObject, 
           CreatedBy, UpdatedBy, CreatedAt, UpdatedAt
├─ Return only 4 columns to user
└─ Time: 4ms

Total Time: 4.5ms
Efficiency: Low (read 2KB, use 500 bytes!)
```

**Visual Representation:**
```
Request:
┌──────────────────────────────────────┐
│ SELECT TenantId, WorkflowId,         │
│        DiagramId, BuilderObject      │
│ FROM Table                           │
│ WHERE TenantId=1 AND WorkflowId=100  │
└──────────────────────────────────────┘
       ↓
    Index Search
┌──────────────────────────────────────┐
│ Index: (TenantId, WorkflowId)        │
│ Entry: 1|100 → Row Pointer: 0x5000   │ ✅ Found!
└──────────────────────────────────────┘
       ↓
    ❌ Must Jump to Table
┌──────────────────────────────────────┐
│ Table Row at 0x5000:                 │
│ Id|TenantId|WorkflowId|DiagramId|    │
│ BuilderObject|CreatedBy|UpdatedBy|   │
│ CreatedAt|UpdatedAt                  │
│ ↓ (read all, return 4 columns)       │
└──────────────────────────────────────┘
       ↓
    Return to User
┌──────────────────────────────────────┐
│ TenantId | WorkflowId | DiagramId |  │
│ BuilderObject                        │
└──────────────────────────────────────┘

Wasted I/O: Read 8 columns, returned 4 columns
```

### The Solution: Covering Index

```sql
CREATE INDEX IX_Covering ON Table (TenantId, WorkflowId)
INCLUDE (DiagramId, BuilderObject)

Query:
SELECT TenantId, WorkflowId, DiagramId, BuilderObject 
FROM Table 
WHERE TenantId = 1 AND WorkflowId = 100
```

**One-Step Process:**

```
Step 1: Search Index (500 bytes per entry - includes data!)
├─ TenantId=1, WorkflowId=100
├─ DiagramId=50 (included in index!)
├─ BuilderObject={JSON data} (included in index!)
├─ ✅ ALL DATA IN INDEX!
└─ Time: 1ms

Step 2: ❌ NO TABLE ACCESS NEEDED!

Total Time: 1ms (4.5x faster!)
Efficiency: Perfect (read only what's needed!)
```

**Visual Representation:**
```
Request:
┌──────────────────────────────────────┐
│ SELECT TenantId, WorkflowId,         │
│        DiagramId, BuilderObject      │
│ FROM Table                           │
│ WHERE TenantId=1 AND WorkflowId=100  │
└──────────────────────────────────────┘
       ↓
    Index Search
┌──────────────────────────────────────┐
│ Index Entry:                         │
│ TenantId=1, WorkflowId=100           │
│ DiagramId=50                         │ ✅ Here!
│ BuilderObject={...}                  │ ✅ Here!
│ Row Pointer: 0x5000                  │ (not needed)
└──────────────────────────────────────┘
       ↓
    ✅ NO Table Access Needed!
    Return directly to user
       ↓
    Return to User
┌──────────────────────────────────────┐
│ TenantId | WorkflowId | DiagramId |  │
│ BuilderObject                        │
└──────────────────────────────────────┘

All Data from Index: 100% efficiency!
```

### Index Anatomy: Normal vs Covering

```
Normal Index: (TenantId, WorkflowId)
┌─────────────────────────────────┐
│ Root Page                       │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│ Intermediate Page               │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│ Leaf Page (Index):              │
│ TenantId|WorkflowId|RowPointer  │ ← 24 bytes per entry
│ 1|100|0x5000                    │
│ 1|200|0x6000                    │
│ 2|50|0x7000                     │
└─────────────────────────────────┘


Covering Index: (TenantId, WorkflowId) INCLUDE (DiagramId, BuilderObject)
┌─────────────────────────────────────┐
│ Root Page                           │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Intermediate Page                   │
└─────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────────────────┐
│ Leaf Page (Index + Data):                                │
│ TenantId|WID|DiagramId|BuilderObject|RowPointer         │
│ 1|100|50|{JSON_1}|0x5000                                 │
│ 1|200|75|{JSON_2}|0x6000                                 │
│ 2|50|25|{JSON_3}|0x7000                                  │
└──────────────────────────────────────────────────────────┘
   ← 500+ bytes per entry (much larger but complete!)
```

### INCLUDE Column Best Practices

```sql
-- ✅ Good: INCLUDE non-key columns
CREATE INDEX IX_Good ON Table (TenantId, WorkflowId)
INCLUDE (DiagramId, BuilderObject, CreatedAt, UpdatedAt)

-- ❌ Bad: INCLUDE a key column
CREATE INDEX IX_Bad ON Table (TenantId)
INCLUDE (WorkflowId)  -- WorkflowId should be in key, not INCLUDE!

-- ❌ Bad: INCLUDE a LOB column
CREATE INDEX IX_Large ON Table (CreatedAt)
INCLUDE (BuilderObject)  -- NVARCHAR(MAX) JSON column
-- (It does remove the key lookup, and pays for it by copying the whole
--  document into the index leaf: the index approaches the size of the
--  table, the buffer pool caches the same JSON twice, and every update
--  to it is written twice. Leave LOBs to the lookup — see the LOB trap
--  under Covering Index above.)

-- ❌ Bad: Too many INCLUDE columns = huge index
CREATE INDEX IX_TooLarge ON Table (TenantId)
INCLUDE (Col1, Col2, Col3, Col4, Col5, Col6, Col7, Col8, Col9, Col10)
-- (Becomes almost as large as table itself!)
```

### Performance Comparison Table

| Aspect | Normal Index | Covering Index |
|--------|--------------|----------------|
| **Size** | Key columns + row locator | Plus every `INCLUDE` column, at the leaf only |
| **Work per row returned** | Seek + one lookup | Seek only |
| **Reads** | Index + base table | Index only |
| **Plan operator** | `Index Seek` + `Key Lookup` (or `RID Lookup` on a heap) | `Index Seek` alone |
| **Write cost** | Updated when key columns change | Also updated when any `INCLUDE`d column changes |
| **Degrades when** | Many rows returned — see the tipping point | Too many/too wide `INCLUDE`s |
| **Use Case** | Selective predicates | Known, hot query shapes |

### The tipping point: why the optimizer abandons your index

The most common "the index is there and it isn't using it" ticket has nothing to do with a broken index. It is the optimizer doing arithmetic correctly.

A seek-plus-lookup plan costs one tree descent per row returned, and those descents are effectively **random** reads scattered across the table. A clustered index scan costs one pass over the table's pages, **sequentially**. As the estimated row count rises, the lookup plan's cost rises linearly while the scan's stays flat — and they cross.

```
cost
 │                                    ╱  seek + key lookup
 │                                  ╱    (cost ∝ rows returned)
 │                                ╱
 │──────────────────────────────╳─────── clustered index scan
 │                            ╱          (cost ≈ constant)
 │                          ╱
 └────────────────────────────────────────► estimated rows
                            ▲
                     the tipping point
```

Kimberly Tripp (SQLskills) is the standard reference for where the crossing happens on SQL Server, and the number is the surprising part: it is expressed in **pages of the table, not rows, and not percent of rows**. Roughly, a non-clustered seek with lookups tends to survive while estimated rows are below about 25% of the table's *page count*, and a scan tends to win above about 33% of it. Since a page holds many rows, that can be a very small fraction of the rows — a few percent is enough to tip a wide table.

Three things follow:

- **A "bad plan" is often a good decision on a bad estimate.** If statistics say 40 rows and reality is 400,000, the optimizer picked the lookup plan for a query that would never have qualified. Fix the estimate, not the plan.
- **Covering removes the cliff entirely.** With no lookup, the per-row cost disappears and the curve flattens. This is the real argument for `INCLUDE`: not "it's faster", but "it stops being a cliff."
- **The threshold is a behaviour, not a constant.** Parallelism, memory, table size and server settings all move it. Quote it as "somewhere in the region of a quarter to a third of the table's pages, per Kimberly Tripp's work at SQLskills" and you're on solid ground; quote it as an exact percentage of rows and you'll be wrong.

### Covering indexes on PostgreSQL do not work the way you expect

PostgreSQL 11+ supports `INCLUDE`, so the syntax transfers. The guarantee does not.

Visibility information in PostgreSQL lives in the heap tuple, not the index entry — the docs state it plainly: "Visibility information is not stored in index entries, only in heap entries; so at first glance it would seem that every row retrieval would require a heap access anyway." The escape hatch is the **visibility map**: "An index-only scan, after finding a candidate index entry, checks the visibility map bit for the corresponding heap page. If it's set, the row is known visible and so the data can be returned with no further work. If it's not set, the heap entry must be visited to find out whether it's visible, so no performance advantage is gained over a standard index scan."

So on PostgreSQL a covering index gives you an `Index Only Scan` **only when `VACUUM` has recently marked the relevant heap pages all-visible**. On a table taking steady writes, the visibility map lags, `EXPLAIN (ANALYZE, BUFFERS)` shows a non-zero `Heap Fetches`, and your "covering" index quietly performs like an ordinary one. The lever is autovacuum aggressiveness on that table, not the index definition — which is not a lever a SQL Server background suggests looking for.

> 🌍 **In the real world**: an order-list endpoint was covered properly — `(customer_id, created_at) INCLUDE (status, total)` — and stayed fast for two years. Then a product change added `ShippingRegion` to the DTO the endpoint returned. One property on a C# record; one extra column in the SELECT that EF Core generates; and the plan went from a single seek to a seek plus one key lookup per row. Nothing failed, nothing errored, no alert fired. p99 drifted up over a release and was written off as traffic growth, and the connection to that PR was never made because the PR touched no SQL. The point is where a covering index's contract actually lives: it is defined by the column list of every query that depends on it, and that list is in the application code, not the schema. An index is the only kind of production dependency that can be broken by editing a DTO. Either the entity carries a comment naming the index it feeds, or a test asserts the plan shape, or the next projection change silently undoes the tuning.

---

## Index Fragmentation

### Question 8: Fragmentation in Index?

### What is Fragmentation?

Fragmentation occurs when index pages are scattered across disk instead of being contiguous.

#### Physical Disk Layout Example

```
Initial State (Perfect - No Fragmentation):
Disk Sectors:
[Sector1][Sector2][Sector3][Sector4][Sector5][Sector6]
[Idx-Page1][Idx-Page2][Idx-Page3][Idx-Page4][Idx-Page5][Idx-Page6]
   └────────────────────── Sequential ──────────────────┘

Single read request gets all 6 pages

---

After Many Operations (Fragmented - 50%):
Disk Sectors:
[Sector1][Sector2][Sector3][Sector4][Sector5][Sector6][Sector7][Sector8]
[Idx-Pg1][Empty  ][Idx-Pg2][Empty  ][Idx-Pg3][Empty  ][Idx-Pg4][Idx-Pg5]
         └─ Gaps ─┘         └─ Gaps ─┘         └─ Gaps ─┘

Multiple read requests needed for scattered pages
```

### Fragmentation Causes

```
1. Frequent INSERT/UPDATE in middle of index
   ├─ New entries added between existing ones
   └─ Existing pages shifted, creating gaps

2. DELETE operations
   ├─ Entries removed, leaving empty space
   └─ Space not reused efficiently

3. Page Splits
   ├─ When page becomes full, split into 2
   ├─ Original page 50% empty, new page 50% empty
   └─ Both scattered on disk

4. Time
   ├─ Fragmentation gradually accumulates
   └─ Over weeks/months becomes significant
```

### Fragmentation Levels and Impact

```
Fragmentation Level | Conventional action | Origin
────────────────────|─────────────────────|──────────────────────
0-10%              | None                | Old Books Online
10-30%             | REORGANIZE          | guidance, widely
30-50%             | REBUILD             | copied, and now
50-100%            | REBUILD             | explicitly disowned
                                           by Microsoft
```

> ⚠️ **These thresholds are the most-copied and least-defensible numbers in SQL Server operations, and the "30-50% slower" impact column was invented — no source supports it.** Microsoft's current position, verbatim from *Maintain indexes optimally to improve performance and reduce resource utilization*: **"Index maintenance decisions should be made after considering multiple factors in the specific context of each workload, including the resource cost of maintenance. They shouldn't be based on fixed fragmentation or page density thresholds alone."** Four things a senior candidate should be able to add:
>
> **1. Page density usually matters more than logical fragmentation.** Microsoft: *"In many workloads, increasing page density results in a greater positive performance impact than reducing fragmentation."* Logical fragmentation costs you when a scan has to jump between out-of-order pages. Low page density costs you *always* — more pages to read, more buffer pool consumed to cache the same rows, higher estimated I/O cost which can change the plan the optimizer picks. The column to watch is `avg_page_space_used_in_percent`, and almost nobody's maintenance script looks at it.
>
> **2. On flash, half the argument evaporates.** Fragmentation hurts because sequential I/O beats random I/O. Microsoft notes that "for most types of storage used in Azure SQL Database and Azure SQL Managed Instance, there's no difference in performance between sequential I/O and random I/O. This reduces the impact of index fragmentation on query performance." The reorganize-then-rebuild rule — quoted as 5/30 as often as the 10/30 in the box above, which is itself a sign nobody measured either — was written for spinning disks with moving heads.
>
> **3. The rebuild that "fixed" performance usually fixed the statistics.** This is the best single fact to have ready. Microsoft again: *"Customers often observe performance improvements after rebuilding indexes. However, in many cases these improvements are unrelated to reducing fragmentation or increasing page density... In reality, the same benefit can often be achieved at a much lower resource cost by updating statistics instead of rebuilding indexes."* A rowstore rebuild updates the index's statistics by scanning every row — the equivalent of `WITH FULLSCAN` — and that recompiles the plans that referenced them.
>
> **4. Small indexes report meaningless fragmentation.** "Rebuilding or reorganizing small rowstore indexes usually doesn't reduce fragmentation. Up to, and including, SQL Server 2014 (12.x), the SQL Server Database Engine allocates space using mixed extents... Mixed extents are shared by up to eight objects, so the fragmentation in a small index might not be reduced after reorganizing or rebuilding it." This is why maintenance scripts filter on `page_count > 1000` — not as a performance heuristic, but because the number below that is noise.

> 🌍 **In the real world**: a nightly `ALTER INDEX ALL ... REBUILD` job on a 400 GB database had run for years and was defended on the grounds that queries were visibly slower on the mornings it failed. That observation was correct; the explanation was not. When the job was replaced with `UPDATE STATISTICS` on the same tables as an experiment, the morning slowdowns stopped just the same — the rebuild's real contribution had always been a full-scan statistics refresh, and the eight hours of I/O and log generation around it were incidental. The job had also been quietly harming the environment in a way nobody had connected to it: it generated enough transaction log to make the geo-replica lag every night, and a failover during that window would have taken far longer than the RTO everyone had signed off. Replacing rebuild-by-schedule with statistics-by-default and rebuild-by-evidence cut the maintenance window to minutes. Before you defend an index maintenance job, be able to say which of the two things it does — defragment, or refresh statistics — is the one your workload is actually benefiting from.

### Measuring Fragmentation

```sql
-- Check fragmentation percentage
SELECT 
    OBJECT_NAME(ips.object_id) AS TableName,
    i.name AS IndexName,
    CAST(ips.avg_fragmentation_in_percent AS DECIMAL(5,2)) AS FragmentationPercent,
    ips.page_count AS PageCount,
    CASE 
        WHEN ips.avg_fragmentation_in_percent < 10 THEN 'OK'
        WHEN ips.avg_fragmentation_in_percent < 30 THEN 'REORGANIZE'
        ELSE 'REBUILD'
    END AS Action
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
INNER JOIN sys.indexes i ON ips.object_id = i.object_id 
    AND ips.index_id = i.index_id
WHERE ips.avg_fragmentation_in_percent > 10
ORDER BY ips.avg_fragmentation_in_percent DESC;

Example Output:
TableName          | IndexName          | Fragmentation | Action
─────────────────────────────────────────────────────────────────
WT_Builder_Def     | IX_TenantId_Work   | 45.23%        | REBUILD
WT_Builder_Def     | IX_Covering        | 28.50%        | REORGANIZE
WT_Builder_Def     | PK_Id              | 8.10%         | OK
```

### Defragmentation Methods

#### REORGANIZE (Online, Lighter)
```sql
-- Light defragmentation
ALTER INDEX IX_TenantId_WorkflowId ON WT_Builder_Workflow_Definition
REORGANIZE;

Characteristics:
├─ ALWAYS online — no long-term object locks, any edition
├─ Lower resource cost than REBUILD
├─ Interruptible: progress made is persisted, so a large
│  index can be reorganized across several windows
├─ Compacts pages to the index's FILL FACTOR, not to 100%
├─ ❗ Does NOT update statistics

Process:
├─ Defragments the LEAF LEVEL only
├─ Reorders leaf pages to match logical order
├─ Requires free space in the same data file
└─ Fails if ALLOW_PAGE_LOCKS is OFF
```

#### REBUILD (Offline, Complete)
```sql
-- Complete defragmentation
ALTER INDEX IX_TenantId_WorkflowId ON WT_Builder_Workflow_Definition
REBUILD WITH (ONLINE = ON);  -- Enterprise edition; Azure SQL always

Characteristics:
├─ Offline by default: holds object-level locks throughout
├─ ONLINE = ON needs Enterprise (or Azure SQL / MI)
├─ Needs disk for TWO copies of the index during the build
├─ Removes fragmentation at ALL levels, not just the leaf
├─ ✅ Updates statistics by scanning every row (= FULLSCAN)
│     ...EXCEPT for partitioned or RESUMABLE rebuilds, which
│     fall back to the default sampling ratio
└─ RESUMABLE = ON (SQL Server 2017+, online only) can be
   paused and resumed across maintenance windows

Process:
├─ Builds a new copy of the index, then swaps it in
├─ During an online build, every write updates BOTH copies
└─ Indexes over 128 extents deallocate in the background
```

> ⚠️ **"Reduces fragmentation to 0%" and the per-100MB timings were unsourced and are removed.** The claim that matters more is the asymmetry Microsoft states directly: **"Statistics aren't updated when an index is reorganized."** That produces the classic own goal — a maintenance script reorganizes an index, then runs `UPDATE STATISTICS` with default sampling over a table whose statistics were previously full-scan quality from an earlier rebuild. The script "did maintenance" and left the optimizer with *worse* information than it started with.

> 🌍 **In the real world**: an index was added to fix a slow endpoint on a 300-million-row PostgreSQL table, at 11am, with a plain `CREATE INDEX`. Checkout began timing out within a minute. Nothing had deadlocked and the index definition was correct — writers were simply queued behind the `SHARE` lock that a non-concurrent build holds for its entire duration, and there was no way out except cancelling the build and starting again that evening with `CONCURRENTLY`. The SQL Server equivalent is `WITH (ONLINE = ON)`, with the sting that it is Enterprise-only, so the statement that works in the DBA's Enterprise test instance silently blocks on a Standard-edition production box. On a busy table, the concurrent form is not an optimisation to remember at review time; it is the only form of the statement anyone should be typing.

### Automated Defragmentation Script

> ⚠️ **The script that was here did not run.** It contained two errors worth recognising because both are common: `ALTER INDEX ... REBUILD` accepts no `WHERE` clause (it is DDL, not DML), and `EXEC sp_executesql N'...' + @var` is a syntax error — `sp_executesql` requires its statement as a single variable or literal, not a concatenation expression. The corrected version below also fixes a third, quieter problem: it uses `SAMPLED` rather than `LIMITED` mode so that `avg_page_space_used_in_percent` is actually returned, since page density is the metric worth acting on.

```sql
-- Maintenance job. Note: prefer Ola Hallengren's IndexOptimize in
-- production; this exists to show the moving parts, not to replace it.
DECLARE @TableName  sysname = N'WT_Builder_Workflow_Definition';
DECLARE @IndexName  sysname;
DECLARE @FragPct    float;
DECLARE @DensityPct float;
DECLARE @sql        nvarchar(max);

-- LIMITED mode does NOT return avg_page_space_used_in_percent.
-- SAMPLED does, at a modest cost. DETAILED reads every page.
SELECT i.name AS IndexName,
       ips.avg_fragmentation_in_percent  AS FragPercent,
       ips.avg_page_space_used_in_percent AS PageDensity
INTO   #FragIndexes
FROM   sys.dm_db_index_physical_stats(
           DB_ID(), OBJECT_ID(@TableName), NULL, NULL, 'SAMPLED') AS ips
JOIN   sys.indexes AS i
       ON ips.object_id = i.object_id
      AND ips.index_id  = i.index_id
WHERE  i.name IS NOT NULL          -- exclude the heap
  AND  ips.index_level = 0         -- leaf level only
  AND  ips.page_count > 1000;      -- below this the numbers are noise

DECLARE curIndexes CURSOR LOCAL FAST_FORWARD FOR
    SELECT IndexName, FragPercent, PageDensity FROM #FragIndexes;

OPEN curIndexes;
FETCH NEXT FROM curIndexes INTO @IndexName, @FragPct, @DensityPct;

WHILE @@FETCH_STATUS = 0
BEGIN
    -- Rebuild only when BOTH signals are bad, and remember the
    -- rebuild's biggest benefit is the full-scan statistics update.
    -- The 30 / 10 / 75 below are CONVENTION, not measurement, and
    -- Microsoft explicitly disowns fixed thresholds (see above).
    -- They are here so the control flow is readable; the numbers
    -- you should ship are the ones your own before/after
    -- measurements justify.
    IF @FragPct > 30 AND @DensityPct < 75
        SET @sql = N'ALTER INDEX ' + QUOTENAME(@IndexName)
                 + N' ON ' + QUOTENAME(@TableName)
                 + N' REBUILD WITH (ONLINE = ON);';   -- Enterprise / Azure SQL
    ELSE IF @FragPct > 10
        SET @sql = N'ALTER INDEX ' + QUOTENAME(@IndexName)
                 + N' ON ' + QUOTENAME(@TableName)
                 + N' REORGANIZE;';
    ELSE
        SET @sql = NULL;

    IF @sql IS NOT NULL
    BEGIN
        PRINT @sql;                 -- log what you are about to do
        EXEC sys.sp_executesql @sql;  -- @sql is a variable, not an expression
    END

    FETCH NEXT FROM curIndexes INTO @IndexName, @FragPct, @DensityPct;
END

CLOSE curIndexes;
DEALLOCATE curIndexes;
DROP TABLE #FragIndexes;
```

`QUOTENAME` is not decoration here: index and table names come from a catalog view, and concatenating them into dynamic SQL without it is how a maintenance script becomes an injection vector — a real risk in any system where users can name objects.

---

## Query Optimizer

### Question 9: What is Query Optimizer?

### The Role of Query Optimizer

The Query Optimizer is the "intelligent brain" of SQL Server that decides **how** to execute your query for optimal performance.

#### User's Perspective

```
User writes:
SELECT * FROM Table WHERE TenantId = 1 AND WorkflowId = 100

User doesn't specify:
├─ Which index to use
├─ What order to process conditions
├─ Whether to parallelize
├─ How much memory to allocate
└─ ...dozens of other decisions

Query Optimizer figures all this out!
```

### Optimizer Decision Process

```
Query: SELECT * FROM Table WHERE TenantId = 1 AND WorkflowId = 100

┌────────────────────────────────────────────────────┐
│ 1. PARSING                                         │
│    ├─ Validate syntax                             │
│    └─ Build query tree                            │
└────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────┐
│ 2. OPTIMIZATION (Critical!)                        │
│    ├─ Identify available indexes:                 │
│    │  ├─ IX_TenantId (covers 30% of table)       │
│    │  ├─ IX_WorkflowId (covers 10% of table)     │
│    │  └─ IX_TenantId_WorkflowId (covers 0.1%)    │
│    │                                              │
│    ├─ Estimate costs:                             │
│    │  ├─ Plan A: Use IX_TenantId_WorkflowId      │
│    │  │  CPU: 2, I/O: 3, Cost: 5                 │
│    │  ├─ Plan B: Use IX_TenantId (then filter)   │
│    │  │  CPU: 10, I/O: 500, Cost: 510            │
│    │  └─ Plan C: Table Scan                      │
│    │     CPU: 100, I/O: 10000, Cost: 10100       │
│    │                                              │
│    └─ Choose Plan A (lowest cost: 5) ✅         │
└────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────┐
│ 3. COMPILATION                                     │
│    └─ Generate compiled query plan                │
└────────────────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────┐
│ 4. EXECUTION                                       │
│    └─ Execute optimized plan                      │
│       [Use IX_TenantId_WorkflowId] → [Return rows]│
└────────────────────────────────────────────────────┘
```

### Execution Plans

#### Viewing Query Execution Plan

```sql
-- Enable actual execution plan
SET STATISTICS IO ON;
SET STATISTICS TIME ON;

-- Your query
SELECT * FROM Table WHERE TenantId = 1 AND WorkflowId = 100;

-- Output:
SQL Server Parse and Compile Time: 
    CPU time = 2 ms, elapsed time = 3 ms.

(100 rows affected)
Table 'WT_Builder_Workflow_Definition'. Scan count 1, 
logical reads 3, physical reads 0, 
read-ahead reads 0.

SQL Server Execution Times:
    CPU time = 0 ms, elapsed time = 1 ms.
```

#### Simple Execution Plan Example

```
Query: SELECT * FROM Table WHERE TenantId = 1 AND WorkflowId = 100

Execution Plan Tree:
┌─────────────────────────────────────┐
│ SELECT (output 100 rows)            │
└─────────────────────────────────────┘
              ↑
┌─────────────────────────────────────┐
│ Index Seek                          │
│ Index: IX_TenantId_WorkflowId       │
│ Seek Predicate: TenantId=1 AND      │
│                 WorkflowId=100      │
│ Cost: 3%                            │
└─────────────────────────────────────┘
              ↑
         [Clustered Index]
    (Table data via index)

Interpretation:
├─ Index Seek: Fast (binary search)
├─ 100 rows returned
└─ Only 3% of query cost
```

#### Complex Execution Plan Example

```
Query: SELECT * FROM Table WHERE TenantId = 1 ORDER BY CreatedAt LIMIT 10

Execution Plan (GOOD):
┌──────────────────────┐
│ Top (return 10 rows) │
└──────────────────────┘
         ↑
┌──────────────────────┐
│ Sort (by CreatedAt)  │
│ Cost: 20%            │
└──────────────────────┘
         ↑
┌──────────────────────────────┐
│ Index Seek                   │
│ Index: IX_TenantId           │
│ Cost: 80%                    │
└──────────────────────────────┘

Execution Plan (WORSE):
┌──────────────────────┐
│ Top (return 10 rows) │
└──────────────────────┘
         ↑
┌──────────────────────┐
│ Sort (by CreatedAt)  │
│ Cost: 10%            │
└──────────────────────┘
         ↑
┌──────────────────────────────┐
│ Table Scan                   │
│ ALL 1 million rows scanned!  │
│ Cost: 90%                    │
│ Memory: 5GB (sorting millions)│
└──────────────────────────────┘

Much worse performance!
```

### When Optimizer Makes Wrong Decisions

#### Problem 1: Outdated Statistics

```sql
-- Table has 10 indexes
-- Statistics not updated in 1 month

Old Statistics:
├─ TenantId=1: ~100,000 rows (outdated!)
└─ WorkflowId=100: ~50 rows

New Reality (after bulk inserts):
├─ TenantId=1: ~50 rows
└─ WorkflowId=100: ~100,000 rows

Query: SELECT * WHERE TenantId = 1 AND WorkflowId = 100

Optimizer thinks:
├─ Use IX_TenantId (based on old stats)
├─ Scans 100,000 rows, filters to few
└─ Time: 500ms ❌

Should use:
├─ Use IX_WorkflowId (newer stats would show this)
├─ Scans 100,000 rows, filters to few
└─ Time: 100ms ✅ (Same plan, but optimizer would find it with fresh stats)

Solution:
UPDATE STATISTICS Table WITH FULLSCAN;
```

#### Problem 2: Too Many Index Choices

```sql
-- Table has 15 indexes
-- Query uses TenantId and WorkflowId

Available Indexes:
├─ IX_1 (TenantId) ← Picked by mistake!
├─ IX_2 (WorkflowId)
├─ IX_3 (TenantId, WorkflowId) ← Should pick this
├─ IX_4 (TenantId, DiagramId)
├─ IX_5 (WorkflowId, DiagramId)
├─ IX_6 (CreatedAt, TenantId)
├─ IX_7 (UpdatedAt, WorkflowId)
└─ ... 8 more indexes ...

Optimizer picks wrong index and performance degrades.

Solution:
DROP unused indexes
Keep only necessary ones
```

#### Problem 3: Parameter Sniffing

```sql
-- Stored procedure with parameter

CREATE PROCEDURE GetData @TenantId INT
AS
SELECT * FROM Table WHERE TenantId = @TenantId;

First Execution: GetData @TenantId = 1
├─ TenantId=1 returns 100 rows (selective!)
├─ Optimizer chooses: Index Seek
└─ Plan cached ✅

Second Execution: GetData @TenantId = 2
├─ TenantId=2 returns 1,000,000 rows (not selective!)
├─ Uses cached plan: Index Seek
├─ Must process 1M rows with seek
└─ Time: 5000ms ❌ (Should use Table Scan)

Solution 1: RECOMPILE
CREATE PROCEDURE GetData @TenantId INT
AS
SELECT * FROM Table WHERE TenantId = @TenantId
OPTION (RECOMPILE);

Solution 2: Use local variable
CREATE PROCEDURE GetData @TenantId INT
AS
DECLARE @LocalTenantId INT = @TenantId;
SELECT * FROM Table WHERE TenantId = @LocalTenantId;
```

> ⚠️ **Solution 2 is presented as a fix; it is really a trade, and knowing which trade is the interesting part.** The optimizer cannot see the runtime value of a local variable, so it stops sniffing and falls back to the **average density** from the statistics object — mathematically identical to `OPTION (OPTIMIZE FOR UNKNOWN)`, just harder to read. That does not give you a good plan; it gives you the *same mediocre plan for every value*. For the tenant with 50 rows and the tenant with a million, you now get one compromise plan that suits neither. It is the right answer only when consistency of latency matters more than best-case latency — a real preference, but state it as a preference.
>
> The full ladder, in the order you should reach for them:
>
> | Approach | What it does | Cost |
> |---|---|---|
> | `OPTION (RECOMPILE)` | Compiles per execution with the actual value, and can also fold the value into a filtered-index match | Compilation CPU on every call; no plan reuse; the plan is not cached for you to inspect later |
> | `OPTIMIZE FOR (@p = <value>)` | Pins the plan to one representative value | Wrong for values unlike that one; needs revisiting as data shifts |
> | `OPTIMIZE FOR UNKNOWN` / local variable | Density-average plan for everyone | Nobody gets the good plan |
> | Split the procedure | Separate procedures (or branches) for the "big tenant" and "small tenant" shapes, each getting its own cached plan | Duplicated code; you must be able to classify at call time |
> | Query Store forced plan | Pin a known-good plan operationally, no code change | Silent rot when the data distribution moves under it |
>
> Note also that SQL Server 2022 added **Parameter Sensitive Plan optimization**, which caches multiple plan variants for a single parameterised statement and dispatches on the parameter's estimated cardinality bucket — worth naming if the interviewer is on a current version, because it changes "what would you do" into "what does the engine now do for you".

### Optimizer Hints (Override Optimizer)

```sql
-- Usually not needed, but sometimes helpful

-- Force a specific index
SELECT * FROM Table WITH (INDEX(IX_TenantId))
WHERE TenantId = 1;

-- Force a SEEK (fails the query outright if no seek is possible)
SELECT * FROM Table WITH (FORCESEEK)
WHERE TenantId = 1;

-- Force a SCAN — this is the one for "the optimizer picked a
-- seek + lookup and underestimated the rows"
SELECT * FROM Table WITH (FORCESCAN)
WHERE TenantId = 1;

-- Compile the plan as if the parameter had this value.
-- Requires actual PARAMETERS — this is a procedure, not ad-hoc SQL.
-- CREATE OR ALTER must be the first statement in its batch, hence GO.
GO
CREATE OR ALTER PROCEDURE GetByTenant @TenantId int
AS
SELECT * FROM Table
WHERE TenantId = @TenantId
OPTION (OPTIMIZE FOR (@TenantId = 1));
GO

Warning: Use hints sparingly!
├─ Hints override automatic optimization
├─ Can cause problems when data changes
└─ Should only use after analysis shows benefit
```

> ⚠️ **Three corrections to the original hint examples, all of which would be caught in an interview.**
>
> 1. **`FORCESEEK` does not force a scan — it forces a *seek*.** The comment "force full table scan" attached to it had the meaning exactly inverted. The hint that forces a scan is **`FORCESCAN`**, added in SQL Server 2008 R2 SP1. `FORCESEEK` is stricter than it looks: if no seek is possible on any index, the query does not fall back to a scan, it **fails to compile**. That is occasionally useful as a guard rail and usually a foot-gun.
> 2. **`OPTIMIZE FOR` does not suggest an index.** It tells the optimizer to compile as though a *parameter* held a given value. The original example applied it to an ad-hoc statement with literals and no parameters at all, which cannot compile. There is also `OPTION (OPTIMIZE FOR UNKNOWN)`, which asks for a plan based on average density rather than any specific value.
> 3. **`NOLOCK` is not a performance hint and does not belong in an example about index choice.** It is `READ UNCOMMITTED` spelled differently. It permits dirty reads, and less famously it permits **missing and duplicated rows** — an allocation-order scan can skip or revisit rows when page splits move them mid-scan, so a `NOLOCK` `COUNT(*)` can be wrong in either direction with no error raised. If the goal is "readers shouldn't block writers", the correct tool on SQL Server is RCSI (`READ_COMMITTED_SNAPSHOT ON`), which gives a statement-consistent view via the version store instead of abandoning consistency altogether.

### Key Takeaway: Trust but Verify

```
✅ The optimizer is usually right
├─ Decades of cost-model research
├─ Considers plans you would not think of
└─ Gets the ordinary case right without help

❌ It goes wrong in a small number of recognisable ways
├─ Estimates built on stale or too-coarse statistics
├─ Predicates it cannot use as seek boundaries (SARGability)
├─ Correlated columns it assumes are independent
├─ Parameter sniffing across skewed distributions
└─ A cost model describing hardware you no longer run on

Best Practice:
├─ The optimizer is not guessing — it is doing arithmetic
├─ on numbers you supplied. Wrong plan usually means
├─ wrong input, so fix the input before overriding
└─ the output with a hint
```

> ⚠️ The "99% / 1%" split was invented. It also frames the problem badly: bad plans are not random misfires, they are a short list of failure modes with names. Learning the names is what lets you diagnose instead of guess — the two most valuable are below.

### SARGability: predicates the engine cannot seek on

The word never appeared on this page and it is the most useful piece of vocabulary in query tuning. A predicate is **SARGable** (Search ARGument-able) if the engine can turn it into a seek boundary — a start and end position in the index. The rule is one sentence: **the indexed column must appear alone on one side of the comparison.** Wrap it in anything and the B-tree, which is sorted on the raw column value, no longer knows where to start.

```sql
-- ❌ NOT SARGable — function applied to the column
WHERE YEAR(CreatedAt) = 2026
WHERE CAST(CreatedAt AS date) = '2026-08-12'
WHERE ISNULL(Status, 'None') = 'Active'
WHERE LEFT(Reference, 3) = 'ABC'
WHERE Amount * 100 > 5000

-- ✅ SARGable rewrites — column left alone, work moved right
WHERE CreatedAt >= '2026-01-01' AND CreatedAt < '2027-01-01'
WHERE CreatedAt >= '2026-08-12' AND CreatedAt < '2026-08-13'
WHERE (Status = 'Active')            -- handle NULL separately
WHERE Reference LIKE 'ABC%'          -- prefix match keeps the seek
WHERE Amount > 50
```

Two notes that separate a real answer from a memorised one:

- **`LIKE 'ABC%'` seeks; `LIKE '%ABC'` cannot.** A B-tree can find everything starting with a prefix because that is a contiguous range. It cannot find everything *containing* a substring, because those entries are scattered. This is not a SQL Server limitation — it is what sorted order means. PostgreSQL's escape hatch is a `pg_trgm` GIN index; SQL Server's is full-text search.
- **The .NET-specific one: implicit conversion.** A `varchar(32)` column compared against a parameter that EF Core sends as `nvarchar` — the default for a `string` property — triggers SQL Server's data type precedence rules, which convert the **column** to `nvarchar` for every row. The seek is gone and the DDL is untouched. The tells are in the plan: `CONVERT_IMPLICIT(nvarchar(32), [reference], 0)` inside the predicate, plus a plan-level warning that the conversion "may affect SeekPlan in query plan choice". The fix is `.IsUnicode(false)` on the property mapping. This is probably the easiest way for a .NET application to defeat an index it correctly created.

### Seek predicate vs residual predicate: the ratio that matters

"Is it using an index?" is the wrong question, and the plan will happily say `Index Seek` while doing an enormous amount of work. What a seek does is establish a **range** to read; anything the index cannot bound is applied afterwards, as a **residual predicate**, to rows already fetched.

```
Query:  WHERE TenantId = 42 AND CreatedAt >= '2026-08-01' AND Status = 'Failed'
Index:  (TenantId, CreatedAt)

  Index Seek  ── Seek Predicate:  TenantId = 42
              │                   AND CreatedAt >= '2026-08-01'
              │      ← this bounds the read
              │
              └── Predicate (residual):  Status = 'Failed'
                     ← applied to every row the seek returned

  Actual Number of Rows :     41
  Number of Rows Read   : 380,000     ← the actual cost
```

`41` is what the user sees. `380,000` is what the server did. The operator is a seek, the index is "being used", and the query is reading four hundred thousand rows to return forty.

**Where to find the two numbers:**

| Engine | Seek boundary | Discarded work |
|---|---|---|
| SQL Server | `Seek Predicates` in the operator properties | `Predicate`, and `Number of Rows Read` next to `Actual Number of Rows` — actual plans only, in the properties pane, not on the face of the plan |
| PostgreSQL | `Index Cond` | `Filter` and `Rows Removed by Filter` in `EXPLAIN ANALYZE` |
| MySQL | `key_len` in `EXPLAIN` shows how much of the key bounded the seek | `rows_examined` vs `rows_sent`; `EXPLAIN ANALYZE` from 8.0.18 |

The fix is almost never a hint. It is moving the residual column into the index key so that it bounds the scan instead of trimming its output — which, per Rule 1 in [the column-order section](#best-practice-selectivity-order), usually means putting the equality column *before* the range column.

> 🌍 **In the real world**: a slow query was escalated with a screenshot of its plan attached and the note "it's using the index, so it isn't the index". Two things were wrong with the artefact used to close the investigation. It was an *estimated* plan, so it contained no Rows Read at all — estimated plans are free and silent about the one number that mattered. And it had been captured against a developer database holding a small fraction of production's rows, where the estimate of forty rows happened to be correct. In production the same operator read close to a million. The query survived two reviews and a "we already checked the index" reply before anyone opened the properties pane on an actual plan from the live system. Everyone who tunes SQL for a living converges on reading one ratio before anything else: rows read per row returned. If it is near 1, the index fits the query. If it is in the thousands, the index is bounding the wrong thing, whatever the operator is called.

### Statistics: the histogram the optimizer is actually reading

"Update your statistics" is advice everyone repeats and few can justify. Knowing the structure lets you explain *which* estimates go wrong and *why*.

A SQL Server statistics object has two parts:

- **A histogram**, built on **the first key column only** — never on the others. It aggregates values into "a maximum of 200 contiguous histogram steps" (Microsoft Learn, *Statistics*), each holding a range, its upper bound, the row count equal to that bound, and the count and distinct count within the range.
- **A density vector**, holding `1 / (number of distinct values)` for each *prefix* of the key columns. For key columns `(CustomerId, ItemId, Price)`, densities are stored for `(CustomerId)`, `(CustomerId, ItemId)` and all three. Density is how the optimizer estimates when it cannot use the histogram — which is exactly the local-variable and `OPTIMIZE FOR UNKNOWN` case above.

Two consequences fall straight out of the structure:

**200 steps for any number of distinct values.** On a column with millions of distinct values, each step covers a huge range and estimates within it are interpolated averages. Skew inside a step is invisible. This is why a heavily skewed column can produce good estimates for the values that earned their own boundary and bad ones for everything else.

**Only the leading column gets a histogram**, so `WHERE Country = 'PK' AND City = 'Karachi'` has to be estimated by combining two separate single-column selectivities — and those columns are not independent. The legacy cardinality estimator simply multiplied them, as if they were; the estimator introduced in SQL Server 2014 (compatibility level 120 and above, the default since) uses **exponential backoff** instead — it sorts the selectivities and applies progressively weaker exponents to the less selective ones, which softens the underestimate without fixing the underlying blindness to correlation. Either way the estimate comes out too low, the optimizer picks a plan for far too few rows, and you get the tipping-point failure described earlier. The named fix on PostgreSQL is extended statistics (`CREATE STATISTICS ... ON country, city FROM customers`); on SQL Server it is a multi-column statistics object or a filtered statistic.

**When does auto-update fire?** With `AUTO_UPDATE_STATISTICS` on, from SQL Server 2016 at database compatibility level 130 or above, the threshold for a table of *n* rows where *n* > 500 is `MIN(500 + (0.20 * n), SQRT(1000 * n))` modifications (Microsoft Learn, *Statistics*). Microsoft's own worked example: a 2,000,000-row table takes the minimum of `500 + 0.20 × 2,000,000 = 400,500` and `SQRT(1000 × 2,000,000) = 44,721`, so statistics refresh every 44,721 modifications. Below compatibility level 130 the old rule applies — `500 + (0.20 * n)`, i.e. 400,500 for that same table, roughly nine times less often — and trace flag 2371 is the pre-2016 way to opt into the dynamic threshold.

> 🌍 **In the real world**: a nightly import loaded the day's rows into a 200-million-row table, and the first report to run afterwards took twenty minutes instead of one. Nothing had been deployed and no index had changed. The import had inserted rows carrying today's date; statistics still described yesterday's maximum; and the report's `WHERE created_at >= @today` therefore sat *past the end of the histogram*, where the optimizer estimates a handful of rows. It picked a nested-loop plan built for a handful of rows and ran it against millions. The auto-update threshold scales with table size, so a big table is slow to notice its own change: by the formula above, a 200-million-row table needs `SQRT(1000 × 200,000,000)` ≈ **447,000** modifications before statistics refresh themselves — and under the pre-2016 rule it would have been `500 + 0.20 × 200,000,000` = **40 million**, which is to say never, in practice, for a daily import. Either way the import was too small to trip it and too significant to ignore. Moving `UPDATE STATISTICS` to the end of the import job, rather than leaving it to a maintenance window with its own unrelated schedule, made it stop happening. The general rule this teaches: statistics maintenance belongs to whatever changes the data, not to the calendar. The specific pattern has a name worth knowing — the **ascending key problem** — and it is the reason `created_at` and `IDENTITY` columns are over-represented in "it was fine yesterday" incidents.

---

## Best Practices

### Comprehensive Index Strategy

#### 1. Index Selection
```sql
-- ✅ DO: Index frequently queried columns
SELECT * FROM Table WHERE TenantId = 1  -- High frequency
CREATE INDEX IX_TenantId ON Table (TenantId);

-- ✅ DO: Create composite indexes for common WHERE combinations
SELECT * FROM Table WHERE TenantId = 1 AND WorkflowId = 100
CREATE INDEX IX_TenantId_WorkflowId ON Table (TenantId, WorkflowId);

-- ❌ DON'T: Index every column
CREATE INDEX IX_CreatedBy ON Table (CreatedBy);  -- If never queried
CREATE INDEX IX_UpdatedAt ON Table (UpdatedAt);   -- If never queried

-- ❌ DON'T: Index low-cardinality columns
-- (column with only 2 distinct values)
CREATE INDEX IX_IsActive ON Table (IsActive);  -- Only 0 and 1
```

#### 2. Column Ordering
```sql
-- ✅ DO: Match common WHERE clause order
-- Query: WHERE TenantId = X AND WorkflowId = Y
CREATE INDEX IX_Good ON Table (TenantId, WorkflowId);

-- ⚠️ Selectivity is a TIEBREAK ONLY — among the equality columns, after
--    equality-before-range and after choosing the leading column that the
--    most queries filter on (Rules 1-4 in Composite Index Column Order).
--    "Most selective column first" as a general rule is folklore. On a
--    multi-tenant table TenantId still leads, even though DiagramId is
--    the more selective column.
CREATE INDEX IX_Selective ON Table (TenantId, DiagramId);

-- ❌ DON'T: Random column order
CREATE INDEX IX_Bad ON Table (WorkflowId, TenantId);  -- Opposite of WHERE clause
```

#### 3. Covering Indexes
```sql
-- ✅ DO: Use INCLUDE for columns accessed but not filtered
-- Query: SELECT TenantId, WorkflowId, DiagramId WHERE TenantId = X
CREATE INDEX IX_Cover ON Table (TenantId, WorkflowId)
INCLUDE (DiagramId);

-- ❌ DON'T: Include too many columns
CREATE INDEX IX_TooMuch ON Table (TenantId)
INCLUDE (Col1, Col2, Col3, Col4, Col5, Col6, Col7, Col8, Col9, Col10);
-- Results in bloated index

-- ❌ DON'T: Include key column in INCLUDE
CREATE INDEX IX_Bad ON Table (TenantId)
INCLUDE (WorkflowId);  -- WorkflowId should be in keys, not INCLUDE!
```

#### 4. Index Naming Convention
```sql
-- Consistent naming helps organization

-- Non-clustered index
CREATE INDEX IX_TenantId ON Table (TenantId);

-- Composite index
CREATE INDEX IX_TenantId_WorkflowId ON Table (TenantId, WorkflowId);

-- Covering index
CREATE INDEX IX_TenantId_WorkflowId_Cover ON Table (TenantId, WorkflowId)
INCLUDE (DiagramId, BuilderObject);

-- Filtered index (optional)
CREATE INDEX IX_Active_TenantId ON Table (TenantId)
WHERE IsActive = 1;

Format: IX_[Columns]_[Purpose]
```

#### 5. Regular Maintenance
```sql
-- Weekly statistics update
UPDATE STATISTICS WT_Builder_Workflow_Definition;

-- Monthly defragmentation
EXEC sp_MSForEachTable 
    'ALTER INDEX ALL ON ? REORGANIZE WITH (LOB_COMPACTION = ON)';

ALTER INDEX ALL ON WT_Builder_Workflow_Definition REBUILD;

-- Quarterly review
-- Check unused indexes, overlapping indexes, etc.
```

---

## Monitoring and Maintenance

### Key DMVs (Dynamic Management Views)

```sql
-- 1. Find unused indexes  (corrected — see the note below this block)
--    The OUTER JOIN's NULLs must be handled, or the indexes that were
--    NEVER used (no DMV row at all) are the ones you filter out.
SELECT  TableName  = OBJECT_SCHEMA_NAME(i.object_id) + '.'
                   + OBJECT_NAME(i.object_id),
        IndexName  = i.name,
        Reads      = ISNULL(s.user_seeks, 0) + ISNULL(s.user_scans, 0)
                   + ISNULL(s.user_lookups, 0),
        Writes     = ISNULL(s.user_updates, 0)
FROM    sys.indexes AS i
LEFT JOIN sys.dm_db_index_usage_stats AS s
       ON  s.object_id   = i.object_id
       AND s.index_id    = i.index_id
       AND s.database_id = DB_ID()     -- the DMV spans the whole INSTANCE
WHERE   i.type_desc = 'NONCLUSTERED'
  AND   i.is_primary_key = 0
  AND   i.is_unique_constraint = 0     -- these enforce constraints; keep them
  AND   OBJECTPROPERTY(i.object_id, 'IsUserTable') = 1
  AND   ISNULL(s.user_seeks, 0) + ISNULL(s.user_scans, 0)
      + ISNULL(s.user_lookups, 0) = 0
ORDER BY Writes DESC;

-- Always check how long the counters have been accumulating first:
SELECT UpSince = sqlserver_start_time FROM sys.dm_os_sys_info;

-- 2. Find REDUNDANT indexes  (rewritten — this is the useful question)
--    An index is redundant when its key list is a strict PREFIX of another's:
--    (a) is covered by (a, b);  (a, b) is covered by (a, b, c).
--    STRING_AGG requires SQL Server 2017+.
WITH IndexCols AS (
    SELECT  ic.object_id,
            ic.index_id,
            KeyCols  = STRING_AGG(CASE WHEN ic.is_included_column = 0
                                       THEN c.name END, ',')
                       WITHIN GROUP (ORDER BY ic.key_ordinal),
            InclCols = STRING_AGG(CASE WHEN ic.is_included_column = 1
                                       THEN c.name END, ',')
                       WITHIN GROUP (ORDER BY c.name)
    FROM    sys.index_columns AS ic
    JOIN    sys.columns AS c
         ON c.object_id = ic.object_id AND c.column_id = ic.column_id
    GROUP BY ic.object_id, ic.index_id
)
SELECT  TableName     = OBJECT_SCHEMA_NAME(a.object_id) + '.'
                      + OBJECT_NAME(a.object_id),
        Redundant     = ia.name,
        RedundantKeys = a.KeyCols,
        CoveredBy     = ib.name,
        CoveringKeys  = b.KeyCols,
        LostIncludes  = a.InclCols     -- check this before dropping anything
FROM    IndexCols AS a
JOIN    IndexCols AS b
     ON b.object_id = a.object_id
    AND b.index_id <> a.index_id
JOIN    sys.indexes AS ia
     ON ia.object_id = a.object_id AND ia.index_id = a.index_id
JOIN    sys.indexes AS ib
     ON ib.object_id = b.object_id AND ib.index_id = b.index_id
WHERE   ia.type_desc = 'NONCLUSTERED'
  AND   ib.type_desc = 'NONCLUSTERED'
  AND   ia.is_unique = 0               -- never drop a uniqueness guarantee
  AND   ia.is_primary_key = 0
  AND   ia.is_unique_constraint = 0
        -- Prefix OR exact match. Appending the comma to BOTH sides is
        -- what makes an identical key list match as well as a strict
        -- prefix -- without it, exact duplicates (the worst case) slip
        -- through, and they come back as a reciprocal pair of rows.
        -- Compared with LEFT() rather than LIKE on purpose: an object
        -- name containing _ or [ would act as a wildcard in a LIKE
        -- pattern and produce false matches.
  AND   LEFT(b.KeyCols + ',', LEN(a.KeyCols) + 1) = a.KeyCols + ',';

-- 3. Missing index suggestions  (corrected DMV name: GROUP, singular)
SELECT  TOP (20)
        Impact = CONVERT(decimal(18,2),
                    migs.user_seeks * migs.avg_total_user_cost
                  * (migs.avg_user_impact * 0.01)),
        TableName = mid.statement,
        mid.equality_columns,
        mid.inequality_columns,
        mid.included_columns,
        migs.user_seeks, migs.last_user_seek
FROM    sys.dm_db_missing_index_details AS mid
JOIN    sys.dm_db_missing_index_groups AS mig
     ON mig.index_handle = mid.index_handle
JOIN    sys.dm_db_missing_index_group_stats AS migs
     ON migs.group_handle = mig.index_group_handle
WHERE   mid.database_id = DB_ID()
ORDER BY Impact DESC;

-- 4. Check index fragmentation
SELECT 
    OBJECT_NAME(ips.object_id) AS TableName,
    i.name AS IndexName,
    ips.avg_fragmentation_in_percent,
    CASE 
        WHEN ips.avg_fragmentation_in_percent < 10 THEN 'OK'
        WHEN ips.avg_fragmentation_in_percent < 30 THEN 'REORGANIZE'
        ELSE 'REBUILD'
    END AS Action
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ips
INNER JOIN sys.indexes i 
    ON ips.object_id = i.object_id AND ips.index_id = i.index_id
WHERE ips.avg_fragmentation_in_percent > 10;
```

> ⚠️ **All four queries above were defective as originally written. Each fault is a common one, so they are named rather than quietly patched.**
>
> - **Query 1 could not return its own answer.** It `LEFT JOIN`ed `sys.dm_db_index_usage_stats` and then filtered on `s.user_seeks + ... = 0`. An index that has *never been touched* has **no row** in that DMV, so the join yields NULLs, `NULL = 0` evaluates to unknown, and the row is discarded by the `WHERE`. The query returned everything except the indexes it was written to find. It also omitted `database_id` from the join — the DMV covers the whole instance, so `object_id` values from other databases can match.
> - **Query 2 did not detect duplicates.** Joining `sys.indexes` to itself on `object_id` and `type_desc` returns every *pair* of same-type indexes on a table. It never inspected a column. Duplication is a property of the key column list, so the key column list has to be in the query. The rewrite catches both shapes that matter — an exact duplicate key list, and a key list that is a strict prefix of another — which is why the comparison appends the delimiter to *both* sides.
> - **Query 3 named a DMV that does not exist.** It is `sys.dm_db_missing_index_group_stats` — **group**, singular. The plural form fails with an invalid object name. The join column is `index_group_handle` → `group_handle`, not `index_group_id`.
> - **Query 4 asks `LIMITED` mode for a metric it does not return.** `LIMITED` gives fragmentation but leaves `avg_page_space_used_in_percent` NULL, and page density is the number worth acting on ([see above](#fragmentation-levels-and-impact)). Use `'SAMPLED'`. Its `CASE` also encodes the 10/30 thresholds Microsoft has explicitly disowned, and it doesn't filter `page_count`, so it will report alarming fragmentation on eight-page indexes where the figure is meaningless.

**The missing-index DMVs are a hint generator, not a design tool, and creating what they emit is a well-known way to make a database worse.** Microsoft publishes the constraints; these are the ones that bite, quoted from *Limitations of the Missing Indexes Feature*:

- *"It is not intended to fine tune an indexing configuration."*
- *"It does not specify an order for columns to be used in an index."* — the `equality_columns` come out in the DMV's own order (in practice, column-id order), not an order chosen for selectivity or `ORDER BY` support; Microsoft's own worked example is a query whose ideal index is `(column_b, column_a)` and whose suggestion lists `column_a` first. Reordering them is your job, and Rules 1-3 of [the column-order section](#best-practice-selectivity-order) are how you do it. Microsoft's guidance for that reordering is "list equality columns first and then inequality columns... order them based on their selectivity, listing the most selective columns first" (Microsoft Learn, `sys.dm_db_missing_index_group_stats`, Example B). Note that this is consistent with Rule 4 rather than with the folklore version: *equality before inequality* is the load-bearing half, and selectivity is the tiebreak **among the equality columns**, once the range column is already last.
- *"It cannot gather statistics for more than 500 missing index groups."* Separately, the group-stats DMV's own documentation notes the result set "is limited to 600 rows." Two different documented limits — the tracking cap and the return cap — so quote whichever you mean.
- *"For queries involving only inequality predicates, it returns less accurate cost information."*
- *"It reports only include columns for some queries, so index key columns must be manually selected."*
- *"It does not suggest filtered indexes."*
- *"It does not consider trivial query plans."*

Add the one Microsoft does not list, which is the most damaging in practice: **the suggestions do not consider the indexes that already exist.** The feature will happily propose `(TenantId, Status) INCLUDE (Total)` on a table that already carries `(TenantId, Status, CreatedAt) INCLUDE (Total, CustomerId)`. Create both and you maintain two structures on every write to serve one query. The `avg_user_impact` figure is only the "average percentage benefit that user queries could experience if this missing index group was implemented" (Microsoft Learn, `sys.dm_db_missing_index_group_stats`) — a read-side estimate for the queries that wanted the index, and it says nothing at all about the write cost you are adding to every insert, update and delete on the table.

> 🌍 **In the real world**: a performance sprint opened by sorting the missing-index DMV by impact and creating the top twenty suggestions verbatim, in one migration, on a Friday. Read latency did improve on the queries that had generated them — the DMV was not lying. Insert throughput on the busiest table collapsed the same afternoon, because six of the twenty were near-duplicates of one another and of indexes already present, several `INCLUDE`-ing the same wide columns, each one a full extra structure to maintain per row. The rollback was politically awkward in a way that is worth anticipating: dropping indexes the DMV was still actively recommending looked like undoing the fix, and it took a week of measurement to establish which four of the twenty were doing the work. The discipline that would have prevented it fits in three lines. Before creating any suggestion: check whether an existing index already leads with the same columns and could simply be widened; reorder the equality columns yourself; and look up how many writes per second the table takes, because the DMV never will.

---

## Real-World Scenarios

### Scenario 1: E-Commerce Platform

```sql
-- Table: Orders
CREATE TABLE Orders (
    OrderId BIGINT PRIMARY KEY,
    TenantId BIGINT,
    CustomerId BIGINT,
    OrderDate DATETIME,
    Amount DECIMAL,
    Status VARCHAR(20)
);

Common Queries:
1. Find order by CustomerId (customer's orders page)
2. Find orders by TenantId and Status (admin dashboard)
3. Find orders in date range (reporting)
4. Recent orders for customer

Optimal Indexes:
CREATE INDEX IX_CustomerId ON Orders (CustomerId);
CREATE INDEX IX_TenantId_Status ON Orders (TenantId, Status);
CREATE INDEX IX_OrderDate ON Orders (OrderDate DESC);
CREATE INDEX IX_TenantId_OrderDate_Cover ON Orders (TenantId, OrderDate DESC)
INCLUDE (Amount, Status, CustomerId);
```

> ⚠️ **One defect in that DDL, and one thing to watch.**
>
> The defect: `Amount DECIMAL` has no precision or scale, and SQL Server's default is `DECIMAL(18, 0)` — **zero decimal places**. Every amount is silently rounded to whole currency units on insert. This is not an indexing bug, but it is in a money column in an orders table on a page about production systems, and it is exactly the class of thing that survives review because it reads as though it says something. Write `DECIMAL(19, 4)` or whatever your domain needs, always explicitly.
>
> The thing to watch: none of those four indexes is currently redundant — no key list is a prefix of another. But `IX_TenantId_Status` becomes redundant the moment someone adds `(TenantId, Status, OrderDate)` to let the admin dashboard sort, because `(TenantId, Status)` is a strict prefix of it. That is exactly the shape query 2 in the previous section is written to catch, and the point of running it periodically rather than once.

> 🌍 **In the real world**: a month-end finance report was why checkout failed on the first of the month, twice, on SQL Server. The report scanned the orders table under the on-premises default — locking read committed — with a non-SARGable date predicate (`WHERE YEAR(OrderDate) = @yr AND MONTH(OrderDate) = @mo`). It therefore took shared locks on every row it *read*, not every row it returned, crossed the escalation threshold at around 5,000 locks on one table in one statement, and held a table lock for the length of the aggregation. The database was never "down" and no error was logged on the reporting side; it was doing precisely what read committed asks of it. Three fixes were proposed and eventually all three were applied, and the order mattered more than the list: first a covering index plus a SARGable rewrite so the report read the rows it needed instead of the table, then RCSI so readers stopped taking shared locks at all, then a read replica so the report stopped competing with checkout for anything. Enabling RCSI first — the tempting one, because it is a single `ALTER DATABASE` — would have moved the cost into the `tempdb` version store while the query still read a table's worth of rows to return a page of totals. Note the engine dependency in all of this: PostgreSQL's MVCC means readers never block writers to begin with, so this incident cannot happen there, and new Azure SQL Database databases have RCSI on by default, so the same code will not reproduce it on Azure.

### Scenario 2: Workflow Management System

```sql
-- Our Table: WT_Builder_Workflow_Definition
CREATE TABLE WT_Builder_Workflow_Definition (
    Id BIGINT PRIMARY KEY,
    TenantId BIGINT,
    WorkflowId BIGINT,
    DiagramId BIGINT,
    BuilderObject NVARCHAR(MAX),
    CreatedAt DATETIME,
    UpdatedAt DATETIME
);

Common Queries:
1. Get workflow by TenantId + WorkflowId
2. Get diagram definitions by TenantId + DiagramId
3. List all workflows for tenant
4. Find workflows created in date range

Recommended Indexes (from migration script):
✅ IX_TenantId
✅ IX_TenantId_WorkflowId
✅ IX_TenantId_DiagramId
✅ IX_WorkflowId_DiagramId
✅ IX_TenantId_WorkflowId_Covering (includes common SELECT columns)
```

### Scenario 3: High-Volume Log Table

```sql
-- Table: ActivityLogs (10 million rows/day)
CREATE TABLE ActivityLogs (
    LogId BIGINT PRIMARY KEY,
    TenantId BIGINT,
    UserId BIGINT,
    Action VARCHAR(50),
    Timestamp DATETIME,
    Details NVARCHAR(MAX)
);

Challenge: High INSERT volume + Need fast queries

Index Strategy:
-- Minimal indexes for INSERT performance
CREATE INDEX IX_TenantId_Timestamp ON ActivityLogs (TenantId, Timestamp DESC);
-- One index for queries, covering common columns
CREATE INDEX IX_TenantId_UserId_Cover ON ActivityLogs (TenantId, UserId)
INCLUDE (Action, Timestamp);

-- Avoid:
-- Multiple indexes (slows INSERT)
-- Covering index with Details (too large)
-- Indexes on rarely queried columns
```

> 🌍 **In the real world**: an `ActivityLogs` table taking roughly ten million rows a day was indexed exactly as above and performed well for a quarter. Then support asked for "search logs by user across all time", and an index went on `(UserId, Timestamp DESC)`. Insert throughput dropped immediately and visibly, because `UserId` is effectively random across concurrent requests — every insert now had to find a *different* leaf page in the new index and split it, on a table whose whole design premise was append-only sequential writes. The team had correctly reasoned about the number of indexes and not at all about their *shape*. What shipped instead was partitioning by month, dropping the `UserId` index, and pointing the support query at a nightly-refreshed copy in the reporting database, where a random-ordered index costs nothing because nothing writes to it in real time. The general shape of the lesson: on a high-write table, the cost of an index is not "one more structure", it is "one more structure **written in this access pattern**". A second sequential index is nearly free. A random-ordered one on the same table is not, and the index count is identical either way.

> ⚠️ **`Details NVARCHAR(MAX)` on a table taking ten million rows a day deserves a second look regardless of indexing.** LOB values over ~8,000 bytes move off-row into a separate allocation unit, so every read of a row that needs `Details` costs an extra I/O; values under it stay in-row and consume the 8 KB page budget that determines how many rows fit per page, and therefore how many pages every scan of the table has to read. Neither is wrong, but on a table this size it is a decision, not a default.

---

## Interview Cross-Questioning Drill

<details>
<summary>📖 Click to expand — cross-question chains (~15-20 min, cover answers and write cold)</summary>

> ⚠️ **Honest caveat**: reading this once doesn't make you interview-ready. Cover the answers, write them cold, then check. Pair with a senior for live mock cross-questioning. The guide removes "I never thought about that" surprises; mock interviews convert knowledge into reflex. Both are needed.

Each drill is **Q → A → Cross-Q → A → Cross-Q² → A**.

### Drill 1 — B+ tree page splits and fillfactor

> **Q**: What happens when you insert into a full B+ tree leaf page?
>
> **A**: Page split. The engine allocates a new page, moves half the existing keys plus the new key to it, and updates the parent node to point at both pages. If the parent is full too, the split cascades upward; at worst, the root splits and the tree grows a level. Cost: extra I/O during the split, fragmentation (the two new pages are at ~50% fill), and write amplification.
>
> **Cross-Q**: How does `FILLFACTOR` prevent splits?
>
> **A**: `FILLFACTOR = 80` tells the engine to leave 20% of each page empty when creating or rebuilding the index. New inserts fit into the slack without splitting until the page reaches capacity. Trade-off: 25% larger index from the start (you reserved space), more I/O per scan, but far fewer splits during writes. Microsoft's guidance is narrower than the folklore: it "doesn't recommend setting fill factor to values other than 100 or 0, except in certain cases for indexes experiencing a high number of page splits" — its own example being a frequently modified index whose leading column holds nonsequential GUIDs (Microsoft Learn, *Maintain indexes optimally*).
>
> **Cross-Q²**: When does FILLFACTOR backfire?
>
> **A**: When inserts are monotonically increasing (e.g., IDENTITY column, sequential GUID, timestamp). New rows always land at the rightmost page; there's no need for slack in older pages. FILLFACTOR < 100 just wastes space and adds I/O without preventing any splits. For append-only patterns, use `FILLFACTOR = 100`. Random-insert patterns (GUID PK, hash-distributed keys) are the one case Microsoft documents as an exception — and even there, set the value from that index's measured page-split rate rather than from a rule of thumb.

### Drill 2 — Hash indexes vs B-tree

> **Q**: When would you reach for a hash index instead of a B-tree?
>
> **A**: Pure equality lookups with no range queries, where the hash's O(1) average beats the B-tree's O(log N). PostgreSQL hash indexes (since v10 WAL-logged), Hekaton hash indexes in SQL Server in-memory tables. Hash indexes can't help with ranges (`>`, `<`, `BETWEEN`) or ordered scans (`ORDER BY`) — those need a B-tree.
>
> **Cross-Q**: Why do hash indexes have a bad reputation despite better complexity?
>
> **A**: Constants matter. B-tree depth is ~4-5 for billion-row tables — that's 4-5 cache-friendly node reads. Hash index lookup is one hash computation + one bucket read, but the bucket is often a less cache-friendly memory access, and hash collisions add chain traversal. On modern hardware, B-tree's predictable access pattern often beats hash. Hash also doesn't support partial matches, prefix searches, or any operator other than `=`.
>
> **Cross-Q²**: What's the killer use case for hash indexes today?
>
> **A**: In-memory OLTP. SQL Server Hekaton tables: lock-free hash indexes give microsecond-level lookups for trading platforms, ticket auctions, hot caches. PostgreSQL hash indexes mostly outperform B-tree on extremely uniform hash distributions with huge tables (billions of rows, equality-only). For disk-backed B-trees vs disk-backed hash, B-tree usually wins because the cache locality advantage is bigger than the algorithmic difference. For in-memory hash, the algorithmic advantage dominates.

### Drill 3 — GIN / GiST / BRIN

> **Q**: Explain GIN, GiST, and BRIN — three Postgres-specific index types.
>
> **A**: **GIN (Generalized Inverted Index)** — inverted index, like a search engine: each value points to all rows containing it. Used for JSONB containment (`@>`), array operators, full-text `tsvector`. Big indexes, slow writes, fast reads on multi-value columns. **GiST (Generalized Search Tree)** — balanced tree with custom inner-node predicates; supports range types, geometric types, full-text. PostGIS uses GiST. **BRIN (Block Range Index)** — stores min/max per block range (default 128 pages); tiny index, very fast to build, useful when data is physically clustered on the indexed column.
>
> **Cross-Q**: What's the killer use case for BRIN?
>
> **A**: Time-series tables where rows are appended in `created_at` order. A B-tree on `created_at` for a 1TB table is huge; a BRIN on `created_at` is tiny (~few MB) and can quickly identify which block ranges might contain rows in a date range. The query reads only matching blocks. Doesn't work if data isn't physically clustered — random insertion order means each block range covers the full date range, and BRIN can't prune anything.
>
> **Cross-Q²**: When does GIN's write cost become unbearable?
>
> **A**: Very high write rates on multi-value columns. Each insert/update touches every key in the indexed value (every word in a tsvector, every key in a JSONB). GIN updates are batched via the "pending list" (controlled by `fastupdate` and `gin_pending_list_limit`), but the pending list must eventually flush. For write-heavy log tables with JSONB metadata, GIN can become the bottleneck. Mitigation: drop the GIN index during bulk loads, rebuild after.

### Drill 4 — Columnstore: compression + segment elimination

> **Q**: How does a columnstore index achieve up to 10× data compression?
>
> **A**: Columnstore stores values column-by-column instead of row-by-row. Each column's values are similar (same type, often similar distribution) → highly compressible. Techniques: dictionary encoding (replace strings with short integer codes), run-length encoding (compress repeating values), bit-packing (use only enough bits per value). A column of "Status" with five distinct values across a billion rows is almost entirely dictionary plus run-length codes, which is where the ratio comes from. Quote Microsoft's published figure — "up to 10 times the data compression over the uncompressed data size" — and not the 100x or 90% numbers that circulate unsourced (see the columnstore section above).
>
> **Cross-Q**: What's segment elimination?
>
> **A**: Columnstore segments group ~1M rows. Each segment stores min/max per column. A query `WHERE created_at > '2025-01-01'` checks each segment's min/max — segments entirely before 2025-01-01 are skipped without reading their data. Combined with high compression, a 10TB columnstore table can answer aggregate queries by reading 1-2 GB of data. For analytical queries, columnstore is the right answer.
>
> **Cross-Q²**: When is columnstore the wrong choice?
>
> **A**: OLTP point lookups. Reading a single row by PK requires decompressing the segment containing that row — expensive vs a B-tree's direct row fetch. Updates also struggle: columnstore segments are largely immutable; updates go to a delta store that's periodically merged in. High-frequency updates create a large delta store and degrade scan performance. Rule: columnstore for OLAP (analytics, dashboards), B-tree for OLTP (transactional reads/writes). SQL Server's HTAP via "real-time operational analytics" combines both, but most workloads should pick one.

### Drill 5 — Bitmap indexes

> **Q**: What's a bitmap index and where is it useful?
>
> **A**: An index where each distinct value maps to a bitmap — one bit per row, set if that row has the value. Best for low-cardinality columns. `WHERE gender = 'F' AND status = 'Active'` → AND two bitmaps together → done. Lightning fast for combining multiple low-cardinality predicates. Oracle has them; PostgreSQL has *bitmap index scans* (different — a runtime hybrid using B-tree results).
>
> **Cross-Q**: Why aren't bitmap indexes used for OLTP?
>
> **A**: Update cost. Modifying a row's value requires updating two bitmaps (clear old, set new) for every indexed column. With concurrent writers, locking entire bitmaps causes massive contention. Bitmap indexes are designed for OLAP / data warehouses with bulk loads and read-heavy workloads. Most modern data warehouses (Snowflake, BigQuery, Redshift) use columnstore + zone maps instead — same idea, different implementation.
>
> **Cross-Q²**: What's a "bitmap index scan" in PostgreSQL?
>
> **A**: Different concept. The planner uses a B-tree (or other) index to produce a list of matching tuple IDs, then builds an in-memory bitmap of pages to visit. Sorts the bitmap into physical order, scans those pages sequentially. Combines well with multiple indexes (BitmapAnd / BitmapOr operators) — the planner can use indexes on `gender` and `status` separately, AND their bitmaps, then fetch only matching rows. Not a persistent bitmap index, but achieves similar AND/OR semantics at query time.

### Drill 6 — Index union vs intersection

> **Q**: I have indexes on `(a)` and `(b)`. My query is `WHERE a = 1 AND b = 2`. Does SQL Server use both?
>
> **A**: Sometimes — via *index intersection*. The optimizer can seek index A for rows matching `a=1`, seek index B for rows matching `b=2`, and intersect the two result sets. Often cheaper than scanning one index and filtering. The plan operator is "Hash Match (Inner Join)" between two Index Seeks.
>
> **Cross-Q**: When does intersection lose to a single composite index?
>
> **A**: When the composite `(a, b)` exists. A composite index seeks to `(1, 2)` directly — one seek, one read. Intersection does two seeks plus a join — two reads minimum, plus join cost. The composite wins for known query shapes. Intersection is the fallback when you have many one-column indexes and the composite for this specific shape doesn't exist.
>
> **Cross-Q²**: Why prefer intersection over creating every possible composite?
>
> **A**: Composite indexes are specialized. Three single-column indexes serve 7 query shapes (each individual column + all subsets). Three two-column composites + originals would cover all six pairs but at much higher write cost and storage. For workloads with diverse query shapes (many ad-hoc queries), individual column indexes + intersection give better coverage per byte. For workloads with a small set of hot queries, targeted composites win. Profile to choose.

### Drill 7 — Locking on index pages

> **Q**: Does SQL Server lock index pages or only table rows?
>
> **A**: Both. Index pages are locked at multiple granularities (key locks, page locks, range locks for serializable). Reads take S locks (or use row versions under RCSI). Writes take X locks. Range queries under SERIALIZABLE take range locks covering the predicate range to prevent phantoms — these can block insertions of new matching rows by other transactions.
>
> **Cross-Q**: What's a "key lock" vs a "page lock"?
>
> **A**: Key locks (`KEY`) lock a specific index key entry. Page locks (`PAGE`) lock the entire 8KB page. The engine prefers row/key locks for concurrency; it may *choose* page granularity up front for a statement it expects to read most of an object, but under memory pressure or past the fine-grained-lock threshold it **escalates to a table lock, never to a page lock** (Microsoft Learn, KB 323630). Page locks are coarser but cheaper to track. Application impact: a page lock can block updates to *other* rows on the same page even when they're unrelated.
>
> **Cross-Q²**: How does latch contention differ from lock contention?
>
> **A**: Latches are short-lived, in-memory synchronization primitives protecting buffer pool pages. Held for microseconds during a memory operation. Locks are logical, transaction-scoped, held for milliseconds-to-seconds. Latch contention shows as `PAGELATCH_*` waits and indicates "many threads hitting the same hot page" — common with monotonically increasing PKs (last page hotspot). Lock contention shows as `LCK_M_*` waits. Fix latch contention with hash-partitioned indexes or by changing insert patterns; fix lock contention with shorter transactions, RCSI, or lower isolation.

### Drill 8 — Latch contention on hot pages

> **Q**: What's the "last-page insertion contention" problem?
>
> **A**: With a monotonically increasing PK (IDENTITY, sequential GUID, timestamp), every new INSERT writes to the same rightmost leaf page. Under high concurrency, threads pile up on a latch protecting that page. Symptom: high `PAGELATCH_EX` waits, dropping insert throughput dramatically as concurrency increases.
>
> **Cross-Q**: How do you mitigate it?
>
> **A**: Several approaches: (1) hash-partition the index — `OPTIMIZE_FOR_SEQUENTIAL_KEY = ON` in SQL Server 2019+ reduces contention by quasi-randomizing inserts; (2) use a UUIDv4 PK (random) instead of sequential — spreads inserts across all leaves but kills cache locality; (3) batch inserts in larger transactions to reduce latch acquire/release frequency; (4) shard the table — multiple tables with different PK seeds, application picks one.
>
> **Cross-Q²**: Why is this a worse problem than it used to be?
>
> **A**: Hardware. Modern servers have 64-128+ cores. With 100 threads inserting concurrently, even a 100-nanosecond latch acquire-release serializes them. On a 4-core 2010 server, the contention was hidden by CPU bottleneck elsewhere. Modern CPUs are fast enough that latch contention becomes the dominant cost. SQL Server's `OPTIMIZE_FOR_SEQUENTIAL_KEY` was added specifically for this — it batches threads into "queues" that grab the latch in order, reducing CAS contention.

### Drill 9 — Page-level vs row-level locking

> **Q**: When does an engine pick page locks over row locks?
>
> **A**: At *lock-granularity selection* time, not by escalation — and keeping those two apart is the whole answer. SQL Server allocates ~96 bytes per lock; with 5,000 row locks held that is ~500 KB for one statement, so the engine will *start* a statement at page or table granularity when it expects to touch most of an object (bulk inserts, full scans, a `PAGLOCK`/`TABLOCK` hint). What it will **not** do is convert row locks into page locks afterwards. Microsoft Learn's *Transaction locking and row versioning guide* is explicit: "The Database Engine doesn't escalate row or key-range locks to page locks, but escalates them directly to table locks. Similarly, page locks are always escalated to table locks." Escalation itself fires when a single statement acquires at least 5,000 locks on one nonpartitioned table or index (retried every 1,250 new locks if the first attempt is blocked), or on the lock-memory threshold — and the result is a **table** lock, with no page-lock stop on the way. KB 323630 says it in one line: "Lock escalation always escalates to a table lock, and never to a page lock."
>
> **Cross-Q**: Can you force row-level only?
>
> **A**: `ALTER TABLE ... SET (LOCK_ESCALATION = DISABLE)` — but it's rarely a win. Disabling escalation means lock memory can grow unbounded, leading to out-of-memory errors. `WITH (ROWLOCK)` hint per query is similarly fragile — engine can ignore it under pressure. Better fix: rewrite the operation to touch fewer rows per transaction, or restructure the schema to localize hot updates.
>
> **Cross-Q²**: How does Postgres differ?
>
> **A**: Postgres uses row-level locks tracked via in-row metadata (xmax) plus a dedicated multixact structure for shared locks. No escalation. Locks are tied to MVCC row versions. Trade-off: Postgres can have very high lock counts without memory issues, but bulk updates create many dead tuples that VACUUM must clean up. SQL Server escalates to save memory; Postgres pays in VACUUM workload instead.

### Drill 10 — Lock escalation due to scan

> **Q**: My UPDATE statement is supposed to touch 100 rows. Why is it suddenly locking the whole table?
>
> **A**: Probably an unindexed predicate. `UPDATE orders SET status = 'X' WHERE customer_id = 7` — if there's no index on `customer_id`, the engine scans the entire table to find matches. It locks every row it scans (to ensure consistency) — millions of locks → escalation → table lock. The "100 rows updated" is the visible outcome; the locking footprint is the entire table.
>
> **Cross-Q**: How would you diagnose this in production?
>
> **A**: `sys.dm_tran_locks` for the running session shows current lock counts and resources. `sp_WhoIsActive` (Adam Machanic's free tool) shows blocking + locks per session. Or examine the execution plan — a Clustered Index Scan + Update indicates the lock footprint matches the scan, not the rowcount. The fix is the missing index, which makes both the query fast AND limits the lock footprint to seek's worth of rows.
>
> **Cross-Q²**: Why does scan-then-update lock everything instead of releasing as it moves?
>
> **A**: Isolation guarantees. Under REPEATABLE READ or SERIALIZABLE, locks must be held until commit to prevent phantoms/non-repeatable reads. Even under READ COMMITTED, the engine holds U (update intent) locks throughout the scan to prevent another transaction from modifying rows the scan hasn't yet evaluated. Releasing locks mid-scan would allow other transactions to modify rows the update was about to skip, breaking consistency. The engine prioritizes correctness over lock-footprint optimization.

### Drill 11 — KEY_LOOKUP vs RID_LOOKUP

> **Q**: In SQL Server execution plans, when do you see KEY_LOOKUP vs RID_LOOKUP?
>
> **A**: `KEY_LOOKUP` appears on tables with a clustered index — the nonclustered index leaf holds the clustered key, and the lookup uses that key to find the row in the clustered index B-tree. `RID_LOOKUP` appears on heap tables (no clustered index) — the nonclustered index leaf holds a Row Identifier (file:page:slot), and the lookup goes directly to that physical location.
>
> **Cross-Q**: Is one faster than the other?
>
> **A**: RID_LOOKUP is slightly faster on a per-lookup basis (direct page access vs B-tree traversal) but only by a few microseconds. The much bigger consideration is whether the lookup happens at all — covering indexes eliminate both. For heap tables, scans and lookups are common; for tables with proper clustered indexes, RID_LOOKUP shouldn't exist. Seeing RID_LOOKUP often means "this should have a clustered index."
>
> **Cross-Q²**: Why might you intentionally keep a heap (no clustered index)?
>
> **A**: Rare cases: (1) ETL staging tables where bulk inserts dominate — heaps insert slightly faster than clustered indexes because there's no PK B-tree to maintain; (2) tables where every query reads via covering nonclustered indexes — clustered index is dead weight; (3) very small tables (< 8 pages) where scan is always cheap. Most production OLTP tables should have a clustered index. The default "heap unless you have a reason" rule has reversed to "clustered unless you have a reason."

### Drill 12 — Included columns vs key columns size impact

> **Q**: I want to add `(status, total)` to my index on `(customer_id)`. Should I extend the key or use INCLUDE?
>
> **A**: INCLUDE almost always. Adding to the key bloats every level of the B-tree — inner nodes hold key values to direct seeks, so wider keys mean fewer keys per inner page, which means a taller tree, more I/O per seek, slower writes. INCLUDE columns only sit at the leaf level — they bloat the leaves but inner nodes stay slim. Use the key for columns you filter, sort, or join on; use INCLUDE for columns you only need to return.
>
> **Cross-Q**: When would adding to the key actually be better?
>
> **A**: When you also need to filter or sort by those columns. `WHERE customer_id = 7 AND status = 'Paid' ORDER BY total DESC` — putting `status` in the key (after `customer_id`) lets the engine seek directly to that status. Putting `status` in INCLUDE means the engine seeks to `customer_id` then filters status in memory, scanning all of that customer's orders. The wider key adds tree-depth cost but eliminates scan cost — net win when the predicate is selective enough.
>
> **Cross-Q²**: How does the size impact compound across many indexes?
>
> **A**: Per-table index size = sum across all indexes; each indexed table contributes to total disk and memory footprint. A wide-key composite index might be 30% the size of the heap; adding 5 such indexes can make the table's index footprint 2-3× the heap. Buffer pool fills with indexes, kicking out hot data, causing physical I/O. Audit `sys.dm_db_index_physical_stats` for `page_count` — if total index pages > heap pages by 5×, you have too much or wrong-shaped indexing.

### Drill 13 — Online index rebuild internals

> **Q**: How does `ALTER INDEX ... REBUILD WITH (ONLINE = ON)` work?
>
> **A**: SQL Server uses a "side-by-side" pattern: builds the new index alongside the old one while the table remains writable. Three concurrent structures: the old index (writable, source of truth), the new index (being built), and a "deletion bitmap" tracking which rows changed during the build. After the bulk build completes, a brief Sch-M lock swaps in the new index and discards the old. Total online except for the swap (milliseconds).
>
> **Cross-Q**: What's the catch?
>
> **A**: Three costs: (1) disk space — both indexes coexist during the build, ~2× the index size temporarily; (2) write amplification — every UPDATE during the build must touch both indexes; (3) sort operations may spill to tempdb. Long online rebuilds also accumulate version history that VACUUM-like processes need to clean. PostgreSQL's `REINDEX CONCURRENTLY` uses a similar pattern with similar costs.
>
> **Cross-Q²**: When does the optimizer pick a non-resumable rebuild over resumable?
>
> **A**: Resumable rebuilds (SQL Server 2017+) checkpoint progress and allow pause/resume — useful for huge indexes that don't fit in a maintenance window. Costs more than non-resumable: each checkpoint creates additional log records, and the build runs slightly slower because of progress tracking. Use resumable for indexes > 10GB or maintenance windows < the expected rebuild time. Use non-resumable (the default) for smaller indexes where the simplicity is worth it.

### Drill 14 — Partition-aligned indexes

> **Q**: What's a partition-aligned index?
>
> **A**: An index whose partition scheme matches the table's. Each partition of the table has its own corresponding index partition with the same boundaries. Maintenance operations (truncate partition, switch partition out) can include the index atomically. Queries hitting one partition use only that partition's index — partition elimination at the index level.
>
> **Cross-Q**: Why does it matter for query performance?
>
> **A**: Partition elimination. A query with `WHERE partition_key = 'X'` reads only the matching partition's index, not the entire index. For tables partitioned by month with 24 partitions, the engine skips 23/24 of the index — massive I/O reduction. Non-aligned indexes can't benefit; the entire index is searched regardless of the partition predicate.
>
> **Cross-Q²**: When would you use a *non-aligned* index intentionally?
>
> **A**: When the index must enforce uniqueness across all partitions globally. A unique index on `email` across all rows can't be partition-aligned by `created_at` (because the same email could appear in different time partitions and the partitioned uniqueness check wouldn't catch it). Non-aligned unique indexes work but can't be switched in/out partition-by-partition — every partition operation triggers a full index rebuild. Trade-off: global uniqueness vs partition agility.

### Drill 15 — Sorted vs unsorted writes

> **Q**: Why are sequential inserts orders of magnitude faster than random inserts on a B-tree index?
>
> **A**: Sequential inserts all hit the rightmost leaf page — that page stays cached, fits in CPU cache, page splits are rare and predictable. Random inserts scatter across the tree, causing constant page reads (often physical I/O), constant splits, fragmentation. On disk-backed indexes, the difference is 10-100× write throughput. Even on SSDs, random inserts to a tree-structured index are slower due to write amplification.
>
> **Cross-Q**: How does this affect GUID PK choice?
>
> **A**: Random GUIDs (UUIDv4) cause maximum random-insert pain on clustered indexes — every insert hits a different page. Sequential GUIDs (UUIDv7, `NEWSEQUENTIALID()`) preserve insertion order, behaving like IDENTITY for write performance while keeping the unique-across-systems property. Many modern systems migrating to UUIDv7 specifically to fix this. PostgreSQL with heap-organized tables suffers less (heap inserts are always sequential), but secondary indexes on random GUIDs still fragment.
>
> **Cross-Q²**: What about read patterns — is sequential always better for reads too?
>
> **A**: Yes for range scans (`ORDER BY pk` benefits from clustering by PK). Equal for point lookups (the B-tree handles both equally). Worse only when reads benefit from data being co-located by a *different* column than the PK — e.g., reads almost always filter by `customer_id` but PK is `id`. Then clustering by `customer_id` (or using a covering index on it) wins. The "monotonic PK is always best" rule is for writes; reads sometimes prefer a clustering choice that matches access patterns.

---

</details>

## Summary and Decision Matrix

### When to Use Each Index Type

| Situation | Best Index Type | Reason |
|-----------|----------------|--------|
| Single column WHERE | Non-clustered single | Fast, low overhead |
| Multiple column WHERE | Composite | Matches query pattern |
| Need SELECT columns with WHERE | Covering | Eliminates table access |
| Primary Key | Clustered | Natural table structure |
| Full table scan better | None | Sometimes better than index! |
| OLTP high volume writes | Few indexes, and sequentially-ordered ones | Minimize write amplification |
| OLAP data warehouse | **Clustered columnstore**, not many B-trees | Compression + rowgroup elimination beat any number of B-trees for scans |

> ⚠️ **"OLAP data warehouse → many indexes" was the original advice and it is a decade out of date.** Piling B-tree indexes onto a fact table gives you write amplification during the load and does nothing for the scan-and-aggregate queries a warehouse actually runs, because those queries touch a large fraction of the rows and a few of the columns — the exact case a rowstore index is worst at. The modern answer is a clustered columnstore index, whose column-wise storage, compression and rowgroup min/max metadata attack all three costs at once, plus a small number of B-trees only where the warehouse also serves point lookups.

### Index Budget

> ⚠️ **This section used to give a table of index counts by row count, and it disagreed with [Recommended Index Limits](#recommended-index-limits) earlier on the page** — 5-15 here versus 8-20 there for tables over 10M rows, which is the clearest possible evidence that neither was measured. The table has been replaced with what actually decides the budget; the other one is left in place, annotated, as the exhibit. Row count is the wrong axis anyway — a 50-million-row append-only table can carry many indexes cheaply, while a 2-million-row table taking a thousand updates a second can be brought down by three. What actually sets the budget:

```
The real constraints, in the order they bind:

1. WRITE PATH   Every INSERT touches every index. Every UPDATE
                touches every index whose KEY or INCLUDE columns
                changed — not all of them, which is why narrow,
                stable columns are cheap to index and volatile
                ones are not. Measure writes/sec, not rows.

2. BUFFER POOL  Indexes compete with data for cached pages. If
                adding an index evicts hot data, every query on
                the table gets slower, including the ones the
                index was meant to help. Watch page life
                expectancy, not index count.

3. INSERT ORDER A second index whose leading column is
                sequential is nearly free. One whose leading
                column is random splits pages on every insert.
                Two indexes, wildly different costs.

4. COVERAGE     Ask "how many query shapes does this index
                serve?" before "how many indexes do we have?"
                One well-ordered composite often replaces three
                narrow ones — see the three-star model.

There is no number. There is a review that asks, per index:
which query needs this, is an existing index one column away
from serving it, and what does it cost the write path?
```

---

## Conclusion

Understanding SQL indexes is critical for database performance:

1. **A seek's cost grows with the log of the row count; a scan's grows with the row count.** That difference in growth rate is the whole value proposition — not any multiplier.
2. **Every INSERT maintains every index. An UPDATE maintains the indexes whose key or `INCLUDE` columns it changed** — which is why indexing narrow, stable columns is cheap and indexing volatile ones is not.
3. **Column order is set by equality-before-range, then by which queries need the leading column** — not by "most selective first", which is folklore.
4. **Covering removes the per-row lookup**, which is why it matters most for queries returning many rows and barely at all for ones returning five. On PostgreSQL it only works when `VACUUM` has kept the visibility map current.
5. **Too many indexes do not "confuse" a cost-based optimizer** — it still costs every candidate. They cost you write amplification, buffer pool, and longer compile times, and they make redundancy hard to spot. Those are the real reasons to prune.
6. **Fragmentation is the least important index metric you can name.** Page density matters more, statistics freshness matters far more, and on flash storage the sequential-vs-random argument mostly evaporates.
7. **A bad plan is usually a good decision made on a bad estimate.** Fix the estimate — statistics, SARGability, correlated columns — before you reach for a hint.

**Golden Rules:**
- Index the predicates your hot queries actually use, in the order equality-then-range
- Prefer widening an existing index to adding a new one
- Read rows-read-per-row-returned before reading the operator name
- Keep the clustered key narrow, unique and ideally sequential — every non-clustered index carries a copy of it
- Drop unused indexes, but only after uptime long enough to include month-end
- Say which engine you mean; SQL Server, PostgreSQL and MySQL disagree on clustering, on NULLs in unique indexes, and on `INCLUDE`

---

## Self-test

<details><summary>1. On SQL Server, what exactly does a non-clustered index leaf row point at?</summary>

A **row locator**, and what it holds depends on the table. If the table has a clustered index, the locator is the **clustered index key**; if the table is a heap, it is a **RID** (file:page:slot). Microsoft Learn, *Index architecture and design guide*, states both. Three consequences: the clustered key's width is copied into every non-clustered index; the locator columns are appended to the index key (non-unique index) or to the includes (unique index); and because the clustered key is physically present at the leaf, you can filter and sort on it without adding it to the definition. This is why "keep the clustered key narrow" is advice about the *other* indexes.
</details>

<details><summary>2. Your plan says <code>Index Seek</code> and the query reads 800,000 rows to return 40. Where do you look?</summary>

At the split between **seek predicate** and **residual predicate**. The seek establishes a range; anything it can't bound is applied afterwards to rows already fetched. In SQL Server the operator properties show `Seek Predicates` versus `Predicate`, and an *actual* plan exposes `Number of Rows Read` next to `Actual Number of Rows`. In PostgreSQL it is `Index Cond` versus `Filter` plus `Rows Removed by Filter`. The fix is to move the residual column into the index key so it bounds the scan — which usually means placing it *before* any range-predicate column.
</details>

<details><summary>3. Index on <code>(TenantId, CreatedAt, Status)</code>; query is <code>WHERE TenantId = 1 AND CreatedAt >= @d AND Status = 'Active'</code>. What's wrong?</summary>

The range predicate sits in the middle of the key. A seek boundary can use a run of equality predicates plus **at most one** range predicate; everything after the range column stops bounding the seek. So `Status` becomes a residual filter and the seek reads every row for that tenant since `@d`, discarding the non-Active ones. Reorder to `(TenantId, Status, CreatedAt)` and all three predicates bound the seek. Same columns, same selectivity, very different work — this is why "most selective column first" is the wrong rule.
</details>

<details><summary>4. Is <code>CREATE UNIQUE INDEX IX_Email ON Users(Email)</code> safe on a nullable column?</summary>

Depends entirely on the engine, and this one catches people who develop on PostgreSQL and deploy to SQL Server. **SQL Server permits at most one NULL**: "You cannot create a unique index on a single column if that column contains NULL in more than one row... These are treated as duplicate values for indexing purposes" (Microsoft Learn, *Create a unique index*). **PostgreSQL and MySQL permit any number**, per the ANSI reading that NULLs aren't equal; PostgreSQL 15 added `NULLS NOT DISTINCT` to opt into SQL Server's behaviour. On SQL Server the fix is a filtered index: `CREATE UNIQUE INDEX ... ON Users(Email) WHERE Email IS NOT NULL`.
</details>

<details><summary>5. Why might a filtered index on <code>WHERE Status = 'Pending'</code> never be used by <code>WHERE Status = @status</code>?</summary>

The optimizer must prove the query's predicate implies the index's predicate **at compile time**, and the plan it compiles is cached for later calls with other values of `@status`. It can't prove it, so it won't risk it. Fix with a literal in a dedicated query, or `OPTION (RECOMPILE)`, which embeds the value at compile time. SQL Server records the near-miss in the plan XML's `<UnmatchedIndexes>` element. Separately, filtered indexes need `ANSI_NULLS`, `ANSI_PADDING`, `ANSI_WARNINGS`, `QUOTED_IDENTIFIER`, `ARITHABORT`, `CONCAT_NULL_YIELDS_NULL` ON and `NUMERIC_ROUNDABORT` OFF — and for stored procedures, `ANSI_NULLS` and `QUOTED_IDENTIFIER` are fixed at creation time, not taken from the session.
</details>

<details><summary>6. There's a perfectly good index on the column and the query scans anyway. Give three causes.</summary>

(a) **Non-SARGable predicate** — the column is wrapped in a function or cast (`YEAR(CreatedAt) = 2026`, `CAST(x AS date) = ...`), so the B-tree's sort order is unusable. (b) **Implicit conversion** — a `varchar` column compared to an `nvarchar` parameter, the default for a `string` property in EF Core, converts the *column* per row; the plan shows `CONVERT_IMPLICIT` inside the predicate. Fix with `.IsUnicode(false)`. (c) **The tipping point** — the optimizer estimated enough rows that a seek-plus-lookup plan costs more than a scan, so it chose the scan on purpose. Only (c) is the optimizer being right; for (a) and (b) it has no choice.
</details>

<details><summary>7. What is the tipping point, and what units is it measured in?</summary>

The estimated row count at which seek-plus-key-lookup stops being cheaper than a clustered index scan. Lookups cost one tree descent **per row returned**, so that plan's cost rises linearly while the scan's stays roughly flat; the lines cross. The counter-intuitive part, from Kimberly Tripp's work at SQLskills, is that it is expressed in **pages of the table, not rows** — roughly, lookups survive below ~25% of the table's page count and a scan wins above ~33%. Because a page holds many rows, that can be a very small percentage of the rows. A covering index removes the per-row lookup and so removes the cliff entirely.
</details>

<details><summary>8. A nightly <code>ALTER INDEX ALL ... REBUILD</code> demonstrably makes mornings faster. What is it actually doing?</summary>

Most likely refreshing statistics, not defragmenting. A rowstore rebuild updates the index's statistics by scanning every row — equivalent to `UPDATE STATISTICS ... WITH FULLSCAN` — which recompiles the plans referencing them. Microsoft says this outright: improvements after a rebuild "are unrelated to reducing fragmentation or increasing page density... the same benefit can often be achieved at a much lower resource cost by updating statistics instead" (Microsoft Learn, *Maintain indexes optimally*). Test it by replacing the rebuild with `UPDATE STATISTICS` for a week. Note the asymmetry: **`REORGANIZE` does not update statistics at all**, so a reorganize-based script gets none of this benefit.
</details>

<details><summary>9. Which index metric should you watch instead of <code>avg_fragmentation_in_percent</code>?</summary>

`avg_page_space_used_in_percent` — **page density**. Microsoft: "In many workloads, increasing page density results in a greater positive performance impact than reducing fragmentation." Low density means more pages for the same rows, so more I/O, more buffer pool consumed, and a higher estimated I/O cost that can change the plan the optimizer picks. Two practical notes: `LIMITED` mode of `sys.dm_db_index_physical_stats` does **not** return it — use `SAMPLED` or `DETAILED` — and both numbers are noise below roughly 1,000 pages, because small indexes historically sat on mixed extents, which Microsoft describes as "shared by up to eight objects".
</details>

<details><summary>10. How do you add an index to a 300-million-row table that is taking writes?</summary>

**PostgreSQL:** `CREATE INDEX CONCURRENTLY`. A plain `CREATE INDEX` holds a `SHARE` lock that blocks every writer for the whole build. Concurrent builds cost two table passes, cannot run inside a transaction block, and leave an invalid index behind on failure (drop and retry). **SQL Server:** `WITH (ONLINE = ON)` — Enterprise edition only, so verify the target edition, not just the dev instance; add `RESUMABLE = ON` for builds that won't fit a window, and `WAIT_AT_LOW_PRIORITY` if long transactions are likely. Watch the version split on `RESUMABLE`: "`ALTER INDEX` starting with SQL Server 2017 (14.x), and `CREATE INDEX` starting with SQL Server 2019 (15.x)" (Microsoft Learn, *Guidelines for online index operations*) — so for *adding* an index, as here, the floor is 2019, not 2017. Budget disk for two copies of the index during the build. **MySQL/InnoDB:** `ALTER TABLE ... ADD INDEX ..., ALGORITHM=INPLACE, LOCK=NONE`, so the statement errors rather than silently copying the whole table.
</details>

<details><summary>11. You are asked to "add a clustered index" to a PostgreSQL table. What do you say?</summary>

That PostgreSQL has no maintained clustered index. Tables are always heaps; `CLUSTER table USING index` is a one-shot physical reorder — "Clustering is a one-time operation: when the table is subsequently updated, the changes are not clustered" (PostgreSQL docs, *CLUSTER*) — and it takes an `ACCESS EXCLUSIVE` lock that "prevents any other database operations (both reads and writes)". MySQL/InnoDB is the opposite extreme: it *always* clusters, on the primary key, or the first `UNIQUE NOT NULL` index, or a hidden 6-byte row ID, with no way to opt out. Only SQL Server gives you the choice between a heap and a clustered index.
</details>

<details><summary>12. The missing-index DMV suggests an index with impact 4,000,000. Do you create it?</summary>

Not as emitted. Microsoft's own limitations list says the feature "is not intended to fine tune an indexing configuration" and "does not specify an order for columns to be used in an index" — the `equality_columns` come out in column-id order, so you must reorder them yourself (equality before inequality first; selectivity only as a tiebreak within the equality columns). It tracks at most 500 missing index groups and returns at most 600 rows, ignores trivial plans, never suggests filtered indexes, and gives poor costs for inequality-only predicates. It also does not persist: the counters reset on restart, so check `sys.dm_os_sys_info.sqlserver_start_time` before trusting them. The limitation Microsoft doesn't list is the worst: **it does not consider indexes that already exist**, so it will happily recommend a near-duplicate of one you have. Check whether an existing index is one column away from serving the query, reorder the keys, and weigh the write cost the DMV never mentions.
</details>

<details><summary>13. Does adding <code>DESC</code> to a single-column index help <code>ORDER BY CreatedAt DESC</code>?</summary>

Barely. B-tree leaf pages are doubly linked, so SQL Server reads an ascending index backwards at essentially the same cost — there is no "reverse scan penalty" to avoid. `DESC` genuinely matters in two cases: **mixed sort directions** in a composite index (`ORDER BY TenantId ASC, CreatedAt DESC` cannot be served by an all-ASC index in either direction), and **parallelism** (SQL Server will not produce a parallel plan for a backward ordered scan, so matching the index direction is what lets a large scan go parallel). Engine note: MySQL ignored `DESC` in index definitions entirely before 8.0.
</details>

<details><summary>14. Why is a wide clustered key expensive even if nothing queries it?</summary>

Two compounding mechanisms. **Fanout:** a wider key means fewer entries per 8 KB page, so lower fanout, so a deeper tree, so more page reads on *every* seek of that index. **Propagation:** the clustered key is the row locator, so it is duplicated into every leaf row of every non-clustered index on the table — a 400-byte key on a table with six non-clustered indexes is stored seven times per row. That is why a wide natural key as the PK can inflate an entire table's index footprint without anyone adding an index. SQL Server's ceilings — 900 bytes clustered, 1,700 non-clustered since 2016 — describe the envelope the engine expects. InnoDB has the same propagation problem with no `INCLUDE` to soften it.
</details>

---

## Sources

<details>
<summary>📚 Click to expand — sources for every cited figure on this page</summary>

Every quantity quoted in the added sections traces to one of these. Figures in the original ASCII blocks that could not be traced were relabelled as illustrative or removed.

- **Microsoft Learn — [SQL Server and Azure SQL index architecture and design guide](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-index-design-guide)** — row locators (clustered key vs RID), how locator columns are added to keys versus includes, uniqueifier on non-unique clustered indexes.
- **Microsoft Learn — [Maintain Indexes Optimally to Improve Performance and Reduce Resource Utilization](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/reorganize-and-rebuild-indexes)** — the definition of fragmentation; page density versus fragmentation; "shouldn't be based on fixed fragmentation or page density thresholds alone"; statistics updated by rebuild but *not* by reorganize; small-index/mixed-extent caveat; two copies of the index during a rebuild; fill factor guidance; sequential-vs-random I/O on Azure storage.
- **Microsoft Learn — [Statistics](https://learn.microsoft.com/en-us/sql/relational-databases/statistics/statistics)** — histogram built on the first key column only, maximum 200 steps; density vector per column prefix; the `MIN(500 + 0.20n, SQRT(1000n))` auto-update threshold and its 2,000,000-row worked example; trace flag 2371.
- **Microsoft Learn — [Create a unique index](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/create-unique-indexes)** — one NULL only in a SQL Server unique index.
- **Microsoft Learn — [Perform index operations online](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/perform-index-operations-online)** — `ONLINE` not available in every edition; available in Azure SQL Database and Managed Instance.
- **Microsoft Learn — [Guidelines for online index operations](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/guidelines-for-online-index-operations)** — the `RESUMABLE` version split: `ALTER INDEX` from SQL Server 2017, `CREATE INDEX` from SQL Server 2019; `RESUMABLE` requires `ONLINE`.
- **Microsoft Learn — [Columnstore indexes: Overview](https://learn.microsoft.com/en-us/sql/relational-databases/indexes/columnstore-indexes-overview)** — "up to 10 times the query performance", "up to 10 times the data compression", batch mode "typically by two to four times"; 1,048,576-row rowgroups; 102,400-row deltastore threshold; segment min/max elimination.
- **Microsoft Learn — [Limitations of the Missing Indexes Feature](https://learn.microsoft.com/en-us/previous-versions/sql/sql-server-2008-r2/ms345485(v=sql.105))** — the verbatim limitations list quoted in Monitoring and Maintenance.
- **Microsoft Learn — [CREATE INDEX](https://learn.microsoft.com/en-us/sql/t-sql/statements/create-index-transact-sql)** and [Maximum capacity specifications](https://learn.microsoft.com/en-us/sql/sql-server/maximum-capacity-specifications-for-sql-server) — 999 non-clustered indexes per table, 32 key columns, 900-byte clustered / 1,700-byte non-clustered key limits.
- **Microsoft Learn — [Table Hints](https://learn.microsoft.com/en-us/sql/t-sql/queries/hints-transact-sql-table)** — `FORCESEEK` forces a seek, `FORCESCAN` forces a scan (`FORCESCAN` added in SQL Server 2008 R2 SP1).
- **PostgreSQL documentation — [Index-Only Scans and Covering Indexes](https://www.postgresql.org/docs/current/indexes-index-only-scans.html)** — visibility information lives in heap entries; the visibility map bit check; `INCLUDE`.
- **PostgreSQL documentation — [CLUSTER](https://www.postgresql.org/docs/current/sql-cluster.html)** — "Clustering is a one-time operation"; `ACCESS EXCLUSIVE` lock.
- **MySQL Reference Manual — [Clustered and Secondary Indexes](https://dev.mysql.com/doc/refman/8.0/en/innodb-index-types.html)** and **[Descending Indexes](https://dev.mysql.com/doc/refman/8.0/en/descending-indexes.html)** — secondary index rows contain the primary key columns; `DESC` ignored before MySQL 8.0.
- **Kimberly L. Tripp, [SQLskills](https://www.sqlskills.com/blogs/kimberly/)** — the tipping point, and that it is measured against the table's page count rather than its row count.
- **Lahdenmäki & Leach, *Relational Database Index Design and the Optimizers*** — the three-star index model.
- **Markus Winand, [use-the-index-luke.com](https://use-the-index-luke.com/)** / *SQL Performance Explained* — equality-before-range column ordering, and the case against "most selective column first".
- **Brent Ozar — [When Should You Use DESC in Indexes?](https://www.brentozar.com/archive/2022/01/when-should-you-use-desc-in-indexes/)** — backward ordered scans and parallelism in SQL Server.

</details>

---

**Document Version:** 1.1  
**Last Updated:** August 12, 2026  
**Applicability:** WT_Builder_Workflow_Definition and similar tables. SQL Server unless stated otherwise.

<!-- nav-footer-start -->

---

[← Previous: Indexes & Query Optimization](06-indexes-and-query-optimization.md) · [↑ Back to top](#sql-indexes--deep-dive) · [Next: Transactions & Concurrency →](07-transactions-and-concurrency.md)

<!-- nav-footer-end -->
