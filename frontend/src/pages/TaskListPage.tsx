import { AlertCircle, ChevronRight, FilePenLine, Play, RefreshCw, RotateCcw, Search, Square, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { Status, Task } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ProgressBar } from "../components/ProgressBar";

type TaskFilter = "all" | "running" | "success" | "failed";

function canCancel(task: Task) {
  return !["success", "failed", "cancelled"].includes(task.status);
}

function canRetry(task: Task) {
  return task.status === "failed" || task.status === "cancelled";
}

function canDelete(task: Task) {
  return ["success", "failed", "cancelled"].includes(task.status);
}

function formatShortDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function videoId(task: Task) {
  if (task.source_type !== "youtube") {
    return task.input;
  }
  try {
    const url = new URL(task.input);
    return url.searchParams.get("v") || url.pathname.split("/").filter(Boolean).pop() || task.title;
  } catch {
    return task.title;
  }
}

function completedSteps(task: Task) {
  return task.steps.filter((step) => step.status === "success" || step.status === "skipped").length;
}

function queuedCount(tasks: Task[]) {
  return tasks.filter((task) => task.status === "pending").length;
}

function filterTasks(tasks: Task[], filter: TaskFilter) {
  if (filter === "all") {
    return tasks;
  }
  return tasks.filter((task) => task.status === filter);
}

function countByStatus(tasks: Task[], status: Status) {
  return tasks.filter((task) => task.status === status).length;
}

