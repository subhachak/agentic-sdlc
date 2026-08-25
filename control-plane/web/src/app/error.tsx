"use client";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main>
      <div className="page-head"><div className="page-head-copy"><span className="eyebrow">Workspace error</span><h1>This view could not be loaded</h1><p>The rest of the control plane remains available from the navigation.</p></div></div>
      <div className="notice crit" role="alert"><h3>Something interrupted this page</h3><p>{error.message || "An unexpected application error occurred."}</p><button type="button" className="secondary" style={{ marginTop: 12 }} onClick={reset}>Try again</button></div>
    </main>
  );
}
