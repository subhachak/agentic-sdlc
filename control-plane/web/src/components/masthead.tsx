"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import ProjectSwitcher from "@/components/project-switcher";
import ThemeToggle from "@/components/theme-toggle";
import { getDashboard, PROJECTS_CHANGED } from "@/lib/api";

const NAVIGATION = [
  { href: "/", label: "Command center", short: "01", group: "Workspace" },
  { href: "/runs", label: "Delivery runs", short: "02", group: "Workspace" },
  { href: "/quality", label: "Quality evidence", short: "03", group: "Assurance" },
  { href: "/codebase", label: "Code intelligence", short: "04", group: "Assurance" },
  { href: "/setup", label: "Administration", short: "05", group: "Manage" },
] as const;

const PAGE_TITLES: Record<string, { eyebrow: string; title: string }> = {
  "/": { eyebrow: "Workspace", title: "Command center" },
  "/runs": { eyebrow: "Delivery", title: "Delivery runs" },
  "/new": { eyebrow: "Delivery", title: "Start a delivery run" },
  "/quality": { eyebrow: "Assurance", title: "Quality evidence" },
  "/codebase": { eyebrow: "Intelligence", title: "Code intelligence" },
  "/setup": { eyebrow: "Manage", title: "Administration" },
};

function pageTitle(pathname: string) {
  if (pathname.startsWith("/runs/")) {
    return { eyebrow: "Delivery run", title: pathname.split("/").pop()?.slice(0, 8) ?? "Run" };
  }
  return PAGE_TITLES[pathname] ?? { eyebrow: "Agentic delivery", title: "Control center" };
}

export default function Masthead() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [waiting, setWaiting] = useState(0);
  const [repo, setRepo] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<string | null>(null);
  const [ready, setReady] = useState<boolean | null>(null);
  const title = pageTitle(pathname);

  useEffect(() => {
    setMenuOpen(false);
    const load = () =>
      getDashboard()
        .then((dashboard) => {
          setWaiting(dashboard.runs.awaiting_human);
          setRepo(dashboard.engagement.indexed_repo);
          setEnvironment(dashboard.engagement.environment);
          setReady(dashboard.hydration.hydrated);
        })
        .catch(() => {
          setWaiting(0);
          setReady(false);
        });
    void load();
    const timer = setInterval(load, 15000);
    window.addEventListener(PROJECTS_CHANGED, load);
    return () => {
      clearInterval(timer);
      window.removeEventListener(PROJECTS_CHANGED, load);
    };
  }, [pathname]);

  return (
    <>
      <button
        className={`sidebar-scrim ${menuOpen ? "visible" : ""}`}
        aria-label="Close navigation"
        onClick={() => setMenuOpen(false)}
      />

      <aside className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Primary navigation">
        <div className="brand-block">
          <Link href="/" className="brand" aria-label="Agentic Delivery Control home">
            <span className="brand-mark" aria-hidden>
              AD
            </span>
            <span>
              <strong>Agentic Delivery</strong>
              <small>Control plane</small>
            </span>
          </Link>
        </div>

        <div className="workspace-switcher">
          <span className="nav-kicker">Active engagement</span>
          <ProjectSwitcher />
        </div>

        <nav className="sidebar-nav">
          {["Workspace", "Assurance", "Manage"].map((group) => (
            <div className="nav-group" key={group}>
              <span className="nav-kicker">{group}</span>
              {NAVIGATION.filter((item) => item.group === group).map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : item.href === "/runs"
                      ? pathname.startsWith("/runs") || pathname === "/new"
                      : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="nav-item"
                    aria-current={active ? "page" : undefined}
                  >
                    <span className="nav-index" aria-hidden>
                      {item.short}
                    </span>
                    <span>{item.label}</span>
                    {item.href === "/runs" && waiting > 0 && (
                      <span className="nav-count" aria-label={`${waiting} awaiting approval`}>
                        {waiting}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-status">
          <div className="sidebar-status-line">
            <span className={`health-dot ${ready ? "ready" : "attention"}`} />
            <span>{ready === null ? "Checking platform" : ready ? "Platform ready" : "Setup required"}</span>
          </div>
          <p>{repo ? repo.split("/").pop() : "No repository indexed"}</p>
        </div>
      </aside>

      <header className="topbar">
        <div className="topbar-leading">
          <button
            type="button"
            className="menu-button"
            aria-label="Open navigation"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}
          >
            <span />
            <span />
            <span />
          </button>
          <div className="page-identity">
            <span>{title.eyebrow}</span>
            <strong>{title.title}</strong>
          </div>
        </div>

        <div className="topbar-actions">
          {repo && (
            <div className="context-chip" title={repo}>
              <span className="context-chip-label">Repository</span>
              <code>{repo.split("/").pop()}</code>
            </div>
          )}
          {environment && <span className="environment-chip">{environment}</span>}
          <ThemeToggle />
          <Link href="/new" className="button-link topbar-primary">
            <span aria-hidden>＋</span>
            New run
          </Link>
        </div>
      </header>
    </>
  );
}
