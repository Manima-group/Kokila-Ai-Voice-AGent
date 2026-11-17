"use client";

import { useState } from "react";

import { Badge, ErrorBox, Field, Loading, Modal, PageHeader, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Member = { user_id: string; email: string; full_name: string; role: string; is_active: boolean; created_at: string };
const ROLES = ["COMPANY_ADMIN", "MANAGER", "OPERATOR", "VIEWER"];

export default function Team() {
  const { can, me } = useAuth();
  const q = useApi<Member[]>("/users");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", full_name: "", role: "OPERATOR" });
  const [temp, setTemp] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      const r = await fn();
      q.refetch();
      return r;
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div>
      <PageHeader title="Team" subtitle="Roles are enforced on the server for every request."
        actions={can("users:write") && <button className="btn-primary" onClick={() => { setTemp(null); setOpen(true); }}>Invite member</button>} />
      <ErrorBox error={error} />
      {q.isLoading ? <Loading /> : (
        <Table head={["Name", "Email", "Role", "Status", "Joined", ""]}>
          {q.data?.map((m) => (
            <tr key={m.user_id}>
              <td className="td">{m.full_name}</td><td className="td">{m.email}</td>
              <td className="td">
                {can("users:write") && m.user_id !== me?.id ? (
                  <select className="input w-44" value={m.role} onChange={(e) => run(() => api(`/users/${m.user_id}/role`, { method: "PATCH", body: { role: e.target.value } }))} aria-label="Role">
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                ) : m.role}
              </td>
              <td className="td"><Badge tone={m.is_active ? "green" : "red"}>{m.is_active ? "active" : "deactivated"}</Badge></td>
              <td className="td">{fmtDate(m.created_at)}</td>
              <td className="td">{can("users:write") && m.is_active && m.user_id !== me?.id && <button className="text-sm text-red-600 hover:underline" onClick={() => run(() => api(`/users/${m.user_id}/deactivate`, { method: "POST" }))}>Deactivate</button>}</td>
            </tr>
          ))}
        </Table>
      )}
      <Modal open={open} title="Invite team member" onClose={() => setOpen(false)}>
        {temp ? (
          <div className="space-y-3 text-sm">
            <p>Share this temporary password securely; ask the user to change it after first sign-in.</p>
            <code className="block rounded bg-panel p-3">{temp}</code>
            <button className="btn-primary" onClick={() => setOpen(false)}>Done</button>
          </div>
        ) : (
          <div className="space-y-3">
            <ErrorBox error={error} />
            <Field label="Full name"><input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
            <Field label="Email"><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Role"><select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></Field>
            <button className="btn-primary" onClick={async () => {
              const r = (await run(() => api<{ temporary_password: string | null }>("/users", { method: "POST", body: form }))) as { temporary_password: string | null } | undefined;
              if (r?.temporary_password) setTemp(r.temporary_password);
              else if (r) setOpen(false);
            }}>Invite</button>
          </div>
        )}
      </Modal>
    </div>
  );
}
