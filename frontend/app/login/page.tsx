'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { authApi } from '@/lib/api';

function LoginForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (searchParams.get('expired') === '1') {
      setError('登录已过期，请重新登录');
    }
  }, [searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await authApi.login(email, password);
      const token = res?.access_token;
      if (!token) {
        setError('登录返回异常，请重试');
        return;
      }
      localStorage.setItem('token', token);
      window.location.href = '/dashboard';
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err ?? '登录失败');
      setError(msg || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md p-8 rounded-2xl bg-white/10 backdrop-blur border border-white/20">
        <h1 className="text-2xl font-bold text-center mb-6">登录</h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-300 mb-1">邮箱</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>
          <div>
            <label className="block text-sm text-slate-300 mb-1">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
          </div>
          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-blue-500 rounded-lg font-medium hover:bg-blue-600 disabled:opacity-50 transition"
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
        <p className="mt-4 text-center text-slate-400 text-sm">
          还没有账号？{' '}
          <Link href="/register" className="text-blue-400 hover:underline">
            先注册
          </Link>
        </p>
        <p className="mt-2 text-center text-slate-500 text-xs">
          请确认后端已启动（如 scripts/start-backend.sh）
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 flex items-center justify-center">
        <span className="text-slate-400">加载中...</span>
      </div>
    }>
      <LoginForm />
    </Suspense>
  );
}
