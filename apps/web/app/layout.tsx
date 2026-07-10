import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Companion",
  description: "Eldercare AI companion runtime for care tasks, fraud warning, and traceability.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
