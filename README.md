# AI 视频工厂 - 商业版 MVP

> 用户上传图片/输入主题 → AI 自动生成视频 → 自动加字幕 → 用户下载/发布 → 平台收费

## 项目架构

```
frontend/          # Next.js 前端
backend/           # FastAPI API 网关 + 用户系统
worker/            # Celery GPU Worker 视频生成
docker/            # Docker 编排
```

## 快速启动

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose (推荐)
- Redis
- PostgreSQL
- MinIO (对象存储)

### 2. 使用 Docker 一键启动

```bash
# 复制环境变量
cp .env.example .env
# 编辑 .env 填入你的配置

# 启动所有服务
docker-compose up -d

# 访问
# 前端: http://localhost:3000
# API:  http://localhost:8000
# API文档: http://localhost:8000/docs
```

### 3. 本地开发

```bash
# 启动 Redis + PostgreSQL + MinIO
docker-compose up -d redis postgres minio

# 后端
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload

# Worker
cd worker && celery -A tasks worker -l info

# 前端
cd frontend && npm install && npm run dev
```

## 需要配置的信息

**启动前请提供：**

1. **JWT_SECRET_KEY**：随机字符串，用于 Token 签名（生产必改）
2. **数据库**：PostgreSQL 连接串（或用 Docker 默认）
3. **Redis**：连接串（或用 Docker 默认）
4. **对象存储**：MinIO/S3 配置（或用 Docker 默认）

详见 [DEPLOYMENT.md](./DEPLOYMENT.md)

## 风格与 BGM（好莱坞大片 / 科技感 10 秒+ 视频）

1. **若希望有 BGM**：在 `worker/assets/bgm/` 下放入 `default.mp3`、`tech.mp3`、`blockbuster.mp3`、`cinematic.mp3`、`upbeat.mp3`（可从免版权音乐站下载）。项目内已提供 5 段可听占位 BGM（脚本生成），可直接使用或替换为正式配乐；Docker 部署时该目录通过卷挂载进容器，无需拷贝。
2. **好莱坞大片效果**：前端把「大片风格」选为「好莱坞大片 · 电影级」（或 API 传 `style: "blockbuster"`），可得至少 15 秒、史诗感金句、底部字幕、更长转场与更强镜头推进的电影级成片。
3. **科技风格**：选「科技」（`style: "tech"`）可得至少 15 秒、科技感画面 + 可选 BGM 的视频。
4. **从 OpenClaw Control UI 触发**：在任务参数里带上 `style: "blockbuster"` 或 `style: "tech"`；可选 `bgm: "none"`（不加 BGM）、`bgm: "default"` / `"tech"` / `"blockbuster"` / `"cinematic"` / `"upbeat"`（指定 BGM），不传 `bgm` 时默认跟随 `style`。确保对应 BGM 文件已放到上述目录即可。

## 语音 / 字幕 / BGM 优化说明

- **语音（TTS）**：默认语速 -85、音调 +14、音量 60，偏真人化。要**更有感情**可设 `ALIYUN_TTS_VOICE=zhimi_emo`（多情感音色需控制台开通）。可微调：`ALIYUN_TTS_SPEECH_RATE`、`ALIYUN_TTS_PITCH_RATE`、`ALIYUN_TTS_VOLUME`。
- **视频时长**：成片**至少 15 秒**。文案为 50～75 字、配合慢语速 TTS 约 15 秒配音；若语音不足 15 秒会自动补足（后半段画面+BGM）；无配音时固定 15 秒。
- **字幕**：不遮挡画面——半透明底条（alpha≈150）、字号与条高缩小、贴底（距底 56px），好莱坞风格可选居中大标题。
- **BGM**：与视频同长、淡入淡出，音量约 22% 不压人声。
- **背景与场景**：6 场景为**日常生活用品/生活场景**（咖啡、美妆、腕表、包包、家居、美食等），虚化后衬托主题；风格调色+高斯虚化，主题照片略放大+阴影突出主体。

## 即梦（火山引擎）场景图（可选）

若希望 6 张场景背景由 **即梦 AI**（火山引擎/字节）文生图生成，可配置后优先走即梦，失败再回退到默认 Unsplash 图。

**方式一：兼容 OpenAI 的接口（推荐）**

- 火山方舟推理接入点、或第三方代理（如 DMXAPI）通常提供 `POST /v1/images/generations`、Bearer 鉴权。
- 在 worker 所在环境配置：
  - `JIYMENG_IMAGE_API_URL`：完整接口地址，如 `https://open.volcengineapi.com/v1/images/generations` 或 `https://xxx.dmxapi.cn`（若代理自动补 path 可只填域名）。
  - `JIYMENG_IMAGE_API_KEY`：Bearer 密钥（或火山方舟 API Key）。
  - `JIYMENG_IMAGE_MODEL`（可选）：模型名，默认 `doubao-seedream-4-0-250828`；即梦 3 可用 `seedream-3.0`。
- 配置后 worker 在生成 6 场景时会先调用即梦文生图（按主题/风格生成电影感背景），失败则使用默认 URL 下载。

**方式二：仅用默认图**

- 不配置上述变量即可，继续使用项目内置 Unsplash 场景 URL。

## 阿里万相 2.6 文生视频（可选试用）

若希望用 **阿里万相 2.6**（百炼 DashScope）直接文生视频进行试用，可配置后优先走万相，失败再回退到本项目的 MVP 流程（背景图 + TTS + 剪辑）。

- 在 [百炼控制台](https://help.aliyun.com/zh/model-studio/get-api-key) 获取 API Key，并开通万相文生视频（有免费额度）。
- 在 worker 所在环境配置：
  - `DASHSCOPE_API_KEY`：百炼 API Key（必填）。
  - `USE_WANXIANG_VIDEO=true`：启用万相 2.6 试用。
  - `DASHSCOPE_BASE_URL`（可选）：默认 `https://dashscope.aliyuncs.com`，海外可用 `https://dashscope-intl.aliyuncs.com` 等。
- 启用后，生成任务会先用「文案」调用万相 2.6 文生视频（10 秒、720P、自动配音），成功则直接使用该视频；失败或未配置则走 MVP 流程。万相任务约需 1～5 分钟，请耐心等待。
