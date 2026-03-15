'use client';

import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-slate-900 flex flex-col items-center justify-center p-4 text-white">
      <h1 className="text-4xl font-bold mb-2">404</h1>
      <p className="text-slate-400 mb-6">页面不存在</p>
      <Link
        href="/"
        className="px-6 py-3 bg-blue-600 hover:bg-blue-500 rounded-lg transition"
      >
        返回首页
      </Link>
    </div>
  );
}
