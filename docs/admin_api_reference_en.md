# Knoweia Admin API Reference

> **Version:** 2026-03-13 | **Base URL:** `https://api.knoweia.com` (prod) / `http://47.93.151.131:10723` (dev)

---

## Important: Terminology

Due to legacy naming in the codebase, the internal names differ from the actual educational hierarchy:

| Actual Concept | Internal Name | Description |
|---|---|---|
| **Course** | `course` | A complete course (e.g., "LLM for Social Science") |
| **Part** (book chapter) | `part` | A major section of a course, corresponding to a chapter in the textbook |
| **Chapter** (sub-section) | `chapter` | A specific learning unit within a part |
| **Session** | `session` | A single tutoring conversation within a chapter |

The hierarchy is: **Course > Parts > Chapters > Sessions**

- **Parts** are display-only groupings stored as a JSON array on the course. They contain no content themselves — only a title and an ordered list of chapter IDs.
- **Chapters** are the actual content units. Each chapter has its own bundle (learning materials) and supports multiple tutoring sessions.

---

## Authentication

All admin endpoints require the `X-Admin-Key` header:

```
X-Admin-Key: your-admin-api-key
```

Returns `403 Forbidden` if the key is missing or invalid.

---

## 1. Course Management

### 1.1 List All Courses

```
GET /v1/admin/courses
```

**Response:**
```json
{
  "courses": [
    {
      "id": "uuid",
      "course_code": "COURSE_ABC",
      "title": "Course Title",
      "description": "",
      "instructor": "Prof. Zhang",
      "semester": "2026 Spring",
      "invite_code": "A1B2C3",
      "overview_experience": "",
      "overview_gains": "",
      "overview_necessity": "",
      "overview_journey": "",
      "is_active": true,
      "is_public": false,
      "parts": null,
      "created_at": "2026-03-01T00:00:00+00:00",
      "chapter_count": 5
    }
  ],
  "total": 1
}
```

### 1.2 Create Course

```
POST /v1/admin/courses
```

**Request Body:**
```json
{
  "title": "LLM for Social Science",
  "description": "An introductory course...",
  "instructor": "Prof. Zhang",
  "semester": "2026 Spring",
  "overview_experience": "What prior experience is expected...",
  "overview_gains": "What students will gain...",
  "overview_necessity": "Why this course matters...",
  "overview_journey": "The learning journey overview...",
  "is_active": true,
  "is_public": false,
  "chapters": [
    {
      "chapter_code": "ch01_intro",
      "title": "Introduction",
      "order": 0,
      "intro_text": "Welcome to chapter 1...",
      "is_active": true
    }
  ]
}
```

- `chapters` is optional — you can create a course with no chapters and add them later.
- An `invite_code` is auto-generated for the course.
- `course_code` is auto-generated from the title.

**Response:** `201 Created` — returns `AdminCourseWithChaptersResponse` (see 1.3).

### 1.3 Get Course Detail

```
GET /v1/admin/courses/{course_id}
```

**Response:**
```json
{
  "id": "uuid",
  "course_code": "COURSE_ABC",
  "title": "...",
  "description": "...",
  "instructor": "...",
  "semester": "...",
  "invite_code": "A1B2C3",
  "overview_experience": "...",
  "overview_gains": "...",
  "overview_necessity": "...",
  "overview_journey": "...",
  "is_active": true,
  "is_public": false,
  "parts": [
    { "title": "Part 1: Basics", "chapter_ids": ["uuid-1", "uuid-2"] }
  ],
  "created_at": "...",
  "chapters": [
    {
      "id": "uuid-1",
      "chapter_code": "ch01_intro",
      "title": "Introduction",
      "intro_text": "...",
      "order": 0,
      "is_active": true,
      "has_bundle": true,
      "created_at": "..."
    }
  ]
}
```

### 1.4 Update Course

```
PATCH /v1/admin/courses/{course_id}
```

All fields are optional — only provided fields are updated.

**Request Body:**
```json
{
  "title": "New Title",
  "description": "Updated description",
  "instructor": "Prof. Li",
  "semester": "2026 Fall",
  "is_active": true,
  "is_public": true,
  "overview_experience": "...",
  "overview_gains": "...",
  "overview_necessity": "...",
  "overview_journey": "..."
}
```

**Response:** `AdminCourseWithChaptersResponse` (same as 1.3).

### 1.5 Archive (Deactivate) Course

Use the update endpoint with `is_active: false`:

```
PATCH /v1/admin/courses/{course_id}
```
```json
{ "is_active": false }
```

