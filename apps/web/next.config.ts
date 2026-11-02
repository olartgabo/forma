import type { NextConfig } from "next";

const configuredOrigin =
  process.env.FORMA_API_ORIGIN ?? "http://127.0.0.1:8000";
const origin = new URL(configuredOrigin);
if (
  !["http:", "https:"].includes(origin.protocol) ||
  origin.username ||
  origin.password ||
  origin.pathname !== "/" ||
  origin.search ||
  origin.hash
) {
  throw new Error(
    "FORMA_API_ORIGIN must be an HTTP(S) origin without credentials or a path",
  );
}

const config: NextConfig = {
  rewrites() {
    return [
      { source: "/api/:path*", destination: `${origin.origin}/api/:path*` },
    ];
  },
};

export default config;
