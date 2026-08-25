"use client";

import { useEffect, useState } from "react";

/**
 * Three states, not two.
 *
 * "System" is a real answer and the default one — someone whose machine
 * switches at dusk expects this to follow. A two-state toggle silently
 * converts that preference into a fixed choice the first time it is
 * touched, and there is then no way back to following the machine.
 */
type Theme = "system" | "light" | "dark";

const ORDER: Theme[] = ["system", "light", "dark"];
const LABEL: Record<Theme, string> = {
  system: "Match system",
  light: "Light",
  dark: "Dark",
};

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") {
    root.removeAttribute("data-theme");
    localStorage.removeItem("theme");
  } else {
    root.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }
}

export default function ThemeToggle() {
  // Starts as "system" on both server and client so the markup matches; the
  // stored value is read after mount. The inline script in the document head
  // has already painted the right theme by then, so this is a label catching
  // up rather than a flash.
  const [theme, setTheme] = useState<Theme>("system");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "dark" || stored === "light") setTheme(stored);
    setReady(true);
  }, []);

  function cycle() {
    const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
    setTheme(next);
    apply(next);
  }

  return (
    <button
      type="button"
      className="icon-button"
      onClick={cycle}
      title={`Theme: ${LABEL[theme]}`}
      aria-label={`Theme: ${LABEL[theme]}. Activate to change.`}
    >
      <span aria-hidden style={{ opacity: ready ? 1 : 0, fontSize: "15px", lineHeight: 1 }}>
        {theme === "system" ? "◐" : theme === "light" ? "☀" : "☾"}
      </span>
    </button>
  );
}
