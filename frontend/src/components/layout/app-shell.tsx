import type { ReactNode } from "react"

import { AppSidebar } from "@/components/navigation/app-sidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 items-center border-b border-border px-4 md:hidden">
          <SidebarTrigger />
          <span className="ml-2 font-mono text-sm tracking-tight">trace</span>
        </header>
        <main className="min-h-svh bg-background">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}
