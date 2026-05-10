import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { VideosPage } from "../pages/VideosPage";
import type { Task } from "../api/types";

const apiMock = vi.hoisted(() => ({
  retryTaskStep: vi.fn(),
  videos: vi.fn(),
  videoArtifactUrl: vi.fn((taskId: number, artifactId: number) => `/api/videos/${taskId}/artifacts/${artifactId}`)
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

const videosFixture: Task[] = [
  {
    id: 9,
    source_type: "youtube",
    input: "https://youtu.be/video-ready",
    title: "Original video title",
    status: "success",
    current_step: "upload_subtitle",
    progress: 100,
    error_summary: "",
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-01T10:03:00Z",
    steps: [
      {
        id: 19,
        name: "generate_metadata",
        order: 9,
        label: "生成投稿信息",
        status: "success",
        progress: 100,
        started_at: null,
        finished_at: null,
        error_message: "",
        retry_count: 0
      }
    ],
    artifacts: [
      {
        id: 11,
        task_id: 9,
        step_id: 1,
        artifact_type: "preview",
        path: "data/artifacts/9/preview.mp4",
        metadata: {},
        created_at: "2026-05-01T10:02:30Z"
      }
    ],
    metadata: {
      id: 4,
      task_id: 9,
      title: "【中文配音】Ready video",
      description: "投稿简介",
      tags: ["AI"],
      category: "科技",
      copyright_type: 2,
      cover_artifact_id: null,
      visibility: "public",
      bilibili_video_id: "BV123",
      bilibili_aid: "10001",
      bilibili_cid: "20002",
      bilibili_filename: "fake-file.mp4",
      bilibili_cover_url: "",
      upload_status: "uploaded",
      updated_at: "2026-05-01T10:03:00Z"
    }
  }
];

beforeEach(() => {
  apiMock.videos.mockResolvedValue({ items: videosFixture });
  apiMock.retryTaskStep.mockResolvedValue(videosFixture[0]);
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("VideosPage", () => {
  test("renders completed videos with inline preview and detail links", async () => {
    render(<VideosPage />);

    expect(await screen.findByRole("heading", { name: "视频库" })).toBeInTheDocument();
    expect(screen.getByText("【中文配音】Ready video")).toBeInTheDocument();
    expect(screen.getByText("https://youtu.be/video-ready")).toBeInTheDocument();
    expect(screen.getByText("BV123")).toBeInTheDocument();
    expect(screen.getByText("uploaded")).toBeInTheDocument();
    expect(screen.getByLabelText("【中文配音】Ready video 预览")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新生成" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "预览详情" })).toHaveAttribute("href", "#/videos/9");
    expect(screen.getByRole("link", { name: "任务详情" })).toHaveAttribute("href", "#/tasks/9");
  });

  test("regenerates metadata through the task step retry endpoint", async () => {
    render(<VideosPage />);

    fireEvent.click(await screen.findByRole("button", { name: "重新生成" }));

    await waitFor(() => expect(apiMock.retryTaskStep).toHaveBeenCalledWith(9, 19));
    await waitFor(() => expect(apiMock.videos).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/投稿信息已重新生成/)).toBeInTheDocument();
  });

  test("renders empty state when no videos are ready", async () => {
    apiMock.videos.mockResolvedValueOnce({ items: [] });

    render(<VideosPage />);

    expect(await screen.findByText("暂无可投稿视频。")).toBeInTheDocument();
  });
});
