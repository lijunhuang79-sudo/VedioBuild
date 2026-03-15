# AI 视频工厂 - 部署与配置指南

## 一、你需要提供的信息

### 1. 基础环境（必填）

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://user:pass@host:5432/dbname` |
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | JWT 签名密钥（生产环境务必更换） | 随机 32 位字符串 |

### 2. 对象存储（必填）

**方案 A：MinIO（自建，推荐开发/小规模）**

- `S3_ENDPOINT_URL`: MinIO 地址，如 `http://localhost:9000`
- `S3_ACCESS_KEY` / `S3_SECRET_KEY`: MinIO 账号
- `S3_BUCKET`: 桶名，如 `ai-videos`

**方案 B：AWS S3**

- `S3_ENDPOINT_URL`: 留空或 `https://s3.amazonaws.com`
- `S3_ACCESS_KEY` / `S3_SECRET_KEY`: AWS Access Key
- `S3_BUCKET`: 你的 S3 桶名
- `S3_REGION`: 如 `us-east-1`

### 3. DeepSeek API（视频文案生成）

| 配置项 | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（必填，用于生成视频字幕文案） |
| `DEEPSEEK_BASE_URL` | 接口地址，默认 `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 模型名，默认 `deepseek-chat`（V3.2） |

> 已接入 DeepSeek V3.2，生成任务时会自动调用以生成短视频文案并写入字幕。

### 4. 支付系统（可选，商业化时配置）

| 配置项 | 说明 |
|--------|------|
| `STRIPE_SECRET_KEY` | Stripe 私钥 |
| `STRIPE_WEBHOOK_SECRET` | Webhook 密钥 |
| `STRIPE_PRICE_*` | 各套餐的 Price ID |

### 5. 域名与访问（生产环境）

| 配置项 | 说明 |
|--------|------|
| `API_BASE_URL` | 后端 API 地址，如 `https://api.your-domain.com` |
| `FRONTEND_URL` | 前端地址，如 `https://your-domain.com` |
| `CORS_ORIGINS` | 允许的跨域来源，逗号分隔 |

---

## 二、快速启动（本地开发）

### 1. 复制环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填写 JWT_SECRET_KEY（可随机生成）
```

### 2. 启动依赖服务

```bash
docker-compose up -d postgres redis minio
```

### 3. 启动后端

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 4. 启动 Worker

```bash
cd worker
pip install -r requirements.txt
# 确保 REDIS_URL、DATABASE_URL、S3 相关环境变量正确
celery -A tasks worker -l info
```

### 5. 启动前端

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### 6. 访问

- 前端: http://localhost:3000
- API 文档: http://localhost:8000/docs

---

## 三、Docker 一键部署

```bash
cp .env.example .env
# 编辑 .env 填入配置
docker-compose up -d
```

---

## 四、GPU 服务器部署（生产视频生成）

当前 MVP 使用 **MoviePy/FFmpeg** 生成占位视频。要接入真实 AI 模型（Stable Video Diffusion、AnimateDiff 等），需要：

1. **GPU 服务器**：至少 1 张 NVIDIA GPU（推荐 24GB+ 显存）
2. **修改 Worker**：在 `worker/tasks.py` 的 `_generate_video_mvp` 中替换为你的模型推理逻辑
3. **Docker GPU**：在 `docker-compose.yml` 中为 worker 启用 GPU（见注释）

---

## 五、成本参考

| 项目 | 月成本 |
|------|--------|
| GPU 服务器 (1×A10) | ~$200 |
| API + DB + Redis | ~$40 |
| **合计** | **~$240** |

约 30 个 $9/月 用户即可覆盖成本。
