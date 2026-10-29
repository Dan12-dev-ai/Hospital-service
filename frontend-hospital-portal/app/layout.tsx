import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ServiceWorkerRegistrar } from "@/components/pwa/service-worker-registrar";

// Self-hosted at build time by next/font: the browser never asks Google for
// fonts (no third-party request from a portal that shows patient data). The
// icons are lucide SVGs (components/ui/icon.tsx), so no icon font is loaded.
const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Dedan Health OS • Hospital Portal",
  description:
    "The Endod hospital portal: Endod bookings and video visits, patients, doctors and hospital settings.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Hospital Portal",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-screen bg-app-bg font-sans text-body-text antialiased">
        <ServiceWorkerRegistrar />
        {children}
      </body>
    </html>
  );
}
