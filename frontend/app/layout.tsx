import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI 视频工厂 - 智能视频生成平台',
  description: '上传图片或输入主题，AI 自动生成视频，一键下载发布',
  manifest: '/manifest.json',
  icons: { apple: '/icons/icon-192.png' },
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'AI视频工厂',
  },
  formatDetection: { telephone: false, email: false },
};

export const viewport: Viewport = {
  themeColor: '#1e40af',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
