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
    // Production builds only: in `next dev` the chunk URLs are not content
    // hashed, so the cache-first worker would serve stale code.
    if (process.env.NODE_ENV !== "production") return;
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
