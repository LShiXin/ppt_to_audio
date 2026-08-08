import asyncio
from openai import OpenAI
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL


client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


WORD_COUNT_DESC = {
    "": "100-300",
    "100-200": "100-200",
    "300-400": "300-400",
    "400-500": "400-500",
}


def build_slide_prompt(
    slide: dict,
    topic: str,
    reference_texts: list[str],
    word_count: str = "",
) -> str:
    ref_section = ""
    if reference_texts:
        joined = "\n---\n".join(reference_texts)
        ref_section = f"""## 参考材料
以下为配套参考资料，请结合内容撰写讲稿：
{joined}
"""

    wc = WORD_COUNT_DESC.get(word_count, "100-300")

    prompt = f"""请根据以下课程信息，撰写对应小节的口播讲稿（旁白）。

## 课程主题
{topic or "请结合内容自行提炼"}

{ref_section}
## 当前小节核心信息
**小节主题**: {slide.get('title', '')}
**核心知识点**: {slide.get('content', '')}
**补充提示**: {slide.get('notes', '')}

## 撰写要求
1. 生成一段自然的授课口播稿，贴合真人线下/录播课的连贯授课逻辑，自然流畅地拆解知识点
2. 语言流畅有讲解感，禁止生硬复述原文；知识点少则简洁带过，内容多则重点拆解核心要点
3. 讲稿长度约 {wc} 字，确保知识点讲解清晰
4. 讲稿中所有阿拉伯数字转换为中文表述（例如 123 → 一百二十三，2024 年 → 二零二四年），确保语音朗读准确
5. 全程禁止出现「本页 PPT」「这一页」「接下来看这页」等生硬页面指代，以课程内容本身的逻辑自然展开，符合真人授课语境

## 输出格式
请直接返回讲稿文本，不要加引号或其他修饰。"""

    return prompt


async def _call_llm(prompt: str, model: str = "") -> str:
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=model or DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是专业的课程口播讲稿撰写专家，负责为系列课程逐页撰写配套授课旁白。讲稿需贴合真人线下/录播课的连贯授课逻辑，自然流畅地拆解知识点；单页内容既能独立成段也能与前后自然衔接，全程禁止生硬提及页面相关的指代表述。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=4096,
                extra_body={"thinking": {"type": "enabled"}},
            )
        )
    except Exception as e:
        raise RuntimeError(f"AI讲稿生成API调用失败: {e}") from e

    content = response.choices[0].message.content or ""
    return content.strip().strip('"').strip("'")


async def generate_slide_script(
    slide: dict,
    topic: str,
    reference_texts: list[str],
    word_count: str = "",
    model: str = "",
) -> str:
    prompt = build_slide_prompt(slide, topic, reference_texts, word_count)
    return await _call_llm(prompt, model)


async def generate_script(
    slides: list[dict],
    topic: str,
    reference_texts: list[str],
    word_count: str = "",
    model: str = "",
) -> list[dict]:
    results = []
    for s in slides:
        try:
            narration = await generate_slide_script(s, topic, reference_texts, word_count, model)
            results.append({"slide": s["slide_number"], "narration": narration})
        except Exception:
            title = s.get("title") or ""
            content_s = s.get("content") or ""
            results.append({
                "slide": s["slide_number"],
                "narration": f"第{s['slide_number']}页的内容是：{title}。{content_s[:100]}"
            })
    return results


async def generate_topic(slides: list[dict]) -> str:
    slides_summary = "\n".join(
        f"第{s['slide_number']}页: {s.get('title', '')}" for s in slides if s.get('title')
    )

    prompt = f"""根据以下PPT的标题列表，提炼出一个简洁的课程主题（15字以内）。

PPT内容:
{slides_summary}

请直接返回主题文本，不要加引号或其他修饰。"""

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个课程策划助手，直接返回简洁的课程主题。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=200,
            )
        )
    except Exception as e:
        raise RuntimeError(f"AI主题生成API调用失败: {e}") from e

    topic = response.choices[0].message.content or ""
    return topic.strip().strip('"').strip("'")
