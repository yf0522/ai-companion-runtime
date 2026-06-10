interface Props {
  level: string;
  message: string;
}

export default function RiskAlertBanner({ level, message }: Props) {
  const isHigh = level === "critical" || level === "high";
  return (
    <div
      className={`rounded-lg border p-4 ${
        isHigh
          ? "border-red-300 bg-red-50 text-red-800"
          : "border-yellow-300 bg-yellow-50 text-yellow-800"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="text-lg">{isHigh ? "⚠️" : "💛"}</span>
        <span className="text-sm font-medium">
          {isHigh ? "安全提醒" : "关怀提示"}
        </span>
      </div>
      {message && <p className="mt-2 text-sm">{message}</p>}
    </div>
  );
}
