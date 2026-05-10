import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { TaskDetailPage } from "../pages/TaskDetailPage";
import type { LogItem, Task } from "../api/types";

const apiMock = vi.hoisted(() => ({
  cancelTask: vi.fn(),
  logs: vi.fn(),
  retryTask: vi.fn(),
  retryTaskStep: vi.fn(),
  task: vi.fn(),
  updateMetadata: vi.fn()
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

const taskFixture: Task = {
  id: 7,
  source_type: "youtube",
  input: "https://youtu.be/demo",
  title: "Demo video",
  status: "running",
  current_step: "translate",
  progress: 64,
  error_summary: "",
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:03:00Z",
  steps: [
    {
      id: 1,
      name: "download_video",
      order: 2,
      label: "下载视频",
      status: "success",
      progress: 100,
      started_at: "2026-05-01T10:00:00Z",
      finished_at: "2026-05-01T10:01:00Z",
      error_message: "",
      retry_count: 0
    },
    {
      id: 2,
      name: "translate",
      order: 6,
      label: "翻译字幕",
      status: "running",
      progress: 40,
      started_at: "2026-05-01T10:02:00Z",
      finished_at: null,
      error_message: "",
      retry_count: 1
    },
    {
      id: 10,
      name: "upload_video",
      order: 10,
      label: "上传视频",
      status: "pending",
      progress: 0,
      started_at: null,
      finished_at: null,
      error_message: "",
      retry_count: 0
    }
  ],
  artifacts: [
    {
      id: 11,
      task_id: 7,
      step_id: 1,
      artifact_type: "video",
      path: "artifacts/7/video.mp4",
      metadata: { mode: "dry-run" },
      created_at: "2026-05-01T10:01:00Z"
    }
  ],
  metadata: {
    id: 4,
    task_id: 7,
    title: "【中文配音】Demo video",
    description: "old description",
    tags: ["YouTube", "AI翻译"],
    category: "科技",
    copyright_type: 2,
    cover_artifact_id: null,
    visibility: "public",
    bilibili_video_id: "",
    bilibili_aid: "",
    bilibili_cid: "",
    bilibili_filename: "",
    bilibili_cover_url: "",
    upload_status: "pending",
    updated_at: "2026-05-01T10:03:00Z"
  }
};

const logsFixture: LogItem[] = [
  {
    id: 21,
    task_id: 7,
    step_id: 1,
    level: "info",
    message: "dry-run step download_video completed",
    context: { mode: "dry-run" },
    created_at: "2026-05-01T10:01:00Z"
  }
];

beforeEach(() => {
  apiMock.task.mockResolvedValue(taskFixture);
  apiMock.logs.mockResolvedValue({ items: logsFixture, total: 1, limit: 100, offset: 0 });
  apiMock.updateMetadata.mockResolvedValue(taskFixture.metadata);
  apiMock.retryTask.mockResolvedValue(taskFixture);
  apiMock.retryTaskStep.mockResolvedValue(taskFixture);
  apiMock.cancelTask.mockResolvedValue(taskFixture);
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("TaskDetailPage", () => {
  test("renders automatic timeline, artifacts, logs, and top preview link", async () => {
    render(<TaskDetailPage taskId={7} />);

    expect(screen.getByText("加载中")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "任务详情" })).toBeInTheDocument();
    expect(screen.getByText("Demo video")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "2. 下载视频")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "6. 翻译字幕")).toBeInTheDocument();
    expect(screen.queryByText((_, element) => element?.textContent === "10. 上传视频")).not.toBeInTheDocument();
    expect(screen.getByText("artifacts/7/video.mp4")).toBeInTheDocument();
    expect(screen.getByText("dry-run step download_video completed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开预览详情" })).toHaveAttribute("href", "#/videos/7");
    expect(screen.queryByRole("heading", { name: "预览与手动上传" })).not.toBeInTheDocument();
    expect(screen.queryByText(/投稿信息编辑、视频上传和字幕上传已移动到预览详情页/)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("【中文配音】Demo video")).not.toBeInTheDocument();
  });

  test("does not render metadata editor on task detail page", async () => {
    render(<TaskDetailPage taskId={7} />);

    expect(await screen.findByRole("heading", { name: "任务详情" })).toBeInTheDocument();
    expect(screen.queryByLabelText("标题")).not.toBeInTheDocument();
    expect(apiMock.updateMetadata).not.toHaveBeenCalled();
  });

  test("shows retry action for failed task and triggers retry", async () => {
    apiMock.task.mockResolvedValueOnce({
      ...taskFixture,
      status: "failed",
      current_step: "download_video",
      error_summary: "下载视频失败",
      steps: taskFixture.steps.map((step) =>
        step.name === "download_video"
          ? { ...step, status: "failed", error_message: "下载视频失败" }
          : step
      )
    });

    render(<TaskDetailPage taskId={7} />);

    const retryButton = await screen.findByRole("button", { name: "重试任务" });
    fireEvent.click(retryButton);

    await waitFor(() => expect(apiMock.retryTask).toHaveBeenCalledWith(7));
  });

  test("shows step retry action and triggers retry for failed step", async () => {
    apiMock.task.mockResolvedValueOnce({
      ...taskFixture,
      status: "failed",
      current_step: "translate",
      error_summary: "翻译失败",
      steps: taskFixture.steps.map((step) =>
        step.name === "translate"
          ? { ...step, status: "failed", error_message: "翻译失败" }
          : step
      )
    });

    render(<TaskDetailPage taskId={7} />);

    const stepRetryButton = await screen.findByRole("button", { name: "重试步骤 翻译字幕" });
    fireEvent.click(stepRetryButton);

    await waitFor(() => expect(apiMock.retryTaskStep).toHaveBeenCalledWith(7, 2));
  });
});
