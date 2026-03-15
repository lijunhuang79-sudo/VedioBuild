#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 20 张日常生活/城市/河流山川场景图下载到 worker/assets/scenes/library/，供场景图库调用。
在项目根目录执行: .venv/bin/python -m worker.scripts.download_scene_library
或: .venv/bin/python worker/scripts/download_scene_library.py
"""
import urllib.request
import sys
from pathlib import Path

# 图库目录与 URL 与 tasks.py 保持一致
SCRIPT_DIR = Path(__file__).resolve().parent
LIBRARY_DIR = SCRIPT_DIR.parent / "assets" / "scenes" / "library"
LIBRARY_URLS = [
    "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1556911220-bff31c812dba?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1554118811-1e0d58224f24?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1480714378408-67cf0d13bc1b?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1514565131-fce0801e5785?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?w=1280&h=720&fit=crop",  # 城市楼宇
    "https://images.unsplash.com/photo-1519681393784-d120267933ba?w=1280&h=720&fit=crop",  # 雪山
    "https://images.unsplash.com/photo-1497366216548-37526070297c?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1469474968028-56623f02e42e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1501785888041-af3ef285b470?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1433086966358-54859d0ed716?w=1280&h=720&fit=crop",
]


def download_one(url: str, path: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; VedioBuild/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  失败: {e}")
        return False
    if len(data) < 100:
        return False
    if data[:3] != b"\xff\xd8\xff" and data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def main():
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, url in enumerate(LIBRARY_URLS):
        path = LIBRARY_DIR / f"lib_{i + 1:03d}.jpg"
        if path.exists():
            print(f"已有 lib_{i + 1:03d}.jpg，跳过")
            ok += 1
            continue
        print(f"下载 lib_{i + 1:03d}.jpg ...", end=" ")
        if download_one(url, path):
            print("OK")
            ok += 1
        else:
            print("失败")
    print(f"图库: {ok}/{len(LIBRARY_URLS)} 张，路径 {LIBRARY_DIR}")
    return 0 if ok >= len(LIBRARY_URLS) else 1


if __name__ == "__main__":
    sys.exit(main())
