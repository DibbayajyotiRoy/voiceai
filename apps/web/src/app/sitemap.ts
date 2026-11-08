import type { MetadataRoute } from "next";

const SITE = "https://voiceai-presentation.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  return [{ url: `${SITE}/`, changeFrequency: "monthly", priority: 1 }];
}
