"use client";

import { useChatStore } from "@/stores/chatStore";
import Link from "next/link";
import { usePathname } from "next/navigation";

interface Props {
  isOpen: boolean;
  onToggle: () => void;
}

export default function Sidebar({ isOpen, onToggle }: Props) {
  const clearMessages = useChatStore((s) => s.clearMessages);
  const pathname = usePathname();

  const navItems = [
    { href: "/chat", label: "聊天" },
    { href: "/notifications", label: "家属通知" },
  ];

  if (!isOpen) return null;

  return (
    <div className="flex h-full w-[260px] flex-shrink-0 flex-col bg-[#171717] text-[#ececec]">
      {/* Header */}
      <div className="border-b border-white/[0.08] p-3">
        <button
          onClick={clearMessages}
          className="flex w-full items-center gap-2 rounded-lg border border-white/[0.15] px-3.5 py-2.5 text-[13px] text-[#ececec] transition hover:bg-white/[0.08]"
        >
          <span className="text-base">+</span>
          <span>新建聊天</span>
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto p-2">
        <div className="px-2 pb-1 pt-2 text-[11px] font-medium text-white/40">
          今天
        </div>
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`mb-px block truncate rounded-lg px-3 py-2 text-[13px] transition ${
              pathname === item.href
                ? "bg-white/[0.16] text-white"
                : "text-white/80 hover:bg-white/[0.08]"
            }`}
          >
            {item.label}
          </Link>
        ))}
        <div className="mt-2 px-2 pb-1 pt-2 text-[11px] font-medium text-white/40">
          会话
        </div>
        <div className="mb-px cursor-pointer truncate rounded-lg bg-white/[0.12] px-3 py-2 text-[13px] text-white">
          当前对话
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-white/[0.08] p-3">
        <div className="flex cursor-pointer items-center gap-2.5 rounded-lg p-2 transition hover:bg-white/[0.08]">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-indigo-400 to-purple-500 text-xs font-semibold text-white">
            U
          </div>
          <span className="text-[13px]">User</span>
        </div>
      </div>
    </div>
  );
}
