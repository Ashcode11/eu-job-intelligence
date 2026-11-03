import type { Metadata } from "next";
import type { ReactNode } from "react";

import Shell from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "EU Job Intelligence",
  description: "Self-hosted multi-agent European job search",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
