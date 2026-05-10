import { ExternalLink, RotateCcw, Square } from "lucide-react";
import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { LogItem, Task, TaskStep } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ProgressBar } from "../components/ProgressBar";
import { StepTimeline } from "../components/StepTimeline";

interface TaskDetailPageProps {
  taskId?: number;
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function canCancel(task: Task) {
  return !["success", "failed", "cancelled"].includes(task.status);
}

function canRetry(task: Task) {
  return task.status === "failed";
}

function canRetryStep(task: Task, step: TaskStep) {
  if (["pending", "running"].includes(task.status)) {
    return false;
  }
  return step.status !== "running";
}

export function TaskDetailPage({ taskId }: TaskDetailPageProps) {
  const [task, setTask] = useState<Task | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");

  async function load() {
    if (!taskId) {
      return;
    }
    try {
      const [taskData, logData] = await Promise.all([
        apiClient.task(taskId),
        apiClient.logs(taskId, { limit: 100 })
      ]);
      setTask(taskData);
      setLogs(logData.items);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务详情加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    if (!taskId) {
      return undefined;
    }
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [taskId]);

  async function runAction(action: "cancel" | "retry") {
    if (!task) {
      return;
    }
    try {
      setActionError("");
      if (action === "cancel") {
        await apiClient.cancelTask(task.id);
      } else {
        await apiClient.retryTask(task.id);
      }
      await load();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "任务操作失败");
    }
  }

  async function runStepRetry(stepId: number) {
    if (!task) {
      return;
    }
    try {
      setActionError("");
      await apiClient.retryTaskStep(task.id, stepId);
      await load();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "步骤重试失败");
    }
  }

  if (!taskId) {
    return (
      <Card>
        <h1>任务详情</h1>
        <p className="empty-state">未指定任务 ID。</p>
      </Card>
    );
  }

  return (
    <div className="page">
      {error ? <div className="alert">任务详情暂不可用：{error}</div> : null}
      {actionError ? <div className="alert">任务操作失败：{actionError}</div> : null}

      <Card>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Task Detail</span>
            <h1>任务详情</h1>
          </div>
          <div className="table-actions">
            <a className="text-link" href="#/tasks">
              返回队列
            </a>
            {task ? (
              <>
                <a className="icon-text-button" href={`#/videos/${task.id}`}>
                  <ExternalLink size={14} aria-hidden="true" />
                  <span>打开预览详情</span>
                </a>
                <button
                  className="icon-text-button"
                  type="button"
                  disabled={!canRetry(task)}
                  onClick={() => void runAction("retry")}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                  <span>重试任务</span>
                </button>
                <button
                  className="icon-text-button danger"
                  type="button"
                  disabled={!canCancel(task)}
                  onClick={() => void runAction("cancel")}
                >
                  <Square size={14} aria-hidden="true" />
                  <span>取消任务</span>
                </button>
              </>
            ) : null}
          </div>
        </div>
        {loading ? <p className="empty-state">加载中</p> : null}
        {task ? (
          <div className="detail-head">
            <div>
              <h2>{task.title}</h2>
              <p>{task.input}</p>
            </div>
            <Badge status={task.status} />
            <ProgressBar value={task.progress} />
            <div className="detail-meta">
              <span>来源：{task.source_type}</span>
              <span>当前步骤：{task.current_step || "-"}</span>
              <span>创建：{formatDate(task.created_at)}</span>
              <span>更新：{formatDate(task.updated_at)}</span>
            </div>
          </div>
        ) : null}
      </Card>

      {task ? (
        <div className="detail-grid">
          <Card className="detail-grid-span">
            <h2>处理步骤</h2>
            <StepTimeline
              steps={task.steps.filter((step) => !["upload_video", "upload_subtitle"].includes(step.name))}
              canRetryStep={(step) => canRetryStep(task, step)}
              onRetryStep={(step) => void runStepRetry(step.id)}
            />
          </Card>
        </div>
      ) : null}

      {task ? (
        <div className="detail-grid">
          <Card>
            <h2>产物</h2>
            <div className="artifact-list">
              {task.artifacts.map((artifact) => (
                <div className="artifact-row" key={artifact.id}>
                  <strong>{artifact.artifact_type}</strong>
                  <span>{artifact.path}</span>
                </div>
              ))}
            </div>
            {task.artifacts.length === 0 ? <p className="empty-state">暂无产物。</p> : null}
          </Card>

          <Card>
            <h2>日志</h2>
            <div className="log-list">
              {logs.map((log) => (
                <div className="log-row" key={log.id}>
                  <span>{log.level}</span>
                  <p>{log.message}</p>
                  <small>{formatDate(log.created_at)}</small>
                </div>
              ))}
            </div>
            {logs.length === 0 ? <p className="empty-state">暂无日志。</p> : null}
          </Card>
        </div>
      ) : null}
    </div>
  );
}
