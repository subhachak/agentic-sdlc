import Link from "next/link";
import RunList from "@/components/run-list";
import { listRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RunsListPage() {
  let runs;
  try {
    runs = await listRuns();
  } catch (error) {
    return (
      <main>
        <div className="page-head">
          <div className="page-head-copy"><span className="eyebrow">Governed delivery</span><h1>Delivery runs</h1></div>
        </div>
        <div className="notice crit" role="alert"><h3>Run history is unavailable</h3><p>{error instanceof Error ? error.message : String(error)}</p></div>
      </main>
    );
  }

  return (
    <main>
      <div className="page-head">
        <div className="page-head-copy">
          <span className="eyebrow">Governed delivery</span>
          <h1>Delivery runs</h1>
          <p>Follow work from requirement through design, implementation, QA evidence and release decision.</p>
        </div>
        <div className="page-actions"><Link href="/new" className="button-link"><span aria-hidden>＋</span> Start a run</Link></div>
      </div>
      <RunList runs={runs} />
    </main>
  );
}
