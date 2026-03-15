#!/usr/bin/env python3
"""测试即梦文生图配置：请求一张图并保存到 /tmp/jimeng_test.png"""
import os
import sys

# 加载项目 .env（项目根目录）
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
env_path = os.path.join(ROOT, ".env")
if os.path.isfile(env_path):
    from dotenv import load_dotenv
    load_dotenv(env_path)

JIYMENG_IMAGE_API_URL = (os.getenv("JIYMENG_IMAGE_API_URL") or "").rstrip("/")
JIYMENG_IMAGE_API_KEY = os.getenv("JIYMENG_IMAGE_API_KEY", "")
JIYMENG_IMAGE_MODEL = os.getenv("JIYMENG_IMAGE_MODEL", "doubao-seedream-4-0-250828")


def main():
    if not JIYMENG_IMAGE_API_URL or not JIYMENG_IMAGE_API_KEY:
        print("失败：未配置 JIYMENG_IMAGE_API_URL 或 JIYMENG_IMAGE_API_KEY")
        return 1
    print("即梦配置:")
    print("  JIYMENG_IMAGE_API_URL:", JIYMENG_IMAGE_API_URL)
    print("  JIYMENG_IMAGE_MODEL:  ", JIYMENG_IMAGE_MODEL)
    print("  JIYMENG_IMAGE_API_KEY: (已配置，长度 %d)" % len(JIYMENG_IMAGE_API_KEY))

    url = JIYMENG_IMAGE_API_URL
    if "/images/generations" not in url:
        base = url.rstrip("/")
        if "ark" in base and "volces.com" in base:
            url = base + "/api/v3/images/generations"
        else:
            url = base + "/v1/images/generations"
    print("\n请求 URL:", url)

    # 方舟即梦 4.5 要求至少 3686400 像素，用 2K；第三方代理可用 "1280x720"
    payload = {
        "prompt": "广告背景图，咖啡与甜点放在大理石桌面，柔和晨光。风格：cinematic commercial, soft focus。高质量虚化背景，无文字。",
        "model": JIYMENG_IMAGE_MODEL,
        "size": "2K",
        "n": 1,
        "response_format": "url",
    }
    headers = {
        "Authorization": "Bearer %s" % JIYMENG_IMAGE_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        import httpx
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload, headers=headers)
        print("HTTP 状态:", r.status_code)
        if r.status_code != 200:
            print("响应内容:", (r.text or "")[:500])
            return 1
        data = r.json()
        image_url = None
        if isinstance(data.get("data"), list) and len(data["data"]) > 0:
            first = data["data"][0]
            image_url = first.get("url")
            if first.get("b64_json"):
                import base64
                raw = base64.b64decode(first["b64_json"])
                out = "/tmp/jimeng_test.png"
                with open(out, "wb") as f:
                    f.write(raw)
                print("成功：已保存图片（base64）->", out)
                return 0
        if not image_url:
            print("响应中无 url/b64_json。data 示例:", str(data)[:400])
            return 1
        # 下载 URL
        import urllib.request
        req = urllib.request.Request(image_url, headers={"User-Agent": "VedioBuild/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        out = "/tmp/jimeng_test.png"
        with open(out, "wb") as f:
            f.write(raw)
        print("成功：已下载并保存 ->", out)
        return 0
    except Exception as e:
        print("异常:", e)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
