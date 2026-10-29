import { AgendaItem } from "@/components/dashboard/agenda-item";
import { agendaEvents } from "@/lib/agenda-data";

export function AgendaTimeline() {
  return (
    <div className="relative flex flex-col gap-3 pl-4">
      {/* Continuous left timeline line */}
      <div className="absolute bottom-3 left-1.5 top-3 w-0.5 bg-neutral-200" />
      {agendaEvents.map((event) => (
        <AgendaItem key={event.id} event={event} />
      ))}
    </div>
  );
}
