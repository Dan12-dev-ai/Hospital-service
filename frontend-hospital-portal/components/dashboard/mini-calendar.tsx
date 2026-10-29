"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";


const WEEKDAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

// Gregorian month (0-11) → Ethiopic month name around the Ethiopian new year (Sept 11/12).
const GREGORIAN_TO_ETHIOPIC: Record<number, string> = {
  0: "ጥር",
  1: "የካቲት",
  2: "መጋቢት",
  3: "ሚያዝያ",
  4: "ግንቦት",
  5: "ሰኔ",
  6: "ሐምሌ",
  7: "ነሐሴ",
  8: "ጳጉሜን",
  9: "ጥቅምት",
  10: "ኅዳር",
  11: "ታኅሣሥ",
};

/** Approximate Gregorian year → Ethiopic year (Ethiopian new year falls in September). */
function ethiopicYear(date: Date) {
  const gregorianYear = date.getFullYear();
  return date.getMonth() >= 8 ? gregorianYear - 7 : gregorianYear - 8;
}

export function MiniCalendar() {
  const [monthDate, setMonthDate] = useState(() => new Date(2024, 9, 1)); // October 2024
  const [selectedDay, setSelectedDay] = useState(19);

  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();

  const monthLabel = new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
  }).format(monthDate);

  // Leading days from the previous month (Sept 29-30, 2024)
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrevMonth = new Date(year, month, 0).getDate();

  const cells: { day: number; muted: boolean }[] = [];
  for (let i = firstWeekday - 1; i >= 0; i--) {
    cells.push({ day: daysInPrevMonth - i, muted: true });
  }
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ day, muted: false });
  }
  let nextDay = 1;
  while (cells.length % 7 !== 0 || cells.length < 42) {
    if (cells.length % 7 === 0 && cells.length >= 35) break;
    cells.push({ day: nextDay++, muted: true });
  }

  const shiftMonth = (delta: number) => {
    setMonthDate(new Date(year, month + delta, 1));
    setSelectedDay(1);
  };

  return (
    <div className="flex flex-col rounded-3xl border border-card-border/80 bg-white p-5 shadow-soft">
      <div className="mb-4 flex items-center justify-between">
        <button
          type="button"
          aria-label="Previous month"
          onClick={() => shiftMonth(-1)}
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100"
        >
          <ChevronLeft className="text-[16px]" />
        </button>
        <span className="text-sm font-bold text-slate-800">
          {monthLabel} / {GREGORIAN_TO_ETHIOPIC[month]} {ethiopicYear(monthDate)}
        </span>
        <button
          type="button"
          aria-label="Next month"
          onClick={() => shiftMonth(1)}
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100"
        >
          <ChevronRight className="text-[16px]" />
        </button>
      </div>

      {/* Day names header */}
      <div className="mb-2 grid grid-cols-7 text-center text-[10px] font-bold tracking-wider text-slate-400">
        {WEEKDAYS.map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>

      {/* Calendar date numbers */}
      <div className="grid grid-cols-7 gap-y-2 text-center text-xs font-medium text-slate-600">
        {cells.map((cell, index) =>
          cell.muted ? (
            <span key={`${cell.day}-${index}`} className="text-slate-300">
              {cell.day}
            </span>
          ) : (
            <button
              key={`${cell.day}-${index}`}
              type="button"
              onClick={() => setSelectedDay(cell.day)}
              className="flex items-center justify-center"
            >
              <span
                className={
                  selectedDay === cell.day
                    ? "flex h-7 w-7 items-center justify-center rounded-full bg-black font-bold text-white shadow-sm"
                    : "flex h-7 w-7 items-center justify-center rounded-full transition-colors hover:bg-slate-100"
                }
              >
                {cell.day}
              </span>
            </button>
          )
        )}
      </div>
    </div>
  );
}
