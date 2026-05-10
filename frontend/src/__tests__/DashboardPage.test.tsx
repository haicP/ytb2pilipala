import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { DashboardPage } from "../pages/DashboardPage";
import type { Task } from "../api/types";

const apiMock = vi.hoisted(() => ({
  createTask: vi.fn(),
  metrics: vi.fn(),
  tasks: vi.fn()
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

beforeEach(() => {
  apiMock.metrics.mockResolvedValue({
      disk_free_gb: 84.2,
      disk_total_gb: 96,
      cpu_percent: 0.2,
      memory_available_gb: 18.4,
      memory_total_gb: 19.6
  });
  apiMock.tasks.mockResolvedValue({ items: [] });
  apiMock.createTask.mockResolvedValue({});
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("DashboardPage", () => {
  test("shows primary workbench sections", async () => {
    render(<DashboardPage />);

    expect(await screen.findByText("系统信息")).toBeInTheDocument();
    expect(screen.getByText("任务概况")).toBeInTheDocument();
    expect(screen.getByText("提交新视频")).toBeInTheDocument();
    expect(screen.getByText("最近处理")).toBeInTheDocument();
  });

  test("submits a YouTube link and refreshes task data", async () => {
    render(<DashboardPage />);

    const input = await screen.findByLabelText("YouTube 链接或本地视频路径");
    fireEvent.change(input, { target: { value: "https://www.youtube.com/watch?v=abc123" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(apiMock.createTask).toHaveBeenCalledWith({
        source_type: "youtube",
        input: "https://www.youtube.com/watch?v=abc123",
        options: {
          download_resolution: "auto",
          playlist: {
            enabled: false,
            start_index: 1,
            max_items: 10
          },
          enabled_steps: {
            download_thumbnail: true,
            transcribe: true,
            translate: true,
            synthesize_voice: true
          }
        }
      });
    });
    await waitFor(() => expect(apiMock.tasks).toHaveBeenCalledTimes(2));
  });

  test("opens task submit settings without navigating to system settings", async () => {
    render(<DashboardPage />);

    const settingsButton = await screen.findByRole("button", { name: "设置" });
    fireEvent.click(settingsButton);

    expect(settingsButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("提交设置")).toBeInTheDocument();
    expect(screen.getByLabelText("下载分辨率")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "设置" })).not.toBeInTheDocument();
  });

  test("submits task-specific settings from the homepage form", async () => {
    render(<DashboardPage />);

    fireEvent.click(await screen.findByRole("button", { name: "设置" }));
    fireEvent.change(screen.getByLabelText("下载分辨率"), { target: { value: "1080p" } });
    fireEvent.click(screen.getByLabelText("启用"));
    fireEvent.change(screen.getByLabelText("最多导入"), { target: { value: "12" } });
    fireEvent.click(screen.getByLabelText("合成字幕配音"));

    const input = screen.getByLabelText("YouTube 链接或本地视频路径");
    fireEvent.change(input, { target: { value: "https://youtu.be/with-options" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(apiMock.createTask).toHaveBeenCalledWith({
        source_type: "youtube",
        input: "https://youtu.be/with-options",
        options: {
          download_resolution: "1080p",
          playlist: {
            enabled: true,
            start_index: 1,
            max_items: 12
          },
          enabled_steps: {
            download_thumbnail: true,
            transcribe: true,
            translate: true,
            synthesize_voice: false
          }
        }
      });
    });
  });

  test("shows a submission error without refreshing tasks", async () => {
    apiMock.createTask.mockRejectedValueOnce(new Error("invalid video source"));

    render(<DashboardPage />);

    const input = await screen.findByLabelText("YouTube 链接或本地视频路径");
    fireEvent.change(input, { target: { value: "/tmp/source.mp4" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(await screen.findByRole("alert")).toHaveTextContent("invalid video source");
    expect(apiMock.createTask).toHaveBeenCalledWith(
      expect.objectContaining({
        source_type: "local",
        input: "/tmp/source.mp4"
      })
    );
    expect(apiMock.tasks).toHaveBeenCalledTimes(1);
  });

  test("shows failed step name in recent processing list", async () => {
    const failedTask: Task = {
      id: 3,
      source_type: "youtube",
      input: "https://youtu.be/failure",
      title: "Failure demo",
      status: "failed",
      current_step: "translate",
      progress: 58,
      error_summary: "翻译失败",
      created_at: "2026-05-01T10:00:00Z",
      updated_at: "2026-05-01T10:05:00Z",
      steps: [
        {
          id: 12,
          name: "translate",
          order: 6,
          label: "翻译字幕",
          status: "failed",
          progress: 58,
          started_at: "2026-05-01T10:03:00Z",
          finished_at: "2026-05-01T10:05:00Z",
          error_message: "LLM timeout",
          retry_count: 1
        }
      ],
      artifacts: [],
      metadata: null
    };
    apiMock.tasks.mockResolvedValueOnce({ items: [failedTask] });

    render(<DashboardPage />);

    expect(await screen.findByText("Failure demo")).toBeInTheDocument();
    expect(screen.getByText("失败步骤：翻译字幕")).toBeInTheDocument();
  });
});
