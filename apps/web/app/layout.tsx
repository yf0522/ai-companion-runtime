import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Companion",
  description: "Your AI Companion for emotional support and daily assistance",
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
