# 0077. Import Bunzy articles as blog drafts

- **Status**: Accepted
- **Date**: 2026-09-15
- **Deciders**: @jamaomonov
- **Tags**: backend | data

## Context and problem statement

We bought a subscription to [Bunzy](https://app.bunzy.io), which writes one SEO article a
day for yupay.uz and serves it over a small read-only API. The articles should appear in
our own blog rather than on somebody else's domain — that is the whole point of paying for
them — but the owner's instruction was explicit: _"чтобы она к нам подтягивалась но не
публиковалась а сохранялась как черновик, я проверю все поправлю и буду публиковать сам"_.

So this is not a syndication feed. It is a **draft pipeline with a human gate**, and the
thing that decides whether it is worth having is fidelity: _"важно чтобы форматирование
теги подтягивались правильно чтобы большой текст отображался у нас тоже как большой текст
и текст со ссылкой и тд"_. An import that arrives as a wall of unformatted prose costs more
to fix than writing the article by hand.

Three facts about our schema shaped the design:

1. `blog_post_translations.body_html` is **HTML**, validated by a fail-closed allowlist
   (`blog/sanitize.py`, ADR-0072 §8.1). Bunzy serves **Markdown**. Something has to map one
   onto the other, and the allowlist has no `h1`, no `h4`, no `<del>`, no attributes beyond
   `a[href]` and `img[src,alt]`.
2. `blog_posts.primary_brand_id` was `NOT NULL`. An article written by a third party arrives
   before anyone has decided what it sells.
3. Every image upstream serves lives on `cdn.bunzy.io`, and `assert_hosted_media` refuses
   anything that is not on our own media origin.

Bunzy also ships a prompt telling an agent to build the integration as a Next.js route that
reads their API at request time. That is the wrong architecture here: it would put a
third-party fetch on the storefront's render path, bypass the admin panel entirely, and
give the owner no way to edit anything — which is the one thing they asked for.

## Decision drivers

- The owner edits and publishes. Nothing may publish itself.
- **An edit is sacred.** A re-sync that overwrites a correction is worse than no re-sync.
- Formatting must survive: headings, links, both list kinds, emphasis, quotes, code, tables.
- The API key authenticates as our whole blog account and must stay server-side.
- One article a day. The mechanism should cost roughly nothing when nothing changed.

## Considered options

1. **Render Bunzy's feed at request time in `apps/web`** — their own suggested integration.
2. **Import into `blog_posts` as drafts, on the scheduler** — one row per article, edited
   in the existing admin panel.
3. **Import and auto-publish**, with the admin panel as an after-the-fact correction tool.

## Decision outcome

**Chosen option: 2.** A scheduler job pulls the feed, converts each new or changed article
to allowlisted HTML, and writes it as a `draft`. The existing admin form is the editor; the
existing publish button is the gate.

Four decisions inside that are worth recording, because each has a cheaper wrong answer:

**Markdown is parsed, not regex-replaced.** We added `markdown-it-py` (CommonMark-compliant,
pure Python, one transitive dependency). Hand-rolling Markdown is where formatting bugs
live — nested emphasis, escapes, reference links, loose vs. tight lists — and formatting
fidelity is the requirement. The project-specific part happens on the **token stream**
before rendering (`blog/markdown_html.py`), so the converter emits allowlisted tags by
construction instead of producing HTML somebody then has to patch:

| Markdown                    | Becomes                              | Why                                                                |
| --------------------------- | ------------------------------------ | ------------------------------------------------------------------ |
| `#`, `##`                   | `<h2>`                               | The body must not carry the page's `h1`.                           |
| `###`–`######`              | `<h3>`                               | The allowlist stops there; demote, don't drop.                     |
| `## Text {#slug}`           | `<h2>Text</h2>`                      | An anchor extension we do not render.                              |
| `[t](https://…)`, `[t](/x)` | `<a href>`, no `title`               | One attribute is all the allowlist takes.                          |
| `[t](mailto:…)`             | `t`                                  | Unwrap; losing an article over one link is the wrong trade.        |
| `![alt](…)`                 | dropped, with its paragraph          | Off-host media; an editor uploads it.                              |
| `~~t~~`                     | `t`                                  | No `<del>` on the allowlist.                                       |
| fenced code                 | `<pre><code>`, no `language-*` class | Attributes are refused.                                            |
| GFM table                   | tags kept, `style=` dropped          | Same reason.                                                       |
| raw HTML                    | escaped to text                      | `html=False`: a `<script>` in the feed is characters, never a tag. |

`sanitize_body` still runs over the result. The converter is the mapping; the validator
stays the guard, and a test asserts it accepts the output **unchanged**.

**`primary_brand_id` becomes nullable, guarded by a CHECK.** `primary_brand_id IS NOT NULL
OR status = 'draft'`. Sixteen files read `primary_brand` and none of them change, because
every public query inner-joins `brands` through that column _and_ filters to `published` —
so a brandless row cannot reach a reader. `publish_post` and `schedule_post` refuse without
one, which turns the constraint into a sentence an editor can act on. The alternative — a
catch-all "Другое" brand row — was rejected: it would surface in the storefront brand list,
in the B2B catalog and in the Merchant Center feed, three places that have nothing to do
with an unfinished draft.

**A re-sync is fingerprinted twice.** `blog_imported_posts` stores a hash of the upstream
fields we consume and a hash of everything we wrote (slug, title, excerpt, body, both SEO
fields, the FAQ). A pass refreshes an article only when the source changed **and** our copy
still hashes to what we wrote **and** the post is still a `draft`. The first touch by a
human ends the sync for that article permanently. This is the promise the whole feature
rests on, and both halves have a test that goes red when the check is removed.

**The feed's `updatedAt` decides what to fetch.** The list endpoint carries a revision per
article, so an unchanged article costs one comparison instead of a download.

### Positive consequences

- The owner's workflow is the one that already exists: open the draft, fix it, publish.
- Formatting is asserted construct by construct, and the converter's output is proven to
  pass the fail-closed validator byte-for-byte.
- A Bunzy outage costs a log line. Nothing on the storefront's render path touches them.
- The key lives in `secrets/api.env` and is read only by the scheduler.

### Negative consequences

- A new dependency (`markdown-it-py` + `mdurl`). Small, pure Python, MIT.
- Images do not come across. The owner said they would upload by hand when needed, and the
  alternative is mirroring a third party's CDN into our bucket on a timer.
- Tags, byline and reading time are dropped — we have no columns for them.
- Once an article is edited it never re-syncs, even for a correction upstream. That is the
  intended trade; the runbook says how to force one.

## Validation

- `apps/api/tests/unit/test_blog_markdown_html.py` — every construct, plus a parametrised
  check that `sanitize_body` accepts the output unchanged.
- `apps/api/tests/integration/test_blog_bunzy_import.py` — the draft lands brandless, the
  formatting arrives, an edited draft is never overwritten (red without the guard), a
  published post is never touched, publishing without a brand is refused by the service
  _and_ by the constraint.
- `apps/api/tests/contract/test_bunzy_client.py` — the recorded payload shape, and that a
  4xx never carries the key into an exception message.

## References

- [ADR-0072](./0072-editorial-blog.md) — the blog, its allowlist and its lifecycle.
- [ADR-0074](./0074-blog-indexnow-queue.md) — what happens after publish.
- `docs/runbooks/blog-bunzy-import.md`
- `docs/architecture/sequence-diagrams/blog-bunzy-import.mmd`
