# BGM 背景音乐

**说明**：生成视频时会从此目录读取 BGM 并与人声混流。若目录为空，worker 会尝试**自动下载或生成** default.mp3 到容器内（见下方「容器内自动准备」），无需手动放文件也可走混流逻辑。

## 快速启用

1. **本机/挂载**：在本目录放入至少一个 MP3 并命名为 **default.mp3**，即可为所有风格视频启用通用 BGM。
2. **容器内自动准备**：若未放置任何 MP3，worker 会：
   - 优先从环境变量 **BGM_DEFAULT_URL** 指定的 URL 下载 default.mp3 到本目录；
   - 未设置或下载失败时，使用内置示例 URL 尝试下载（可替换为自有链接）；
   - 仍失败则用 ffmpeg 生成一段静音 default.mp3，保证混流流程可跑，您可将该文件替换为真实 BGM。
3. 可选：放入 **tech.mp3**（科技风格）、**blockbuster.mp3**（好莱坞大片风格），在创建任务时选择对应「大片风格」即可优先使用。

## 文件名与用途

| 文件名        | 用途 |
|---------------|------|
| **default.mp3** | 通用 BGM，所有风格均可使用 |
| **tech.mp3**    | 科技风格（`style: "tech"`）优先使用，可选 |
| **blockbuster.mp3** | 好莱坞大片风格（`style: "blockbuster"`）优先使用，建议选用史诗/电影感配乐 |
| **cinematic.mp3** | 电影感 BGM，创建任务时选「电影感 BGM」或传 `bgm: "cinematic"` |
| **upbeat.mp3** | 轻快 BGM，创建任务时选「轻快 BGM」或传 `bgm: "upbeat"` |

- 人声与 BGM 混流比例约 1 : 0.25（BGM 较小声）。
- **请使用无版权/可商用的音乐文件**，可从免版权音乐站下载，例如：
  - [Pixabay Music](https://pixabay.com/music/)
  - [Free Music Archive](https://freemusicarchive.org/)
  - [YouTube Audio Library](https://www.youtube.com/audiolibrary)（需登录）
  - 搜索关键词：cinematic、tech、corporate、ambient 等。

若希望「好莱坞大片」或「科技」风格视频带 BGM，在 `worker/assets/bgm/` 下放入对应 MP3（如 `blockbuster.mp3`、`tech.mp3`、`default.mp3`），并在创建任务时选择对应大片风格或传参 `style: "blockbuster"` / `style: "tech"`。

**独立 BGM 参数**：创建任务时可传 `bgm`（API/Control UI）：`none`=不加 BGM；`default`/`tech`/`blockbuster`/`cinematic`/`upbeat`=指定使用的 BGM 文件（可与画面风格分离）；不传则默认跟随 `style`。

**Docker 部署**：docker-compose 已将 `./worker` 挂载到容器的 `/app`，因此本目录（`worker/assets/bgm/`）在容器内即 `/app/assets/bgm/`。在本机此目录放入或生成 5 个 MP3 后，无需重建镜像，重启 worker 或直接使用即可生效。
