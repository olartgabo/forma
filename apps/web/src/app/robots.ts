import type { MetadataRoute } from "next";

// Pages are public; /api serves private per-owner project data behind tokens.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/" },
  };
}
