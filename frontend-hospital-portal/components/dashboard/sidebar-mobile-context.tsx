"use client";

import { createContext, useContext, useState } from "react";

interface SidebarMobileContextValue {
  mobileOpen: boolean;
  setMobileOpen: (value: boolean) => void;
}

const SidebarMobileContext = createContext<SidebarMobileContextValue | null>(
  null
);

export function SidebarMobileProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <SidebarMobileContext.Provider value={{ mobileOpen, setMobileOpen }}>
      {children}
    </SidebarMobileContext.Provider>
  );
}

export function useSidebarMobile() {
  const value = useContext(SidebarMobileContext);
  if (!value) {
    throw new Error("useSidebarMobile must be used within SidebarMobileProvider");
  }
  return value;
}
