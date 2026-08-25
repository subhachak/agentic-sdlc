"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import ProjectSwitcher from "@/components/project-switcher";
import ThemeToggle from "@/components/theme-toggle";
import { getDashboard, PROJECTS_CHANGED } from "@/lib/api";

/**
 * Four tabs, down from five.
 *
 * "Operations" and "Configuration" were the same subject split by verb —
 * what the platform is pointed at, and pointing it. Nobody arrives knowing
 * whether choosing a repository is a setting or an action, and the split put
 * a repository field on both pages, where they promptly disagreed. They are
 * one page now.
 *
 * The dashboard's engagement and platform cards went with them: they
 * restated the same values a third time, read-only.
 */
const TABS = [
  { href: "/", label: "Overview" },
  { href: "/runs", label: "Runs" },
  { href: "/codebase", label: "Codebase" },
  { href: "/setup", label: "Setup" },
];

export default function Masthead() {
  const pathname = usePathname();
  // Carried in the nav so "a gate is waiting for you" survives being on
  // another page. A run blocked on a person is the one thing in this system
  // that will not resolve itself.
  const [waiting, setWaiting] = useState(0);

  useEffect(() => {
    const load = () =>
      getDashboard()
        .then((d) => setWaiting(d.runs.awaiting_human))
        .catch(() => setWaiting(0));
    void load();
    const timer = setInterval(load, 15000);
    window.addEventListener(PROJECTS_CHANGED, load);
    return () => {
      clearInterval(timer);
      window.removeEventListener(PROJECTS_CHANGED, load);
    };
  }, [pathname]);

  return (
    <header className="masthead">
      <div className="masthead-inner">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden>
            A
          </span>
          Agentic SDLC
        </Link>

        <nav aria-label="Sections" style={{ display: "flex", gap: "2px" }}>
          {TABS.map((tab) => {
            const active =
              tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className="tab"
                aria-current={active ? "page" : undefined}
              >
                {tab.label}
                {tab.href === "/runs" && waiting > 0 && (
                  <>
                    <span className="tab-badge">{waiting}</span>
                    <span className="sr-only">
                      {waiting} waiting for approval
                    </span>
                  </>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="masthead-end">
          <ProjectSwitcher />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
