import type { MetadataRoute } from "next";

/**
 * AI assistant / answer-engine crawlers we explicitly welcome, so YuPay's
 * catalog can be surfaced and cited by ChatGPT, Perplexity, Claude, Google AI
 * Overviews, Apple Intelligence, etc. A `*` Allow already covers them, but
 * naming them documents intent and opts in the training/answer tokens
 * (Google-Extended, Applebot-Extended) that sites often block by default.
 * They get the same access as everyone: the public site, never /api or /admin.
 */
const AI_CRAWLERS = [
  // OpenAI
  "GPTBot",
  "OAI-SearchBot",
  "ChatGPT-User",
  // Anthropic
  "ClaudeBot",
  "anthropic-ai",
  "Claude-User",
  "Claude-SearchBot",
  // Perplexity
  "PerplexityBot",
  "Perplexity-User",
  // Google (Gemini / AI Overviews token) & Apple Intelligence
  "Google-Extended",
  "Applebot-Extended",
  // Common Crawl (feeds many open models) + others
  "CCBot",
  "cohere-ai",
  "Amazonbot",
  "Meta-ExternalAgent",
];

const DISALLOW = ["/api/", "/admin/"];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: DISALLOW },
      { userAgent: AI_CRAWLERS, allow: "/", disallow: DISALLOW },
    ],
    sitemap: "https://yupay.uz/sitemap.xml",
    host: "https://yupay.uz",
  };
}
