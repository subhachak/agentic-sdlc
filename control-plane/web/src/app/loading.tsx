export default function Loading() {
  return (
    <main aria-busy="true" aria-label="Loading workspace">
      <div className="loading-head"><span /><span /></div>
      <div className="loading-grid">{Array.from({ length: 4 }).map((_, index) => <span key={index} />)}</div>
      <div className="loading-panel"><span /><span /><span /><span /></div>
    </main>
  );
}
