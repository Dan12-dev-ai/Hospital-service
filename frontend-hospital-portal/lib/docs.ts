/**
 * The integration guide (backend-hospital/app/integrations/guide.md, the
 * single source of truth) split into the dashboard's Docs pages: one page per
 * "## " section, and one per record type under Records ("### Lab results",
 * ...). Hidden blocks (<!-- ... -->, e.g. video visits while they are off)
 * never show.
 */

export type DocPage = {
  /** "" (the introduction), "authentication", "records/lab-results", ... */
  slug: string;
  title: string;
  group: string;
  markdown: string;
};

const GROUPS: { name: string; slugs: string[] }[] = [
  { name: "Get started", slugs: ["", "connect-your-system", "authentication"] },
  {
    name: "Records",
    slugs: [
      "records",
      "records/lab-results",
      "records/imaging-reports",
      "records/prescriptions",
      "records/diagnoses",
      "records/visit-notes",
      "records/documents",
    ],
  },
  { name: "Patient journey", slugs: ["patients", "bookings", "the-queue", "follow-ups", "prescriptions-dispensed"] },
  { name: "Prices and charges", slugs: ["pricing", "charges"] },
  { name: "Reference", slugs: ["webhooks", "errors", "limits", "test-mode", "what-endod-keeps"] },
];

/** The record types that get a page of their own (### headings under Records). */
const RECORD_TYPES = new Set(["Lab results", "Imaging reports", "Prescriptions", "Diagnoses", "Visit notes", "Documents"]);

export function stripComments(markdown: string): string {
  return markdown.replace(/<!--[\s\S]*?-->\n?/g, "");
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/`/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** "## 3. Records (FHIR R4)" -> "Records"; "## 6. The queue (`queue.write`)" -> "The queue". */
export function sectionTitle(heading: string): string {
  return heading
    .replace(/^#+\s*/, "")
    .replace(/^\d+\.\s*/, "")
    .replace(/\s*\(.*\)\s*$/, "")
    .trim();
}

type Section = { heading: string | null; lines: string[] };

/** Splits at headings of `level` (e.g. "## "), never inside a code block. */
function split(lines: string[], marker: string): Section[] {
  const sections: Section[] = [{ heading: null, lines: [] }];
  let fenced = false;
  for (const line of lines) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    if (!fenced && line.startsWith(marker)) {
      sections.push({ heading: line, lines: [] });
    } else {
      sections[sections.length - 1].lines.push(line);
    }
  }
  return sections;
}

function groupOf(slug: string): string {
  return GROUPS.find((g) => g.slugs.includes(slug))?.name ?? "More";
}

export function buildPages(guide: string): DocPage[] {
  const lines = stripComments(guide).replace(/\r\n/g, "\n").split("\n");
  const [intro, ...sections] = split(lines, "## ");
  const pages: DocPage[] = [];
  const introLines = intro.lines.filter((line) => !line.startsWith("# "));
  pages.push({ slug: "", title: "Introduction", group: groupOf(""), markdown: introLines.join("\n").trim() });
  for (const section of sections) {
    const title = sectionTitle(section.heading ?? "");
    const slug = slugify(title);
    if (slug === "records") {
      const [overview, ...subsections] = split(section.lines, "### ");
      const rest: string[] = [...overview.lines];
      const types: DocPage[] = [];
      for (const sub of subsections) {
        const subTitle = sectionTitle(sub.heading ?? "");
        if (RECORD_TYPES.has(subTitle)) {
          const subSlug = `records/${slugify(subTitle)}`;
          types.push({ slug: subSlug, title: subTitle, group: groupOf(subSlug), markdown: sub.lines.join("\n").trim() });
        } else {
          rest.push(sub.heading ?? "", ...sub.lines);
        }
      }
      if (types.length) {
        rest.push("", "### Record types", "", ...types.map((t) => `- [${t.title}](/docs/${t.slug})`));
      }
      pages.push({ slug, title, group: groupOf(slug), markdown: rest.join("\n").trim() }, ...types);
      continue;
    }
    pages.push({ slug, title, group: groupOf(slug), markdown: section.lines.join("\n").trim() });
  }
  return pages;
}

/** The sidebar: groups in order, each with its pages in the guide's order. */
export function navGroups(pages: DocPage[]): { name: string; pages: DocPage[] }[] {
  const order = [...GROUPS.map((g) => g.name), "More"];
  return order
    .map((name) => {
      const inGroup = pages.filter((p) => p.group === name);
      const wanted = GROUPS.find((g) => g.name === name)?.slugs ?? [];
      inGroup.sort((a, b) => {
        const ia = wanted.indexOf(a.slug);
        const ib = wanted.indexOf(b.slug);
        return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
      });
      return { name, pages: inGroup };
    })
    .filter((g) => g.pages.length > 0);
}

/** A page's label in the sidebar ("Lab results" under Records; "Overview" for Records itself). */
export function navLabel(page: DocPage): string {
  if (page.slug === "records") return "Overview";
  if (page.slug === "the-queue") return "Queue";
  if (page.slug === "prescriptions-dispensed") return "Prescriptions";
  return page.title;
}
