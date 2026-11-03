"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";
import { Play } from "lucide-react";
import { ErrorState, FormError, LoadingState, inputClass, labelClass, primaryButtonClass } from "@/components/common/states";
import { PageHeader, Panel } from "@/components/shell/dashboard-shell";
import { CodeBlock } from "@/components/docs/markdown";
import { ApiError, apiFetch, useApi } from "@/lib/api";

/** One operation of the integration API's OpenAPI document. */
export type Operation = {
  id: string;
  method: string;
  path: string;
  summary: string;
  tag: string;
  /** The path with its parameters filled with sample values. */
  samplePath: string;
  /** The request body from the document's first example, pretty-printed ("" when there is none). */
  sampleBody: string;
};

type Spec = { paths?: Record<string, Record<string, unknown>> };
type Answer = { status: number; duration_ms: number; headers: Record<string, string>; body: unknown };

/** Path parameters filled with values a Test key answers (its made-up data). */
const SAMPLE_PARAMS: Record<string, string> = {
  mrn: "TEST-000001",
  booking_id: `sample${"1".padStart(26, "0")}`,
  follow_up_id: "sample-follow-up-1",
  prescription_id: "sample-prescription-1",
  resource_type: "Observation",
  resource_id: "hb-000123",
  doctor_id: "c0ffee00c0ffee00c0ffee00c0ffee00",
  entry_id: "sample-entry-1",
};

const SKIPPED = new Set(["/oauth/token", "/.well-known/jwks.json"]);
const METHODS = ["get", "post", "put", "delete"];

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function firstExample(operation: Record<string, unknown>): unknown {
  const content = record(record(operation.requestBody)?.content);
  if (!content) return undefined;
  for (const media of Object.values(content)) {
    const m = record(media);
    if (!m) continue;
    if (m.example !== undefined) return m.example;
    const examples = record(m.examples);
    if (examples) {
      const first = record(Object.values(examples)[0]);
      if (first && first.value !== undefined) return first.value;
    }
  }
  return undefined;
}

/** Every operation (but the token endpoint and the keys), with sample values. */
export function operationsOf(spec: Spec): Operation[] {
  const out: Operation[] = [];
  for (const [path, item] of Object.entries(spec.paths ?? {})) {
    if (SKIPPED.has(path)) continue;
    for (const method of METHODS) {
      const operation = record(item[method]);
      if (!operation) continue;
      const example = firstExample(operation);
      const tags = Array.isArray(operation.tags) ? operation.tags : [];
      out.push({
        id: `${method.toUpperCase()} ${path}`,
        method: method.toUpperCase(),
        path,
        summary: typeof operation.summary === "string" ? operation.summary : "",
        tag: typeof tags[0] === "string" ? tags[0] : "Other",
        samplePath: path.replace(/\{(\w+)\}/g, (_m, name: string) => SAMPLE_PARAMS[name] ?? name),
        sampleBody: example === undefined ? "" : JSON.stringify(example, null, 2),
      });
    }
  }
  return out;
}

/**
 * The playground: pick an endpoint, its request body is filled from the
 * OpenAPI examples, send it, see the answer. Always Test mode: the request
 * goes through the dashboard's server with the hospital's playground key
 * (nothing is saved, no real patient is touched).
 */
export function PlaygroundPage() {
  const { data, error, loading, reload } = useApi<Spec>("playground/spec");
  const operations = useMemo(() => (data ? operationsOf(data) : []), [data]);

  return (
    <div>
      <PageHeader
        title="Playground"
        description="Try any endpoint. Requests are sent from the dashboard's server with a Test key of its own: Endod checks them exactly as in Live, and saves nothing."
        actions={
          <span data-testid="playground-mode" className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-amber-800">
            Test mode
          </span>
        }
      />
      {loading && !data && <LoadingState label="Loading the API reference…" />}
      {error && <ErrorState message={error.message} onRetry={reload} />}
      {operations.length > 0 && <Console operations={operations} />}
    </div>
  );
}

