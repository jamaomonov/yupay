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
