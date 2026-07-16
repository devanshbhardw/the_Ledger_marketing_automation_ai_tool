"use client";

import { useState } from "react";

import { Profile } from "@/lib/format";

const EMPTY = {
  name: "",
  propertyId: "",
  channelGroupDim: "",
  projectId: "",
  spreadsheetId: "",
  slidesId: "",
  moengageAppId: "",
  moengageApiKey: "",
  moengageDataCenter: "",
  googleAdsCustomerId: "",
  merchantCenterId: "",
  searchConsoleSiteUrl: "",
  metaAdAccountId: "",
  // Which OAuth connection the ids above came from (no input — passthrough).
  connectionId: "",
};

export type FormState = typeof EMPTY;

function fromProfile(p: Profile): FormState {
  // Pick only the editable fields (drops id and any extras).
  return Object.fromEntries(
    Object.keys(EMPTY).map((k) => [k, (p as any)[k] ?? ""]),
  ) as FormState;
}

export default function AddSiteForm({
  initial,
  prefill,
  onSaved,
  onCancel,
}: {
  initial?: Profile | null;
  prefill?: Partial<FormState>;
  onSaved: (p: Profile) => void;
  onCancel: () => void;
}) {
  const editing = !!initial;
  const [form, setForm] = useState<FormState>(
    initial ? fromProfile(initial) : { ...EMPTY, ...prefill },
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const url = editing ? `/api/ga/profiles/${initial!.id}` : "/api/ga/profiles";
      const r = await fetch(url, {
        method: editing ? "PUT" : "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(form),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Failed to save");
      onSaved(body as Profile);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="card add-form" onSubmit={submit}>
      <h3>{editing ? `Edit ${initial!.name}` : "Add a site"}</h3>
      <div className="form-grid">
        <label>
          <span>Name *</span>
          <input value={form.name} onChange={set("name")} placeholder="TTK" required />
        </label>
        <label>
          <span>GA4 Property ID *</span>
          <input value={form.propertyId} onChange={set("propertyId")} placeholder="123456789" required />
        </label>
        <label>
          <span>Custom channel-group dimension</span>
          <input
            value={form.channelGroupDim}
            onChange={set("channelGroupDim")}
            placeholder="sessionCustomChannelGroup:1234567 (optional)"
          />
        </label>
        <label>
          <span>Project ID</span>
          <input value={form.projectId} onChange={set("projectId")} placeholder="optional" />
        </label>
        <label className="wide">
          <span>Google Sheet ID (for CSV/Sheets export)</span>
          <input
            value={form.spreadsheetId}
            onChange={set("spreadsheetId")}
            placeholder="optional — spreadsheet must be shared with the service account"
          />
        </label>
        <label className="wide">
          <span>Google Slides deck ID (for PPT export)</span>
          <input
            value={form.slidesId}
            onChange={set("slidesId")}
            placeholder="optional — deck must be shared with the service account (Editor)"
          />
        </label>
        <label>
          <span>Google Ads Customer ID</span>
          <input
            value={form.googleAdsCustomerId}
            onChange={set("googleAdsCustomerId")}
            placeholder="optional — 123-456-7890"
          />
        </label>
        <label>
          <span>Merchant Center ID</span>
          <input
            value={form.merchantCenterId}
            onChange={set("merchantCenterId")}
            placeholder="optional"
          />
        </label>
        <label>
          <span>Search Console Site URL</span>
          <input
            value={form.searchConsoleSiteUrl}
            onChange={set("searchConsoleSiteUrl")}
            placeholder="optional — https://example.com/ or sc-domain:example.com"
          />
        </label>
        <label>
          <span>Meta Ad Account ID</span>
          <input
            value={form.metaAdAccountId}
            onChange={set("metaAdAccountId")}
            placeholder="optional"
          />
        </label>
        <label>
          <span>MoEngage App ID</span>
          <input
            value={form.moengageAppId}
            onChange={set("moengageAppId")}
            placeholder="optional — Settings › App Settings › APP ID"
          />
        </label>
        <label>
          <span>MoEngage Data Center</span>
          <input
            value={form.moengageDataCenter}
            onChange={set("moengageDataCenter")}
            placeholder="e.g. 01 (from api-0X.moengage.com)"
          />
        </label>
        <label className="wide">
          <span>MoEngage DATA API key</span>
          <input
            type="password"
            autoComplete="off"
            value={form.moengageApiKey}
            onChange={set("moengageApiKey")}
            placeholder="optional — Settings › APIs › DATA API Settings (stored on server)"
          />
        </label>
      </div>
      {error && <p className="muted">⚠ {error}</p>}
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? "Saving…" : editing ? "Save changes" : "Save site"}
        </button>
        <button className="btn" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
