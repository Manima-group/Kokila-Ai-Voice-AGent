"use client";

import { useState } from "react";

import { Badge, Empty, ErrorBox, Field, Loading, Modal, PageHeader, Table } from "@/components/ui";
import { useApi, useMutate } from "@/hooks/useApi";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Page } from "@/types";

type Appt = { id: string; title: string; start_at: string; end_at: string; timezone: string; status: string; external_event_id: string | null; failure_reason: string | null };
type Conn = { id: string; provider: string; label: string; timezone: string; slot_minutes: number; status: string };

export default function Appointments() {
  const { can } = useAuth();
  const conns = useApi<Conn[]>("/calendar-connections");
  const list = useApi<Page<Appt>>("/appointments?limit=100");
  const [day, setDay] = useState(() => new Date(Date.now() + 86400000).toISOString().slice(0, 10));
  const slots = useApi<{ timezone: string; slots: string[] }>(conns.data?.length ? `/appointments/availability?day=${day}` : null);
  const [book, setBook] = useState<string | null>(null);
  const [title, setTitle] = useState("Consultation");
  const [error, setError] = useState<unknown>(null);
  const addConn = useMutate("POST", "/calendar-connections", ["/calendar-connections"]);

  const doBook = async () => {
    setError(null);
    try {
      await api("/appointments", { method: "POST", body: { start: book, title, idempotency_key: `ui-${crypto.randomUUID()}` } });
      setBook(null);
      list.refetch();
      slots.refetch();
    } catch (e) {
      setError(e);
    }
  };
  const act = async (path: string, body?: unknown) => {
    setError(null);
    try {
      await api(path, { method: "POST", body });
      list.refetch();
      slots.refetch();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div>
      <PageHeader title="Appointments" subtitle="Bookings are only marked confirmed after the authoritative calendar write succeeds." />
      <ErrorBox error={error || addConn.error} />
      {conns.isLoading ? <Loading /> : !conns.data?.length ? (
        <Empty title="No calendar connected" body="Use the Kokila calendar, or connect Google Calendar from Integrations."
          action={can("integrations:write") && <button className="btn-primary" onClick={() => addConn.mutate({ label: "Kokila calendar" })}>Create Kokila calendar</button>} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="card">
            <h2 className="mb-2 font-semibold">Availability</h2>
            <p className="mb-3 text-xs text-muted">{conns.data[0].label} ({conns.data[0].provider}) · {conns.data[0].slot_minutes}-minute slots · {conns.data[0].timezone}</p>
            <input className="input mb-3" type="date" value={day} onChange={(e) => setDay(e.target.value)} aria-label="Day" />
            <div className="flex flex-wrap gap-2">
              {slots.data?.slots.map((s) => (
                <button key={s} className="btn-secondary px-2 py-1 text-xs" disabled={!can("appointments:write")} onClick={() => setBook(s)}>
                  {new Date(s).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: slots.data?.timezone })}
                </button>
              ))}
              {slots.data && !slots.data.slots.length && <span className="text-sm text-muted">No free slots.</span>}
            </div>
          </div>
          <div className="lg:col-span-2">
            {list.data?.items.length ? (
              <Table head={["When", "Title", "Status", "Actions"]}>
                {list.data.items.map((a) => (
                  <tr key={a.id}>
                    <td className="td">{fmtDate(a.start_at)}</td>
                    <td className="td">{a.title}{a.failure_reason && <div className="text-xs text-red-600">{a.failure_reason}</div>}</td>
                    <td className="td"><Badge>{a.status}</Badge></td>
                    <td className="td">{a.status === "confirmed" && can("appointments:write") && <button className="text-sm text-red-600 hover:underline" onClick={() => act(`/appointments/${a.id}/cancel`)}>Cancel</button>}</td>
                  </tr>
                ))}
              </Table>
            ) : <Empty title="No appointments yet" />}
          </div>
        </div>
      )}
      <Modal open={!!book} title="Book appointment" onClose={() => setBook(null)}>
        <div className="space-y-3">
          <p className="text-sm">{book && fmtDate(book)}</p>
          <Field label="Title"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <button className="btn-primary" onClick={doBook}>Book</button>
        </div>
      </Modal>
    </div>
  );
}
