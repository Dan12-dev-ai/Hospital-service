"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/icon";
import { secondaryButtonClass } from "@/components/common/states";

/** The browser's BarcodeDetector (Chrome, Edge, Android), when present. */
type DetectedBarcode = { rawValue: string };
type BarcodeDetectorInstance = { detect: (source: CanvasImageSource) => Promise<DetectedBarcode[]> };
type BarcodeDetectorClass = new (options: { formats: string[] }) => BarcodeDetectorInstance;

declare global {
  interface Window {
    BarcodeDetector?: BarcodeDetectorClass;
  }
}

type Decoder = (video: HTMLVideoElement, canvas: HTMLCanvasElement) => Promise<string | null>;

/** BarcodeDetector when the browser has it, else jsQR on a canvas frame. */
async function makeDecoder(): Promise<Decoder> {
  if (window.BarcodeDetector) {
    try {
      const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
      return async (video) => {
        const codes = await detector.detect(video);
        return codes[0]?.rawValue ?? null;
      };
    } catch {
      // Present but without QR support: fall back to jsQR.
    }
  }
  const { default: jsQR } = await import("jsqr");
  return async (video, canvas) => {
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (!width || !height) return null;
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(video, 0, 0, width, height);
    const image = context.getImageData(0, 0, width, height);
    return jsQR(image.data, width, height, { inversionAttempts: "dontInvert" })?.data ?? null;
  };
}

/**
 * Reads a QR code with the device camera (the back camera on a phone or
 * tablet) and reports the first one found.
 *
 * The camera is never left on unseen: it stops as soon as a code is read
 * (the parent then sends it, and closes or reopens the scanner), when
 * anything fails (the error is shown), when the page is hidden, and when
 * this closes.
 */
export function QrScanner({ onResult, onClose }: { onResult: (text: string) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [read, setRead] = useState(false);
  const report = useRef(onResult);
  const close = useRef(onClose);

  useEffect(() => {
    report.current = onResult;
    close.current = onClose;
  }, [onResult, onClose]);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    function stopCamera() {
      stopped = true;
      if (timer) clearTimeout(timer);
      timer = null;
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      if (videoRef.current) videoRef.current.srcObject = null;
    }

    function fail(message: string) {
      stopCamera();
      setReady(false);
      setError(message);
    }

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        fail("This browser cannot use the camera here (it needs HTTPS). Type the Endod ID and phone instead.");
        return;
      }
      let opened: MediaStream;
      try {
        opened = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      } catch {
        fail("The camera could not be opened. Allow camera access, or type the Endod ID and phone instead.");
        return;
      }
      if (stopped || !videoRef.current) {
        // Closed while the camera was opening: the cleanup ran before the stream existed.
        opened.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = opened;
      videoRef.current.srcObject = stream;
      await videoRef.current.play().catch(() => undefined);
      let decode: Decoder;
      try {
        decode = await makeDecoder();
      } catch {
        fail("The QR reader could not be started. Type the card's link or the Endod ID and phone instead.");
        return;
      }
      if (stopped) return;
      setReady(true);
      const tick = async () => {
        if (stopped || !videoRef.current || !canvasRef.current) return;
        try {
          const text = await decode(videoRef.current, canvasRef.current);
          if (text && !stopped) {
            // Read: the camera goes off now, whatever happens to the code next.
            stopCamera();
            setRead(true);
            report.current(text);
            return;
          }
        } catch {
          // A frame that could not be read: try the next one.
        }
        if (!stopped) timer = setTimeout(tick, 200);
      };
      void tick();
    }

    function onVisibility() {
      if (document.visibilityState === "hidden" && !stopped) {
        stopCamera();
        close.current();
      }
    }

    document.addEventListener("visibilitychange", onVisibility);
    void start();
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stopCamera();
    };
  }, []);

  return (
    <div className="flex flex-col gap-3" data-testid="qr-scanner">
      <div className="relative overflow-hidden rounded-2xl bg-slate-900">
        <video ref={videoRef} muted playsInline className="aspect-video w-full object-cover" />
        <canvas ref={canvasRef} className="hidden" />
        {!ready && !error && !read && (
          <p className="absolute inset-0 flex items-center justify-center text-xs text-white/80">Opening the camera…</p>
        )}
        {read && !error && (
          <p className="absolute inset-0 flex items-center justify-center text-xs text-white/80">Card read. Checking it…</p>
        )}
        {ready && !read && !error && (
          <div className="pointer-events-none absolute inset-8 rounded-2xl border-2 border-dashed border-white/70" />
        )}
      </div>
      {error ? (
        <p role="alert" className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {error}
        </p>
      ) : (
        <p className="text-xs text-slate-500">Hold the health card&apos;s QR code inside the frame.</p>
      )}
      <button type="button" onClick={onClose} className={secondaryButtonClass}>
        <Icon name="close" className="text-[16px]" />
        {read || error ? "Close" : "Stop the camera"}
      </button>
    </div>
  );
}
