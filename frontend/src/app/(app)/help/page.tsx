import Link from "next/link";

import { PageHeader } from "@/components/ui";

const FAQ = [
  ["How do I switch between products?", "Use Back to Overview or the product switcher at the top of the sidebar. You stay signed in."],
  ["Why is a product locked?", "Access follows your organization's subscription. Admins can upgrade or request access from Billing."],
  ["Why does the assistant say my data isn't connected?", "Business answers come only from verified connections. Connect ERPNext or Manima Hub under Integrations."],
  ["Is the microphone always listening?", "No. The microphone starts muted and only listens after you unmute it. Muting stops capture immediately."],
  ["Who can see my personal assistant chats?", "Only you. Personal mode is isolated from your organization's data and from other users."],
];

export default function Help() {
  return (
    <div className="max-w-3xl">
      <PageHeader title="Help & Support" subtitle="Answers to common questions, and how to reach Manima AI-Tech Solutions." />
      <dl className="space-y-4">
        {FAQ.map(([q, a]) => (
          <div key={q} className="card">
            <dt className="font-semibold">{q}</dt>
            <dd className="mt-1 text-sm text-muted">{a}</dd>
          </div>
        ))}
      </dl>
      <div className="card mt-6 text-sm">
        <div className="font-semibold">Contact support</div>
        <p className="mt-1 text-muted">Email <a className="text-brand-700 underline" href="mailto:business@manima.co.in">business@manima.co.in</a>. Include the time of the issue and the page you were on.</p>
        <Link href="/overview" className="btn-secondary mt-4">Back to Overview</Link>
      </div>
    </div>
  );
}
