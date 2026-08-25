import Link from "next/link";

export default function NotFound() {
  return (
    <main className="narrow">
      <section className="panel empty-state">
        <span className="empty-state-mark">404</span>
        <h1 style={{ fontSize: "1.25rem", margin: 0 }}>This control-plane view does not exist</h1>
        <p>The workspace is intact. Return to the command center or choose another section.</p>
        <Link href="/" className="button-link">Return to command center</Link>
      </section>
    </main>
  );
}
