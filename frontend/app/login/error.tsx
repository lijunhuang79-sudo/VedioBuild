'use client';

import { useEffect } from 'react';
import Link from 'next/link';

export default function LoginError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Login page error:', error);
  }, [error]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md p-8 rounded-2xl bg-white/10 backdrop-blur border border-white/20 text-center">
        <h2 className="text-xl font-semibold text-white mb-2">登录页出错</h2>
        <p className="text-slate-400 text-sm mb-4">{error.message || '请重试或返回首页'}</p>
        <div className="flex gap-3 justify-center flex-wrap">
          <button
            onClick={() => reset()}
            className="px-4 py-2 bg-blue-500 rounded-lg hover:bg-blue-600 transition text-white"
          >
            重试
          </button>
          <Link
            href="/"
            className="px-4 py-2 border border-white/30 rounded-lg hover:bg-white/10 transition text-white"
          >
            返回首页
          </Link>
        </div>
      </div>
    </div>
  );
}
