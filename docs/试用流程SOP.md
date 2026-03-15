# AI 视频工厂 - 试用流程 SOP

> 标准操作流程：从零到在本地完成一次完整试用（注册 → 生成视频 → 下载）

---

## 一、前置准备

### 1.1 环境要求

| 项目       | 要求说明 |
|------------|----------|
| Python     | 3.9+（推荐 3.10+） |
| Node.js    | 18+ |
| **FFmpeg** | **必须**（本地试用生成视频依赖，无则任务会失败并提示安装） |

### 1.2 项目结构确认

确保在项目根目录下存在：

- `backend/`：FastAPI 后端
- `frontend/`：Next.js 前端
- `worker/`：视频生成任务逻辑
- `.env`：环境变量（可从 `.env.example` 复制）
- `.venv/`：Python 虚拟环境（首次需创建）

---

## 二、首次试用：环境准备（一次性）

### 2.1 创建并激活 Python 虚拟环境

```bash
cd /path/to/VedioBuild
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2.2 安装后端依赖

```bash
pip install -r backend/requirements.txt
```

### 2.3 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

### 2.4 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少设置：
# - JWT_SECRET_KEY（随机字符串）
# - DEEPSEEK_API_KEY（若需 AI 文案生成）
# - 真人配音（可选）：ALIYUN_ACCESS_KEY_ID、ALIYUN_ACCESS_KEY_SECRET、ALIYUN_NLS_APPKEY（阿里云智能语音项目 AppKey）
```

### 2.5 安装 FFmpeg（必须）

本地试用生成视频依赖 FFmpeg，未安装时任务会显示「失败」并提示安装。

```bash
# macOS
brew install ffmpeg
```

若 Homebrew 报目录无写权限，先修复权限再安装：

```bash
sudo chown -R $(whoami) /opt/homebrew /opt/homebrew/Cellar /opt/homebrew/Frameworks /opt/homebrew/bin /opt/homebrew/etc /opt/homebrew/include /opt/homebrew/lib /opt/homebrew/opt /opt/homebrew/sbin /opt/homebrew/share /opt/homebrew/var/homebrew/linked /opt/homebrew/var/homebrew/locks
brew install ffmpeg
```

安装后可用 `ffmpeg -version` 验证。

### 2.6 本地试用模式说明

无需 Docker/Redis/MinIO 时，使用 **SQLite + 进程内 Worker + 本地视频目录**：

- 数据库：`sqlite:///./demo.db`（在 backend 目录下生成）
- 任务执行：当前进程内线程执行，不依赖 Celery/Redis
- 视频文件：保存在 `backend/static/videos/`，通过 `/static/videos/xxx.mp4` 访问

---

## 三、启动服务（每次试用前）

**需要开两个终端**，都在项目根目录 `VedioBuild` 下操作。

### 3.1 推荐：用启动脚本（避免环境变量问题）

**终端一 — 后端：**

```bash
cd /path/to/VedioBuild
source .venv/bin/activate
./scripts/start-backend.sh
```

看到 `Uvicorn running on http://0.0.0.0:8000` 即表示后端已就绪。

**终端二 — 前端：**

```bash
cd /path/to/VedioBuild
./scripts/start-frontend.sh
```

首次运行会先执行一次 `npm run build`，再以生产模式启动；看到 `frontend: http://localhost:3000` 后，在浏览器打开该地址即可（若之前 dev 模式出现 404，改用本脚本即可）。

脚本会自动设置本地试用所需的环境变量（SQLite、进程内 Worker、本地视频目录），并从 `.env` 读取 DeepSeek、JWT 等配置，**避免在 Cursor 等终端里用 `xargs` 加载 .env 失败导致 app 跑不起来**。

### 3.2 手动启动（不用脚本时）

**终端一 — 后端：**

```bash
cd /path/to/VedioBuild
source .venv/bin/activate
export DATABASE_URL="sqlite:///./demo.db" INLINE_WORKER=1 LOCAL_STORAGE=1
export API_BASE_URL="http://localhost:8000" LOCAL_VIDEO_DIR="$PWD/backend/static/videos"
mkdir -p backend/static/videos
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**终端二 — 前端：**

```bash
cd /path/to/VedioBuild/frontend
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

注意：不要用 `export $(grep -v '^#' .env | xargs)`，在某些环境下会报错（如 `xargs: sysconf(_SC_ARG_MAX) failed`），导致变量未生效、后端连错数据库等。

### 3.3 可选：一键脚本

若已配置好依赖，可在项目根目录执行：

```bash
chmod +x scripts/try-local.sh
./scripts/try-local.sh
```

脚本会同时启动后端与前端（按 Ctrl+C 停止）。

---

## 四、试用流程（用户操作）

### 4.1 打开应用

浏览器访问：**http://localhost:3000**

### 4.2 注册账号

1. 点击「免费注册」
2. 输入邮箱、密码（至少 6 位）
3. 点击「注册」  
   → 自动登录并进入仪表盘，默认赠送 20 次额度

### 4.3 生成视频

1. 在「创建视频」区域输入 **视频主题**（如：`PLC 梯形图入门讲解`）
2. 可选：点击「上传图片」选择一张图片
3. 点击「生成视频」  
   → 新任务会立即出现在「我的任务」列表顶部（生成中）；本地试用下通常直接为「生成中」，完成后可下载

### 4.4 查看进度与下载

1. 在「我的任务」列表中查看任务状态  
   - **排队中** / **生成中**：等待几秒，页面会自动轮询刷新  
   - **已完成**：出现「下载视频」按钮  
   - **失败**：可查看错误信息（若后端/worker 有日志）
