"use client";

import { useEffect, useState } from "react";

interface Job {
  id: string;
  profileId: string;
  type: "sheets_export" | "slides_export" | "insights_digest";
  frequency: "daily" | "weekly" | "monthly";
  hour: number;
  enabled: boolean;
  lastRunAt: number;
  nextRunAt: number;
  createdAt: number;
}

const TYPE_LABELS: Record<Job["type"], string> = {
  sheets_export: "Sheets export",
  slides_export: "Slides export",
  insights_digest: "Insights digest",
};

const FREQUENCY_HINTS: Record<Job["frequency"], string> = {
  daily: "daily",
  weekly: "weekly · Mondays",
  monthly: "monthly · 1st",
};

function fmtTime(epochSeconds: number): string {
  if (!epochSeconds) return "—";
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export default function JobsPanel({ profileId }: { profileId: string }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ type: "sheets_export", frequency: "monthly", hour: 8 });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`/api/ga/jobs?profileId=${encodeURIComponent(profileId)}`)
      .then((r) => r.json())
      .then((body) => setJobs(body.jobs || []))
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [profileId]);

  async function addJob(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const r = await fetch("/api/ga/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ profileId, ...form }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Failed to add job");
      setJobs((list) => [...list, body as Job]);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function toggle(job: Job) {
    const r = await fetch(`/api/ga/jobs/${job.id}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled: !job.enabled }),
    });
    const body = await r.json();
    if (r.ok) setJobs((list) => list.map((j) => (j.id === job.id ? (body as Job) : j)));
    else setErr(body.detail || "Failed to update job");
  }

  async function remove(job: Job) {
    if (!confirm(`Delete the ${TYPE_LABELS[job.type]} job?`)) return;
    const r = await fetch(`/api/ga/jobs/${job.id}`, { method: "DELETE" });
    if (r.ok) setJobs((list) => list.filter((j) => j.id !== job.id));
    else setErr("Failed to delete job");
  }

  return (
    <div className="card">
      <h3>Jobs</h3>

      {loading && <p className="muted">Loading…</p>}
      {!loading && jobs.length === 0 && (
        <p className="muted">No scheduled jobs yet — add one below to run exports or insights automatically.</p>
      )}

      {jobs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Schedule</th>
                <th>Next run</th>
                <th>Last run</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    {TYPE_LABELS[job.type]}{" "}
                    {!job.enabled && <span className="badge">paused</span>}
                  </td>
                  <td className="muted">
                    {FREQUENCY_HINTS[job.frequency]} · {String(job.hour).padStart(2, "0")}:00
                  </td>
                  <td>{job.enabled ? fmtTime(job.nextRunAt) : "—"}</td>
                  <td className="muted">{fmtTime(job.lastRunAt)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <label className="compare-toggle" style={{ display: "inline-flex", marginRight: 10 }}>
                      <input type="checkbox" checked={job.enabled} onChange={() => toggle(job)} />
                      Enabled
                    </label>
                    <button className="btn btn-sm" onClick={() => remove(job)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form className="controls" style={{ marginBottom: 0 }} onSubmit={addJob}>
        <div className="field">
          <label>Job</label>
          <select value={form.type} onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}>
            <option value="sheets_export">Sheets export</option>
            <option value="slides_export">Slides export</option>
            <option value="insights_digest">Insights digest</option>
          </select>
        </div>
        <div className="field">
          <label>Frequency</label>
          <select value={form.frequency} onChange={(e) => setForm((f) => ({ ...f, frequency: e.target.value }))}>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly (Mondays)</option>
            <option value="monthly">Monthly (1st)</option>
          </select>
        </div>
        <div className="field">
          <label>At hour</label>
          <select value={form.hour} onChange={(e) => setForm((f) => ({ ...f, hour: Number(e.target.value) }))}>
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>
            ))}
          </select>
        </div>
        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? "Adding…" : "+ Add job"}
        </button>
      </form>

      {err && <p className="muted" style={{ marginBottom: 0 }}>⚠ {err}</p>}
    </div>
  );
}
