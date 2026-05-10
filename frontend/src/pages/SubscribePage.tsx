import { CheckCircle2, CircleUserRound, ExternalLink, Play, RefreshCw, Rss, Search, UsersRound } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { apiClient } from "../api/client";
import type { SubscriptionChannel, SubscriptionVideo } from "../api/types";
import { Card } from "../components/Card";

type TabKey = "videos" | "channels";

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString();
}

function videoStatusLabel(video: SubscriptionVideo) {
  if (video.task_id) {
    return "已入队";
  }
  return video.status === "queued" ? "已入队" : "待创建";
}

export function SubscribePage() {
  const [activeTab, setActiveTab] = useState<TabKey>("videos");
  const [channels, setChannels] = useState<SubscriptionChannel[]>([]);
  const [videos, setVideos] = useState<SubscriptionVideo[]>([]);
  const [channelInput, setChannelInput] = useState("");
  const [channelKeyword, setChannelKeyword] = useState("");
  const [videoKeyword, setVideoKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState("");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");

  async function load(params?: { channelKeyword?: string; videoKeyword?: string }) {
    setLoading(true);
    try {
      const [channelData, videoData] = await Promise.all([
        apiClient.subscriptionChannels(
          (params?.channelKeyword ?? channelKeyword).trim()
            ? { keyword: (params?.channelKeyword ?? channelKeyword).trim() }
            : undefined
        ),
        apiClient.subscriptionVideos(
          (params?.videoKeyword ?? videoKeyword).trim()
            ? { keyword: (params?.videoKeyword ?? videoKeyword).trim() }
            : undefined
        )
      ]);
      setChannels(channelData.items);
      setVideos(videoData.items);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "订阅数据加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load({ channelKeyword: "", videoKeyword: "" });
  }, []);

  async function runAction(name: string, action: () => Promise<unknown>) {
    setActionLoading(name);
    try {
      setActionError("");
      await action();
      await load();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "订阅操作失败");
    } finally {
      setActionLoading("");
    }
  }

  async function submitChannel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = channelInput.trim();
    if (!input) {
      setActionError("请输入 YouTube 频道 URL、@handle 或 channel id");
      return;
    }
    await runAction("create-channel", async () => {
      await apiClient.createSubscriptionChannel(input);
      setChannelInput("");
      setActiveTab("channels");
    });
  }

  const channelErrors = useMemo(
    () => channels.filter((channel) => channel.error_summary.trim()),
    [channels]
  );

  const pageSubtitle =
    activeTab === "videos"
      ? `订阅频道的最新视频 · 共 ${videos.length} 个视频`
      : `已订阅的频道 · 共 ${channels.length} 个频道`;

  return (
    <div className="page subscribe-page">
      <Card>
        <div className="subscribe-head">
          <div>
            <span className="eyebrow">YouTube Subscription</span>
            <h1>YouTube 订阅</h1>
            <p>{pageSubtitle}</p>
          </div>
          <button
            className="button"
            type="button"
            disabled={Boolean(actionLoading)}
            onClick={() =>
              void runAction("sync-all", async () => {
                await apiClient.syncSubscriptionChannels();
              })
            }
          >
            <Rss size={16} aria-hidden="true" />
            <span>{activeTab === "videos" ? "同步订阅" : "刷新"}</span>
          </button>
        </div>

        <div className="subscribe-tabs" role="tablist" aria-label="YouTube 订阅视图">
          <button
            className={activeTab === "videos" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={activeTab === "videos"}
            onClick={() => setActiveTab("videos")}
          >
            <Play size={16} aria-hidden="true" />
            <span>订阅视频</span>
          </button>
          <button
            className={activeTab === "channels" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={activeTab === "channels"}
            onClick={() => setActiveTab("channels")}
          >
            <UsersRound size={16} aria-hidden="true" />
            <span>订阅频道</span>
          </button>
        </div>
      </Card>

      {error ? <div className="alert">订阅数据暂不可用：{error}</div> : null}
      {actionError ? <div className="alert">订阅操作失败：{actionError}</div> : null}
      {channelErrors.length ? (
        <div className="alert">最近同步异常：{channelErrors.map((channel) => channel.title).join("、")}</div>
      ) : null}

      {activeTab === "videos" ? (
        <Card>
          <form
            className="filter-bar"
            onSubmit={(event) => {
              event.preventDefault();
              void load({ videoKeyword });
            }}
          >
            <label className="sr-only" htmlFor="subscription-video-keyword">
              搜索订阅视频
            </label>
            <input
              className="input"
              id="subscription-video-keyword"
              value={videoKeyword}
              onChange={(event) => setVideoKeyword(event.target.value)}
              placeholder="按视频标题、频道或 video id 搜索"
            />
            <button className="button secondary" type="submit">
              <Search size={16} aria-hidden="true" />
              <span>筛选</span>
            </button>
          </form>

          <div className="table-shell subscribe-table-shell">
            <table className="data-table subscribe-table">
              <thead>
                <tr>
                  <th>视频</th>
                  <th>频道</th>
                  <th>发布时间</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {videos.map((video) => (
                  <tr key={video.id}>
                    <td>
                      <strong>{video.title}</strong>
                      <span>{video.youtube_url}</span>
                    </td>
                    <td>{video.channel_title}</td>
                    <td>{formatDate(video.published_at)}</td>
                    <td>
                      <span className={`status-badge ${video.task_id ? "status-running" : "status-pending"}`}>
                        {videoStatusLabel(video)}
                      </span>
                    </td>
                    <td>
                      <div className="table-actions">
                        {video.task_id ? (
                          <a className="text-link" href={`#/tasks/${video.task_id}`}>
                            任务详情
                          </a>
                        ) : (
                          <button
                            className="icon-text-button"
                            type="button"
                            disabled={Boolean(actionLoading)}
                            onClick={() =>
                              void runAction(`video-${video.id}`, async () => {
                                await apiClient.createTaskFromSubscriptionVideo(video.id);
                              })
                            }
                          >
                            <CheckCircle2 size={14} aria-hidden="true" />
                            <span>创建任务</span>
                          </button>
                        )}
                        <a className="icon-text-button" href={video.youtube_url} target="_blank" rel="noreferrer">
                          <ExternalLink size={14} aria-hidden="true" />
                          <span>打开</span>
                        </a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {loading ? <p className="empty-state">加载订阅视频...</p> : null}
          {!loading && videos.length === 0 ? (
            <div className="subscribe-empty">
              <Play size={44} aria-hidden="true" />
              <h3>暂无视频</h3>
              <p>点击“同步订阅”按钮从 YouTube 订阅频道获取最新视频</p>
            </div>
          ) : null}
        </Card>
      ) : (
        <Card>
          <form className="subscribe-channel-form" onSubmit={submitChannel}>
            <label className="sr-only" htmlFor="subscription-channel-input">
              YouTube 频道
            </label>
            <input
              className="input"
              id="subscription-channel-input"
              value={channelInput}
              onChange={(event) => setChannelInput(event.target.value)}
              placeholder="粘贴频道 URL、@handle 或 channel id"
            />
            <button className="button" type="submit" disabled={Boolean(actionLoading)}>
              <UsersRound size={16} aria-hidden="true" />
              <span>订阅频道</span>
            </button>
          </form>
          <form
            className="filter-bar subscribe-channel-search"
            onSubmit={(event) => {
              event.preventDefault();
              void load({ channelKeyword });
            }}
          >
            <label className="sr-only" htmlFor="subscription-channel-keyword">
              搜索频道
            </label>
            <input
              className="input"
              id="subscription-channel-keyword"
              value={channelKeyword}
              onChange={(event) => setChannelKeyword(event.target.value)}
              placeholder="搜索频道..."
            />
            <button className="button secondary" type="submit">
              <Search size={16} aria-hidden="true" />
              <span>搜索</span>
            </button>
          </form>

          <div className="subscription-channel-list">
            {channels.map((channel) => (
              <article className="subscription-channel-row" key={channel.id}>
                <div className="subscription-channel-avatar">
                  {channel.thumbnail_url ? (
                    <img src={channel.thumbnail_url} alt="" />
                  ) : (
                    <CircleUserRound size={24} aria-hidden="true" />
                  )}
                </div>
                <div>
                  <strong>{channel.title}</strong>
                  <span>{channel.source_url}</span>
                  {channel.error_summary ? <em>同步异常：{channel.error_summary}</em> : null}
                </div>
                <div className="subscription-channel-meta">
                  <span>{channel.video_count} 个视频</span>
                  <span>最近同步：{formatDate(channel.last_synced_at)}</span>
                </div>
                <button
                  className="icon-text-button"
                  type="button"
                  disabled={Boolean(actionLoading)}
                  onClick={() =>
                    void runAction(`channel-${channel.id}`, async () => {
                      await apiClient.syncSubscriptionChannel(channel.id);
                    })
                  }
                >
                  <RefreshCw size={14} aria-hidden="true" />
                  <span>同步</span>
                </button>
              </article>
            ))}
          </div>
          {loading ? <p className="empty-state">加载订阅频道...</p> : null}
          {!loading && channels.length === 0 ? (
            <div className="subscribe-empty">
              <UsersRound size={44} aria-hidden="true" />
              <h3>暂无订阅频道</h3>
              <p>还没有订阅任何 YouTube 频道</p>
            </div>
          ) : null}
        </Card>
      )}
    </div>
  );
}
