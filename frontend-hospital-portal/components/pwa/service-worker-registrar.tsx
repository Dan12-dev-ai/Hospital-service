"use client";

import { useEffect } from "react";

/**
 * Registers the hospital portal service worker so the app can be installed
 * as a PWA. Registration is best-effort: failures (unsupported browsers,
 * insecure contexts) are ignored.
 */
export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;
    // Only register in production-like contexts; dev's HMR is happier without it.
    const register = () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
        // Ignore registration errors.
      });
    };
    if (document.readyState === "complete") {
      register();
    } else {
      window.addEventListener("load", register, { once: true });
    }
  }, []);
  return null;
}
