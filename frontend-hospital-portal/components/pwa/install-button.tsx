"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { Icon } from "@/components/ui/icon";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

const STANDALONE = "(display-mode: standalone)";

function subscribeStandalone(onChange: () => void) {
  const query = window.matchMedia(STANDALONE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/**
 * Shows an "Install app" button. When the browser offers a native install
 * prompt it is used; otherwise the button stays visible and offers manual
 * install guidance (important for dev/localhost where the prompt may not fire).
 */
export function InstallPwaButton() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  // Already running as the installed app (false while rendering on the server).
  const standalone = useSyncExternalStore(
    subscribeStandalone,
    () => window.matchMedia(STANDALONE).matches,
    () => false
  );

  useEffect(() => {
    function onBeforeInstallPrompt(event: Event) {
      event.preventDefault();
      setDeferred(event as BeforeInstallPromptEvent);
    }

    function onAppInstalled() {
      setDeferred(null);
      setInstalled(true);
    }

    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    window.addEventListener("appinstalled", onAppInstalled);

    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
      window.removeEventListener("appinstalled", onAppInstalled);
    };
  }, []);

  if (installed || standalone) return null;

  const handleClick = async () => {
    if (deferred) {
      try {
        await deferred.prompt();
        const choice = await deferred.userChoice;
        if (choice.outcome === "accepted") setInstalled(true);
      } catch {
        // ignore
      } finally {
        setDeferred(null);
      }
      return;
    }
    setShowHelp((v) => !v);
  };

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={handleClick}
        className="inline-flex items-center gap-2 rounded-full bg-primary-container px-4 py-2 text-sm font-bold text-white shadow-md shadow-pine-green/30 transition-all hover:bg-pine-dark hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-pine-light"
        title="Install the hospital portal"
        aria-label="Install app"
      >
        <Icon name="install_mobile" className="text-[20px]" />
        Install app
      </button>
      {showHelp && !deferred ? (
        <div className="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-600 shadow-lg">
          Install isn&apos;t available automatically here. Use your browser menu
          and choose &quot;Install app&quot; / &quot;Add to Home Screen&quot;.
        </div>
      ) : null}
    </div>
  );
}