# Runbook — Bunzy blog import

One article a day is written for us on [app.bunzy.io](https://app.bunzy.io).
`apps/scheduler`'s `bunzy_import` job pulls it in as a **draft**. Nothing in
this path publishes, and nothing in it overwrites a post somebody has edited.

Design and the full Markdown→HTML mapping table: [ADR-0077](../decisions/0077-bunzy-blog-import.md).
Flow: [`blog-bunzy-import.mmd`](../architecture/sequence-diagrams/blog-bunzy-import.mmd).

## Turning it on

Add to `secrets/api.env` on the VPS (both `api` and `scheduler` read that
file, but only the scheduler uses these):

```
BUNZY_API_URL=https://app.bunzy.io
BUNZY_API_KEY=<the key from their dashboard>
```

then restart the scheduler:

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate scheduler
docker compose -f docker-compose.prod.yml logs -f scheduler | grep bunzy
```

`bunzy.registered` means it is on. **`bunzy.disabled` means the key is
empty** — without one the job is not registered at all, which is the dev and
CI default. The first pass runs two minutes after boot, then hourly.

The key is server-side only. It authenticates as our whole blog account, so
it must never appear in `web.env`, `miniapp.env` or anything `NEXT_PUBLIC_`.

## The daily loop

1. The job reads `GET /posts` and compares each article's `updatedAt` with
   what `blog_imported_posts` last recorded. Unchanged articles cost nothing.
2. A new or changed article is fetched, converted and written as a `draft`
   **with no brand**.
3. You open it in the admin panel (`/blog`, filter `draft`), pick the brand,
   fix whatever needs fixing, and press «Опубликовать».

Publish refuses while the brand is empty — both in the service and in the
database constraint. That is deliberate: every storefront query reaches an
article through its brand.

## What does and does not come across

| Comes across                                                             | Does not                                                                             |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Headings (`##` → `h2`, `###`+ → `h3`)                                    | The article's own `#` title — it becomes `h2`; the title field is the page H1        |
| Links, including in-sentence ones                                        | `title=` on a link; a `mailto:`/other-scheme link keeps its text, loses its tag      |
| Both list kinds, nested                                                  | Images — they live on `cdn.bunzy.io`, and our allowlist refuses off-host media       |
| Bold, italic, inline code, quotes, rules, tables, fenced code            | `~~strikethrough~~` (keeps the words), `language-*` on code, `style=` on table cells |
| The key-takeaways box, re-inserted at the top under the feed's own label | Tags, byline, reading time — no columns for them                                     |
| FAQ → `blog_post_faqs` (shown on the page and in `FAQPage` JSON-LD)      | `jsonLd` from their SEO block — we build our own                                     |
| `metaTitle` / `metaDescription` → `seo_title` / `seo_description`        | `ogImage`, `thumbnailUrl` — off-host again; upload a cover by hand                   |

**Want the picture?** Download it from their dashboard and upload it through
the admin form's cover / inline-image uploader. It then lives on
`cdn.yupay.uz` like every other image we serve.

## Reading what a pass did

```bash
docker compose -f docker-compose.prod.yml logs --since 2h scheduler | grep bunzy
```

| Line                                            | Means                                                                         |
| ----------------------------------------------- | ----------------------------------------------------------------------------- |
| `bunzy.up_to_date`                              | Nothing upstream moved. The common case.                                      |
| `bunzy.created`                                 | New draft. `dropped_images` / `unwrapped_links` say what the mapping gave up. |
| `bunzy.refreshed`                               | Upstream rewrote an article we had not touched, so we took the new version.   |
| `bunzy.edited`                                  | **You edited it.** That article will never sync again. Intended.              |
| `bunzy.locked`                                  | The post left `draft` (published / scheduled / archived). Never touched.      |
| `bunzy.skipped_locale`                          | Their `language` is not one of ru/en/uz.                                      |
| `bunzy.feed_unavailable` / `bunzy.fetch_failed` | Their API. Status code only — the key never reaches a log line.               |
| `bunzy.import_failed`                           | Our side. Read the traceback; the article is untouched and retried next pass. |

Where things stand in the database:

```sql
SELECT i.external_id, p.status, t.slug, i.last_seen_at, i.last_synced_at
FROM blog_imported_posts i
JOIN blog_posts p ON p.id = i.post_id
LEFT JOIN blog_post_translations t ON t.post_id = p.id
ORDER BY i.last_seen_at DESC;
```

## Things that will come up

**"They fixed a mistake upstream but our copy still has it."** Once you edit
an article, the importer stops touching it — that is the promise. To take
their new version, either apply the fix by hand, or delete the post and let
the next pass re-import it:

```sql
-- The ledger row cascades with the post, so the next pass sees it as new.
DELETE FROM blog_posts WHERE id = '<post id>';
```

**"The slug is `steam-2`."** Something already held `steam` in that locale.
Rename it in the admin form before publishing — a draft's slug is free to
change; a published one is not (see the blog module README).

**"I want it to import more often."** `BUNZY_IMPORT_INTERVAL_MINUTES` in
`secrets/api.env`. They publish once a day, so hourly is already generous.

**"I want to stop it."** Blank `BUNZY_API_KEY` and restart the scheduler.
Existing drafts stay where they are.

## Known gaps

- **No backfill command.** The job reads the newest `BUNZY_IMPORT_PAGE_SIZE`
  (20) articles per pass, which covers a feed of one a day but would not
  import a large archive on day one. If that is ever needed, raise the page
  size for one pass rather than writing a script.
- **No alert on repeated failures.** A Bunzy outage shows up as log lines and
  nothing else. Nothing is lost — the next pass retries — but nobody is told.
- **One locale per article.** They write in one language; the import fills
  that locale only. `en`/`uz` translations stay a manual job.
