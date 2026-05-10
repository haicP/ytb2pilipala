# AI 助手与字幕工作流增强设计

## 背景

当前项目已经具备 YouTube 任务创建、下载视频与缩略图、dry-run 工作流推进、任务详情展示和基础系统设置能力，但 AI 相关能力仍停留在占位阶段：

- `transcribe` 与 `translate` 仍由 `DryRunAdapter` 生成占位字幕。
- `/assistant` 页面只是占位，不承载实际配置。
- 工作流没有真实的源语言检测、字幕翻译跳过、Whisper 时间线对齐与提示词配置能力。

用户本次明确要求：

- 任务目标以完善后端工作流为导向。
- 前端 AI 助手不是聊天页，而是提示词配置页。
- 字幕翻译需要自动检测源语言，目标语言统一为简体中文。
- 若已有简体中文字幕文件，则跳过翻译步骤。
- 需要生成简体中文字幕文件，时间线可以使用 Whisper 对齐。
- 本地测试环境使用 conda 管理的 Python 环境。
- 完成后需要能够打包为 Docker 镜像。

同时，仓库规则要求：

- 工作流步骤必须显式建模。
- 真实媒体依赖和 LLM Key 不得硬编码。
- 页面实现前应参照 `http://127.0.0.1:8096/dashboard/` 的工作台信息架构。

已尝试访问参考工作台，但在 2026-05-04 实际检查时，`http://127.0.0.1:8096/dashboard/` 返回 `ERR_CONNECTION_REFUSED`，本机 `8096` 端口无监听。该状态不阻塞本次后端设计，但会影响后续 `/assistant` 页面最终布局的对齐验收。

## 目标

- 将 `transcribe` 与 `translate` 从 dry-run 占位升级为真实可执行的字幕处理链路。
- 自动检测源语言，并统一生成简体中文字幕产物 `zh.srt`。
- 支持在存在本地或 YouTube 简体中文字幕时跳过 LLM 翻译。
- 将 Whisper/faster-whisper 作为本地转写与时间线对齐的基础能力。
- 为翻译、转写后处理和投稿信息生成提供可配置提示词模板。
- 保持现有任务、步骤、日志、产物和投稿信息模型的连续性，避免推翻现有 UI/API。
- 补齐 conda 与 Docker 运行依赖，使本地与容器环境可追踪、可复现。

## 非目标

- 本次不实现聊天式 AI 助手。
- 本次不实现 B 站真实上传或字幕真实上传。
- 本次不引入分布式任务系统、消息队列或独立 worker。
- 本次不接入 GPU 专属推理链路，默认以 CPU 可运行为基础设计。
- 本次不处理参考工作台不可达带来的视觉验收问题，只记录为已知阻塞。

## 方案选择

本次评估三类方案：

1. 本地 Whisper/faster-whisper 转写 + LLM 翻译 + `/assistant` 提示词配置页
2. 仅补齐翻译，转写继续保留 dry-run
3. 转写与翻译全部依赖外部 API

采用方案 1。

原因：

- 与用户已确认的技术路径一致。
- 能满足“自动检测源语言”和“Whisper 时间线对齐”的要求。
- 能利用当前已有的 `API2KEY_BASE_URL` 与 `LLM_API_KEY` 配置。
- 能与现有步骤模型、任务详情页和 Docker 打包方式自然集成。

不采用方案 2，因为不能满足真实字幕生成目标。不采用方案 3，因为会削弱本地 conda 与 Docker 可复现性，也与用户选定方案不一致。

## 总体架构

系统继续保留单进程任务执行架构，但将现有媒体与 AI 流程拆分成更清晰的适配层：

```text
FastAPI API
  |
  +-- SQLite Repository
  |
  +-- DownloadRunner
  |     |
  |     +-- YtDlpDownloader
  |
  +-- WorkflowRunner
        |
        +-- MediaAdapter
        |     +-- ffmpeg audio extraction
        |
        +-- SubtitleSourceResolver
        |     +-- local subtitle probe
        |     +-- YouTube subtitle probe
        |
        +-- WhisperTranscriber
        |     +-- language detect
        |     +-- segment timeline
        |
        +-- SubtitleTranslator
        |     +-- prompt rendering
        |     +-- LLM client
        |
        +-- SubtitleAligner
        |     +-- segment remap / Whisper timeline alignment
        |
        +-- MetadataGenerator
              +-- metadata prompt rendering
```

