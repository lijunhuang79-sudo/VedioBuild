# -*- coding: utf-8 -*-
"""
故事化广告 Skill：拍广告如讲故事，把主题融入故事，抓取对应故事情节的背景图并嵌入每个镜头。

流程（下次可直接调用本模块）：
  1. 生成故事文案 + 6 个故事情节对应的场景视觉描述（DeepSeek）
  2. 文案结尾含一句总结：数量+单位+主题名（如一款小板凳、一张高端沙发），作为视频最后一句话
  3. 按描述抓取/生成 6 张背景图并保存到本次任务目录（即梦或 URL）
  4. 生成视频时显式加载这 6 张图作为每镜背景，与旁白、字幕一致

调用方式（脚本/API/定时任务）：
  from worker.story_ad_skill import run_story_ad_skill
  video_path = run_story_ad_skill(
      theme="高端护肤品",
      style="blockbuster",
      image_path="/path/to/product.jpg",
  )

Celery 任务已默认走本 Skill，无需改任务代码即可使用上述流程。
"""
from typing import Optional

# 避免循环导入：skill 在 worker 包内，tasks 为同包模块
def run_story_ad_skill(
    theme: str,
    image_path: Optional[str] = None,
    image_url: Optional[str] = None,
    voice: Optional[str] = None,
    style: Optional[str] = None,
    bgm: Optional[str] = None,
    script_text: Optional[str] = None,
    scene_descriptions: Optional[list] = None,
) -> str:
    """
    执行「故事化广告」全流程：生成故事文案与 6 镜场景描述 → 抓取并保存 6 张对应背景图 → 生成视频并嵌入每镜背景。

    :param theme: 视频主题（如产品名、品牌卖点）
    :param image_path: 本地主题/产品图路径，用于抠图合成
    :param image_url: 主题图 URL，可选
    :param voice: TTS 音色
    :param style: 风格（blockbuster/tech/默认等）
    :param bgm: 背景音乐（none/default/tech/...）
    :param script_text: 若提供则跳过文案生成，仅用 scene_descriptions 抓背景（若未提供则仍会生成故事文案）
    :param scene_descriptions: 若提供且长度为 6，则直接用作 6 镜场景描述，跳过文案中的 scenes 解析
    :return: 生成视频的本地路径
    """
    from worker.tasks import (
        _generate_story_script_with_deepseek,
        _generate_video_mvp,
    )
    import logging
    logger = logging.getLogger("worker")

    if not theme or not str(theme).strip():
        raise ValueError("theme 不能为空")

    # 1) 故事文案 + 6 镜场景描述
    if script_text is None or (scene_descriptions is None or len(scene_descriptions) != 6):
        story = _generate_story_script_with_deepseek(theme=theme, style=style)
        if script_text is None:
            script_text = story.get("script") or theme[:200]
        if scene_descriptions is None or len(scene_descriptions) != 6:
            scene_descriptions = story.get("scenes") if isinstance(story.get("scenes"), list) and len(story.get("scenes", [])) >= 6 else None
    logger.info("故事化广告 Skill: 文案与场景描述已就绪，共 %d 镜场景", len(scene_descriptions) if scene_descriptions else 0)

    # 2) 生成视频（内部先抓取并保存 6 张故事情节背景图到任务目录，再合成每镜时显式调用这 6 张图）
    out_path = _generate_video_mvp(
        theme=theme,
        script_text=script_text,
        image_url=image_url,
        image_path=image_path,
        voice=voice,
        style=style,
        bgm=bgm,
        scene_descriptions=scene_descriptions,
    )
    return out_path
