"use client";

import { useParams } from "next/navigation";
import { ErrorState, LoadingState, primaryButtonClass } from "@/components/common/states";
import { useApi } from "@/lib/api";
import type { ApiInfo, Connection } from "@/lib/connect-types";

const ID_PATTERN = /^[0-9a-f]{32}$/;

/**
 * A printable page for the hospital's IT team: the connection's details,
 * where to get a token and send records, and the developer guide. Never the
 * secret (it was shown once, when the system was connected).
 */
export function SetupGuide() {
  const params = useParams<{ id: string }>();
  const id = typeof params.id === "string" && ID_PATTERN.test(params.id) ? params.id : null;
  const { data, error, loading } = useApi<ApiInfo & { connection: Connection }>(id ? `connections/${id}` : null);

  if (!id) return <ErrorState message="Unknown connection." className="m-6" />;
  if (loading && !data) return <LoadingState label="Preparing the setup guide…" className="m-6" />;
  if (error || !data) return <ErrorState message={error?.message ?? "Could not load the connection."} className="m-6" />;
  const c = data.connection;
  const rows: [string, string][] = [
    ["System", c.name],
    ["Mode", c.mode === "live" ? "Live (real patient records)" : "Test (checks everything, saves nothing)"],
    ["Client ID", c.client_id],
    ["Client secret", "Not in this guide: it was shown once, when the system was connected. Keep it in your secret store."],
    ["Authentication", c.auth_method === "private_key_jwt" ? "Signed client assertion (private_key_jwt, ES256 or RS256)" : "Client secret (HTTP Basic or form)"],
    ["Token URL", data.token_url],
    ["API base URL", data.api_url],
    ["FHIR endpoint", data.fhir_url],
    ["Token signing keys", data.jwks_url],
    ["Patient numbers (MRN) system", data.mrn_system],
    ["Endod ID system", "https://endod-health.com/id"],
    ["Developer guide", data.docs_url],
  ];
  if (c.webhook_url) rows.push(["Webhook URL", c.webhook_url]);
  if (c.allowed_ips.length) rows.push(["Allowed addresses", c.allowed_ips.join(", ")]);
  const granted = data.scopes.filter((s) => c.scopes.includes(s.scope));

  return (
    <main data-testid="setup-guide" className="mx-auto max-w-3xl bg-white p-8 text-sm text-slate-800 print:p-0">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Endod Health</p>
          <h1 className="text-2xl font-bold">Setup guide: {c.name}</h1>
        </div>
        <button type="button" className={`${primaryButtonClass} print:hidden`} onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </div>
      <table className="w-full border-collapse text-left">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-t border-slate-200 align-top">
              <th className="w-56 py-2 pr-4 font-semibold text-slate-600">{label}</th>
              <td className="break-all py-2 font-mono text-xs">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2 className="mb-2 mt-6 text-base font-bold">What it may do (scopes)</h2>
      <table className="w-full border-collapse text-left">
        <tbody>
          {granted.map((s) => (
            <tr key={s.scope} className="border-t border-slate-200 align-top">
              <th className="w-56 py-2 pr-4 font-semibold text-slate-600">{s.label}</th>
              <td className="py-2">
                <code className="font-mono text-xs">{s.scope}</code>
                <span className="block text-xs text-slate-500">{s.description}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2 className="mb-2 mt-6 text-base font-bold">Get a token</h2>
      <pre className="overflow-x-auto rounded-xl bg-slate-50 p-3 text-xs">
        {`curl -s ${data.token_url} \\\n  -u "${c.client_id}:$CLIENT_SECRET" \\\n  -d grant_type=client_credentials`}
      </pre>
      <p className="mt-6 text-xs text-slate-500">
        The full guide (patients, FHIR examples, webhooks, errors and limits): {data.docs_url}
      </p>
    </main>
  );
}
