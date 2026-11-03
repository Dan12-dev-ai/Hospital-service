"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { CheckCircle2 } from "lucide-react";

type ToastState = { id: number; message: string; visible: boolean } | null;

const ToastContext = createContext<((message: string) => void) | null>(null);

/** Shows a short confirmation at the bottom right ("Webhook saved"). */
export function useToast(): (message: string) => void {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast must be used within <ToastProvider>");
  return show;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState>(null);
  const timers = useRef<{ fade?: ReturnType<typeof setTimeout>; clear?: ReturnType<typeof setTimeout> }>({});

  const show = useCallback((message: string) => {
    clearTimeout(timers.current.fade);
    clearTimeout(timers.current.clear);
    setToast({ id: Date.now(), message, visible: true });
    timers.current.fade = setTimeout(() => setToast((prev) => (prev ? { ...prev, visible: false } : prev)), 2700);
    timers.current.clear = setTimeout(() => setToast(null), 3000);
  }, []);

  useEffect(() => {
    const current = timers.current;
    return () => {
      clearTimeout(current.fade);
      clearTimeout(current.clear);
    };
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-end p-6">
        {toast && (
          <div
            key={toast.id}
            data-testid="toast"
            className={`flex items-center gap-2 rounded-lg bg-neutral-900 px-4 py-2.5 text-xs font-medium text-white shadow-lg transition-all duration-300 ${
              toast.visible ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"
            }`}
          >
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            <span>{toast.message}</span>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}
