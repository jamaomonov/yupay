-- Bunzy re-sent «Steam-кошелёк: как пополнить и на что тратить» (external id
-- `steam-koshelek`, 2026-09-27) after the same article had already been
-- imported as `steam-2`, reviewed, translated and published at
-- `/blog/steam-koshelek` (post 01a0d6aa-5498-7901-8ee7-729baee8643c). The
-- second copy landed as a Russian-only draft with slug `steam-koshelek-2`.
--
-- Archived rather than deleted: deleting cascades the import ledger row, and
-- the next hourly pass would see the article as new and re-import it.
-- `archived` is a locked state for the importer (`bunzy.locked`), so the
-- copy stays out of the admin's draft filter and never comes back.

BEGIN;

UPDATE blog_posts
SET status = 'archived', updated_at = now()
WHERE id = '01a0e4ff-161c-7351-b7e2-655ef0c5e61d' AND status = 'draft';

COMMIT;
