# Netlify 部署说明（解决 Page not found）

## 原因

Next.js 14 使用 **App Router**，路由（如 `/dashboard`、`/login`）由服务端或 Next 运行时处理。  
若 Netlify 只做静态构建、没有用 **Next.js 官方插件**，就只会生成首页，其它路径都会变成 **Page not found**。

## 项目里已完成的配置（你只需推送并部署）

| 文件 | 说明 |
|------|------|
| **根目录 `netlify.toml`** | 指定 `base = "frontend"`、Next 插件，**无需在 Netlify 后台再设 Base directory** |
| **`frontend/netlify.toml`** | 当只部署 frontend 目录时使用 |
| **`frontend/app/not-found.tsx`** | 自定义 404 页 |
| **`frontend/.nvmrc`** | Node 18 |
| **`frontend/.env.netlify.example`** | 环境变量示例 |

## 你需要做的（最少两步）

### 1. 推送代码

```bash
git add .
git commit -m "chore: Netlify PWA and config"
git push
```

### 2. 在 Netlify 重新部署

1. 打开 [Netlify](https://app.netlify.com) → 你的站点（如 melodic-gumption-831f65）。
2. **Deploys** → **Trigger deploy** → **Deploy site**（或等自动部署完成）。
3. 无需改 **Base directory**：根目录的 `netlify.toml` 已写 `base = "frontend"`。

### 3. 若要连自己的后端

在 **Site configuration** → **Environment variables** 里添加：

- **Key**：`NEXT_PUBLIC_API_URL`
- **Value**：你的后端地址，如 `https://你的后端.railway.app` 或 `http://你的服务器IP:8000`

保存后再次 **Trigger deploy**。

## 确认成功

- 构建日志里出现 `@netlify/plugin-nextjs`。
- 访问 `https://melodic-gumption-831f65.netlify.app`、`/login`、`/dashboard` 均正常，不再整站 Page not found。

## 若仍然 404

- 确认推送的代码里包含**根目录**的 `netlify.toml`（带 `base = "frontend"`）。
- 在 Netlify **Build settings** 里不要覆盖 **Base directory**（留空即可）。
- 环境变量里可加 `NODE_VERSION` = `18`。
