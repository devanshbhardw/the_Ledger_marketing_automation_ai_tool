"use client";

// The Ledger — a browsable card index of saved sites. All report/export
// logic lives on /site/[profileId] (SiteView); this page only lists.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { computeRanges, Profile, RANGE_PRESETS } from "@/lib/format";
import OverviewPanel from "./OverviewPanel";
import Sparkline from "./Sparkline";

const LAST_VIEWED_KEY = "ttk.lastViewed";

interface Connection {
  id: string;
  provider: string;
  accountEmailOrName: string;
}

function timeAgo(epochSeconds: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epochSeconds));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function stampText(conn: Connection | undefined): string {
  if (!conn) return "SA";
  const name = conn.accountEmailOrName.split("@")[0].trim();
  return (name.slice(0, 2) || "OA").toUpperCase();
}

function OverviewPicker({
  current,
  sites,
  onPick,
}: {
  current: Profile;
  sites: Profile[];
  onPick: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="Show analytics for another property"
        style={{
          font: "inherit",
          fontFamily: "var(--font-fraunces), Georgia, serif",
          fontWeight: 600,
          fontSize: 34,
          color: "var(--paper)",
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        {current.name}
        <span style={{ fontSize: 14, color: "var(--text-muted)" }}>▾</span>
      </button>
      {open && (
        <div
          className="card"
          style={{
            position: "absolute", top: "calc(100% + 8px)", left: 0, zIndex: 30,
            minWidth: 280, maxHeight: 380, overflowY: "auto",
            padding: 6, marginBottom: 0,
          }}
        >
          {sites.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => { setOpen(false); onPick(p.id); }}
              style={{
                display: "flex", justifyContent: "space-between", gap: 12,
                width: "100%", textAlign: "left", padding: "8px 10px",
                border: "none", borderRadius: 6, cursor: "pointer",
                background: p.id === current.id ? "var(--surface-0)" : "none",
                color: "var(--text-primary)", fontSize: 14,
                fontWeight: p.id === current.id ? 650 : 400,
              }}
            >
              {p.name}
              <span className="muted">{p.propertyId}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [sparks, setSparks] = useState<Record<string, { points: number[]; fetchedAt: number }>>({});
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [lastViewedId, setLastViewedId] = useState("");
  const [presetKey, setPresetKey] = useState("28d");
  const [custom, setCustom] = useState({ start: "", end: "" });

  useEffect(() => {
    setLastViewedId(localStorage.getItem(LAST_VIEWED_KEY) || "");
  }, []);

  const ranges = useMemo(() => computeRanges(presetKey, custom), [presetKey, custom]);

  useEffect(() => {
    Promise.all([
      fetch("/api/ga/profiles").then((r) => r.json()),
      fetch("/api/ga/connections").then((r) => r.json()).catch(() => ({ connections: [] })),
    ])
      .then(([p, c]) => {
        const list: Profile[] = p.profiles || [];
        setProfiles(list);
        setConnections(c.connections || []);
        // Sparklines load per card after the grid paints — never block on them.
        list.forEach((profile) => {
          fetch(`/api/ga/reports/sparkline/${profile.id}`)
            .then((r) => (r.ok ? r.json() : null))
            .then((body) => {
              if (body?.points) {
                setSparks((s) => ({
                  ...s,
                  [profile.id]: { points: body.points, fetchedAt: body.fetchedAt || 0 },
                }));
              }
            })
            .catch(() => {});
        });
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  const q = search.trim().toLowerCase();
  const visible = useMemo(
    () =>
      profiles.filter(
        (p) =>
          !q ||
          p.name.toLowerCase().includes(q) ||
          (p.propertyId || "").toLowerCase().includes(q),
      ),
    [profiles, q],
  );

  const connById = useMemo(
    () => new Map(connections.map((c) => [c.id, c])),
    [connections],
  );

  // The overview spotlights the last-viewed site (falling back to the first).
  const overviewProfile =
    profiles.find((p) => p.id === lastViewedId) || profiles[0];

  return (
    <div className="ledger-container">
      {overviewProfile ? (
        <>
          <p className="ledger-sub" style={{ marginBottom: 2 }}>
            Overview · last viewed
          </p>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
            <OverviewPicker
              current={overviewProfile}
              sites={profiles}
              onPick={(id) => {
                setLastViewedId(id);
                try {
                  localStorage.setItem(LAST_VIEWED_KEY, id);
                } catch {}
              }}
            />
            <a href={`/site/${overviewProfile.id}`} style={{ fontSize: 13 }}>
              Open full reports →
            </a>

            <div
              style={{
                marginLeft: "auto", display: "flex", gap: 10,
                alignItems: "flex-end", flexWrap: "wrap",
              }}
            >
              <div className="field">
                <label>Period</label>
                <select value={presetKey} onChange={(e) => setPresetKey(e.target.value)}>
                  {RANGE_PRESETS.map((p) => (
                    <option key={p.key} value={p.key}>{p.label.replace(/ vs .*/, "")}</option>
                  ))}
                </select>
              </div>
              {presetKey === "custom" && (
                <>
                  <div className="field">
                    <label>Start</label>
                    <input
                      type="date"
                      value={custom.start}
                      onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))}
                    />
                  </div>
                  <div className="field">
                    <label>End</label>
                    <input
                      type="date"
                      value={custom.end}
                      onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))}
                    />
                  </div>
                </>
              )}
            </div>
          </div>
          <p className="ledger-pid" style={{ marginBottom: 20 }}>
            {overviewProfile.propertyId}
            {ranges && (
              <span> · {ranges.current.start} → {ranges.current.end}</span>
            )}
          </p>
          {ranges ? (
            <OverviewPanel profile={overviewProfile} range={ranges.current} />
          ) : (
            <p className="muted">Pick a start and end date.</p>
          )}
        </>
      ) : (
        <>
          <h1>The Ledger</h1>
          <p className="ledger-sub">Every account, one page.</p>
        </>
      )}

      {overviewProfile && (
        <p className="ledger-sub" style={{ marginTop: 8 }}>
          All accounts
        </p>
      )}

      <div className="ledger-search">
        <label htmlFor="ledger-q">Search accounts</label>
        <input
          id="ledger-q"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Name or property ID…"
        />
      </div>

      {err && <p className="ledger-empty">⚠ {err}</p>}
      {loading && <p className="ledger-empty">Loading…</p>}
      {!loading && !err && visible.length === 0 && (
        <p className="ledger-empty">
          {profiles.length === 0
            ? "No accounts yet — connect one to get started."
            : `Nothing matches “${search}”.`}
        </p>
      )}

      <div className="ledger-grid">
        {visible.map((p) => {
          const conn = p.connectionId ? connById.get(p.connectionId) : undefined;
          const spark = sparks[p.id];
          return (
            <a
              key={p.id}
              className="ledger-card"
              href={`/site/${p.id}`}
              onClick={(e) => {
                e.preventDefault();
                router.push(`/site/${p.id}`);
              }}
            >
              <span
                className={`ledger-stamp${conn ? " oauth" : ""}`}
                title={conn ? `OAuth · ${conn.accountEmailOrName}` : "Service account"}
              >
                {stampText(conn)}
              </span>
              <h2>{p.name}</h2>
              <p className="ledger-pid">{p.propertyId}</p>
              {spark ? <Sparkline points={spark.points} /> : <div className="ledger-spark-empty" />}
              <p className="ledger-updated">
                {spark?.fetchedAt ? `Updated ${timeAgo(spark.fetchedAt)}` : " "}
              </p>
            </a>
          );
        })}

        {!loading && (
          <a className="ledger-add" href="/connections">
            <span>
              <span className="plus">+</span>
              <br />
              Connect account
            </span>
          </a>
        )}
      </div>
    </div>
  );
}