2. 点击「下载视频」即可下载生成的 MP4

### 4.5 退出登录

点击右上角「退出」，返回登录页。

### 4.6 大片风格与 BGM（可选）

- **大片风格**：在「创建视频」里选择「大片风格」可影响文案语气与画面质感（**好莱坞大片** / 奢华 / 科技 / 自然 / 极简）。
  - **好莱坞大片 · 电影级**：史诗感金句、画面居中大标题、更长转场（0.8s）、更强镜头推进、最低 12 秒；无上传图片时主题海报带「史诗 · 电影级」标签；BGM 优先 `blockbuster.mp3`。
  - **科技**：无上传图片会生成科技感主题海报（青蓝主色、网格线、未来感）；视频至少 10 秒；BGM 优先 `tech.mp3`。
- **BGM**：在项目目录 `worker/assets/bgm/` 下放入 MP3 即可启用背景音乐：
  - `default.mp3`：默认/通用；
  - `tech.mp3`：风格选「科技」时优先；
  - `blockbuster.mp3`：风格选「好莱坞大片」时优先（可选用史诗/电影感配乐）。
  未放置时视频为静音轨或仅 TTS 配音（需配置阿里云智能语音）。
- **真人配音**：需在 `.env` 中配置 `ALIYUN_ACCESS_KEY_ID`、`ALIYUN_ACCESS_KEY_SECRET`、`ALIYUN_NLS_APPKEY`，并在「配音音色」中选择音色；未配置时视频为静音轨 + 可选 BGM。

---

## 五、验证检查点

| 步骤       | 预期结果 |
|------------|----------|
| 后端启动   | 访问 http://localhost:8000/docs 可打开 API 文档 |
| 前端启动   | 访问 http://localhost:3000 可看到首页 |
| 注册       | 提示成功并跳转仪表盘，显示剩余额度 |
| 生成视频   | 任务状态由 排队中 → 生成中 → 已完成 |
| 下载视频   | 可下载 MP4，本地播放正常 |

---

## 六、常见问题

### 6.1 本地终端里 app 跑不起来（必查）

按下面顺序检查：

1. **是否在项目根目录执行？**  
   所有命令都要在 `VedioBuild` 根目录下执行（或先 `cd` 到该目录）。

2. **是否激活了虚拟环境？**  
   终端一启动后端前必须执行：`source .venv/bin/activate`（Windows: `.venv\Scripts\activate`）。

3. **是否开了两个终端？**  
   后端一个终端（端口 8000），前端一个终端（端口 3000），两个都要保持运行。

4. **端口是否被占用？**  
   若提示 `Address already in use`，先关掉占用 8000/3000 的进程，或改用其他端口（见 6.2）。

5. **是否用了脚本？**  
   推荐用 `./scripts/start-backend.sh` 和 `./scripts/start-frontend.sh`，避免手写环境变量或错误使用 `xargs` 加载 `.env` 导致启动失败。

6. **依赖是否装全？**  
   后端：`pip install -r backend/requirements.txt`  
   前端：`cd frontend && npm install`

### 6.2 端口被占用

- 后端 8000 被占用：先结束占用进程（如 `lsof -ti:8000 | xargs kill -9`），或把启动命令中的 `--port 8000` 改为 8001，并设置前端的 `NEXT_PUBLIC_API_URL=http://localhost:8001`
- 前端 3000 被占用：先结束占用进程，或 `npm run dev` 会提示改用 3001 等端口

### 6.3 视频生成失败 / 一直「生成中」

- **未安装 FFmpeg**：任务会失败，并在任务卡片上显示红色错误「未检测到 FFmpeg，请安装: brew install ffmpeg」。请按 2.5 节安装 FFmpeg。
- **一直「生成中」无结果**：看后端终端日志卡在哪一步（DeepSeek / 生成视频 / 上传）；确认 FFmpeg 已安装、环境变量 `LOCAL_STORAGE=1` 与 `LOCAL_VIDEO_DIR` 在启动脚本中已传入。
- DeepSeek 未配置或失败：不影响生成，仅会用主题文本作为字幕。

### 6.4 额度不足

- 试用默认 20 次，用完后提示「额度不足」
- 可重新注册新账号，或直接改数据库/配置中的额度（开发环境）

### 6.5 使用 Docker 的完整环境

若本机已安装 Docker，可改用完整栈（PostgreSQL + Redis + MinIO）：

```bash
cp .env.example .env
# 编辑 .env 后执行：
docker compose up -d postgres redis minio
# 再单独启动 backend、worker、frontend（见 README / DEPLOYMENT.md）
```

---

## 七、附录：相关文档

- 项目说明与快速启动：根目录 `README.md`
- 部署与配置清单：`DEPLOYMENT.md`
- 本 SOP 所在目录：`docs/`

---

---

## 八、启动脚本说明

| 脚本 | 作用 |
|------|------|
| `scripts/start-backend.sh` | 启动后端（SQLite + 进程内 Worker），自动读 .env 中的 DeepSeek、JWT |
| `scripts/start-frontend.sh` | 启动前端（生产模式，避免 dev 的 404），默认请求 http://localhost:8000 |
| `scripts/try-local.sh` | 一次性启动后端+前端（同一脚本内开两个进程） |

首次使用前可执行：`chmod +x scripts/*.sh`

---

*文档版本：v1.1 | 适用项目：AI 视频工厂 商业版 MVP*
