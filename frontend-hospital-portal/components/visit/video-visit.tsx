"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Icon } from "@/components/ui/icon";
import { ErrorState, LoadingState, RoleGate } from "@/components/common/states";
import { useSignedIn } from "@/components/session/session-context";
import { ApiError, apiFetch, useApi } from "@/lib/api";
import type { Booking, VideoJoin } from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";

/** The Jitsi IFrame API, as loaded from https://{domain}/external_api.js. */
type JitsiApi = { dispose: () => void; addListener?: (event: string, handler: () => void) => void };
type JitsiConstructor = new (
  domain: string,
  options: { roomName: string; jwt: string; parentNode: HTMLElement; width?: string | number; height?: string | number }
) => JitsiApi;

declare global {
  interface Window {
    JitsiMeetExternalAPI?: JitsiConstructor;
  }
}

/**
 * A bare host name (no scheme, port, path or user info), checked before it is
 * put into a script URL: the domain comes from the backend, and a script tag
 * runs whatever it points at.
 */
const HOSTNAME = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

export function isValidJitsiDomain(domain: string): boolean {
  return HOSTNAME.test(domain);
}

/** Loads external_api.js once per domain. */
function loadJitsiScript(domain: string): Promise<JitsiConstructor> {
  const src = `https://${domain}/external_api.js`;
  return new Promise((resolve, reject) => {
    if (window.JitsiMeetExternalAPI) {
      resolve(window.JitsiMeetExternalAPI);
      return;
    }
    const existing = document.querySelector<HTMLScriptElement>(`script[data-jitsi-src="${src}"]`);
    const script = existing ?? document.createElement("script");
    const done = () => {
      if (window.JitsiMeetExternalAPI) resolve(window.JitsiMeetExternalAPI);
      else reject(new Error("The video service did not load."));
    };
    script.addEventListener("load", done, { once: true });
    script.addEventListener(
      "error",
      () => {
        // Removed, so "Try again" loads it afresh instead of waiting on a dead tag.
        script.remove();
        reject(new Error("The video service could not be reached."));
      },
      { once: true }
    );
    if (!existing) {
      script.src = src;
      script.async = true;
      script.dataset.jitsiSrc = src;
      document.head.appendChild(script);
    }
  });
}

export function VideoVisit() {
  return (
    <RoleGate roles={["doctor"]} what="video visits (only the visit's doctor joins)">
      <VideoVisitLoaded />
    </RoleGate>
  );
}

function VideoVisitLoaded() {
  const params = useParams<{ id: string }>();
  const id = typeof params.id === "string" ? params.id : "";
  const signedIn = useSignedIn();
  const booking = useApi<Booking>(id ? `bookings/${encodeURIComponent(id)}` : null);
  const container = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ status: "joining" | "joined" } | { status: "error"; message: string }>({
    status: "joining",
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!id) return;
    let api: JitsiApi | null = null;
    let cancelled = false;
    (async () => {
      try {
        const join = await apiFetch<VideoJoin>(`bookings/${encodeURIComponent(id)}/video`, { method: "POST" });
        if (!isValidJitsiDomain(join.domain)) throw new Error("The video service address is not valid.");
        const JitsiMeetExternalAPI = await loadJitsiScript(join.domain);
        if (cancelled || !container.current) return;
        container.current.replaceChildren();
        api = new JitsiMeetExternalAPI(join.domain, {
          roomName: join.room,
          jwt: join.jwt,
          parentNode: container.current,
          width: "100%",
          height: "100%",
        });
        setState({ status: "joined" });
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof ApiError || error instanceof Error ? error.message : "Could not join the visit.",
          });
        }
      }
    })();
    return () => {
      cancelled = true;
      api?.dispose();
    };
  }, [id, attempt]);

  const timeZone = signedIn?.hospital.timezone;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-outline">Video visit • you are the moderator</p>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">
            {booking.data ? booking.data.patient.name : "Video visit"}
          </h1>
          {booking.data && (
            <p className="text-xs text-slate-500">
              {booking.data.patient.dedan_id} • {formatDateTime(booking.data.scheduled_at, timeZone)} •{" "}
              {booking.data.duration_minutes} min
              {booking.data.notes ? ` • ${booking.data.notes}` : ""}
            </p>
          )}
        </div>
        <Link
          href="/appointments"
          className="inline-flex items-center gap-1.5 rounded-xl bg-surface-container px-4 py-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container-high"
        >
          <Icon name="arrow_back" className="text-[16px]" />
          Back to appointments
        </Link>
      </div>

      {state.status === "error" ? (
        <ErrorState
          message={state.message}
          onRetry={() => {
            setState({ status: "joining" });
            setAttempt((value) => value + 1);
          }}
        />
      ) : (
        <>
          {state.status === "joining" && <LoadingState label="Joining the video room…" />}
          <div
            ref={container}
            data-testid="jitsi-container"
            className={state.status === "joined" ? "h-[70vh] min-h-[420px] overflow-hidden rounded-3xl bg-slate-900 shadow-soft" : "hidden"}
          />
        </>
      )}
    </div>
  );
}
