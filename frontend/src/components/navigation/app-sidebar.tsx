import { Link, NavLink, useLocation, useNavigate } from "react-router-dom"
import {
  ArrowLeft01Icon,
  BookOpen02Icon,
  BotIcon,
  Folder01Icon,
  Key01Icon,
  Logout01Icon,
  MessageNotification01Icon,
  PlugIcon,
  Search01Icon,
  Settings01Icon,
} from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { useLogout, useSession } from "@/hooks/use-session"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

const navigationItems = [
  { label: "Projects", to: "/projects", icon: Folder01Icon },
  { label: "Agents", to: "/agents", icon: BotIcon },
  { label: "Notifications", to: "/notifications", icon: MessageNotification01Icon },
  { label: "Settings", to: "/settings", icon: Settings01Icon },
] as const

// Shown instead of the main navigation while the user is in Settings: the
// same sidebar changes view rather than gaining a second sidebar.
const settingsItems = [
  { label: "API keys", to: "/settings/api-keys", icon: Key01Icon },
  { label: "Integrations", to: "/settings/integrations", icon: PlugIcon },
] as const

function getInitials(name: string, email: string) {
  const initials = name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")

  return (initials || email[0] || "T").toUpperCase()
}

function AccountMenu() {
  const navigate = useNavigate()
  const session = useSession()
  const logout = useLogout()
  const email = session.data?.email?.trim() || "Signed-in account"
  const name = session.data?.display_name?.trim() || email
  const initials = getInitials(name, email)

  return (
    <Popover>
      <PopoverTrigger
        type="button"
        aria-label={`Open account menu for ${name}`}
        className="flex w-full items-center gap-3 rounded-sm px-2 py-2 text-left transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-medium text-sidebar-foreground">
          {initials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-sidebar-foreground">
            {name}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {email}
          </span>
        </span>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-64 p-1">
        <div className="border-b border-border px-3 py-2.5">
          <p className="truncate text-sm font-medium">{name}</p>
          <p className="truncate text-xs text-muted-foreground">{email}</p>
        </div>
        <nav aria-label="Account" className="pt-1">
          <Link
            to="/settings"
            className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <HugeiconsIcon icon={Settings01Icon} size={16} strokeWidth={2} />
            Settings
          </Link>
          <Link
            to="/learn-more"
            className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <HugeiconsIcon icon={BookOpen02Icon} size={16} strokeWidth={2} />
            Learn More
          </Link>
          <button
            type="button"
            disabled={logout.isPending}
            onClick={() =>
              logout.mutate(undefined, {
                onSuccess: () => navigate("/sign-in", { replace: true }),
              })
            }
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
          >
            <HugeiconsIcon icon={Logout01Icon} size={16} strokeWidth={2} />
            {logout.isPending ? "Logging out…" : "Log Out"}
          </button>
        </nav>
      </PopoverContent>
    </Popover>
  )
}

export function AppSidebar() {
  const location = useLocation()
  const isSettings =
    location.pathname === "/settings" ||
    location.pathname.startsWith("/settings/")
  const items = isSettings ? settingsItems : navigationItems

  return (
    <Sidebar collapsible="offcanvas" className="border-sidebar-border">
      <SidebarHeader className="px-3 py-4">
        {isSettings ? (
          <Link
            to="/projects"
            className="flex items-center gap-2 rounded-sm px-2 py-2 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
          >
            <HugeiconsIcon icon={ArrowLeft01Icon} size={17} strokeWidth={2} />
            <span>Back to app</span>
          </Link>
        ) : (
          <div className="flex items-center justify-between">
            <Link
              to="/projects"
              className="font-mono text-sm tracking-tight text-sidebar-foreground"
            >
              trace
            </Link>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Search"
              className="text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground"
            >
              <HugeiconsIcon icon={Search01Icon} size={17} strokeWidth={2} />
            </Button>
          </div>
        )}
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup className="px-3 pt-2">
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => {
                const isActive =
                  location.pathname === item.to ||
                  location.pathname.startsWith(`${item.to}/`)

                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      render={<NavLink to={item.to} />}
                      isActive={isActive}
                      tooltip={item.label}
                      className="h-9 rounded-sm px-3 py-2"
                    >
                      <HugeiconsIcon
                        icon={item.icon}
                        size={17}
                        strokeWidth={2}
                      />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="px-3 pb-4">
        <AccountMenu />
      </SidebarFooter>
    </Sidebar>
  )
}
