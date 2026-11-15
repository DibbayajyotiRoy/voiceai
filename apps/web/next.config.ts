import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: the site is hosted on Cloudflare Pages. The only dynamic pieces are
  // the /api/track Pages Function (apps/web/functions) and the public control API, which
  // the browser calls directly.
  output: "export",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
