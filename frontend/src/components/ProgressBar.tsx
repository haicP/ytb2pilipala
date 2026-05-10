export function ProgressBar({ value }: { value: number }) {
  const normalized = Math.max(0, Math.min(100, Math.round(value)));

  return (
    <div
      className="progress-track"
      aria-label={`进度 ${normalized}%`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={normalized}
      role="progressbar"
    >
      <div className="progress-fill" style={{ width: `${normalized}%` }} />
    </div>
  );
}
