import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { TaskListPage } from "../pages/TaskListPage";
import type { Task } from "../api/types";

const apiMock = vi.hoisted(() => ({
  cancelTask: vi.fn(),
  deleteTask: vi.fn(),
  retryTask: vi.fn(),
  tasks: vi.fn()
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

const tasksFixture: Task[] = [
  {
    id: 1,
    source_type: "youtube",
    input: "https://youtu.be/demo",
    title: "YouTube demo",
    status: "failed",
    current_step: "translate",
    progress: 52,
    error_summary: "LLM timeout",
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-01T10:05:00Z",
    steps: [
      {
        id: 1,
        name: "import",
        order: 1,
        label: "导入任务",
        status: "success",
        progress: 100,
        started_at: "2026-05-01T10:00:00Z",
        finished_at: "2026-05-01T10:00:10Z",
        error_message: "",
        retry_count: 0
      },
      {
        id: 2,
        name: "translate",
        order: 2,
        label: "翻译字幕",
        status: "failed",
        progress: 52,
        started_at: "2026-05-01T10:00:10Z",
        finished_at: null,
        error_message: "LLM timeout",
        retry_count: 1
      }
    ],
    artifacts: [],
    metadata: null
  },
  {
    id: 2,
    source_type: "youtube",
    input: "https://youtu.be/running-demo",
    title: "Running demo",
    status: "running",
    current_step: "download_video",
    progress: 20,
    error_summary: "",
    created_at: "2026-05-01T11:00:00Z",
    updated_at: "2026-05-01T11:02:00Z",
    steps: [],
    artifacts: [],
    metadata: null
  }
];

beforeEach(() => {
  apiMock.tasks.mockResolvedValue({ items: tasksFixture });
  apiMock.retryTask.mockResolvedValue(tasksFixture[0]);
  apiMock.cancelTask.mockResolvedValue(tasksFixture[1]);
  apiMock.deleteTask.mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("TaskListPage", () => {
  test("renders task management cards with status tabs, progress, and actions", async () => {
    render(<TaskListPage />);

    expect(await screen.findByRole("heading", { name: "任务管理" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "全部 2" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "处理中 1" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "失败 1" })).toBeInTheDocument();
    expect(screen.getByText("YouTube demo")).toBeInTheDocument();
    expect(screen.getByText("LLM timeout")).toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();
    expect(screen.getByText("视频ID: demo")).toBeInTheDocument();
    expect(screen.getAllByText("失败").length).toBeGreaterThan(0);
    expect(screen.getByRole("progressbar", { name: "进度 52%" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "展开" })[0]).toHaveAttribute("href", "#/tasks/1");
    expect(screen.getAllByRole("link", { name: "编辑投稿" })[0]).toHaveAttribute("href", "#/tasks/1");
    expect(screen.getAllByText("继续/重跑").length).toBeGreaterThan(0);
    expect(screen.getAllByText("取消").length).toBeGreaterThan(0);
    expect(screen.getAllByText("删除").length).toBeGreaterThan(0);
    expect(screen.getByText("自动化调度策略")).toBeInTheDocument();
    expect(screen.getByText("总任务数")).toBeInTheDocument();
  });

  test("filters cards by status and runs task actions", async () => {
    render(<TaskListPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "处理中 1" }));

    expect(screen.getAllByText("Running demo").length).toBeGreaterThan(0);
    expect(screen.queryByText("YouTube demo")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    await waitFor(() => expect(apiMock.cancelTask).toHaveBeenCalledWith(2));
    await waitFor(() => expect(apiMock.tasks).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("tab", { name: "失败 1" }));
    fireEvent.click(screen.getByRole("button", { name: "继续/重跑" }));

    await waitFor(() => expect(apiMock.retryTask).toHaveBeenCalledWith(1));
  });

  test("confirms and deletes a terminal task then refreshes the list", async () => {
    apiMock.tasks
      .mockResolvedValueOnce({ items: tasksFixture })
      .mockResolvedValueOnce({ items: [tasksFixture[1]] });

    render(<TaskListPage />);

    const deleteButtons = await screen.findAllByRole("button", { name: "删除" });
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => expect(apiMock.deleteTask).toHaveBeenCalledWith(1));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("YouTube demo"));
    await waitFor(() => expect(screen.queryByText("YouTube demo")).not.toBeInTheDocument());
  });
});
