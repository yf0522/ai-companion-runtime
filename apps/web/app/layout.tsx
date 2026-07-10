import type { Metadata } from "next";
import ProductProvider from "@/components/ProductProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "Companion",
  description: "Real-time elder companion, family care coordination, and accountable AI operations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" data-theme="light">
      <body>
        <ProductProvider>{children}</ProductProvider>
      </body>
    </html>
  );
}
