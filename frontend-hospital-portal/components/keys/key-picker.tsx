"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { EmptyState, ErrorState, inputClass, labelClass } from "@/components/common/states";
import { useApi } from "@/lib/api";
import type { Connection, ConnectionList } from "@/lib/connect-types";
import { KeyPickerSkeleton } from "@/components/common/page-skeletons";

/**
 * Loads the hospital's API keys and lets the page work on one of them (the
 * first by default): Webhooks and Logs are per key.
 */
export function WithKey({
  children,
  skeleton,
}: {
  children: (connection: Connection, reload: () => void) => ReactNode;
  /** What the page shows for a key, as a skeleton while the keys load. */
  skeleton?: ReactNode;
}) {
  const { data, error, loading, reload } = useApi<ConnectionList>("connections");
  const [chosen, setChosen] = useState<string | null>(null);

  if (loading && !data) return <KeyPickerSkeleton>{skeleton}</KeyPickerSkeleton>;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;
  if (data.items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-neutral-300">
        <EmptyState icon="key" title="No API keys yet">
          <Link href="/keys" className="font-medium text-neutral-900 underline underline-offset-2">
            Create an API key
          </Link>{" "}
          first.
        </EmptyState>
      </div>
    );
  }
  const connection = data.items.find((c) => c.id === chosen) ?? data.items[0];
  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-sm">
        <label htmlFor="key-picker" className={labelClass}>
          API key
        </label>
        <select
          id="key-picker"
          className={inputClass}
          value={connection.id}
          onChange={(event) => setChosen(event.target.value)}
        >
          {data.items.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.mode === "live" ? "Live" : "Test"})
            </option>
          ))}
        </select>
      </div>
      <div key={connection.id}>{children(connection, reload)}</div>
    </div>
  );
}
