import { ExternalLink, Film, RotateCcw, Tags } from "lucide-react";
import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { Task } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { libraryPreviewArtifact, videoTags, videoTitle } from "../videoArtifacts";

export function VideosPage() {
  const [videos, setVideos] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [regeneratingTaskId, setRegeneratingTaskId] = useState<number | null>(null);

  async function load() {
    try {
      const data = await apiClient.videos();
      setVideos(data.items);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "视频列表加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function regenerateMetadata(video: Task) {
    const metadataStep = video.steps.find((step) => step.name === "generate_metadata");
    if (!metadataStep) {
      setActionMessage("未找到生成投稿信息步骤。");
      return;
    }

    setRegeneratingTaskId(video.id);
    setActionMessage("");
    try {
      await apiClient.retryTaskStep(video.id, metadataStep.id);
      setActionMessage(`「${videoTitle(video)}」投稿信息已重新生成。`);
      await load();
    } catch (caught) {
      setActionMessage(caught instanceof Error ? caught.message : "投稿信息重新生成失败");
    } finally {
      setRegeneratingTaskId(null);
    }
  }

  return (
    <div className="page">
      <Card>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Video Library</span>
            <h1>视频库</h1>
          </div>
          <a className="text-link" href="#/tasks">
            查看任务队列
          </a>
        </div>
        <p className="section-copy">
          双列查看已完成或失败的视频，先在列表里快速预览，再进入独立页面比对原视频、配音预览和字幕。
        </p>
      </Card>

      {error ? <div className="alert">视频列表暂不可用：{error}</div> : null}
      {actionMessage ? <div className="alert neutral">{actionMessage}</div> : null}

      <Card>
        {loading ? <p className="empty-state">加载视频列表...</p> : null}
        {!loading && videos.length === 0 ? <p className="empty-state">暂无可投稿视频。</p> : null}
        <div className="video-grid">
          {videos.map((video) => (
            <article className="video-card" key={video.id}>
              <div className="video-preview-shell">
                {libraryPreviewArtifact(video) ? (
                  <video
                    aria-label={`${videoTitle(video)} 预览`}
                    className="video-preview-player"
                    controls
                    preload="metadata"
                    src={apiClient.videoArtifactUrl(video.id, libraryPreviewArtifact(video)!.id)}
                  />
                ) : (
                  <div className="video-thumb">
                    <Film size={22} />
                    <span>等待生成预览</span>
                  </div>
                )}
              </div>
              <div className="video-card-body">
                <div className="video-card-head">
                  <strong>{videoTitle(video)}</strong>
                  <Badge status={video.status} />
                </div>
                <span className="video-source">{video.input}</span>
                <div className="video-meta">
                  <span>
                    <Tags size={14} aria-hidden="true" />
                    {videoTags(video)}
                  </span>
                  <span>
                    分区：<strong>{video.metadata?.category || "-"}</strong>
                  </span>
                  <span>
                    上传：<strong>{video.metadata?.upload_status || "-"}</strong>
                  </span>
                  <span>
                    B 站稿件：<strong>{video.metadata?.bilibili_video_id || "-"}</strong>
                  </span>
                </div>
                <div className="video-card-actions">
                  <button
                    className="icon-text-button video-detail-link"
                    type="button"
                    disabled={
                      video.status === "running" ||
                      regeneratingTaskId !== null ||
                      !video.steps.some((step) => step.name === "generate_metadata")
                    }
                    onClick={() => void regenerateMetadata(video)}
                  >
                    <RotateCcw size={14} aria-hidden="true" />
                    <span>{regeneratingTaskId === video.id ? "生成中" : "重新生成"}</span>
                  </button>
                  <a className="icon-text-button video-detail-link" href={`#/videos/${video.id}`}>
                    <ExternalLink size={14} aria-hidden="true" />
                    <span>预览详情</span>
                  </a>
                  <a className="icon-text-button video-detail-link" href={`#/tasks/${video.id}`}>
                    <ExternalLink size={14} aria-hidden="true" />
                    <span>任务详情</span>
                  </a>
                </div>
              </div>
            </article>
          ))}
        </div>
      </Card>
    </div>
  );
}
