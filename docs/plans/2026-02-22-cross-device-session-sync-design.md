# Cross-Device Session Sync Design

**Date:** 2026-02-22
**Status:** Approved
**Problem:** When a user logs into their account on a new device, all local learning data (chat history, CA memory, dynamic report, workspace files) is lost. The backend only stores a progress checkpoint — not the full conversational state.

---

## Goal

Enable a user to open a chapter on any device and silently recover their full session state (chat history, CA memory, dynamic report) plus access previously submitted workspace files.

---

## Scope

**Recoverable on new device:**
- Full chat history (all turn-by-turn messages)
- Latest CA memory/memo state
- Latest dynamic learning report (Markdown)
- User-submitted `.py` / `.ipynb` workspace files

**Not in scope (v1):**
- Expert consultation transcripts
- Dataset files uploaded during session
- Code execution history

---

## Architecture: Sidecar-Direct Sync (Approach B)

Desktop registers a session with the backend first, receives a `session_id`, then passes both the `session_id` and its JWT to the sidecar at session create time. After each turn completes, the sidecar posts turn data + memory + report directly to the backend. Sync is best-effort — failures are logged but never block the student.

```
Desktop ──[POST /chapters/{id}/sessions]──► Backend (PG)
   │                                          returns session_id
   │
   └──[POST /api/session/create + session_id + auth_token]──► Sidecar
                                                                  │
                                              after each turn ◄───┤
                                                                  │
Sidecar ──[POST /sessions/{id}/turns      ]──► Backend (PG)
        ──[PUT  /sessions/{id}/memory     ]──►
        ──[PUT  /sessions/{id}/report     ]──►
```

---

## Database Schema

### New tables

```sql
-- Backend-registered sessions (source of truth for session identity)
sessions (
  session_id  VARCHAR(64)  PRIMARY KEY,
  user_id     UUID         NOT NULL REFERENCES users(id),
  chapter_id  VARCHAR(64)  NOT NULL,
  course_id   VARCHAR(64),
  created_at  TIMESTAMPTZ  DEFAULT NOW(),
  last_active_at TIMESTAMPTZ DEFAULT NOW()
);

-- Full turn history (immutable append)
session_turn_history (
  id                  BIGSERIAL PRIMARY KEY,
  user_id             UUID         NOT NULL,
  session_id          VARCHAR(64)  NOT NULL REFERENCES sessions(session_id),
  chapter_id          VARCHAR(64)  NOT NULL,
  turn_index          INTEGER      NOT NULL,
  user_message        TEXT         NOT NULL,
  companion_response  TEXT         NOT NULL,
  turn_outcome        JSONB,
  created_at          TIMESTAMPTZ  DEFAULT NOW(),
  UNIQUE (session_id, turn_index)
);

-- Latest CA memory state (upsert on each turn)
session_memory_state (
  id           BIGSERIAL PRIMARY KEY,
  user_id      UUID        NOT NULL,
  session_id   VARCHAR(64) NOT NULL REFERENCES sessions(session_id),
  chapter_id   VARCHAR(64) NOT NULL,
  memory_json  JSONB       NOT NULL,   -- memo_digest + memory_state combined
  updated_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (session_id)
);

-- Latest dynamic report (upsert on each turn)
session_dynamic_report (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID        NOT NULL,
  session_id  VARCHAR(64) NOT NULL REFERENCES sessions(session_id),
  chapter_id  VARCHAR(64) NOT NULL,
  report_md   TEXT        NOT NULL,
  updated_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (session_id)
);

-- User-submitted workspace files (OSS-backed)
user_submitted_files (
  id               BIGSERIAL PRIMARY KEY,
  user_id          UUID         NOT NULL REFERENCES users(id),
  session_id       VARCHAR(64)  NOT NULL,
  chapter_id       VARCHAR(64)  NOT NULL,
  filename         VARCHAR(255) NOT NULL,
  oss_key          VARCHAR(500) NOT NULL,
  file_size_bytes  INTEGER      NOT NULL,
  submitted_at     TIMESTAMPTZ  DEFAULT NOW()
);
```

**Per-user OSS quota: 100 MB** (enforced before issuing presigned URLs).

---

## API Endpoints (all under `/v1/`)

| Method | Path | Caller | Purpose |
|--------|------|--------|---------|
| `POST` | `/chapters/{chapter_id}/sessions` | Desktop | Register a new session; returns `session_id` |
| `POST` | `/sessions/{session_id}/turns` | Sidecar | Append one turn |
| `PUT`  | `/sessions/{session_id}/memory` | Sidecar | Upsert latest CA memory state |
| `PUT`  | `/sessions/{session_id}/report` | Sidecar | Upsert latest dynamic report |
| `GET`  | `/chapters/{chapter_id}/session-state` | Desktop | Fetch latest session state (recovery) |
| `POST` | `/storage/workspace/upload-url` | Desktop | Quota check → return OSS presigned PUT URL |
| `POST` | `/storage/workspace/confirm` | Desktop | Record file after direct OSS upload |
| `GET`  | `/storage/workspace/files` | Desktop | List user's submitted files |

