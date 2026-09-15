import type { LucideIcon } from "lucide-react";

/**
 * A screen's title, with the icon that names its section.
 *
 * The icon is the same one the sidebar uses for this destination, which is the
 * only reason it earns its place: a reader who clicked "Orders" sees the same
 * mark at the top of the page and knows the click landed. A different icon per
 * surface would be decoration.
 *
 * `aria-hidden`, because the heading text already says it.
 */
export function PageHeading({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  /** A count, a control — whatever sits on the title's line. */
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="text-tx-dim flex shrink-0 items-center" aria-hidden="true">
        <Icon size={19} />
      </span>
      <h1 className="font-display text-xl font-semibold tracking-tight">{title}</h1>
      {children}
    </div>
  );
}
