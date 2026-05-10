import type { Artifact, Task } from "./api/types";

function sortByCreatedAt(a: Artifact, b: Artifact) {
  if (a.created_at === b.created_at) {
    return a.id - b.id;
  }
  return a.created_at.localeCompare(b.created_at);
}

export function videoTitle(task: Task) {
  return task.metadata?.title || task.title;
}

export function videoTags(task: Task) {
  return task.metadata?.tags.join(", ") || "未生成标签";
}

export function latestArtifact(task: Task, artifactTypes: string[]) {
  return (
    task.artifacts
      .filter((artifact) => artifactTypes.includes(artifact.artifact_type))
      .sort(sortByCreatedAt)
      .at(-1) || null
  );
}

export function originalVideoArtifact(task: Task) {
  return latestArtifact(task, ["video"]);
}

export function dubbedVideoArtifact(task: Task) {
  return latestArtifact(task, ["preview"]);
}

export function coverArtifact(task: Task) {
  if (task.metadata?.cover_artifact_id) {
    const selected = task.artifacts.find((artifact) => artifact.id === task.metadata?.cover_artifact_id);
    if (selected) {
      return selected;
    }
  }
  return latestArtifact(task, ["cover", "thumbnail"]);
}

export function libraryPreviewArtifact(task: Task) {
  return latestArtifact(task, ["preview", "video"]);
}

export function sourceSubtitleArtifact(task: Task) {
  return latestArtifact(task, ["subtitle_source"]);
}

export function translatedSubtitleArtifact(task: Task) {
  return latestArtifact(task, ["subtitle_translated"]);
}

export function subtitleTextPreview(rawText: string) {
  const cleaned = rawText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !/^\d+$/.test(line) && !line.includes("-->"))
    .join("\n");
  return cleaned || "字幕内容为空。";
}
