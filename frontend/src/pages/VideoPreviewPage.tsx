import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileImage,
  FileText,
  Film,
  ImagePlus,
  RotateCcw,
  Save,
  Send,
  Tags
} from "lucide-react";
import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { AccountBinding, Task, TaskStep } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import {
  dubbedVideoArtifact,
  coverArtifact,
  originalVideoArtifact,
  sourceSubtitleArtifact,
  subtitleTextPreview,
  translatedSubtitleArtifact,
  videoTags,
  videoTitle
} from "../videoArtifacts";

interface VideoPreviewPageProps {
  taskId?: number;
}

type SubtitleState = {
  source: string;
  translated: string;
  error: string;
  loading: boolean;
};

type SubtitleKey = "source" | "translated";

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

async function loadSubtitleText(task: Task) {
  const sourceArtifact = sourceSubtitleArtifact(task);
  const translatedArtifact = translatedSubtitleArtifact(task);

  const [sourceText, translatedText] = await Promise.all([
    sourceArtifact ? apiClient.videoArtifactText(task.id, sourceArtifact.id) : Promise.resolve(""),
    translatedArtifact ? apiClient.videoArtifactText(task.id, translatedArtifact.id) : Promise.resolve("")
  ]);

  return {
    source: subtitleTextPreview(sourceText),
    translated: subtitleTextPreview(translatedText)
  };
}

function PreviewVideo({
  task,
  artifactId,
  label,
  emptyText
}: {
  task: Task;
  artifactId: number | null;
  label: string;
  emptyText: string;
}) {
  if (!artifactId) {
    return (
      <div className="preview-player-empty">
        <Film size={20} aria-hidden="true" />
        <span>{emptyText}</span>
      </div>
    );
  }

  return (
    <video
      aria-label={label}
      className="preview-player"
      controls
      preload="metadata"
      src={apiClient.videoArtifactUrl(task.id, artifactId)}
    />
  );
}

function tagsText(task: Task) {
  return task.metadata?.tags.join(", ") ?? "";
}

function stepByName(task: Task, stepName: string) {
  return task.steps.find((step) => step.name === stepName) || null;
}

function UploadStepRow({ step }: { step: TaskStep | null }) {
  return (
    <div className="upload-step-row">
      <div>
        <strong>{step ? step.label : "上传步骤"}</strong>
        <span>{step?.name || "未创建"}</span>
      </div>
      {step ? <Badge status={step.status} /> : <span className="empty-state compact">暂无步骤</span>}
    </div>
  );
}

function activeBilibiliAccounts(accounts: AccountBinding[]) {
  return accounts.filter((account) => account.platform === "bilibili" && account.status === "active");
}

