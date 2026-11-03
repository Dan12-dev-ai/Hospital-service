"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/shell/dashboard-shell";
import { CodeBlock } from "@/components/docs/markdown";
import { useApi } from "@/lib/api";
import { PUBLIC_API_URL, type ConnectionList } from "@/lib/connect-types";

/** Five steps from an API key to the first record, in Test mode. */
export function GettingStartedPage() {
  const { data } = useApi<ConnectionList>("connections");
  const api = data?.api_url ?? PUBLIC_API_URL;
  const tokenUrl = data?.token_url ?? `${api}/oauth/token`;
  const mrnSystem = data?.mrn_system ?? "https://endod-health.com/hospital/<your code>/mrn";
  const testKey = data?.items.find((k) => k.mode === "test");
  const clientId = testKey?.client_id ?? "endod_test_...";

  return (
    <div>
      <PageHeader
        title="Getting started"
        description="From an API key to your first record in five steps. Everything here uses a Test key: Endod checks each request exactly as in Live, and saves nothing."
      />
      <ol className="flex flex-col gap-10" data-testid="getting-started">
        <Step n={1} title="Create a Test API key">
          <p>
            Open{" "}
            <Link href="/keys" className="font-medium text-neutral-900 underline underline-offset-2">
              API keys
            </Link>
            , click <strong>Create API key</strong>, choose <strong>Test</strong> and the scopes{" "}
            <code>patients.write</code> and <code>records.labs.write</code>. Copy the client secret: it is shown once.
            {testKey && (
              <span className="mt-2 block text-emerald-700" data-testid="has-test-key">
                You have one: {testKey.name} ({testKey.client_id}).
              </span>
            )}
          </p>
        </Step>
        <Step n={2} title="Get an access token">
          <p>OAuth 2.0 client credentials. A token lives 5 minutes: get a new one when it expires.</p>
          <CodeBlock
            language="bash"
            code={`curl -s ${tokenUrl} \\\n  -u "${clientId}:$CLIENT_SECRET" \\\n  -d grant_type=client_credentials`}
          />
          <p>
            Keep <code>access_token</code> from the answer as <code>$TOKEN</code>.
          </p>
        </Step>
        <Step n={3} title="Register a patient">
          <p>Endod issues the hospital number (MRN). A Test key answers a made-up one, TEST-000001.</p>
          <CodeBlock
            language="bash"
            code={`curl -s ${api}/patients \\\n  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\\n  -d '{"full_name": "Almaz Tefera", "sex": "female", "date_of_birth": "1990-04-12", "phone": "+251911234567"}'`}
          />
        </Step>
        <Step n={4} title="Send your first record">
          <p>A lab result as a FHIR R4 Observation, naming the patient by the hospital number.</p>
          <CodeBlock
            language="bash"
            code={`curl -s ${api}/fhir/Observation \\\n  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/fhir+json" \\\n  -d '{"resourceType": "Observation", "status": "final",\n       "category": [{"coding": [{"code": "laboratory"}]}],\n       "code": {"text": "Hemoglobin"},\n       "subject": {"identifier": {"system": "${mrnSystem}", "value": "SPH-000124"}},\n       "effectiveDateTime": "2026-10-01T09:30:00+03:00",\n       "valueQuantity": {"value": 13.2, "unit": "g/dL"}}'`}
          />
          <p>
            A Test key answers <code>201</code> with what <em>would</em> be stored. Rather click than type? The{" "}
            <Link href="/playground" className="font-medium text-neutral-900 underline underline-offset-2">
              Playground
            </Link>{" "}
            sends any request in Test mode for you.
          </p>
        </Step>
        <Step n={5} title="Check the logs, then go Live">
          <p>
            Your calls appear in{" "}
            <Link href="/logs" className="font-medium text-neutral-900 underline underline-offset-2">
              Logs
            </Link>
            . When everything works, create a <strong>Live</strong> key, add a webhook to hear about bookings, and keep
            your price list in step with <code>PUT /prices/...</code>. The{" "}
            <Link href="/docs" className="font-medium text-neutral-900 underline underline-offset-2">
              Docs
            </Link>{" "}
            cover every endpoint.
          </p>
        </Step>
      </ol>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="grid grid-cols-[28px_minmax(0,1fr)] gap-4">
      <span className="flex h-7 w-7 items-center justify-center rounded-full border border-neutral-300 text-xs font-semibold text-neutral-700">
        {n}
      </span>
      <div className="docs-prose min-w-0">
        <h2 className="!mt-0.5 !text-base">{title}</h2>
        {children}
      </div>
    </li>
  );
}
