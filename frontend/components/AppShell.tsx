"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { Profile } from "@/lib/format";

const REPORT_LINKS_SHOWN = 8;

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [sites, setSites] = useState<Profile[]>([]);

  useEffect(() => {
    fetch("/api/ga/profiles")
      .then((r) => r.json())
      .then((body) => setSites(body.profiles || []))
      .catch(() => {});
  }, [pathname]); // refetch on navigation so newly added sites appear

  const is = (href: string) =>
    href === "/dashboard" ? pathname === "/dashboard" || pathname === "/" : pathname.startsWith(href);

  return (
    <div className="shell">
      <aside className="side">
        <div className="side-brand-row">
          <a className="side-brand" href="/dashboard">The Ledger</a>
          <a
            className={`side-plus${is("/connections") ? " active" : ""}`}
            href="/connections"
            title="New connection"
            aria-label="New connection"
          >
            +
          </a>
        </div>

        <nav className="side-nav">
          <a href="/dashboard" className={is("/dashboard") ? "active" : ""}>▦ Overview</a>

          <div className="side-head">Reports</div>
          <div className="side-sub">
            {sites.slice(0, REPORT_LINKS_SHOWN).map((s) => (
              <a
                key={s.id}
                href={`/site/${s.id}`}
                className={pathname === `/site/${s.id}` ? "active" : ""}
              >
                {s.name}
              </a>
            ))}
            {sites.length > REPORT_LINKS_SHOWN && (
              <a href="/dashboard">All sites ({sites.length}) →</a>
            )}
            {sites.length === 0 && (
              <a href="/connections">Add your first site →</a>
            )}
          </div>

          <div className="side-head">Platform</div>
          <a href="/platform/ga4" className={is("/platform/ga4") ? "active" : ""}>◧ GA4</a>
          <a href="/platform/merchant-center" className={is("/platform/merchant-center") ? "active" : ""}>◨ Merchant Center</a>
          <a href="/platform/search-console" className={is("/platform/search-console") ? "active" : ""}>◩ Search Console</a>

          <div className="side-head">Workspace</div>
          <a href="/settings" className={is("/settings") ? "active" : ""}>⚙ Settings</a>
          <a href="/admin" className={is("/admin") ? "active" : ""}>▩ Admin</a>
        </nav>

        <div className="side-foot">The Ledger</div>
      </aside>

      <main className="content">{children}</main>
    </div>
  );
}
