"use client";

import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";

function apply(theme: Theme) {
  if (theme === "system") {
    document.documentElement.removeAttribute("data-theme");
    localStorage.removeItem("theme");
  } else {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "light" || stored === "dark") setTheme(stored);
  }, []);

  return (
    <label className="theme-control">
      <span className="sr-only">Appearance</span>
      <span aria-hidden>◐</span>
      <select
        aria-label="Appearance"
        value={theme}
        onChange={(event) => {
          const next = event.target.value as Theme;
          setTheme(next);
          apply(next);
        }}
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}
