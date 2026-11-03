"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Check, Copy } from "lucide-react";
import { slugify } from "@/lib/docs";

/**
 * A small Markdown renderer for the integration guide (a document Endod
 * writes, not user input): headings, paragraphs, lists (with nested blocks),
 * tables, fenced code with a copy button, inline code, bold, italics and
 * links. Everything becomes React elements: no HTML is ever injected.
 */
export function Markdown({ source }: { source: string }) {
  return <div className="docs-prose">{blocks(source.split("\n"), "b")}</div>;
}

const LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

function dedent(lines: string[], width: number): string[] {
  return lines.map((line) => (line.slice(0, width).trim() === "" ? line.slice(width) : line.trimStart()));
}

function blocks(lines: string[], keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  let i = 0;
  let n = 0;
  const key = () => `${keyPrefix}-${n++}`;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    // Fenced code
    const fence = /^```(\w*)\s*$/.exec(trimmed);
    if (fence) {
      const indent = indentOf(line);
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        code.push(lines[i].slice(Math.min(indent, indentOf(lines[i]) || 0)));
        i += 1;
      }
      i += 1;
      out.push(<CodeBlock key={key()} language={fence[1]} code={code.join("\n")} />);
      continue;
    }
    // Headings
    const heading = /^(#{2,4})\s+(.*)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2];
      const id = slugify(text);
      if (level === 2) out.push(<h2 key={key()} id={id}>{inline(text)}</h2>);
      else if (level === 3) out.push(<h3 key={key()} id={id}>{inline(text)}</h3>);
      else out.push(<h4 key={key()} id={id}>{inline(text)}</h4>);
      i += 1;
      continue;
    }
    // Tables
    if (trimmed.startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(lines[i].trim());
        i += 1;
      }
      out.push(<Table key={key()} rows={rows} />);
      continue;
    }
    // Lists
    const item = LIST_ITEM.exec(line);
    if (item) {
      const baseIndent = item[1].length;
      const ordered = /\d/.test(item[2]);
      const items: string[][] = [];
      while (i < lines.length) {
        const current = lines[i];
        const match = LIST_ITEM.exec(current);
        if (match && match[1].length === baseIndent) {
          items.push([match[3]]);
          i += 1;
          continue;
        }
        if (!current.trim()) {
          // A blank line: the list goes on only if indented content follows.
          const next = lines[i + 1];
          if (next !== undefined && next.trim() && indentOf(next) > baseIndent) {
            items[items.length - 1].push("");
            i += 1;
            continue;
          }
          break;
        }
        if (indentOf(current) > baseIndent) {
          items[items.length - 1].push(current);
          i += 1;
          continue;
        }
        break;
      }
      const ListTag = ordered ? "ol" : "ul";
      out.push(
        <ListTag key={key()}>
          {items.map((content, index) => {
            const [first, ...rest] = content;
            const width = Math.max(...rest.filter((l) => l.trim()).map(indentOf), baseIndent + 2);
            const nested = rest.length ? dedent(rest, Math.min(width, baseIndent + 3)) : [];
            // A first line and its plain continuation lines form the item's text; the rest are blocks.
            const textLines = [first];
            let j = 0;
            while (j < nested.length && nested[j].trim() && !/^(\||```|[-*]\s|\d+\.\s)/.test(nested[j].trim())) {
              textLines.push(nested[j].trim());
              j += 1;
            }
            const remaining = nested.slice(j);
            return (
              <li key={index}>
                {inline(textLines.join(" "))}
                {remaining.some((l) => l.trim()) && blocks(remaining, `${keyPrefix}-${n}-${index}`)}
              </li>
            );
          })}
        </ListTag>
      );
      continue;
    }
    // Paragraph
    const paragraph: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^```/.test(lines[i].trim()) &&
      !/^#{2,4}\s/.test(lines[i].trim()) &&
      !lines[i].trim().startsWith("|") &&
      !(paragraph.length > 0 && LIST_ITEM.test(lines[i]) && indentOf(lines[i]) === 0)
    ) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    out.push(<p key={key()}>{inline(paragraph.join(" "))}</p>);
  }
  return out;
}

function cells(row: string): string[] {
  const inner = row.replace(/^\|/, "").replace(/\|$/, "");
  // A pipe inside `code` is part of the cell.
  const parts: string[] = [];
  let current = "";
  let code = false;
  for (const char of inner) {
    if (char === "`") code = !code;
    if (char === "|" && !code) {
      parts.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  parts.push(current.trim());
  return parts;
}

function Table({ rows }: { rows: string[] }) {
  const [head, separator, ...body] = rows;
  const hasHead = separator !== undefined && /^\|?\s*:?-{2,}/.test(separator);
  const bodyRows = hasHead ? body : rows.slice(1);
  return (
    <div className="docs-table">
      <table>
        {hasHead && (
          <thead>
            <tr>
              {cells(head).map((cell, index) => (
                <th key={index}>{inline(cell)}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {bodyRows.map((row, r) => (
            <tr key={r}>
              {cells(row).map((cell, index) => (
                <td key={index}>{inline(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const LANGUAGE_LABELS: Record<string, string> = {
  bash: "cURL",
  python: "Python",
  javascript: "Node.js",
  json: "JSON",
  csharp: "C#",
};

export function CodeBlock({ language, code }: { language?: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const label = language ? (LANGUAGE_LABELS[language] ?? language) : "";
  return (
    <div className="docs-code group" data-testid="code-block">
      <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-1.5">
        <span className="text-[11px] font-medium text-neutral-400">{label}</span>
        <button
          type="button"
          aria-label="Copy code"
          data-testid="copy-code"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(code);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            } catch {
              setCopied(false);
            }
          }}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-neutral-400 hover:bg-neutral-800 hover:text-white"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

/** Inline Markdown: `code`, **bold**, *italics*, [links](url). */
export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    const token = match[0];
    const k = `i${index++}`;
    if (token.startsWith("`")) {
      out.push(<code key={k}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      out.push(<strong key={k}>{inline(token.slice(2, -2))}</strong>);
    } else if (token.startsWith("*")) {
      out.push(<em key={k}>{inline(token.slice(1, -1))}</em>);
    } else {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      if (link) {
        const [, label, href] = link;
        if (href.startsWith("/")) {
          out.push(
            <Link key={k} href={href}>
              {inline(label)}
            </Link>
          );
        } else if (/^https:\/\//.test(href)) {
          out.push(
            <a key={k} href={href} target="_blank" rel="noreferrer">
              {inline(label)}
            </a>
          );
        } else {
          out.push(label);
        }
      }
    }
    last = start + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
