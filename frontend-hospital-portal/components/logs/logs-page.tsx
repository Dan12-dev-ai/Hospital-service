"use client";

import { cn } from "cn";
import { RefreshCw } from "lucide-react";
import { ErrorState } from "@/components/common/states";
import { PageHeader, Panel } from "@/components/shell/dashboard-shell";
import { WithKey } from "@/components/keys/key-picker";
import { useSignedIn } from "@/components/session/session-context";
import { useApi } from "@/lib/api";
import type { Connection, RequestLogEntry } from "@/lib/connect-types";
import { formatDateTime } from "@/lib/format";
import { LogTableSkeleton, LogsBodySkeleton } from "@/components/common/page-skeletons";

/** Logs: each key's recent API requests (method, path, status, time, address; never a body). */
export function LogsPage() {
  return (
    <div>
      <PageHeader
        title="Logs"
        description="The last 50 requests of each key, kept 30 days: method, path, status, duration and address. Never the data sent."
      />
      <WithKey skeleton={<LogsBodySkeleton />}>{(connection) => <RequestLog connection={connection} />}</WithKey>
    </div>
  );
}

function RequestLog({ connection }: { connection: Connection }) {
  const signedIn = useSignedIn();
  const { data, error, loading, reload } = useApi<{ items: RequestLogEntry[] }>(`connections/${connection.id}/requests`);
  const zone = signedIn?.hospital.timezone;
  return (
    <Panel
      title="Recent requests"
      actions={
        <button type="button" onClick={reload} className="inline-flex items-center gap-1 text-xs font-medium text-neutral-600 hover:text-neutral-900">
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      }
    >
      {loading && !data && <LogTableSkeleton rows={6} />}
      {error && <ErrorState message={error.message} onRetry={reload} className="p-4" />}
      {data && data.items.length === 0 && (
        <p className="text-xs text-neutral-500" data-testid="no-requests">
          No requests yet. Get a token and make your first call: see Getting started.
        </p>
      )}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs" data-testid="request-log">
            <thead className="text-neutral-500">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Time</th>
                <th className="py-1.5 pr-3 font-medium">Request</th>
                <th className="py-1.5 pr-3 font-medium">Status</th>
                <th className="py-1.5 pr-3 font-medium">Duration</th>
                <th className="py-1.5 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row, index) => (
                <tr key={`${row.at}-${index}`} className="border-t border-neutral-100">
                  <td className="whitespace-nowrap py-1.5 pr-3">{formatDateTime(row.at, zone)}</td>
                  <td className="py-1.5 pr-3 font-mono">
                    <span className="mr-2 font-semibold">{row.method}</span>
                    {row.path}
                  </td>
                  <td className={cn("py-1.5 pr-3 font-medium", row.status < 400 ? "text-emerald-700" : "text-rose-600")}>
                    {row.status}
                  </td>
                  <td className="py-1.5 pr-3">{row.duration_ms} ms</td>
                  <td className="py-1.5 font-mono">{row.ip ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
