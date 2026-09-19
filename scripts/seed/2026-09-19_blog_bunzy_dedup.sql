-- Bunzy re-sent three already-published articles under new external ids.
--
-- Their feed used to key these three as `post`, `post-2` and `10-2026`;
-- on 2026-09-19 07:02 UTC the same three arrived as `kupit-donat-v-uzbekistane`,
-- `popolneniye-igr-onlayn` and `top-10-mobilnyh-igr-2026`. `stale_slugs` matches
-- on `external_id`, saw no record, and `_create`d three fresh drafts whose ru
-- slugs collided with ours and picked up a `-2` suffix.
--
-- The drafts are the raw upstream text: no cover, no likes, no views, 4-5 FAQs
-- against the 12-15 our published copies carry after the 2026-09-19 corrections,
-- and ru only against our ru/en/uz. Deleting them loses nothing of ours.
--
-- Deleting alone does not hold: the next hourly pass would see the new ids as
-- unknown and re-create all three. So the published posts' import records are
-- re-pointed at the ids Bunzy now sends, carrying over the fresh `source_hash`
-- and `source_updated_at` the drafts were built from. After that a pass matches
-- the record, finds `source_updated_at` unchanged (no detail fetch), and if it
-- ever does fetch, `_refresh` bails at `status != 'draft'` with `bunzy.locked`.

BEGIN;

-- Carry the upstream identity off the drafts before the cascade takes them.
CREATE TEMP TABLE bunzy_remap ON COMMIT DROP AS
SELECT i.external_id,
       i.source_hash,
       i.source_updated_at,
       i.post_id AS draft_post_id,
       pub.post_id AS published_post_id
FROM blog_imported_posts i
JOIN blog_post_translations pub
  ON pub.locale = 'ru' AND pub.slug = i.external_id
WHERE i.source = 'bunzy'
  AND i.post_id IN (
    '01a0b879-769a-79c2-b124-cfc72f4d4431',  -- kupit-donat-v-uzbekistane-2
    '01a0b879-75b1-7cb2-a283-f905dde16f71',  -- popolneniye-igr-onlayn-2
    '01a0b879-75fd-7813-94be-71259d802080'   -- top-10-mobilnyh-igr-2026-2
  );

-- Refuse to run half-matched: three drafts in, three pairs out, or nothing.
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM bunzy_remap;
  IF n <> 3 THEN
    RAISE EXCEPTION 'expected 3 draft->published pairs, found %', n;
  END IF;
END $$;

-- Only ever the untouched drafts. A post that left `draft`, or that a reader
-- has already liked or read, is not a duplicate we may delete.
DELETE FROM blog_posts p
USING bunzy_remap r
WHERE p.id = r.draft_post_id
  AND p.status = 'draft'
  AND p.cover_image_url IS NULL
  AND NOT EXISTS (SELECT 1 FROM blog_post_likes l WHERE l.post_id = p.id)
  AND NOT EXISTS (SELECT 1 FROM blog_post_views v WHERE v.post_id = p.id);

DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM blog_posts p
    JOIN bunzy_remap r ON r.draft_post_id = p.id;
  IF n <> 0 THEN
    RAISE EXCEPTION 'a draft survived the guards, % left', n;
  END IF;
END $$;

-- Re-point the survivors. The PK is (source, external_id), so this only works
-- once the drafts holding those ids are gone — hence the order.
UPDATE blog_imported_posts i
SET external_id       = r.external_id,
    source_hash       = r.source_hash,
    source_updated_at = r.source_updated_at,
    last_seen_at      = CURRENT_TIMESTAMP
FROM bunzy_remap r
WHERE i.source = 'bunzy'
  AND i.post_id = r.published_post_id;

COMMIT;
