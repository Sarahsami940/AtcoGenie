# AtcoGenie — .NET ↔ FastAPI Coexistence Strategy

> This document defines how the .NET Identity Gateway and FastAPI AI Engine
> run side-by-side on the same VM.

---

## Port Mapping

| Service | Port | Protocol |
|---------|------|----------|
| .NET Backend (IIS) | 5256 | HTTP |
| FastAPI AI Engine | 8000 | HTTP |
| PostgreSQL (IMD + Chats) | 5432 | TCP |
| PostgreSQL (Checkpointer) | 5432 | TCP (same instance, different DB) |
| Redis | 6379 | TCP |

## IIS Reverse Proxy Rules

When deploying behind a single domain, IIS routes requests by path:

```xml
<!-- web.config URL Rewrite rules -->
<rule name="FastAPI AI Engine" stopProcessing="true">
    <match url="^api/v1/(.*)" />
    <action type="Rewrite" url="http://localhost:8000/api/v1/{R:1}" />
</rule>
<!-- All other /api/* routes go to .NET as usual -->
```

| URL Pattern | Routed To |
|-------------|-----------|
| `/api/v1/chat` | FastAPI :8000 |
| `/api/v1/auth/login` | FastAPI :8000 |
| `/api/v1/health` | FastAPI :8000 |
| `/api/chats/*` | .NET :5256 |
| `/api/folders/*` | .NET :5256 |
| `/api/query` | .NET :5256 (legacy, removed later) |
| `/*` (static files) | .NET :5256 (serves React from wwwroot) |

## Shared Resources

### PostgreSQL (Same Instance, Multiple Databases)
- `AtcoGenie_IMD` — Identity mappings (both backends read)
- `AtcoGenie_Chats` — Chat sessions & messages (.NET owns)
- `AtcoGenie_Checkpoints` — LangGraph agent state (Python owns)

### Redis (Single Instance)
- DB 0: Python session/cache (role cache, query cache, rate limits)
- The .NET backend does not currently use Redis

## Frontend Routing

The React frontend must know which backend to call:

```typescript
// api.ts — route based on endpoint
const AI_BASE = '/api/v1';     // → FastAPI
const DOTNET_BASE = '/api';     // → .NET

// AI queries go to FastAPI
export const sendChat = (msg) => fetch(`${AI_BASE}/chat`, ...);

// Chat/folder CRUD stays on .NET
export const getFolders = () => fetch(`${DOTNET_BASE}/folders`, ...);
export const getChatSessions = () => fetch(`${DOTNET_BASE}/chats`, ...);
```

## Deployment Order

1. Deploy .NET backend normally (IIS site, same as today)
2. Install Python 3.12+ on VM
3. Install Redis on VM (or Docker container)
4. Create `AtcoGenie_Checkpoints` PostgreSQL database
5. Deploy FastAPI as Windows service (via NSSM)
6. Add IIS URL Rewrite rule for `/api/v1/*`
7. Verify health: `GET /api/v1/health`

## Rollback Procedure

If FastAPI has issues after go-live:

1. Remove IIS URL Rewrite rule for `/api/v1/*`
2. Re-enable legacy AI endpoints in .NET (GenieQueryService)
3. Frontend auto-falls back to `/api/query` endpoint
4. Stop FastAPI service

Feature flag in React:
```typescript
const USE_LANGCHAIN = true; // Set to false to rollback
const chatEndpoint = USE_LANGCHAIN ? '/api/v1/chat' : '/api/query';
```
