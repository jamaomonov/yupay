/**
 * Render sanitized article HTML. The API already ran the allowlist; this is
 * presentation only.
 */

export function ArticleBody({ html }: { html: string }) {
  return (
    <div
      className="article-body text-tx-mute text-[16px] leading-relaxed"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
