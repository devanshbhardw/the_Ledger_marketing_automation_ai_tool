"use client";

// GA4-style at-a-glance summary for one site: KPI tiles, 7-day trend,
// top channels and device split — all from existing (cached) report routes.

import { useEffect, useMemo, useState } from "react";

import { Period, Profile } from "@/lib/format";
import Sparkline from "./Sparkline";

interface ReportData {
  dimensions: string[];
  metrics: string[];
  rows: Record<string, any>[];
  totals: Record<string, any>;
}

function fmt(n: any): string {
  const v = Number(n);
  if (!isFinite(v)) return "—";
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(2)} L`;
  return Math.round(v).toLocaleString();
}

export default function OverviewPanel({
  profile,
  range,
}: {
  profile: Profile;
  range?: Period; // omitted -> backend default (last 28 days)
}) {
  const [spark, setSpark] = useState<number[]>([]);
  const [traffic, setTraffic] = useState<ReportData | null>(null);
  const [devices, setDevices] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);

  const rangeLabel = range?.label || "28 days";

  useEffect(() => {
    setLoading(true);
    setTraffic(null);
    setDevices(null);
    setSpark([]);
    const get = (url: string) =>
      fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const dates = range ? `&startDate=${range.start}&endDate=${range.end}` : "";
    Promise.all([
      get(`/api/ga/reports/sparkline/${profile.id}`),
      get(`/api/ga/reports/traffic-acquisition?profileId=${profile.id}${dates}`),
      get(`/api/ga/reports/device-category?profileId=${profile.id}${dates}`),
    ])
      .then(([s, t, d]) => {
        if (s?.points) setSpark(s.points);
        if (t?.rows) setTraffic(t);
        if (d?.rows) setDevices(d);
      })
      .finally(() => setLoading(false));
  }, [profile.id, range?.start, range?.end]);

  // traffic-acquisition is channel × source/medium — roll it up by channel.
  const channels = useMemo(() => {
    if (!traffic) return [];
    const dim = traffic.dimensions[0];
    const byChannel = new Map<string, number>();
    for (const row of traffic.rows) {
      const key = String(row[dim] ?? "—");
      byChannel.set(key, (byChannel.get(key) || 0) + Number(row.sessions || 0));
    }
    return [...byChannel.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [traffic]);

  const kpi = (label: string, value: string) => (
    <div className="kpi" key={label}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );

  if (loading) return <p className="muted">Loading overview…</p>;
  if (!traffic && !devices && spark.length === 0) {
    return <p className="muted">No overview data available for this site yet.</p>;
  }

  const totals = traffic?.totals || {};
  const revenue = devices?.totals?.totalRevenue;

  return (
    <>
      <div className="kpis">
        {kpi(`Sessions · ${rangeLabel}`, fmt(totals.sessions))}
        {kpi(`Users · ${rangeLabel}`, fmt(totals.totalUsers))}
        {kpi(`Conversions · ${rangeLabel}`, fmt(totals.conversions))}
        {kpi(`Revenue · ${rangeLabel}`, revenue !== undefined ? `₹${fmt(revenue)}` : "—")}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 14,
          marginBottom: 24,
        }}
      >
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>Sessions — last 7 days</h3>
          <Sparkline points={spark} height={64} />
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <h3>Top channels</h3>
          {channels.length === 0 && <p className="muted">No channel data.</p>}
          <table>
            <tbody>
              {channels.map(([name, sessions]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td className="num">{fmt(sessions)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <h3>Devices</h3>
          {!devices?.rows.length && <p className="muted">No device data.</p>}
          <table>
            <tbody>
              {(devices?.rows || []).slice(0, 4).map((row) => (
                <tr key={String(row.deviceCategory)}>
                  <td>{String(row.deviceCategory)}</td>
                  <td className="num">{fmt(row.sessions)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
