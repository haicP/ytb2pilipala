import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { SubscribePage } from "../pages/SubscribePage";

const apiMock = vi.hoisted(() => ({
  createSubscriptionChannel: vi.fn(),
  createTaskFromSubscriptionVideo: vi.fn(),
  subscriptionChannels: vi.fn(),
  subscriptionVideos: vi.fn(),
  syncSubscriptionChannel: vi.fn(),
  syncSubscriptionChannels: vi.fn()
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

const channelFixture = {
  id: 1,
  source_url: "https://www.youtube.com/@demo/videos",
  channel_id: "UCdemo",
  title: "Demo Channel",
  thumbnail_url: "",
  status: "active",
  error_summary: "",
  last_synced_at: "2026-05-01T10:00:00Z",
  created_at: "2026-05-01T09:00:00Z",
  updated_at: "2026-05-01T10:00:00Z",
  video_count: 1
};

const videoFixture = {
  id: 2,
  channel_id: 1,
  channel_title: "Demo Channel",
  video_id: "video-1",
  youtube_url: "https://www.youtube.com/watch?v=video-1",
  title: "First video",
  published_at: "2026-05-01T08:00:00Z",
  thumbnail_url: "",
  status: "discovered",
  task_id: null,
  discovered_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:00:00Z"
};

beforeEach(() => {
  apiMock.subscriptionChannels.mockResolvedValue({ items: [channelFixture] });
  apiMock.subscriptionVideos.mockResolvedValue({ items: [videoFixture] });
  apiMock.createSubscriptionChannel.mockResolvedValue(channelFixture);
  apiMock.syncSubscriptionChannel.mockResolvedValue(channelFixture);
  apiMock.syncSubscriptionChannels.mockResolvedValue({ items: [channelFixture] });
  apiMock.createTaskFromSubscriptionVideo.mockResolvedValue({ ...videoFixture, status: "queued", task_id: 8 });
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("SubscribePage", () => {
  test("renders subscription videos and creates a task", async () => {
    render(<SubscribePage />);

    expect(await screen.findByRole("heading", { name: "YouTube 订阅" })).toBeInTheDocument();
    expect(await screen.findByText("订阅频道的最新视频 · 共 1 个视频")).toBeInTheDocument();
    expect(await screen.findByText("First video")).toBeInTheDocument();
    expect(screen.getByText("Demo Channel")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "创建任务" }));

    await waitFor(() => expect(apiMock.createTaskFromSubscriptionVideo).toHaveBeenCalledWith(2));
    await waitFor(() => expect(apiMock.subscriptionVideos).toHaveBeenCalledTimes(2));
  });

  test("shows channel tab and subscribes by handle", async () => {
    render(<SubscribePage />);

    fireEvent.click(await screen.findByRole("tab", { name: "订阅频道" }));

    expect(screen.getByText("已订阅的频道 · 共 1 个频道")).toBeInTheDocument();
    expect(screen.getByText("Demo Channel")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("YouTube 频道"), { target: { value: "@new-channel" } });
    fireEvent.submit(screen.getByLabelText("YouTube 频道").closest("form") as HTMLFormElement);

    await waitFor(() => expect(apiMock.createSubscriptionChannel).toHaveBeenCalledWith("@new-channel"));
  });

  test("renders video empty state", async () => {
    apiMock.subscriptionVideos.mockResolvedValueOnce({ items: [] });

    render(<SubscribePage />);

    expect(await screen.findByRole("heading", { name: "暂无视频" })).toBeInTheDocument();
    expect(screen.getByText("点击“同步订阅”按钮从 YouTube 订阅频道获取最新视频")).toBeInTheDocument();
  });
});
