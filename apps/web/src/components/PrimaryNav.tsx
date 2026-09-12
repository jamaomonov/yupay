"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { navSectionActive } from "@/lib/locale-href";
import { pathFor } from "@/lib/seo";

interface Props {
  locale: string;
  label: string;
  store: string;
  blog: string;
  how: string;
  support: string;
}

export function PrimaryNav({ locale, label, store, blog, how, support }: Props) {
  const pathname = usePathname();
  const storeHref = pathFor(locale, "/store");
  const blogHref = pathFor(locale, "/blog");
  const howHref = `${pathFor(locale)}#how`;

  const cls = (href: string, hash = false) => {
    const active = hash ? false : navSectionActive(pathname, href);
    return `whitespace-nowrap text-sm font-medium transition ${
      active ? "text-foreground" : "text-tx-mute hover:text-foreground"
    }`;
  };

  return (
    <nav aria-label={label} className="hidden items-center gap-8 md:flex">
      <Link
        href={storeHref}
        aria-current={navSectionActive(pathname, storeHref) ? "page" : undefined}
        className={cls(storeHref)}
      >
        {store}
      </Link>
      <Link
        href={blogHref}
        aria-current={navSectionActive(pathname, blogHref) ? "page" : undefined}
        className={cls(blogHref)}
      >
        {blog}
      </Link>
      <a href={howHref} className={cls(howHref, true)}>
        {how}
      </a>
      <a
        href="https://t.me/yupay_support"
        target="_blank"
        rel="noreferrer noopener"
        className={cls("/support", true)}
      >
        {support}
      </a>
    </nav>
  );
}
