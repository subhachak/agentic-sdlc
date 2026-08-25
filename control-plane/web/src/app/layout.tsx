import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import Masthead from "@/components/masthead";

// Self-hosted at build time, so the console has no runtime dependency on a
// font CDN — an internal tool that renders differently on a restricted
// network is a tool people stop trusting.
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

// Identifiers, paths, commit shas and counts. This console is mostly machine
// values, and giving them their own face is information design: a column of
// module paths is scannable in mono and a wall of text in a proportional.
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Agentic Delivery Control",
    template: "%s · Agentic Delivery Control",
  },
  description:
    "Enterprise control center for governed, evidence-led agentic software delivery.",
};

// Runs before first paint. Without it the stored choice is applied after
// hydration and every load flashes the other theme, which reads as a bug
// rather than a preference.
const NO_FLASH = `(function(){try{var t=localStorage.getItem("theme");if(t==="dark"||t==="light"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}})()`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <Script id="restore-theme" strategy="beforeInteractive" dangerouslySetInnerHTML={{ __html: NO_FLASH }} />
      </head>
      <body>
        <a className="skip-link" href="#main-content">Skip to main content</a>
        <Masthead />
        <div className="application-content" id="main-content">{children}</div>
      </body>
    </html>
  );
}
