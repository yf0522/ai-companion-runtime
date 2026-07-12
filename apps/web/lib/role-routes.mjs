export const ROLE_NAV = {
  elder: [
    { href: "/elder/companion", label: "陪伴", description: "对话与照护确认" },
    { href: "/elder/today", label: "今日事项", description: "当前提醒和确认记录" },
    { href: "/elder/help", label: "帮助", description: "联系家人或人工支持" },
    { href: "/elder/memory", label: "记忆与隐私", description: "长期记忆同意与本机记录" },
  ],
  family: [
    { href: "/family/overview", label: "概览", description: "需要关注的事项" },
    { href: "/family/tasks", label: "照护任务", description: "创建和管理照护任务" },
    { href: "/family/alerts", label: "告警", description: "风险事件和通知状态" },
    { href: "/family/people", label: "人员权限", description: "照护圈成员和授权范围" },
    { href: "/family/contacts", label: "联系人", description: "已验证联系人和投递顺序" },
    { href: "/family/readiness", label: "就绪检查", description: "家庭试点上线条件" },
    { href: "/family/summary", label: "摘要", description: "授权范围内的照护摘要" },
  ],
  operator: [
    { href: "/ops/care", label: "照护队列", description: "未解决事项和人工处理" },
    { href: "/ops/platform", label: "平台就绪", description: "运行依赖、证据时效和修复责任" },
    { href: "/ops/households/readiness", label: "家庭就绪", description: "家庭、联系人和设备状态" },
    { href: "/ops/traces", label: "追踪", description: "决策、延迟和投递证据" },
  ],
};

export function normalizeRole(role) {
  if (role === "family") return "family";
  if (role === "operator" || role === "admin" || role === "ops") return "operator";
  return "elder";
}

export function defaultRouteForRole(role) {
  const normalized = normalizeRole(role);
  if (normalized === "family") return "/family/overview";
  if (normalized === "operator") return "/ops/care";
  return "/elder/companion";
}

export function navForRole(role) {
  return ROLE_NAV[normalizeRole(role)];
}
