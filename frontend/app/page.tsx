'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/** 暂时去除注册/登录落地页，方便测试：首页直接进入 dashboard，未登录则由 dashboard 跳转登录 */
export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/dashboard');
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white">
      <p className="text-slate-400">正在跳转到工作台…</p>
    </div>
  );
}
