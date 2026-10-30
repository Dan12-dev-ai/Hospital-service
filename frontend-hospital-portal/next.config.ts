import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  experimental: {
    agentFeedback: true,
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    // The service worker must not be long-cached, or a fixed worker would
    // take a day (or longer, behind a CDN) to reach the browsers.
    const worker = [
      { key: "Cache-Control", value: "no-cache" },
      { key: "Content-Type", value: "application/javascript; charset=utf-8" },
    ];
    return [
      { source: "/sw.js", headers: worker },
      { source: "/service-worker.js", headers: worker },
      { source: "/manifest.json", headers: [{ key: "Cache-Control", value: "no-cache" }] },
    ];
  },
  images: {
    // Allow the template's Google-hosted avatar imagery (avatars, staff photos)
    remotePatterns: [
      {
        protocol: "https",
        hostname: "lh3.googleusercontent.com",
        pathname: "/aida-public/**",
      },
    ],
  },
};

export default nextConfig;
