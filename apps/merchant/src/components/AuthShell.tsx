import Link from "next/link";

/** The centred card every signed-out screen sits in. */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  /** Optional: the confirm and check-your-mail screens are prose only. */
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-5 py-12">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {subtitle ? <p className="text-tx-mute mt-2 text-sm leading-relaxed">{subtitle}</p> : null}
      <div className="mt-7">{children}</div>
      {footer ? <div className="text-tx-mute mt-6 text-sm">{footer}</div> : null}
    </main>
  );
}

export function AuthLink({ href, label }: { href: string; label: string }) {
  return (
    <Link href={href} className="text-primary font-medium underline-offset-4 hover:underline">
      {label}
    </Link>
  );
}
