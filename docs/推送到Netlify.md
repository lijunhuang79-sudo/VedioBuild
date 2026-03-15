# 推送到 GitHub / Netlify

## 1. 仓库已初始化并完成首次提交

- 已在项目根目录执行过 `git init` 和首次 `git commit`。
- 已把本地数据库、上传图片、视频、场景图等加入 `.gitignore`，不会推送到远程。

---

## 两步完成推送（推荐）

### 第一步：在 GitHub 创建空仓库

点下面链接（仓库名已填好，可直接点 Create）：

**https://github.com/new?name=VedioBuild**

- 打开后登录 GitHub（若未登录）。
- Repository name 已是 VedioBuild，可改可不改。
- 不要勾选 “Add a README”，保持空仓库。
- 点 **Create repository**。

### 第二步：在终端执行一条命令

创建好后，在页面上复制仓库的 **HTTPS 地址**（形如 `https://github.com/你的用户名/VedioBuild.git`），在项目根目录执行（把 `<仓库URL>` 换成你复制的地址）：

```bash
cd /Users/huanglijun/Desktop/project/CoursorProject/VedioBuild
./scripts/setup-remote-and-push.sh <仓库URL>
```

示例（用户名为 zhangsan 时）：

```bash
./scripts/setup-remote-and-push.sh https://github.com/zhangsan/VedioBuild.git
```

执行后会添加 origin 并执行 `git push -u origin main`。推送成功后，在 Netlify 里 Import 该仓库即可自动部署。

---

## 2. 添加远程并推送（二选一，不用脚本时）

### 方式 A：推送到 GitHub，再在 Netlify 里连这个仓库

1. 在 [GitHub](https://github.com/new) 新建一个空仓库（不要勾选 “Add a README”）。
2. 在本地项目根目录执行（把 `你的用户名` 和 `仓库名` 换成你的）：

```bash
cd /Users/huanglijun/Desktop/project/CoursorProject/VedioBuild

git remote add origin https://github.com/你的用户名/仓库名.git
git branch -M main
git push -u origin main
```

3. 在 [Netlify](https://app.netlify.com) 里：**Add new site** → **Import an existing project** → 选 **GitHub** → 选刚创建的仓库 → 直接 **Deploy**（根目录的 `netlify.toml` 会自动用 `frontend` 构建）。

### 方式 B：Netlify 用 “Deploy with Git” 并给出仓库地址

1. 在 Netlify 里 **Add new site** → **Import an existing project** → 选 **GitHub**，授权后创建一个新仓库（或选已有仓库）。
2. Netlify 会显示仓库的 Git 地址，例如：  
   `https://github.com/你的用户名/xxx.git`
3. 在本地执行：

```bash
cd /Users/huanglijun/Desktop/project/CoursorProject/VedioBuild

git remote add origin https://github.com/你的用户名/Netlify显示的仓库名.git
git branch -M main
git push -u origin main
```

## 3. 推送时若提示 “not a git repository”

说明当前目录不是 Git 仓库根目录。请先进入项目根目录再执行上面的命令：

```bash
cd /Users/huanglijun/Desktop/project/CoursorProject/VedioBuild
git status
```

若 `git status` 正常，再执行 `git remote add ...` 和 `git push`。

## 4. 推送后

- Netlify 连的是 GitHub 时，每次 `git push` 会自动触发部署。
- 站点地址类似：`https://melodic-gumption-831f65.netlify.app`（以你实际站点为准）。
- 若需连自己的后端，在 Netlify 的 **Site configuration** → **Environment variables** 里添加 `NEXT_PUBLIC_API_URL`。
