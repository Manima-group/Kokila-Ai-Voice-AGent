import Link from "next/link";

const FEATURES = [
  { t: "Multilingual voice agents", d: "Build agents for English, Hindi, Kannada and Telugu* from industry templates — receptionist, admissions, real estate, support and more." },
  { t: "Inbound call answering", d: "Route your business numbers to AI agents that capture leads, answer from your knowledge base and hand off to your team." },
  { t: "Consent-first outbound", d: "Campaigns dial only contacts with recorded consent, honour opt-outs instantly and stay inside 9 AM – 9 PM IST." },
  { t: "Built-in CRM", d: "Contacts, leads, follow-up tasks, transcripts and call outcomes in one place, updated automatically after every call." },
  { t: "Appointments", d: "Agents check real availability and only confirm bookings after your calendar accepts them. Google Calendar supported." },
  { t: "Analytics & billing", d: "Answer rates, conversions, agent performance and minute usage — with Razorpay subscriptions and GST invoices." },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-600 font-bold text-white">K</span>
          <span className="text-xl font-semibold">Kokila</span>
        </div>
        <nav className="flex items-center gap-3">
          <Link href="/login" className="btn-secondary">Sign in</Link>
          <Link href="/signup" className="btn-primary">Start free trial</Link>
        </nav>
      </header>
      <section className="mx-auto max-w-6xl px-6 pb-16 pt-12 md:pt-20">
        <p className="mb-4 inline-block rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">AI voice agents for Indian businesses</p>
        <h1 className="max-w-3xl text-4xl font-bold leading-tight tracking-tight md:text-5xl">
          Answer every call. Follow up every lead. <span className="text-brand-600">In your customer&apos;s language.</span>
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-muted">
          Kokila gives telecalling teams, BPOs, real estate, education and service businesses AI voice agents that handle inbound calls,
          run compliant outbound campaigns and keep your CRM up to date.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/signup" className="btn-primary px-6 py-3 text-base">Create your first agent</Link>
          <Link href="/login" className="btn-secondary px-6 py-3 text-base">I already have an account</Link>
        </div>
      </section>
      <section className="border-t border-line bg-panel">
        <div className="mx-auto grid max-w-6xl gap-5 px-6 py-16 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.t} className="card">
              <div className="mb-2 h-1 w-10 rounded bg-brand-500" />
              <h3 className="font-semibold">{f.t}</h3>
              <p className="mt-2 text-sm text-muted">{f.d}</p>
            </div>
          ))}
        </div>
        <p className="mx-auto max-w-6xl px-6 pb-10 text-xs text-muted">
          *Language availability depends on the configured voice provider and is verified per deployment before being enabled for live calls.
        </p>
      </section>
      <footer className="border-t border-line py-8 text-center text-sm text-muted">© {new Date().getFullYear()} Manima AI-Tech Solutions · business@manima.co.in</footer>
    </div>
  );
}
