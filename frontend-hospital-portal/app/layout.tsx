import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dedan Health OS • Hospital Portal",
  description:
    "The Endod hospital portal: Endod bookings and video visits, patients, doctors and hospital settings.",
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
{/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap"
        />
        {/* Material Symbols icon font — loaded in the root layout so it
            applies to every route (the no-page-custom-font rule targets the
            pages router; app/router root layouts are global). */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
        />
      </head>
      <body className="min-h-screen bg-app-bg font-sans text-body-text antialiased">
        {children}
      </body>
    </html>
  );
}
