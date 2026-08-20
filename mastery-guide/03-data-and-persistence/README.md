# 03 — Data & Persistence

> [Mastery Guide](../README.md) › Data & Persistence

ORMs, query languages, and the storage engines they sit on top of. Covers .NET's primary data stack (EF Core + LINQ + SQL Server) plus caching (Redis) and time-series (InfluxDB) for specialized workloads.

## Topics in this chapter

| # | Topic | Status | Priority | Phase |
|---|---|---|---|---|
| 1 | [EF Core](./01-ef-core.md) | Not Started | High | Phase 5 |
| 2 | [LINQ](./02-linq.md) | Not Started | High | Phase 5 |
| 3 | [**SQL Mastery**](./03-sql/README.md) (9-file sub-chapter) | Not Started | High | Phase 5 |
| 4 | [MS SQL Server](./04-mssql-server.md) | Not Started | High | Phase 5 |
| 5 | [Redis](./05-redis.md) | Not Started | High | Phase 5 |
| 6 | [InfluxDB](./06-influxdb.md) | Not Started | Low | Phase 9 |
| 7 | [NoSQL & Document Stores (MongoDB, Cosmos DB)](./07-nosql-document-stores.md) | Not Started | High | Phase 5 |
| 8 | [PostgreSQL](./08-postgresql.md) | Not Started | High | Phase 5 |

The **SQL Mastery** entry is a sub-chapter folder containing 9 files covering basics through advanced — ~3,500 lines of interview-grade SQL. See [its README](./03-sql/README.md) for the full TOC.

---

## Recommended reading order within this chapter

1. **EF Core** + **LINQ** are the day-to-day work — both have full deep-dive coverage already.
2. **SQL Mastery** sub-chapter — read sequentially (Fundamentals → ... → Advanced Patterns) or as a reference. Then **MS SQL Server** for vendor-specific deep-dive on top.
3. **Redis** — the deep-dive covers the caching strategy primer; layer Redis-specific topics (clustering, persistence, eviction) on top.
4. **InfluxDB** is specialized — only when you actually need time-series.
5. **NoSQL & Document Stores** — read alongside SQL Mastery to compare the relational and document worlds; covers MongoDB and Cosmos DB.
6. **PostgreSQL** — vendor-specific deep-dive on the open-source RDBMS standard in 2026; pairs with SQL Mastery and offers a direct comparison to MS SQL Server.

<!-- nav-footer-start -->

---

[← Previous: Advanced Auth — OAuth 2.1, DPoP, FAPI, Token Introspection](../02-api-development/17-advanced-auth.md) · [↑ Back to top](#03--data--persistence) · [Next: EF Core →](01-ef-core.md)

<!-- nav-footer-end -->
