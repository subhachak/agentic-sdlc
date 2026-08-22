"use client";

import { useEffect, useState } from "react";

type Claim = {
  id: string;
  policyholder: string;
  status: string;
  lastUpdated: string;
};

export default function ClaimsPage() {
  const [claims, setClaims] = useState<Claim[]>([]);

  useEffect(() => {
    fetch("/api/claims")
      .then((r) => r.json())
      .then((d) => setClaims(d.claims));
  }, []);

  return (
    <main style={{ padding: 32, fontFamily: "sans-serif" }}>
      <h1>Claims</h1>
      <table data-testid="claims-table">
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
    </main>
  );
}
