# YouTube 到 B 站自动处理工作台设计

## 背景

项目目标是实现一个自动下载 YouTube 视频、生成与翻译字幕、合成中文配音、生成投稿信息，并上传到 B 站的视频处理工作台。用户要求页面仿照 `http://127.0.0.1:8096/dashboard/`，并使用 `ui-ux-pro-max` 作为页面设计约束。

已观察参考 dashboard 的登录后页面。其主要结构包括左侧固定导航、系统信息、任务概况、提交新视频、最近处理、快捷入口和支持平台。首版应保持这种浅色、高密度、运营工作台式的信息架构，而不是营销页或单一功能页。

## 首版范围

首版采用 MVP 工作台骨架加 mock/dry-run 流程。

包含：
- 可打开的 React/Vite 工作台页面。
- FastAPI 后端 API。
- SQLite 持久化任务、步骤、日志、产物和投稿信息。
- 创建 YouTube 链接或本地视频占位任务。
- 按真实处理步骤推进 dry-run 状态。
- 任务列表、任务详情、日志、产物占位、投稿元数据编辑。
- 系统设置页展示依赖与配置状态。
- conda 本地环境说明与 Docker 运行封装。

不包含：
- 首版不真实调用 YouTube 下载。
- 首版不真实调用 B 站上传。
- 首版不真实调用 LLM、字幕生成或配音服务。
- 首版不引入 Redis、Celery 或分布式 worker。

这些外部能力必须通过 adapter 接口预留，后续能逐步替换 dry-run 实现。

## 技术栈

- 后端：FastAPI。
- 前端：React + Vite。
- 数据库：SQLite。
- 本地开发环境：conda。
- 最终运行环境：Docker。
- 后续外部依赖：`yt-dlp`、`ffmpeg`、`api2key.base_url`、LLM Key、B 站账号或凭据。

## 架构

系统采用单体开发形态：

```text
React/Vite UI
  |
  | HTTP polling
  v
FastAPI API
  |
  +-- SQLite Repository
  |
  +-- In-process Dry-run Runner
        |
        +-- DownloaderAdapter
        +-- MediaAdapter
        +-- SpeechAdapter
        +-- TranslationAdapter
        +-- MetadataAdapter
        +-- BilibiliAdapter
```

FastAPI 提供 API、任务状态、系统指标、设置读取和 dry-run runner。React/Vite 负责仿照参考 dashboard 的工作台界面。SQLite 存储任务、步骤、日志、产物占位路径和投稿元数据。

首版 runner 在 FastAPI 进程内运行。创建任务后写入 SQLite，生成固定步骤列表，再由后台 runner 顺序推进状态。前端通过轮询获取任务详情和日志。后续真实执行耗时增加后，可以将 runner 抽成独立 worker，而不改变 API 和任务模型。

## 视频处理工作流

每个任务固定生成以下步骤：

1. `import`：导入 YouTube 链接或本地视频占位。
2. `download_video`：下载视频。
3. `download_thumbnail`：下载缩略图。
4. `extract_audio`：提取音频。
5. `transcribe`：生成源语言字幕。
6. `translate`：翻译字幕，默认目标语言为中文。
7. `synthesize_voice`：合成中文配音。
8. `sync_preview`：生成音视频同步预览。
9. `generate_metadata`：生成标题、简介、标签等投稿信息。
10. `upload_video`：上传 B 站视频。
11. `upload_subtitle`：上传 B 站字幕。

首版 dry-run runner 必须按这些步骤写入状态、日志和产物占位。这样后续接入真实 `yt-dlp`、`ffmpeg`、LLM 和 B 站上传时，不需要重建前端和 API。

## 页面设计

页面必须使用 `ui-ux-pro-max` 的设计系统检索流程作为参考，但最终视觉优先遵循已观察的参考 dashboard：浅色、高密度、专业、可扫描的 SaaS/运营工作台。

### 全局布局

- 左侧固定导航。
- 主内容区使用卡片式信息分组。
- 卡片圆角、边框、留白与参考 dashboard 保持接近。
- 不使用营销 hero。
- 不使用装饰性大图、渐变球或过重视觉效果。
- 所有表格、任务流、日志区和编辑区必须有稳定尺寸和响应式约束。

### 首页 `/dashboard`

首页包含：
- 系统信息：磁盘剩余、CPU 占用、可用内存。
- 任务概况：视频总数、已完成、处理中、已上传 B 站。
- 提交新视频：输入 YouTube 链接或本地视频路径/文件占位，包含设置和提交按钮。
- 最近处理：展示最近任务和当前步骤。
- 快捷入口：AI 助手、视频库、任务队列、系统设置。
- 支持平台：YouTube、Bilibili、Douyin、TikTok、Twitter/X 等。

提交任务后立即创建任务。首版可以停留在首页并更新最近处理，也可以跳转到任务详情；实施时以更顺畅的体验为准。

### 任务队列 `/dashboard/tasks`

任务队列表格展示：
- 标题。
- 来源类型。
- 当前步骤。
- 总体进度。
- 状态。
- 创建时间。
- 更新时间。
- 操作入口。

操作包括：
- 查看详情。
- 从失败步骤重试。
- 取消未完成 dry-run 任务。

取消只改变状态，不删除任务和产物记录。

### 任务详情 `/dashboard/tasks/:id`

任务详情包含：
- 任务摘要。
- 总体进度。
- 步骤时间线。
- 日志列表。
- 产物列表。
- 字幕和翻译字幕预览占位。
- 配音和同步预览占位。
- 投稿信息编辑区。
- 上传状态。

投稿信息包括标题、简介、标签、分区、封面和 B 站上传返回信息。首版允许编辑，但不真实上传。

### 视频列表 `/dashboard/videos`

