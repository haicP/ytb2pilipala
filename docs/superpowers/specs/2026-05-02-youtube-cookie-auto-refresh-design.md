# YouTube Cookie 自动刷新机制设计

## 背景

当前项目已支持通过 `YOUTUBE_COOKIES_PATH` 读取 `cookies.txt` 供 `yt-dlp` 下载 YouTube 视频，但现状仍依赖人工导出并覆盖文件。该方式可以支持短期验证，却无法满足 Docker 生产环境的持续运行要求：

- `cookies.txt` 会过期或被 YouTube 风控拒绝。
- 主下载流程无法主动发现登录态陈旧，只能在任务失败后暴露问题。
- Docker 容器不适合直接依赖宿主浏览器 profile。
- 不应在业务容器中保存 Google 账号密码或实现高风险自动登录。

本设计的目标不是“永不过期”，而是建立一套可持续维护的登录态机制：自动续导 cookies、提前发现失效、失败后有限自动恢复、最终通过人工补登兜底。

## 目标

- 在 Docker 环境中长期维持可用的 YouTube 登录态。
- 保持现有下载器继续消费 `cookies.txt`，尽量减少对业务下载链路的侵入。
- 将“登录态维护”和“视频下载”隔离为不同职责，降低安全与稳定性风险。
- 支持首次人工登录、自动定时刷新、下载前预检、失败后单次补偿刷新、失效后人工补登。
- 在前端和 API 中清晰暴露认证状态、错误摘要和恢复入口。
- 所有日志与接口必须脱敏，不输出 cookie 明文、浏览器 storage 明文或账号密码。

## 非目标

- 不追求完全无人值守的 Google 账号自动登录。
- 不在主应用中存储 Google 账号密码。
- 不依赖宿主浏览器 profile 或宿主机 `--cookies-from-browser` 作为长期方案。
- 不承诺 YouTube 登录态绝对不会过期。
- 不在本阶段引入分布式任务系统，只新增一个独立的认证维护 sidecar。

## 方案选择

评估过三类方案：

1. 专用登录态维护容器 + 共享 `cookies.txt`
2. 下载容器直接绑定浏览器 profile
3. 主应用持有凭据并自动登录 Google

采用方案 1。

选择原因：

- 与当前仓库已接入的 `cookies.txt` 模式兼容，改造成本最低。
- Docker 内可以稳定维护独立浏览器 profile，不受宿主浏览器实现差异影响。
- 业务容器不接触账号密码，安全边界清楚。
- 管理员只需在首次部署或失效后通过受控入口补登，维护成本可控。

不采用方案 2 的原因是 profile 锁、浏览器版本兼容和容器并发读取都更脆弱。不采用方案 3 的原因是 Google 登录风控、2FA 和验证码导致实现成本与风险过高。

## 总体架构

系统新增一个 `youtube-auth-maintainer` sidecar，用于维护 YouTube 登录态。整体结构如下：

```text
FastAPI app
  |
  +-- reads cookies.txt
  +-- reads auth state
  +-- calls maintainer API
  |
  v
shared volume: /app/data/youtube-auth
  |
  +-- profile/
  +-- exports/cookies.txt
  +-- exports/cookies.next.txt
  +-- state/auth-status.json
  +-- locks/
  +-- logs/
  +-- tmp/
  |
  v
youtube-auth-maintainer
  |
  +-- Chromium persistent profile
  +-- inspector
  +-- cookie exporter
  +-- scheduler
  +-- admin noVNC entry
```

核心原则：

- 浏览器持久 profile 是登录态源。
- `cookies.txt` 是供下载器消费的派生副本。
- 主应用只读取状态与副本，不直接操控浏览器内部数据。
- 自动恢复优先基于现有 profile 续导 cookies，无法恢复时才升级到人工补登。

## 容器与部署设计

### app 容器

保留现有 FastAPI + 前端职责，新增：

- 读取共享卷中的 YouTube 认证状态。
- 调用维护容器 API 进行校验、刷新、锁定和解锁。
- 在设置页和下载失败流程中展示认证状态与恢复入口。

### youtube-auth-maintainer 容器

新增 sidecar，内部包含：