Archived courses are hidden from students but remain in the database.

### 1.6 Delete Course

```
DELETE /v1/admin/courses/{course_id}?delete_bundles=false
```

- **Hard-deletes** the course, all chapters, enrollments, and chapter progress.
- Set `delete_bundles=true` to also delete associated bundle releases from the database.
- **Irreversible.** Prefer archiving (1.5) unless you truly want to remove all data.

**Response:** `204 No Content`

---

## 2. Chapter Management

### 2.1 Add or Update Chapter

This is an **upsert** — creates the chapter if it doesn't exist, updates it if it does.

```
PUT /v1/admin/courses/{course_id}/chapters/{chapter_code}
```

**Request Body:**
```json
{
  "title": "Introduction to LLM",
  "order": 1,
  "intro_text": "In this chapter, you will learn...",
  "is_active": true
}
```

- `chapter_code` is the permanent identifier (e.g., `ch01_intro`). Cannot be changed after creation.
- `order` controls display sequence (ascending). Use 0, 1, 2... for ordered chapters.
- To reorder chapters, update each chapter's `order` value individually.

**Response:**
```json
{
  "id": "uuid",
  "chapter_code": "ch01_intro",
  "title": "Introduction to LLM",
  "intro_text": "In this chapter, you will learn...",
  "order": 1,
  "is_active": true,
  "has_bundle": false,
  "created_at": "..."
}
```

### 2.2 Update Chapter Intro Text

A convenience endpoint to update only the intro text:

```
PATCH /v1/admin/courses/{course_id}/chapters/{chapter_code}/intro
```
```json
{ "intro_text": "Updated intro text..." }
```

### 2.3 Archive (Deactivate) Chapter

```
DELETE /v1/admin/courses/{course_id}/chapters/{chapter_code}?delete_bundles=false
```

- **Soft-deletes** the chapter (sets `is_active=false`). The chapter is hidden from students.
- To re-activate, use the upsert endpoint (2.1) with `is_active: true`.
- Set `delete_bundles=true` to also delete associated bundle releases.

**Response:** `204 No Content`

---

## 3. Parts Management

Parts are display-only groupings that organize chapters into sections (corresponding to textbook chapters).

### 3.1 Update Parts

Replaces the entire parts configuration for a course.

```
PUT /v1/admin/courses/{course_id}/parts
```

**Request Body:**
```json
{
  "parts": [
    {
      "title": "Introduction",
      "chapter_ids": ["uuid-of-ch01"]
    },
    {
      "title": "Understanding LLMs",
      "chapter_ids": ["uuid-of-ch02", "uuid-of-ch03", "uuid-of-ch04"]
    },
    {
      "title": "Practical Applications",
      "chapter_ids": ["uuid-of-ch05", "uuid-of-ch06"]
    }
  ]
}
```

- `chapter_ids` must be valid chapter UUIDs (from the `id` field in chapter responses).
- The order of the `parts` array determines display order.
- The order of `chapter_ids` within each part determines chapter display order within that part.
- To remove all parts (revert to flat chapter list), send `{ "parts": [] }`.
- A chapter not listed in any part will not appear in the parts-grouped view.

**Response:** `AdminCourseWithChaptersResponse` (same as 1.3).

### 3.2 View Parts

Parts are included in the course detail response:

```
GET /v1/admin/courses/{course_id}
```

The `parts` field will be `null` if no parts are configured, or an array of `{ title, chapter_ids }`.

---

## 4. Bundle Management

Bundles are the actual learning content packages (`.tar.gz` archives) for each chapter.

### 4.1 Upload Chapter Bundle

```
POST /v1/admin/bundles/upload-chapter
Content-Type: multipart/form-data
```

**Form Fields:**
| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | `.tar.gz` archive of chapter content |
| `scope_id` | string | Yes | Chapter UUID (from chapter `id` field) |
| `version` | string | Yes | Semantic version (e.g., `1.0.0`, `1.0.1`) |

**Response:** `201 Created`
```json
{
  "id": "bundle-uuid",
  "bundle_type": "chapter",
  "scope_id": "chapter-uuid",
  "version": "1.0.0",
  "artifact_url": "oss://...",
  "created_at": "..."
}
```

- Each (scope_id, version) pair must be unique. Uploading the same version again will fail.
- To update content, increment the version number.
- The file is uploaded to Aliyun OSS and the SHA256 checksum is computed automatically.

### 4.2 List Bundles

```
GET /v1/admin/bundles?bundle_type=chapter&scope_id={chapter_uuid}&limit=50&offset=0
```

