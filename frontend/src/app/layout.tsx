import type { Metadata } from "next";

import { Providers } from "@/lib/auth";

import "./globals.css";

export const metadata: Metadata = {
  title: "Kokila — AI Voice Agents for Indian Businesses",
  description: "Multilingual AI voice agents for inbound calls, consent-based outbound campaigns, CRM and appointments. By Manima AI-Tech Solutions.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
