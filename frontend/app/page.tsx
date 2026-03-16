'use client';

import { useEffect } from 'react';

/** 首页直接进工作台，未登录则由 dashboard 跳转登录；用 window.location 避免 IP 访问时白屏 */
export default function Home() {
  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.location.replace('/dashboard');
    }
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white">
      <p className="text-slate-400">正在跳转到工作台…</p>
    </div>
  );
}
