'use client';

import { useEffect } from 'react';

export default function Error({
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
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-900 text-white p-4">
      <h2 className="text-xl font-semibold mb-2">出错了</h2>
      <p className="text-slate-400 text-sm mb-4 max-w-md text-center">
        {error.message || '页面加载异常'}
      </p>
      <button
        onClick={() => reset()}
        className="px-4 py-2 bg-blue-500 rounded-lg hover:bg-blue-600 transition"
      >
        重试
      </button>
    </div>
  );
}
