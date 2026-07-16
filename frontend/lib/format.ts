// Generic display + export helpers (report structure comes from the backend).

export interface ReportDef {
  key: string;
  name: string;
  dimensions: string[];
  metrics: string[];
  orderBy?: string;
  limit?: number;
  sheetTab?: string;
  source?: "ga4" | "moengage";
  campaignTypes?: string[];
}

export interface ComparisonRow {
  dims: Record<string, any>;
  current: Record<string, any>;
  previous: Record<string, any>;
}

export interface ComparisonData {
  name?: string;
  dimensions: string[];
  metrics: string[];
  current: { label: string; totals: Record<string, any> };
  previous: { label: string; totals: Record<string, any> };
  compared?: boolean;
  rows: ComparisonRow[];
  cached?: boolean;
  demo?: boolean;
}

export interface Profile {
  id: string;
  name: string;
  propertyId: string;
  channelGroupDim?: string;
  projectId?: string;
  spreadsheetId?: string;
  slidesId?: string;
  moengageAppId?: string;
  moengageApiKey?: string;
  moengageDataCenter?: string;
  googleAdsCustomerId?: string;
  merchantCenterId?: string;
  searchConsoleSiteUrl?: string;
  metaAdAccountId?: string;
  connectionId?: string;
}

export interface Period {
  start: string;
  end: string;
  label: string;
}

export interface Insight {
  headline: string;
  body: string;
}

const LABELS: Record<string, string> = {
  "{channelGroup}": "Channel grouping",
  sessionSourceMedium: "Source / Medium",
  sessionCampaignName: "Campaign",
  landingPagePlusQueryString: "Landing page",
  deviceCategory: "Device",
  itemName: "Item",
  sessions: "Sessions",
  totalUsers: "Users",
  activeUsers: "Users",
  transactions: "Transactions",
  conversions: "Conversions",
  totalRevenue: "Revenue",
  itemRevenue: "Revenue",
  convRate: "Conv Rate",
  itemsViewed: "Viewed",
  itemsAddedToCart: "Added to cart",
  itemsCheckedOut: "Checked out",
  itemsPurchased: "Purchased",
  // MoEngage campaign analytics
  campaignName: "Campaign",
  campaignType: "Type",
  sent: "Sent",
  delivered: "Delivered",
  opens: "Opens",
  clicks: "Clicks",
  impressions: "Impressions",
  bounces: "Bounces",
  clickRate: "CTR",
  openRate: "Open Rate",
};

/** Friendly column header for a GA4 dimension/metric API name. */
export function headerLabel(name: string): string {
  return LABELS[name] ?? name;
}

/** Format a metric value, adding % for rates and ₹ for revenue. */
export function fmtMetric(key: string, value: unknown): string {
  const low = key.toLowerCase();
  if (low.includes("rate")) return `${fmt(value)}%`;
  if (low.includes("revenue")) return `₹${fmt(value)}`;
  return fmt(value);
}

/** Light numeric formatting — thousands separators for numbers, raw for strings. */
export function fmt(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

const esc = (v: unknown) => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** Build a CSV string from a comparison report (this vs previous period). */
export function toCSV(report: ComparisonData): string {
  const { dimensions: dims, metrics: mets } = report;
  const header = [
    ...dims,
    ...mets.map((m) => `${m} (${report.current.label})`),
    ...mets.map((m) => `${m} (${report.previous.label})`),
  ];
  const lines = [header.map(esc).join(",")];
  for (const row of report.rows) {
    const line = [
      ...dims.map((d) => row.dims[d]),
      ...mets.map((m) => row.current[m]),
      ...mets.map((m) => row.previous[m]),
    ];
    lines.push(line.map(esc).join(","));
  }
  return lines.join("\n");
}

export function downloadCSV(filename: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const iso = (d: Date) => d.toISOString().slice(0, 10);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (d: Date) => `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;

export const RANGE_PRESETS = [
  { key: "lastMonth", label: "Last month vs previous" },
  { key: "thisMonth", label: "This month vs last" },
  { key: "28d", label: "Last 28 days vs previous" },
  { key: "7d", label: "Last 7 days vs previous" },
  { key: "90d", label: "Last 90 days vs previous" },
  { key: "custom", label: "Custom…" },
];

/**
 * Compute the current + previous periods (month-over-month) for a preset, as
 * explicit YYYY-MM-DD dates so the backend can run both windows.
 */
export function computeRanges(
  presetKey: string,
  custom?: { start: string; end: string },
): { current: Period; previous: Period } | null {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();

  const daysWindow = (n: number) => {
    const end = new Date(now);
    const start = new Date(now);
    start.setDate(start.getDate() - (n - 1));
    const pEnd = new Date(start);
    pEnd.setDate(pEnd.getDate() - 1);
    const pStart = new Date(pEnd);
    pStart.setDate(pStart.getDate() - (n - 1));
    return {
      current: { start: iso(start), end: iso(end), label: `Last ${n} days` },
      previous: { start: iso(pStart), end: iso(pEnd), label: `Prev ${n} days` },
    };
  };

  switch (presetKey) {
    case "7d":
      return daysWindow(7);
    case "28d":
      return daysWindow(28);
    case "90d":
      return daysWindow(90);
    case "thisMonth": {
      const cur = new Date(y, m, 1);
      const prev = new Date(y, m - 1, 1);
      return {
        current: { start: iso(cur), end: iso(now), label: monthLabel(cur) },
        previous: { start: iso(prev), end: iso(new Date(y, m, 0)), label: monthLabel(prev) },
      };
    }
    case "lastMonth": {
      const cur = new Date(y, m - 1, 1);
      const prev = new Date(y, m - 2, 1);
      return {
        current: { start: iso(cur), end: iso(new Date(y, m, 0)), label: monthLabel(cur) },
        previous: { start: iso(prev), end: iso(new Date(y, m - 1, 0)), label: monthLabel(prev) },
      };
    }
    case "custom": {
      if (!custom?.start || !custom?.end) return null;
      const cs = new Date(custom.start);
      const ce = new Date(custom.end);
      const len = Math.round((ce.getTime() - cs.getTime()) / 86400000) + 1;
      const pe = new Date(cs);
      pe.setDate(pe.getDate() - 1);
      const ps = new Date(pe);
      ps.setDate(ps.getDate() - (len - 1));
      return {
        current: { start: custom.start, end: custom.end, label: `${custom.start} → ${custom.end}` },
        previous: { start: iso(ps), end: iso(pe), label: `${iso(ps)} → ${iso(pe)}` },
      };
    }
    default:
      return null;
  }
}