All query parameters are optional:
- `bundle_type`: Filter by type (`chapter`, `app_agents`, `experts`, etc.)
- `scope_id`: Filter by scope (chapter UUID)
- `limit`: 1-200, default 50
- `offset`: default 0

**Response:**
```json
{
  "bundles": [
    {
      "id": "bundle-uuid",
      "bundle_type": "chapter",
      "scope_id": "chapter-uuid",
      "version": "1.0.0",
      "artifact_url": "oss://...",
      "created_at": "..."
    }
  ],
  "total": 1
}
```

### 4.3 Get Bundle Detail

```
GET /v1/admin/bundles/{bundle_id}
```

**Response:**
```json
{
  "id": "bundle-uuid",
  "bundle_type": "chapter",
  "scope_id": "chapter-uuid",
  "version": "1.0.0",
  "artifact_url": "oss://...",
  "sha256": "abc123...",
  "size_bytes": 1048576,
  "is_mandatory": true,
  "manifest_json": {},
  "created_at": "..."
}
```

### 4.4 Delete Bundle

```
DELETE /v1/admin/bundles/{bundle_id}
```

- Deletes the bundle record from the database.
- **Does NOT delete the file from OSS.**

**Response:** `204 No Content`

---

## 5. Student & Enrollment Management

### 5.1 Batch Create Students

```
POST /v1/admin/users/batch
```

**Request Body:**
```json
{
  "users": [
    {
      "email": "student1@example.com",
      "display_name": "Student One",
      "password": "securepass123",
      "invite_codes": []
    },
    {
      "email": "student2@example.com",
      "display_name": "Student Two",
      "password": "securepass456",
      "invite_codes": ["INVITE1"]
    }
  ]
}
```

- If a user with the same email already exists, their display_name and password are updated.
- Users are auto-enrolled in all public courses.
- If `invite_codes` are provided, users are also enrolled in those courses.

**Response:** `201 Created`
```json
{
  "results": [
    {
      "email": "student1@example.com",
      "display_name": "Student One",
      "created": true,
      "enrolled_in": ["Public Course A"]
    }
  ],
  "total": 1
}
```

### 5.2 Enroll Students to Course

```
POST /v1/admin/users/bulk-enroll
```

**Request Body:**
```json
{
  "course_id": "course-uuid",
  "user_ids": ["user-uuid-1", "user-uuid-2"]
}
```

- Set `user_ids` to `null` or omit it to enroll **all active users**.
- Duplicate enrollments are silently skipped.

**Response:**
```json
{
  "enrolled": 5,
  "already_enrolled": 2,
  "course_title": "LLM for Social Science"
}
```

### 5.3 List Users

```
GET /v1/admin/users?status=active
```

**Response:**
```json
{
  "users": [
    {
      "id": "user-uuid",
      "email": "student@example.com",
      "display_name": "Student Name",
      "status": "active"
    }
  ],
  "total": 10
}
```

---

## 6. Invite Codes

### 6.1 Generate Invite Codes

Generate platform-level invite codes (for user registration, not course enrollment):

```
POST /v1/admin/invite-codes/generate
```
```json
{ "count": 100 }
```

**Response:** `201 Created`
```json
{
  "codes": ["ABC123", "DEF456", "..."],
  "count": 100
}
```

### 6.2 List Invite Codes

```
GET /v1/admin/invite-codes?limit=100&offset=0&unused_only=false
```

**Response:**
```json
{
  "codes": [
    {
      "code": "ABC123",
      "created_at": "...",
      "used": false,
      "used_by_email": null,
      "used_at": null
    }
  ],
  "total": 100,
  "used_count": 42
}
```

---

## Typical Teacher Workflow

### Creating a new course from scratch

```
1. POST /v1/admin/courses          → Create course (get course_id, invite_code)
2. PUT  .../chapters/ch01_intro    → Add chapters one by one
3. PUT  .../chapters/ch02_basics
4. PUT  .../parts                  → Organize chapters into parts
5. POST /v1/admin/bundles/upload-chapter  → Upload content bundles per chapter
6. POST /v1/admin/users/bulk-enroll      → Enroll students
```

### Updating an existing course

```
1. PATCH /v1/admin/courses/{id}         → Update course info
2. PUT   .../chapters/{code}            → Add/update chapters
3. PUT   .../parts                      → Reorganize parts
4. POST  /v1/admin/bundles/upload-chapter → Upload new bundle version
```

### Archiving

```
PATCH /v1/admin/courses/{id}  { "is_active": false }    → Archive course
DELETE .../chapters/{code}                                → Archive chapter
```
