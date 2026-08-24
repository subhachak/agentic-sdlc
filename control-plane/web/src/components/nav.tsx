"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import ProjectSwitcher from "@/components/project-switcher";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/runs", label: "Runs" },
  { href: "/graph", label: "Context graph" },
  // Things you do, then things you set. Setup used to be buried in the graph
  // view, which made it a matter of knowing where to look.
  { href: "/operations", label: "Operations" },
  { href: "/config", label: "Configuration" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="nav">
      <div className="nav-inner">
        <span className="brand">Agentic SDLC</span>
        {LINKS.map((link) => {
          const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          return (
            <Link key={link.href} href={link.href} className={active ? "active" : undefined}>
              {link.label}
            </Link>
          );
        })}
        <ProjectSwitcher />
      </div>
    </nav>
  );
}
