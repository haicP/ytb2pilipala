import { CheckCircle2, CircleAlert, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { SettingsSummary, SettingsUpdatePayload } from "../api/types";
import { Card } from "../components/Card";

const TTS_PROVIDER_LABELS = {
  mimo_v2_5_tts: "MiMo-V2.5-TTS",
  openai: "OpenAI"
} as const;

const emptySettings: SettingsSummary = {
  dependencies: {},
  config: {},
  settings: {}
};

const emptyConnectionForm: SettingsUpdatePayload = {
  assistant_base_url: "",
  assistant_api_key: "",
  assistant_model_id: "",
  image_model_id: "gpt-image-2",
  tts_provider: "mimo_v2_5_tts",
  mimo_base_url: "",
  mimo_api_key: "",
  mimo_tts_model: "",
  mimo_tts_voice: "",
  mimo_tts_style_prompt: "",
  mimo_tts_concurrency: 10,
  tts_concurrency: 10,
  openai_tts_base_url: "https://api.openai.com/v1",
  openai_tts_api_key: "",
  openai_tts_model: "gpt-4o-mini-tts",
  openai_tts_voice: "alloy",
  openai_tts_instructions: "",
  openai_tts_speed: 1
};

function StatusLine({ label, value }: { label: string; value: boolean }) {
  const Icon = value ? CheckCircle2 : CircleAlert;

  return (
    <div className={`status-line ${value ? "ok" : "missing"}`}>
      <Icon size={18} aria-hidden="true" />
      <span>{label}</span>
      <strong>{value ? "已配置" : "未配置"}</strong>
    </div>
  );
}

function settingValue(settings: SettingsSummary, key: string, fallback: string) {
  return settings.settings[key] || fallback;
}

function providerValue(value: string): "mimo_v2_5_tts" | "openai" {
  return value === "openai" ? "openai" : "mimo_v2_5_tts";
}

function connectionFormFromSettings(settings: SettingsSummary): SettingsUpdatePayload {
  return {
    assistant_base_url: settingValue(settings, "assistant_base_url", ""),
    assistant_api_key: settingValue(settings, "assistant_api_key", ""),
    assistant_model_id: settingValue(settings, "assistant_model_id", ""),
    image_model_id: settingValue(settings, "image_model_id", "gpt-image-2"),
    tts_provider: providerValue(settingValue(settings, "tts_provider", "mimo_v2_5_tts")),
    mimo_base_url: settingValue(settings, "mimo_base_url", ""),
    mimo_api_key: settingValue(settings, "mimo_api_key", ""),
    mimo_tts_model: settingValue(settings, "mimo_tts_model", ""),
    mimo_tts_voice: settingValue(settings, "mimo_tts_voice", ""),
    mimo_tts_style_prompt: settingValue(settings, "mimo_tts_style_prompt", ""),
    mimo_tts_concurrency: Number(settingValue(settings, "mimo_tts_concurrency", "10")),
    tts_concurrency: Number(settingValue(settings, "tts_concurrency", settingValue(settings, "mimo_tts_concurrency", "10"))),
    openai_tts_base_url: settingValue(settings, "openai_tts_base_url", "https://api.openai.com/v1"),
    openai_tts_api_key: settingValue(settings, "openai_tts_api_key", ""),
    openai_tts_model: settingValue(settings, "openai_tts_model", "gpt-4o-mini-tts"),
    openai_tts_voice: settingValue(settings, "openai_tts_voice", "alloy"),
    openai_tts_instructions: settingValue(settings, "openai_tts_instructions", ""),
    openai_tts_speed: Number(settingValue(settings, "openai_tts_speed", "1"))
  };
}

export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsSummary>(emptySettings);
  const [connectionForm, setConnectionForm] = useState<SettingsUpdatePayload>(emptyConnectionForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const data = await apiClient.settings();
        setSettings(data);
        setConnectionForm(connectionFormFromSettings(data));
        setError("");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "系统设置加载失败");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  function updateField(field: keyof SettingsUpdatePayload, value: string) {
    const numericFields = new Set<keyof SettingsUpdatePayload>([
      "mimo_tts_concurrency",
      "tts_concurrency",
      "openai_tts_speed"
    ]);
    setConnectionForm((current) => ({
      ...current,
      [field]: numericFields.has(field) ? Number(value) : value
    }));
    setSaveMessage("");
  }

  function restoreSavedValues() {
    setConnectionForm(connectionFormFromSettings(settings));
    setSaveMessage("");
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setSaveMessage("");
    try {
      const updated = await apiClient.updateSettings(connectionForm);
      setSettings(updated);
      setConnectionForm(connectionFormFromSettings(updated));
      setError("");
      setSaveMessage("配置已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "系统设置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <Card>
        <div className="section-heading">
          <div>
            <span className="eyebrow">System Settings</span>
            <h1>系统设置</h1>
          </div>
          <SlidersHorizontal size={20} aria-hidden="true" />
        </div>
        <p className="section-copy">连接配置和 TTS 配置优先读取这里的保存值；环境变量继续作为保底回退。</p>
      </Card>

      {error ? <div className="alert">系统设置暂不可用：{error}</div> : null}
      {loading ? <p className="empty-state">加载系统设置...</p> : null}

      <div className="settings-grid">
        <Card className="settings-grid-wide">
          <form className="assistant-form" onSubmit={saveSettings}>
            <div className="section-heading compact">
              <div>
                <span className="eyebrow">Connections</span>
                <h2>连接与 TTS 配置</h2>
              </div>
              <div className="form-actions">
                <button className="button secondary" type="button" onClick={restoreSavedValues} disabled={loading || saving}>
                  <RotateCcw size={16} aria-hidden="true" />
                  恢复已保存
                </button>
                <button className="button" type="submit" disabled={loading || saving}>
                  <Save size={16} aria-hidden="true" />
                  {saving ? "保存中..." : "保存配置"}
                </button>
              </div>
            </div>

            <div className="settings-form-grid">
              <div className="prompt-template prompt-template-compact">
                <span>LLM 连接</span>
                <small>用于字幕翻译和投稿信息生成，界面保存值优先于 `.env`。</small>
                <label className="prompt-inline-field">
                  <span>LLM API Base URL</span>
                  <input
                    aria-label="LLM API Base URL"
                    className="input"
                    value={connectionForm.assistant_base_url ?? ""}
                    onChange={(event) => updateField("assistant_base_url", event.target.value)}
                  />
                </label>
                <label className="prompt-inline-field">
                  <span>LLM API Key</span>
                  <input
                    aria-label="LLM API Key"
                    className="input"
                    value={connectionForm.assistant_api_key ?? ""}
                    onChange={(event) => updateField("assistant_api_key", event.target.value)}
                  />
                </label>
                <label className="prompt-inline-field">
                  <span>LLM 模型 ID</span>
                  <input
                    aria-label="LLM 模型 ID"
                    className="input"
                    value={connectionForm.assistant_model_id ?? ""}
                    onChange={(event) => updateField("assistant_model_id", event.target.value)}
                  />
                </label>
                <label className="prompt-inline-field">
                  <span>图片模型 ID</span>
                  <input
                    aria-label="图片模型 ID"
                    className="input"
                    value={connectionForm.image_model_id ?? ""}
                    onChange={(event) => updateField("image_model_id", event.target.value)}
                  />
                </label>
              </div>

              <div className="prompt-template prompt-template-compact">
                <span>TTS 连接</span>
                <small>
                  当前使用 {TTS_PROVIDER_LABELS[connectionForm.tts_provider ?? "mimo_v2_5_tts"]}；切换提供商不会清空另一组配置。
                </small>
                <label className="prompt-inline-field">
                  <span>TTS 接口提供商</span>
                  <select
                    aria-label="TTS 接口提供商"
                    className="input"
                    value={connectionForm.tts_provider ?? "mimo_v2_5_tts"}
                    onChange={(event) => updateField("tts_provider", event.target.value)}
                  >
                    <option value="mimo_v2_5_tts">MiMo-V2.5-TTS</option>
                    <option value="openai">OpenAI</option>
                  </select>
                </label>
                <label className="prompt-inline-field">
                  <span>TTS 并发数</span>
                  <input
                    aria-label="TTS 并发数"
                    className="input"
                    min={1}
                    max={50}
                    type="number"
                    value={connectionForm.tts_concurrency ?? connectionForm.mimo_tts_concurrency ?? 10}
                    onChange={(event) => updateField("tts_concurrency", event.target.value)}
                  />
                </label>

                {connectionForm.tts_provider === "openai" ? (
                  <>
                    <label className="prompt-inline-field">
                      <span>OpenAI TTS Base URL</span>
                      <input
                        aria-label="OpenAI TTS Base URL"
                        className="input"
                        value={connectionForm.openai_tts_base_url ?? ""}
                        onChange={(event) => updateField("openai_tts_base_url", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>OpenAI TTS API Key</span>
                      <input
                        aria-label="OpenAI TTS API Key"
                        className="input"
                        value={connectionForm.openai_tts_api_key ?? ""}
                        onChange={(event) => updateField("openai_tts_api_key", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>OpenAI TTS 模型 ID</span>
                      <input
                        aria-label="OpenAI TTS 模型 ID"
                        className="input"
                        value={connectionForm.openai_tts_model ?? ""}
                        onChange={(event) => updateField("openai_tts_model", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>OpenAI TTS 音色</span>
                      <input
                        aria-label="OpenAI TTS 音色"
                        className="input"
                        value={connectionForm.openai_tts_voice ?? ""}
                        onChange={(event) => updateField("openai_tts_voice", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>OpenAI TTS 语速</span>
                      <input
                        aria-label="OpenAI TTS 语速"
                        className="input"
                        min={0.25}
                        max={4}
                        step={0.05}
                        type="number"
                        value={connectionForm.openai_tts_speed ?? 1}
                        onChange={(event) => updateField("openai_tts_speed", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>OpenAI TTS 说明词</span>
                      <textarea
                        aria-label="OpenAI TTS 说明词"
                        className="textarea"
                        value={connectionForm.openai_tts_instructions ?? ""}
                        onChange={(event) => updateField("openai_tts_instructions", event.target.value)}
                      />
                    </label>
                  </>
                ) : (
                  <>
                    <label className="prompt-inline-field">
                      <span>TTS Base URL</span>
                      <input
                        aria-label="TTS Base URL"
                        className="input"
                        value={connectionForm.mimo_base_url ?? ""}
                        onChange={(event) => updateField("mimo_base_url", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>TTS API Key</span>
                      <input
                        aria-label="TTS API Key"
                        className="input"
                        value={connectionForm.mimo_api_key ?? ""}
                        onChange={(event) => updateField("mimo_api_key", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>TTS 模型 ID</span>
                      <input
                        aria-label="TTS 模型 ID"
                        className="input"
                        value={connectionForm.mimo_tts_model ?? ""}
                        onChange={(event) => updateField("mimo_tts_model", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>TTS 音色</span>
                      <input
                        aria-label="TTS 音色"
                        className="input"
                        value={connectionForm.mimo_tts_voice ?? ""}
                        onChange={(event) => updateField("mimo_tts_voice", event.target.value)}
                      />
                    </label>
                    <label className="prompt-inline-field">
                      <span>TTS 风格提示词</span>
                      <textarea
                        aria-label="TTS 风格提示词"
                        className="textarea"
                        value={connectionForm.mimo_tts_style_prompt ?? ""}
                        onChange={(event) => updateField("mimo_tts_style_prompt", event.target.value)}
                      />
                    </label>
                  </>
                )}
              </div>
            </div>

            {saveMessage ? <p className="form-note">{saveMessage}</p> : null}
          </form>
        </Card>

        <Card>
          <h2>依赖状态</h2>
          <div className="status-list">
            <StatusLine label="yt-dlp" value={Boolean(settings.dependencies.yt_dlp)} />
            <StatusLine label="ffmpeg" value={Boolean(settings.dependencies.ffmpeg)} />
          </div>
        </Card>

        <Card>
          <h2>AI 与账号配置</h2>
          <div className="status-list">
            <StatusLine label="LLM Base URL" value={Boolean(settings.config.api2key_base_url)} />
            <StatusLine label="LLM Key" value={Boolean(settings.config.llm_key)} />
            <StatusLine label="TTS Base URL" value={Boolean(settings.config.tts_base_url)} />
            <StatusLine label="TTS API Key" value={Boolean(settings.config.tts_api_key)} />
            <StatusLine
              label="B 站凭据来源"
              value={Boolean(settings.config.bilibili_credential_source)}
            />
            <StatusLine
              label="YouTube cookies.txt"
              value={Boolean(settings.config.youtube_cookies_file)}
            />
          </div>
        </Card>

        <Card className="settings-grid-wide">
          <h2>运行参数</h2>
          <div className="settings-summary-grid">
            <div className="setting-kv">
              <span>默认分区</span>
              <strong>{settingValue(settings, "default_category", "未设置")}</strong>
            </div>
            <div className="setting-kv">
              <span>dry-run 步骤延时</span>
              <strong>{settingValue(settings, "dry_run_step_delay_ms", "0")} ms</strong>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
