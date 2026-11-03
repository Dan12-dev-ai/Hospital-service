"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { cn } from "cn";
import { ArrowLeft, ArrowRight, ExternalLink } from "lucide-react";
import { ErrorState, LoadingState } from "@/components/common/states";
import { Markdown } from "@/components/docs/markdown";
import { useApi } from "@/lib/api";
import type { GuideSource } from "@/lib/api-types";
import { buildPages, navGroups, navLabel, type DocPage } from "@/lib/docs";

function hrefOf(page: DocPage): string {
  return page.slug ? `/docs/${page.slug}` : "/docs";
}

/**
 * The integration guide as pages: a sidebar listing every section, the page,
 * previous and next. The guide comes from the hospital service (the same
 * text as the API's OpenAPI description and docs/integrations.md).
 */
export function DocsPage() {
  const params = useParams<{ slug?: string[] }>();
  const slug = (Array.isArray(params.slug) ? params.slug : []).join("/");
  const { data, error, loading, reload } = useApi<GuideSource>("developer/guide");
  const pages = useMemo(() => (data ? buildPages(data.markdown) : []), [data]);

  if (loading && !data) return <LoadingState label="Loading the docs…" />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;
  const index = pages.findIndex((p) => p.slug === slug);
  const page = index >= 0 ? pages[index] : null;
  const previous = index > 0 ? pages[index - 1] : null;
  const next = index >= 0 && index < pages.length - 1 ? pages[index + 1] : null;

  return (
    <div className="grid gap-10 lg:grid-cols-[200px_minmax(0,1fr)]">
      <nav aria-label="Docs" data-testid="docs-nav" className="lg:sticky lg:top-8 lg:max-h-[calc(100vh-4rem)] lg:self-start lg:overflow-y-auto">
        {navGroups(pages).map((group) => (
          <div key={group.name} className="mb-5">
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-neutral-400">{group.name}</p>
            <ul className="space-y-0.5 border-l border-neutral-200">
              {group.pages.map((p) => {
                const active = p.slug === slug;
                return (
                  <li key={p.slug}>
                    <Link
                      href={hrefOf(p)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "-ml-px block border-l py-1 pl-3 text-[13px]",
                        active
                          ? "border-neutral-900 font-medium text-neutral-900"
                          : "border-transparent text-neutral-500 hover:border-neutral-400 hover:text-neutral-900"
                      )}
                    >
                      {navLabel(p)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
        <div className="mb-5">
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-neutral-400">API reference</p>
          <ul className="space-y-1 text-[13px]">
            <li>
              <a href={data.docs_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-neutral-500 hover:text-neutral-900">
                Swagger <ExternalLink className="h-3 w-3" />
              </a>
            </li>
            <li>
              <a href={data.openapi_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-neutral-500 hover:text-neutral-900">
                openapi.json <ExternalLink className="h-3 w-3" />
              </a>
            </li>
          </ul>
        </div>
      </nav>

      <article className="min-w-0 max-w-3xl" data-testid="docs-article">
        {page ? (
          <>
            {page.group !== "More" && <p className="text-xs font-medium text-neutral-500">{page.group}</p>}
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-neutral-900">{page.title}</h1>
            <div className="mt-6">
              <Markdown source={page.markdown} />
            </div>
            <div className="mt-14 flex items-center justify-between gap-4 border-t border-neutral-200 pt-6 text-sm">
              {previous ? (
                <Link href={hrefOf(previous)} className="inline-flex items-center gap-1.5 text-neutral-500 hover:text-neutral-900">
                  <ArrowLeft className="h-4 w-4" />
                  {navLabel(previous)}
                </Link>
              ) : (
                <span />
              )}
              {next && (
                <Link href={hrefOf(next)} className="inline-flex items-center gap-1.5 font-medium text-neutral-900">
                  {navLabel(next)}
                  <ArrowRight className="h-4 w-4" />
                </Link>
              )}
            </div>
          </>
        ) : (
          <div>
            <h1 className="text-2xl font-semibold text-neutral-900">Page not found</h1>
            <p className="mt-2 text-sm text-neutral-500">
              <Link href="/docs" className="underline underline-offset-2">
                Back to the docs
              </Link>
            </p>
          </div>
        )}
      </article>
    </div>
  );
}
