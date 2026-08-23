"use client";

import { useEffect, useState } from "react";

type Claim = {
  id: string;
  policyholder: string;
  status: string;
  lastUpdated: string;
};

const STATUS_OPTIONS = ["All", "Under Review", "Approved", "Denied"];

export default function ClaimsPage() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [status, setStatus] = useState("All");

  useEffect(() => {
    const url = status === "All" ? "/api/claims" : `/api/claims?status=${encodeURIComponent(status)}`;
    fetch(url)
      .then((r) => r.json())
      .then((d) => setClaims(d.claims));
  }, [status]);

  return (
    <main style={{ padding: 32, fontFamily: "sans-serif" }}>
      <h1>Claims</h1>

      <label htmlFor="status-filter" style={{ marginRight: 8 }}>
        Filter by status:
      </label>
      <select
        id="status-filter"
        data-testid="status-filter"
        value={status}
        onChange={(e) => setStatus(e.target.value)}
      >
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>

      <table data-testid="claims-table" style={{ marginTop: 16 }}>
        <thead>
          <tr>
            <th>ID</th>
            <th>Policyholder</th>
            <th>Status</th>
            <th>Last Updated</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((c) => (
            <tr key={c.id} data-testid="claim-row" data-status={c.status}>
              <td>{c.id}</td>
              <td>{c.policyholder}</td>
              <td>{c.status}</td>
              <td>{c.lastUpdated}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {claims.length === 0 && <p data-testid="empty-state">No claims match this filter.</p>}
    </main>
  );
}