function Console({ operations }: { operations: Operation[] }) {
  const [selected, setSelected] = useState(operations.find((o) => o.id === "GET /bookings")?.id ?? operations[0].id);
  const operation = operations.find((o) => o.id === selected) ?? operations[0];
  const [path, setPath] = useState(operation.samplePath);
  const [query, setQuery] = useState("");
  const [body, setBody] = useState(operation.sampleBody);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const tags = useMemo(() => Array.from(new Set(operations.map((o) => o.tag))), [operations]);

  function choose(id: string) {
    // A new endpoint: its sample path and body (the user edits from there).
    const next = operations.find((o) => o.id === id) ?? operations[0];
    setSelected(next.id);
    setPath(next.samplePath);
    setBody(next.sampleBody);
    setQuery("");
    setAnswer(null);
    setProblem(null);
  }

  async function send() {
    setBusy(true);
    setProblem(null);
    try {
      if (body.trim()) JSON.parse(body);
    } catch {
      setProblem("The body is not valid JSON.");
      setBusy(false);
      return;
    }
    try {
      setAnswer(await apiFetch<Answer>("playground/send", { method: "POST", body: { method: operation.method, path, query, body } }));
    } catch (err) {
      setAnswer(null);
      setProblem(err instanceof ApiError ? err.message : "Could not send the request.");
    } finally {
      setBusy(false);
    }
  }

  const hasBody = operation.method === "POST" || operation.method === "PUT";
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Panel title="Request">
        <div className="flex flex-col gap-4">
          <div>
            <label htmlFor="endpoint" className={labelClass}>
              Endpoint
            </label>
            <select id="endpoint" className={inputClass} value={selected} onChange={(e) => choose(e.target.value)}>
              {tags.map((tag) => (
                <optgroup key={tag} label={tag}>
                  {operations
                    .filter((o) => o.tag === tag)
                    .map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.method} {o.path}
                        {o.summary ? ` · ${o.summary}` : ""}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
            <div>
              <span className={labelClass}>Method</span>
              <span data-testid="method" className={cn(inputClass, "block cursor-default text-center font-mono text-xs font-semibold")}>
                {operation.method}
              </span>
            </div>
            <div>
              <label htmlFor="path" className={labelClass}>
                Path
              </label>
              <input id="path" className={cn(inputClass, "font-mono text-xs")} value={path} onChange={(e) => setPath(e.target.value)} />
            </div>
          </div>
          <div>
            <label htmlFor="query" className={labelClass}>
              Query string (optional)
            </label>
            <input
              id="query"
              className={cn(inputClass, "font-mono text-xs")}
              value={query}
              placeholder="status=confirmed&limit=10"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {hasBody && (
            <div>
              <label htmlFor="body" className={labelClass}>
                Body (from the API reference&apos;s example)
              </label>
              <textarea
                id="body"
                spellCheck={false}
                className={cn(inputClass, "min-h-[260px] font-mono text-xs leading-5")}
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
            </div>
          )}
          <FormError message={problem} />
          <div className="flex justify-end">
            <button type="button" className={primaryButtonClass} onClick={send} disabled={busy}>
              <Play className="h-3.5 w-3.5" />
              {busy ? "Sending…" : "Send request"}
            </button>
          </div>
        </div>
      </Panel>
      <Panel title="Response" testId="playground-response">
        {!answer && <p className="text-xs text-neutral-500">Send a request to see the answer here.</p>}
        {answer && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3 text-sm">
              <span
                data-testid="response-status"
                className={cn(
                  "rounded px-2 py-0.5 font-mono text-xs font-semibold",
                  answer.status < 300 ? "bg-emerald-50 text-emerald-700" : answer.status < 500 ? "bg-amber-50 text-amber-800" : "bg-rose-50 text-rose-700"
                )}
              >
                {answer.status}
              </span>
              <span className="text-xs text-neutral-500">{answer.duration_ms} ms</span>
            </div>
            {Object.keys(answer.headers).length > 0 && (
              <table className="w-full text-left text-xs" data-testid="response-headers">
                <tbody>
                  {Object.entries(answer.headers).map(([name, value]) => (
                    <tr key={name} className="border-t border-neutral-100">
                      <th className="w-40 py-1.5 pr-3 font-mono font-medium text-neutral-500">{name}</th>
                      <td className="break-all py-1.5 font-mono text-neutral-900">{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div data-testid="response-body">
              <CodeBlock language="json" code={typeof answer.body === "string" ? answer.body : JSON.stringify(answer.body, null, 2)} />
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
