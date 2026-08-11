# 02 — API Development

> [Mastery Guide](../README.md) › API Development

Everything about exposing capabilities over the wire: REST, GraphQL, the various streaming/event protocols, plus the cross-cutting concerns (auth, design, security, versioning, testing, docs) that separate a working API from a production-grade one.

## Topics in this chapter

| # | Topic | Status | Priority | Phase |
|---|---|---|---|---|
| 1 | [REST & Web API](./01-rest-and-web-api.md) | Not Started | High | Phase 3 |
| 2 | [Authentication & Authorization](./02-authentication-and-authorization.md) | Started | High | Phase 4 |
| 3 | [API Design Principles](./03-api-design-principles.md) | Not Started | High | Phase 4 |
| 4 | [API Security](./04-api-security.md) | Not Started | High | Phase 4 |
| 5 | [API Versioning](./05-api-versioning.md) | Not Started | High | Phase 4 |
| 6 | [API Testing](./06-api-testing.md) | Not Started | Medium | Phase 6 |
| 7 | [API Documentation](./07-api-documentation.md) | Not Started | Low | Phase 6 |
| 8 | [GraphQL](./08-graphql.md) | Not Started | Medium | Phase 8 |
| 9 | [Webhooks](./09-webhooks.md) | Not Started | Low | Phase 8 |
| 10 | [WebSockets](./10-websockets.md) | Not Started | Medium | Phase 8 |
| 11 | [SOAP](./11-soap.md) | Not Started | Low | Phase 8 |
| 12 | [MQTT](./12-mqtt.md) | Not Started | Low | Phase 8 |
| 13 | [Event-Driven Architecture](./13-event-driven-architecture.md) | Not Started | High | Phase 8 |
| 14 | [BFF & Aggregation](./14-bff-and-aggregation.md) | Not Started | High | Phase 4 |
| 15 | [Server-Sent Events](./15-server-sent-events.md) | Not Started | Medium | Phase 8 |
| 16 | [API Management & Gateway](./16-api-management.md) | Not Started | High | Phase 4 |
| 17 | [Advanced Auth (OAuth 2.1, DPoP, FAPI, Token Introspection)](./17-advanced-auth.md) | Not Started | High | Phase 4 |

---

## Recommended reading order within this chapter

1. **REST & Web API** first — most APIs are still REST, and the deep-dive already covers this.
2. **Authentication & Authorization** — JWT is covered; layer OIDC and ASP.NET Identity on top.
3. The **Design / Security / Versioning / Testing / Documentation** quintet — these are the cross-cutting concerns interviewers care about.
4. **BFF & Aggregation** for client-specific back-ends — sits with auth/security since cookie-on-server auth is its biggest production justification.
5. The protocol survey (GraphQL, Webhooks, WebSockets, **SSE**, SOAP, MQTT, EDA) — read these when you encounter a system using them, or when you're doing protocol comparison study. SSE is the modern default for one-way server→client push (LLM token streaming, notification feeds).
6. **API Management & Gateway** — when your platform exposes more than a couple of APIs, this is where cross-cutting concerns (auth, rate limit, transformation, monetization) live.
7. **Advanced Auth** — OAuth 2.1, DPoP, FAPI, token introspection — the senior-interview surface beyond JWT bearer.

<!-- nav-footer-start -->

---

[← Previous: Interview Problems](../01-foundations/06-dsa/07-interview-problems.md) · [↑ Back to top](#02--api-development) · [Next: REST & Web API →](01-rest-and-web-api.md)

<!-- nav-footer-end -->
