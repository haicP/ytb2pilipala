import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { VideoPreviewPage } from "../pages/VideoPreviewPage";
import type { Task } from "../api/types";

const apiMock = vi.hoisted(() => ({
  accounts: vi.fn(),
  generateCover: vi.fn(),
  runBilibiliUpload: vi.fn(),
  retryTaskStep: vi.fn(),
  task: vi.fn(),
  updateMetadata: vi.fn(),
  videoArtifactText: vi.fn(),
  videoArtifactUrl: vi.fn((taskId: number, artifactId: number) => `/api/videos/${taskId}/artifacts/${artifactId}`)
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

const taskFixture: Task = {
  id: 7,
  source_type: "youtube",
  input: "https://youtu.be/demo",
  title: "Demo video",
  status: "success",
  current_step: "upload_subtitle",
  progress: 100,
  error_summary: "",
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:03:00Z",
  steps: [
    {
      id: 9,
      name: "generate_metadata",
      order: 9,
      label: "生成投稿信息",
      status: "success",
      progress: 100,
      started_at: null,
      finished_at: null,
      error_message: "",
      retry_count: 0
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
    },
    {
      id: 11,
      name: "upload_subtitle",
      order: 11,
      label: "上传字幕",
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
      id: 9,
      task_id: 7,
      step_id: 3,
      artifact_type: "thumbnail",
      path: "data/artifacts/7/source.jpg",
      metadata: {},
      created_at: "2026-05-01T10:00:30Z"
    },
    {
      id: 11,
      task_id: 7,
      step_id: 1,
      artifact_type: "video",
      path: "data/artifacts/7/source.mp4",
      metadata: {},
      created_at: "2026-05-01T10:01:00Z"
    },
    {
      id: 12,
      task_id: 7,
      step_id: 8,
      artifact_type: "preview",
      path: "data/artifacts/7/preview.mp4",
      metadata: {},
      created_at: "2026-05-01T10:02:00Z"
    },
    {
      id: 13,
      task_id: 7,
      step_id: 5,
      artifact_type: "subtitle_source",
      path: "data/artifacts/7/source.srt",
      metadata: {},
      created_at: "2026-05-01T10:01:30Z"
    },
    {
      id: 14,
      task_id: 7,
      step_id: 6,
      artifact_type: "subtitle_translated",
      path: "data/artifacts/7/zh.srt",
      metadata: {},
      created_at: "2026-05-01T10:01:45Z"
    }
  ],
  metadata: {
    id: 4,
    task_id: 7,
    title: "【中文配音】Demo video",
    description: "投稿简介",
    tags: ["技术", "配音"],
    category: "科技",
    copyright_type: 2,
    cover_artifact_id: null,
    visibility: "public",
    bilibili_video_id: "BV1demo",
    bilibili_aid: "10001",
    bilibili_cid: "20002",
    bilibili_filename: "fake-file.mp4",
    bilibili_cover_url: "https://i0.hdslb.com/cover.jpg",
    upload_status: "uploaded",
    updated_at: "2026-05-01T10:03:00Z"
  }
};

beforeEach(() => {
  apiMock.accounts.mockResolvedValue({
    items: [
      {
        id: 21,
        platform: "bilibili",
        platform_user_id: "10086",
        nickname: "主账号",
        avatar_url: "",
        status: "active",
        is_primary: true,
        cookie_summary: "已保存关键 Cookie",
        last_login_at: "2026-05-01T09:00:00Z",
        error_summary: "",
        created_at: "2026-05-01T09:00:00Z",
        updated_at: "2026-05-01T09:00:00Z"
      },
      {
        id: 22,
        platform: "bilibili",
        platform_user_id: "10087",
        nickname: "备用账号",
        avatar_url: "",
        status: "active",
        is_primary: false,
        cookie_summary: "已保存关键 Cookie",
        last_login_at: "2026-05-01T09:30:00Z",
        error_summary: "",
        created_at: "2026-05-01T09:30:00Z",
        updated_at: "2026-05-01T09:30:00Z"
      }
    ]
  });
  apiMock.task.mockResolvedValue(taskFixture);
  apiMock.updateMetadata.mockResolvedValue(taskFixture.metadata);
  apiMock.retryTaskStep.mockResolvedValue({
    ...taskFixture,
    metadata: { ...taskFixture.metadata, title: "重新生成标题" }
  });
  apiMock.runBilibiliUpload.mockResolvedValue({
    ...taskFixture,
    metadata: { ...taskFixture.metadata, upload_status: "skipped" },
    steps: taskFixture.steps.map((step) => ({ ...step, status: "skipped", progress: 100 }))
  });
  apiMock.generateCover.mockResolvedValue({
    ...taskFixture,
    metadata: { ...taskFixture.metadata, cover_artifact_id: 15 },
    artifacts: [
      ...taskFixture.artifacts,
      {
        id: 15,
        task_id: 7,
        step_id: null,
        artifact_type: "cover",
        path: "data/artifacts/7/cover.png",
        metadata: {},
        created_at: "2026-05-01T10:04:00Z"
      }
    ]
  });
  apiMock.videoArtifactText.mockImplementation(async (_taskId: number, artifactId: number) => {
    if (artifactId === 13) {
      return "1\n00:00:00,000 --> 00:00:01,000\nhello world";
    }
    return "1\n00:00:00,000 --> 00:00:01,000\n你好，世界";
  });
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("VideoPreviewPage", () => {
  test("renders original video, dubbed preview, and subtitles", async () => {
    render(<VideoPreviewPage taskId={7} />);

    expect(await screen.findByRole("heading", { name: "视频预览详情" })).toBeInTheDocument();
    expect(screen.getByText("原视频")).toBeInTheDocument();
    expect(screen.getByText("重新配音后视频")).toBeInTheDocument();
    expect(screen.getByText("原始字幕")).toBeInTheDocument();
    expect(screen.getByText("中文字幕")).toBeInTheDocument();
    expect(screen.getByText("投稿信息")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新生成" })).toBeInTheDocument();
    expect(screen.getByText("视频封面")).toBeInTheDocument();
    expect(screen.getByAltText("当前视频封面")).toHaveAttribute("src", "/api/videos/7/artifacts/9");
    expect(screen.getByText("B 站发布")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "手动上传B站" })).toBeInTheDocument();
    expect(screen.getByLabelText("上传账号")).toHaveValue("21");
    expect(screen.queryByText("10. 上传视频")).not.toBeInTheDocument();
    expect(screen.getByText("上传视频")).toBeInTheDocument();
    expect(screen.getByLabelText("版权")).toHaveValue("2");
    expect(screen.getByText("稿件 AID：10001")).toBeInTheDocument();
    expect(screen.getByText("视频 CID：20002")).toBeInTheDocument();
    expect(screen.getByLabelText("原视频播放器")).toHaveAttribute("src", "/api/videos/7/artifacts/11");
    expect(screen.getByLabelText("重新配音后视频播放器")).toHaveAttribute("src", "/api/videos/7/artifacts/12");
    expect(screen.getByText("hello world")).toBeInTheDocument();
    expect(screen.getByText("你好，世界")).toBeInTheDocument();
    await waitFor(() => expect(apiMock.videoArtifactText).toHaveBeenCalledTimes(2));
  });

  test("generates cover from text prompt and uploaded reference image", async () => {
    render(<VideoPreviewPage taskId={7} />);

    const prompt = await screen.findByLabelText("提示词");
    fireEvent.change(prompt, { target: { value: "科技感封面，突出中文配音" } });
    fireEvent.click(screen.getByRole("button", { name: "文生图生成封面" }));

    await waitFor(() =>
      expect(apiMock.generateCover).toHaveBeenCalledWith(7, {
        mode: "text",
        prompt: "科技感封面，突出中文配音",
        reference_image: null
      })
    );
    expect(await screen.findByText("视频封面已生成")).toBeInTheDocument();
    expect(screen.getByAltText("当前视频封面")).toHaveAttribute("src", "/api/videos/7/artifacts/15");

    const file = new File(["reference"], "reference.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("参考图"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "图生图生成封面" }));

    await waitFor(() =>
      expect(apiMock.generateCover).toHaveBeenLastCalledWith(7, {
        mode: "image",
        prompt: "科技感封面，突出中文配音",
        reference_image: file
      })
    );
  });

  test("saves metadata and triggers manual bilibili upload", async () => {
    render(<VideoPreviewPage taskId={7} />);

    const titleInput = await screen.findByLabelText("标题");
    fireEvent.change(titleInput, { target: { value: "新投稿标题" } });
    fireEvent.change(screen.getByLabelText("简介"), { target: { value: "新简介" } });
    fireEvent.change(screen.getByLabelText("标签"), { target: { value: "技术, 翻译" } });
    fireEvent.change(screen.getByLabelText("分区"), { target: { value: "知识" } });
    fireEvent.change(screen.getByLabelText("版权"), { target: { value: "1" } });
    fireEvent.submit(titleInput.closest("form") as HTMLFormElement);

    await waitFor(() => {
      expect(apiMock.updateMetadata).toHaveBeenCalledWith(7, {
        title: "新投稿标题",
        description: "新简介",
        tags: ["技术", "翻译"],
        category: "知识",
        copyright_type: 1
      });
    });

    fireEvent.change(screen.getByLabelText("上传账号"), { target: { value: "22" } });
    fireEvent.click(screen.getByRole("button", { name: "手动上传B站" }));

    await waitFor(() => expect(apiMock.runBilibiliUpload).toHaveBeenCalledWith(7, { account_id: 22 }));
    expect(await screen.findByText(/B 站后台上传任务已启动/)).toBeInTheDocument();
  });

  test("regenerates submission metadata from preview detail", async () => {
    render(<VideoPreviewPage taskId={7} />);

    fireEvent.click(await screen.findByRole("button", { name: "重新生成" }));

    await waitFor(() => expect(apiMock.retryTaskStep).toHaveBeenCalledWith(7, 9));
    expect(await screen.findByText("投稿信息已重新生成")).toBeInTheDocument();
  });

  test("collapses and expands subtitle text manually", async () => {
    render(<VideoPreviewPage taskId={7} />);

    expect(await screen.findByText("hello world")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "折叠" })[0]);

    expect(screen.queryByText("hello world")).not.toBeInTheDocument();
    expect(screen.queryByText("原始字幕已折叠。")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(screen.getByText("hello world")).toBeInTheDocument();
  });

  test("shows subtitle retry action when subtitle upload failed", async () => {
    apiMock.task.mockResolvedValue({
      ...taskFixture,
      steps: taskFixture.steps.map((step) =>
        step.name === "upload_subtitle"
          ? { ...step, status: "failed", error_message: "subtitle rejected" }
          : step
      )
    });

    render(<VideoPreviewPage taskId={7} />);

    expect(await screen.findByRole("button", { name: "重新上传字幕" })).toBeInTheDocument();
    expect(screen.getByText(/视频稿件已保留，字幕上传失败/)).toBeInTheDocument();
  });

  test("shows detailed video upload failure on preview page", async () => {
    apiMock.task.mockResolvedValue({
      ...taskFixture,
      status: "failed",
      current_step: "upload_video",
      error_summary: "manual upload step upload_video failed: B 站视频文件上传失败：HTTP 403",
      steps: taskFixture.steps.map((step) =>
        step.name === "upload_video"
          ? { ...step, status: "failed", error_message: "B 站视频文件上传失败：HTTP 403" }
          : step
      )
    });

    render(<VideoPreviewPage taskId={7} />);

    expect(await screen.findByText(/视频上传失败：B 站视频文件上传失败：HTTP 403/)).toBeInTheDocument();
  });
});
