# Knoweia 管理端 API 参考文档

> **版本：** 2026-03-13 | **正式环境：** `https://api.knoweia.com` | **开发环境：** `http://47.93.151.131:10723`

---

## 重要说明：术语约定

由于早期设计的历史原因，系统内部命名与实际教学层级存在差异，请特别注意：

| 实际概念 | 系统内部名称 | 说明 |
|---|---|---|
| **课程** | `course` | 一门完整的课程（如"面向社会科学的大模型增强型研究方法"） |
| **章**（教材中的章） | `part` | 课程的大分组，对应教材中的一个章 |
| **节**（章下的具体部分） | `chapter` | 一个章下面的具体学习单元 |
| **会话** | `session` | 一次辅导对话 |

层级关系为：**课程 > 章（part） > 节（chapter） > 会话（session）**

- **章（part）** 仅用于前端分组展示，存储为课程上的 JSON 数组。它本身不包含内容，只有标题和一组有序的节 ID。
- **节（chapter）** 才是实际的内容单元。每个节有自己的内容包（bundle），支持多次辅导会话。

---

## 认证方式

所有管理端接口需要在请求头中携带 `X-Admin-Key`：

```
X-Admin-Key: 你的管理密钥
```

密钥缺失或错误将返回 `403 Forbidden`。

---

## 1. 课程管理

### 1.1 获取课程列表

```
GET /v1/admin/courses
```

**返回示例：**
```json
{
  "courses": [
    {
      "id": "uuid",
      "course_code": "COURSE_ABC",
      "title": "课程标题",
      "description": "",
      "instructor": "张教授",
      "semester": "2026春季",
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

### 1.2 创建课程

```
POST /v1/admin/courses
```

**请求体：**
```json
{
  "title": "面向社会科学的大模型增强型研究方法",
  "description": "课程简介...",
  "instructor": "张教授",
  "semester": "2026春季",
  "overview_experience": "预期学生具备的背景...",
  "overview_gains": "学生将获得...",
  "overview_necessity": "为什么需要这门课...",
  "overview_journey": "学习旅程概览...",
  "is_active": true,
  "is_public": false,
  "chapters": [
    {
      "chapter_code": "ch01_intro",
      "title": "范式转型与学习地图",
      "order": 0,
      "intro_text": "欢迎来到第一节...",
      "is_active": true
    }
  ]
}
```

- `chapters` 是可选的——可以先创建空课程，之后再逐步添加节。
- 系统会自动生成 `invite_code`（课程邀请码）和 `course_code`。

**返回：** `201 Created`，包含完整课程信息和节列表（同 1.3）。

### 1.3 获取课程详情

```
GET /v1/admin/courses/{course_id}
```

**返回示例：**
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
    { "title": "导言", "chapter_ids": ["uuid-1"] },
    { "title": "社会科学应用的起点", "chapter_ids": ["uuid-2", "uuid-3", "uuid-4"] }
  ],
  "created_at": "...",
  "chapters": [
    {
      "id": "uuid-1",
      "chapter_code": "ch01_intro",
      "title": "范式转型与学习地图",
      "intro_text": "...",
      "order": 0,
      "is_active": true,
      "has_bundle": true,
      "created_at": "..."
    }
  ]
}
```

### 1.4 更新课程信息

```
PATCH /v1/admin/courses/{course_id}
```

所有字段均为可选——只更新提供的字段。

**请求体：**
```json
{
  "title": "新标题",
  "description": "更新后的描述",
  "instructor": "李教授",
  "semester": "2026秋季",
  "is_active": true,
  "is_public": true,
  "overview_experience": "...",
  "overview_gains": "...",
  "overview_necessity": "...",
  "overview_journey": "..."
}
```

**返回：** 完整课程信息（同 1.3）。

### 1.5 归档（停用）课程

使用更新接口将 `is_active` 设为 `false`：

```
PATCH /v1/admin/courses/{course_id}
```
```json
{ "is_active": false }
```

归档后的课程对学生不可见，但数据保留在数据库中。

### 1.6 删除课程

```
DELETE /v1/admin/courses/{course_id}?delete_bundles=false
```

- **永久删除**课程及其所有节、选课记录和学习进度。
- 设置 `delete_bundles=true` 可同时删除关联的内容包记录。
- **此操作不可撤销。** 建议优先使用归档（1.5）。

