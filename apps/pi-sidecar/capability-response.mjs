export const ELDER_CAPABILITY_RESPONSE =
  "我可以帮您处理照护事项、联系家人，也可以记住您的长期偏好。";

export function capabilityResponseFor(message) {
  const text = String(message ?? "").normalize("NFKC").trim().toLowerCase();
  if (!text) return "";

  const compact = text.replace(/[\s\p{P}\p{S}_]+/gu, "");
  const directChineseQuestion = [
    /^(?:请问)?(?:你|您)?(?:都)?(?:有哪些|有什么|有些什么|有啥)(?:tools?|functions?|工具|功能|能力)(?:呢|呀|啊|可以用)?$/,
    /^(?:请问)?(?:你|您)?(?:能|可以|会)(?:帮我)?(?:做|干)(?:些|点)?(?:哪些(?:事|事情)?|什么|啥)(?:呀|呢|啊)?$/,
    /^(?:请)?(?:介绍|列出|说说)(?:一下)?(?:你|您)?(?:的)?(?:tools?|functions?|工具|功能|能力)$/,
    /^(?:你|您)(?:的)?(?:tools?|functions?|工具|功能|能力)(?:有|是|包括)?(?:哪些|什么|啥)$/,
    /^(?:请问)?(?:你|您)?(?:都)?能(?:做|干)(?:些)?什么(?:呀|呢|啊)?$/,
  ].some((pattern) => pattern.test(compact));
  if (directChineseQuestion) return ELDER_CAPABILITY_RESPONSE;

  const mentionsCapability =
    /tools?|functions?|工具|功能|能力|features?|capabilit(?:y|ies)/.test(compact);
  const asksQuestion =
    /哪些|什么|啥|介绍|列出|说说|what|which|list|show|can|do|have/.test(compact);
  const asksAboutAssistant =
    /(?:你|您)(?:都)?(?:有(?:哪些|什么|啥)|具备|支持|提供)/.test(compact) ||
    /(?:你|您)(?:的)?(?:tools?|functions?|工具|功能|能力|features?|capabilit(?:y|ies))/.test(
      compact,
    ) ||
    /your(?:tools?|functions?|features?|capabilit(?:y|ies))/.test(compact) ||
    /you(?:have|offer|support|use)/.test(compact);
  if (mentionsCapability && asksQuestion && asksAboutAssistant) {
    return ELDER_CAPABILITY_RESPONSE;
  }

  if (/^whatcanyoudo(?:forme)?$/.test(compact)) {
    return ELDER_CAPABILITY_RESPONSE;
  }
  return "";
}
