"use client";

// Admin view of every saved Ask Q&A across all sites (ask_history.json).

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Profile } from "@/lib/format";

interface Entry {
  profileId: string;
  question: string;
  answer: string;
  createdAt: number;
}

function fmtTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

export default function AskHistoryAdmin() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [siteFilter, setSiteFilter] = useState("");
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    Promise.all([
      fetch("/api/ga/ask/history/all").then((r) => r.json()),
      fetch("/api/ga/profiles").then((r) => r.json()),
    ])
      .then(([h, p]) => {
        setEntries(h.history || []);
        setProfiles(p.profiles || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const nameById = useMemo(
    () => new Map(profiles.map((p) => [p.id, p.name])),
    [profiles],
  );

  const visible = siteFilter
    ? entries.filter((e) => e.profileId === siteFilter)
    : entries;

  async function clearSite(profileId: string) {
    const name = nameById.get(profileId) || profileId;
    if (!confirm(`Delete all saved questions for ${name}?`)) return;
    const r = await fetch(`/api/ga/ask/history?profileId=${encodeURIComponent(profileId)}`, {
      method: "DELETE",
    });
    if (r.ok) setEntries((list) => list.filter((e) => e.profileId !== profileId));
  }

  return (
    <div className="card">
      <div className="section-head">
        <h3>Ask history</h3>
        <div className="section-actions">
          <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
            <option value="">All sites</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {siteFilter && (
            <button className="btn btn-sm" onClick={() => clearSite(siteFilter)}>
              Clear this site's history
            </button>
          )}
        </div>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Every saved question &amp; answer, stored in <code>backend/ask_history.json</code>.
      </p>

      {loading && <p className="muted">Loading…</p>}
      {!loading && visible.length === 0 && (
        <p className="muted">No saved questions yet.</p>
      )}

      {visible.map((e, i) => (
        <details
          key={`${e.profileId}-${e.createdAt}-${i}`}
          style={{ borderTop: "1px solid var(--border)", padding: "10px 0" }}
        >
          <summary style={{ cursor: "pointer", lineHeight: 1.5 }}>
            <span className="badge" style={{ marginRight: 8 }}>
              {nameById.get(e.profileId) || e.profileId}
            </span>
            {e.question}
            <span className="muted" style={{ marginLeft: 8 }}>{fmtTime(e.createdAt)}</span>
          </summary>
          <div className="ask-answer" style={{ padding: "10px 0 4px 14px" }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{e.answer}</ReactMarkdown>
          </div>
        </details>
      ))}
    </div>
  );
}
