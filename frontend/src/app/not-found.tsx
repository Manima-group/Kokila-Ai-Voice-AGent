import Link from "next/link";

export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center p-8 text-center">
      <div>
        <div className="text-5xl font-bold text-brand-600">404</div>
        <p className="mt-2 text-muted">This page does not exist.</p>
        <Link className="btn-primary mt-6" href="/dashboard">Go to dashboard</Link>
      </div>
    </div>
  );
}
