import Link from "next/link";

export default function AuthFrame({ title, children, footer }: { title: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center bg-panel p-4">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-6 flex items-center justify-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-600 font-bold text-white">K</span>
          <span className="text-xl font-semibold">Kokila</span>
        </Link>
        <div className="card p-8">
          <h1 className="mb-6 text-xl font-semibold">{title}</h1>
          {children}
        </div>
        <p className="mt-4 text-center text-sm text-muted">{footer}</p>
      </div>
    </div>
  );
}
