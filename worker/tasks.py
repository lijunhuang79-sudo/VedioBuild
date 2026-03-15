"""
AI 视频生成 Celery 任务
目标：商用好莱坞大片感广告片，主题突出、画面优美、字幕清晰、卡点准确，可落地商用。
故事化广告：拍广告如讲故事，主题融入故事，每镜对应故事情节并抓取/生成相匹配的背景图嵌入。

出厂策略：
- 输出 1080p、高码率（CRF16/8M）、电影感镜头（缓 zoom + 轻 pan）、风格化暗角
- 文案：DeepSeek 生成故事化 6 镜方案（旁白 + 6 个场景视觉描述），使情节与画面一致
- 背景：每镜按故事情节描述生成/选取背景图（即梦或 URL），虚化衬托主题；抠图主体放大+双层阴影 3D 感
- 字幕：贴底、无黑底条、多行完整；按段与语音/镜头严格对齐
- 语音：语速放慢、逗号处加 1 秒停顿、句间 1 秒静音；文案 5～8 句 80～120 字，分 6 镜
- BGM 淡入淡出与视频起止对齐；视频至少 15 秒（不足则补足）
"""
from typing import Optional, Any
import io
import os
import sys
import uuid
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("worker")

# 添加 backend 到 path 以便导入配置
sys.path.insert(0, str(Path(__file__).parent.parent))

# 尽早注册 HEIC 支持，便于后续 PIL 打开 .heic（内联 worker 使用 backend 依赖）
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 从环境变量读取配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_video_factory"
)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
S3_ACCESS = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET", "ai-videos")

# DeepSeek API（兼容 OpenAI 接口）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 阿里云 智能语音合成 TTS（真人配音）
ALIYUN_ACCESS_KEY_ID = os.getenv("ALIYUN_ACCESS_KEY_ID", "")
ALIYUN_ACCESS_KEY_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET", "")
ALIYUN_NLS_APPKEY = os.getenv("ALIYUN_NLS_APPKEY", "")
ALIYUN_NLS_REGION = os.getenv("ALIYUN_NLS_REGION", "cn-shanghai")
_NLS_TOKEN_CACHE: Optional[str] = None
_NLS_TOKEN_EXPIRY: float = 0

# 即梦（火山引擎/字节）文生图：6 镜背景首选，与故事情节一致；未配置或失败时用 URL 图库备用。
# 支持兼容 OpenAI 的接口：JIYMENG_IMAGE_API_URL + JIYMENG_IMAGE_API_KEY（Bearer）
# 或火山方舟推理接入点。模型如 doubao-seedream-4-0-250828、seedream-3.0
JIYMENG_IMAGE_API_URL = (os.getenv("JIYMENG_IMAGE_API_URL") or "").rstrip("/")
JIYMENG_IMAGE_API_KEY = os.getenv("JIYMENG_IMAGE_API_KEY", "")
JIYMENG_IMAGE_MODEL = os.getenv("JIYMENG_IMAGE_MODEL", "doubao-seedream-4-0-250828")
JIYMENG_ENABLED = bool(JIYMENG_IMAGE_API_URL and JIYMENG_IMAGE_API_KEY)
# 是否优先即梦（默认 1）；设为 0 可跳过即梦、直接用 URL 备用
PREFER_JIMENG_SCENE = os.getenv("PREFER_JIMENG_SCENE", "1").strip() in ("1", "true", "yes")

# 阿里万相 2.6 文生视频（DashScope 百炼）：可选试用，生成后直接返回视频路径
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
WANXIANG_VIDEO_ENABLED = os.getenv("USE_WANXIANG_VIDEO", "").strip().lower() in ("1", "true", "yes")
WANXIANG_VIDEO_BASE = (os.getenv("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com").rstrip("/")

celery_app = Celery(
    "ai_video_factory",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
)


@celery_app.task(bind=True, name="worker.tasks.generate_video_task")
def generate_video_task(
    self,
    task_id: str,
    user_id: int,
    theme: str,
    template: str = "default",
    image_url: Optional[str] = None,
    image_path: Optional[str] = None,
    voice: Optional[str] = None,
    style: Optional[str] = None,
    bgm: Optional[str] = None,
):
    """
    生成视频任务
    
    MVP: 生成带字幕的占位视频
    生产: 接入 SVD/AnimateDiff 等模型
    """
    from sqlalchemy import text

    logger.info("Worker 开始: task_id=%s theme=%s", task_id, theme[:30] if theme else "")
    _url = DATABASE_URL
    if _url.startswith("sqlite"):
        engine = create_engine(
            _url,
            connect_args={"check_same_thread": False, "timeout": 15},
        )
    else:
        _url = _url.replace("postgresql://", "postgresql+psycopg2://")
        engine = create_engine(_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        db.execute(
            text("UPDATE video_tasks SET status = 'processing' WHERE task_id = :task_id"),
            {"task_id": task_id},
        )
        db.commit()
        logger.info("Worker 状态已更新为 processing")

        logger.info("Worker 使用故事化广告 Skill 生成视频（故事文案 → 抓取对应背景图 → 嵌入每镜）...")
        output_path = None
        if WANXIANG_VIDEO_ENABLED and DASHSCOPE_API_KEY:
            story = _generate_story_script_with_deepseek(theme=theme, style=style)
            script_text = story.get("script") or theme[:200]
            output_path = _generate_video_wanxiang(theme=theme, script_text=script_text, style=style)
        if not output_path:
            try:
                from worker.story_ad_skill import run_story_ad_skill
                output_path = run_story_ad_skill(
                    theme=theme,
                    image_path=image_path,
                    image_url=image_url,
                    voice=voice,
                    style=style,
                    bgm=bgm,
                )
            except ImportError:
                story = _generate_story_script_with_deepseek(theme=theme, style=style)
                script_text = story.get("script") or _generate_script_with_deepseek(theme=theme, image_url=image_url, style=style)
                scene_descriptions = story.get("scenes") if isinstance(story.get("scenes"), list) and len(story.get("scenes", [])) >= 6 else None
                output_path = _generate_video_mvp(
                    theme=theme, script_text=script_text, image_url=image_url, image_path=image_path,
                    voice=voice, style=style, bgm=bgm, scene_descriptions=scene_descriptions,
                )

        logger.info("Worker 上传视频...")
        video_url = _upload_to_s3(output_path, user_id)

        # 清理临时文件
        if output_path and os.path.exists(output_path):
            os.remove(output_path)

        # 更新任务完成
        db.execute(
            text("""
                UPDATE video_tasks 
                SET status = 'completed', 
                    video_url = :video_url,
                    completed_at = :completed_at
                WHERE task_id = :task_id
            """),
            {
                "task_id": task_id,
                "video_url": video_url,
                "completed_at": datetime.utcnow(),
            },
        )
        db.commit()

        return {"status": "completed", "video_url": video_url}

    except Exception as e:
        logger.exception("Worker 失败: %s", e)
        err_msg = str(e)[:500]
        try:
            db.execute(
                text("UPDATE video_tasks SET status = 'failed', error_message = :error WHERE task_id = :task_id"),
                {"task_id": task_id, "error": err_msg},
            )
            db.commit()
        except Exception as e2:
            logger.exception("Worker 更新失败状态时出错: %s", e2)
    finally:
        db.close()
        logger.info("Worker 结束: task_id=%s", task_id)


def _generate_script_with_deepseek(
    theme: str,
    image_url: Optional[str] = None,
    style: Optional[str] = None,
) -> str:
    """调用 DeepSeek 生成广告文案（兼容旧接口）。优先使用故事化生成并返回旁白文案。"""
    out = _generate_story_script_with_deepseek(theme=theme, style=style)
    return out.get("script", (theme[:200] if len(theme) > 200 else theme).replace("\n", " "))


def _generate_story_script_with_deepseek(theme: str, style: Optional[str] = None) -> dict:
    """
    生成「故事化广告」：一段 6 镜旁白文案 + 6 个与情节对应的场景视觉描述（用于每镜背景图）。
    返回 {"script": "旁白全文", "scenes": ["镜1场景描述", ...]}，scenes 长度不足 6 时用 None 补足或回退默认。
    """
    if not DEEPSEEK_API_KEY:
        return {"script": (theme[:200] if len(theme) > 200 else theme).replace("\n", " "), "scenes": []}

    style_hint = {
        "luxury": "奢华品牌感：金句、质感、身份认同",
        "tech": "科技未来感：简洁、专业、像苹果/特斯拉广告",
        "nature": "自然生活感：温暖、治愈、慢节奏",
        "minimal": "极简高级感：留白多、字少有力",
        "blockbuster": "好莱坞大片感：史诗、戏剧张力、像电影预告片",
    }.get((style or "").strip().lower(), "高端品牌广告感：有记忆点、有氛围")

    prompt = f"""你是顶级广告片文案与视觉总监。请为以下视频主题写一个「像讲故事一样」的 6 镜广告方案。

要求：
1) 风格：{style_hint}。把主题自然融入故事，有开头引入、发展、高潮/卖点、结尾升华。
2) 结尾总结句（必须）：旁白最后一句必须是「一句话总结」，内容格式为：数量词+单位+主题名。例如：一款小板凳、一张高端沙发、一瓶精华液、一盒巧克力。这句话作为视频收尾，便于观众记住产品，不要省略。
3) 输出严格为以下 JSON（不要 markdown 代码块，不要多余说明）：
{{
  "script": "旁白全文。5～8 句完整句、80～120 字，句间可用逗号；最后一句必须是「数量+单位+主题名」的总结句；每句完整适合分 6 镜配音，纯中文无前缀。",
  "scenes": [
    "第1镜画面描述：如 清晨都市高楼窗边柔和晨光、简约桌面",
    "第2镜画面描述：如 产品特写放在大理石台面",
    "第3镜画面描述：如 户外草地阳光自然氛围",
    "第4镜画面描述：如 会议室或办公场景",
    "第5镜画面描述：如 高端室内暖色灯光",
    "第6镜画面描述：如 开阔海景或山峦收尾"
  ]
}}
4) scenes 数组必须恰好 6 个字符串，每个 10～30 字，描述该镜背景图的画面（用于 AI 生成背景图），与旁白情节对应、可虚化衬托产品。
5) 禁止：script 不要「文案：」「旁白：」、不要「您」「我们」。

视频主题：{theme}
"""
    try:
        import json
        import httpx
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.6,
                },
            )
            r.raise_for_status()
            data = r.json()
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
        # 尝试解析 JSON（可能被 markdown 包裹）
        for raw in (text, text.split("```")[0].strip(), text.replace("```json", "").replace("```", "").strip()):
            try:
                obj = json.loads(raw)
                script = (obj.get("script") or "").strip().replace("\n", " ")[:500]
                scenes = obj.get("scenes")
                if isinstance(scenes, list) and len(scenes) >= 6:
                    scenes = [str(s).strip()[:80] for s in scenes[:6]]
                    return {"script": script or theme[:200], "scenes": scenes}
                if script:
                    return {"script": script, "scenes": []}
            except (json.JSONDecodeError, TypeError):
                continue
        # 回退：整段当作文案
        return {"script": (text[:500] if text else theme[:200]).replace("\n", " "), "scenes": []}
    except Exception:
        return {"script": (theme[:200] if len(theme) > 200 else theme).replace("\n", " "), "scenes": []}


def _get_aliyun_nls_token() -> Optional[str]:
    """获取阿里云智能语音 NLS 的 Access Token（带简单缓存，24h 有效）。"""
    global _NLS_TOKEN_CACHE, _NLS_TOKEN_EXPIRY
    if not ALIYUN_ACCESS_KEY_ID or not ALIYUN_ACCESS_KEY_SECRET:
        return None
    import time
    now = time.time()
    if _NLS_TOKEN_CACHE and now < _NLS_TOKEN_EXPIRY - 3600:  # 提前 1 小时刷新
        return _NLS_TOKEN_CACHE
    try:
        from aliyunsdkcore.client import AcsClient
        from aliyunsdkcore.request import CommonRequest
        client = AcsClient(ALIYUN_ACCESS_KEY_ID, ALIYUN_ACCESS_KEY_SECRET, ALIYUN_NLS_REGION)
        req = CommonRequest()
        req.set_method("POST")
        req.set_domain("nls-meta.%s.aliyuncs.com" % ALIYUN_NLS_REGION)
        req.set_version("2019-02-28")
        req.set_action_name("CreateToken")
        body = client.do_action_with_exception(req)
        import json
        data = json.loads(body)
        _NLS_TOKEN_CACHE = data.get("Token", {}).get("Id")
        expire = data.get("Token", {}).get("ExpireTime", 0)
        _NLS_TOKEN_EXPIRY = expire if isinstance(expire, (int, float)) else now + 86400
        return _NLS_TOKEN_CACHE
    except Exception as e:
        logger.warning("阿里云 NLS Token 获取失败: %s", e)
        return None


