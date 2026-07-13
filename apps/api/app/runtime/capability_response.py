from __future__ import annotations

import re
import unicodedata

ELDER_CAPABILITY_RESPONSE = "我可以帮您处理照护事项、联系家人，也可以记住您的长期偏好。"


def capability_response_for(message: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(message or "")).strip().lower()
    if not text:
        return ""
    compact = re.sub(r"[\s\W_]+", "", text)
    patterns = (
        r"^(?:请问)?(?:你|您)?(?:都)?(?:有哪些|有什么|有些什么|有啥)(?:tools?|functions?|工具|功能|能力)(?:呢|呀|啊|可以用)?$",
        r"^(?:请问)?(?:你|您)?(?:能|可以|会)(?:帮我)?(?:做|干)(?:些|点)?(?:哪些(?:事|事情)?|什么|啥)(?:呀|呢|啊)?$",
        r"^(?:请问)?(?:你|您)?(?:都)?能(?:做|干)(?:些)?什么(?:呀|呢|啊)?$",
        r"^(?:请)?(?:介绍|列出|说说)(?:一下)?(?:你|您)?(?:的)?(?:tools?|functions?|工具|功能|能力)$",
        r"^(?:你|您)(?:的)?(?:tools?|functions?|工具|功能|能力)(?:有|是|包括)?(?:哪些|什么|啥)$",
        r"^whatcanyoudo(?:forme)?$",
        r"^whattoolsdoyouhave$",
        r"^whatareyourcapabilit(?:y|ies)$",
    )
    if any(re.fullmatch(pattern, compact) for pattern in patterns):
        return ELDER_CAPABILITY_RESPONSE
    mentions_capability = bool(re.search(
        r"tools?|functions?|features?|capabilit(?:y|ies)|工具|功能|能力", compact
    ))
    asks_question = bool(re.search(
        r"what|which|list|show|can|do|have|哪些|什么|啥|介绍|列出", compact
    ))
    asks_about_assistant = bool(re.search(
        r"your(?:tools?|functions?|features?|capabilit(?:y|ies))|"
        r"you(?:have|offer|support|use)|(?:你|您).*(?:工具|功能|能力|tools?)",
        compact,
    ))
    if mentions_capability and asks_question and asks_about_assistant:
        return ELDER_CAPABILITY_RESPONSE
    return ""
