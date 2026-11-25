import type { NextConfig } from "next";

const apiOrigin = process.env.KOKILA_API_ORIGIN ?? "http://localhost:8000";

// Strict CSP. Embedding origins for Kokila Connect are added explicitly via KOKILA_FRAME_ANCESTORS.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'" + (process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""),
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'" + (process.env.KOKILA_MEDIA_ORIGINS ? ` ${process.env.KOKILA_MEDIA_ORIGINS}` : ""),
  "media-src 'self' blob:",
  `frame-ancestors ${process.env.KOKILA_FRAME_ANCESTORS ?? "'none'"}`,
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  env: { KOKILA_API_ORIGIN: apiOrigin },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "microphone=(self), camera=(), geolocation=()" },
        ],
      },
      { source: "/api/:path*", headers: [{ key: "Cache-Control", value: "no-store" }] },
    ];
  },
};

export default config;
