"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Icon } from "@/components/ui/icon";

type ToastState = { id: number; message: string; visible: boolean } | null;

type DashboardContextValue = {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  /** MRN of the appointment row that should be scrolled to + highlighted */
  highlightedMrn: string | null;
  highlightAppointment: (mrn: string) => void;
  showToast: (message: string) => void;
};

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function useDashboard() {
  const ctx = useContext(DashboardContext);
  if (!ctx) {
    throw new Error(
      "useDashboard must be used within a <DashboardProvider>"
    );
  }
  return ctx;
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [searchQuery, setSearchQuery] = useState("");
  const [highlightedMrn, setHighlightedMrn] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState>(null);
  const toastTimers = useRef<{ fade?: ReturnType<typeof setTimeout>; clear?: ReturnType<typeof setTimeout> }>({});

  const showToast = useCallback((message: string) => {
    clearTimeout(toastTimers.current.fade);
    clearTimeout(toastTimers.current.clear);
    setToast({ id: Date.now(), message, visible: true });
    toastTimers.current.fade = setTimeout(() => {
      setToast((prev) => (prev ? { ...prev, visible: false } : prev));
    }, 2700);
    toastTimers.current.clear = setTimeout(() => setToast(null), 3000);
  }, []);

  const highlightAppointment = useCallback((mrn: string) => {
    setHighlightedMrn(mrn);
    // Clear the highlight after the flash period (matches template's 2.5s)
    setTimeout(() => setHighlightedMrn((current) => (current === mrn ? null : current)), 2500);
  }, []);

  useEffect(() => {
    const timers = toastTimers.current;
    return () => {
      clearTimeout(timers.fade);
      clearTimeout(timers.clear);
    };
  }, []);

  return (
    <DashboardContext.Provider
      value={{
        searchQuery,
        setSearchQuery,
        highlightedMrn,
        highlightAppointment,
        showToast,
      }}
    >
      {children}
      {/* Global toast (migrated from template's showToast()) */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-end p-6"
      >
        {toast && (
          <div
            key={toast.id}
            className={`flex items-center gap-2.5 rounded-2xl bg-pine-green px-4 py-3 text-xs font-semibold text-white shadow-xl transition-all duration-300 ${
              toast.visible
                ? "translate-y-0 opacity-100"
                : "translate-y-2 opacity-0"
            }`}
          >
            <Icon name="verified" className="text-[18px] text-emerald-300" />
            <span>{toast.message}</span>
          </div>
        )}
      </div>
    </DashboardContext.Provider>
  );
}
