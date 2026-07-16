"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ComparisonData,
  downloadCSV,
  fmt,
  fmtMetric,
  headerLabel,
  Insight,
  Period,
  ReportDef,
  toCSV,
} from "@/lib/format";

const PAGE_SIZE = 25;

export default function ReportSection({
  def,
  profileId,
  current,
  previous,
  compare,
}: {
  def: ReportDef;
  profileId: string;
  current: Period;
  previous: Period;
  compare: boolean;
}) {
  const [open, setOpen] = useState(true);
  const [page, setPage] = useState(0);
  const [data, setData] = useState<ComparisonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [insights, setInsights] = useState<Insight[] | null>(null);
  const [insightSrc, setInsightSrc] = useState<string>("");
  const [insightBusy, setInsightBusy] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    setPage(0);
    const q = new URLSearchParams({
      profileId,
      curStart: current.start,
      curEnd: current.end,
      prevStart: previous.start,
      prevEnd: previous.end,
      curLabel: current.label,
      prevLabel: previous.label,
      compare: String(compare),
    });
    fetch(`/api/ga/reports/${def.key}/compare?${q}`, { signal: ctrl.signal })
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || body.error || "Request failed");
        return body;
      })
      .then(setData)
      .catch((e) => e.name !== "AbortError" && setError(e.message))
      .finally(() => setLoading(false));
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [def.key, profileId, current.start, current.end, previous.start, previous.end, compare]);

  const loadInsights = useCallback(
    async (regenerate: boolean) => {
      setInsightBusy(true);
      try {
        const r = await fetch("/api/ga/insights", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ reportKey: def.key, profileId, current, previous, compare, regenerate }),
        });
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail || "Failed");
        setInsights(body.insights);
        setInsightSrc(body.source);
      } catch (e: any) {
        setInsightSrc(`⚠ ${e.message}`);
      } finally {
        setInsightBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [def.key, profileId, current.start, current.end, previous.start, previous.end, compare],
  );

  useEffect(() => {
    if (data && data.rows.length) {
      setInsights(null);
      loadInsights(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const mets = data?.metrics ?? [];
  const showPrev = compare && (data?.compared ?? true);
  const total = data?.rows.length ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageRows = data ? data.rows.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE) : [];

  return (
    <section className="card">
      <div className="section-head">
        <button className="section-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className="caret">{open ? "▾" : "▸"}</span> {def.name}
        </button>
        <div className="section-actions">
          {data?.demo && <span className="badge">demo</span>}
          {data?.cached !== undefined && (
            <span className="badge">{data.cached ? "cached" : "live"}</span>
          )}
          {total > 0 && <span className="muted">{total} rows</span>}
          {data && total > 0 && (
            <button
              className="btn btn-sm"
              onClick={() => downloadCSV(`${def.key}_${current.start}_${current.end}.csv`, toCSV(data))}
            >
              ⬇ CSV
            </button>
          )}
        </div>
      </div>

      {!open ? null : (
        <>
          {loading && <p className="muted">Loading…</p>}
          {error && <p className="muted">⚠ {error}</p>}
          {data && !loading && total === 0 && <p className="muted">No data for this range.</p>}

          {data && total > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  {showPrev && (
                    <tr>
                      <th colSpan={data.dimensions.length} />
                      <th className="num grp" colSpan={mets.length}>{data.current.label}</th>
                      <th className="num grp" colSpan={mets.length}>{data.previous.label}</th>
                    </tr>
                  )}
                  <tr>
                    {data.dimensions.map((d) => (
                      <th key={d}>{headerLabel(d)}</th>
                    ))}
                    {mets.map((m) => (
                      <th key={`c-${m}`} className="num">{headerLabel(m)}</th>
                    ))}
                    {showPrev &&
                      mets.map((m) => (
                        <th key={`p-${m}`} className="num">{headerLabel(m)}</th>
                      ))}
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row, i) => (
                    <tr key={i}>
                      {data.dimensions.map((d) => (
                        <td key={d}>{fmt(row.dims[d])}</td>
                      ))}
                      {mets.map((m) => (
                        <td key={`c-${m}`} className="num">{fmtMetric(m, row.current[m])}</td>
                      ))}
                      {showPrev &&
                        mets.map((m) => (
                          <td key={`p-${m}`} className="num">{fmtMetric(m, row.previous[m])}</td>
                        ))}
                    </tr>
                  ))}
                  {page === pageCount - 1 && (
                    <tr className="total-row">
                      <td colSpan={data.dimensions.length}>Grand Total</td>
                      {mets.map((m) => (
                        <td key={`ct-${m}`} className="num">{fmtMetric(m, data.current.totals[m])}</td>
                      ))}
                      {showPrev &&
                        mets.map((m) => (
                          <td key={`pt-${m}`} className="num">{fmtMetric(m, data.previous.totals[m])}</td>
                        ))}
                    </tr>
                  )}
                </tbody>
              </table>

              {pageCount > 1 && (
                <div className="pager">
                  <button className="btn btn-sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
                    ← Prev
                  </button>
                  <span className="muted">
                    {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
                  </span>
                  <button
                    className="btn btn-sm"
                    onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                    disabled={page >= pageCount - 1}
                  >
                    Next →
                  </button>
                </div>
              )}
            </div>
          )}

          {data && total > 0 && (
            <div className="insights">
              <div className="insights-head">
                <strong>Insights</strong>
                <span className="muted">{insightSrc && `· ${insightSrc}`}</span>
                <button className="btn btn-sm" onClick={() => loadInsights(true)} disabled={insightBusy}>
                  {insightBusy ? "…" : "↻ Regenerate"}
                </button>
              </div>
              {!insights && insightBusy && <p className="muted">Generating…</p>}
              {insights?.map((ins, i) => (
                <p key={i} className="insight">
                  → <strong>{ins.headline}</strong> {ins.body}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
