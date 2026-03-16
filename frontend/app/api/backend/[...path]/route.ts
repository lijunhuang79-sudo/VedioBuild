/**
 * 代理请求到后端，显式转发 method/body/headers，确保 POST 请求体正确转发（登录等）。
 * 使用必选 catch-all [...path]，避免与页面路由冲突导致 404。
 */
const BACKEND = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, context, 'GET');
}

export async function POST(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, context, 'POST');
}

export async function PUT(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, context, 'PUT');
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, context, 'DELETE');
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxy(request, context, 'PATCH');
}

async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
  method: string
) {
  const { path } = await context.params;
  const pathStr = path.length ? path.join('/') : '';
  const url = new URL(request.url);
  const targetUrl = `${BACKEND.replace(/\/$/, '')}/${pathStr}${url.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k !== 'host' && k !== 'connection') headers.set(key, value);
  });

  let body: string | undefined;
  try {
    body = await request.text();
  } catch {
    body = undefined;
  }

  const res = await fetch(targetUrl, {
    method,
    headers,
    body: body || undefined,
  });

  const resHeaders = new Headers();
  res.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k !== 'transfer-encoding') resHeaders.set(key, value);
  });

  const contentType = res.headers.get('content-type') || '';
  const isBinary =
    contentType.startsWith('video/') ||
    contentType.startsWith('audio/') ||
    contentType.startsWith('image/') ||
    contentType.includes('octet-stream');
  const responseBody = isBinary ? await res.arrayBuffer() : await res.text();

  return new Response(responseBody, {
    status: res.status,
    statusText: res.statusText,
    headers: resHeaders,
  });
}
