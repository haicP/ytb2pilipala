import type {
  AccountBinding,
  AccountBindingListResponse,
  BilibiliUploadPayload,
  AssistantSettings,
  AssistantSettingsUpdatePayload,
  BilibiliQrCodePollResponse,
  BilibiliQrCodeResponse,
  CoverGenerationPayload,
  CreateTaskPayload,
  LogListResponse,
  MetadataUpdatePayload,
  SettingsSummary,
  SettingsUpdatePayload,
  SubscriptionChannel,
  SubscriptionChannelListResponse,
  SubscriptionVideo,
  SubscriptionVideoListResponse,
  SystemMetrics,
  Task,
  TaskListResponse
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(path, {
    headers: isFormData
      ? init?.headers
      : {
          "Content-Type": "application/json",
          ...(init?.headers ?? {})
        },
    ...init
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.text();
}

export const apiClient = {
  metrics: () => request<SystemMetrics>("/api/system/metrics"),
  accounts: () => request<AccountBindingListResponse>("/api/accounts"),
  createBilibiliQrCode: () =>
    request<BilibiliQrCodeResponse>("/api/accounts/bilibili/qrcode", {
      method: "POST"
    }),
  pollBilibiliQrCode: (loginSessionId: string) =>
    request<BilibiliQrCodePollResponse>(`/api/accounts/bilibili/qrcode/${loginSessionId}/poll`, {
      method: "POST"
    }),
  unbindAccount: (accountId: number) =>
    request<AccountBinding>(`/api/accounts/${accountId}/unbind`, {
      method: "POST"
    }),
  settings: () => request<SettingsSummary>("/api/settings"),
  updateSettings: (payload: SettingsUpdatePayload) =>
    request<SettingsSummary>("/api/settings", {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  assistantSettings: () => request<AssistantSettings>("/api/assistant/settings"),
  updateAssistantSettings: (payload: AssistantSettingsUpdatePayload) =>
    request<AssistantSettings>("/api/assistant/settings", {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  tasks: (params?: { status_filter?: string; source_type?: string; keyword?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.status_filter) {
      searchParams.set("status_filter", params.status_filter);
    }
    if (params?.source_type) {
      searchParams.set("source_type", params.source_type);
    }
    if (params?.keyword) {
      searchParams.set("keyword", params.keyword);
    }
    const query = searchParams.toString();
    const path = query ? `/api/tasks?${query}` : "/api/tasks";
    return request<TaskListResponse>(path);
  },
  task: (taskId: number) => request<Task>(`/api/tasks/${taskId}`),
  videos: () => request<TaskListResponse>("/api/videos"),
  videoArtifactUrl: (taskId: number, artifactId: number) => `/api/videos/${taskId}/artifacts/${artifactId}`,
  videoArtifactText: (taskId: number, artifactId: number) =>
    requestText(`/api/videos/${taskId}/artifacts/${artifactId}`),
  logs: (taskId: number, params?: { limit?: number; offset?: number }) => {
    const searchParams = new URLSearchParams();
    if (typeof params?.limit === "number") {
      searchParams.set("limit", String(params.limit));
    }
    if (typeof params?.offset === "number") {
      searchParams.set("offset", String(params.offset));
    }
    const query = searchParams.toString();
    const path = query ? `/api/tasks/${taskId}/logs?${query}` : `/api/tasks/${taskId}/logs`;
    return request<LogListResponse>(path);
  },
  subscriptionChannels: (params?: { keyword?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.keyword) {
      searchParams.set("keyword", params.keyword);
    }
    const query = searchParams.toString();
    return request<SubscriptionChannelListResponse>(
      query ? `/api/subscriptions/channels?${query}` : "/api/subscriptions/channels"
    );
  },
  createSubscriptionChannel: (input: string) =>
    request<SubscriptionChannel>("/api/subscriptions/channels", {
      method: "POST",
      body: JSON.stringify({ input })
    }),
  syncSubscriptionChannels: () =>
    request<SubscriptionChannelListResponse>("/api/subscriptions/channels/sync", {
      method: "POST"
    }),
  syncSubscriptionChannel: (channelId: number) =>
    request<SubscriptionChannel>(`/api/subscriptions/channels/${channelId}/sync`, {
      method: "POST"
    }),
  subscriptionVideos: (params?: { status_filter?: string; keyword?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.status_filter) {
      searchParams.set("status_filter", params.status_filter);
    }
    if (params?.keyword) {
      searchParams.set("keyword", params.keyword);
    }
    const query = searchParams.toString();
    return request<SubscriptionVideoListResponse>(
      query ? `/api/subscriptions/videos?${query}` : "/api/subscriptions/videos"
    );
  },
  createTaskFromSubscriptionVideo: (videoId: number) =>
    request<SubscriptionVideo>(`/api/subscriptions/videos/${videoId}/create-task`, {
      method: "POST"
    }),
  createTask: (payload: CreateTaskPayload) =>
    request<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateMetadata: (taskId: number, payload: MetadataUpdatePayload) =>
    request<Task["metadata"]>(`/api/tasks/${taskId}/metadata`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  runBilibiliUpload: (taskId: number, payload?: BilibiliUploadPayload) =>
    request<Task>(`/api/tasks/${taskId}/bilibili-upload`, {
      method: "POST",
      body: payload ? JSON.stringify(payload) : undefined
    }),
  generateCover: (taskId: number, payload: CoverGenerationPayload) => {
    const form = new FormData();
    form.set("mode", payload.mode);
    form.set("prompt", payload.prompt);
    if (payload.reference_image) {
      form.set("reference_image", payload.reference_image);
    }
    return request<Task>(`/api/tasks/${taskId}/cover-generation`, {
      method: "POST",
      body: form
    });
  },
  cancelTask: (taskId: number) =>
    request<Task>(`/api/tasks/${taskId}/cancel`, {
      method: "POST"
    }),
  deleteTask: (taskId: number) =>
    requestText(`/api/tasks/${taskId}`, {
      method: "DELETE"
    }).then(() => undefined),
  retryTask: (taskId: number) =>
    request<Task>(`/api/tasks/${taskId}/retry`, {
      method: "POST"
    }),
  retryTaskStep: (taskId: number, stepId: number) =>
    request<Task>(`/api/tasks/${taskId}/steps/${stepId}/retry`, {
      method: "POST"
    })
};
