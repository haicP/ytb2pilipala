export type Status = "pending" | "running" | "success" | "failed" | "skipped" | "cancelled";

export interface TaskStep {
  id: number;
  name: string;
  order: number;
  label: string;
  status: Status;
  progress: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string;
  retry_count: number;
}

export interface Artifact {
  id: number;
  task_id: number;
  step_id: number | null;
  artifact_type: string;
  path: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface SubmissionMetadata {
  id: number;
  task_id: number;
  title: string;
  description: string;
  tags: string[];
  category: string;
  copyright_type: 1 | 2;
  cover_artifact_id: number | null;
  visibility: string;
  bilibili_video_id: string;
  bilibili_aid: string;
  bilibili_cid: string;
  bilibili_filename: string;
  bilibili_cover_url: string;
  upload_status: string;
  updated_at: string;
}

export interface Task {
  id: number;
  source_type: string;
  input: string;
  title: string;
  status: Status;
  current_step: string;
  progress: number;
  error_summary: string;
  created_at: string;
  updated_at: string;
  steps: TaskStep[];
  artifacts: Artifact[];
  metadata: SubmissionMetadata | null;
}

export interface LogItem {
  id: number;
  task_id: number;
  step_id: number | null;
  level: string;
  message: string;
  context: Record<string, unknown>;
  created_at: string;
}

export interface SystemMetrics {
  disk_free_gb: number;
  disk_total_gb: number;
  cpu_percent: number;
  memory_available_gb: number;
  memory_total_gb: number;
}

export interface SettingsSummary {
  dependencies: Record<string, boolean>;
  config: Record<string, boolean>;
  settings: Record<string, string>;
}

export interface AssistantSettings {
  base_url: string;
  api_key: string;
  model_id: string;
  postprocess_prompt: string;
  translation_prompt: string;
  metadata_prompt: string;
  defaults: Record<string, string>;
  updated_at: string | null;
}

export interface TaskListResponse {
  items: Task[];
}

export interface LogListResponse {
  items: LogItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SubscriptionChannel {
  id: number;
  source_url: string;
  channel_id: string;
  title: string;
  thumbnail_url: string;
  status: string;
  error_summary: string;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
  video_count: number;
}

export interface SubscriptionVideo {
  id: number;
  channel_id: number;
  channel_title: string;
  video_id: string;
  youtube_url: string;
  title: string;
  published_at: string | null;
  thumbnail_url: string;
  status: string;
  task_id: number | null;
  discovered_at: string;
  updated_at: string;
}

export interface SubscriptionChannelListResponse {
  items: SubscriptionChannel[];
}

export interface SubscriptionVideoListResponse {
  items: SubscriptionVideo[];
}

export interface AccountBinding {
  id: number;
  platform: string;
  platform_user_id: string;
  nickname: string;
  avatar_url: string;
  status: string;
  is_primary: boolean;
  cookie_summary: string;
  last_login_at: string | null;
  error_summary: string;
  created_at: string;
  updated_at: string;
}

export interface AccountBindingListResponse {
  items: AccountBinding[];
}

export interface BilibiliQrCodeResponse {
  login_session_id: string;
  qrcode_data_url: string;
  expires_at: string;
}

export interface BilibiliQrCodePollResponse {
  status: "pending_scan" | "scanned" | "confirmed" | "expired" | "failed";
  message: string;
  account: AccountBinding | null;
}

export interface CreateTaskPayload {
  source_type: "youtube" | "local";
  input: string;
  options?: {
    download_resolution?: "auto" | "1080p" | "720p";
    playlist?: {
      enabled: boolean;
      start_index: number;
      max_items: number;
    };
    enabled_steps?: {
      download_thumbnail: boolean;
      transcribe: boolean;
      translate: boolean;
      synthesize_voice: boolean;
    };
  };
}

export interface MetadataUpdatePayload {
  title?: string;
  description?: string;
  tags?: string[];
  category?: string;
  copyright_type?: 1 | 2;
}

export interface CoverGenerationPayload {
  mode: "text" | "image";
  prompt: string;
  reference_image?: File | null;
}

export interface BilibiliUploadPayload {
  account_id?: number;
}

export interface SettingsUpdatePayload {
  default_category?: string;
  dry_run_step_delay_ms?: number;
  assistant_base_url?: string;
  assistant_api_key?: string;
  assistant_model_id?: string;
  image_model_id?: string;
  tts_provider?: "mimo_v2_5_tts" | "openai";
  mimo_base_url?: string;
  mimo_api_key?: string;
  mimo_tts_model?: string;
  mimo_tts_voice?: string;
  mimo_tts_style_prompt?: string;
  mimo_tts_concurrency?: number;
  tts_concurrency?: number;
  openai_tts_base_url?: string;
  openai_tts_api_key?: string;
  openai_tts_model?: string;
  openai_tts_voice?: string;
  openai_tts_instructions?: string;
  openai_tts_speed?: number;
}

export interface AssistantSettingsUpdatePayload {
  base_url: string;
  api_key: string;
  model_id: string;
  postprocess_prompt: string;
  translation_prompt: string;
  metadata_prompt: string;
}
