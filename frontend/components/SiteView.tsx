"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { computeRanges, Profile, RANGE_PRESETS, ReportDef } from "@/lib/format";
import AddSiteForm from "./AddSiteForm";
import AskPanel from "./AskPanel";
import JobsPanel from "./JobsPanel";
import ReportSection from "./ReportSection";

interface Connection {
  id: string;
  provider: string;
  accountEmailOrName: string;
}

const SITE_LIST_PREVIEW = 10;

interface DiscoveredSite {
  connectionId: string;
  propertyId: string;
  displayName: string;
  accountName: string;
}

function SiteSwitcher({ current, sites }: { current: Profile; sites: Profile[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredSite[] | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [addingId, setAddingId] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // Lazily discover connection properties the first time the menu opens —
  // the same GA4 lists /connections shows, minus already-saved ones.
  useEffect(() => {
    if (!open || discovered !== null || discovering) return;
    setDiscovering(true);
    fetch("/api/ga/connections")
      .then((r) => r.json())
      .then(async (body) => {
        const conns: Connection[] = body.connections || [];
        const results = await Promise.all(
          conns.map((c) =>
            fetch(`/api/ga/connections/${c.id}/properties`)
              .then((r) => (r.ok ? r.json() : { properties: [] }))
              .then((b) =>
                (b.properties || [])
                  .filter((p: any) => p.type === "ga4")
                  .map((p: any): DiscoveredSite => ({
                    connectionId: c.id,
                    propertyId: p.externalId,
                    displayName: p.displayName,
                    accountName: p.accountName,
                  })))
              .catch(() => []),
          ),
        );
        setDiscovered(results.flat());
      })
      .catch(() => setDiscovered([]))
      .finally(() => setDiscovering(false));
  }, [open, discovered, discovering]);

  async function addAndOpen(site: DiscoveredSite) {
    setAddingId(site.propertyId);
    try {
      const r = await fetch("/api/ga/profiles", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: site.displayName,
          propertyId: site.propertyId,
          connectionId: site.connectionId,
        }),
      });
      const created = await r.json();
      if (!r.ok) throw new Error(created.detail || "Failed to add site");
      setOpen(false);
      router.push(`/site/${created.id}`);
    } catch {
      setAddingId("");
    }
  }

  const saved = sites.length ? sites : [current];
  const savedIds = new Set(saved.map((p) => p.propertyId));
  const unsaved = (discovered || []).filter((d) => !savedIds.has(d.propertyId));
  const shownUnsaved = showAll ? unsaved : unsaved.slice(0, SITE_LIST_PREVIEW);
  const hidden = unsaved.length - shownUnsaved.length;

  const rowStyle = (active: boolean): React.CSSProperties => ({
    display: "flex", justifyContent: "space-between", gap: 12,
    width: "100%", textAlign: "left", padding: "8px 10px",
    border: "none", borderRadius: 6, cursor: "pointer",
    background: active ? "var(--surface-0)" : "none",
    color: "var(--text-primary)", fontSize: 14,
    fontWeight: active ? 650 : 400,
  });

  const headStyle: React.CSSProperties = {
    padding: "6px 10px 2px", fontSize: 11, textTransform: "uppercase",
    letterSpacing: "0.04em", color: "var(--text-muted)",
  };

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        className="section-toggle"
        style={{ fontSize: 16 }}
        onClick={() => setOpen((o) => !o)}
        title="Switch site"
      >
        {current.name} <span className="caret">▾</span>
      </button>
      {open && (
        <div
          className="card"
          style={{
            position: "absolute", top: "calc(100% + 8px)", left: 0, zIndex: 30,
            minWidth: 260, maxHeight: 420, overflowY: "auto",
            padding: 6, marginBottom: 0,
          }}
        >
          <div style={headStyle}>Saved sites</div>
          {saved.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => { setOpen(false); router.push(`/site/${p.id}`); }}
              style={rowStyle(p.id === current.id)}
            >
              {p.name}
              <span className="muted">{p.propertyId}</span>
            </button>
          ))}

          <div style={headStyle}>From connections</div>
          {discovering && <p className="muted" style={{ margin: "4px 10px" }}>Discovering…</p>}
          {!discovering && discovered !== null && unsaved.length === 0 && (
            <p className="muted" style={{ margin: "4px 10px" }}>
              {discovered.length === 0
                ? <>No connected accounts — <a href="/connections">connect one</a></>
                : "All discovered properties are already saved."}
            </p>
          )}
          {shownUnsaved.map((d) => (
            <button
              key={`${d.connectionId}-${d.propertyId}`}
              type="button"
              disabled={!!addingId}
              onClick={() => addAndOpen(d)}
              title={`${d.accountName} — saves this property as a site and opens it`}
              style={rowStyle(false)}
            >
              {addingId === d.propertyId ? "Adding…" : d.displayName}
              <span className="muted">{d.propertyId}</span>
            </button>
          ))}
          {hidden > 0 && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              style={{
                width: "100%", padding: "8px 10px", border: "none",
                borderTop: "1px solid var(--border)", borderRadius: 0,
                background: "none", cursor: "pointer",
                color: "var(--accent)", fontSize: 13, textAlign: "left",
              }}
            >
              View {hidden} more…
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function SiteView({ profileId }: { profileId: string }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [allProfiles, setAllProfiles] = useState<Profile[]>([]);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [defs, setDefs] = useState<ReportDef[]>([]);
  const [demo, setDemo] = useState(false);
  const [presetKey, setPresetKey] = useState("lastMonth");
  const [custom, setCustom] = useState({ start: "", end: "" });
  const [compare, setCompare] = useState(true);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [exportMsg, setExportMsg] = useState<{ text: string; url?: string } | null>(null);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    setEditing(false);
    setExportMsg(null);
    try {
      localStorage.setItem("ttk.lastViewed", profileId);
    } catch {}
    Promise.all([
      fetch(`/api/ga/profiles/${profileId}`).then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || "Failed to load site");
        return body as Profile;
      }),
      fetch("/api/ga/reports").then((r) => r.json()),
      fetch("/api/ga/profiles").then((r) => r.json()).catch(() => ({ profiles: [] })),
    ])
      .then(([p, r, all]) => {
        setProfile(p);
        setAllProfiles(all.profiles || []);
        setDefs(r.reports || []);
        setDemo(!!r.demo);
        if (p.connectionId) {
          fetch("/api/ga/connections")
            .then((res) => res.json())
            .then((body) =>
              setConnection(
                (body.connections || []).find((c: Connection) => c.id === p.connectionId) || null,
              ))
            .catch(() => {});
        }
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [profileId]);

  const ranges = useMemo(() => computeRanges(presetKey, custom), [presetKey, custom]);

  async function runExport(kind: "sheets" | "slides") {
    if (!profile || !ranges) return;
    setBusy(kind);
    setExportMsg({ text: kind === "slides" ? "Building slides…" : "Exporting to sheet…" });
    try {
      const payload =
        kind === "slides"
          ? { profileId, current: ranges.current, previous: ranges.previous }
          : { profileId, startDate: ranges.current.start, endDate: ranges.current.end };
      const r = await fetch(`/api/ga/export/${kind}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Export failed");
      if (body.demo) setExportMsg({ text: body.message });
      else if (kind === "slides") setExportMsg({ text: `Built ${body.slides} slides ✓`, url: body.url });
      else setExportMsg({ text: `Exported ${body.tabs.length} tabs ✓`, url: body.url });
    } catch (e: any) {
      setExportMsg({ text: `⚠ ${e.message}` });
    } finally {
      setBusy("");
    }
  }

  if (loading) return <p className="muted">Loading…</p>;
  if (err || !profile) {
    return (
      <p className="muted">
        ⚠ {err || "Site not found."} <a href="/dashboard">Back to dashboard</a>
      </p>
    );
  }

  const credBadge = profile.connectionId
    ? `OAuth · ${connection?.accountEmailOrName || profile.connectionId}`
    : "Service account";
  const canSheets = !!profile.spreadsheetId;
  const canSlides = !!profile.slidesId;

  return (
    <>
      <div className="topbar">
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <SiteSwitcher current={profile} sites={allProfiles} />
          <span className="muted">({profile.propertyId})</span>
        </div>
        <span className="badge">{credBadge}</span>
      </div>

      <div className="container">
        {demo && (
          <div className="demo-banner">
            🧪 <strong>Demo mode</strong> — synthetic data + rule-based insights (no service-account
            key / no ANTHROPIC_API_KEY). Add keys to fetch real GA4 data and Claude insights.
          </div>
        )}

        <div className="controls">
          <div className="field">
            <label>Period (month-over-month)</label>
            <select value={presetKey} onChange={(e) => setPresetKey(e.target.value)}>
              {RANGE_PRESETS.map((p) => (
                <option key={p.key} value={p.key}>{p.label}</option>
              ))}
            </select>
          </div>

          {presetKey === "custom" && (
            <>
              <div className="field">
                <label>Start</label>
                <input type="date" value={custom.start} onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))} />
              </div>
              <div className="field">
                <label>End</label>
                <input type="date" value={custom.end} onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))} />
              </div>
            </>
          )}

          <label className="compare-toggle">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
            Compare to previous
          </label>

          <button className="btn" onClick={() => setEditing((e) => !e)}>
            {editing ? "Close" : "✎ Edit site"}
          </button>

          <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {exportMsg && (
              <span className="muted">
                {exportMsg.text}{" "}
                {exportMsg.url && <a href={exportMsg.url} target="_blank" rel="noreferrer">Open ↗</a>}
              </span>
            )}
            <button
              className="btn"
              onClick={() => runExport("sheets")}
              disabled={!canSheets || !ranges || !!busy}
              title={canSheets ? "Export to Google Sheets" : "Add a Google Sheet ID via ✎ Edit site first"}
            >
              ⬇ Sheets
            </button>
            <button
              className="btn btn-primary"
              onClick={() => runExport("slides")}
              disabled={!canSlides || !ranges || !!busy}
              title={canSlides ? "Generate Google Slides deck" : "Add a Slides deck ID via ✎ Edit site first"}
            >
              🖼 Generate Slides
            </button>
          </div>
        </div>

        {ranges && (
          <p className="muted" style={{ marginTop: -8 }}>
            {compare ? (
              <>
                Comparing <strong>{ranges.current.label}</strong> ({ranges.current.start} → {ranges.current.end})
                vs <strong>{ranges.previous.label}</strong> ({ranges.previous.start} → {ranges.previous.end})
              </>
            ) : (
              <>
                Showing <strong>{ranges.current.label}</strong> ({ranges.current.start} → {ranges.current.end})
              </>
            )}
          </p>
        )}

        {editing && (
          <AddSiteForm
            key={profile.id}
            initial={profile}
            onCancel={() => setEditing(false)}
            onSaved={(p) => {
              setProfile(p);
              setEditing(false);
            }}
          />
        )}

        {!ranges && <p className="muted">Pick a start and end date.</p>}

        {ranges &&
          defs.map((def) => (
            <ReportSection
              key={`${def.key}-${profile.id}-${ranges.current.start}-${ranges.previous.start}-${compare}`}
              def={def}
              profileId={profile.id}
              current={ranges.current}
              previous={ranges.previous}
              compare={compare}
            />
          ))}

        <JobsPanel profileId={profile.id} />
        <AskPanel profileId={profile.id} />
      </div>
    </>
  );
}
