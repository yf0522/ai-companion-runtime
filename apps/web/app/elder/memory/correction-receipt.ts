export function memoryCorrectionReceipt(
  consentStatus: string,
  retentionStatus?: string | null,
): string {
  if (retentionStatus === "expired") {
    return "记忆内容已更新，但保留期已经结束，仍不会用于陪伴。";
  }
  if (consentStatus === "granted") {
    return "记忆内容已按你的修改更新。之后会使用新内容。";
  }
  if (consentStatus === "pending" || consentStatus === "legacy_unverified") {
    return "记忆内容已更新；等你同意保留后，陪伴助手才会使用它。";
  }
  return "记忆内容已更新，但当前仍不会用于陪伴。";
}