视频列表展示已完成或已有产物的任务，提供：
- 预览入口。
- 投稿信息入口。
- 上传状态。
- 对应任务详情入口。

首版用任务生成的 mock 视频记录承载。

### 系统设置 `/dashboard/settings`

设置页展示：
- `yt-dlp` 是否可用。
- `ffmpeg` 是否可用。
- `api2key.base_url` 是否已配置。
- LLM Key 是否已配置。
- B 站账号状态。
- 非敏感配置项。

密钥、cookie、token 不显示明文，不写入日志。首版优先从环境变量读取敏感配置。

## 数据模型

### Task

任务主表。

字段：
- `id`
- `source_type`
- `input`
- `title`
- `status`
- `current_step`
- `progress`
- `error_summary`
- `created_at`
- `updated_at`

### TaskStep

任务步骤表。

字段：
- `id`
- `task_id`
- `name`
- `order`
- `status`
- `progress`
- `started_at`
- `finished_at`
- `error_message`
- `retry_count`

### TaskLog

任务日志表。

字段：
- `id`
- `task_id`
- `step_id`
- `level`
- `message`
- `context`
- `created_at`

### Artifact

产物表。

字段：
- `id`
- `task_id`
- `step_id`
- `artifact_type`
- `path`
- `metadata`
- `created_at`

产物类型包括视频、缩略图、音频、源字幕、翻译字幕、配音、同步预览、封面等。

### SubmissionMetadata

投稿信息表。

字段：
- `id`
- `task_id`
- `title`
- `description`
- `tags`
- `category`
- `cover_artifact_id`
- `visibility`
- `bilibili_video_id`
- `upload_status`
- `updated_at`

### AppSettings

非敏感配置表。

字段：
- `key`
- `value`
- `updated_at`

敏感配置只展示是否已配置和来源，不存明文。

## 状态枚举

任务和步骤共用以下状态：

- `pending`
- `running`
- `success`
- `failed`
- `skipped`
- `cancelled`

任务失败时保留已完成步骤、日志和产物。重试从失败步骤开始，不重跑已成功步骤。

## API 设计

- `GET /api/health`：服务状态。
- `GET /api/system/metrics`：磁盘、CPU、内存。
- `GET /api/settings`：依赖检查与配置状态。
- `PATCH /api/settings`：保存非敏感设置。
- `POST /api/tasks`：创建任务。
- `GET /api/tasks`：任务列表，支持状态、来源、关键词过滤。
- `GET /api/tasks/{id}`：任务详情。
- `POST /api/tasks/{id}/retry`：从失败步骤重试。
- `POST /api/tasks/{id}/cancel`：取消未完成任务。
- `GET /api/tasks/{id}/logs`：日志分页。
- `PATCH /api/tasks/{id}/metadata`：编辑投稿信息。
- `GET /api/videos`：已完成或可投稿视频列表。

前端首版用轮询刷新任务状态，不引入 WebSocket。

## Adapter 边界

首版定义 adapter 接口，但实现 dry-run：

- `DownloaderAdapter`：未来封装 `yt-dlp`。
- `MediaAdapter`：未来封装 `ffmpeg`。
- `SpeechAdapter`：未来接字幕生成和配音。
- `TranslationAdapter`：未来接 LLM 翻译。
- `MetadataAdapter`：未来生成标题、简介、标签。
- `BilibiliAdapter`：未来上传视频和字幕。

每个 adapter 返回结构化结果：
- 是否成功。
- 产物列表。
- 日志列表。
- 耗时。
- 错误信息。

## 错误处理

- 每个步骤单独记录 `status`、`error_message` 和 `retry_count`。
- 失败后任务进入 `failed`。
- `retry` 从失败步骤继续。
- `cancel` 只改变状态，不删除数据。
- 外部命令后续必须使用参数数组或安全封装，禁止拼接不可信 shell 字符串。
- 日志必须脱敏，不能输出 LLM Key、cookie、token 或账号凭据。
- 用户输入的 URL、路径、标题、简介、标签必须校验。

## 环境与配置

本地开发使用 conda：
- 提供 `environment.yml`。
- Python 依赖包含 FastAPI、数据库、测试和开发工具。

前端使用 Node/Vite：
- 提供 `package.json` 和 Vite 配置。
- 前端构建产物由后端或 Docker 镜像统一提供。

Docker：
- 提供 Dockerfile。
- 镜像包含 Python 运行时、前端构建产物、`yt-dlp`、`ffmpeg`。
- 首版 Docker 能运行 API 和静态前端。

配置：
- 提供 `.env.example`。
- `api2key.base_url`、LLM Key、B 站凭据从环境变量或安全配置读取。
- 不提交真实密钥。

## 验证策略

后端测试：
- 模型测试。
- 状态机测试。
- dry-run runner 测试。
- API 测试。

前端测试：
- 提交任务表单。
- 任务列表。
- 任务详情。
- 设置页配置状态展示。

集成测试：
- 启动 API。
- 创建 dry-run 任务。
- 验证任务最终完成。
- 验证步骤、日志、产物和投稿信息生成。

UI 验证：
- 桌面视口。
- 移动视口。
- 无文字溢出。
- 无控件重叠。
- 关键区域非空白。

完成前必须运行与改动范围匹配的验证命令，并在最终说明中记录结果。

## 后续演进

1. 将 `DownloaderAdapter` 替换为真实 `yt-dlp`。
2. 将 `MediaAdapter` 替换为真实 `ffmpeg`。
3. 接入字幕生成、翻译和配音服务。
4. 接入 B 站上传视频和字幕。
5. 将进程内 runner 替换为独立 worker 和队列。
6. 增加订阅频道自动同步。
7. 增加 AI 助手对任务和元数据的自然语言管理。