关键原则：

- `DownloadRunner` 继续负责视频与缩略图下载。
- 下载完成后，真实工作流 runner 负责后续步骤，不再由 `DryRunAdapter` 贯穿整条链路。
- 每一步仍通过 `TaskStep` 状态、日志和产物表更新，前端无需更换数据读取模型。
- 每个外部能力都通过明确的小组件封装，避免把整条流程写进单个长函数。

## 工作流设计

### 步骤保持不变

任务步骤顺序继续使用既有定义：

1. `import`
2. `download_video`
3. `download_thumbnail`
4. `extract_audio`
5. `transcribe`
6. `translate`
7. `synthesize_voice`
8. `sync_preview`
9. `generate_metadata`
10. `upload_video`
11. `upload_subtitle`

本次只把 `extract_audio`、`transcribe`、`translate`、`generate_metadata` 变成真实逻辑；`synthesize_voice`、`sync_preview`、`upload_video`、`upload_subtitle` 仍可保留当前 dry-run 或跳过模式，但要能消费真实字幕产物。

### `extract_audio`

- 从下载后的视频中提取音频。
- 输出统一音频文件，例如 `audio.wav`。
- 使用 `ffmpeg`，并记录版本信息到日志或 artifact metadata。
- 若音频提取失败，当前步骤标记 `failed`，任务停止。

### `transcribe`

`transcribe` 的职责是生成标准化的源字幕文件与结构化转写结果。

执行顺序：

1. 检查任务目录中是否已有可作为源字幕的文件。
2. 若任务来源为 YouTube，尝试下载源语言字幕或自动字幕。
3. 若仍无源字幕，则对 `audio.wav` 使用 `faster-whisper` 进行转写。
4. 自动检测源语言，并将检测结果写入 metadata。
5. 输出标准化 `source.srt`。
6. 额外输出结构化 `transcript.json`，保存段落级文本、时间线与语言信息。

要求：

- 源语言检测结果必须可追踪，例如 `detected_source_language=en`。
- 即使源字幕来自本地或 YouTube，也需要被规范化为统一的 `source.srt`。
- 若源字幕文件格式为 `vtt` 或 `ass`，需要先转换再落盘。

### `translate`

`translate` 的目标始终是生成简体中文 `zh.srt`。

执行顺序：

1. 检查任务目录是否已有简体中文字幕文件，文件名模式至少覆盖 `zh*.srt`、`zh*.vtt`、`zh*.ass`。
2. 若未命中且任务来源为 YouTube，则尝试下载 `zh-Hans`、`zh-CN`、`zh-SG`、`zh` 等中文字幕。
3. 若命中任一简体中文字幕来源，则：
   - 转换成标准化 `zh.srt`
   - 步骤标记为 `success`
   - 日志记录“跳过 LLM 翻译”的原因
   - artifact metadata 记录 `translation_mode=local_zh_reuse` 或 `youtube_zh_reuse`
4. 若没有现成简体中文字幕，则读取 `source.srt` 与 `transcript.json`，按片段批量调用 LLM 翻译为简体中文。
5. 将翻译结果与原时间线对齐，必要时使用 Whisper 段信息重新映射，输出 `zh.srt`。
6. 额外输出 `translation.json`，保存原文、译文、段落索引与最终时间线。

要求：

- 目标语言固定为简体中文，不提供页面级切换。
- LLM 提示词必须来自提示词配置，不得硬编码在业务函数里。
- 需要做分段或批量翻译，避免单次请求过长。
- 日志中只记录摘要，不输出完整密钥或大段字幕正文。

### Whisper 时间线对齐

本次不要求复杂的 forced alignment 服务，但需要满足“时间线可以用 Whisper 对齐”的目标，设计采用以下方式：

