"use client";

// Where the facility is: Leaflet with OpenStreetMap tiles (free, no key), as
// in the Endod patient app. The pin can be dragged, or the map clicked, to
// move it; the parent keeps the coordinates.

import { useEffect, useRef, useState } from "react";
import type { Map as LeafletMap, Marker } from "leaflet";
import "leaflet/dist/leaflet.css";

export type Point = { latitude: number; longitude: number };

const ADDIS_ABABA: [number, number] = [9.03, 38.74];
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// The pin is drawn with CSS (no image files to bundle).
const PIN =
  '<span style="display:block;width:26px;height:26px;border-radius:50% 50% 50% 0;background:#1E5852;' +
  'border:3px solid #fff;transform:rotate(-45deg);box-shadow:0 1px 5px rgba(0,0,0,.45)"></span>';

function rounded(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

export function LocationMap({ value, onChange }: { value: Point | null; onChange: (point: Point) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<LeafletMap | null>(null);
  const marker = useRef<Marker | null>(null);
  const [ready, setReady] = useState(false);
  // The newest handler, without re-creating the map when it changes.
  const change = useRef(onChange);
  useEffect(() => {
    change.current = onChange;
  });
  const initial = useRef(value);

  // Leaflet needs the browser: loaded here, once.
  useEffect(() => {
    let cancelled = false;
    let resize: ResizeObserver | null = null;
    void import("leaflet").then((L) => {
      if (cancelled || !box.current || map.current) return;
      const start = initial.current;
      const center: [number, number] = start ? [start.latitude, start.longitude] : ADDIS_ABABA;
      const created = L.map(box.current, { center, zoom: start ? 16 : 12, scrollWheelZoom: false });
      created.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
      L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(created);
      const pin = L.marker(center, {
        draggable: true,
        autoPan: true,
        title: "Your facility (drag to move)",
        alt: "Your facility",
        icon: L.divIcon({ className: "", html: PIN, iconSize: [26, 26], iconAnchor: [13, 26] }),
      }).addTo(created);
      pin.on("dragend", () => {
        const at = pin.getLatLng();
        change.current({ latitude: rounded(at.lat), longitude: rounded(at.lng) });
      });
      created.on("click", (event) => {
        pin.setLatLng(event.latlng);
        change.current({ latitude: rounded(event.latlng.lat), longitude: rounded(event.latlng.lng) });
      });
      map.current = created;
      marker.current = pin;
      // The box can change width without the window resizing (a scrollbar
      // appearing, the card growing): keep the map's idea of its size right.
      resize = new ResizeObserver(() => created.invalidateSize());
      resize.observe(box.current);
      setReady(true);
    });
    return () => {
      cancelled = true;
      resize?.disconnect();
      map.current?.remove();
      map.current = null;
      marker.current = null;
    };
  }, []);

  // A position set from outside (typed, or "use my location") moves the pin.
  const latitude = value?.latitude;
  const longitude = value?.longitude;
  useEffect(() => {
    if (!ready || !map.current || !marker.current || latitude === undefined || longitude === undefined) return;
    const current = marker.current.getLatLng();
    if (rounded(current.lat) === latitude && rounded(current.lng) === longitude) return;
    marker.current.setLatLng([latitude, longitude]);
    map.current.setView([latitude, longitude], Math.max(map.current.getZoom(), 15));
  }, [ready, latitude, longitude]);

  return (
    <div
      ref={box}
      role="region"
      aria-label="Map: drag the pin to your entrance"
      data-testid="location-map"
      data-ready={ready ? "true" : "false"}
      className="relative z-0 h-64 w-full overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 sm:h-72"
    />
  );
}
