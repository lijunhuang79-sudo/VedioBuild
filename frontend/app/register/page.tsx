'use client';

import { useState } from 'react';
import Link from 'next/link';
import { authApi } from '@/lib/api';

export default function RegisterPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await authApi.register(email, password);
      const token = res?.access_token;
      if (!token) {
        setError('注册返回异常，请重试');
        return;
      }
      localStorage.setItem('token', token);
      window.location.href = '/dashboard';
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '注册失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md p-8 rounded-2xl bg-white/10 backdrop-blur border border-white/20">
        <h1 className="text-2xl font-bold text-center mb-6">免费注册</h1>
        <p className="text-slate-400 text-sm text-center mb-6">
          注册即送 20 次免费视频生成额度
        </p>
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
              minLength={6}
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
            {loading ? '注册中...' : '注册'}
          </button>
        </form>
        <p className="mt-4 text-center text-slate-400 text-sm">
          已有账号？{' '}
          <Link href="/login" className="text-blue-400 hover:underline">
            登录
          </Link>
        </p>
      </div>
    </div>
  );
}