### Request / Response shapes

**POST `/chapters/{chapter_id}/sessions`**
```json
Request:  { "course_id": "string" }
Response: { "session_id": "uuid-string", "created_at": "iso8601" }
```

**POST `/sessions/{session_id}/turns`**
```json
{
  "chapter_id": "string",
  "turn_index": 5,
  "user_message": "string",
  "companion_response": "string",
  "turn_outcome": { ... }   // optional
}
Response: 201 Created
```

**PUT `/sessions/{session_id}/memory`**
```json
{
  "chapter_id": "string",
  "memory_json": { ... }    // memo_digest + memory_state dicts merged
}
Response: 200 OK
```

**PUT `/sessions/{session_id}/report`**
```json
{
  "chapter_id": "string",
  "report_md": "# Dynamic Report\n..."
}
Response: 200 OK
```

**GET `/chapters/{chapter_id}/session-state`**
```json
Response: {
  "session_id": "string",
  "turns": [ { "turn_index", "user_message", "companion_response", "turn_outcome", "created_at" }, ... ],
  "memory": { ... },
  "report_md": "string",
  "has_data": true
}
// If no data: { "has_data": false }
```

**POST `/storage/workspace/upload-url`**
```json
Request:  { "chapter_id": "string", "filename": "solution.py", "file_size_bytes": 4096 }
Response: { "presigned_url": "https://...", "oss_key": "user/{id}/workspace/{chapter_id}/solution.py" }
// Error 409 if quota exceeded
```

**POST `/storage/workspace/confirm`**
```json
Request:  { "oss_key": "user/.../solution.py", "filename": "solution.py", "chapter_id": "string", "file_size_bytes": 4096 }
Response: { "quota_used_bytes": 12345678, "quota_limit_bytes": 104857600 }
```

---

## Sidecar Changes

### Session create request (extended)
```python
class CreateSessionRequest(BaseModel):
    chapter_id: str
    course_id: str | None = None
    session_id: str | None = None      # NEW: backend-registered session ID
    backend_url: str | None = None     # NEW: for sync calls
    auth_token: str | None = None      # NEW: JWT forwarded from desktop
```

### Post-turn sync
After `_run_turn()` returns, fire three async best-effort HTTP calls:
```python
async def _sync_turn_to_backend(session, turn_index, user_msg, companion_msg, outcome):
    if not session.backend_url or not session.auth_token:
        return  # sync disabled (local-only mode)
    headers = {"Authorization": f"Bearer {session.auth_token}"}
    base = session.backend_url
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(f"{base}/v1/sessions/{session.session_id}/turns", json={...}, headers=headers)
        await client.put(f"{base}/v1/sessions/{session.session_id}/memory", json={...}, headers=headers)
        await client.put(f"{base}/v1/sessions/{session.session_id}/report", json={...}, headers=headers)
    # All failures are caught and logged — never raised
```

---

## Desktop Changes

### Session create flow (modified)
1. `POST /v1/chapters/{chapter_id}/sessions` → receive `session_id`
2. `POST /api/session/create` to sidecar (include `session_id`, `backend_url`, `auth_token`)

### Recovery flow (when opening a chapter)
1. Check if local session files exist in sidecar's sessions directory
2. If **no local files**: call `GET /v1/chapters/{chapter_id}/session-state`
3. If `has_data: true`:
   - Show `"正在恢复学习记录..."` overlay (skeleton / spinner)
   - Write turns / memory / report to `sessions/{session_id}/` on disk
   - Call `POST /api/session/{session_id}/reattach` on sidecar
   - Hide overlay → student sees restored chat
4. If `has_data: false` → fresh start

### File submit UX
- "Submit" button in code editor panel (beside Run)
- Click → quota-check request → direct OSS PUT → confirm
- Button shows loading state during upload, green "已提交" on success
- Toast error if quota exceeded: `"存储空间不足 (已用 X/100MB)"`
- "已提交文件" section lists files (download available on any device)

---

## Error Handling

| Failure point | Behavior |
|---------------|----------|
| Sidecar sync call fails | Log to `system_events.jsonl`; turn proceeds normally |
| Backend create-session fails | Desktop falls back to local-only mode (no sync) |
| Recovery fetch fails | Fall back to fresh start; show one-time toast warning |
| OSS quota exceeded | Block file submit; show quota info |
| JWT expired during sidecar session | 401 responses logged; sidecar continues locally |

---

## Not Changed

- Existing progress sync (`ChapterProgress`) — unchanged
- Existing analytics sync — unchanged
- Existing bundle delivery flow — unchanged
- Existing sidecar reattach logic — reused as-is for recovery restore step
