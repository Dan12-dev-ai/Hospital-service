import { cn } from "cn";

/**
 * Material Symbols Outlined icon.
 *
 * The icon font is loaded once in `app/layout.tsx`; this component is the
 * single place that renders a ligature span so usage stays consistent
 * (and swappable for lucide-react later if desired).
 */
export function Icon({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn("material-symbols-outlined select-none", className)}
    >
      {name}
    </span>
  );
}
