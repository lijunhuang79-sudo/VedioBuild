'use client';

import Link from 'next/link';

/** 暂时关闭登录：仅显示暂未开放，恢复时从 git 历史还原表单逻辑 */
export default function LoginPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md p-8 rounded-2xl bg-white/10 backdrop-blur border border-white/20 text-center">
        <h1 className="text-2xl font-bold mb-4">登录</h1>
        <p className="text-slate-400 mb-6">登录功能暂未开放，敬请期待。</p>
        <Link
          href="/"
          className="inline-block py-2 px-4 text-blue-400 hover:underline"
        >
          返回首页
        </Link>
      </div>
    </div>
  );
}
