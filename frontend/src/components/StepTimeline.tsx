import { RotateCcw } from "lucide-react";
import type { TaskStep } from "../api/types";
import { Badge } from "./Badge";
import { ProgressBar } from "./ProgressBar";

interface StepTimelineProps {
  steps: TaskStep[];
  canRetryStep?: (step: TaskStep) => boolean;
  onRetryStep?: (step: TaskStep) => void;
}

export function StepTimeline({ steps, canRetryStep, onRetryStep }: StepTimelineProps) {
  if (steps.length === 0) {
    return <p className="empty-state">暂无步骤记录。</p>;
  }

  return (
    <div className="step-timeline">
      {steps.map((step) => (
        <div className="step-item" key={step.id}>
          <div className="step-title">
            <strong>
              {step.order}. {step.label}
            </strong>
            <span>{step.name}</span>
          </div>
          <Badge status={step.status} />
          <ProgressBar value={step.progress} />
          <div className="step-meta">
            <span>重试 {step.retry_count}</span>
            <span>{step.started_at ? `开始 ${new Date(step.started_at).toLocaleString()}` : "未开始"}</span>
            <span>{step.finished_at ? `完成 ${new Date(step.finished_at).toLocaleString()}` : "未完成"}</span>
          </div>
          {onRetryStep ? (
            <div className="step-actions">
              <button
                aria-label={`重试步骤 ${step.label}`}
                className="icon-text-button step-retry-button"
                type="button"
                disabled={canRetryStep ? !canRetryStep(step) : false}
                onClick={() => onRetryStep(step)}
              >
                <RotateCcw size={14} aria-hidden="true" />
                <span>重试此步骤</span>
              </button>
            </div>
          ) : null}
          {step.error_message ? <p className="error-text">{step.error_message}</p> : null}
        </div>
      ))}
    </div>
  );
}