- 如果 `source.srt` 来自 Whisper 转写，则直接复用 Whisper 段时间线。
- 如果 `source.srt` 来自本地或 YouTube，则先解析成段，再与 Whisper 对音频生成的粗粒度分段进行映射。
- 翻译阶段默认保持原段落边界；若出现跨段过长文本，可按源段继续拆分，而不重新生成自由时间轴。

这样可以在不引入额外高复杂度对齐引擎的前提下，保证 `zh.srt` 的时间线来自 Whisper 或被 Whisper 分段校正。

### `generate_metadata`

- 读取任务标题、源语言、字幕摘要和当前中文字幕。
- 使用“投稿信息生成提示词模板”调用 LLM，生成标题、简介、标签建议。
- 写回 `SubmissionMetadata`。
- 若生成失败，不影响前面字幕产物保留，但当前步骤标记 `failed`。

## 任务目录与产物规范

每个任务目录建议统一为 `data/artifacts/<task_id>/`，新增或稳定以下产物：

- `source.mp4`
- `source.jpg`
- `audio.wav`
- `source.srt`
- `zh.srt`
- `transcript.json`
- `translation.json`
- `zh_voice.wav`
- `preview.mp4`

artifact metadata 中需要补充：

- `mode`
- `subtitle_source`
- `detected_source_language`
- `translation_mode`
- `prompt_template_version`
- `whisper_model`

## 配置设计

### 环境变量

敏感项和运行时依赖继续从环境变量读取：

- `API2KEY_BASE_URL`
- `LLM_API_KEY`
- `YOUTUBE_COOKIES_PATH`
- `WHISPER_MODEL_SIZE`
- `WHISPER_COMPUTE_TYPE`

其中：

- `WHISPER_MODEL_SIZE` 默认建议 `small`
- `WHISPER_COMPUTE_TYPE` 默认建议 `int8`

### 非敏感配置

继续使用 `app_settings` 存非敏感配置。本次新增三类提示词模板：

- `assistant_postprocess_prompt`
- `assistant_translation_prompt`
- `assistant_metadata_prompt`

还可补充少量流程参数，例如：

- `subtitle_translation_batch_size`
- `whisper_beam_size`

但首版优先只开放三类提示词模板，避免设置面板膨胀。

## API 设计

### 设置 API

现有 `/api/settings` 主要展示依赖状态和少量运行参数，不适合直接承载长文本模板。新增专用接口更清晰：

- `GET /api/assistant/settings`
- `PATCH /api/assistant/settings`

返回内容：

- 三类提示词模板当前值
- 是否启用默认模板
- 更新时间

约束：

- 模板长度需要限制，例如单项不超过 10_000 字符。
- 接口不返回敏感环境变量值。

### 任务详情 API

现有任务详情结构可复用，但需要在 artifact metadata 和任务日志中暴露更多处理信息。必要时可在 `TaskResponse` 中追加：

- `detected_source_language`
- `subtitle_status_summary`

如果不新增顶层字段，也至少需要保证前端能从 artifact metadata 读取这些信息。

## `/assistant` 页面设计

`/assistant` 明确不是聊天界面，而是 AI 相关模板配置页。

页面职责：

- 编辑“转写后处理提示词”
- 编辑“字幕翻译提示词”
- 编辑“投稿信息生成提示词”
- 展示模板说明、作用范围和保存状态
- 展示当前依赖状态，例如 `LLM Key` 是否已配置

页面结构采用工作台式表单布局，而不是会话流布局：

- 顶部说明卡片：页面用途、适用步骤、依赖状态摘要
- 三个模板卡片：每个卡片包含名称、用途、受影响步骤、文本域、重置默认模板按钮
- 底部保存栏：保存、恢复默认、最近更新时间

由于参考工作台当前不可访问，正式实现时应尽量复用现有 `SettingsPage` 的信息密度、卡片组织与状态展示模式，而不是自行扩展为聊天 UI。

## 依赖与环境设计

### conda 环境

