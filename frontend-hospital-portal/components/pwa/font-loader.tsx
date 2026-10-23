"use client";

import { useEffect } from "react";

const FONT_HREFS = [
  "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap",
  "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap",
];

/**
 * Loads the external icon/text fonts after hydration so they never block the
 * initial page load (and the PWA/service-worker installability checks).
 */
export function FontLoader() {
  useEffect(() => {
    for (const href of FONT_HREFS) {
      if (document.querySelector(`link[href="${href}"]`)) continue;
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      document.head.appendChild(link);
    }
  }, []);
  return null;
}