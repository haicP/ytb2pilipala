import base64
import re
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import Artifact, Task
from backend.app.repositories import TaskRepository


class CoverGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoverGenerationResult:
    artifact_id: int
    path: str


class OpenAICoverClient:
    def __init__(
        self,
        db: Session,
        client=None,
        model: str = "gpt-image-2",
        size: str = "1536x1024",
    ):
        self.db = db
        self.repo = TaskRepository(db)
        self.client = client
        self.model = model
        self.size = size

    def generate_from_text(self, task: Task, prompt: str) -> CoverGenerationResult:
        clean_prompt = self._clean_prompt(prompt)
        model = self._model_id()
        response = self._openai().images.generate(
            model=model,
            prompt=clean_prompt,
            size=self.size,
            n=1,
        )
        return self._save_response_image(task, response, source="text", model=model)

    def generate_from_image(
        self,
        task: Task,
        prompt: str,
        reference_bytes: bytes | None = None,
        reference_filename: str | None = None,
    ) -> CoverGenerationResult:
        clean_prompt = self._clean_prompt(prompt)
        model = self._model_id()
        image_bytes = reference_bytes
        filename = reference_filename or "reference.png"
        if image_bytes is None:
            reference_artifact = self._reference_artifact(task)
            if reference_artifact is None:
                raise CoverGenerationError("缺少参考图，请上传参考图或先生成/下载封面缩略图")
            reference_path = Path(reference_artifact.path)
            if not reference_path.is_file():
                raise CoverGenerationError("参考图文件不存在，无法生成封面")
            image_bytes = reference_path.read_bytes()
            filename = reference_path.name

        response = self._openai().images.edit(
            model=model,
            image=(filename, image_bytes),
            prompt=clean_prompt,
            size=self.size,
            n=1,
        )
        return self._save_response_image(task, response, source="image", model=model)

    def _openai(self):
        if self.client is not None:
            return self.client

        settings = get_settings()
        saved = self.repo.get_app_settings(("assistant_base_url", "assistant_api_key"))
        api_key = saved.get("assistant_api_key") or settings.llm_api_key
        if not api_key:
            raise CoverGenerationError("缺少 OpenAI API Key，请先在设置页配置 LLM API Key")

        kwargs = {"api_key": api_key}
        base_url = saved.get("assistant_base_url") or settings.api2key_base_url
        if base_url:
            kwargs["base_url"] = base_url
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise CoverGenerationError("openai package is required for cover generation") from exc

        self.client = OpenAI(**kwargs)
        return self.client

    def _model_id(self) -> str:
        settings = get_settings()
        saved = self.repo.get_app_settings(("image_model_id",))
        return saved.get("image_model_id") or settings.image_model_id or self.model

    def _save_response_image(self, task: Task, response, source: str, model: str) -> CoverGenerationResult:
        encoded = self._response_b64(response)
        try:
            image_bytes = base64.b64decode(encoded)
        except Exception as exc:  # noqa: BLE001
            raise CoverGenerationError("OpenAI 图片响应无法解析") from exc
        if not image_bytes:
            raise CoverGenerationError("OpenAI 图片响应为空")

        output_dir = Path("data") / "artifacts" / str(task.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"cover-{int(time.time() * 1000)}.png"
        output_path.write_bytes(image_bytes)

        artifact = self.repo.add_artifact(
            task_id=task.id,
            step_id=None,
            artifact_type="cover",
            path=str(output_path),
            metadata={"source": source, "model": model},
        )
        self.repo.update_metadata_cover(task.id, artifact.id)
        self.repo.append_log(task.id, None, "info", "视频封面已生成")
        return CoverGenerationResult(artifact_id=artifact.id, path=artifact.path)

    def _response_b64(self, response) -> str:
        data = getattr(response, "data", None)
        if not data:
            raise CoverGenerationError("OpenAI 图片响应缺少 data")
        first = data[0]
        encoded = getattr(first, "b64_json", None)
        if isinstance(encoded, str) and encoded:
            return encoded
        if isinstance(first, dict):
            encoded = first.get("b64_json")
            if isinstance(encoded, str) and encoded:
                return encoded
        raise CoverGenerationError("OpenAI 图片响应缺少 b64_json")

    def _reference_artifact(self, task: Task) -> Artifact | None:
        metadata = task.metadata_record
        if metadata and metadata.cover_artifact_id is not None:
            for artifact in task.artifacts:
                if artifact.id == metadata.cover_artifact_id:
                    return artifact
        return self._latest_artifact(task, ("cover", "thumbnail"))

    def _latest_artifact(self, task: Task, artifact_types: tuple[str, ...]) -> Artifact | None:
        matches = [artifact for artifact in task.artifacts if artifact.artifact_type in artifact_types]
        if not matches:
            return None
        return sorted(matches, key=lambda item: (item.created_at, item.id))[-1]

    def _clean_prompt(self, prompt: str) -> str:
        clean = re.sub(r"\s+", " ", prompt).strip()
        if not clean:
            raise CoverGenerationError("封面提示词不能为空")
        if len(clean) > 2000:
            raise CoverGenerationError("封面提示词不能超过 2000 字符")
        return clean


def sanitize_cover_error(error: Exception) -> str:
    message = str(error) or error.__class__.__name__
    message = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[redacted]", message)
    message = re.sub(r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*[^,\s]+", r"\1=[redacted]", message)
    message = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "data:image/[redacted];base64,[redacted]", message)
    if len(message) > 500:
        message = f"{message[:500]}..."
    return message
