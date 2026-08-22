import Link from "next/link";

export default function Home() {
  return (
    <main style={{ padding: 32, fontFamily: "sans-serif" }}>
      <h1>Claims Lite</h1>
      <p>
        <Link href="/claims" data-testid="nav-claims">
          View claims
        </Link>
      </p>
    </main>
  );
}
