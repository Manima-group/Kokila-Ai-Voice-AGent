"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Footer, Header } from "@/components/Brand";
import { api, KokilaApiError } from "@/lib/api";

type Item = { id: string; kind: string; content: string; revision: number; updated_at: string };

export default function MemoryPage() {
  const router = useRouter();
  const [items, setItems] = useState<Item[] | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const onErr = useCallback((e: unknown) => {
    if (e instanceof KokilaApiError && e.status === 401) router.replace("/login");
    else setError(e instanceof KokilaApiError ? e.error.message : "Network error");
  }, [router]);

  const [version, setVersion] = useState(0);
  const load = useCallback(async () => setVersion((v) => v + 1), []);

  useEffect(() => {
    let alive = true;
    api.get<{ items: Item[] }>("memory")
      .then((r) => { if (alive) setItems(r.items); })
      .catch((e) => { if (alive) { setItems([]); onErr(e); } });
    return () => { alive = false; };
  }, [version, onErr]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    try { await api.post("memory", { content: draft }); setDraft(""); await load(); } catch (err) { onErr(err); }
  }
  async function save(it: Item) {
    try {
      await api.patch(`memory/${it.id}`, { content: editing[it.id], expected_revision: it.revision });
      setEditing((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== it.id)));
      await load();
    } catch (err) { onErr(err); await load(); }
  }
  async function remove(id: string) {
    try { await api.del(`memory/${id}`); await load(); } catch (err) { onErr(err); }
  }
  async function removeAll() {
    if (!window.confirm("Delete all saved memory? This cannot be undone.")) return;
    try { await api.del("memory"); await load(); } catch (err) { onErr(err); }
  }

  return (
    <>
      <Header subtitle="MEMORY" right={<Link className="k-btn" href="/assistant">Back to assistant</Link>} />
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        <h1 className="text-2xl font-bold">What Kokila remembers about you</h1>
        <p className="text-sm text-k-grey-600">Only you can see these. Edit or delete anything at any time. Kokila does not
          save secrets, passwords, financial or health details by default.</p>
        {error && <p role="alert" className="text-sm text-k-danger">{error}</p>}
        <form onSubmit={add} className="flex gap-2">
          <input className="k-input" aria-label="New memory" placeholder="e.g. I prefer replies in Telugu"
                 value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={1000} />
          <button className="k-btn-primary" disabled={!draft.trim()}>Add</button>
        </form>
        {items === null ? <p>Loading…</p> : items.length === 0 ? (
          <p className="k-card p-4 text-sm text-k-grey-600">Nothing saved yet.</p>
        ) : (
          <ul className="space-y-2">
            {items.map((it) => (
              <li key={it.id} className="k-card flex flex-wrap items-center gap-2 p-3">
                {it.id in editing ? (
                  <input className="k-input flex-1" aria-label="Edit memory" value={editing[it.id]}
                         onChange={(e) => setEditing({ ...editing, [it.id]: e.target.value })} />
                ) : <span className="flex-1">{it.content}</span>}
                <span className="text-xs text-k-grey-600">{it.kind}</span>
                {it.id in editing
                  ? <button className="k-btn-primary" onClick={() => save(it)}>Save</button>
                  : <button className="k-btn" onClick={() => setEditing({ ...editing, [it.id]: it.content })}>Edit</button>}
                <button className="k-btn-danger" onClick={() => remove(it.id)}>Delete</button>
              </li>
            ))}
          </ul>
        )}
        {items && items.length > 0 && <button className="k-btn-danger" onClick={removeAll}>Delete all memory</button>}
      </main>
      <Footer />
    </>
  );
}
