"use client";

// One page per connected platform (GA4 / Merchant Center / Search Console).
// Lists EVERY saved site in a single table — the ID column itself communicates
// connected (shows the id) vs. not (em dash + a "Connect" link) rather than
// splitting into separate sections. Connected sites sort first.

import { useEffect, useState } from "react";

import { Profile } from "@/lib/format";

interface Connection {
  id: string;
  accountEmailOrName: string;
}

export interface PlatformConfig {
  // The Profile field holding this platform's per-site id.
  field: "propertyId" | "merchantCenterId" | "searchConsoleSiteUrl";
  // Column header for that id.
  idLabel: string;
}

// Same rule as SiteView's header badge: OAuth (with the connection's account)
// when the profile came from a connection, else the shared service account.
function credBadge(p: Profile, conns: Connection[]): string {
  if (!p.connectionId) return "Service account";
  const conn = conns.find((c) => c.id === p.connectionId);
  return `OAuth · ${conn?.accountEmailOrName || p.connectionId}`;
}

export default function PlatformView({ config }: { config: PlatformConfig }) {
  const [sites, setSites] = useState<Profile[]>([]);
  const [conns, setConns] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/ga/profiles").then((r) => r.json()),
      // Best-effort: badge falls back to the raw connectionId if this fails.
      fetch("/api/ga/connections")
        .then((r) => r.json())
        .catch(() => ({ connections: [] })),
    ])
      .then(([pBody, cBody]) => {
        setSites(pBody.profiles || []);
        setConns(cBody.connections || []);
      })
      .catch((e) => setErr(e.message || "Failed to load sites"))
      .finally(() => setLoading(false));
  }, []);

  const idOf = (p: Profile) => ((p[config.field] as string | undefined) || "").trim();

  // Connected sites (id populated) first, then unconnected; stable by name within each.
  const rows = [...sites].sort((a, b) => {
    const ha = idOf(a) ? 0 : 1;
    const hb = idOf(b) ? 0 : 1;
    if (ha !== hb) return ha - hb;
    return a.name.localeCompare(b.name);
  });

  if (loading) return <p className="ledger-empty">Loading…</p>;
  if (err) return <p className="ledger-empty">⚠ {err}</p>;
  if (rows.length === 0) return <p className="ledger-empty">No sites yet.</p>;

  return (
    <div className="card">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Site</th>
              <th>{config.idLabel}</th>
              <th>Credential source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const id = idOf(p);
              return (
                <tr key={p.id}>
                  <td><a href={`/site/${p.id}`}>{p.name}</a></td>
                  <td>
                    {id ? (
                      id
                    ) : (
                      <span className="muted">
                        — <a href="/connections">Connect</a>
                      </span>
                    )}
                  </td>
                  <td><span className="badge">{credBadge(p, conns)}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
