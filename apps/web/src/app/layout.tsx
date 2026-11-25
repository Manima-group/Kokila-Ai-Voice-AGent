import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kokila — Intelligence that speaks",
  description: "Kokila voice assistant by Manima AI-Tech Solutions",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#f2c230", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
