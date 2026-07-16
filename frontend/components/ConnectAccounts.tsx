"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { FormState } from "./AddSiteForm";

interface Connection {
  id: string;
  provider: "google" | "meta";
  accountEmailOrName: string;
  scopes: string;
  createdAt: number;
}

interface DiscoveredProperty {
  provider: string;
  type: "ga4" | "google_ads" | "merchant_center" | "search_console" | "meta_ads";
  externalId: string;
  displayName: string;
  accountName: string;
}

const TYPE_LABELS: Record<DiscoveredProperty["type"], string> = {
  ga4: "GA4",
  google_ads: "Google Ads",
  merchant_center: "Merchant Center",
  search_console: "Search Console",
  meta_ads: "Meta Ads",
};

// Per-type badge accent so each source is visually distinct in the list.
const TYPE_BADGE_COLORS: Record<DiscoveredProperty["type"], string> = {
  ga4: "#e8710a", // Analytics orange
  google_ads: "#1a73e8", // Ads blue
  merchant_center: "#188038", // Shopping green
  search_console: "#8430ce", // Search Console purple
  meta_ads: "#0866ff", // Meta blue
};

// Which AddSiteForm field each property type prefills.
const TYPE_FIELDS: Record<DiscoveredProperty["type"], keyof FormState> = {
  ga4: "propertyId",
  google_ads: "googleAdsCustomerId",
  merchant_center: "merchantCenterId",
  search_console: "searchConsoleSiteUrl",
  meta_ads: "metaAdAccountId",
};

type Discovery =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      properties: DiscoveredProperty[];
      total: number;
      hasMore: boolean;
      page: number;
      loadingMore?: boolean;
    };

const PAGE_SIZE = 25;

const selKey = (connId: string, p: DiscoveredProperty) =>
  `${connId}::${p.type}::${p.externalId}`;

