import { RotateCcw, Save, WandSparkles } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { apiClient } from "../api/client";
import type { AssistantSettings } from "../api/types";
import { Card } from "../components/Card";

type PromptTemplateForm = {
  postprocess_prompt: string;
  translation_prompt: string;
  metadata_prompt: string;
};

const promptFields = [
  {
    key: "postprocess_prompt",
    label: "转写后处理提示词",
    description: "用于清理 ASR 输出、修正断句、保留术语和生成可翻译字幕。"
  },
  {
    key: "translation_prompt",
    label: "字幕翻译提示词",
    description: "用于将源语言字幕翻译为中文，并控制语气、术语和字幕长度。"
  },
  {
    key: "metadata_prompt",
    label: "投稿信息生成提示词",
    description: "用于生成 B 站标题、简介、标签和投稿定位。"
  }
] as const;

const emptyPromptForm: PromptTemplateForm = {
  postprocess_prompt: "",
  translation_prompt: "",
  metadata_prompt: ""
};

function promptFormFromSettings(settings: AssistantSettings): PromptTemplateForm {
  return {
    postprocess_prompt: settings.postprocess_prompt,
    translation_prompt: settings.translation_prompt,
    metadata_prompt: settings.metadata_prompt
  };
}

function defaultsFromSettings(settings: AssistantSettings | null): PromptTemplateForm {
  return {
    postprocess_prompt: settings?.defaults.postprocess_prompt ?? "",
    translation_prompt: settings?.defaults.translation_prompt ?? "",
    metadata_prompt: settings?.defaults.metadata_prompt ?? ""
  };
}

export function AssistantPage() {
  const [assistantSettings, setAssistantSettings] = useState<AssistantSettings | null>(null);
  const [promptForm, setPromptForm] = useState<PromptTemplateForm>(emptyPromptForm);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");

  async function load() {
    try {
      const assistantData = await apiClient.assistantSettings();
      setAssistantSettings(assistantData);
      setPromptForm(promptFormFromSettings(assistantData));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 配置加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function updatePrompt(field: keyof PromptTemplateForm, value: string) {
    setPromptForm((current) => ({
      ...current,
      [field]: value
    }));
    setSaveMessage("");
  }

  function restoreDefaults() {
    setPromptForm(defaultsFromSettings(assistantSettings));
    setSaveMessage("");
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setSaveMessage("");
    try {
      const updatedSettings = await apiClient.updateAssistantSettings({
        base_url: assistantSettings?.base_url ?? "",
        api_key: assistantSettings?.api_key ?? "",
        model_id: assistantSettings?.model_id ?? "",
        ...promptForm
      });
      setAssistantSettings(updatedSettings);
      setPromptForm(promptFormFromSettings(updatedSettings));
      setError("");
      setSaveMessage("配置已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI 配置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <Card>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Assistant Settings</span>
            <h1>AI 配置</h1>
          </div>
          <WandSparkles size={20} aria-hidden="true" />
        </div>
        <p className="section-copy">
          这里只管理工作流中的提示词模板。连接配置、TTS 参数和系统依赖状态已统一归入设置页。
        </p>
      </Card>

      {error ? <div className="alert">AI 配置暂不可用：{error}</div> : null}
      {loading ? <p className="empty-state">加载 AI 配置...</p> : null}

      <div className="assistant-grid assistant-grid-single">
        <Card className="assistant-form-card">
          <form className="assistant-form" onSubmit={saveSettings}>
            <div className="section-heading compact">
              <div>
                <span className="eyebrow">Prompt Templates</span>
                <h2>提示词模板</h2>
              </div>
              <div className="form-actions">
                <button className="button secondary" type="button" onClick={restoreDefaults} disabled={loading || saving}>
                  <RotateCcw size={16} aria-hidden="true" />
                  恢复默认
                </button>
                <button className="button" type="submit" disabled={loading || saving}>
                  <Save size={16} aria-hidden="true" />
                  {saving ? "保存中..." : "保存配置"}
                </button>
              </div>
            </div>

            <div className="prompt-template-list">
              {promptFields.map((field) => (
                <label className="prompt-template" key={field.key}>
                  <span>{field.label}</span>
                  <small>{field.description}</small>
                  <textarea
                    aria-label={field.label}
                    className="textarea"
                    value={promptForm[field.key]}
                    onChange={(event) => updatePrompt(field.key, event.target.value)}
                  />
                </label>
              ))}
            </div>

            {saveMessage ? <p className="form-note">{saveMessage}</p> : null}
          </form>
        </Card>
      </div>
    </div>
  );
}