- Chromium 持久浏览器进程。
- Xvfb + noVNC，用于管理员首次登录和失效补登。
- Playwright 或 CDP 控制逻辑，用于状态检测与 cookies 导出。
- 定时调度器，用于周期性检查和刷新。
- 内网 HTTP API，仅供 `app` 调用。

推荐使用 `Playwright + Chromium`：

- 可直接读取浏览器上下文中的 cookie。
- 可复用同一浏览器 profile 做自动校验与人工补登。
- 可通过页面状态判断当前是否仍为登录态。

### 共享卷结构

复用现有 `./data` 挂载，在其下新增 `youtube-auth/`：

- `profile/`：Chromium 的 `user-data-dir`
- `exports/cookies.txt`：当前给 `yt-dlp` 使用的正式文件
- `exports/cookies.next.txt`：临时导出文件
- `state/auth-status.json`：sidecar 持久化状态快照
- `locks/refresh.lock`：并发互斥
- `logs/maintainer.log`：脱敏维护日志
- `tmp/`：临时文件

### 环境变量

新增或调整以下配置：

- `YOUTUBE_COOKIES_PATH=./data/youtube-auth/exports/cookies.txt`
- `YOUTUBE_AUTH_STATE_PATH=./data/youtube-auth/state/auth-status.json`
- `YOUTUBE_AUTH_MAINTAINER_URL=http://youtube-auth-maintainer:8081`
- `YOUTUBE_AUTH_REFRESH_INTERVAL_MINUTES=360`
- `YOUTUBE_AUTH_STALE_AFTER_MINUTES=120`
- `YOUTUBE_AUTH_FORCE_REFRESH_AFTER_MINUTES=720`
- `YOUTUBE_AUTH_PROBE_URL=`：可选，供更强的下载前验证
- `YOUTUBE_AUTH_NOVNC_URL=`：可选，用于 UI 展示管理员补登入口

### 访问控制

- `noVNC` 不直接面向公网开放。
- 推荐仅在内网、VPN、SSH 隧道或受限反向代理下访问。
- 如果主应用未来没有管理员鉴权，不直接在前端路由中嵌入 noVNC 页面。

## 认证状态机

YouTube 登录态必须单独建模，不与任务状态混用。定义以下状态：

- `uninitialized`：尚未建立可用登录态。
- `ready`：最近一次校验通过，当前 cookies 可用。
- `refreshing`：正在导出并验证新 cookies。
- `degraded`：刷新失败，但旧 cookies 可能仍可用。
- `reauth_required`：当前登录态已不可自动恢复，需要人工补登。
- `locked`：管理员正在维护会话，自动刷新暂停。

状态流转：

- `uninitialized -> ready`
  首次人工登录成功并导出 cookies。
- `ready -> refreshing`
  定时刷新、下载前强制刷新或手动刷新触发。
- `refreshing -> ready`
  新 cookies 导出成功并验证通过。
- `refreshing -> degraded`
  导出失败，但旧 cookies 尚未被判定失效。
- `degraded -> ready`
  下一次刷新成功。
- `ready/degraded -> reauth_required`
  明确识别到登录态失效或 YouTube 要求重新登录。
- `reauth_required -> locked`
  管理员进入补登流程。
- `locked -> ready`
  补登成功并完成校验与导出。
- `locked -> reauth_required`
  补登退出但修复失败。

## 自动刷新策略

自动刷新采用三层触发，不依赖单一 cron：

### 1. 定时刷新

- 每 6 小时执行一次导出与验证。
- 目的不是追求高频，而是避免长期闲置后突然失效。

### 2. 下载前预检

- 新任务进入 `download_video` 前检查认证状态。
- 若距离上次成功校验超过 2 小时，先做快速校验。
- 若距离上次成功刷新超过 12 小时，先执行强制刷新。

### 3. 失败后补偿刷新

- 当 `yt-dlp` 命中明确认证失效信号时，立即触发一次刷新。
- 刷新成功后仅重试一次下载。
- 若重试仍失败，更新认证状态为 `reauth_required` 或 `degraded`，并结束任务。

## 登录态检测与导出

### 登录态检测