export function TaskListPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [activeFilter, setActiveFilter] = useState<TaskFilter>("all");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionLoading, setActionLoading] = useState("");

  async function load(searchKeyword = keyword) {
    setLoading(true);
    try {
      const data = await apiClient.tasks(searchKeyword.trim() ? { keyword: searchKeyword.trim() } : undefined);
      setTasks(data.items);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务队列加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("");
  }, []);

  async function runAction(task: Task, action: "cancel" | "retry" | "delete") {
    if (action === "delete") {
      const confirmed = window.confirm(
        `确认删除任务「${task.title}」？此操作会删除步骤、日志、产物和投稿信息，且无法恢复。`
      );
      if (!confirmed) {
        return;
      }
    }

    try {
      setActionError("");
      setActionLoading(`${action}-${task.id}`);
      if (action === "cancel") {
        await apiClient.cancelTask(task.id);
      } else if (action === "delete") {
        await apiClient.deleteTask(task.id);
      } else {
        await apiClient.retryTask(task.id);
      }
      await load();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "任务操作失败");
    } finally {
      setActionLoading("");
    }
  }

  const filteredTasks = filterTasks(tasks, activeFilter);
  const running = countByStatus(tasks, "running");
  const completed = countByStatus(tasks, "success");
  const failed = countByStatus(tasks, "failed");
  const pending = queuedCount(tasks);
  const tabs: Array<{ key: TaskFilter; label: string; count?: number }> = [
    { key: "all", label: "全部", count: tasks.length },
    { key: "running", label: "处理中", count: running },
    { key: "success", label: "已完成", count: completed },
    { key: "failed", label: "失败", count: failed }
  ];

  return (
    <div className="page task-management-page">
      <div className="task-management-head">
        <h1>任务管理</h1>
        <button className="icon-text-button" type="button" onClick={() => void load(keyword)} disabled={loading || Boolean(actionLoading)}>
          <RefreshCw size={15} aria-hidden="true" />
          <span>刷新</span>
        </button>
      </div>

      <Card>
        <form
          className="task-management-search"
          onSubmit={(event) => {
            event.preventDefault();
            void load(keyword);
          }}
        >
          <label className="sr-only" htmlFor="task-keyword">
            搜索任务
          </label>
          <input
            className="input"
            id="task-keyword"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="按标题、链接或本地路径搜索"
          />
          <button className="button secondary" type="submit">
            <Search size={16} aria-hidden="true" />
            <span>筛选</span>
          </button>
        </form>
      </Card>

      {error ? <div className="alert">任务队列暂不可用：{error}</div> : null}
      {actionError ? <div className="alert">任务操作失败：{actionError}</div> : null}

      <div className="task-status-tabs" role="tablist" aria-label="任务状态筛选">
        {tabs.map((tab) => (
          <button
            className={activeFilter === tab.key ? "active" : ""}
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeFilter === tab.key}
            onClick={() => setActiveFilter(tab.key)}
          >
            <span>{tab.label}</span>
            {typeof tab.count === "number" && tab.count > 0 ? <strong>{tab.count}</strong> : null}
          </button>
        ))}
      </div>

      <section className="task-chain-section" aria-labelledby="task-chain-title">
        <h2 id="task-chain-title">视频处理任务链</h2>
        <div className="task-chain-list">
          {filteredTasks.map((task) => {
            const stepTotal = task.steps.length || 1;
            const doneSteps = completedSteps(task);
            return (
              <article className="task-chain-card" key={task.id}>
                <div className="task-chain-main">
                  <div className="task-chain-title-row">
                    <strong>{task.title}</strong>
                    <Badge status={task.status} />
                    <span className="task-config-pill">best</span>
                    <span className="task-config-pill accent">音色: 默认音色</span>
                  </div>
                  <p>{task.error_summary || `当前步骤：${task.current_step || "等待调度"}`}</p>
                  <div className="task-chain-progress">
                    <ProgressBar value={task.progress} />
                    <span>
                      {doneSteps}/{stepTotal}
                    </span>
                    <span>{Math.round(task.progress)}%</span>
                  </div>
                  <div className="task-chain-meta">
                    <span>视频ID: {videoId(task)}</span>
                    <span>创建: {formatShortDate(task.created_at)}</span>
                    <span>更新: {formatShortDate(task.updated_at)}</span>
                  </div>
                </div>
                <div className="task-chain-actions">
                  <a className="icon-text-button ghost" href={`#/tasks/${task.id}`}>
                    <ChevronRight size={14} aria-hidden="true" />
                    <span>展开</span>
                  </a>
                  <button
                    className="icon-text-button warning"
                    type="button"
                    disabled={Boolean(actionLoading) || !canRetry(task)}
                    onClick={() => void runAction(task, "retry")}
                  >
                    <RotateCcw size={14} aria-hidden="true" />
                    <span>继续/重跑</span>
                  </button>
                  <a className="icon-text-button pink" href={`#/tasks/${task.id}`}>
                    <FilePenLine size={14} aria-hidden="true" />
                    <span>编辑投稿</span>
                  </a>
                  <button
                    className="icon-text-button danger"
                    type="button"
                    disabled={Boolean(actionLoading) || !canCancel(task)}
                    onClick={() => void runAction(task, "cancel")}
                  >
                    <Square size={14} aria-hidden="true" />
                    <span>取消</span>
                  </button>
                  <button
                    className="icon-text-button delete"
                    type="button"
                    disabled={Boolean(actionLoading) || !canDelete(task)}
                    title={canDelete(task) ? undefined : "仅可删除已完成、失败或已取消任务"}
                    onClick={() => void runAction(task, "delete")}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                    <span>删除</span>
                  </button>
                </div>
              </article>
            );
          })}
        </div>
        {loading ? <p className="empty-state task-management-empty">加载任务队列...</p> : null}
        {!loading && filteredTasks.length === 0 ? <p className="empty-state task-management-empty">暂无任务。</p> : null}
      </section>

      <section className="automation-policy" aria-labelledby="automation-policy-title">
        <h2 id="automation-policy-title">自动化调度策略</h2>
        <div className="automation-policy-list">
          <div className="automation-policy-row">
            <span className="automation-policy-icon">
              <Play size={18} aria-hidden="true" />
            </span>
            <div>
              <h3>视频处理任务链</h3>
              <p>基础顺序为：导入任务、下载视频、下载缩略图、提取音频、生成字幕、翻译字幕、合成配音、同步预览、生成投稿信息。</p>
              <small>
                当前处理中 {running} 个 | 待处理 {pending} 个
              </small>
            </div>
          </div>
          <div className="automation-policy-row">
            <span className="automation-policy-icon upload">
              <FilePenLine size={18} aria-hidden="true" />
            </span>
            <div>
              <h3>B站自动上传调度</h3>
              <p>当前版本保留上传前编辑入口；任务详情页可维护标题、简介、标签、分区和上传状态。</p>
            </div>
          </div>
          <div className="automation-policy-row alert-row">
            <span className="automation-policy-icon danger">
              <AlertCircle size={18} aria-hidden="true" />
            </span>
            <div>
              <h3>失败任务提醒</h3>
              <p>{failed > 0 ? `当前有 ${failed} 个任务失败，请展开查看详情并手动重试失败步骤。` : "当前没有失败任务。"}</p>
            </div>
          </div>
        </div>
      </section>

      <div className="task-summary-grid">
        <div className="task-summary-card">
          <span>总任务数</span>
          <strong>{tasks.length}</strong>
        </div>
        <div className="task-summary-card">
          <span>处理中</span>
          <strong className="blue">{running}</strong>
        </div>
        <div className="task-summary-card">
          <span>已完成</span>
          <strong className="green">{completed}</strong>
        </div>
        <div className="task-summary-card">
          <span>失败</span>
          <strong className="red">{failed}</strong>
        </div>
      </div>
    </div>
  );
}
