import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { SettingsPage } from "../pages/SettingsPage";

const apiMock = vi.hoisted(() => ({
  settings: vi.fn(),
  updateSettings: vi.fn()
}));

vi.mock("../api/client", () => ({
  apiClient: apiMock
}));

beforeEach(() => {
  apiMock.settings.mockResolvedValue({
    dependencies: {
      yt_dlp: true,
      ffmpeg: false
    },
    config: {
      api2key_base_url: true,
      llm_key: false,
      tts_base_url: true,
      tts_api_key: false,
      bilibili_credential_source: true,
      youtube_cookies_file: true
    },
    settings: {
      assistant_base_url: "https://saved-llm.example.com/v1",
      assistant_api_key: "sk-llm-saved",
      assistant_model_id: "gpt-4.1-mini",
      image_model_id: "gpt-image-2",
      tts_provider: "mimo_v2_5_tts",
      mimo_base_url: "https://saved-tts.example.com/v1",
      mimo_api_key: "sk-tts-saved",
      mimo_tts_model: "mimo-v2.5-tts",
      mimo_tts_voice: "冰糖",
      mimo_tts_style_prompt: "请自然朗读。",
      mimo_tts_concurrency: "8",
      tts_concurrency: "8",
      openai_tts_base_url: "https://api.openai.com/v1",
      openai_tts_api_key: "sk-openai-saved",
      openai_tts_model: "gpt-4o-mini-tts",
      openai_tts_voice: "alloy",
      openai_tts_instructions: "请使用清晰自然的中文解说语气。",
      openai_tts_speed: "1",
      default_category: "科技",
      dry_run_step_delay_ms: "50"
    }
  });
  apiMock.updateSettings.mockResolvedValue({
    dependencies: {
      yt_dlp: true,
      ffmpeg: false
    },
    config: {
      api2key_base_url: true,
      llm_key: true,
      tts_base_url: true,
      tts_api_key: true,
      bilibili_credential_source: true,
      youtube_cookies_file: true
    },
    settings: {
      assistant_base_url: "https://saved-llm.example.com/v1",
      assistant_api_key: "sk-llm-updated",
      assistant_model_id: "gpt-4.1",
      image_model_id: "gpt-image-2",
      tts_provider: "openai",
      mimo_base_url: "https://saved-tts.example.com/v1",
      mimo_api_key: "sk-tts-updated",
      mimo_tts_model: "mimo-v3-tts",
      mimo_tts_voice: "知性女声",
      mimo_tts_style_prompt: "请更自然地解说。",
      mimo_tts_concurrency: "12",
      tts_concurrency: "12",
      openai_tts_base_url: "https://api.openai.com/v1",
      openai_tts_api_key: "sk-openai-updated",
      openai_tts_model: "gpt-4o-mini-tts",
      openai_tts_voice: "verse",
      openai_tts_instructions: "请更自然地解说。",
      openai_tts_speed: "1.15",
      default_category: "科技",
      dry_run_step_delay_ms: "50"
    }
  });
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("SettingsPage", () => {
  test("renders dependency, connection, and TTS configuration in settings", async () => {
    render(<SettingsPage />);

    expect(await screen.findByRole("heading", { name: "系统设置" })).toBeInTheDocument();
    expect(screen.getByText("yt-dlp")).toBeInTheDocument();
    expect(screen.getByText("ffmpeg")).toBeInTheDocument();
    expect(screen.getByText("LLM Base URL")).toBeInTheDocument();
    expect(screen.getByLabelText("LLM API Base URL")).toBeInTheDocument();
    expect(screen.getByText("LLM Key")).toBeInTheDocument();
    expect(screen.getByLabelText("TTS 接口提供商")).toHaveValue("mimo_v2_5_tts");
    expect(screen.getAllByText("TTS Base URL")).toHaveLength(2);
    expect(screen.getAllByText("TTS API Key")).toHaveLength(2);
    expect(screen.getByText("B 站凭据来源")).toBeInTheDocument();
    expect(screen.getByText("YouTube cookies.txt")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://saved-llm.example.com/v1")).toBeInTheDocument();
    expect(screen.getByDisplayValue("sk-llm-saved")).toBeInTheDocument();
    expect(screen.getByDisplayValue("gpt-4.1-mini")).toBeInTheDocument();
    expect(screen.getByDisplayValue("gpt-image-2")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://saved-tts.example.com/v1")).toBeInTheDocument();
    expect(screen.getByDisplayValue("sk-tts-saved")).toBeInTheDocument();
    expect(screen.getByDisplayValue("mimo-v2.5-tts")).toBeInTheDocument();
    expect(screen.getByDisplayValue("冰糖")).toBeInTheDocument();
    expect(screen.getByDisplayValue("请自然朗读。")).toBeInTheDocument();
    expect(screen.getByLabelText("TTS 并发数")).toHaveValue(8);
    expect(screen.queryByLabelText("OpenAI TTS API Key")).not.toBeInTheDocument();
    expect(screen.getByText("科技")).toBeInTheDocument();
    expect(screen.getByText("50 ms")).toBeInTheDocument();
  });

  test("saves connection and TTS overrides from settings page", async () => {
    render(<SettingsPage />);

    fireEvent.change(await screen.findByLabelText("LLM API Key"), { target: { value: "sk-llm-updated" } });
    fireEvent.change(screen.getByLabelText("LLM 模型 ID"), { target: { value: "gpt-4.1" } });
    fireEvent.change(screen.getByLabelText("图片模型 ID"), { target: { value: "gpt-image-2" } });
    fireEvent.change(screen.getByLabelText("TTS API Key"), { target: { value: "sk-tts-updated" } });
    fireEvent.change(screen.getByLabelText("TTS 模型 ID"), { target: { value: "mimo-v3-tts" } });
    fireEvent.change(screen.getByLabelText("TTS 音色"), { target: { value: "知性女声" } });
    fireEvent.change(screen.getByLabelText("TTS 并发数"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("TTS 风格提示词"), { target: { value: "请更自然地解说。" } });
    fireEvent.change(screen.getByLabelText("TTS 接口提供商"), { target: { value: "openai" } });
    fireEvent.change(screen.getByLabelText("OpenAI TTS API Key"), { target: { value: "sk-openai-updated" } });
    fireEvent.change(screen.getByLabelText("OpenAI TTS 音色"), { target: { value: "verse" } });
    fireEvent.change(screen.getByLabelText("OpenAI TTS 语速"), { target: { value: "1.15" } });
    fireEvent.change(screen.getByLabelText("OpenAI TTS 说明词"), { target: { value: "请更自然地解说。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      expect(apiMock.updateSettings).toHaveBeenCalledWith({
        assistant_base_url: "https://saved-llm.example.com/v1",
        assistant_api_key: "sk-llm-updated",
        assistant_model_id: "gpt-4.1",
        image_model_id: "gpt-image-2",
        tts_provider: "openai",
        mimo_base_url: "https://saved-tts.example.com/v1",
        mimo_api_key: "sk-tts-updated",
        mimo_tts_model: "mimo-v3-tts",
        mimo_tts_voice: "知性女声",
        mimo_tts_style_prompt: "请更自然地解说。",
        mimo_tts_concurrency: 8,
        tts_concurrency: 12,
        openai_tts_base_url: "https://api.openai.com/v1",
        openai_tts_api_key: "sk-openai-updated",
        openai_tts_model: "gpt-4o-mini-tts",
        openai_tts_voice: "verse",
        openai_tts_instructions: "请更自然地解说。",
        openai_tts_speed: 1.15
      });
    });
  });

  test("keeps provider-specific values when switching TTS provider", async () => {
    render(<SettingsPage />);

    fireEvent.change(await screen.findByLabelText("TTS 模型 ID"), { target: { value: "mimo-v3-tts" } });
    fireEvent.change(screen.getByLabelText("TTS 接口提供商"), { target: { value: "openai" } });
    fireEvent.change(screen.getByLabelText("OpenAI TTS API Key"), { target: { value: "sk-openai-edited" } });
    fireEvent.change(screen.getByLabelText("TTS 接口提供商"), { target: { value: "mimo_v2_5_tts" } });

    expect(screen.getByLabelText("TTS 模型 ID")).toHaveValue("mimo-v3-tts");

    fireEvent.change(screen.getByLabelText("TTS 接口提供商"), { target: { value: "openai" } });

    expect(screen.getByLabelText("OpenAI TTS API Key")).toHaveValue("sk-openai-edited");
  });
});