检测逻辑按从轻到重的顺序执行：

1. 读取本地状态快照，判断是否已处于 `reauth_required` 或 `locked`
2. 使用浏览器页面信号快速判断是否存在登录态
3. 可选：对 `YOUTUBE_AUTH_PROBE_URL` 执行一次轻量下载模拟验证

明确的失效信号包括但不限于：

- 页面出现登录按钮或无法访问账号菜单
- `yt-dlp` 返回 `cookies are no longer valid`
- `yt-dlp` 返回 `sign in to confirm`
- `yt-dlp` 返回 `use --cookies-from-browser or --cookies`

### Cookie 导出

导出流程：

1. 从持久 Chromium profile 读取当前 cookie 集合
2. 过滤并转换成 Netscape cookies 格式
3. 写入 `exports/cookies.next.txt`
4. 使用轻量校验确认新文件可用
5. 原子替换正式 `exports/cookies.txt`
6. 更新 `auth-status.json`

必须保证：

- 导出失败时绝不覆盖旧 `cookies.txt`
- 替换时使用原子 rename，避免下载器读到半写入文件
- 日志仅记录行数、时间、状态与错误摘要，不记录 cookie 值

## 维护容器内部模块

### Browser Supervisor

- 启动并保持 Chromium 常驻
- 固定 `user-data-dir`
- 避免多进程并发抢占同一 profile

### Auth Inspector

- 提供快速登录态检测
- 输出结构化状态与错误码

### Cookie Exporter

- 导出与验证 `cookies.txt`
- 负责临时文件写入与原子替换

### Scheduler

- 执行周期性刷新
- 避免并发执行相同刷新作业

### Admin Session API

- 负责人工补登前后的锁定和解锁
- 统一为主应用提供受控入口

## 后端集成设计

### 新增配置

在 [backend/app/config.py](/Users/haic/files/workspace/ytb2pilipala/backend/app/config.py:1) 中扩展 YouTube 认证相关配置。

### 新增客户端

新增 `YouTubeAuthClient`，职责如下：

- 读取当前认证状态
- 触发刷新
- 在需要时申请补登会话信息
- 在补登结束后请求重新校验

客户端只对认证状态和动作建模，不处理下载逻辑细节。

### 下载器接入点

现有 [backend/app/runner/download.py](/Users/haic/files/workspace/ytb2pilipala/backend/app/runner/download.py:1) 继续作为 `yt-dlp` 调用层，但在其外层增加认证预检与有限补偿逻辑：

1. 任务进入 `download_video` 前读取认证状态
2. 若为 `reauth_required`，直接失败并提示管理员补登
3. 若状态陈旧，先请求刷新
4. 调用 `yt-dlp`
5. 命中认证失效特征时，触发一次即时刷新并仅重试一次
6. 若仍失败，更新任务失败状态并同步系统认证状态

### 设置接口扩展

现有 [backend/app/api/settings.py](/Users/haic/files/workspace/ytb2pilipala/backend/app/api/settings.py:1) 中的 `youtube_cookies_file: bool` 仅能表达“文件可用”，不足以反映真实认证状态。建议：

- 保留 `youtube_cookies_file` 作为低层文件健康指标
- 新增独立 `GET /api/youtube-auth` 接口返回结构化认证状态

建议新增接口：

- `GET /api/youtube-auth`
- `POST /api/youtube-auth/refresh`
- `POST /api/youtube-auth/reauth-session`
- `POST /api/youtube-auth/unlock`

## 数据模型设计

认证状态不建议继续存入 `AppSetting` 的松散 key-value。建议新增结构化表 `youtube_auth_state`，字段如下：

- `provider`
- `status`
- `cookies_path`
- `cookies_updated_at`
- `last_check_at`
- `last_refresh_at`
- `last_refresh_result`
- `last_error_code`
- `last_error_summary`
- `locked_by`
- `locked_at`
- `updated_at`

这样可以：

- 让 UI 直接读取结构化字段
- 保留审计所需时间戳和错误码
- 为未来的 B 站凭据状态建模提供一致模式

## 前端设计

### 设置页

