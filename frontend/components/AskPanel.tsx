"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface QA {
  question: string;
  answer?: string;
  error?: string;
}

interface HistoryEntry {
  question: string;
  answer: string;
  createdAt: number;
}

function fmtTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export default function AskPanel({ profileId }: { profileId: string }) {
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState<QA[]>([]);
  const [asking, setAsking] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[] | null>(null);

  // Fresh panel per site; history stays behind its button.
  useEffect(() => {
    setThread([]);
    setShowHistory(false);
    setHistory(null);
  }, [profileId]);

  function toggleHistory() {
    const opening = !showHistory;
    setShowHistory(opening);
    if (opening) {
      setHistory(null); // re-fetch each open so new questions show up
      fetch(`/api/ga/ask/history?profileId=${encodeURIComponent(profileId)}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((body) => setHistory((body?.history || []).slice().reverse())) // newest first
        .catch(() => setHistory([]));
    }
  }

  async function clearHistory() {
    if (!confirm("Clear this site's saved questions and answers?")) return;
    const r = await fetch(`/api/ga/ask/history?profileId=${encodeURIComponent(profileId)}`, {
      method: "DELETE",
    });
    if (r.ok) setHistory([]);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || asking) return;
    setQuestion("");
    setAsking(true);
    setThread((t) => [...t, { question: q }]);
    try {
      const r = await fetch("/api/ga/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ profileId, question: q }),
      });
      const body = await r.json();
      if (r.status === 501) {
        throw new Error("Set ANTHROPIC_API_KEY in backend/.env to enable this");
      }
      if (!r.ok) throw new Error(body.detail || "Ask failed");
      setThread((t) =>
        t.map((qa, i) => (i === t.length - 1 ? { ...qa, answer: body.answer } : qa)),
      );
    } catch (err: any) {
      setThread((t) =>
        t.map((qa, i) => (i === t.length - 1 ? { ...qa, error: err.message } : qa)),
      );
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="card">
      <div className="section-head">
        <h3 style={{ margin: 0 }}>Ask</h3>
        <button className="btn btn-sm" onClick={toggleHistory}>
          {showHistory ? "Close history" : "🕘 History"}
        </button>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Ask a question about this site's data — any time range works
        (&quot;last week&quot;, &quot;March vs April&quot;…).
      </p>

      {showHistory && (
        <div
          style={{
            border: "1px solid var(--border)", borderRadius: 8,
            padding: "4px 14px 10px", marginBottom: 16,
            maxHeight: 420, overflowY: "auto",
          }}
        >
          <div className="section-head" style={{ marginBottom: 0, paddingTop: 10 }}>
            <h3 style={{ margin: 0 }}>Previous questions</h3>
            {!!history?.length && (
              <button className="btn btn-sm" onClick={clearHistory}>Clear all</button>
            )}
          </div>
          {history === null && <p className="muted">Loading…</p>}
          {history?.length === 0 && <p className="muted">No saved questions for this site yet.</p>}
          {(history || []).map((h, i) => (
            <details
              key={`${h.createdAt}-${i}`}
              style={{ borderTop: i ? "1px solid var(--border)" : "none", padding: "8px 0" }}
            >
              <summary style={{ cursor: "pointer", lineHeight: 1.5 }}>
                {h.question}
                <span className="muted" style={{ marginLeft: 8 }}>{fmtTime(h.createdAt)}</span>
              </summary>
              <div className="ask-answer" style={{ padding: "8px 0 4px 14px" }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{h.answer}</ReactMarkdown>
              </div>
            </details>
          ))}
        </div>
      )}

      {thread.map((qa, i) => (
        <div key={i} style={{ marginBottom: 14 }}>
          <p style={{ margin: "0 0 6px", fontWeight: 600 }}>You: {qa.question}</p>
          {qa.answer !== undefined && (
            <div className="ask-answer">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{qa.answer}</ReactMarkdown>
            </div>
          )}
          {qa.error && <p className="muted" style={{ margin: 0 }}>⚠ {qa.error}</p>}
          {qa.answer === undefined && !qa.error && (
            <p className="muted" style={{ margin: 0 }}>Thinking…</p>
          )}
        </div>
      ))}

      <form onSubmit={submit} style={{ display: "flex", gap: 10 }}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Which channel drove the most sessions in June?"
          style={{
            flex: 1, padding: "8px 10px", borderRadius: 8,
            border: "1px solid var(--border)", background: "var(--surface-0)",
            color: "var(--text-primary)", fontSize: 14,
          }}
        />
        <button className="btn btn-primary" type="submit" disabled={asking || !question.trim()}>
          {asking ? "Asking…" : "Ask"}
        </button>
      </form>
    </div>
  );
}
