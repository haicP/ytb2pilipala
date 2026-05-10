import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AssistantPage } from "../pages/AssistantPage";

const apiMock = vi.hoisted(() => ({
  assistantSettings: vi.fn(),
  updateAssistantSettings: vi.fn()
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

const assistantSettings = {
  base_url: "https://api.example.com/v1",
  api_key: "sk-test-key",
  model_id: "gpt-custom-1",
  postprocess_prompt: "清理转写文本，修正断句。",
  translation_prompt: "翻译为自然中文。",
  metadata_prompt: "生成 B 站投稿标题、简介和标签。",
  defaults: {
    postprocess_prompt: "默认转写后处理提示词",
    translation_prompt: "默认字幕翻译提示词",
    metadata_prompt: "默认投稿信息提示词"
  },
  updated_at: "2026-05-04T10:00:00Z"
};

beforeEach(() => {
  apiMock.assistantSettings.mockResolvedValue(assistantSettings);
  apiMock.updateAssistantSettings.mockResolvedValue(assistantSettings);
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("AssistantPage", () => {
  test("renders only prompt template configuration", async () => {
    render(<AssistantPage />);

    expect(await screen.findByRole("heading", { name: "AI 配置" })).toBeInTheDocument();
    expect(screen.getByLabelText("转写后处理提示词")).toHaveValue(assistantSettings.postprocess_prompt);
    expect(screen.getByLabelText("字幕翻译提示词")).toHaveValue(assistantSettings.translation_prompt);
    expect(screen.getByLabelText("投稿信息生成提示词")).toHaveValue(assistantSettings.metadata_prompt);
    expect(screen.queryByLabelText("API Base URL")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("模型 ID")).not.toBeInTheDocument();
    expect(screen.queryByText("系统依赖状态")).not.toBeInTheDocument();
    expect(screen.queryByText("连接配置")).not.toBeInTheDocument();
  });

  test("saves edited assistant configuration", async () => {
    render(<AssistantPage />);

    const translationPrompt = await screen.findByLabelText("字幕翻译提示词");
    fireEvent.change(translationPrompt, { target: { value: "翻译字幕，保留专有名词。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      expect(apiMock.updateAssistantSettings).toHaveBeenCalledWith({
        base_url: assistantSettings.base_url,
        api_key: assistantSettings.api_key,
        model_id: assistantSettings.model_id,
        postprocess_prompt: assistantSettings.postprocess_prompt,
        translation_prompt: "翻译字幕，保留专有名词。",
        metadata_prompt: assistantSettings.metadata_prompt
      });
    });
  });

  test("saving prompt templates does not request system settings", async () => {
    render(<AssistantPage />);

    await screen.findByRole("heading", { name: "AI 配置" });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() => expect(apiMock.updateAssistantSettings).toHaveBeenCalledTimes(1));
    expect(apiMock.assistantSettings).toHaveBeenCalledTimes(1);
  });
});
