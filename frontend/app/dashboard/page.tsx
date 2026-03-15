'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { authApi, tasksApi, checkBackendHealth, getVideoProxyUrl, TTS_VOICES, VIDEO_STYLES, BGM_OPTIONS, type Task, type User } from '@/lib/api';

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState('');
  const [image, setImage] = useState<File | null>(null);
  const [voice, setVoice] = useState('ruoxi');
  const [style, setStyle] = useState('');
  const [bgm, setBgm] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  const fetchUser = async () => {
    try {
      const u = await authApi.me();
      setUser(u);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes('无法连接服务器')) {
        setError(msg);
        setLoading(false);
        return;
      }
      localStorage.removeItem('token');
      router.replace('/login?expired=1');
    }
  };

  const fetchTasks = async () => {
    try {
      const res = await tasksApi.list();
      setTasks(res.tasks);
      setTotal(res.total);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    if (!token) {
      router.replace('/login');
      return;
    }
    checkBackendHealth().then((ok) => { if (!cancelled) setBackendOk(ok); });
    Promise.all([fetchUser(), fetchTasks()])
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : '加载失败'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [router]);

  // 轮询未完成的任务（每 8 秒一次，减轻后端日志刷屏）
  useEffect(() => {
    const hasPending = tasks.some(
      (t) => t.status === 'pending' || t.status === 'processing'
    );
    if (!hasPending) return;
    const id = setInterval(fetchTasks, 8000);
    return () => clearInterval(id);
  }, [tasks]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!theme.trim()) {
      setError('请输入视频主题');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const created = await tasksApi.create(theme, 'default', image || undefined, voice, style || undefined, bgm || undefined);
      // 乐观更新：立即把新任务插入列表顶部，用户不用等轮询即看到「生成中」
      setTasks((prev) => [created, ...prev.filter((t) => t.task_id !== created.task_id)]);
      setTotal((prev) => prev + 1);
      setTheme('');
      await fetchUser();
      await fetchTasks();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '创建失败';
      setError(msg);
      if (msg.includes('登录已过期') || msg.includes('无效的认证凭据')) {
        localStorage.removeItem('token');
        router.replace('/login?expired=1');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    router.replace('/login');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-2xl text-slate-400">加载中...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      <nav className="border-b border-white/10 bg-slate-900/80 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 py-4 flex justify-between items-center">
          <Link href="/dashboard" className="text-xl font-bold">
            AI 视频工厂
          </Link>
          <div className="flex items-center gap-4">
            <span className="text-slate-400 text-sm">
              剩余额度: <strong className="text-blue-400">{user?.credits ?? 0}</strong>
            </span>
            <button
              onClick={handleLogout}
              className="px-4 py-2 rounded-lg hover:bg-white/10 transition text-sm"
            >
              退出
            </button>
          </div>
        </div>
      </nav>

      {backendOk === false && (
        <div className="max-w-6xl mx-auto px-6 py-2">
          <div className="bg-amber-500/20 border border-amber-500/50 rounded-lg px-4 py-3 flex items-center justify-between gap-4">
            <span className="text-amber-200 text-sm">
              无法连接后端，请确认已在项目根目录执行 <code className="bg-black/30 px-1 rounded">./scripts/start-backend.sh</code>（端口 8000）
            </span>
            <button
              type="button"
              onClick={async () => {
                const ok = await checkBackendHealth();
                setBackendOk(ok);
                if (ok) {
                  setError('');
                  await fetchUser();
                  await fetchTasks();
                }
              }}
              className="shrink-0 px-3 py-1.5 rounded bg-amber-500/30 hover:bg-amber-500/50 text-amber-200 text-sm"
            >
              重试
            </button>
          </div>
        </div>
      )}

      <main className="max-w-6xl mx-auto px-6 py-8">
        <div className="grid md:grid-cols-3 gap-8">
          <div className="md:col-span-2">
            <h2 className="text-xl font-bold mb-1">AI 生成视频</h2>
            <p className="text-slate-500 text-sm mb-4">
              输入主题或上传图片，由 AI 自动生成广告大片：1080p 电影级输出、史诗感镜头与转场、高端文案 + 真人配音，一键生成专业级短视频
            </p>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm text-slate-400 mb-2">
                  视频主题
                </label>
                <input
                  type="text"
                  value={theme}
                  onChange={(e) => setTheme(e.target.value)}
                  placeholder="例如：高端智能手表、新能源汽车、轻奢生活方式"
                  className="w-full px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-2">
                  大片风格
                </label>
                <select
                  value={style}
                  onChange={(e) => setStyle(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
                >
                  {VIDEO_STYLES.map((s) => (
                    <option key={s.value || 'default'} value={s.value} className="bg-slate-800 text-white">
                      {s.label}
                    </option>
                  ))}
                </select>
                <p className="text-slate-500 text-xs mt-1">
                  选「好莱坞大片」得 12 秒+、居中大标题 + 更长转场 + 强镜头推进；选「科技」得科技感画面。
                </p>
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-2">
                  背景音乐 (BGM)
                </label>
                <select
                  value={bgm}
                  onChange={(e) => setBgm(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
                >
                  {BGM_OPTIONS.map((o) => (
                    <option key={o.value || 'follow'} value={o.value} className="bg-slate-800 text-white">
                      {o.label}
                    </option>
                  ))}
                </select>
                <p className="text-slate-500 text-xs mt-1">
                  跟随风格时按「大片风格」选对应 BGM；选「无 BGM」则不加背景音乐。MP3 需放在 worker/assets/bgm/（default / tech / blockbuster / cinematic / upbeat.mp3）
                </p>
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-2">
                  配音音色
                </label>
                <select
                  value={voice}
                  onChange={(e) => setVoice(e.target.value)}
                  className="w-full px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 text-white"
                >
                  {TTS_VOICES.map((v) => (
                    <option key={v.value} value={v.value} className="bg-slate-800 text-white">
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-2">
                  上传图片（选填）
                </label>
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => setImage(e.target.files?.[0] || null)}
                  className="w-full px-4 py-3 rounded-lg bg-slate-800 border border-slate-700 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:bg-blue-500 file:text-white"
                />
                {image && <p className="text-green-400 text-xs mt-1">已选: {image.name}</p>}
              </div>
              {error && <p className="text-red-400 text-sm">{error}</p>}
              <button
                type="submit"
                disabled={submitting || (user?.credits ?? 0) <= 0}
                className="w-full py-3 bg-blue-500 rounded-lg font-medium hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                {submitting ? 'AI 生成中...' : 'AI 生成视频'}
              </button>
            </form>
          </div>

          <div>
            <h2 className="text-xl font-bold mb-4">我的任务</h2>
            <div className="space-y-3 max-h-[500px] overflow-y-auto">
              {tasks.length === 0 ? (
                <p className="text-slate-500 text-sm">暂无任务</p>
              ) : (
                tasks.map((task) => (
                  <TaskCard key={task.task_id} task={task} onRefresh={fetchTasks} />
                ))
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function TaskCard({
  task,
  onRefresh,
}: {
  task: Task;
  onRefresh: () => void;
}) {
  const statusMap: Record<string, string> = {
    pending: '排队中',
    processing: '生成中',
    completed: '已完成',
    failed: '失败',
  };
  const statusColor: Record<string, string> = {
    pending: 'text-yellow-400',
    processing: 'text-blue-400',
    completed: 'text-green-400',
    failed: 'text-red-400',
  };

  const themeDisplay = task.theme.length > 42 ? `${task.theme.slice(0, 42)}…` : task.theme;
  const createdStr = task.created_at
    ? (() => {
        try {
          const d = new Date(task.created_at);
          const sec = (Date.now() - d.getTime()) / 1000;
          if (sec < 60) return '刚刚';
          if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
          if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
          return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        } catch {
          return '';
        }
      })()
    : '';

  return (
    <div className="p-4 rounded-lg bg-slate-800 border border-slate-700">
      <p className="font-medium truncate" title={task.theme}>
        {themeDisplay}
      </p>
      <div className="flex items-center gap-2 mt-1 flex-wrap">
        <span className={`text-sm ${statusColor[task.status]}`}>
          {statusMap[task.status]}
        </span>
        {createdStr && (
          <span className="text-xs text-slate-500">{createdStr}</span>
        )}
      </div>
      {task.status === 'failed' && task.error_message && (
        <p className="text-xs mt-1 text-red-300 break-words">{task.error_message}</p>
      )}
      {task.status === 'completed' && task.video_url && (
        <a
          href={getVideoProxyUrl(task.video_url) ?? task.video_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block px-3 py-1 text-sm bg-blue-500 rounded hover:bg-blue-600 transition"
        >
          下载视频
        </a>
      )}
    </div>
  );
}