**返回：** `204 No Content`

---

## 2. 节（Chapter）管理

### 2.1 添加或更新节

此接口为 **upsert** 操作——节不存在则创建，已存在则更新。

```
PUT /v1/admin/courses/{course_id}/chapters/{chapter_code}
```

**请求体：**
```json
{
  "title": "范式转型与学习地图",
  "order": 1,
  "intro_text": "本节将带你了解...",
  "is_active": true
}
```

- `chapter_code` 是节的永久标识符（如 `ch01_intro`），创建后不可修改。
- `order` 控制显示顺序（升序排列），使用 0, 1, 2... 即可。
- 若要调整节的顺序，需逐个更新各节的 `order` 值。

**返回：**
```json
{
  "id": "uuid",
  "chapter_code": "ch01_intro",
  "title": "范式转型与学习地图",
  "intro_text": "本节将带你了解...",
  "order": 1,
  "is_active": true,
  "has_bundle": false,
  "created_at": "..."
}
```

### 2.2 更新节简介

仅更新简介文本的便捷接口：

```
PATCH /v1/admin/courses/{course_id}/chapters/{chapter_code}/intro
```
```json
{ "intro_text": "更新后的简介..." }
```

### 2.3 归档（停用）节

```
DELETE /v1/admin/courses/{course_id}/chapters/{chapter_code}?delete_bundles=false
```

- **软删除**——将 `is_active` 设为 `false`，对学生隐藏。
- 如需恢复，使用 upsert 接口（2.1）并设置 `is_active: true`。
- 设置 `delete_bundles=true` 可同时删除关联的内容包记录。

**返回：** `204 No Content`

---

## 3. 章（Part）管理

章（part）是纯展示层的分组，用于将节组织成教材中的章。

### 3.1 更新章分组

整体替换课程的章分组配置。

```
PUT /v1/admin/courses/{course_id}/parts
```

**请求体：**
```json
{
  "parts": [
    {
      "title": "导言",
      "chapter_ids": ["ch01的uuid"]
    },
    {
      "title": "社会科学应用的起点：认识大语言模型",
      "chapter_ids": ["ch02的uuid", "ch03的uuid", "ch04的uuid"]
    },
    {
      "title": "连接社会科学分析与大语言模型",
      "chapter_ids": ["ch05的uuid", "ch06的uuid"]
    }
  ]
}
```

- `chapter_ids` 必须是有效的节 UUID（来自节的 `id` 字段）。
- `parts` 数组的顺序决定章的显示顺序。
- 每个 part 内 `chapter_ids` 的顺序决定节在该章内的显示顺序。
- 发送 `{ "parts": [] }` 可清除所有章分组，恢复为扁平的节列表。
- 未被任何 part 引用的节不会在分组视图中显示。

**返回：** 完整课程信息（同 1.3）。

### 3.2 查看章分组

章分组信息包含在课程详情响应中：

```
GET /v1/admin/courses/{course_id}
```

`parts` 字段为 `null` 表示未配置分组，否则为 `[{ title, chapter_ids }]` 数组。

---

## 4. 内容包（Bundle）管理

内容包是每个节的实际学习内容，打包为 `.tar.gz` 压缩文件。

### 4.1 上传节内容包

```
POST /v1/admin/bundles/upload-chapter
Content-Type: multipart/form-data
```

**表单字段：**
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | 文件 | 是 | `.tar.gz` 格式的内容包 |
| `scope_id` | 字符串 | 是 | 节的 UUID（来自节的 `id` 字段） |
| `version` | 字符串 | 是 | 语义化版本号（如 `1.0.0`、`1.0.1`） |

**返回：** `201 Created`
```json
{
  "id": "bundle-uuid",
  "bundle_type": "chapter",
  "scope_id": "节的uuid",
  "version": "1.0.0",
  "artifact_url": "oss://...",
  "created_at": "..."
}
```

- 同一节的同一版本号不可重复上传，重复会报错。
- 如需更新内容，请递增版本号（如 `1.0.0` → `1.0.1`）。
- 文件会自动上传到阿里云 OSS，并自动计算 SHA256 校验值。

### 4.2 查看内容包列表

```
GET /v1/admin/bundles?bundle_type=chapter&scope_id={节的uuid}&limit=50&offset=0
```

