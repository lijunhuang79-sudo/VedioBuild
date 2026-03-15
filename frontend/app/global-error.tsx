'use client';

import { useEffect } from 'react';

export default function GlobalError({
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
    <html lang="zh-CN">
      <body className="min-h-screen flex flex-col items-center justify-center bg-slate-900 text-white p-4 antialiased">
        <h2 className="text-xl font-semibold mb-2">应用错误</h2>
        <p className="text-slate-400 text-sm mb-4 max-w-md text-center">
          {error.message || '发生错误，请刷新页面重试'}
        </p>
        <button
          onClick={() => reset()}
          className="px-4 py-2 bg-blue-500 rounded-lg hover:bg-blue-600 transition"
        >
          重试
        </button>
      </body>
    </html>
  );
}
