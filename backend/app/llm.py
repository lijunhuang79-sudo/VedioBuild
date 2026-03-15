"""
DeepSeek API 调用（兼容 OpenAI Chat Completions 接口）
用于生成视频文案、脚本、字幕文本
"""
from typing import Optional
import httpx
from .config import get_settings

settings = get_settings()


def generate_video_script(theme: str, image_description: Optional[str] = None) -> str:
    """
    根据主题（及可选图片描述）生成一段短视频文案/旁白，用于视频字幕。
    若未配置 API Key 则返回主题本身。
    """
    if not settings.deepseek_api_key:
        return theme[:200] if len(theme) > 200 else theme

    prompt = f"""你是一个短视频文案助手。根据用户给出的视频主题，生成一段适合作为短视频字幕或旁白的文案。
要求：
- 1～3 句话，简洁有力，适合 5～15 秒视频
- 直接输出文案内容，不要加「文案：」等前缀
- 中文

视频主题：{theme}
"""
    if image_description:
        prompt += f"\n用户上传的图片描述：{image_description}"

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.deepseek_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,
                    "temperature": 0.7,
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
            return text[:500] if text else theme[:200]
    except Exception:
        return theme[:200] if len(theme) > 200 else theme