所有查询参数均为可选：
- `bundle_type`：按类型过滤（`chapter`、`app_agents`、`experts` 等）
- `scope_id`：按节的 UUID 过滤
- `limit`：1-200，默认 50
- `offset`：默认 0

**返回：**
```json
{
  "bundles": [
    {
      "id": "bundle-uuid",
      "bundle_type": "chapter",
      "scope_id": "节的uuid",
      "version": "1.0.0",
      "artifact_url": "oss://...",
      "created_at": "..."
    }
  ],
  "total": 1
}
```

### 4.3 查看内容包详情

```
GET /v1/admin/bundles/{bundle_id}
```

**返回：**
```json
{
  "id": "bundle-uuid",
  "bundle_type": "chapter",
  "scope_id": "节的uuid",
  "version": "1.0.0",
  "artifact_url": "oss://...",
  "sha256": "abc123...",
  "size_bytes": 1048576,
  "is_mandatory": true,
  "manifest_json": {},
  "created_at": "..."
}
```

### 4.4 删除内容包

```
DELETE /v1/admin/bundles/{bundle_id}
```

- 仅删除数据库中的记录。
- **不会删除 OSS 上的文件。**

**返回：** `204 No Content`

---

## 5. 学生与选课管理

### 5.1 批量创建学生

```
POST /v1/admin/users/batch
```

**请求体：**
```json
{
  "users": [
    {
      "email": "student1@example.com",
      "display_name": "张三",
      "password": "securepass123",
      "invite_codes": []
    },
    {
      "email": "student2@example.com",
      "display_name": "李四",
      "password": "securepass456",
      "invite_codes": ["INVITE1"]
    }
  ]
}
```

- 如果邮箱已存在，会更新该用户的姓名和密码。
- 用户创建后会自动加入所有公开课程。
- 如果提供了 `invite_codes`，还会加入对应课程。

**返回：** `201 Created`
```json
{
  "results": [
    {
      "email": "student1@example.com",
      "display_name": "张三",
      "created": true,
      "enrolled_in": ["公开课程A"]
    }
  ],
  "total": 1
}
```

### 5.2 批量选课

```
POST /v1/admin/users/bulk-enroll
```

**请求体：**
```json
{
  "course_id": "课程uuid",
  "user_ids": ["用户uuid-1", "用户uuid-2"]
}
```

- `user_ids` 设为 `null` 或不传，将把**所有活跃用户**加入该课程。
- 已选课的用户会被自动跳过。

**返回：**
```json
{
  "enrolled": 5,
  "already_enrolled": 2,
  "course_title": "面向社会科学的大模型增强型研究方法"
}
```

### 5.3 查看用户列表

```
GET /v1/admin/users?status=active
```

**返回：**
```json
{
  "users": [
    {
      "id": "用户uuid",
      "email": "student@example.com",
      "display_name": "张三",
      "status": "active"
    }
  ],
  "total": 10
}
```

---

## 6. 邀请码管理

### 6.1 生成邀请码

生成平台级邀请码（用于用户注册，非课程选课）：

```
POST /v1/admin/invite-codes/generate
```
```json
{ "count": 100 }
```

**返回：** `201 Created`
```json
{
  "codes": ["ABC123", "DEF456", "..."],
  "count": 100
}
```

### 6.2 查看邀请码列表

```
GET /v1/admin/invite-codes?limit=100&offset=0&unused_only=false
```

**返回：**
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

## 典型教师工作流

### 从零创建新课程

```
1. POST /v1/admin/courses                    → 创建课程（获得 course_id 和 invite_code）
2. PUT  .../chapters/ch01_intro              → 逐一添加节
3. PUT  .../chapters/ch02_basics
4. PUT  .../parts                            → 将节组织为章
5. POST /v1/admin/bundles/upload-chapter     → 逐个上传节的内容包
6. POST /v1/admin/users/bulk-enroll          → 将学生加入课程
```

### 更新已有课程

```
1. PATCH /v1/admin/courses/{id}              → 更新课程信息
2. PUT   .../chapters/{code}                 → 添加或更新节
3. PUT   .../parts                           → 重新组织章分组
4. POST  /v1/admin/bundles/upload-chapter    → 上传新版本内容包
```

### 归档操作

```
PATCH /v1/admin/courses/{id}  { "is_active": false }    → 归档课程
DELETE .../chapters/{code}                                → 归档节
```