def _synthesize_speech_aliyun(text: str, voice: Optional[str] = None) -> Optional[str]:
    """
    调用阿里云 TTS 合成语音，保存为 WAV。voice 由前端传入或环境变量 ALIYUN_TTS_VOICE。
    语速/音调/音量已按「真人感」优化：偏慢语速、微暖音调、适中音量。推荐多情感音色 zhimi_emo/zhiyan_emo（需控制台开通）。
    """
    if not text or not ALIYUN_NLS_APPKEY:
        return None
    token = _get_aliyun_nls_token()
    if not token:
        return None
    text = (text or "").strip()[:300]
    if not text:
        return None
    # 默认若兮；要更有感情可设 ALIYUN_TTS_VOICE=zhimi_emo 或 zhiyan_emo（多情感需控制台开通）
    voice = (voice or os.getenv("ALIYUN_TTS_VOICE") or "ruoxi").strip() or "ruoxi"
    out_path = f"/tmp/tts_aliyun_{uuid.uuid4()}.wav"
    base_url = "https://nls-gateway-%s.aliyuncs.com/stream/v1/tts" % ALIYUN_NLS_REGION.replace("_", "-")

    def save_audio(r) -> bool:
        try:
            ct = (r.headers.get("content-type") or "").lower()
            if "json" in ct or (r.content and len(r.content) < 500 and b"{" in r.content[:200]):
                try:
                    err = r.json() if hasattr(r, "json") else None
                    logger.warning("阿里云 TTS 返回 JSON 错误: %s", err or r.text[:300])
                except Exception:
                    logger.warning("阿里云 TTS 非音频响应: len=%s", len(r.content))
                return False
            if len(r.content) > 1000:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return True
            return False
        except Exception:
            return False

    try:
        import httpx
        from urllib.parse import quote

        # 真人化：语速放慢约 3 倍、与镜头字幕对齐；推荐 ALIYUN_TTS_VOICE=zhimi_emo
        volume = int(os.getenv("ALIYUN_TTS_VOLUME", "65"))
        speech_rate = int(os.getenv("ALIYUN_TTS_SPEECH_RATE", "-200"))  # 再放慢约 3 倍，与镜头节奏一致
        pitch_rate = int(os.getenv("ALIYUN_TTS_PITCH_RATE", "12"))
        sample_rate = int(os.getenv("ALIYUN_TTS_SAMPLE_RATE", "16000"))  # 部分区域仅 16k；可试 24000 更清晰

        with httpx.Client(timeout=30.0) as client:
            # 先试 POST（文档推荐），voice 由参数传入或环境变量
            payload = {
                "appkey": ALIYUN_NLS_APPKEY,
                "token": token,
                "text": text,
                "format": "wav",
                "sample_rate": sample_rate,
                "volume": volume,
                "speech_rate": speech_rate,
                "pitch_rate": pitch_rate,
                "voice": voice,
            }
            r = client.post(base_url, json=payload, headers={"Content-Type": "application/json"})
            if r.status_code != 200:
                err_msg = r.text[:500] if r.text else r.content[:200].decode("utf-8", errors="replace") if r.content else "(空)"
                logger.warning("阿里云 TTS POST %s: %s", r.status_code, err_msg)
                # 备用：GET（text 需 urlencode）；部分区域仅支持 16000，失败时可设 ALIYUN_TTS_SAMPLE_RATE=16000
                get_url = f"{base_url}?appkey={quote(ALIYUN_NLS_APPKEY)}&token={quote(token)}&text={quote(text)}&format=wav&sample_rate={sample_rate}&volume={volume}&speech_rate={speech_rate}&pitch_rate={pitch_rate}&voice={quote(voice)}"
                r2 = client.get(get_url)
                if r2.status_code != 200:
                    logger.warning("阿里云 TTS GET %s: %s", r2.status_code, (r2.text or r2.content[:200].decode("utf-8", errors="replace") if r2.content else "")[:400])
                    return None
                r = r2
            if save_audio(r):
                return out_path
            return None
    except Exception as e:
        logger.warning("阿里云 TTS 合成失败: %s", e)
        return None


def _heic_to_png_with_sips(heic_path: str, png_path: str) -> bool:
    """macOS 上用 sips 将 HEIC 转为 PNG（不依赖 libheif）。"""
    try:
        import subprocess
        r = subprocess.run(
            ["sips", "-s", "format", "png", heic_path, "--out", png_path],
            capture_output=True,
            timeout=30,
        )
        if r.returncode == 0 and os.path.isfile(png_path):
            return True
        logger.debug("sips 转换 HEIC 失败: returncode=%s stderr=%s", r.returncode, r.stderr)
    except Exception as e:
        logger.debug("sips 不可用或失败: %s", e)
    return False


def _load_image_to_pil(raw: bytes, image_path: Optional[str], path_lower: Optional[str]) -> Any:
    """将图片字节或路径转为 PIL Image（支持 HEIC）；自动纠正 EXIF 旋转，避免竖拍杯子等在视频里变横。"""
    from PIL import Image, ImageOps
    def _ensure_orientation(img: "Image.Image") -> "Image.Image":
        try:
            return ImageOps.exif_transpose(img)
        except Exception:
            return img

    is_heic = path_lower and (path_lower.endswith(".heic") or path_lower.endswith(".heif"))
    if is_heic or (len(raw) >= 8 and raw[4:8] == b"ftyp"):
        # HEIC：有本地路径且在 macOS 时优先用 sips（兼容「Too many auxiliary image references」等复杂 HEIC），否则用 pillow_heif
        if image_path and os.path.isfile(image_path):
            if sys.platform == "darwin":
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    tmp_png = f.name
                try:
                    if _heic_to_png_with_sips(image_path, tmp_png):
                        img = Image.open(tmp_png).convert("RGB")
                        return _ensure_orientation(img)
                finally:
                    if os.path.isfile(tmp_png):
                        try:
                            os.unlink(tmp_png)
                        except Exception:
                            pass
            try:
                import pillow_heif
                heif_file = pillow_heif.open_heif(image_path)
                img = heif_file.to_pillow().convert("RGB")
                return _ensure_orientation(img)
            except ImportError:
                if sys.platform != "darwin":
                    logger.warning("pillow_heif 未安装，HEIC 可能无法打开")
            except Exception as e:
                logger.warning("pillow_heif 打开 HEIC 失败: %s", e)
        else:
            try:
                import pillow_heif
                heif_file = pillow_heif.open_heif(io.BytesIO(raw))
                img = heif_file.to_pillow().convert("RGB")
                return _ensure_orientation(img)
            except Exception as e:
                logger.warning("pillow_heif 从字节打开 HEIC 失败: %s", e)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return _ensure_orientation(img)


def _prepare_background_image(
    image_path: Optional[str],
    image_url: Optional[str],
    out_path: str,
    width: int = 1280,
    height: int = 720,
) -> bool:
    """
    用用户上传的图片做背景，缩放到 width x height（裁切填满），保存为 PNG。
    优先用 image_path（本地路径），没有则用 image_url 下载。支持 HEIC（需 pillow-heif）。
    """
    try:
        from PIL import Image

        raw = None
        path_lower = (image_path or "").lower()
        if image_path and os.path.isfile(image_path):
            with open(image_path, "rb") as f:
                raw = f.read()
        elif image_url and image_url.strip():
            import httpx
            logger.info("image_path 为空，从 image_url 获取背景图: %s", image_url[:80] if image_url else "")
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(image_url)
                r.raise_for_status()
                raw = r.content
        if not raw:
            return False
        img = _load_image_to_pil(raw, image_path if os.path.isfile(image_path or "") else None, path_lower or None)
        w, h = img.size
        # 完整显示：先按「包含」缩放，再垫黑边到 1280x720，避免裁掉画面
        scale = min(width / w, height / h, 1.0)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        out_img = Image.new("RGB", (width, height), (18, 22, 32))
        paste_x = (width - new_w) // 2
        paste_y = (height - new_h) // 2
        out_img.paste(img, (paste_x, paste_y))
        img = out_img
        # 广告大片感调色：提亮、对比、饱和度 + 电影感（略压高光、微 teal & orange），突出主题
        try:
            from PIL import ImageEnhance, ImageFilter
            brightness = ImageEnhance.Brightness(img)
            img = brightness.enhance(1.08)
            contrast = ImageEnhance.Contrast(img)
            img = contrast.enhance(1.20)
            color = ImageEnhance.Color(img)
            img = color.enhance(1.12)
            try:
                img = img.filter(ImageFilter.UnsharpMask(radius=1.1, percent=90, threshold=3))
            except Exception:
                pass
            # 电影感：阴影略偏青、高光略偏暖（teal & orange 倾向），画面更统一
            r, g, b = img.split()
            r = r.point(lambda x: min(255, int(x * 0.98 + 4)))
            g = g.point(lambda x: min(255, int(x * 1.00)))
            b = b.point(lambda x: min(255, int(x * 1.03)))
            img = Image.merge("RGB", (r, g, b))
            logger.info("背景图已做广告大片感调色")
        except Exception as e:
            logger.warning("背景图美化跳过: %s", e)
        img.save(out_path, "PNG")
        return True
    except Exception as e:
        logger.warning("准备背景图失败，将使用纯色底: %s", e)
        return False


