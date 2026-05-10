import type { Status } from "../api/types";

const labels: Record<Status, string> = {
  pending: "等待中",
  running: "处理中",
  success: "已完成",
  failed: "失败",
  skipped: "已跳过",
  cancelled: "已取消"
};

export function Badge({ status }: { status: Status }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>;
}
