import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import App from "./App";
import { AppShell } from "./components/AppShell";

const apiMock = vi.hoisted(() => ({
  accounts: vi.fn(),
  assistantSettings: vi.fn(),
  createBilibiliQrCode: vi.fn(),
  metrics: vi.fn(),
  pollBilibiliQrCode: vi.fn(),
  settings: vi.fn(),
  subscriptionChannels: vi.fn(),
  subscriptionVideos: vi.fn(),
  updateSettings: vi.fn(),
  unbindAccount: vi.fn(),
  task: vi.fn(),
  tasks: vi.fn(),
  videoArtifactText: vi.fn(),
  videoArtifactUrl: vi.fn((taskId: number, artifactId: number) => `/api/videos/${taskId}/artifacts/${artifactId}`)
}));

vi.mock("./api/client", () => ({
  apiClient: apiMock
}));

beforeEach(() => {
  apiMock.assistantSettings.mockResolvedValue({
    base_url: "https://api.example.com/v1",
    api_key: "sk-test-key",
    model_id: "gpt-custom-1",
    postprocess_prompt: "清理转写文本。",
    translation_prompt: "翻译为中文。",
    metadata_prompt: "生成投稿信息。",
    defaults: {
      postprocess_prompt: "默认转写后处理提示词",
      translation_prompt: "默认字幕翻译提示词",
      metadata_prompt: "默认投稿信息提示词"
    },
    updated_at: null
  });
  apiMock.settings.mockResolvedValue({
    dependencies: {},
    config: {
      api2key_base_url: true,
      llm_key: true
    },
    settings: {}
  });
  apiMock.subscriptionChannels.mockResolvedValue({ items: [] });
  apiMock.subscriptionVideos.mockResolvedValue({ items: [] });
  apiMock.accounts.mockResolvedValue({ items: [] });
  apiMock.task.mockResolvedValue({
    id: 9,
    source_type: "youtube",
    input: "https://youtu.be/demo",
    title: "Demo video",
    status: "success",
    current_step: "upload_subtitle",
    progress: 100,
    error_summary: "",
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-01T10:03:00Z",
    steps: [],
    artifacts: [],
    metadata: null
  });
  apiMock.videoArtifactText.mockResolvedValue("");
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("App shell routing", () => {
  test("renders the AI configuration page for the assistant route", async () => {
    window.location.hash = "#/assistant";

    render(<App />);

    expect(await screen.findByRole("heading", { name: "AI 配置" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "工作台总览" })).not.toBeInTheDocument();
  });

  test("renders the video preview page for the video detail route", async () => {
    window.location.hash = "#/videos/9";

    render(<App />);

    expect(await screen.findByRole("heading", { name: "视频预览详情" })).toBeInTheDocument();
  });

  test("keeps sidebar navigation accessible when labels are visually hidden", () => {
    render(
      <AppShell currentPath="/dashboard">
        <main />
      </AppShell>
    );

    expect(screen.getByRole("link", { name: "AI 配置" })).toHaveAttribute("href", "#/assistant");
    expect(screen.getByRole("link", { name: "订阅" })).toHaveAttribute("href", "#/subscribe");
    expect(screen.getByRole("link", { name: "任务队列" })).toHaveAttribute("href", "#/tasks");
    expect(screen.getByRole("link", { name: "账号管理" })).toHaveAttribute("href", "#/accounts");
  });

  test("manually collapses and expands the sidebar", () => {
    const { container } = render(
      <AppShell currentPath="/dashboard">
        <main />
      </AppShell>
    );

    fireEvent.click(screen.getByRole("button", { name: "折叠侧边栏" }));
    expect(container.querySelector(".app-shell")).toHaveClass("sidebar-collapsed");
    expect(screen.queryByRole("button", { name: "展开侧边栏" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "展开侧边栏" }));
    expect(container.querySelector(".app-shell")).not.toHaveClass("sidebar-collapsed");
    expect(screen.getByRole("button", { name: "折叠侧边栏" })).toBeInTheDocument();
  });

  test("renders the subscription page for the subscribe route", async () => {
    window.location.hash = "#/subscribe";

    render(<App />);

    expect(await screen.findByRole("heading", { name: "YouTube 订阅" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "订阅" })).toHaveClass("active");
  });

  test("renders the account management page for the accounts route", async () => {
    window.location.hash = "#/accounts";

    render(<App />);

    expect(await screen.findByRole("heading", { name: "账号绑定管理" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "账号管理" })).toHaveClass("active");
  });
});
