import { ChevronDown, RotateCcw, Send, Settings } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";

import { apiClient } from "../api/client";

type Resolution = "auto" | "1080p" | "720p";

type EnabledSteps = {
  download_thumbnail: boolean;
  transcribe: boolean;
  translate: boolean;
  synthesize_voice: boolean;
};

const defaultSteps: EnabledSteps = {
  download_thumbnail: true,
  transcribe: true,
  translate: true,
  synthesize_voice: true
};

const stepOptions: Array<{
  key: keyof EnabledSteps;
  label: string;
  description: string;
}> = [
  {
    key: "download_thumbnail",
    label: "下载缩略图",
    description: "保存视频封面，方便后续展示和上传。"
  },
  {
    key: "transcribe",
    label: "转录字幕",
    description: "提取音频并生成时间轴字幕，关闭后会跳过翻译和配音。"
  },
  {
    key: "translate",
    label: "AI 翻译字幕",
    description: "将字幕翻译为中文结果，并生成翻译版 SRT。"
  },
  {
    key: "synthesize_voice",
    label: "合成字幕配音",
    description: "为中文字幕生成 TTS 音频，依赖转录和翻译。"
  }
];

function enabledStepCount(steps: EnabledSteps) {
  return Object.values(steps).filter(Boolean).length;
}

export function TaskForm({ onCreated }: { onCreated: () => void }) {
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [resolution, setResolution] = useState<Resolution>("auto");
  const [playlistEnabled, setPlaylistEnabled] = useState(false);
  const [playlistStart, setPlaylistStart] = useState(1);
  const [playlistLimit, setPlaylistLimit] = useState(10);
  const [enabledSteps, setEnabledSteps] = useState<EnabledSteps>(defaultSteps);
  const trimmedInput = input.trim();
  const activeSteps = enabledStepCount(enabledSteps);
  const settingsSummary =
    resolution === "auto" && !playlistEnabled && activeSteps === stepOptions.length ? "自动最佳" : "已自定义";

  function resetTaskSettings() {
    setResolution("auto");
    setPlaylistEnabled(false);
    setPlaylistStart(1);
    setPlaylistLimit(10);
    setEnabledSteps(defaultSteps);
  }

  function updateStep(step: keyof EnabledSteps, checked: boolean) {
    setEnabledSteps((current) => {
      const next = { ...current, [step]: checked };
      if (step === "transcribe" && !checked) {
        next.translate = false;
        next.synthesize_voice = false;
      }
      if (step === "translate" && !checked) {
        next.synthesize_voice = false;
      }
      if (step === "translate" && checked) {
        next.transcribe = true;
      }
      if (step === "synthesize_voice" && checked) {
        next.transcribe = true;
        next.translate = true;
      }
      return next;
    });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedInput || submitting) {
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const sourceType = /^https?:\/\//i.test(trimmedInput) ? "youtube" : "local";
      await apiClient.createTask({
        source_type: sourceType,
        input: trimmedInput,
        options: {
          download_resolution: resolution,
          playlist: {
            enabled: playlistEnabled,
            start_index: playlistStart,
            max_items: playlistLimit
          },
          enabled_steps: enabledSteps
        }
      });
      setInput("");
      onCreated();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="task-form" onSubmit={submit}>
      <div className="task-form-row">
        <label className="sr-only" htmlFor="task-input">
          YouTube 链接或本地视频路径
        </label>
        <input
          className="input"
          id="task-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="https://www.youtube.com/watch?v=... / playlist?list=... / /path/to/local.mp4"
        />
        <button
          aria-expanded={settingsOpen}
          aria-controls="task-submit-settings"
          className="button secondary task-settings-button"
          type="button"
          onClick={() => setSettingsOpen((current) => !current)}
        >
          <Settings size={16} aria-hidden="true" />
          <span>设置</span>
          <ChevronDown className={settingsOpen ? "chevron-open" : ""} size={14} aria-hidden="true" />
        </button>
        <button className="button" type="submit" disabled={submitting || !trimmedInput}>
          <Send size={16} aria-hidden="true" />
          <span>{submitting ? "提交中" : "提交"}</span>
        </button>
      </div>
      {settingsOpen ? (
        <div className="task-settings-panel" id="task-submit-settings">
          <div className="task-settings-panel-head">
            <strong>提交设置</strong>
            <button className="text-link reset-button" type="button" onClick={resetTaskSettings}>
              <RotateCcw size={14} aria-hidden="true" />
              <span>恢复默认</span>
            </button>
          </div>
          <div className="task-settings-grid">
            <section className="task-setting-box">
              <label htmlFor="task-resolution">下载分辨率</label>
              <small>优先按该分辨率筛选视频格式。</small>
              <select
                className="input"
                id="task-resolution"
                value={resolution}
                onChange={(event) => setResolution(event.target.value as Resolution)}
              >
                <option value="auto">自动最佳</option>
                <option value="1080p">1080p 优先</option>
                <option value="720p">720p 保底</option>
              </select>
              <p>实际下载会拒绝低于 720p 的格式，即使选了更低分辨率选项。</p>
            </section>
            <section className="task-setting-box">
              <div className="setting-inline-head">
                <div>
                  <strong>播放列表批量提交</strong>
                  <small>开启后，YouTube 播放列表会被拆分成多条独立任务入队。</small>
                </div>
                <label className="switch-label">
                  <input
                    checked={playlistEnabled}
                    onChange={(event) => setPlaylistEnabled(event.target.checked)}
                    type="checkbox"
                  />
                  <span>启用</span>
                </label>
              </div>
              <div className="playlist-grid">
                <label>
                  <span>起始序号</span>
                  <input
                    className="input"
                    disabled={!playlistEnabled}
                    min={1}
                    max={50}
                    type="number"
                    value={playlistStart}
                    onChange={(event) => setPlaylistStart(Number(event.target.value))}
                  />
                </label>
                <label>
                  <span>最多导入</span>
                  <input
                    className="input"
                    disabled={!playlistEnabled}
                    min={1}
                    max={50}
                    type="number"
                    value={playlistLimit}
                    onChange={(event) => setPlaylistLimit(Number(event.target.value))}
                  />
                </label>
              </div>
              <p>后端最大保护上限为 50 条，避免一次性创建过多任务。</p>
            </section>
            <section className="task-setting-box task-chain-box">
              <div className="setting-inline-head">
                <div>
                  <strong>任务链</strong>
                  <small>按需关闭可选步骤，保留最小链路。</small>
                </div>
                <span className="task-chain-count">{activeSteps} / {stepOptions.length}</span>
              </div>
              <div className="task-step-options">
                {stepOptions.map((step) => (
                  <label className="task-step-option" key={step.key}>
                    <input
                      aria-label={step.label}
                      checked={enabledSteps[step.key]}
                      onChange={(event) => updateStep(step.key, event.target.checked)}
                      type="checkbox"
                    />
                    <span>
                      <strong>{step.label}</strong>
                      <small>{step.description}</small>
                    </span>
                  </label>
                ))}
              </div>
            </section>
          </div>
          <p className="task-settings-note">
            配音细节统一在设置页维护；当前页面仅控制下载分辨率、播放列表批量提交和任务链开关。
          </p>
        </div>
      ) : null}
      <div className="pill-row" aria-label="当前任务提交设置">
        <span>{settingsSummary}</span>
        {stepOptions
          .filter((step) => enabledSteps[step.key])
          .map((step) => (
            <span key={step.key}>{step.label}</span>
          ))}
      </div>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
