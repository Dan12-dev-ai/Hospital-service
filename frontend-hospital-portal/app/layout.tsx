import type { Metadata } from "next";
import "./globals.css";
import { ServiceWorkerRegistrar } from "@/components/pwa/service-worker-registrar";
import { InstallPwaButton } from "@/components/pwa/install-button";
import { FontLoader } from "@/components/pwa/font-loader";

export const metadata: Metadata = {
  title: "Dedan Health OS • Hospital Portal",
  description:
    "The Endod hospital portal: Endod bookings and video visits, patients, doctors and hospital settings.",
  manifest: "/manifest.json",
  themeColor: "#0f172a",
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

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
      </head>
      <body className="min-h-screen bg-app-bg font-sans text-body-text antialiased">
        <FontLoader />
        <ServiceWorkerRegistrar />
        {children}
      </body>
    </html>
  );
}
