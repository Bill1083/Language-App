import type { NextConfig } from "next";

const config: NextConfig = {
  // Self-contained server bundle for the Docker image.
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // don't write an AGENTS.md into the project on every dev start
  agentRules: false,
  // this folder is the workspace root (a stray lockfile higher up confuses detection)
  turbopack: { root: process.cwd() },
  // Caddy routes /api to the FastAPI service, so the frontend never proxies.
  async headers() {
    return [
      {
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
};

export default config;
