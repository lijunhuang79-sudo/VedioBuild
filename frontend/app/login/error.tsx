'use client';

import { useEffect } from 'react';

export default function LoginError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 flex flex-col items-center justify-center p-4 text-white">
      <h2 className="text-xl font-semibold mb-2">登录页异常</h2>
      <p className="text-slate-400 text-sm mb-4 max-w-md text-center">
        {error.message || '加载失败，请重试'}
      </p>
      <button
        onClick={() => reset()}
        className="px-4 py-2 bg-blue-500 rounded-lg hover:bg-blue-600 transition"
      >
        重试
      </button>
      <a href="/login" className="mt-4 text-slate-400 text-sm hover:underline">
        重新打开登录页
      </a>
    </div>
  );
}
