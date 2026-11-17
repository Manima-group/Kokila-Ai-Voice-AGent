"use client";

import Link from "next/link";
import { useState } from "react";

import { Empty, ErrorBox, Field, Loading, Modal, PageHeader, Pager, Table } from "@/components/ui";
import { useApi, useMutate } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Contact, Page } from "@/types";

type ImportResult = { created: number; existing: number; duplicates_in_file: number; consents_recorded: number; invalid_count: number; invalid: { row: number; error: string }[] };

export default function Contacts() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<"add" | "import" | null>(null);
  const [form, setForm] = useState({ phone: "", name: "", email: "" });
  const [file, setFile] = useState<File | null>(null);
  const [imp, setImp] = useState<ImportResult | null>(null);
  const [impErr, setImpErr] = useState<unknown>(null);
  const list = useApi<Page<Contact>>(`/contacts?limit=25&offset=${offset}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
  const add = useMutate("POST", "/contacts", ["/contacts"]);

  const doImport = async () => {
    if (!file) return;
    setImpErr(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      setImp(await api<ImportResult>("/contacts/import", { method: "POST", form: fd }));
      list.refetch();
    } catch (e) {
      setImpErr(e);
    }
  };

  return (
    <div>
      <PageHeader title="Contacts" subtitle="Every contact belongs to your organization only. Consent and opt-outs are tracked per contact."
        actions={<>
          {can("contacts:import") && <button className="btn-secondary" onClick={() => { setImp(null); setOpen("import"); }}>Import CSV</button>}
          {can("contacts:write") && <button className="btn-primary" onClick={() => setOpen("add")}>Add contact</button>}
        </>} />
      <input className="input mb-4 max-w-sm" placeholder="Search name, phone or email" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} aria-label="Search contacts" />
      {list.isLoading ? <Loading /> : list.error ? <ErrorBox error={list.error} /> : list.data?.items.length ? (
        <>
          <Table head={["Name", "Phone", "Email", "Tags", "Source", "Added"]}>
            {list.data.items.map((c) => (
              <tr key={c.id} className="hover:bg-panel">
                <td className="td"><Link className="font-medium text-brand-700 hover:underline" href={`/contacts/${c.id}`}>{c.name ?? "Unnamed"}</Link></td>
                <td className="td font-mono text-xs">{c.phone_e164}</td>
                <td className="td">{c.email ?? "—"}</td>
                <td className="td text-xs">{c.tags.join(", ")}</td>
                <td className="td">{c.source}</td>
                <td className="td">{fmtDate(c.created_at)}</td>
              </tr>
            ))}
          </Table>
          <Pager total={list.data.total} limit={list.data.limit} offset={offset} onChange={setOffset} />
        </>
      ) : <Empty title="No contacts" body="Add contacts manually or import a CSV with a 'phone' column." />}

      <Modal open={open === "add"} title="Add contact" onClose={() => setOpen(null)}>
        <div className="space-y-3">
          <ErrorBox error={add.error} />
          <Field label="Phone"><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="98450 12345" /></Field>
          <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Email"><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <button className="btn-primary" disabled={add.isPending} onClick={() => add.mutate({ phone: form.phone, name: form.name || null, email: form.email || null }, { onSuccess: () => { setOpen(null); setForm({ phone: "", name: "", email: "" }); } })}>Save</button>
        </div>
      </Modal>
      <Modal open={open === "import"} title="Import contacts" onClose={() => setOpen(null)}>
        <div className="space-y-3 text-sm">
          <p className="text-muted">Columns: <code>phone</code> (required), <code>name</code>, <code>email</code>, <code>language</code>, <code>tags</code> (; separated). To record consent include <code>consent_purpose</code>, <code>consent_source</code>, <code>consent_evidence</code> and optional <code>consent_granted_at</code> (ISO-8601 with timezone). Rows with consent but no evidence are rejected.</p>
          <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="CSV file" />
          <ErrorBox error={impErr} />
          <button className="btn-primary" disabled={!file} onClick={doImport}>Upload</button>
          {imp && (
            <div className="rounded-lg bg-panel p-3">
              <div>{imp.created} created · {imp.existing} already existed · {imp.duplicates_in_file} duplicate rows · {imp.consents_recorded} consents · {imp.invalid_count} problems</div>
              {imp.invalid.length > 0 && <ul className="mt-2 max-h-40 overflow-y-auto text-xs text-red-700">{imp.invalid.map((x) => <li key={x.row}>Row {x.row}: {x.error}</li>)}</ul>}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
