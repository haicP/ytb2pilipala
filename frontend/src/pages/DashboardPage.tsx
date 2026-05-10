import { Cpu, Database, HardDrive, MemoryStick, Video } from "lucide-react";
import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { SystemMetrics, Task } from "../api/types";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ProgressBar } from "../components/ProgressBar";
import { TaskForm } from "../components/TaskForm";

function formatMetric(value: number | undefined, unit: string) {
  return typeof value === "number" ? `${value}${unit}` : "-";
}

function getFailedStepName(task: Task) {
  if (task.status !== "failed") {
    return "";
  }

  const failedStep = task.steps.find((step) => step.status === "failed");
  return failedStep?.label || task.current_step || "";
}

export function DashboardPage() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");

  async function load() {
    try {
      const [metricData, taskData] = await Promise.all([apiClient.metrics(), apiClient.tasks()]);
      setMetrics(metricData);
      setTasks(taskData.items);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "工作台数据加载失败");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const completed = tasks.filter((task) => task.status === "success").length;
  const running = tasks.filter((task) => task.status === "running").length;
  const uploaded = tasks.filter((task) => task.metadata?.upload_status === "success").length;

  return (
    <div className="dashboard-grid">
      {error ? <div className="alert">工作台数据暂不可用：{error}</div> : null}

      <Card className="dashboard-card-wide">
        <div className="section-heading">
          <div>
            <span className="eyebrow">System Overview</span>
            <h2>系统信息</h2>
          </div>
          <a className="text-link" href="#/settings">
            系统设置
          </a>
        </div>
        <p className="section-copy">这里只保留最常看的资源指标：磁盘剩余、CPU 占用、可用内存。</p>
        <div className="metric-grid">
          <div className="metric-card">
            <HardDrive size={20} aria-hidden="true" />
            <span>磁盘剩余</span>
            <strong>{formatMetric(metrics?.disk_free_gb, " GB")}</strong>
          </div>
          <div className="metric-card">
            <Cpu size={20} aria-hidden="true" />
            <span>CPU 占用</span>
            <strong>{formatMetric(metrics?.cpu_percent, "%")}</strong>
          </div>
          <div className="metric-card">
            <MemoryStick size={20} aria-hidden="true" />
            <span>可用内存</span>
            <strong>{formatMetric(metrics?.memory_available_gb, " GB")}</strong>
          </div>
        </div>
      </Card>

      <Card className="dashboard-card-wide">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Task Overview</span>
            <h2>任务概况</h2>
          </div>
          <a className="text-link" href="#/tasks">
            查看队列
          </a>
        </div>
        <div className="metric-grid metric-grid-4">
          <div className="metric-card">
            <Video size={20} aria-hidden="true" />
            <span>视频总数</span>
            <strong>{tasks.length}</strong>
          </div>
          <div className="metric-card">
            <Database size={20} aria-hidden="true" />
            <span>已完成</span>
            <strong>{completed}</strong>
          </div>
          <div className="metric-card">
            <Cpu size={20} aria-hidden="true" />
            <span>处理中</span>
            <strong>{running}</strong>
          </div>
          <div className="metric-card">
            <HardDrive size={20} aria-hidden="true" />
            <span>已上传 B 站</span>
            <strong>{uploaded}</strong>
          </div>
        </div>
      </Card>

      <Card className="dashboard-card-wide submit-panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Create Task</span>
            <h1>提交新视频</h1>
          </div>
        </div>
        <p className="section-copy">
          粘贴 YouTube 单视频、YouTube 播放列表或本地视频路径后会先加入任务队列，再按本次提交设置继续处理。
        </p>
        <TaskForm onCreated={load} />
      </Card>

      <Card>
        <div className="section-heading">
          <h2>最近处理</h2>
          <a className="text-link" href="#/tasks">
            全部任务
          </a>
        </div>
        {tasks.length === 0 ? <p className="empty-state">暂无视频，提交第一个链接开始。</p> : null}
        <div className="task-list">
          {tasks.slice(0, 5).map((task) => {
            const failedStepName = getFailedStepName(task);

            return (
              <a className="task-row" key={task.id} href={`#/tasks/${task.id}`}>
                <div>
                  <strong>{task.title}</strong>
                  <span>{task.input}</span>
                  {failedStepName ? <span className="task-row-error">失败步骤：{failedStepName}</span> : null}
                </div>
                <div className="task-row-meta">
                  <Badge status={task.status} />
                  <ProgressBar value={task.progress} />
                </div>
              </a>
            );
          })}
        </div>
      </Card>

      <Card>
        <h2>快捷入口</h2>
        <div className="quick-links">
          <a href="#/subscribe">YouTube 订阅</a>
          <a href="#/tasks">任务队列</a>
          <a href="#/videos">视频库</a>
          <a href="#/settings">系统设置</a>
        </div>
      </Card>
    </div>
  );
}