在 [frontend/src/pages/SettingsPage.tsx](/Users/haic/files/workspace/ytb2pilipala/frontend/src/pages/SettingsPage.tsx:1) 中新增 `YouTube 登录态` 面板，展示：

- 当前状态徽标
- 最近成功校验时间
- 最近成功刷新时间
- `cookies.txt` 是否存在
- 失败摘要
- 管理员补登入口

操作按钮：

- `立即校验并刷新`
- `打开补登入口`
- `下载诊断信息`

其中诊断信息仅输出脱敏状态快照，不包含 cookie 内容。

### 任务详情页

在下载步骤失败时区分两类提示：

- 自动刷新已触发但仍在处理中
- 已确认需要人工补登

示例文案：

- `检测到 YouTube 登录态可能失效，系统正在自动刷新后重试。`
- `YouTube 登录态已失效，需管理员重新登录专用浏览器会话后重试任务。`

### 任务重试

因认证失败中断的任务允许从 `download_video` 步骤重试，无需整任务重建。

## 安全要求

- 不在主应用或 sidecar 中保存 Google 账号密码。
- 不在普通日志、任务日志、API 返回和前端页面中显示 cookie 明文。
- 不在下载失败错误摘要中暴露请求头、session token 或浏览器存储内容。
- noVNC 入口必须受管理员访问控制。
- 浏览器 profile 目录仅挂载在受信任卷中，不暴露给下载器或用户下载。

## 失败恢复策略

恢复策略按层级执行：

1. 文件级恢复
   导出失败不覆盖旧 `cookies.txt`
2. 会话级恢复
   旧 cookies 失效时先尝试基于现有 profile 刷新
3. 人工补登恢复
   自动恢复失败后进入 `reauth_required`
4. 任务级恢复
   任务从 `download_video` 步骤重试

关键约束：

- 自动补偿重试最多一次
- 进入 `reauth_required` 后暂停自动重试，等待人工处理
- 管理员补登完成后无需重启整个应用

## 验证策略

### 后端

- 为认证状态机添加定向单元测试
- 为 `YouTubeAuthClient` 添加 API mock 测试
- 为下载器添加“预检 + 单次补偿重试”测试
- 为 cookies 原子替换与旧文件保留逻辑添加测试

### 前端

- 为设置页新增认证状态展示测试
- 为任务详情页新增认证失效提示与重试提示测试

### Docker / 集成

- `docker compose config` 验证双容器编排
- 验证首次登录后 `cookies.txt` 能生成
- 验证自动刷新失败不会删除旧 cookies
- 验证 `reauth_required` 状态能在 UI 中清晰显示

### Dry-run / Mock 优先

涉及 YouTube、浏览器、`yt-dlp` 的集成测试优先提供 mock 路径，不要求在 CI 中真实访问外网。

## 验收标准

- 部署后，管理员可以通过专用浏览器容器完成首次登录
- 登录成功后，系统能导出 `yt-dlp` 可用的 `cookies.txt`
- 定时刷新不会中断正在使用的旧 cookies 文件
- 下载前预检能发现登录态陈旧并触发刷新
- `yt-dlp` 命中认证失效时，系统会自动刷新并最多重试一次
- 自动刷新失败后，系统进入 `reauth_required`
- 管理员补登完成后，无需重启即可恢复 `ready`
- 所有日志、接口和 UI 均不暴露敏感认证内容

## 分阶段实施建议

### Phase 1

- 新增 `youtube-auth-maintainer` 容器骨架
- 定义状态文件、API 契约和共享卷目录
- 主应用设置页接入状态展示

### Phase 2

- 实现定时刷新、人工补登入口与 cookies 导出
- 下载前预检与失败后单次补偿重试

### Phase 3

- 完善告警、诊断导出、锁定机制与管理员体验
- 根据真实部署反馈调整刷新阈值与验证策略

## 决策摘要

- 采用独立认证维护 sidecar，而不是把登录逻辑放入主应用
- 采用持久浏览器 profile 作为登录态源，而不是直接依赖宿主浏览器
- 采用导出的 `cookies.txt` 作为下载消费副本，而不是让下载器直接读取 profile
- 采用自动刷新优先、人工补登兜底，而不是高风险的账号密码自动登录
