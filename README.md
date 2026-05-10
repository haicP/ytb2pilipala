# ytb2pilipala

YouTube 到 B 站自动处理工作台。当前 MVP 提供 FastAPI API、React/Vite 工作台、SQLite 持久化和 YouTube 视频下载状态流。

## 本地开发

```bash
conda env create -f environment.yml
conda activate ytb2pilipala
npm --prefix frontend install
```

启动后端：

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

启动前端：

```bash
npm --prefix frontend run dev
```

打开 `http://127.0.0.1:5173/#/dashboard`。

`/dashboard` 是任务处理工作台，用于导入 YouTube 链接或本地视频、查看下载与处理进度、预览资产并执行上传前操作。
`/assistant` 是 AI 配置与辅助页面，用于检查和配置 LLM、Whisper、字幕生成/翻译等 AI 能力所需的运行参数。

## Docker 验证

```bash
docker build -t ytb2pilipala:local .
docker run --rm -p 8000:8000 -v "$PWD/data:/app/data" ytb2pilipala:local
```

打开 `http://127.0.0.1:8000/#/dashboard`。

容器镜像会构建前端静态资源，并由 FastAPI 同进程提供 API 和前端页面。运行时包含 Python 3.12、`ffmpeg`、`yt-dlp`、Node.js、npm 和 `yt-dlp-ejs`。
为兼容 YouTube 近期的 challenge 校验，运行环境还需要可用的 JavaScript runtime，项目默认使用 `Node.js`，并安装 `yt-dlp-ejs`。

## 配置

复制 `.env.example` 为 `.env`，按需设置：

- `API2KEY_BASE_URL`
- `LLM_API_KEY`
- `TTS_PROVIDER`：TTS 接口提供商，支持 `mimo_v2_5_tts` 和 `openai`，默认 `mimo_v2_5_tts`
- `MIMO_API_KEY`：小米 MiMo TTS API Key，用于合成中文配音
- `MIMO_BASE_URL`：小米 MiMo API Base URL，默认 `https://api.xiaomimimo.com/v1`
- `MIMO_TTS_MODEL`：配音模型，默认 `mimo-v2.5-tts-voiceclone`
- `MIMO_TTS_VOICE`：内置音色模型的回退音色，默认 `冰糖`
- `MIMO_TTS_STYLE_PROMPT`：传给 `user` role 的语气/风格指令
- `MIMO_TTS_TIMEOUT_SECONDS`：MiMo 配音请求超时时间，默认 `600`
- `MIMO_TTS_CONCURRENCY`：旧版 MiMo 配音分段并发数；未设置 `TTS_CONCURRENCY` 时作为兼容回退
- `TTS_CONCURRENCY`：TTS 配音分段并发数，默认 `10`，有效范围 `1..50`
- `OPENAI_TTS_API_KEY`：OpenAI TTS API Key；未设置时回退 `OPENAI_API_KEY`
- `OPENAI_API_KEY`：标准 OpenAI API Key，可作为 OpenAI TTS Key 回退
- `OPENAI_TTS_BASE_URL`：OpenAI TTS API Base URL，默认 `https://api.openai.com/v1`
- `OPENAI_TTS_MODEL`：OpenAI TTS 模型，默认 `gpt-4o-mini-tts`
- `OPENAI_TTS_VOICE`：OpenAI TTS 音色，默认 `alloy`
- `OPENAI_TTS_INSTRUCTIONS`：OpenAI TTS 朗读说明词
- `OPENAI_TTS_SPEED`：OpenAI TTS 语速，默认 `1`，有效范围 `0.25..4`
- `LLM_MODEL`：字幕翻译、投稿信息生成等 LLM 任务使用的模型名称
- `WHISPER_MODEL_SIZE`：Whisper/faster-whisper 模型大小，Docker 默认 `small`
- `WHISPER_COMPUTE_TYPE`：Whisper/faster-whisper 推理精度，Docker 默认 `int8`
- `BILIBILI_CREDENTIAL_SOURCE`
- `YOUTUBE_COOKIES_PATH`：YouTube cookies 文件路径，默认 `./data/cookies.txt`

敏感值不要提交到仓库。

正式 YouTube 工作流中的“合成配音”步骤默认使用小米 MiMo TTS voiceclone 模型，也可在设置页切换为 OpenAI 标准音频接口。两组配置分别保存，切换提供商不会清空另一组参数。

MiMo TTS：
- 接口：`POST /v1/chat/completions`
- 认证头：`api-key`
- MiMo 请求格式：非流式 `wav`，从 `message.audio.data` 解 Base64 后解析为 PCM16；避免 MiMo 当前兼容流式响应的 HTTP chunk 解码问题
- 声音样本：从原视频 `audio.wav` 生成 `voice_clone_reference.wav`，作为 `data:audio/wav;base64,$BASE64_AUDIO` 传入 `audio.voice`
- 大小保护：本地只校验 `$BASE64_AUDIO` 纯 Base64 字符串大小，不包含 Data URI 前缀；超过 9.5 MiB 会缩短样本后重新编码，给官方 10 MB 限制留余量

OpenAI TTS：
- 接口：`audio.speech.create`
- 请求格式：`response_format="wav"`，从返回的 WAV 解析为 PCM16
- 参数：`model`、`voice`、`input`、`instructions`、`speed`

通用行为：
- 并发合成：按字幕段并发调用当前 TTS provider，默认并发 `10`；每段完成后更新合成配音步骤进度
- 落地文件：`data/artifacts/<task_id>/zh_voice.wav`
- 预览视频：随后由 `ffmpeg` 合成 `preview.mp4`

Docker 默认挂载 `./data:/app/data`。需要登录态下载 YouTube 视频时，把导出的
`cookies.txt` 放到项目目录的 `data/cookies.txt`，重试任务即可。

### Whisper 模型缓存

Docker 镜像不会在构建阶段下载 faster-whisper 模型，避免每次 `docker compose build`
都重新拉取大文件。容器运行时使用挂载目录 `/app/data/huggingface`，对应宿主机
`./data/huggingface`；只要这个目录存在完整模型缓存，重建镜像和重建容器都会复用。

首次运行前可用一次性容器把模型下载到宿主机挂载目录：

```bash
docker compose run --rm app python -c "from faster_whisper import WhisperModel; WhisperModel('small', compute_type='int8'); print('faster-whisper small ready')"
```

国内网络较慢时，可在 `.env` 设置可用镜像源后再执行上面的命令：

```bash
HF_ENDPOINT=https://hf-mirror.com
```

相关配置：

- `HF_HOME`：HuggingFace 缓存根目录，Docker 默认 `/app/data/huggingface`
- `HF_HUB_CACHE`：模型仓库缓存目录，Docker 默认 `/app/data/huggingface/hub`
- `HF_HUB_DISABLE_XET`：默认 `1`，禁用 Xet 下载路径，降低容器环境兼容风险
- `HF_ENDPOINT`：可选 HuggingFace 镜像源

如果任务日志出现 `n challenge solving failed`、`Only images are available for download` 或
`Requested format is not available`，通常表示当前环境缺少可用的 JavaScript runtime 或
`yt-dlp-ejs`。先确认容器/本机的 `Node.js`、`yt-dlp`、`yt-dlp-ejs` 正常，再重试任务。

## 验证命令

```bash
pytest -q
npm --prefix frontend test
npm --prefix frontend run build
docker build -t ytb2pilipala:local .
docker compose config
```
