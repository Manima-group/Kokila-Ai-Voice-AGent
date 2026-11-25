import Link from "next/link";

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <span aria-hidden className="grid place-items-center rounded-[12px] bg-k-yellow-500 text-k-grey-900"
          style={{ width: size, height: size }}>
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 32 32" fill="none" stroke="currentColor"
           strokeWidth="2.8" strokeLinecap="round">
        <path d="M5 13v6M10 8v16M16 4v24M22 9v14M27 13v6" />
      </svg>
    </span>
  );
}

export function Header({ right, subtitle }: { right?: React.ReactNode; subtitle?: string }) {
  return (
    <header className="sticky top-0 z-10 border-b border-k-grey-200 bg-k-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
        <Link href="/assistant" className="flex items-center gap-2.5">
          <Logo />
          <span className="text-2xl font-bold tracking-tight">kokila.</span>
          {subtitle && <span className="hidden text-xs tracking-widest text-k-grey-600 sm:inline">{subtitle}</span>}
        </Link>
        <nav className="flex items-center gap-2 text-sm">{right}</nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="py-6 text-center text-xs text-k-grey-600">Intelligence that speaks · Manima AI-Tech Solutions</footer>
  );
}
