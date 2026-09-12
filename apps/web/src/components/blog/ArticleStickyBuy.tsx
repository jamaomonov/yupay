import Link from "next/link";

import { buttonStyles } from "@/lib/button";

interface Props {
  href: string;
  label: string;
}

/** Phone-only persistent top-up. The in-flow buy card stays on sm+. */
export function ArticleStickyBuy({ href, label }: Props) {
  return (
    <div className="border-border bg-bg/95 fixed inset-x-0 bottom-0 z-30 border-t px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:hidden">
      <Link href={href} className={buttonStyles({ size: "md", className: "w-full" })}>
        {label}
      </Link>
    </div>
  );
}
