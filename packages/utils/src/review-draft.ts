/** Chip labels and free text share one draft, joined with ". ". */

const JOIN = ". ";

/**
 * Split a review body into segments the chip row can toggle independently.
 *
 * A custom sentence without ". " stays one segment, so typing does not
 * invent chips. Chip labels are stored as their own segments.
 */
export function splitReviewDraft(draft: string): string[] {
  return draft
    .split(/\.\s+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

/** True when `label` is already a segment of `draft` (case-insensitive). */
export function reviewDraftHasChip(draft: string, label: string): boolean {
  const needle = label.trim().toLocaleLowerCase();
  if (!needle) return false;
  return splitReviewDraft(draft).some((part) => part.toLocaleLowerCase() === needle);
}

/**
 * Add or remove a chip label in the draft. Custom text that is not an
 * exact (case-insensitive) chip segment is left untouched, so selecting
 * "Fast" never concatenates a second copy onto "the delivery was fast".
 */
export function toggleChipInReviewDraft(draft: string, label: string): string {
  const chip = label.trim();
  if (!chip) return draft.trim();
  const parts = splitReviewDraft(draft);
  const idx = parts.findIndex((part) => part.toLocaleLowerCase() === chip.toLocaleLowerCase());
  if (idx >= 0) {
    parts.splice(idx, 1);
  } else {
    parts.push(chip);
  }
  return parts.join(JOIN);
}

/** A review of one order as the storefronts know it, for {@link reviewFollowUp}. */
export interface ReviewFollowUpInput {
  /** What the reviewer wrote, or null for a star-only review. */
  body: string | null;
  /** Whether the server would still accept a body — `PATCH /reviews/{id}`. */
  can_add_text: boolean;
}

/** What a review surface should be doing about one order right now. */
export type ReviewFollowUp =
  /** No review yet — show the stars. */
  | "ask"
  /** Rated but wordless, and the window is open — ask for the words. */
  | "words"
  /** Written already, or too late to write — show it back, ask nothing. */
  | "settled";

/**
 * The one rule behind "is there anything left to do with this review".
 *
 * Shared rather than written per surface because the surfaces disagreeing is
 * exactly what went wrong: four of them read "this order has a review" as
 * "render nothing", which — since posting a star is what makes it true — took
 * the comment step off screen in the tick it appeared. Production ran that way
 * for months and collected 27 star-only reviews against one edit ever.
 *
 * "settled" is deliberately not "has a review": a rated order with no words
 * and an open window is the single most valuable state this feature has, and
 * it is the one the old rule threw away.
 */
export function reviewFollowUp(review: ReviewFollowUpInput | null | undefined): ReviewFollowUp {
  if (!review) return "ask";
  if (review.body !== null && review.body.trim() !== "") return "settled";
  return review.can_add_text ? "words" : "settled";
}
