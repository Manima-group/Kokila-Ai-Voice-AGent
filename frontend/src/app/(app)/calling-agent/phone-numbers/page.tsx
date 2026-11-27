"use client";

import { useState } from "react";

import { Badge, Empty, ErrorBox, Field, Loading, Modal, PageHeader, Table } from "@/components/ui";
import { useApi, useMutate } from "@/hooks/useApi";
import { useAuth } from "@/lib/auth";
import type { Agent, PhoneNumber } from "@/types";

export default function PhoneNumbers() {
  const { can } = useAuth();
  const nums = useApi<PhoneNumber[]>("/phone-numbers");
  const agents = useApi<Agent[]>("/agents");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ e164: "", label: "", number_type: "service", inbound_agent_id: "", outbound_enabled: false });
  const add = useMutate("POST", "/phone-numbers", ["/phone-numbers"]);
  const patch = useMutate<{ id: string; body: Record<string, unknown> }>("PATCH", (b) => `/phone-numbers/${b.id}`, ["/phone-numbers"], (b) => b.body);
  const agentName = (id: string | null) => agents.data?.find((a) => a.id === id)?.name ?? "—";

  return (
    <div>
      <PageHeader title="Phone numbers" subtitle="Business numbers provisioned with your voice provider. Inbound calls route to the assigned agent."
        actions={can("phone_numbers:write") && <button className="btn-primary" onClick={() => setOpen(true)}>Add number</button>} />
      <ErrorBox error={patch.error} />
      {nums.isLoading ? <Loading /> : nums.data?.length ? (
        <Table head={["Number", "Label", "Type", "Inbound agent", "Outbound", "Status"]}>
          {nums.data.map((n) => (
            <tr key={n.id}>
              <td className="td font-mono">{n.e164}</td>
              <td className="td">{n.label ?? "—"}</td>
              <td className="td">{n.number_type}</td>
              <td className="td">
                {can("phone_numbers:write") ? (
                  <select className="input" value={n.inbound_agent_id ?? ""} onChange={(e) => patch.mutate({ id: n.id, body: { inbound_agent_id: e.target.value || null } })}>
                    <option value="">None</option>
                    {agents.data?.filter((a) => a.status === "published").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select>
                ) : agentName(n.inbound_agent_id)}
              </td>
              <td className="td">{n.outbound_enabled ? <Badge tone="green">enabled</Badge> : <Badge>disabled</Badge>}</td>
              <td className="td"><Badge>{n.status}</Badge></td>
            </tr>
          ))}
        </Table>
      ) : <Empty title="No numbers yet" body="Add a number you have purchased or ported to your voice provider account." />}
      <Modal open={open} title="Add phone number" onClose={() => setOpen(false)}>
        <div className="space-y-3">
          <ErrorBox error={add.error} />
          <Field label="Number"><input className="input" value={form.e164} onChange={(e) => setForm({ ...form, e164: e.target.value })} placeholder="+91 80 4123 4567" /></Field>
          <Field label="Label"><input className="input" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></Field>
          <Field label="Number type" hint="India: 1600-series for service/transactional, 140-series for promotional calls">
            <select className="input" value={form.number_type} onChange={(e) => setForm({ ...form, number_type: e.target.value })}>
              <option value="service">Service / transactional</option><option value="promotional">Promotional</option><option value="other">Other</option>
            </select>
          </Field>
          <Field label="Inbound agent">
            <select className="input" value={form.inbound_agent_id} onChange={(e) => setForm({ ...form, inbound_agent_id: e.target.value })}>
              <option value="">None</option>
              {agents.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.outbound_enabled} onChange={(e) => setForm({ ...form, outbound_enabled: e.target.checked })} /> Allow outbound campaigns from this number</label>
          <button className="btn-primary" disabled={add.isPending} onClick={() => add.mutate({ ...form, inbound_agent_id: form.inbound_agent_id || null, label: form.label || null }, { onSuccess: () => setOpen(false) })}>Save</button>
        </div>
      </Modal>
    </div>
  );
}
