# .NET Core / ASP.NET Core Deep Dive Guide

> [Mastery Guide](../../README.md) › [Foundations](../README.md) › .NET Core Deep Dive

**Comprehensive Understanding of .NET 10, C#, and ASP.NET Core**

**Last reviewed:** 2026-05-07 (post .NET 10 GA)  
**Scope:** .NET Fundamentals through Advanced Patterns  
**Level:** Beginner to Advanced

> Mechanics in this guide are version-agnostic across .NET 6–10. For per-version feature deltas, see [Version History](./18-version-history.md).

---

This is the deep-dive chapter of the [Mastery Guide](../../README.md), covering .NET 10 + ASP.NET Core in detail across 18 focused topic files. Each topic file carries its own in-file Table of Contents.

## Master Table of Contents

1. [.NET Fundamentals, C# Core Concepts & Garbage Collection](./01-net-fundamentals.md) — .NET, C# core concepts, garbage collection
2. [Dependency Injection in .NET 10](./02-dependency-injection.md)
3. [Async/Await, Multithreading & Synchronization Primitives](./03-async-and-threading.md)
4. [Middleware in ASP.NET Core](./04-middleware.md) — pipeline, conditional middleware, registration
5. [Entity Framework Core, LINQ & Data Querying](./05-data-access.md)
6. [Microservices, APIs & Minimal APIs](./06-apis-and-microservices.md)
7. [Unit Testing](./07-testing.md) — xUnit + Moq
8. [Hash Tables, Best Practices & Design Patterns](./08-patterns-and-best-practices.md)
9. [Security & Authentication](./09-security.md) — JWT + OWASP
10. [Caching Strategies](./10-caching.md) — In-Memory, Distributed, Output
11. [SignalR — Real-Time Communication](./11-signalr.md)
12. [Modern C# Features](./12-modern-csharp.md) — records, pattern matching, primary ctors
13. [Exception Handling & Result Pattern](./13-exception-handling.md)
14. [HttpClient & Resilience (Polly)](./14-httpclient-resilience.md)
15. [Configuration Deep Dive](./15-configuration.md) — IOptions variants, priority
16. [Interview Prep — Quick Reference, Revision Sheet & Mind Map](./16-interview-prep.md)
17. [Hands-On Mini Project: TaskFlow API](./17-taskflow-mini-project.md)
18. [.NET Version History (.NET 7 → .NET 10)](./18-version-history.md) — feature-by-feature reference across recent releases

---

## Section Mapping (Original → New File)

For readers familiar with the original numbered sections:

| Original section | New file |
|---|---|
| 1. .NET Fundamentals | [01-net-fundamentals.md](./01-net-fundamentals.md#1-net-fundamentals) |
| 2. C# Core Concepts | [01-net-fundamentals.md](./01-net-fundamentals.md#2-c-core-concepts) |
| 3. Garbage Collection | [01-net-fundamentals.md](./01-net-fundamentals.md#3-garbage-collection-in-net-10) |
| 4. Dependency Injection | [02-dependency-injection.md](./02-dependency-injection.md#4-dependency-injection-in-net-10) |
| 5. Async/Await | [03-async-and-threading.md](./03-async-and-threading.md#5-asyncawait-in-c-and-net-10) |
| 6. Multithreading | [03-async-and-threading.md](./03-async-and-threading.md#6-multithreading-and-parallel-execution) |
| 7. Synchronization Primitives | [03-async-and-threading.md](./03-async-and-threading.md#7-synchronization-primitives) |
| 8. Middleware | [04-middleware.md](./04-middleware.md#8-middleware-in-aspnet-core-net-10) |
| 9. Conditional Middleware | [04-middleware.md](./04-middleware.md#9-conditional-middleware) |
| 10. Ways to Register Middleware | [04-middleware.md](./04-middleware.md#10-ways-to-register-middleware) |
| 11. Entity Framework Core | [05-data-access.md](./05-data-access.md#11-entity-framework-ef-and-ef-core) |
| 12. LINQ and Data Querying | [05-data-access.md](./05-data-access.md#12-linq-and-data-querying) |
| 13. Microservices & APIs | [06-apis-and-microservices.md](./06-apis-and-microservices.md#13-microservices--apis) |
| 14. Unit Testing | [07-testing.md](./07-testing.md#14-unit-testing) |
| 15. Hash-Based Lookup Table | [08-patterns-and-best-practices.md](./08-patterns-and-best-practices.md#15-hash-based-lookup-table) |
| 16. General Best Practices | [08-patterns-and-best-practices.md](./08-patterns-and-best-practices.md#16-general-best-practices) |
| 17. ASP.NET Core Concepts (1-25) | [16-interview-prep.md](./16-interview-prep.md#17-aspnet-core-concepts-1-25) |
| 18. Design Patterns in .NET | [08-patterns-and-best-practices.md](./08-patterns-and-best-practices.md#18-design-patterns-in-net) |
| 19. Security & Authentication | [09-security.md](./09-security.md#19-security--authentication) |
| 20. Caching Strategies | [10-caching.md](./10-caching.md#20-caching-strategies) |
| 21. SignalR | [11-signalr.md](./11-signalr.md#21-signalr---real-time-communication) |
| 22. Minimal APIs | [06-apis-and-microservices.md](./06-apis-and-microservices.md#22-minimal-apis) |
| 23. Modern C# Features | [12-modern-csharp.md](./12-modern-csharp.md#23-modern-c-features) |
| 24. Exception Handling | [13-exception-handling.md](./13-exception-handling.md#24-exception-handling--result-pattern) |
| 25. HttpClient & Resilience | [14-httpclient-resilience.md](./14-httpclient-resilience.md#25-httpclient--resilience-polly) |
| 26. Configuration | [15-configuration.md](./15-configuration.md#26-configuration-deep-dive) |
| 27. Interview Revision Sheet | [16-interview-prep.md](./16-interview-prep.md#27-interview-revision-sheet) |
| 28. Concept Mind Map | [16-interview-prep.md](./16-interview-prep.md#28-concept-mind-map) |
| 29. Hands-On Mini Project: TaskFlow API | [17-taskflow-mini-project.md](./17-taskflow-mini-project.md#29-hands-on-mini-project-taskflow-api) |
| 30. .NET Version History (.NET 7 → .NET 10) | [18-version-history.md](./18-version-history.md) |

<!-- nav-footer-start -->

---

[← Previous: 01 — Foundations](../README.md) · [↑ Back to top](#net-core--aspnet-core-deep-dive-guide) · [Next: .NET Fundamentals, C# Core Concepts & Garbage Collection →](01-net-fundamentals.md)

<!-- nav-footer-end -->
