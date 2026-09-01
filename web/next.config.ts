import type { NextConfig } from "next";

/**
 * Static export only. CLAUDE.md §2: "Static export only. No serverless functions in Core."
 * `output: "export"` makes that a build-time guarantee rather than a convention - any
 * server-only feature fails the build instead of quietly requiring a runtime.
 */
const nextConfig: NextConfig = {
  output: "export",
  // Trailing slashes keep the exported tree servable by any static host without rewrite
  // rules, which is what "no keyed provider, no serverless" implies for hosting too.
  trailingSlash: true,
  images: { unoptimized: true },
  // A wrong environment value should fail the build, not render a blank map at runtime.
  env: {
    NEXT_PUBLIC_DATA_BASE: process.env.NEXT_PUBLIC_DATA_BASE ?? "/data",
  },
};

export default nextConfig;
