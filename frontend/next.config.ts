import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    // Same-origin API access so the httpOnly refresh cookie works without cross-site CORS.
    return [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
  async redirects() {
    // Preserve pre-unification URLs.
    const moved = ["agents", "voice-test", "phone-numbers", "calls", "contacts", "leads", "campaigns", "appointments", "analytics"];
    return [
      { source: "/dashboard", destination: "/overview", permanent: false },
      ...moved.flatMap((m) => [
        { source: `/${m}`, destination: `/calling-agent/${m}`, permanent: true },
        { source: `/${m}/:path*`, destination: `/calling-agent/${m}/:path*`, permanent: true },
      ]),
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