// Reduce a property/account name to a bare comparison slug, e.g.
//   "tjori - GA4"        -> "tjori"
//   "sc-domain:tjori.com"-> "tjori"
//   "https://www.tjori.com/" -> "tjori"
//   "TJORI"              -> "tjori"
function normalizeSlug(raw: string): string {
  let s = (raw || "").toLowerCase().trim();
  s = s.replace(/^https?:\/\//, ""); // strip protocol
  s = s.replace(/^sc-domain:/, ""); // strip Search Console domain prefix
  s = s.replace(/^www\./, ""); // strip www.
  s = s.replace(/\/+$/, ""); // strip trailing slash(es)
  s = s.replace(/[\s\-–—]*ga4\s*$/, ""); // strip a trailing "- GA4" style suffix
  s = s.trim();
  if (s.includes(".")) s = s.split(".")[0]; // domain -> registrable label ("tjori.com" -> "tjori")
  return s.replace(/[^a-z0-9]/g, ""); // drop remaining spaces/punctuation
}

// A candidate can carry its identifying name in either field (SC uses the site
// URL, MC often the shop name), so match on whichever normalizes to the slug.
function candidateMatches(p: DiscoveredProperty, slug: string): boolean {
  if (!slug) return false;
  return (
    normalizeSlug(p.displayName) === slug || normalizeSlug(p.accountName) === slug
  );
}

export default function ConnectAccounts() {
  const router = useRouter();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [discoveries, setDiscoveries] = useState<Record<string, Discovery>>({});
  const [selected, setSelected] = useState<
    Record<string, { connId: string; prop: DiscoveredProperty }>
  >({});
  // GA4 selKey -> type labels auto-checked alongside it (for the inline note).
  const [autoMatched, setAutoMatched] = useState<Record<string, string[]>>({});
  const [search, setSearch] = useState("");
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  function loadPage(connId: string, page: number, refresh = false) {
    if (page === 1) {
      setDiscoveries((d) => ({ ...d, [connId]: { status: "loading" } }));
    } else {
      setDiscoveries((d) => {
        const cur = d[connId];
        return cur?.status === "ready"
          ? { ...d, [connId]: { ...cur, loadingMore: true } }
          : d;
      });
    }
    const params = `page=${page}&pageSize=${PAGE_SIZE}${refresh ? "&refresh=true" : ""}`;
    fetch(`/api/ga/connections/${connId}/properties?${params}`)
      .then(async (r) => {
        const b = await r.json();
        if (!r.ok) throw new Error(b.detail || "Discovery failed");
        setDiscoveries((d) => {
          const prev = d[connId];
          const existing = page > 1 && prev?.status === "ready" ? prev.properties : [];
          return {
            ...d,
            [connId]: {
              status: "ready",
              properties: [...existing, ...(b.properties || [])],
              total: b.total ?? 0,
              hasMore: !!b.hasMore,
              page,
            },
          };
        });
      })
      .catch((e) =>
        setDiscoveries((d) => ({
          ...d,
          [connId]: { status: "error", message: e.message },
        })),
      );
  }

  useEffect(() => {
    fetch("/api/ga/connections")
      .then((r) => r.json())
      .then((body) => {
        const list: Connection[] = body.connections || [];
        setConnections(list);
        list.forEach((c) => loadPage(c.id, 1));
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function disconnect(id: string) {
    if (!confirm("Disconnect this account? Its stored tokens are revoked.")) return;
    const r = await fetch(`/api/ga/connections/${id}`, { method: "DELETE" });
    if (r.ok) {
      setConnections((list) => list.filter((c) => c.id !== id));
      setSelected((sel) =>
        Object.fromEntries(Object.entries(sel).filter(([, v]) => v.connId !== id)),
      );
    }
  }

  const q = search.trim().toLowerCase();
  const matches = (p: DiscoveredProperty) =>
    !q ||
    p.displayName.toLowerCase().includes(q) ||
    (p.accountName || "").toLowerCase().includes(q);

  // Group each connection's properties by accountName for collapsible headers.
  const groups = useMemo(() => {
    const out: Record<string, { name: string; props: DiscoveredProperty[] }[]> = {};
    for (const [connId, disc] of Object.entries(discoveries)) {
      if (disc.status !== "ready") continue;
      const byAccount = new Map<string, DiscoveredProperty[]>();
      for (const p of disc.properties) {
        const name = p.accountName || "Other";
        byAccount.set(name, [...(byAccount.get(name) || []), p]);
      }
      out[connId] = [...byAccount.entries()].map(([name, props]) => ({ name, props }));
    }
    return out;
  }, [discoveries]);

  const selectedList = Object.values(selected);

  // Toggle a property's selection. Checking a GA4 property triggers a one-time
  // suggestion: if exactly one Merchant Center and/or exactly one Search Console
  // entry in the same connection shares the GA4 account's normalized slug, we
  // auto-check it too and note it under the row. Ambiguous (0 or >1) is left
  // alone — we don't guess.
  function toggleSelect(connId: string, p: DiscoveredProperty, checked: boolean) {
    const k = selKey(connId, p);
    setSelected((sel) => {
      const next = { ...sel };
      if (checked) next[k] = { connId, prop: p };
      else delete next[k];
      return next;
    });

    if (p.type !== "ga4") return; // auto-match only runs off a GA4 selection

    if (!checked) {
      // Drop the note when the GA4 row is unchecked; leave the user's other
      // selections as-is so they stay in control.
      setAutoMatched((m) => {
        if (!(k in m)) return m;
        const next = { ...m };
        delete next[k];
        return next;
      });
      return;
    }

    const disc = discoveries[connId];
    if (!disc || disc.status !== "ready") return;
    const slug = normalizeSlug(p.accountName);
    if (!slug) return;

    const toCheck: DiscoveredProperty[] = [];
    const labels: string[] = [];
    for (const type of ["merchant_center", "search_console"] as const) {
      const cands = disc.properties.filter(
        (c) => c.type === type && candidateMatches(c, slug),
      );
      if (cands.length === 1) {
        toCheck.push(cands[0]);
        labels.push(TYPE_LABELS[type]);
      }
    }

    if (toCheck.length === 0) return;
    setSelected((sel) => {
      const next = { ...sel };
      for (const c of toCheck) next[selKey(connId, c)] = { connId, prop: c };
      return next;
    });
    setAutoMatched((m) => ({ ...m, [k]: labels }));
  }

  async function useSelected() {
    const form: Partial<FormState> = {};
    let connectionId = "";
    for (const { connId, prop } of selectedList) {
      const field = TYPE_FIELDS[prop.type];
      if (!form[field]) {
        form[field] = prop.externalId;
        // Prefer the connection the GA4 property came from.
        if (prop.type === "ga4" || !connectionId) connectionId = connId;
      }
      if (prop.type === "ga4" && !form.name) form.name = prop.displayName;
    }
    if (!form.propertyId) {
      setCreateErr("Select a GA4 property — it provides the site's name and property id.");
      return;
    }
    setCreating(true);
    setCreateErr(null);
    try {
      const r = await fetch("/api/ga/profiles", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...form, connectionId }),
      });
      const created = await r.json();
      if (!r.ok) throw new Error(created.detail || "Failed to create site");
      // Fine-tune anything (channel group, exports…) via ✎ Edit site afterward.
      router.push(`/site/${created.id}`);
    } catch (e: any) {
      setCreateErr(e.message);
      setCreating(false);
    }
  }

  if (loading) return <p className="muted">Loading…</p>;

  return (
    <>
      <div className="controls">
        <a className="btn" href="/oauth/google/login">🔑 Connect Google account</a>
        <a className="btn" href="/oauth/meta/login">🔑 Connect Meta account</a>
        <div className="field" style={{ marginLeft: "auto" }}>
          <label>Search properties</label>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by name or account…"
          />
        </div>
        <button
          className="btn btn-primary"
          onClick={useSelected}
          disabled={selectedList.length === 0 || creating}
        >
          {creating
            ? "Creating site…"
            : `Use selected in new site${selectedList.length ? ` (${selectedList.length})` : ""}`}
        </button>
      </div>

      {err && <p className="muted">⚠ {err}</p>}
      {createErr && <p className="muted">⚠ {createErr}</p>}

      {connections.length === 0 && (
        <p className="muted">
          No accounts connected yet. Connect a Google or Meta account to discover the
          GA4 properties and ad accounts it can access.
        </p>
      )}

      {connections.map((conn) => {
        const disc = discoveries[conn.id];
        return (
          <div className="card" key={conn.id}>
            <div className="section-head">
              <h3>
                {conn.provider === "google" ? "Google" : "Meta"} ·{" "}
                {conn.accountEmailOrName}
              </h3>
              <div className="section-actions">
                <span className="badge">{conn.provider}</span>
                <button
                  className="btn btn-sm"
                  onClick={() => loadPage(conn.id, 1, true)}
                  title="Re-query the provider (results are cached for 10 minutes)"
                >
                  ↻ Refresh
                </button>
                <button className="btn btn-sm" onClick={() => disconnect(conn.id)}>
                  Disconnect
                </button>
              </div>
            </div>

            {(!disc || disc.status === "loading") && (
              <p className="muted">Discovering accounts…</p>
            )}
            {disc?.status === "error" && <p className="muted">⚠ {disc.message}</p>}

            {disc?.status === "ready" &&
              (groups[conn.id] || []).map((group) => {
                const visible = group.props.filter(matches);
                const groupMatches =
                  visible.length > 0 || (!!q && group.name.toLowerCase().includes(q));
                if (q && !groupMatches) return null;
                const key = `${conn.id}::${group.name}`;
                // Collapsed by default; search matches force groups open.
                const open = opened.has(key) || (!!q && groupMatches);
                const shown = q ? visible : group.props;
                return (
                  <div key={key} style={{ marginBottom: 6 }}>
                    <button
                      type="button"
                      className="section-toggle"
                      onClick={() =>
                        setOpened((s) => {
                          const next = new Set(s);
                          next.has(key) ? next.delete(key) : next.add(key);
                          return next;
                        })
                      }
                    >
                      <span className="caret">{open ? "▾" : "▸"}</span>
                      {group.name}
                      <span className="muted">({group.props.length})</span>
                    </button>
                    {open &&
                      shown.map((p) => {
                        const k = selKey(conn.id, p);
                        const note = autoMatched[k];
                        return (
                          <div key={k}>
                            <label className="compare-toggle" style={{ padding: "4px 0 4px 20px" }}>
                              <input
                                type="checkbox"
                                checked={k in selected}
                                onChange={(e) => toggleSelect(conn.id, p, e.target.checked)}
                              />
                              {p.displayName}
                              <span className="muted">{p.externalId}</span>
                              <span
                                className="badge"
                                style={{ color: TYPE_BADGE_COLORS[p.type], borderColor: TYPE_BADGE_COLORS[p.type] }}
                              >
                                {TYPE_LABELS[p.type]}
                              </span>
                            </label>
                            {note && note.length > 0 && (
                              <p
                                className="muted"
                                style={{ margin: "0 0 4px 46px", fontSize: 12 }}
                              >
                                Also matched: {note.join(", ")}
                              </p>
                            )}
                          </div>
                        );
                      })}
                  </div>
                );
              })}

            {disc?.status === "ready" && disc.hasMore && (
              <button
                className="btn btn-sm"
                style={{ marginTop: 6 }}
                disabled={disc.loadingMore}
                onClick={() => loadPage(conn.id, disc.page + 1)}
              >
                {disc.loadingMore
                  ? "Loading…"
                  : `Load more (${disc.properties.length} of ${disc.total})`}
              </button>
            )}
          </div>
        );
      })}
    </>
  );
}
