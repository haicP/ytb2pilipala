import { useEffect, useMemo, useState } from "react";
import { AppShell } from "./components/AppShell";
import { AccountsPage } from "./pages/AccountsPage";
import { AssistantPage } from "./pages/AssistantPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SubscribePage } from "./pages/SubscribePage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { TaskListPage } from "./pages/TaskListPage";
import { VideoPreviewPage } from "./pages/VideoPreviewPage";
import { VideosPage } from "./pages/VideosPage";

type Route = {
  path: string;
  taskId?: number;
  videoId?: number;
};

function parseHashRoute(hash: string): Route {
  const normalized = hash.replace(/^#/, "") || "/dashboard";
  const [pathPart] = normalized.split("?");
  const path = pathPart.startsWith("/") ? pathPart : `/${pathPart}`;

  const taskMatch = path.match(/^\/tasks\/(\d+)$/);
  if (taskMatch) {
    return { path: "/tasks/:id", taskId: Number(taskMatch[1]) };
  }
  const videoMatch = path.match(/^\/videos\/(\d+)$/);
  if (videoMatch) {
    return { path: "/videos/:id", videoId: Number(videoMatch[1]) };
  }
  return { path };
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHashRoute(window.location.hash));

  useEffect(() => {
    const onHashChange = () => {
      setRoute(parseHashRoute(window.location.hash));
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const content = useMemo(() => {
    if (route.path === "/tasks/:id") {
      return <TaskDetailPage taskId={route.taskId} />;
    }
    if (route.path === "/tasks") {
      return <TaskListPage />;
    }
    if (route.path === "/videos") {
      return <VideosPage />;
    }
    if (route.path === "/videos/:id") {
      return <VideoPreviewPage taskId={route.videoId} />;
    }
    if (route.path === "/settings") {
      return <SettingsPage />;
    }
    if (route.path === "/assistant") {
      return <AssistantPage />;
    }
    if (route.path === "/subscribe") {
      return <SubscribePage />;
    }
    if (route.path === "/accounts") {
      return <AccountsPage />;
    }
    return <DashboardPage />;
  }, [route.path, route.taskId, route.videoId]);

  return (
    <AppShell
      currentPath={route.path === "/tasks/:id" ? "/tasks" : route.path === "/videos/:id" ? "/videos" : route.path}
    >
      {content}
    </AppShell>
  );
}
