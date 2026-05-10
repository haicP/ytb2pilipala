import type { ReactNode } from "react";
import { useState } from "react";
import {
  Bot,
  Clapperboard,
  LayoutDashboard,
  Link2,
  ListChecks,
  PanelLeftClose,
  Rss,
  Settings
} from "lucide-react";

interface AppShellProps {
  currentPath: string;
  children: ReactNode;
}

const navItems = [
  { key: "dashboard", label: "总览", href: "#/dashboard", icon: LayoutDashboard },
  { key: "assistant", label: "AI 配置", href: "#/assistant", icon: Bot },
  { key: "subscribe", label: "订阅", href: "#/subscribe", icon: Rss },
  { key: "videos", label: "视频库", href: "#/videos", icon: Clapperboard },
  { key: "tasks", label: "任务队列", href: "#/tasks", icon: ListChecks },
  { key: "accounts", label: "账号管理", href: "#/accounts", icon: Link2 },
  { key: "settings", label: "设置", href: "#/settings", icon: Settings }
] as const;

function isActive(currentPath: string, key: string): boolean {
  if (key === "dashboard") {
    return currentPath === "/" || currentPath === "/dashboard";
  }
  if (key === "tasks") {
    return currentPath === "/tasks" || currentPath.startsWith("/tasks/");
  }
  if (key === "assistant") {
    return currentPath === "/assistant";
  }
  return currentPath === `/${key}`;
}

export function AppShell({ currentPath, children }: AppShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className={`app-shell${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <a
            className="brand"
            href="#/dashboard"
            aria-label={sidebarCollapsed ? "展开侧边栏" : "返回总览"}
            onClick={(event) => {
              if (!sidebarCollapsed) {
                return;
              }
              event.preventDefault();
              setSidebarCollapsed(false);
            }}
          >
            <span className="brand-mark">y2</span>
            <span className="brand-text">ytb2pilipala</span>
          </a>
          {sidebarCollapsed ? null : (
            <button
              className="sidebar-toggle"
              type="button"
              aria-label="折叠侧边栏"
              title="折叠侧边栏"
              aria-pressed="false"
              onClick={() => setSidebarCollapsed(true)}
            >
              <PanelLeftClose size={17} aria-hidden="true" />
            </button>
          )}
        </div>
        <nav className="nav" aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <a
                key={item.key}
                className={`nav-item${isActive(currentPath, item.key) ? " active" : ""}`}
                href={item.href}
                aria-label={item.label}
                data-label={item.label}
              >
                <Icon size={16} aria-hidden="true" />
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>
      </aside>
      <main className="main-panel">{children}</main>
    </div>
  );
}
