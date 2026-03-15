/**
 * API 客户端
 * 浏览器端请求同源 /api-backend，由 Next 代理到后端，避免「无法连接服务器」
 */
const API_BASE =
  typeof window !== 'undefined'
    ? '/api-backend'  // 浏览器：同源代理 -> 后端 /api
    : (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000');

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('token');
}

export async function api<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    ...options.headers,
  };
  if (token) {
    (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
  }

  const isFormData = options.body instanceof FormData;
  const isFormUrlEncoded = options.body instanceof URLSearchParams;
  const contentType = (headers as Record<string, string>)['Content-Type'];
  if (!contentType && !isFormData && !isFormUrlEncoded) {
    (headers as Record<string, string>)['Content-Type'] = 'application/json';
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg === 'Failed to fetch' || msg.includes('Load failed') || msg.includes('NetworkError')) {
      const hint = API_BASE.startsWith('/') ? '请确认后端已启动 (http://localhost:8000)' : `请确认后端已启动：${API_BASE}`;
      throw new Error(`无法连接服务器，${hint}`);
    }
    throw e;
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const msg = err.detail || err.message || err.error || '请求失败';
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return res.json();
}

/**
 * 将后端返回的视频 URL 转为通过前端代理访问，便于手机/局域网访问。
 * 例如 http://localhost:8000/static/videos/xxx.mp4 -> /api-backend/static/videos/xxx.mp4
 */
export function getVideoProxyUrl(videoUrl: string | null | undefined): string | null {
  if (!videoUrl?.trim()) return null;
  try {
    const u = new URL(videoUrl, window.location.origin);
    const path = u.pathname;
    if (path.startsWith('/static/videos/')) return `/api-backend${path}`;
    return videoUrl;
  } catch {
    return videoUrl;
  }
}

/** 检查后端是否可连接（用于仪表盘显示状态） */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const base = typeof window !== 'undefined' ? '/api-backend' : (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000');
    const r = await fetch(`${base}/health`);
    return r.ok;
  } catch {
    return false;
  }
}

// 认证
export const authApi = {
  register: (email: string, password: string) =>
    api<{ access_token: string; user: User }>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    api<{ access_token: string; user: User }>('/api/auth/login-json', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => api<User>('/api/auth/me'),
};

/** 可选配音音色（阿里云 TTS），优先推荐自然/多情感音色，减少 AI 感 */
export const TTS_VOICES = [
  { value: 'ruoxi', label: '若兮 · 温柔自然（推荐）' },
  { value: 'zhimi_emo', label: '知米 · 多情感女声（推荐）' },
  { value: 'zhiyan_emo', label: '知燕 · 多情感直播' },
  { value: 'zhitian_emo', label: '知甜 · 多情感甜美' },
  { value: 'siyue', label: '思悦 · 温柔女声' },
  { value: 'aiyu', label: '艾雨 · 自然女声' },
  { value: 'rosa', label: 'Rosa · 自然女声' },
  { value: 'zhijia', label: '知佳 · 超高清女声' },
  { value: 'zhiqi', label: '知琪 · 温柔超高清' },
  { value: 'zhixiaoxia', label: '知小夏 · 甜美可爱' },
  { value: 'xiaomei', label: '小美 · 甜美女声' },
  { value: 'xiaoyun', label: '小云 · 标准女声' },
  { value: 'sicheng', label: '思诚 · 男声' },
  { value: 'xiaogang', label: '小刚 · 标准男声' },
  { value: 'zhifeng_emo', label: '知锋 · 多情感男声' },
] as const;

/** 广告大片风格：影响文案语气与画面质感 */
export const VIDEO_STYLES = [
  { value: '', label: '默认 · 高端品牌感' },
  { value: 'blockbuster', label: '好莱坞大片 · 电影级' },
  { value: 'luxury', label: '奢华 · 金句质感' },
  { value: 'tech', label: '科技 · 简洁专业' },
  { value: 'nature', label: '自然 · 温暖治愈' },
  { value: 'minimal', label: '极简 · 留白高级' },
] as const;

/** 背景音乐：跟随风格 / 无 / 指定 BGM 文件（需在 worker/assets/bgm/ 放置对应 MP3） */
export const BGM_OPTIONS = [
  { value: '', label: '跟随大片风格' },
  { value: 'none', label: '无 BGM' },
  { value: 'default', label: '通用 BGM (default.mp3)' },
  { value: 'tech', label: '科技 BGM (tech.mp3)' },
  { value: 'blockbuster', label: '好莱坞大片 BGM (blockbuster.mp3)' },
  { value: 'cinematic', label: '电影感 BGM (cinematic.mp3)' },
  { value: 'upbeat', label: '轻快 BGM (upbeat.mp3)' },
] as const;

// 任务
export const tasksApi = {
  create: (theme: string, template: string, image?: File, voice?: string, style?: string, bgm?: string) => {
    const form = new FormData();
    form.append('theme', theme);
    form.append('template', template);
    if (voice) form.append('voice', voice);
    if (style) form.append('style', style);
    if (bgm) form.append('bgm', bgm);
    if (image) form.append('image', image);
    return api<Task>('/api/tasks', {
      method: 'POST',
      body: form,
    });
  },
  get: (taskId: string) => api<Task>(`/api/tasks/${taskId}`),
  list: (skip = 0, limit = 20) =>
    api<{ tasks: Task[]; total: number }>(`/api/tasks?skip=${skip}&limit=${limit}`),
};

export interface User {
  id: number;
  email: string;
  plan: string;
  credits: number;
  created_at: string;
}

export interface Task {
  id: number;
  task_id: string;
  theme: string;
  template: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  video_url: string | null;
  error_message?: string | null;
  created_at: string;
}