def _pick_font_path() -> Optional[str]:
    for p in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _load_font(font_path: Optional[str], size: int):
    from PIL import ImageFont

    try:
        if font_path and font_path.endswith(".ttc"):
            return ImageFont.truetype(font_path, size, index=0)
        if font_path:
            return ImageFont.truetype(font_path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def _wrap_subtitle_lines(raw: str, max_chars_per_line: int, max_lines: int = 4) -> list:
    """将字幕文案按每行字数换行，优先在标点/空格处断行，最多 max_lines 行，保证字幕完整不截断。"""
    if not raw or max_chars_per_line < 1:
        return [raw] if raw else []
    lines = []
    rest = raw
    while rest and len(lines) < max_lines:
        rest = rest.strip()
        if not rest:
            break
        if len(rest) <= max_chars_per_line:
            lines.append(rest)
            break
        chunk = rest[: max_chars_per_line + 1]
        break_at = -1
        for i, c in enumerate(reversed(chunk)):
            if c in "。！？，,、；： ":
                break_at = len(chunk) - i
                break
        if break_at <= 0:
            break_at = max_chars_per_line
        lines.append(rest[:break_at].strip())
        rest = rest[break_at:]
    return lines[:max_lines]


def _render_text_to_png(
    text: str, png_path: str, width: int = 1280, height: int = 720, style: Optional[str] = None
) -> bool:
    """
    广告大片风格字幕：底部横条（lower third）、金/白高对比、细描边。
    支持多行换行显示完整段落（按段字幕不再只显示前 18/28 字）。
    好莱坞大片（blockbuster）时：大号字、强阴影；叠加时统一底部安全区。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False

    raw = (text or "AI 视频工厂").replace("\n", " ").strip()
    font_path = _pick_font_path()
    is_blockbuster = (style or "").strip().lower() == "blockbuster"

    if is_blockbuster:
        lines = _wrap_subtitle_lines(raw, max_chars_per_line=16, max_lines=3)
        main_font = _load_font(font_path, 52)
        line_h = int(52 * 1.25)
        pad = 18
        band_h = min(160, len(lines) * line_h + pad * 2)
        band_y0 = height - band_h - SUBTITLE_BOTTOM_MARGIN_PX
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        y0 = band_y0 + pad
        for line in lines:
            if not line:
                continue
            bbox = draw.textbbox((0, 0), line, font=main_font)
            tw = bbox[2] - bbox[0]
            main_x = max(60, (width - tw) // 2)
            for dx, dy in [(-4, -4), (-4, 4), (4, -4), (4, 4), (0, -4), (0, 4), (-4, 0), (4, 0)]:
                draw.text((main_x + dx, y0 + dy), line, fill=(0, 0, 0, 240), font=main_font)
            for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
                draw.text((main_x + dx, y0 + dy), line, fill=(0, 0, 0, 180), font=main_font)
            draw.text((main_x, y0), line, fill=(255, 255, 255, 255), font=main_font)
            y0 += line_h
        img.save(png_path, "PNG")
        return True

    # 底部字幕：无黑底条，多行换行显示完整段落
    lines = _wrap_subtitle_lines(raw, max_chars_per_line=20, max_lines=4)
    main_font = _load_font(font_path, 42)
    sub_font = _load_font(font_path, 26)
    line_main = int(42 * 1.28)
    pad = 20
    band_h = len(lines) * line_main + pad * 2 + 4
    band_y0 = height - band_h - SUBTITLE_BOTTOM_MARGIN_PX
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y0 = band_y0 + pad
    for line in lines:
        if not line:
            continue
        bbox = draw.textbbox((0, 0), line, font=main_font)
        tw = bbox[2] - bbox[0]
        main_x = max(40, (width - tw) // 2)
        for dx, dy in [(-3, -3), (-3, 3), (3, -3), (3, 3), (0, -3), (0, 3), (-3, 0), (3, 0)]:
            draw.text((main_x + dx, y0 + dy), line, fill=(0, 0, 0, 220), font=main_font)
        for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
            draw.text((main_x + dx, y0 + dy), line, fill=(0, 0, 0, 160), font=main_font)
        draw.text((main_x, y0), line, fill=(255, 255, 255, 255), font=main_font)
        y0 += line_main
    img.save(png_path, "PNG")
    return True


def _render_theme_poster(theme: str, script_text: str, png_path: str, width: int = 1280, height: int = 720, style: Optional[str] = None) -> bool:
    """
    无上传图片时，生成一张「有购买欲」的主题海报：高级渐变、层次、卖点感，配合 Ken Burns 动效更吸睛。
    style=tech 时使用科技感：青蓝主色、网格线、扫描线、未来感。
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    s_style = (style or "").strip().lower()
    is_tech = s_style == "tech"
    is_blockbuster = s_style == "blockbuster"

    try:
        if is_tech:
            # 科技感背景：深青蓝 + 网格 + 高光
            img = Image.new("RGB", (width, height), (6, 18, 32))
            draw = ImageDraw.Draw(img)
            for y in range(height):
                t = y / max(1, height - 1)
                r = int(6 + 15 * (1 - t))
                g = int(18 + 40 * (1 - t) + 25 * t)
                b = int(32 + 60 * (1 - t) + 50 * t)
                draw.line((0, y, width, y), fill=(min(255, r), min(255, g), min(255, b)))
            # 网格线（科技感）
            grid_step = 64
            for x in range(0, width + 1, grid_step):
                draw.line((x, 0, x, height), fill=(20, 80, 140))
            for y in range(0, height + 1, grid_step):
                draw.line((0, y, width, y), fill=(20, 80, 140))
            # 对角线光带（科技感）
            for i in range(-height, width + height, 120):
                draw.line((i, -10, i + height, height + 10), fill=(0, 100, 160))
            # 扫描线感（每隔几行略暗）
            for y in range(0, height, 4):
                draw.line((0, y, width, y), fill=(12, 35, 65))
        else:
            img = Image.new("RGB", (width, height), (8, 12, 28))
            draw = ImageDraw.Draw(img)
            # 背景：深蓝 → 紫 → 深色渐变，更有质感
            for y in range(height):
                t = y / max(1, height - 1)
                r = int(12 + 28 * (1 - t) + 40 * t * t)
                g = int(18 + 35 * (1 - t) + 25 * t)
                b = int(48 + 60 * (1 - t) + 80 * t)
                draw.line((0, y, width, y), fill=(min(255, r), min(255, g), min(255, b)))

        # 非科技风格：装饰光晕；科技风格保持网格简洁
        if not is_tech:
            draw.ellipse((-80, 60, 420, 560), fill=(30, 80, 140))
            draw.ellipse((width - 420, -60, width + 80, 380), fill=(80, 50, 120))
            draw.ellipse((width - 380, height - 280, width + 60, height + 60), fill=(100, 40, 80))
            draw.ellipse((width - 220, 140, width - 60, 300), fill=(60, 120, 180))
            draw.ellipse((100, height - 320, 320, height - 100), fill=(180, 100, 140))
        else:
            # 科技感：角落高光小圆（青蓝）
            draw.ellipse((width - 200, 80, width + 20, 280), fill=(20, 100, 160))
            draw.ellipse((-20, height - 220, 180, height + 20), fill=(15, 80, 140))

        font_path = _pick_font_path()
        title_font = _load_font(font_path, 72)
        body_font = _load_font(font_path, 34)
        tag_font = _load_font(font_path, 26)
        cta_font = _load_font(font_path, 30)

        title = (theme or "AI 视频工厂").strip()[:16]
        subtitle = (script_text or theme or "AI 视频工厂").replace("\n", " ").strip()[:48]
        tag = "史诗 · 电影级" if is_blockbuster else ("科技 · 未来" if is_tech else "🔥 爆款推荐")
        cta = "立即生成 · 抢占流量"

        # 主卡片：深色玻璃感 + 细边（科技感青蓝，好莱坞大片金/琥珀，否则金边）
        card_x0, card_y0 = 72, 100
        card_x1, card_y1 = width - 72, height - 100
        outline_color = (0, 180, 220) if is_tech else ((220, 180, 80) if is_blockbuster else (180, 160, 100))
        inner_line = (40, 100, 160) if is_tech else ((90, 70, 40) if is_blockbuster else (60, 55, 90))
        draw.rounded_rectangle((card_x0, card_y0, card_x1, card_y1), radius=32, fill=(18, 24, 48))
        draw.rounded_rectangle((card_x0, card_y0, card_x1, card_y1), radius=32, outline=outline_color, width=2)
        draw.rounded_rectangle((card_x0 + 4, card_y0 + 4, card_x1 - 4, card_y1 - 4), radius=28, outline=inner_line, width=1)

        # 标签：科技感青蓝 pill，好莱坞大片琥珀 pill，否则金/琥珀（爆款推荐）
        tag_w, tag_h = 168, 44
        tag_x, tag_y = card_x0 + 48, card_y0 + 36
        if is_tech:
            tag_bg, tag_text_fill = (0, 140, 180), (255, 255, 255)
        elif is_blockbuster:
            tag_bg, tag_text_fill = (200, 140, 40), (20, 18, 10)
        else:
            tag_bg, tag_text_fill = (220, 170, 60), (28, 22, 12)
        draw.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), radius=22, fill=tag_bg)
        draw.text((tag_x + 20, tag_y + 8), tag, fill=tag_text_fill, font=tag_font)

        # 标题（主卖点）：大号白字，带轻微阴影
        title_lines = []
        chunk = 8
        for i in range(0, len(title), chunk):
            title_lines.append(title[i:i + chunk])
        if not title_lines:
            title_lines = ["AI 视频工厂"]
        y = card_y0 + 110
        for line in title_lines[:2]:
            draw.text((card_x0 + 52, y + 2), line, fill=(40, 38, 60), font=title_font)
            draw.text((card_x0 + 50, y), line, fill=(255, 255, 255), font=title_font)
            y += 82

        # 副文案
        body_lines = []
        for i in range(0, min(len(subtitle), 36), 18):
            body_lines.append(subtitle[i:i + 18])
        if not body_lines:
            body_lines = ["智能脚本 + 真人配音，一条视频搞定带货"]
        y += 8
        for line in body_lines[:2]:
            draw.text((card_x0 + 50, y), line, fill=(200, 208, 224), font=body_font)
            y += 44

        # 底部 CTA 条（科技感用青蓝）
        cta_y0 = card_y1 - 56
        cta_bg = (0, 100, 140) if is_tech else (80, 70, 130)
        draw.rounded_rectangle((card_x0 + 40, cta_y0, card_x1 - 40, card_y1 - 24), radius=20, fill=cta_bg)
        draw.text((card_x0 + (card_x1 - card_x0 - 280) // 2, cta_y0 + 10), cta, fill=(230, 225, 255), font=cta_font)

        img.save(png_path, "PNG")
        logger.info("已生成主题海报背景: %s", title)
        return True
    except Exception as e:
        logger.warning("生成主题海报失败: %s", e)
        return False


def _smooth_alpha_edge(rgba: "Image.Image", radius: float = 1.2) -> "Image.Image":
    """对抠图结果的 alpha 通道做轻微模糊，弱化锯齿、提升与背景融合感。"""
    try:
        from PIL import Image, ImageFilter
        if rgba.mode != "RGBA":
            return rgba
        r, g, b, a = rgba.split()
        a_smooth = a.filter(ImageFilter.GaussianBlur(radius=radius))
        return Image.merge("RGBA", (r, g, b, a_smooth))
    except Exception:
        return rgba


def _remove_background(pil_image: "Image.Image", session: Any = None) -> Optional["Image.Image"]:
    """
    抠图：用 rembg 去掉背景，返回 RGBA 图（主体保留，背景透明）。失败或未安装则返回 None。
    传入 session 可复用模型，避免多次加载（同一任务内只抠一次时建议在调用方 new_session 后传入）。
    """
    try:
        from rembg import remove as rembg_remove
        try:
            from rembg import new_session
        except ImportError:
            new_session = None
    except ImportError:
        logger.info("rembg 未安装，跳过抠图（请在该项目 .venv 下执行: pip install rembg）")
        return None
    try:
        import io
        from PIL import Image
        if hasattr(pil_image, "save"):
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            buf.seek(0)
            input_data = buf.read()
        else:
            input_data = pil_image
        kwargs = {}
        if session is not None:
            kwargs["session"] = session
        out_bytes = rembg_remove(input_data, **kwargs)
        if out_bytes is None or len(out_bytes) < 100:
            logger.warning("抠图返回为空或过短")
            return None
        out_img = Image.open(io.BytesIO(out_bytes)).convert("RGBA")
        out_img = _smooth_alpha_edge(out_img)
        return out_img
    except Exception as e:
        logger.warning("抠图失败: %s", e, exc_info=True)
        return None


def _subject_alpha_halves(rgba: "Image.Image", threshold: int = 30) -> Optional[dict]:
    """
    根据抠图 RGBA 的 alpha 通道计算主体区域：bbox、左/右半区质量、上/下半区质量。
    用于智能判断横图应旋转 90° 还是 -90°（主体朝上）、竖图是否倒立需 180° 纠正。
    返回 None 表示无有效主体区域。
    """
    try:
        if rgba.mode != "RGBA":
            return None
        alpha = rgba.split()[3]
        w, h = alpha.size
        if w < 2 or h < 2:
            return None
        # 主体 bbox：alpha > threshold 的像素
        px = alpha.load()
        x1, y1, x2, y2 = w, h, 0, 0
        total = 0
        for y in range(h):
            for x in range(w):
                if px[x, y] > threshold:
                    total += px[x, y]
                    x1, x2 = min(x1, x), max(x2, x)
                    y1, y2 = min(y1, y), max(y2, y)
        if x2 <= x1 or y2 <= y1 or total < 100:
            return None
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        left_sum = right_sum = top_sum = bottom_sum = 0
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                a = px[x, y]
                if a <= threshold:
                    continue
                if x < cx:
                    left_sum += a
                else:
                    right_sum += a
                if y < cy:
                    top_sum += a
                else:
                    bottom_sum += a
        return {
            "bbox": (x1, y1, x2, y2),
            "left_sum": left_sum,
            "right_sum": right_sum,
            "top_sum": top_sum,
            "bottom_sum": bottom_sum,
        }
    except Exception:
        return None


def _bbox_aspect_hw(rgba: "Image.Image", threshold: int = 30) -> Optional[float]:
    """返回主体 bbox 的高/宽比，>1 表示主体偏竖。用于横图选 90°/-90° 时挑「竖起来」的那一档。"""
    h = _subject_alpha_halves(rgba, threshold=threshold)
    if not h or "bbox" not in h:
        return None
    x1, y1, x2, y2 = h["bbox"]
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    return bh / bw


# 6 个创意场景的标题（醒目显示在画面上方）
_SCENE_LABELS = ("豪车", "贵妇手", "健身房", "奢华桌", "高端", "自然")

WORKER_DIR = Path(__file__).resolve().parent
SCENES_ASSET_DIR = WORKER_DIR / "assets" / "scenes"
BGM_ASSET_DIR = WORKER_DIR / "assets" / "bgm"

# 是否已打过「无 BGM」提示（避免重复刷日志）
_BGM_MISSING_LOGGED = False

# 可选：容器内无 BGM 时从 BGM_DEFAULT_URL 下载 default.mp3；不设则只尝试生成静音占位
BGM_DEFAULT_DOWNLOAD_URL = os.getenv("BGM_DEFAULT_URL", "").strip()


def _ensure_bgm_available() -> None:
    """
    确保 BGM 目录存在；若 default.mp3 不存在则尝试下载或生成静音 MP3 到容器内，
    便于后续 _get_bgm_path 能返回可用路径。
    """
    BGM_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    default_mp3 = BGM_ASSET_DIR / "default.mp3"
    if default_mp3.is_file():
        return
    # 尝试从环境变量或默认 URL 下载
    url = (os.getenv("BGM_DEFAULT_URL") or BGM_DEFAULT_DOWNLOAD_URL or "").strip()
    if url:
        try:
            import httpx
            with httpx.Client(follow_redirects=True, timeout=30.0) as client:
                r = client.get(url)
                if r.status_code == 200 and len(r.content) > 1000:
                    default_mp3.write_bytes(r.content)
                    logger.info("已下载 BGM 到容器: %s", default_mp3)
                    return
        except Exception as e:
            logger.warning("下载 BGM 失败，将生成静音占位: %s", e)
    # 无 URL 或下载失败：用 ffmpeg 生成一段静音 MP3，保证混流逻辑可跑；用户可替换为真实 BGM
    try:
        import subprocess
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "60", "-ac", "2", "-q:a", "9", str(default_mp3),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if default_mp3.is_file():
            logger.info("已在容器内生成静音 BGM 占位: %s（可替换为真实 MP3）", default_mp3)
    except Exception as e:
        logger.debug("生成静音 BGM 占位失败: %s", e)


def _get_bgm_path(
    style: Optional[str], duration_sec: float, bgm_override: Optional[str] = None
) -> Optional[str]:
    """
    返回可用的 BGM 文件路径（assets/bgm/ 下 default/tech/blockbuster/cinematic/upbeat.mp3），不存在则返回 None。
    bgm_override: "none"=不用BGM；"default"/"tech"/"blockbuster"/"cinematic"/"upbeat"=指定BGM；None=跟随 style。
    """
    global _BGM_MISSING_LOGGED
    if (bgm_override or "").strip().lower() == "none":
        return None
    if not BGM_ASSET_DIR.is_dir():
        _ensure_bgm_available()
    if not BGM_ASSET_DIR.is_dir():
        if not _BGM_MISSING_LOGGED:
            logger.info(
                "未检测到 BGM 目录，背景音乐未启用。请创建 worker/assets/bgm/ 并放入 default.mp3 / tech.mp3 / blockbuster.mp3 等，详见 worker/assets/bgm/README.md"
            )
            _BGM_MISSING_LOGGED = True
        return None
    s = (bgm_override or style or "").strip().lower()
    if s == "tech":
        order = ("tech.mp3", "default.mp3")
    elif s == "blockbuster":
        order = ("blockbuster.mp3", "default.mp3")
    elif s == "cinematic":
        order = ("cinematic.mp3", "default.mp3")
    elif s == "upbeat":
        order = ("upbeat.mp3", "default.mp3")
    else:
        order = ("default.mp3", "tech.mp3", "blockbuster.mp3", "cinematic.mp3", "upbeat.mp3")
    for name in order:
        p = BGM_ASSET_DIR / name
        if p.is_file():
            return str(p)
    # 容器内无文件时尝试自动下载或生成 default.mp3
    _ensure_bgm_available()
    default_p = BGM_ASSET_DIR / "default.mp3"
    if default_p.is_file():
        return str(default_p)
    if not _BGM_MISSING_LOGGED:
        logger.info(
            "未检测到 BGM 文件，背景音乐未启用。请将 default.mp3（或 tech.mp3 / blockbuster.mp3）放入 worker/assets/bgm/，或设置 BGM_DEFAULT_URL 自动下载，详见 worker/assets/bgm/README.md"
        )
        _BGM_MISSING_LOGGED = True
    return None

# 背景图：每个镜头均为真实图片（大海/草地/湖泊/森林/山雾等），无纯色；虚化后衬托主题
_SCENE_IMAGE_URLS_DEFAULT = [
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop",   # 大海/蓝
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?w=1280&h=720&fit=crop",   # 草地/自然
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",   # 湖泊/山
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1280&h=720&fit=crop",   # 森林
    "https://images.unsplash.com/photo-1493246507139-91e8fad9978e?w=1280&h=720&fit=crop",   # 户外柔焦
    "https://images.unsplash.com/photo-1557683316-973673baf926?w=1280&h=720&fit=crop",   # 自然渐变
]
_SCENE_IMAGE_URLS_TECH = [
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1557682268-e3955ed5f83e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1280&h=720&fit=crop",
]
_SCENE_IMAGE_URLS_BLOCKBUSTER = [
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop",   # 大海
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?w=1280&h=720&fit=crop",   # 草地/自然
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",   # 湖泊/山
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1493246507139-91e8fad9978e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1557683316-973673baf926?w=1280&h=720&fit=crop",
]
_SCENE_IMAGE_URLS_DEFAULT_B = [
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",   # 湖泊/山
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1493246507139-91e8fad9978e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1557683316-973673baf926?w=1280&h=720&fit=crop",
]
_SCENE_IMAGE_URLS_TECH_B = [
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1557682268-e3955ed5f83e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1551434678-e076c223a692?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1280&h=720&fit=crop",
]
_SCENE_IMAGE_URLS_BLOCKBUSTER_B = [
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1493246507139-91e8fad9978e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1557683316-973673baf926?w=1280&h=720&fit=crop",
]
# 下载失败时按镜索引轮换使用的备用 URL（6 张不同图），保证每镜都有真实背景、不重复
_SCENE_IMAGE_URLS_FALLBACK = [
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1493246507139-91e8fad9978e?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1557683316-973673baf926?w=1280&h=720&fit=crop",
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1280&h=720&fit=crop",
]

# 场景图库：20 张日常生活/城市/河流山川风景，下载到 library/ 供调用（运行 scripts/download_scene_library.py 拉取）
SCENE_LIBRARY_DIR = SCENES_ASSET_DIR / "library"
_SCENE_LIBRARY_URLS = [
    # 日常生活场景 (1-7)
    "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1280&h=720&fit=crop",  # 咖啡
    "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?w=1280&h=720&fit=crop",  # 办公桌
    "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=1280&h=720&fit=crop",  # 客厅
    "https://images.unsplash.com/photo-1556911220-bff31c812dba?w=1280&h=720&fit=crop",  # 厨房
    "https://images.unsplash.com/photo-1554118811-1e0d58224f24?w=1280&h=720&fit=crop",  # 咖啡馆
    "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=1280&h=720&fit=crop",  # 阅读/书
    "https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=1280&h=720&fit=crop",  # 店铺/生活
    # 城市 (8-14)
    "https://images.unsplash.com/photo-1480714378408-67cf0d13bc1b?w=1280&h=720&fit=crop",  # 城市天际线
    "https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=1280&h=720&fit=crop",  # 都市街道
    "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=1280&h=720&fit=crop",  # 建筑室内
    "https://images.unsplash.com/photo-1514565131-fce0801e5785?w=1280&h=720&fit=crop",  # 城市夜景
    "https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?w=1280&h=720&fit=crop",  # 城市楼宇
    "https://images.unsplash.com/photo-1519681393784-d120267933ba?w=1280&h=720&fit=crop",  # 雪山
    "https://images.unsplash.com/photo-1497366216548-37526070297c?w=1280&h=720&fit=crop",  # 写字楼
    # 河流山川风景 (15-20)
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1280&h=720&fit=crop",  # 雪山
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?w=1280&h=720&fit=crop",  # 草地/山
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1280&h=720&fit=crop",  # 森林
    "https://images.unsplash.com/photo-1469474968028-56623f02e42e?w=1280&h=720&fit=crop",  # 山川
    "https://images.unsplash.com/photo-1501785888041-af3ef285b470?w=1280&h=720&fit=crop",  # 湖景
    "https://images.unsplash.com/photo-1433086966358-54859d0ed716?w=1280&h=720&fit=crop",  # 瀑布/河流
]


def _get_scene_urls_for_style(style: Optional[str], theme: Optional[str] = None) -> list:
    """根据风格与主题返回 6 个场景图 URL，主题不同时切换 A/B 组以更好衬托主题。"""
    s = (style or "").strip().lower()
    variant = 0
    if (theme or "").strip():
        variant = hash((theme or "").strip()) % 2
    if s == "tech":
        return list(_SCENE_IMAGE_URLS_TECH_B if variant else _SCENE_IMAGE_URLS_TECH)
    if s == "blockbuster":
        return list(_SCENE_IMAGE_URLS_BLOCKBUSTER_B if variant else _SCENE_IMAGE_URLS_BLOCKBUSTER)
    return list(_SCENE_IMAGE_URLS_DEFAULT_B if variant else _SCENE_IMAGE_URLS_DEFAULT)


def _build_jimeng_prompt_for_scene(
    index: int, style: Optional[str], theme: Optional[str], scene_description: Optional[str] = None
) -> str:
    """为即梦文生图构造场景描述。首选故事情节 scene_description，使背景与文案画面一致。"""
    s = (style or "").strip().lower()
    theme_part = (theme or "").strip()[:80].replace("\n", " ") or "commercial"
    style_hint = ""
    if s == "tech":
        style_hint = "cool blue cyan tone, tech futuristic, soft bokeh"
    elif s == "blockbuster":
        style_hint = "warm cinematic film look, teal and orange, Hollywood commercial"
    else:
        style_hint = "cinematic commercial, soft focus background, 16:9"
    if scene_description and (scene_description := scene_description.strip())[:1]:
        # 故事情节描述：即梦支持中英文，保留关键画面信息，便于与故事契合
        desc = scene_description[:150].replace("\n", " ").strip()
        # 中英结合提升即梦理解：场景描述 + 风格 + 无文字无人物（适合做背景）
        return (
            f"广告背景图，场景：{desc}，主题：{theme_part}。"
            f"风格：{style_hint}。高质量、虚化背景、无文字、无人脸，适合作为产品展示背景。"
        )
    # 无故事情节时用默认 6 镜模板
    labels = [
        "咖啡与甜点放在大理石桌面，柔和晨光",
        "护肤品与化妆品，干净影棚光",
        "奢华手表或配饰，中性背景",
        "手袋与时尚单品，生活化平铺",
        "家居香氛与鲜花，温暖室内",
        "早餐或美食，新鲜诱人",
    ]
    base = labels[index % 6]
    return (
        f"广告背景图，{base}，主题：{theme_part}。"
        f"风格：{style_hint}。高质量虚化背景，无文字。"
    )


def _generate_scene_image_jimeng(
    prompt: str, width: int, height: int, save_path: str
) -> bool:
    """
    调用即梦（兼容 OpenAI 的文生图接口）生成一张图并保存到 save_path。
    支持火山方舟、第三方代理等。成功返回 True。
    """
    if not JIYMENG_IMAGE_API_URL or not JIYMENG_IMAGE_API_KEY:
        return False
    try:
        import httpx
        url = JIYMENG_IMAGE_API_URL
        if "/images/generations" not in url:
            base = url.rstrip("/")
            # 火山方舟即梦使用 /api/v3/images/generations；第三方代理多为 /v1/images/generations
            if "ark" in base and "volces.com" in base:
                url = base + "/api/v3/images/generations"
            else:
                url = base + "/v1/images/generations"
        # 方舟即梦 4.5 要求至少 3686400 像素（约 1920x1920），用 2K；第三方代理可用较小尺寸
        is_ark = "ark" in url and "volces.com" in url
        if is_ark:
            size_str = "2K"
        else:
            size_map = [(1920, 1080), (1664, 936), (1280, 720), (1024, 768)]
            size_str = f"{width}x{height}"
            for w, h in size_map:
                if w <= width and h <= height:
                    size_str = f"{w}x{h}"
                    break
        payload = {
            "prompt": prompt[:2000],
            "model": JIYMENG_IMAGE_MODEL,
            "size": size_str,
            "n": 1,
            "response_format": "url",
        }
        headers = {
            "Authorization": "Bearer %s" % JIYMENG_IMAGE_API_KEY,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            logger.warning("即梦文生图请求失败 status=%s body=%s", r.status_code, (r.text or "")[:300])
            return False
        data = r.json()
        image_url = None
        if isinstance(data.get("data"), list) and len(data["data"]) > 0:
            first = data["data"][0]
            image_url = first.get("url")
            if not image_url and first.get("b64_json"):
                import base64
                raw = base64.b64decode(first["b64_json"])
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(raw)
                return True
        if not image_url:
            logger.warning("即梦文生图响应无 url/b64_json: %s", str(data)[:200])
            return False
        # 下载 URL 到本地
        import urllib.request
        req = urllib.request.Request(image_url, headers={"User-Agent": "VedioBuild/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(raw)
        return True
    except Exception as e:
        logger.warning("即梦文生图异常: %s", e)
        return False


def _apply_style_color_grade(img: "Image.Image", style: Optional[str]) -> "Image.Image":
    """
    对场景图做风格化调色，使与主题融合：tech=青蓝、blockbuster=暖橙电影感、默认=轻微 teal&orange。
    """
    from PIL import ImageEnhance, Image
    s = (style or "").strip().lower()
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.08)
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.05)
    if s == "tech":
        # 青蓝调：半透明青蓝叠层
        tint = Image.new("RGB", img.size, (28, 80, 140))
        img = Image.blend(img, tint, alpha=0.18)
    elif s == "blockbuster":
        # 暖橙电影感：半透明暖色叠层，略强以贴近好莱坞商业片
        tint = Image.new("RGB", img.size, (165, 88, 48))
        img = Image.blend(img, tint, alpha=0.18)
    return img

# 兼容旧环境变量：默认使用 default 的 URL 列表
_SCENE_IMAGE_URLS = _SCENE_IMAGE_URLS_DEFAULT
# 场景图缓存版本：改号后不再复用旧缓存（v5=无黑条字幕+氛围背景）
SCENE_CACHE_VERSION = os.getenv("SCENE_CACHE_VERSION", "v7")  # v7=每镜头真实图(大海/草地/湖泊/森林等)+备用URL


def _normalize_scene_image_url(url: str) -> str:
    """若 URL 为 Unsplash 但查询参数不完整（如 ?w= 无值），补全为 w=1280&h=720&fit=crop，避免 404。"""
    if not url or "unsplash.com" not in url:
        return url
    if "?w=" in url and "&h=" not in url:
        # 可能被截断成 ?w= 无值，统一补全
        base = url.split("?")[0]
        return f"{base}?w=1280&h=720&fit=crop"
    return url


def _download_scene_image(url: str, path: str, scene_index: Optional[int] = None) -> bool:
    """下载场景图到本地；相同内容的图只存一份（按内容 hash 合并到 assets/scenes）。"""
    url = _normalize_scene_image_url(url)
    try:
        import hashlib
        import shutil
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; VedioBuild/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 100:
            return False
        # 仅接受 JPEG/PNG，避免把 404/HTML 当图片写入
        if data[:3] != b"\xff\xd8\xff" and data[:8] != b"\x89PNG\r\n\x1a\n":
            logger.warning("下载内容非图片格式: %s", url[:60])
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 相同内容只存一份：用内容 hash 做 canonical 文件，避免 scenes 里重复图
        content_hash = hashlib.sha256(data).hexdigest()[:24]
        canonical_dir = SCENES_ASSET_DIR
        canonical_path = canonical_dir / f"_c_{content_hash}.jpg"
        if canonical_path.exists():
            shutil.copy2(str(canonical_path), path)
            return True
        with open(path, "wb") as f:
            f.write(data)
        try:
            if path != str(canonical_path):
                canonical_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, str(canonical_path))
        except Exception:
            pass
        return True
    except Exception as e:
        logger.warning("下载场景图失败 %s: %s", url[:60], e)
        return False


def _get_library_scene_path(index: int):
    """返回图库中第 index 镜对应的本地路径（lib_001.jpg～lib_020.jpg），共 20 张供轮换。"""
    if not SCENE_LIBRARY_DIR or not _SCENE_LIBRARY_URLS:
        return None
    n = len(_SCENE_LIBRARY_URLS)
    num = (index % n) + 1
    return SCENE_LIBRARY_DIR / f"lib_{num:03d}.jpg"


def _get_scene_background_image(
    index: int,
    width: int,
    height: int,
    style: Optional[str] = None,
    theme: Optional[str] = None,
    scene_description: Optional[str] = None,
) -> Optional["Image.Image"]:
    """
    获取第 index 个场景的背景图：优先读本地缓存；
    首选即梦文生图（与故事情节一致），未配置或失败时用 URL 图库备用，最后回退手绘。
    """
    from PIL import Image
    i = index % 6
    s = (style or "").strip().lower()
    suffix = s if s in ("tech", "blockbuster") else "default"
    variant = "_b" if (theme or "").strip() and hash((theme or "").strip()) % 2 else "_a"
    if scene_description and scene_description.strip():
        story_hash = str(hash(scene_description.strip()[:60]) % 100000).replace("-", "s")
        path = SCENES_ASSET_DIR / f"scene_{i}_{suffix}_story_{story_hash}_{SCENE_CACHE_VERSION}.jpg"
    else:
        path = SCENES_ASSET_DIR / f"scene_{i}_{suffix}{variant}_{SCENE_CACHE_VERSION}.jpg"
    if not path.exists():
        got = False
        # 首选：即梦文生图（与故事/风格一致）
        if PREFER_JIMENG_SCENE and JIYMENG_ENABLED:
            logger.debug("第 %d 镜背景：优先即梦文生图（与故事情节一致）", i)
            prompt = _build_jimeng_prompt_for_scene(i, style, theme, scene_description=scene_description)
            got = _generate_scene_image_jimeng(prompt, width, height, str(path))
        # 第二选项：URL 图库下载（风格/主题对应 6 张图）
        if not got:
            if PREFER_JIMENG_SCENE and JIYMENG_ENABLED:
                logger.info("即梦未生成第 %d 镜背景，使用 URL 图库备用", i)
            urls = _get_scene_urls_for_style(style, theme=theme)
            url = os.getenv(f"SCENE_IMAGE_URL_{i}", urls[i] if i < len(urls) else _SCENE_IMAGE_URLS_DEFAULT[i])
            if not _download_scene_image(url, str(path), scene_index=i):
                # 按镜索引选用不同 fallback，避免 6 张图都用同一张；再轮询其余 URL
                fallback_list = _SCENE_IMAGE_URLS_FALLBACK
                nf = len(fallback_list)
                for k in range(nf):
                    fallback_url = fallback_list[(i + k) % nf]
                    if _download_scene_image(fallback_url, str(path), scene_index=i):
                        break
                else:
                    # 备用 URL 均失败时，从本地图库取图（20 张日常生活/城市/山川，需先运行 scripts/download_scene_library.py）
                    lib_path = _get_library_scene_path(i)
                    if lib_path and lib_path.exists():
                        img = _load_and_style_background_image(str(lib_path), width, height, style=style)
                        if img is not None:
                            return img
                    return None
    try:
        from PIL import ImageFilter
        img = Image.open(str(path)).convert("RGB")
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        img = _apply_style_color_grade(img, style)
        # 背景虚化，不抢主题，突出前景主体
        img = img.filter(ImageFilter.GaussianBlur(radius=SCENE_BLUR_RADIUS))
        return img
    except Exception as e:
        logger.warning("加载场景图 scene_%s 失败: %s", i, e)
        return None


def _load_and_style_background_image(
    image_path: str, width: int, height: int, style: Optional[str] = None
) -> Optional["Image.Image"]:
    """从本地路径加载图片，做风格调色与虚化，与 _get_scene_background_image 输出一致。"""
    try:
        from PIL import Image, ImageFilter
        img = Image.open(image_path).convert("RGB")
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        img = _apply_style_color_grade(img, style)
        img = img.filter(ImageFilter.GaussianBlur(radius=SCENE_BLUR_RADIUS))
        return img
    except Exception as e:
        logger.warning("加载背景图失败 %s: %s", image_path, e)
        return None


def _fetch_and_save_story_backgrounds(
    scene_descriptions: list,
    style: Optional[str],
    theme: Optional[str],
    width: int,
    height: int,
    save_dir: str,
) -> list:
    """
    按故事情节描述抓取并保存 6 张对应场景背景图到 save_dir（scene_0_bg.jpg ... scene_5_bg.jpg）。
    首选即梦文生图（与故事一致），失败则用 URL 图库备用。返回 6 个文件路径，任一张失败则返回空列表。
    """
    if not scene_descriptions or len(scene_descriptions) < 6:
        return []
    if PREFER_JIMENG_SCENE and JIYMENG_ENABLED:
        logger.info("6 镜背景：首选即梦文生图（与故事情节一致），失败则 URL 备用")
    else:
        logger.info("6 镜背景：使用 URL 图库（即梦未配置或已关闭）")
    os.makedirs(save_dir, exist_ok=True)
    paths = []
    for i in range(6):
        desc = (scene_descriptions[i] if i < len(scene_descriptions) else "").strip() or None
        img = _get_scene_background_image(
            i, width, height, style=style, theme=theme, scene_description=desc
        )
        if img is None:
            logger.warning("故事情节背景图第 %d 镜获取失败，回退将使用默认流程", i)
            return []
        p = os.path.join(save_dir, f"scene_{i}_bg.jpg")
        img.save(p, "JPEG", quality=92)
        paths.append(p)
    logger.info("已保存 6 张故事情节背景图到 %s", save_dir)
    return paths


def _draw_scene_title(img: "Image.Image", index: int, style: Optional[str] = None) -> None:
    """在画面顶部绘制场景标题条，确保豪车/贵妇等一眼可见；按风格使用不同配色与主题融合。"""
    from PIL import ImageDraw
    width, height = img.size
    draw = ImageDraw.Draw(img)
    label = _SCENE_LABELS[index % 6]
    band_h = 72
    s = (style or "").strip().lower()
    if s == "tech":
        band_fill, line_fill = (18, 28, 42), (60, 140, 200)
    elif s == "blockbuster":
        band_fill, line_fill = (42, 28, 18), (200, 160, 90)
    else:
        band_fill, line_fill = (28, 24, 32), (120, 100, 180)
    draw.rectangle((0, 0, width, band_h), fill=band_fill)
    draw.line((0, band_h, width, band_h), fill=line_fill, width=2)
    font = _load_font(_pick_font_path(), 42)
    # 用 textbbox 居中
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (width - tw) // 2
    ty = (band_h - th) // 2
    shadow_fill = (40, 35, 50) if band_fill[0] > 30 else (20, 35, 55)
    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
        draw.text((tx + dx, ty + dy), label, fill=shadow_fill, font=font)
    draw.text((tx, ty), label, fill=(255, 255, 255), font=font)


def _draw_creative_background(
    index: int,
    width: int,
    height: int,
    style: Optional[str] = None,
    theme: Optional[str] = None,
    scene_description: Optional[str] = None,
) -> "Image.Image":
    """
    6 种创意主题背景：按风格+主题选用场景图并调色融合；若提供 scene_description 则按故事情节生成该镜背景。
    无图时回退为 PIL 手绘场景。抠图主体合成在对应场景位。
    """
    from PIL import Image, ImageDraw
    img = _get_scene_background_image(
        index, width, height, style=style, theme=theme, scene_description=scene_description
    )
    if img is not None:
        # 不再绘制场景标题条（豪车/自然等），保持画面干净
        return img
    # 回退：PIL 手绘场景
    img = Image.new("RGB", (width, height), (15, 12, 18))
    draw = ImageDraw.Draw(img)
    cx, cy = width // 2, height // 2
    themes = [
        ((25, 18, 12), (70, 52, 35), (120, 95, 65), (55, 45, 35)),   # 0 豪车：更亮皮革棕
        ((55, 45, 42), (100, 88, 78), (220, 200, 180), (95, 85, 75)), # 1 贵妇：更亮肤米金
        ((28, 26, 35), (65, 48, 58), (255, 120, 70), (40, 38, 48)),  # 2 健身房：更亮橙
        ((35, 35, 40), (75, 70, 78), (220, 185, 110), (75, 70, 60)), # 3 奢华桌：更亮金
        ((28, 32, 42), (60, 68, 88), (140, 180, 255), (55, 60, 78)), # 4 高端：更亮蓝
        ((18, 40, 30), (45, 75, 58), (100, 180, 140), (35, 58, 45)), # 5 自然：更亮绿
    ]
    base, mid, accent, dark = themes[index % 6]
    for y in range(height):
        r = base[0] + (mid[0] - base[0]) * (y / height)
        g = base[1] + (mid[1] - base[1]) * (y / height)
        b = base[2] + (mid[2] - base[2]) * (y / height)
        draw.line((0, y, width, y), fill=(min(255, int(r)), min(255, int(g)), min(255, int(b))))

    # ---------- 0 豪车：中控台 + 方向盘轮廓 + 杯座区（高对比）----------
    if index == 0:
        y_band = int(height * 0.64)
        draw.rectangle((0, y_band, width, height), fill=(35, 26, 18))
        draw.line((0, y_band, width, y_band), fill=(130, 100, 70), width=3)
        # 方向盘轮廓：大圆 + 左右两辐条
        steer_y = int(height * 0.28)
        draw.ellipse((cx - 120, steer_y - 80, cx + 120, steer_y + 80), outline=(100, 80, 55), width=4)
        draw.ellipse((cx - 90, steer_y - 50, cx + 90, steer_y + 50), outline=(80, 62, 42), width=2)
        draw.rectangle((cx - 8, steer_y - 80, cx + 8, steer_y + 80), fill=(90, 72, 50))
        draw.rectangle((cx - 120, steer_y - 8, cx + 120, steer_y + 8), fill=(90, 72, 50))
        # 仪表/出风口：两个亮圈
        for ox in (cx - 200, cx + 100):
            draw.ellipse((ox - 55, steer_y - 45, ox + 55, steer_y + 45), outline=(110, 88, 60), width=3)
        # 杯座区（放杯子）：明显深色椭圆
        cup_x1, cup_x2 = int(width * 0.36), int(width * 0.64)
        cup_y1, cup_y2 = int(height * 0.56), int(height * 0.74)
        draw.ellipse((cup_x1, cup_y1, cup_x2, cup_y2), fill=(42, 32, 22), outline=(115, 92, 65))

    # ---------- 1 贵妇手：手心 + 手指（高对比肤色）----------
    elif index == 1:
        palm_x1, palm_y1 = int(width * 0.38), int(height * 0.22)
        palm_x2, palm_y2 = int(width * 0.94), int(height * 0.84)
        draw.ellipse((palm_x1, palm_y1, palm_x2, palm_y2), fill=(115, 98, 88))
        draw.ellipse((palm_x1 + 25, palm_y1 + 25, palm_x2 - 25, palm_y2 - 25), outline=(200, 185, 170), width=3)
        # 手指椭圆（更亮）
        draw.ellipse((int(width * 0.28), int(height * 0.34), int(width * 0.46), int(height * 0.50)), fill=(108, 92, 82))
        draw.ellipse((int(width * 0.24), int(height * 0.44), int(width * 0.40), int(height * 0.60)), fill=(102, 88, 78))
        draw.ellipse((int(width * 0.34), int(height * 0.64), int(width * 0.50), int(height * 0.80)), fill=(105, 90, 80))
        draw.ellipse((int(width * 0.46), int(height * 0.68), int(width * 0.60), int(height * 0.88)), fill=(98, 85, 75))

    # ---------- 2 健身房：哑铃 + 地面 + 台面（亮橙色）----------
    elif index == 2:
        draw.rectangle((0, int(height * 0.75), width, height), fill=(25, 24, 30))
        draw.line((0, int(height * 0.75), width, int(height * 0.75)), fill=(accent[0], accent[1], accent[2]), width=4)
        d_x, d_y = int(width * 0.18), int(height * 0.42)
        draw.ellipse((d_x - 58, d_y - 58, d_x + 58, d_y + 58), outline=(accent[0], accent[1], accent[2]), width=4)
        draw.ellipse((d_x + 110 - 58, d_y - 58, d_x + 110 + 58, d_y + 58), outline=(accent[0], accent[1], accent[2]), width=4)
        draw.rectangle((d_x + 48, d_y - 14, d_x + 62, d_y + 14), fill=(accent[0], accent[1], accent[2]))
        d2_x = int(width * 0.76)
        draw.ellipse((d2_x - 42, d_y - 42, d2_x + 42, d_y + 42), outline=(accent[0], accent[1], accent[2]), width=3)
        draw.ellipse((d2_x + 75 - 42, d_y - 42, d2_x + 75 + 42, d_y + 42), outline=(accent[0], accent[1], accent[2]), width=3)
        draw.rectangle((d2_x + 28, d_y - 10, d2_x + 47, d_y + 10), fill=(accent[0], accent[1], accent[2]))
        draw.rounded_rectangle((cx - 240, int(height * 0.50), cx + 240, int(height * 0.78)), radius=14, outline=(80, 60, 75), width=3)

    # ---------- 3 奢华桌面：金线 + 倒影（更亮金）----------
    elif index == 3:
        table_y1 = int(height * 0.40)
        draw.rectangle((0, table_y1, width, height), fill=(dark[0], dark[1], dark[2]))
        draw.line((0, table_y1, width, table_y1), fill=(accent[0], accent[1], accent[2]), width=4)
        margin = 40
        draw.rectangle((margin, table_y1 + margin, width - margin, height - margin), outline=(accent[0], accent[1], accent[2]), width=3)
        draw.ellipse((cx - 220, int(height * 0.58), cx + 220, int(height * 0.90)), fill=(55, 52, 58))
        draw.ellipse((cx - 180, int(height * 0.62), cx + 180, int(height * 0.84)), outline=(140, 125, 95))

    # ---------- 4 高端商场：竖线 + 展台（更亮蓝）----------
    elif index == 4:
        for x_ in (width // 5, width // 2, width * 4 // 5):
            draw.line((x_, 0, x_, height), fill=(accent[0] // 2 + 40, accent[1] // 2 + 50, accent[2] // 2 + 60))
        plat_y = int(height * 0.52)
        draw.rectangle((cx - 300, plat_y, cx + 300, height), fill=(dark[0], dark[1], dark[2]))
        draw.line((cx - 300, plat_y, cx + 300, plat_y), fill=(accent[0], accent[1], accent[2]), width=4)
        draw.rectangle((cx - 270, plat_y + 24, cx + 270, plat_y + 130), outline=(100, 120, 180))

    # ---------- 5 自然户外：叶子 + 石头台面（更亮绿）----------
    else:
        draw.rectangle((0, int(height * 0.70), width, height), fill=(22, 55, 42))
        for i, (lx, ly) in enumerate([(width * 0.12, height * 0.48), (width * 0.86, height * 0.42), (width * 0.48, height * 0.62)]):
            leaf_w, leaf_h = 90 + i * 25, 200
            draw.ellipse((int(lx - leaf_w // 2), int(ly - leaf_h // 2), int(lx + leaf_w // 2), int(ly + leaf_h // 2)), outline=(60, 130, 95), width=3)
        draw.ellipse((cx - 260, int(height * 0.50), cx + 260, int(height * 0.74)), fill=(45, 75, 58))
        draw.ellipse((cx - 220, int(height * 0.52), cx + 220, int(height * 0.70)), outline=(90, 160, 125))

    # 不再绘制场景标题条，保持画面干净
    return img


def _paste_subject_on_bg(bg: "Image.Image", subject_rgba: "Image.Image", theme_index: int, width: int, height: int) -> "Image.Image":
    """把抠图主体贴到对应场景，主体放大、多层阴影增强 3D 立体感，边缘与背景自然融合。"""
    from PIL import Image, ImageFilter
    sw, sh = subject_rgba.size
    if sw <= 0 or sh <= 0:
        return bg
    # 主体占画面约 95% 宽、90% 高，中心略偏下；每镜微调中心纵坐标增加层次感
    slot_center_y = 0.52 + (theme_index % 3) * 0.02
    max_w = int(width * 0.95)
    max_h = int(height * 0.90)
    scale = min(max_w / sw, max_h / sh, 7.5) * 1.04
    nw, nh = int(sw * scale), int(sh * scale)
    center_x = width // 2
    center_y = int(height * slot_center_y)
    px = center_x - nw // 2
    py = center_y - nh // 2
    px = max(16, min(width - nw - 16, px))
    py = max(16, min(height - nh - 16, py))
    subject = subject_rgba.resize((nw, nh), Image.Resampling.LANCZOS)
    # 3D 立体感：软投影 + 接触阴影（更柔和、过渡更自然）
    if subject.mode == "RGBA":
        alpha_ch = subject.split()[3]
        try:
            from PIL import ImageStat
            has_alpha = ImageStat.Stat(alpha_ch).extrema[0][1] > 12
        except Exception:
            has_alpha = True
        if has_alpha:
            # 1) 软投影：更大模糊半径，更自然的地面落影
            shadow_soft_alpha = alpha_ch.point(lambda a: int(a * 0.32) if a > 20 else 0)
            shadow_soft = Image.new("RGBA", subject.size, (0, 0, 0, 0))
            shadow_soft.putalpha(shadow_soft_alpha)
            try:
                blur_r = min(20, max(10, nw // 18))
                shadow_soft = shadow_soft.filter(ImageFilter.GaussianBlur(radius=blur_r))
            except Exception:
                pass
            shift_soft = (12, 22)
            bg.paste(shadow_soft, (px + shift_soft[0], py + shift_soft[1]), shadow_soft)
            # 2) 接触阴影：略硬、贴近主体
            shadow_contact_alpha = alpha_ch.point(lambda a: int(a * 0.5) if a > 25 else 0)
            shadow_contact = Image.new("RGBA", subject.size, (0, 0, 0, 0))
            shadow_contact.putalpha(shadow_contact_alpha)
            try:
                shadow_contact = shadow_contact.filter(ImageFilter.GaussianBlur(radius=2.5))
            except Exception:
                pass
            shift_contact = (5, 10)
            bg.paste(shadow_contact, (px + shift_contact[0], py + shift_contact[1]), shadow_contact)
        bg.paste(subject, (px, py), subject)
    else:
        bg.paste(subject, (px, py))
    return bg


def _generate_six_scenes(
    base_image_path: str,
    out_dir: str,
    width: int = 1280,
    height: int = 720,
    style: Optional[str] = None,
    theme: Optional[str] = None,
    scene_descriptions: Optional[list] = None,
    scene_background_paths: Optional[list] = None,
) -> list:
    """
    抠图后把主体合成到 6 种创意背景上。
    若提供 scene_background_paths（6 张已保存的故事情节背景图路径），则直接加载这 6 张作为每镜背景；
    否则若提供 scene_descriptions 则按描述生成/取图；再否则按风格+主题选用场景图。抠图失败则回退为「原图+6 种华丽底」。
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return []
    if not os.path.isfile(base_image_path):
        return []
    os.makedirs(out_dir, exist_ok=True)
    out_paths = []
    try:
        from PIL import ImageOps
        product = Image.open(base_image_path)
        product = ImageOps.exif_transpose(product)  # 纠正 EXIF 旋转
        product = product.convert("RGB")
        w, h = product.size
        subject_rgba = None

        # 仅做抠图，不强制旋转横图。此前对横图一律旋转 90° 会导致「正立放在地面上的小板凳」等物体在视频里被错误转横，故改为保持原图朝向。
        rembg_session = None
        try:
            from rembg import new_session
            rembg_session = new_session()
        except Exception:
            pass
        subject_rgba = _remove_background(product, session=rembg_session)

        # 竖图/正方：上轻下重视为倒立（头在上应为轻的一侧），旋转 180° 纠正
        if subject_rgba is not None:
            halves = _subject_alpha_halves(subject_rgba)
            if halves and halves["top_sum"] < halves["bottom_sum"]:
                product = product.rotate(180, expand=False)
                subject_rgba = subject_rgba.rotate(180, expand=False)

        use_cutout = subject_rgba is not None
        if use_cutout:
            logger.info("抠图成功，将主体合成到 6 种创意场景（风格: %s，主题: %s）", style or "default", (theme or "")[:20] or "无")
        else:
            logger.info("未抠图，使用原图+背景框合成")

        for i in range(6):
            if scene_background_paths and len(scene_background_paths) >= 6 and os.path.isfile(scene_background_paths[i]):
                bg = _load_and_style_background_image(scene_background_paths[i], width, height, style=style)
                if bg is None:
                    desc = (scene_descriptions[i] if scene_descriptions and i < len(scene_descriptions) else None) or None
                    bg = _draw_creative_background(i, width, height, style=style, theme=theme, scene_description=desc)
            else:
                desc = (scene_descriptions[i] if scene_descriptions and i < len(scene_descriptions) else None) or None
                bg = _draw_creative_background(i, width, height, style=style, theme=theme, scene_description=desc)
            if use_cutout and subject_rgba:
                out_img = _paste_subject_on_bg(bg, subject_rgba, i, width, height)
            else:
                pw, ph = product.size
                scale = min(0.76 * width / pw, 0.76 * height / ph, 1.0)
                sw, sh = int(pw * scale), int(ph * scale)
                product_scaled = product.resize((sw, sh), Image.Resampling.LANCZOS)
                pad = 24
                paste_x = (width - sw - pad * 2) // 2 + pad
                paste_y = (height - sh - pad * 2) // 2 + pad
                x0, y0 = (width - sw - pad * 2) // 2, (height - sh - pad * 2) // 2
                draw = ImageDraw.Draw(bg)
                draw.rounded_rectangle((x0, y0, x0 + sw + pad * 2, y0 + sh + pad * 2), radius=16, fill=(22, 22, 28))
                draw.rounded_rectangle((x0, y0, x0 + sw + pad * 2, y0 + sh + pad * 2), radius=16, outline=(180, 160, 100), width=2)
                bg.paste(product_scaled, (paste_x, paste_y))
                out_img = bg
            p = os.path.join(out_dir, f"scene_{i}.png")
            out_img.save(p, "PNG")
            out_paths.append(p)
        logger.info("已生成 6 张创意场景图: %s", out_dir)
        return out_paths
    except Exception as e:
        logger.warning("生成 6 场景图失败: %s", e)
        for p in out_paths:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        return []


def _get_audio_duration_sec(audio_path: str) -> float:
    """用 ffprobe 获取音频时长（秒），失败返回 5.0"""
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0 and r.stdout:
            return max(0.5, min(60.0, float(r.stdout.decode().strip())))
    except Exception:
        pass
    return 5.0


def _split_script_to_segments(script_text: str, max_segments: int = 6) -> list:
    """
    按完整句/完整从句切分，保证每个镜头每一句都是完整的，不出现两字、几字的碎片。
    切分点：句号、感叹号、问号、逗号；过短片段合并到前一句。
    """
    import re
    text = (script_text or "").strip().replace("\n", " ")
    if not text or len(text) < 2:
        base = (text or "AI 视频工厂").strip()
        return [base] + [""] * (max_segments - 1)
    max_segments = max(1, max_segments)
    # 按句号、感叹号、问号、中英文逗号分句（保留标点在上一句末）
    parts = re.split(r"([。！？，,])", text)
    clauses = []
    i = 0
    while i < len(parts):
        s = parts[i]
        i += 1
        if i < len(parts) and parts[i] in "。！？，,":
            s += parts[i]
            i += 1
        s = s.strip()
        if s:
            clauses.append(s)
    if not clauses:
        clauses = [text]
    # 过短片段（两字、几字）合并到前一句，避免单镜出现碎片
    min_clause_chars = 4
    merged = []
    for c in clauses:
        if merged and len(c) < min_clause_chars and len(merged[-1]) + len(c) < 40:
            merged[-1] += c
        else:
            merged.append(c)
    clauses = merged
    if not clauses:
        return [text[:50].strip() or " "] + [""] * (max_segments - 1)
    n = len(clauses)
    total_chars = sum(len(c) for c in clauses)
    target_per_seg = (total_chars / max_segments) if max_segments else total_chars
    segs = []
    idx = 0
    for seg_i in range(max_segments):
        chunk = []
        chunk_chars = 0
        is_last = seg_i == max_segments - 1
        while idx < n:
            chunk.append(clauses[idx])
            chunk_chars += len(clauses[idx])
            idx += 1
            if is_last:
                continue
            if chunk_chars >= target_per_seg:
                break
        segs.append("".join(chunk) if chunk else "")
    return segs[:max_segments]


# 逗号之间停顿时长（秒）
_COMMA_PAUSE_SEC = 1.0


def _tts_one_segment_with_comma_pause(seg_text: str, voice: Optional[str], run_ffmpeg) -> tuple:
    """
    对一段文案做 TTS；若含逗号则按逗号拆成多句，句与句之间加 1 秒静音，再拼接。
    返回 (本段 wav 路径, 本段总时长)，失败返回 (None, 0)。
    """
    seg_text = (seg_text or "").strip()
    if not seg_text:
        return None, _COMMA_PAUSE_SEC
    # 支持中文逗号、英文逗号，统一按逗号拆句
    parts = [p.strip() for p in seg_text.replace(",", "，").split("，") if p.strip()]
    if not parts:
        return None, _COMMA_PAUSE_SEC
    if len(parts) == 1:
        path = _synthesize_speech_aliyun(parts[0], voice=voice)
        if path and os.path.exists(path):
            return path, max(0.5, _get_audio_duration_sec(path))
        return None, 0
    # 多句：每句 TTS，中间插 1 秒静音后拼接
    wav_paths = []
    durations = []
    for p in parts:
        path = _synthesize_speech_aliyun(p, voice=voice)
        if not path or not os.path.exists(path):
            for fp in wav_paths:
                try:
                    if fp and os.path.exists(fp):
                        os.remove(fp)
                except OSError:
                    pass
            return None, 0
        wav_paths.append(path)
        durations.append(max(0.3, _get_audio_duration_sec(path)))
    out_path = f"/tmp/ai_video_tts_seg_comma_{uuid.uuid4()}.wav"
    list_path = f"/tmp/ai_video_concat_comma_{uuid.uuid4()}.txt"
    silences = []
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for i, wp in enumerate(wav_paths):
                f.write(f"file '{wp}'\n")
                if i < len(wav_paths) - 1:
                    sp = f"/tmp/ai_video_comma_silence_{uuid.uuid4()}_{i}.wav"
                    r = run_ffmpeg(
                        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", str(_COMMA_PAUSE_SEC), "-ac", "1", sp]
                    )
                    if r.returncode != 0 or not os.path.exists(sp):
                        raise RuntimeError("生成逗号静音失败")
                    silences.append(sp)
                    f.write(f"file '{sp}'\n")
        r = run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path])
        for wp in wav_paths:
            try:
                if os.path.exists(wp):
                    os.remove(wp)
            except OSError:
                pass
        for sp in silences:
            try:
                if os.path.exists(sp):
                    os.remove(sp)
            except OSError:
                pass
        if os.path.exists(list_path):
            try:
                os.remove(list_path)
            except OSError:
                pass
        if r.returncode != 0 or not os.path.exists(out_path):
            return None, 0
        total_dur = sum(durations) + (len(parts) - 1) * _COMMA_PAUSE_SEC
        return out_path, max(0.5, total_dur)
    except Exception as e:
        logger.warning("段内逗号拼接失败: %s", e)
        for wp in wav_paths:
            try:
                if wp and os.path.exists(wp):
                    os.remove(wp)
            except OSError:
                pass
        return None, 0


def _generate_tts_per_segment_and_concat(
    segment_texts: list,
    voice: Optional[str],
    run_ffmpeg,
) -> tuple:
    """
    对每段文案生成 TTS（段内逗号处加 1 秒停顿），再按顺序拼接成一条人声轨；
    返回 (拼接后的 wav 路径, 每段时长列表)。任一段失败则返回 (None, None)。
    """
    if not segment_texts or len(segment_texts) != 6:
        return None, None
    segment_paths = []
    segment_durations = []
    inter_sentence_silence_sec = 1.0
    for seg in segment_texts:
        if not (seg or "").strip():
            segment_paths.append(None)
            segment_durations.append(inter_sentence_silence_sec)
            continue
        path, dur = _tts_one_segment_with_comma_pause(seg, voice, run_ffmpeg)
        if path and dur > 0:
            segment_paths.append(path)
            segment_durations.append(dur)
        else:
            for p in segment_paths:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            return None, None
    # 句间停顿：每两句之间加 1 秒静音；返回的 segment_durations 含停顿（末段不含），便于视频/字幕对齐
    for i in range(len(segment_durations) - 1):
        segment_durations[i] += inter_sentence_silence_sec
    # 拼接：concat demuxer 需要统一格式，TTS 为 16k wav；静音用 ffmpeg 生成
    concat_path = f"/tmp/ai_video_tts_concat_{uuid.uuid4()}.wav"
    list_path = f"/tmp/ai_video_concat_list_{uuid.uuid4()}.txt"
    temp_silence_files = []
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for i, p in enumerate(segment_paths):
                if p:
                    f.write(f"file '{p}'\n")
                else:
                    sp = f"/tmp/ai_video_silence_{uuid.uuid4()}_{i}.wav"
                    r = run_ffmpeg(
                        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", str(segment_durations[i]), "-ac", "1", sp]
                    )
                    if r.returncode != 0 or not os.path.exists(sp):
                        raise RuntimeError("生成静音片段失败")
                    temp_silence_files.append(sp)
                    f.write(f"file '{sp}'\n")
                # 每句后插入 1 秒静音（最后一句后不插）
                if i < len(segment_paths) - 1:
                    sp = f"/tmp/ai_video_silence_gap_{uuid.uuid4()}_{i}.wav"
                    r = run_ffmpeg(
                        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", str(inter_sentence_silence_sec), "-ac", "1", sp]
                    )
                    if r.returncode != 0 or not os.path.exists(sp):
                        raise RuntimeError("生成句间静音失败")
                    temp_silence_files.append(sp)
                    f.write(f"file '{sp}'\n")
        r = run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", concat_path])
        if r.returncode != 0 or not os.path.exists(concat_path):
            raise RuntimeError("拼接 TTS 失败")
        for p in segment_paths:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        for sp in temp_silence_files:
            try:
                if os.path.exists(sp):
                    os.remove(sp)
            except OSError:
                pass
        if os.path.exists(list_path):
            try:
                os.remove(list_path)
            except OSError:
                pass
        return concat_path, segment_durations
    except Exception as e:
        logger.warning("按段 TTS 拼接失败，将使用整段 TTS: %s", e)
        for p in segment_paths:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        for f in (list_path, concat_path):
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        return None, None


# ---------- 商用好莱坞大片感 出厂参数（可调）----------
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 25
# 字幕：贴底、与镜头/语音严格对齐，显示时间=该段语音时长
SUBTITLE_BOTTOM_MARGIN_PX = 56
SUBTITLE_FADE_IN_DUR = 0.35       # 字幕淡入稍慢，与语音节奏一致
# 场景背景虚化（加强景深，突出主体 3D 感）；减弱至约 80% 避免过糊
SCENE_BLUR_RADIUS = 6.8
# 暗角：加强中心聚焦与立体感
VIGNETTE_STRENGTH_DEFAULT = 0.58
VIGNETTE_STRENGTH_BLOCKBUSTER = 0.66
# 时长与转场（最短视频 15 秒）
MIN_VIDEO_DURATION_SEC = 15
BLOCKBUSTER_MIN_DURATION_SEC = 15
BLOCKBUSTER_XFADE_DUR = 1.0


def _generate_video_wanxiang(theme: str, script_text: str, style: Optional[str] = None) -> Optional[str]:
    """
    调用阿里万相 2.6（DashScope）文生视频，异步任务轮询完成后下载到本地并返回路径。
    成功返回本地 mp4 路径，失败返回 None，调用方回退 MVP。
    """
    if not DASHSCOPE_API_KEY or not WANXIANG_VIDEO_ENABLED:
        return None
    prompt = (script_text or theme or "高端品牌广告").strip()[:1500]
    if not prompt:
        return None
    url_create = f"{WANXIANG_VIDEO_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
    url_tasks = f"{WANXIANG_VIDEO_BASE}/api/v1/tasks"
    out_path = f"/tmp/wanxiang_video_{uuid.uuid4()}.mp4"
    try:
        import httpx
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                url_create,
                headers={
                    "Authorization": "Bearer %s" % DASHSCOPE_API_KEY,
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json={
                    "model": "wan2.6-t2v",
                    "input": {"prompt": prompt},
                    "parameters": {
                        "size": "1280*720",
                        "duration": 10,
                        "prompt_extend": True,
                        "watermark": False,
                    },
                },
            )
        if r.status_code != 200:
            logger.warning("万相创建任务失败: status=%s body=%s", r.status_code, (r.text or "")[:300])
            return None
        data = r.json()
        task_id = (data.get("output") or {}).get("task_id")
        if not task_id:
            logger.warning("万相返回无 task_id: %s", str(data)[:200])
            return None
        logger.info("万相任务已创建 task_id=%s，轮询结果中...", task_id[:16])
        import time
        for _ in range(40):
            time.sleep(15)
            r2 = httpx.get(
                f"{url_tasks}/{task_id}",
                headers={"Authorization": "Bearer %s" % DASHSCOPE_API_KEY},
                timeout=30.0,
            )
            if r2.status_code != 200:
                continue
            out2 = (r2.json().get("output") or {})
            status = out2.get("task_status")
            if status == "SUCCEEDED":
                video_url = out2.get("video_url")
                if not video_url:
                    break
                with httpx.Client(follow_redirects=True, timeout=60.0) as c:
                    resp = c.get(video_url)
                if resp.status_code != 200:
                    logger.warning("万相视频下载失败: %s", resp.status_code)
                    return None
                with open(out_path, "wb") as f:
                    f.write(resp.content)
                logger.info("万相视频已下载: %s", out_path)
                return out_path
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                logger.warning("万相任务失败: status=%s %s", status, out2.get("message", ""))
                return None
        logger.warning("万相任务轮询超时")
        return None
    except Exception as e:
        logger.warning("万相调用异常: %s", e)
        return None


def _generate_video_mvp(
    theme: str,
    script_text: str,
    image_url: Optional[str] = None,
    image_path: Optional[str] = None,
    voice: Optional[str] = None,
    style: Optional[str] = None,
    bgm: Optional[str] = None,
    scene_descriptions: Optional[list] = None,
) -> str:
    """
    MVP: 背景图 + 字幕 + TTS 配音；视频时长 = 配音时长，声画同步。
    若提供 scene_descriptions（6 个故事情节对应的场景描述），则每镜背景图按该描述生成/选取，故事与画面一致。
    全面优化为广告大片级：1080p、电影感镜头与转场、强暗角、高码率。
    """
    import subprocess

    w, h = VIDEO_WIDTH, VIDEO_HEIGHT
    # 按段 TTS 使用完整文案（最多 400 字），单条字幕/回退用前 80 字
    script_for_tts = (script_text or theme)[:800].replace("\n", " ").strip() or "AI 视频工厂"
    display_text = script_for_tts[:120]
    out_path = f"/tmp/ai_video_{uuid.uuid4()}.mp4"
    text_png = f"/tmp/ai_video_txt_{uuid.uuid4()}.png"
    bg_png = f"/tmp/ai_video_bg_{uuid.uuid4()}.png"
    tts_path = None
    text_png_segments = []  # 按段字幕图，仅 6 场景+按段 TTS 时使用

    def run_ffmpeg(args: list) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, timeout=120, check=False)

    try:
        if not _render_text_to_png(display_text, text_png, width=w, height=h, style=style):
            raise RuntimeError("Pillow 不可用，无法生成字幕图")
        if not os.path.exists(text_png):
            raise RuntimeError("字幕图生成失败")

        # 背景：优先用户图（1080p）；失败时生成主题海报
        has_bg = _prepare_background_image(image_path, image_url, bg_png, width=w, height=h)
        if not has_bg:
            has_bg = _render_theme_poster(theme, display_text, bg_png, width=w, height=h, style=style)
        logger.info("视频背景: has_bg=%s image_path=%s image_url=%s", has_bg, image_path or "(无)", "有" if image_url else "无")

        # 先生成 6 场景图：有故事情节描述时先抓取并保存 6 张对应背景图，再合成每镜（故事与画面一致）
        scene_dir = None
        scene_paths = []
        if has_bg and os.path.exists(bg_png):
            scene_dir = f"/tmp/ai_video_scenes_{uuid.uuid4()}"
            scene_bg_paths = []
            if scene_descriptions and len(scene_descriptions) >= 6:
                scene_bg_paths = _fetch_and_save_story_backgrounds(
                    scene_descriptions, style, theme, w, h, scene_dir
                )
            if len(scene_bg_paths) == 6:
                scene_paths = _generate_six_scenes(
                    bg_png, scene_dir, w, h, style=style, theme=theme,
                    scene_descriptions=None, scene_background_paths=scene_bg_paths,
                )
            else:
                scene_paths = _generate_six_scenes(
                    bg_png, scene_dir, w, h, style=style, theme=theme, scene_descriptions=scene_descriptions
                )

        is_blockbuster = (style or "").strip().lower() == "blockbuster"
        NUM_SCENES = 6
        XFADE_DUR = BLOCKBUSTER_XFADE_DUR if is_blockbuster else 0.8
        use_six_scenes = len(scene_paths) >= NUM_SCENES

        # 真人配音：6 场景时优先按段 TTS，使每段解说与对应场景时间点一致；保留 segment_texts 供按段字幕使用
        segment_durations = None
        segment_texts = None
        if use_six_scenes and ALIYUN_NLS_APPKEY and (script_for_tts or "").strip():
            segment_texts = _split_script_to_segments(script_for_tts, NUM_SCENES)
            tts_path, segment_durations = _generate_tts_per_segment_and_concat(segment_texts, voice, run_ffmpeg)
            if tts_path and segment_durations and len(segment_durations) == NUM_SCENES:
                duration_sec = sum(segment_durations)
                logger.info("使用按段 TTS，语音与场景时间点对齐，总时长 %.1f 秒", duration_sec)
            else:
                tts_path = None
                segment_durations = None
                segment_texts = None
        if tts_path is None or not os.path.exists(tts_path):
            tts_path = _synthesize_speech_aliyun(script_for_tts, voice=voice)
            if tts_path and os.path.exists(tts_path):
                duration_sec = _get_audio_duration_sec(tts_path)
                logger.info("使用阿里云 TTS 配音, 时长 %.1f 秒", duration_sec)
            else:
                if not ALIYUN_NLS_APPKEY:
                    logger.info("阿里云 TTS 未配置，使用静音轨")
                tts_path = None
                duration_sec = 5.0
            segment_durations = None

        # 视频时长至少 15 秒：有配音时若短于 15 秒则补足，无配音时取最短 15 秒
        min_dur = BLOCKBUSTER_MIN_DURATION_SEC if is_blockbuster else MIN_VIDEO_DURATION_SEC
        if tts_path and (segment_durations is None or len(segment_durations) != NUM_SCENES):
            duration_sec = max(min_dur, float(duration_sec))
        elif tts_path and segment_durations and len(segment_durations) == NUM_SCENES:
            duration_sec = max(min_dur, sum(segment_durations))
        else:
            duration_sec = max(min_dur, float(duration_sec))
        duration_str = str(duration_sec)
        n_frames = max(1, int(round(duration_sec * VIDEO_FPS)))

        # BGM：若存在 assets/bgm/default.mp3 或 tech.mp3 则混流（人声主、BGM 约 25%）；bgm 可覆盖：none=不用，default/tech/blockbuster=指定
        bgm_path = _get_bgm_path(style, duration_sec, bgm_override=bgm)
        if bgm_path:
            logger.info("使用 BGM 混流: %s", bgm_path)

        # 广告大片级输出：1080p、高码率、高质量音频
        out_opts = [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS),
            "-crf", "16", "-preset", "slow", "-b:v", "8M",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
            "-t", duration_str, "-movflags", "+faststart", "-y", out_path,
        ]

        # 6 场景 + 按段字幕时共 12 个视频输入(0-5 场景, 6-11 字幕)，人声/BGM 顺延
        n_video_inputs = 12 if (use_six_scenes and segment_durations and segment_texts and len(segment_texts) == NUM_SCENES) else (7 if use_six_scenes else 2)
        voice_idx = n_video_inputs
        bgm_idx = n_video_inputs + 1
        # BGM 淡入淡出时长，与视频起止对齐、不抢人声
        bgm_fade_in = 1.2
        bgm_fade_out = min(2.0, max(0.8, duration_sec * 0.12))
        bgm_fade_out_st = max(0, duration_sec - bgm_fade_out)

        if tts_path:
            audio_input = ["-i", tts_path]
            if bgm_path:
                # 人声 + BGM 混流：BGM 淡入/淡出与视频节点一致，音量约 22% 不压人声
                filter_a = (
                    f"[{voice_idx}:a]atrim=0:{duration_sec},apad=whole_dur={duration_sec}[vo];"
                    f"[{bgm_idx}:a]atrim=0:{duration_sec},afade=t=in:st=0:d={bgm_fade_in},afade=t=out:st={bgm_fade_out_st}:d={bgm_fade_out},volume=0.26,apad=whole_dur={duration_sec}[b];"
                    "[vo][b]amix=inputs=2:duration=first:dropout_transition=1[a]"
                )
                audio_input = audio_input + ["-stream_loop", "-1", "-t", duration_str, "-i", bgm_path]
            else:
                filter_a = f"[{voice_idx}:a]atrim=0:{duration_sec},apad=whole_dur={duration_sec}[a]"
            map_opts = ["-map", "[v]", "-map", "[a]"]
        else:
            # 无 TTS：静音轨与 BGM 的索引紧跟视频输入之后（与 voice_idx/bgm_idx 一致）
            audio_input = ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo", "-t", duration_str]
            if bgm_path:
                filter_a = (
                    f"[{voice_idx}:a]apad=whole_dur={duration_sec}[silent];"
                    f"[{bgm_idx}:a]atrim=0:{duration_sec},afade=t=in:st=0:d={bgm_fade_in},afade=t=out:st={bgm_fade_out_st}:d={bgm_fade_out},volume=0.32,apad=whole_dur={duration_sec}[b];"
                    "[silent][b]amix=inputs=2:duration=first:dropout_transition=1[a]"
                )
                audio_input = audio_input + ["-stream_loop", "-1", "-t", duration_str, "-i", bgm_path]
                map_opts = ["-map", "[v]", "-map", "[a]"]
            else:
                filter_a = ""
                map_opts = ["-map", "[v]", "-map", "%d:a" % voice_idx]

        s_param = f"{w}x{h}"
        if use_six_scenes:
            # 6 张场景图；有 segment_durations 时每场景时长与对应解说段一致，否则均分
            if segment_durations and len(segment_durations) == NUM_SCENES:
                clip_durs = [max(0.5, float(d)) for d in segment_durations]
                # xfade 会使总视频时长 = sum(clip_durs) - (NUM_SCENES-1)*XFADE_DUR，补到最后一镜使与音频 duration_sec 一致
                pad = (NUM_SCENES - 1) * XFADE_DUR
                if pad > 0:
                    clip_durs[NUM_SCENES - 1] = clip_durs[NUM_SCENES - 1] + pad
            else:
                clip_dur = (duration_sec + (NUM_SCENES - 1) * XFADE_DUR) / NUM_SCENES
                clip_durs = [clip_dur] * NUM_SCENES
            # 按段字幕：语音、文字、视频时间点一致——每段对应一张字幕图并在该段时间内叠加
            use_per_segment_subtitles = (
                segment_durations is not None
                and segment_texts is not None
                and len(segment_texts) == NUM_SCENES
            )
            if use_per_segment_subtitles:
                for k in range(NUM_SCENES):
                    seg_png = f"/tmp/ai_video_txt_seg_{uuid.uuid4()}_{k}.png"
                    if _render_text_to_png(
                        (segment_texts[k] or " ").strip() or " ",
                        seg_png,
                        width=w,
                        height=h,
                        style=style,
                    ):
                        text_png_segments.append(seg_png)
                    else:
                        text_png_segments.clear()
                        break
            video_inputs = []
            for k, p in enumerate(scene_paths[:NUM_SCENES]):
                video_inputs += ["-loop", "1", "-t", str(clip_durs[k]), "-i", p]
            if use_per_segment_subtitles and len(text_png_segments) == NUM_SCENES:
                for k in range(NUM_SCENES):
                    video_inputs += ["-loop", "1", "-t", str(clip_durs[k]), "-i", text_png_segments[k]]
            else:
                video_inputs += ["-loop", "1", "-t", duration_str, "-i", text_png]
            zoom_end = 1.11 if is_blockbuster else 1.08
            zoom_rate = 0.00022 if is_blockbuster else 0.00018
            pan_x, pan_y = (0.06, 0.03) if is_blockbuster else (0.04, 0.02)
            zoom_parts = []
            for k in range(NUM_SCENES):
                clip_frames_k = max(1, int(round(clip_durs[k] * VIDEO_FPS)))
                zoom_parts.append(
                    "[%d:v]zoompan=z='min(1+%s*on,%s)':x='iw/2-(iw/2/zoom)+%s*on':y='ih/2-(ih/2/zoom)+%s*on':d=%d:s=%s[z%d]" % (k, zoom_rate, zoom_end, pan_x, pan_y, clip_frames_k, s_param, k)
                )
            xfade_parts = []
            offset_accum = 0.0
            for k in range(NUM_SCENES - 1):
                in_left = "[z0]" if k == 0 else "[v%02d]" % k
                in_right = "[z%d]" % (k + 1)
                out_label = "[v%02d]" % (k + 1)
                offset_accum += clip_durs[k]
                offset = offset_accum - (k + 1) * XFADE_DUR
                xfade_parts.append(
                    "%s%sxfade=transition=fade:duration=%s:offset=%s%s" % (in_left, in_right, XFADE_DUR, offset, out_label)
                )
            # 暗角：好莱坞更强，聚焦中心
            vignette = VIGNETTE_STRENGTH_BLOCKBUSTER if is_blockbuster else VIGNETTE_STRENGTH_DEFAULT
            base_v = (
                ";".join(zoom_parts) + ";"
                + ";".join(xfade_parts) + ";"
                + "[v05]geq=lum='lum(X,Y)*(1-%.2f*(pow(X-W/2,2)+pow(Y-H/2,2))/(pow(W/2,2)+pow(H/2,2)))':cb='cb(X,Y)':cr='cr(X,Y)'[v05b]"
                % vignette
            )
            if use_per_segment_subtitles and len(text_png_segments) == NUM_SCENES:
                # 字幕与语音节点严格对齐：有 TTS 分段时用 segment_durations 作为每段字幕的起止，与播放一致
                if segment_durations and len(segment_durations) == NUM_SCENES:
                    sub_starts = [0.0]
                    for k in range(1, NUM_SCENES):
                        sub_starts.append(sub_starts[-1] + segment_durations[k - 1])
                    sub_ends = [sub_starts[k] + segment_durations[k] for k in range(NUM_SCENES)]
                else:
                    sub_starts = [0.0]
                    for k in range(1, NUM_SCENES):
                        sub_starts.append(sub_starts[-1] + clip_durs[k - 1] - XFADE_DUR)
                    sub_ends = []
                    for k in range(NUM_SCENES):
                        d = clip_durs[k] - (XFADE_DUR if k < NUM_SCENES - 1 else 0)
                        sub_ends.append(sub_starts[k] + max(SUBTITLE_FADE_IN_DUR + 0.08, d))
                overlay_parts = []
                for k in range(NUM_SCENES):
                    overlay_parts.append(
                        "[%d:v]fade=t=in:st=0:d=%s:alpha=1[t%d];"
                        % (NUM_SCENES + k, SUBTITLE_FADE_IN_DUR, k)
                    )
                # 统一底部安全区，不挡画面、适合商用
                sub_y_expr = "H-h-%d" % SUBTITLE_BOTTOM_MARGIN_PX
                prev = "[v05b]"
                for k in range(NUM_SCENES):
                    t_start = sub_starts[k]
                    t_end = sub_ends[k]
                    enable_expr = "between(t,%s,%s)" % (t_start, t_end)
                    out_label = "[v]" if k == NUM_SCENES - 1 else "[va%d]" % k
                    overlay_parts.append(
                        "%s[t%d]overlay=(W-w)/2:%s:enable='%s'%s;"
                        % (prev, k, sub_y_expr, enable_expr, out_label)
                    )
                    prev = out_label
                filter_v = base_v + ";" + "".join(overlay_parts).rstrip(";")
            else:
                # 单条全片字幕：统一底部安全区
                sub_pos = "(W-w)/2:H-h-%d" % SUBTITLE_BOTTOM_MARGIN_PX
                filter_v = (
                    base_v + ";"
                    + "[%d:v]fade=t=in:st=0:d=%s:alpha=1[txt];[v05b][txt]overlay=%s[v]" % (NUM_SCENES, SUBTITLE_FADE_IN_DUR, sub_pos)
                )
        elif has_bg and os.path.exists(bg_png):
            video_inputs = ["-loop", "1", "-i", bg_png, "-loop", "1", "-i", text_png]
            # 广告大片感：缓慢 zoom；好莱坞大片 1→1.15 推进更强
            z_end = 1.15 if is_blockbuster else 1.12
            z_rate = 0.00026 if is_blockbuster else 0.00022
            sub_pos = "(W-w)/2:H-h-%d" % SUBTITLE_BOTTOM_MARGIN_PX
            v_strength = VIGNETTE_STRENGTH_BLOCKBUSTER if is_blockbuster else VIGNETTE_STRENGTH_DEFAULT
            filter_v = (
                f"[0:v]zoompan=z='min(1+{z_rate}*on,{z_end})':"
                f"x='iw/2-(iw/2/zoom)+0.06*on':y='ih/2-(ih/2/zoom)+0.03*on':"
                f"d={n_frames}:s={s_param}[v0];"
                "[v0]geq=lum='lum(X,Y)*(1-%.2f*(pow(X-W/2,2)+pow(Y-H/2,2))/(pow(W/2,2)+pow(H/2,2)))':cb='cb(X,Y)':cr='cr(X,Y)'[v0b];"
                "[1:v]fade=t=in:st=0:d=%s:alpha=1[txt];[v0b][txt]overlay=%s[v]" % (v_strength, SUBTITLE_FADE_IN_DUR, sub_pos)
            )
        else:
            video_inputs = [
                "-f", "lavfi", "-i", f"color=c=0x1a2b3c:s={s_param}:d={duration_str}",
                "-loop", "1", "-i", text_png,
            ]
            sub_pos = "(W-w)/2:H-h-%d" % SUBTITLE_BOTTOM_MARGIN_PX
            filter_v = "[0:v][1:v]overlay=%s:shortest=1[v]" % sub_pos
        filter_complex = filter_v + ((";" + filter_a) if filter_a else "")
        cmd = ["ffmpeg"] + video_inputs + audio_input + ["-filter_complex", filter_complex] + map_opts + out_opts
        r = run_ffmpeg(cmd)
        if r.returncode == 0:
            return out_path
        err = (r.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg 失败 (exit {r.returncode}): {err[:500]}")
    except FileNotFoundError as e:
        raise RuntimeError("未检测到 FFmpeg，请安装: brew install ffmpeg") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"FFmpeg 执行超时: {e}") from e
    finally:
        for p in (text_png, bg_png):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        for p in text_png_segments:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        for p in scene_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        if scene_dir and os.path.isdir(scene_dir):
            try:
                import shutil
                shutil.rmtree(scene_dir, ignore_errors=True)
            except OSError:
                pass
        if tts_path and os.path.exists(tts_path):
            try:
                os.remove(tts_path)
            except OSError:
                pass

    # 备用: MoviePy（当前由上面无字幕 fallback 保证成功，此处保留供后续可选）
    try:
        import moviepy.editor as mpy
        import numpy as np

        duration = 5
        fps = 24
        w, h = 1280, 720

        def make_frame(t):
            r = int(30 + (t / duration) * 50)
            g = int(60 + (t / duration) * 40)
            b = int(100 + (t / duration) * 80)
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:, :, 0] = min(r, 255)
            frame[:, :, 1] = min(g, 255)
            frame[:, :, 2] = min(b, 255)
            return frame

        clip = mpy.VideoClip(make_frame, duration=duration)
        clip = clip.set_fps(fps)
        txt_clip = mpy.TextClip(
            f"AI 视频工厂\n\n{display_text}",
            fontsize=36,
            color="white",
            font="Arial",
        )
        txt_clip = txt_clip.set_duration(duration).set_position("center")
        video = mpy.CompositeVideoClip([clip, txt_clip])
        out_path = f"/tmp/ai_video_{uuid.uuid4()}.mp4"
        video.write_videofile(out_path, fps=fps, codec="libx264", audio=False)
        video.close()
        return out_path

    except ImportError:
        raise RuntimeError("未安装 MoviePy 且 FFmpeg 不可用，请安装: brew install ffmpeg")


def _upload_to_s3(file_path: str, user_id: int) -> str:
    """上传到 S3/MinIO，或本地试用时保存到 LOCAL_VIDEO_DIR"""
    if os.getenv("LOCAL_STORAGE") == "1":
        import shutil
        local_dir = os.getenv("LOCAL_VIDEO_DIR", "./static/videos")
        os.makedirs(local_dir, exist_ok=True)
        fname = f"{uuid.uuid4()}.mp4"
        dest = os.path.join(local_dir, fname)
        shutil.copy2(file_path, dest)
        base = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
        return f"{base}/static/videos/{fname}"
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS,
        aws_secret_access_key=S3_SECRET,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )

    try:
        client.head_bucket(Bucket=S3_BUCKET)
    except Exception:
        client.create_bucket(Bucket=S3_BUCKET)

    key = f"videos/{user_id}/{uuid.uuid4()}.mp4"
    client.upload_file(file_path, S3_BUCKET, key)
    return f"{S3_ENDPOINT_URL}/{S3_BUCKET}/{key}"
