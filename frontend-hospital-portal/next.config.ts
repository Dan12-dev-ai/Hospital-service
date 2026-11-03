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
    // The old portal's service worker is replaced by one that removes itself
    // (public/sw.js): never long-cached, so browsers fetch the replacement.
    const worker = [
      { key: "Cache-Control", value: "no-cache" },
      { key: "Content-Type", value: "application/javascript; charset=utf-8" },
    ];
    return [{ source: "/sw.js", headers: worker }];
  },
};

export default nextConfig;