export function VideoPreviewPage({ taskId }: VideoPreviewPageProps) {
  const [task, setTask] = useState<Task | null>(null);
  const [accounts, setAccounts] = useState<AccountBinding[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [coverGenerating, setCoverGenerating] = useState(false);
  const [metadataGenerating, setMetadataGenerating] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");
  const [coverPrompt, setCoverPrompt] = useState("");
  const [coverReference, setCoverReference] = useState<File | null>(null);
  const [coverMessage, setCoverMessage] = useState("");
  const [collapsedSubtitles, setCollapsedSubtitles] = useState<Record<SubtitleKey, boolean>>({
    source: false,
    translated: false
  });
  const [subtitleState, setSubtitleState] = useState<SubtitleState>({
    source: "",
    translated: "",
    error: "",
    loading: false
  });

  const resolvedTaskId = taskId ?? null;

  useEffect(() => {
    let cancelled = false;

    async function loadAccounts() {
      try {
        const data = await apiClient.accounts();
        if (cancelled) {
          return;
        }
        const activeAccounts = activeBilibiliAccounts(data.items);
        setAccounts(activeAccounts);
        setSelectedAccountId((current) => {
          if (current && activeAccounts.some((account) => String(account.id) === current)) {
            return current;
          }
          const primary = activeAccounts.find((account) => account.is_primary);
          return String((primary ?? activeAccounts[0])?.id ?? "");
        });
      } catch {
        if (!cancelled) {
          setAccounts([]);
          setSelectedAccountId("");
        }
      }
    }

    void loadAccounts();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (resolvedTaskId === null) {
      return;
    }
    const currentTaskId = resolvedTaskId;

    let cancelled = false;

    async function load() {
      try {
        const taskData = await apiClient.task(currentTaskId);
        if (cancelled) {
          return;
        }
        setTask(taskData);
        setError("");

        setSubtitleState((current) => ({ ...current, loading: true, error: "" }));
        try {
          const subtitles = await loadSubtitleText(taskData);
          if (cancelled) {
            return;
          }
          setSubtitleState({
            source: subtitles.source,
            translated: subtitles.translated,
            error: "",
            loading: false
          });
        } catch (caught) {
          if (cancelled) {
            return;
          }
          setSubtitleState({
            source: "",
            translated: "",
            error: caught instanceof Error ? caught.message : "字幕加载失败",
            loading: false
          });
        }
      } catch (caught) {
        if (cancelled) {
          return;
        }
        setError(caught instanceof Error ? caught.message : "视频预览详情加载失败");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [resolvedTaskId]);

  useEffect(() => {
    if (!task || resolvedTaskId === null || task.status !== "running" || !task.current_step.startsWith("upload_")) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      void apiClient
        .task(resolvedTaskId)
        .then((taskData) => {
          if (!cancelled) {
            setTask(taskData);
          }
        })
        .catch(() => {
          // The next manual refresh or route visit will retry loading task state.
        });
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [resolvedTaskId, task]);

  async function reloadTask() {
    if (resolvedTaskId === null) {
      return;
    }
    const taskData = await apiClient.task(resolvedTaskId);
    setTask(taskData);
  }

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!task || !task.metadata) {
      return;
    }
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setSaveMessage("");
    try {
      await apiClient.updateMetadata(task.id, {
        title: String(form.get("title") ?? "").trim(),
        description: String(form.get("description") ?? "").trim(),
        tags: String(form.get("tags") ?? "")
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
        category: String(form.get("category") ?? "").trim(),
        copyright_type: Number(form.get("copyright_type")) === 1 ? 1 : 2
      });
      setSaveMessage("投稿信息已保存");
      await reloadTask();
    } catch (caught) {
      setSaveMessage(caught instanceof Error ? caught.message : "投稿信息保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function regenerateMetadata() {
    if (!task) {
      return;
    }
    const metadataStep = stepByName(task, "generate_metadata");
    if (!metadataStep) {
      setSaveMessage("未找到生成投稿信息步骤。");
      return;
    }

    setMetadataGenerating(true);
    setSaveMessage("");
    try {
      const updated = await apiClient.retryTaskStep(task.id, metadataStep.id);
      setTask(updated);
      setSaveMessage("投稿信息已重新生成");
    } catch (caught) {
      setSaveMessage(caught instanceof Error ? caught.message : "投稿信息重新生成失败");
    } finally {
      setMetadataGenerating(false);
    }
  }

  async function runManualUpload() {
    if (!task || !selectedAccountId) {
      return;
    }
    setUploading(true);
    setUploadMessage("");
    try {
      const updated = await apiClient.runBilibiliUpload(task.id, {
        account_id: Number(selectedAccountId)
      });
      setTask(updated);
      setUploadMessage("B 站后台上传任务已启动，页面会自动刷新状态。");
    } catch (caught) {
      setUploadMessage(caught instanceof Error ? caught.message : "手动上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function runCoverGeneration(mode: "text" | "image") {
    if (!task) {
      return;
    }
    setCoverGenerating(true);
    setCoverMessage("");
    try {
      const updated = await apiClient.generateCover(task.id, {
        mode,
        prompt: coverPrompt,
        reference_image: mode === "image" ? coverReference : null
      });
      setTask(updated);
      setCoverMessage("视频封面已生成");
    } catch (caught) {
      setCoverMessage(caught instanceof Error ? caught.message : "视频封面生成失败");
    } finally {
      setCoverGenerating(false);
    }
  }

  function updateCoverReference(event: ChangeEvent<HTMLInputElement>) {
    setCoverReference(event.currentTarget.files?.[0] ?? null);
  }

  function toggleSubtitle(key: SubtitleKey) {
    setCollapsedSubtitles((current) => ({ ...current, [key]: !current[key] }));
  }

  if (resolvedTaskId === null) {
    return (
      <Card>
        <h1>视频预览详情</h1>
        <p className="empty-state">未指定视频任务 ID。</p>
      </Card>
    );
  }

  const originalArtifact = task ? originalVideoArtifact(task) : null;
  const dubbedArtifact = task ? dubbedVideoArtifact(task) : null;
  const currentCoverArtifact = task ? coverArtifact(task) : null;
  const uploadVideoStep = task ? stepByName(task, "upload_video") : null;
  const uploadSubtitleStep = task ? stepByName(task, "upload_subtitle") : null;
  const metadataStep = task ? stepByName(task, "generate_metadata") : null;
  const hasUploadAccount = accounts.length > 0;
  const uploadFailureMessage =
    uploadVideoStep?.status === "failed"
      ? uploadVideoStep.error_message || task?.error_summary || "请查看任务日志"
      : uploadSubtitleStep?.status === "failed"
        ? uploadSubtitleStep.error_message || task?.error_summary || "请查看任务日志"
        : "";

  return (
    <div className="page">
      {error ? <div className="alert">视频预览详情暂不可用：{error}</div> : null}

      <Card>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Video Preview</span>
            <h1>视频预览详情</h1>
          </div>
          <div className="table-actions">
            <a className="text-link" href="#/videos">
              返回视频库
            </a>
            {task ? (
              <a className="icon-text-button" href={`#/tasks/${task.id}`}>
                <ExternalLink size={14} aria-hidden="true" />
                <span>查看任务详情</span>
              </a>
            ) : null}
          </div>
        </div>
        {loading ? <p className="empty-state">加载视频预览详情...</p> : null}
        {task ? (
          <div className="preview-summary">
            <div className="preview-summary-main">
              <div className="preview-summary-head">
                <div>
                  <h2>{videoTitle(task)}</h2>
                  <p>{task.input}</p>
                </div>
                <Badge status={task.status} />
              </div>
              <div className="preview-summary-meta">
                <span>
                  <Tags size={14} aria-hidden="true" />
                  {videoTags(task)}
                </span>
                <span>来源：{task.source_type}</span>
                <span>步骤：{task.current_step || "-"}</span>
                <span>上传：{task.metadata?.upload_status || "-"}</span>
                <span>B 站稿件：{task.metadata?.bilibili_video_id || "-"}</span>
              </div>
            </div>
            <div className="preview-side-card">
              <strong>处理快照</strong>
              <span>创建：{formatDate(task.created_at)}</span>
              <span>更新：{formatDate(task.updated_at)}</span>
              <span>分区：{task.metadata?.category || "-"}</span>
            </div>
          </div>
        ) : null}
      </Card>

      {task ? (
        <div className="preview-video-grid">
          <Card className="preview-panel">
            <div className="preview-panel-heading">
              <div>
                <span className="eyebrow">Cover Generation</span>
                <h2>视频封面</h2>
              </div>
              <FileImage size={16} aria-hidden="true" />
            </div>
            <div className="cover-generation-panel">
              {currentCoverArtifact ? (
                <img
                  className="cover-preview-image"
                  src={apiClient.videoArtifactUrl(task.id, currentCoverArtifact.id)}
                  alt="当前视频封面"
                />
              ) : (
                <div className="cover-preview-empty">
                  <ImagePlus size={20} aria-hidden="true" />
                  <span>暂无视频封面</span>
                </div>
              )}
              <label htmlFor="cover-generation-prompt">
                <span>提示词</span>
                <textarea
                  className="textarea"
                  id="cover-generation-prompt"
                  value={coverPrompt}
                  onChange={(event) => setCoverPrompt(event.currentTarget.value)}
                  rows={4}
                  placeholder="描述封面的画面、主体、文字氛围和 B 站点击场景"
                />
              </label>
              <label htmlFor="cover-reference-image">
                <span>参考图</span>
                <input
                  className="input"
                  id="cover-reference-image"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={updateCoverReference}
                />
              </label>
              <div className="cover-generation-actions">
                <button
                  className="button"
                  type="button"
                  disabled={coverGenerating}
                  onClick={() => void runCoverGeneration("text")}
                >
                  <ImagePlus size={16} aria-hidden="true" />
                  <span>{coverGenerating ? "生成中" : "文生图生成封面"}</span>
                </button>
                <button
                  className="icon-text-button"
                  type="button"
                  disabled={coverGenerating}
                  onClick={() => void runCoverGeneration("image")}
                >
                  <FileImage size={14} aria-hidden="true" />
                  <span>图生图生成封面</span>
                </button>
              </div>
              <p className="form-note muted">
                图生图会优先使用上传参考图；未上传时使用当前封面或已下载缩略图。
              </p>
              {coverMessage ? <p className="form-note">{coverMessage}</p> : null}
            </div>
          </Card>

          <Card className="preview-panel">
            <div className="preview-panel-heading">
              <div>
                <span className="eyebrow">Submission Metadata</span>
                <h2>投稿信息</h2>
              </div>
              <div className="preview-panel-actions">
                <button
                  className="icon-text-button"
                  type="button"
                  disabled={!metadataStep || metadataGenerating || task.status === "running"}
                  onClick={() => void regenerateMetadata()}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                  <span>{metadataGenerating ? "生成中" : "重新生成"}</span>
                </button>
                <FileText size={16} aria-hidden="true" />
              </div>
            </div>
            {task.metadata ? (
              <form className="metadata-form" onSubmit={saveMetadata}>
                <label htmlFor="preview-metadata-title">
                  <span>标题</span>
                  <input
                    className="input"
                    id="preview-metadata-title"
                    name="title"
                    defaultValue={task.metadata.title}
                  />
                </label>
                <label htmlFor="preview-metadata-description">
                  <span>简介</span>
                  <textarea
                    className="textarea"
                    id="preview-metadata-description"
                    name="description"
                    defaultValue={task.metadata.description}
                    rows={5}
                  />
                </label>
                <label htmlFor="preview-metadata-tags">
                  <span>标签</span>
                  <input className="input" id="preview-metadata-tags" name="tags" defaultValue={tagsText(task)} />
                </label>
                <label htmlFor="preview-metadata-category">
                  <span>分区</span>
                  <input
                    className="input"
                    id="preview-metadata-category"
                    name="category"
                    defaultValue={task.metadata.category}
                  />
                </label>
                <label htmlFor="preview-metadata-copyright">
                  <span>版权</span>
                  <select
                    className="input"
                    id="preview-metadata-copyright"
                    name="copyright_type"
                    defaultValue={String(task.metadata.copyright_type)}
                  >
                    <option value="2">转载</option>
                    <option value="1">自制</option>
                  </select>
                </label>
                <button className="button" type="submit" disabled={saving}>
                  <Save size={16} aria-hidden="true" />
                  <span>{saving ? "保存中" : "保存投稿信息"}</span>
                </button>
                {saveMessage ? <p className="form-note">{saveMessage}</p> : null}
              </form>
            ) : (
              <p className="empty-state">暂无投稿信息。</p>
            )}
          </Card>

          <Card className="preview-panel">
            <div className="preview-panel-heading">
              <div>
                <span className="eyebrow">Bilibili Publish</span>
                <h2>B 站发布</h2>
              </div>
              <Send size={16} aria-hidden="true" />
            </div>
            <div className="manual-upload-panel">
              <UploadStepRow step={uploadVideoStep} />
              <UploadStepRow step={uploadSubtitleStep} />
              <label className="manual-upload-account" htmlFor="bilibili-upload-account">
                <span>上传账号</span>
                <select
                  className="input"
                  id="bilibili-upload-account"
                  value={selectedAccountId}
                  onChange={(event) => setSelectedAccountId(event.currentTarget.value)}
                  disabled={!hasUploadAccount || uploading}
                >
                  {hasUploadAccount ? (
                    accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.nickname || account.platform_user_id}
                        {account.is_primary ? "（默认）" : ""}
                      </option>
                    ))
                  ) : (
                    <option value="">暂无可用 B 站账号</option>
                  )}
                </select>
              </label>
              <div className="metadata-status">
                <span>上传状态：{task.metadata?.upload_status || "-"}</span>
                <span>B 站稿件：{task.metadata?.bilibili_video_id || "-"}</span>
                <span>稿件 AID：{task.metadata?.bilibili_aid || "-"}</span>
                <span>视频 CID：{task.metadata?.bilibili_cid || "-"}</span>
                <span>上传文件：{task.metadata?.bilibili_filename || "-"}</span>
              </div>
              {uploadVideoStep?.status === "failed" ? (
                <p className="manual-upload-note danger">视频上传失败：{uploadFailureMessage}</p>
              ) : uploadSubtitleStep?.status === "failed" ? (
                <p className="manual-upload-note danger">
                  视频稿件已保留，字幕上传失败：{uploadFailureMessage}
                </p>
              ) : (
                <p className="manual-upload-note">
                  {hasUploadAccount
                    ? "上传会使用所选 B 站账号 Cookie，视频成功后再提交中文字幕。"
                    : "暂无可用 B 站账号，请先到账号管理扫码绑定。"}
                </p>
              )}
              <button
                className="button"
                type="button"
                disabled={uploading || !hasUploadAccount}
                onClick={() => void runManualUpload()}
              >
                <Send size={16} aria-hidden="true" />
                <span>
                  {uploading ? "上传处理中" : uploadSubtitleStep?.status === "failed" ? "重新上传字幕" : "手动上传B站"}
                </span>
              </button>
              {uploadMessage ? <p className="form-note">{uploadMessage}</p> : null}
            </div>
          </Card>
        </div>
      ) : null}

      {task ? (
        <div className="preview-video-grid">
          <Card className="preview-panel">
            <div className="preview-panel-heading">
              <div>
                <span className="eyebrow">Original Asset</span>
                <h2>原视频</h2>
              </div>
              <span className="preview-panel-note">{originalArtifact?.path || "原视频未就绪"}</span>
            </div>
            <PreviewVideo
              task={task}
              artifactId={originalArtifact?.id || null}
              label="原视频播放器"
              emptyText="尚未生成原视频文件。"
            />
          </Card>

          <Card className="preview-panel">
            <div className="preview-panel-heading">
              <div>
                <span className="eyebrow">Dubbed Preview</span>
                <h2>重新配音后视频</h2>
              </div>
              <span className="preview-panel-note">{dubbedArtifact?.path || "预览视频未就绪"}</span>
            </div>
            <PreviewVideo
              task={task}
              artifactId={dubbedArtifact?.id || null}
              label="重新配音后视频播放器"
              emptyText="尚未生成同步预览视频。"
            />
          </Card>
        </div>
      ) : null}

      {task ? (
        <div className="preview-video-grid">
          <Card className="preview-panel">
            <div className="preview-panel-heading">
              <div>
                <span className="eyebrow">Source Subtitle</span>
                <h2>原始字幕</h2>
              </div>
              <button
                className="icon-text-button"
                type="button"
                aria-expanded={!collapsedSubtitles.source}
                onClick={() => toggleSubtitle("source")}
              >
                {collapsedSubtitles.source ? (
                  <ChevronDown size={14} aria-hidden="true" />
                ) : (
                  <ChevronUp size={14} aria-hidden="true" />
                )}
                <span>{collapsedSubtitles.source ? "展开" : "折叠"}</span>
              </button>
            </div>
            {!collapsedSubtitles.source ? (
              <div className="subtitle-panel">
                {subtitleState.loading ? <p className="empty-state">加载字幕中...</p> : null}
                {!subtitleState.loading && subtitleState.error ? (
                  <p className="empty-state">{subtitleState.error}</p>
                ) : null}
                {!subtitleState.loading && !subtitleState.error ? (
                  <pre className="subtitle-text">{subtitleState.source || "暂无原始字幕。"}</pre>
                ) : null}
              </div>
            ) : null}
          </Card>

          <Card className="preview-panel">
            <div className="preview-panel-heading">
              <div>
                <span className="eyebrow">Translated Subtitle</span>
                <h2>中文字幕</h2>
              </div>
              <button
                className="icon-text-button"
                type="button"
                aria-expanded={!collapsedSubtitles.translated}
                onClick={() => toggleSubtitle("translated")}
              >
                {collapsedSubtitles.translated ? (
                  <ChevronDown size={14} aria-hidden="true" />
                ) : (
                  <ChevronUp size={14} aria-hidden="true" />
                )}
                <span>{collapsedSubtitles.translated ? "展开" : "折叠"}</span>
              </button>
            </div>
            {!collapsedSubtitles.translated ? (
              <div className="subtitle-panel">
                {subtitleState.loading ? <p className="empty-state">加载字幕中...</p> : null}
                {!subtitleState.loading && subtitleState.error ? (
                  <p className="empty-state">{subtitleState.error}</p>
                ) : null}
                {!subtitleState.loading && !subtitleState.error ? (
                  <pre className="subtitle-text">{subtitleState.translated || "暂无中文字幕。"}</pre>
                ) : null}
              </div>
            ) : null}
          </Card>
        </div>
      ) : null}
    </div>
  );
}
