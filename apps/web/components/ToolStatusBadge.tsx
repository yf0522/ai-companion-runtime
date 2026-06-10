interface Props {
  tool: string;
  status: "calling" | "success" | "failed";
}

const STATUS_CONFIG = {
  calling: { bg: "bg-yellow-100", text: "text-yellow-700", label: "调用中" },
  success: { bg: "bg-green-100", text: "text-green-700", label: "成功" },
  failed: { bg: "bg-red-100", text: "text-red-700", label: "失败" },
};

export default function ToolStatusBadge({ tool, status }: Props) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.calling;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${config.bg} ${config.text}`}
    >
      {status === "calling" && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-yellow-500" />
      )}
      🔧 {tool}: {config.label}
    </span>
  );
}
