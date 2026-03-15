/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 代理：/api-backend/* -> 后端 /api/*，浏览器同源请求，避免「无法连接服务器」
  async rewrites() {
    const target = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    return [{ source: '/api-backend/:path*', destination: `${target}/:path*` }];
  },
};

module.exports = nextConfig;