`environment.yml` 需要补齐：

- `python=3.12`
- `ffmpeg`
- `yt-dlp`
- `nodejs=22`
- `pip`
- `faster-whisper`
- `ctranslate2`
- `openai` 或兼容的 HTTP 客户端
- 字幕解析库，例如 `pysubs2` 或 `webvtt-py`

设计原则：

- 本地 conda 环境必须能完整跑通测试与真实字幕链路。
- 若某些包只能通过 pip 安装，应写入 `pip:` 段并在 README 中说明。

### Docker 镜像

Docker 继续采用前端构建 + Python runtime 两阶段结构，但 runtime 层要补齐相同 Python 依赖。

要求：

- 继续包含 `ffmpeg`
- 继续包含 `yt-dlp` 与 `yt-dlp-ejs`
- 继续包含 `nodejs`，以满足 YouTube challenge 处理
- 安装 Whisper/翻译所需 Python 包
- 默认 CPU 运行，不要求 GPU 镜像

镜像必须允许通过环境变量控制 Whisper 模型大小与计算类型，避免默认配置过重。

## 日志与错误处理

每一步要记录结构化摘要，而不是只写笼统字符串。

重点错误分类：

- 依赖缺失：`ffmpeg`、`yt-dlp`、JavaScript runtime、Whisper 模型不可用
- 字幕缺失：本地与 YouTube 都没有字幕，Whisper 转写失败
- LLM 失败：接口不可用、认证失败、超时、返回空翻译
- 对齐失败：字幕解析失败、时间线映射失败

要求：

- 错误摘要写入 `Task.error_summary`
- 步骤错误写入 `TaskStep.error_message`
- 日志可追踪失败来源，但不得泄漏密钥、cookie 或完整敏感请求头

## 测试策略

本次属于真实功能增强，测试至少覆盖 Level 1，并对关键流程使用 TDD。

后端定向测试至少包括：

- 本地已有简体中文字幕时，`translate` 直接复用并生成标准 `zh.srt`
- YouTube 可下载简中字幕时，`translate` 跳过 LLM 翻译
- 无简中字幕时，`translate` 调用 LLM 生成简中字幕
- `transcribe` 使用 Whisper 结果并记录自动检测语言
- `generate_metadata` 使用配置提示词生成投稿信息
- 缺失 `LLM_API_KEY` 或 `API2KEY_BASE_URL` 时给出明确失败摘要

前端测试至少包括：

- `/assistant` 页面正确加载三类模板
- 保存模板后显示更新结果
- 模板页不暴露敏感环境变量

验证命令应覆盖：

- `pytest -q`
- `npm --prefix frontend test`
- `npm --prefix frontend run build`
- `docker build -t ytb2pilipala:local .`

若 Docker build 太重，也至少要保证 `docker compose config` 与单独镜像 build 之一成功，并在实现阶段给出实际结果。

## 风险与边界

### 1. Whisper 性能

CPU 模式下转写速度可能较慢，尤其是长视频。首版需要优先保证可运行与可验证，而不是极致速度。

### 2. 字幕对齐精度

本设计采用“Whisper 分段对齐/校正”而非专业 forced alignment 引擎，能满足工作台级字幕生成要求，但不保证广播级精度。

### 3. 参考工作台不可达

`127.0.0.1:8096` 当前不可访问，前端最终布局对齐只能延后验证。实现阶段需要先按现有工作台风格收敛，待参考页面恢复后再做视觉补差。

### 4. 仓库现有脏工作区

当前仓库已有多处未提交改动。后续实现时必须限定改动边界，只修改与本设计直接相关的文件，不覆盖现有未确认工作。

## 实施边界总结

本次设计的落地范围是：

- 后端新增真实字幕转写、翻译与提示词读取链路
- 前端新增 `/assistant` 配置页，而不是聊天助手
- 补齐 conda 与 Docker 依赖
- 增强定向测试与验证路径

本次不落地：

- 聊天式 AI 助手
- B 站真实上传
- 独立 worker 或分布式调度
- GPU 版 Whisper 运行链路
