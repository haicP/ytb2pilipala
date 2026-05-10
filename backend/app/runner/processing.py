from collections.abc import Mapping

from backend.app.domain import MANUAL_UPLOAD_STEP_NAMES, TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.ai_adapter import AiWorkflowAdapter
from backend.app.runner.workflow import calculate_task_progress


class WorkflowRunner:
    def __init__(self, repo: TaskRepository, adapter=None):
        self.repo = repo
        self.adapter = adapter or AiWorkflowAdapter()

    def run_task(self, task_id: int) -> None:
        task = self.repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        self.repo.update_task_status(task, TaskStatus.RUNNING, current_step=task.current_step, progress=task.progress)

        for step in sorted(task.steps, key=lambda item: item.order):
            if step.status in {TaskStatus.SUCCESS.value, TaskStatus.SKIPPED.value}:
                continue
            if step.name in MANUAL_UPLOAD_STEP_NAMES:
                continue

            self.repo.update_task_status(
                task,
                TaskStatus.RUNNING,
                current_step=step.name,
                progress=calculate_task_progress(task),
            )
            self.repo.update_step_status(step, TaskStatus.RUNNING, 10)
            self.repo.append_log(task.id, step.id, "info", f"开始执行：{step.label}")

            try:
                if isinstance(self.adapter, AiWorkflowAdapter):
                    self.adapter.progress_callback = self._step_progress_callback(task, step)
                result = self.adapter.execute(task, step.name)
            except Exception as exc:
                message = f"workflow step {step.name} failed: {exc}"
                self.repo.update_step_status(step, TaskStatus.FAILED, 100, message)
                self.repo.update_task_status(
                    task,
                    TaskStatus.FAILED,
                    current_step=step.name,
                    progress=calculate_task_progress(task),
                    error_summary=message,
                )
                self.repo.append_log(task.id, step.id, "error", message)
                return

            if not result.success:
                self.repo.update_step_status(step, TaskStatus.FAILED, 100, result.message)
                self.repo.update_task_status(
                    task,
                    TaskStatus.FAILED,
                    current_step=step.name,
                    progress=calculate_task_progress(task),
                    error_summary=result.message,
                )
                self.repo.append_log(task.id, step.id, "error", result.message)
                return

            for artifact_type, path in result.artifacts:
                self.repo.add_artifact(task.id, step.id, artifact_type, path, result.metadata)

            self._update_submission_metadata(task.id, result.metadata)
            step_status = self._step_status_from_metadata(result.metadata)
            self.repo.update_step_status(step, step_status, 100)
            self.repo.append_log(task.id, step.id, "info", f"完成执行：{step.label}")
            self.repo.update_task_status(
                task,
                TaskStatus.RUNNING,
                current_step=step.name,
                progress=calculate_task_progress(task),
            )

        self.repo.update_task_status(task, TaskStatus.SUCCESS, progress=100)
        self.repo.append_log(task.id, None, "info", "processing 工作流已完成")

    def _step_progress_callback(self, task, step):
        def update(progress: int) -> None:
            clamped = max(0, min(99, int(progress)))
            self.repo.update_step_status(step, TaskStatus.RUNNING, clamped)
            self.repo.update_task_status(
                task,
                TaskStatus.RUNNING,
                current_step=step.name,
                progress=calculate_task_progress(task),
            )

        return update

    def _update_submission_metadata(self, task_id: int, metadata: dict[str, object]) -> None:
        payload = metadata.get("submission_metadata")
        if not isinstance(payload, Mapping):
            return
        self.repo.update_metadata(
            task_id=task_id,
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            tags=self._metadata_tags(payload.get("tags")),
            category=str(payload.get("category", "科技") or "科技"),
        )

    @staticmethod
    def _metadata_tags(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    @staticmethod
    def _step_status_from_metadata(metadata: dict[str, object]) -> TaskStatus:
        if metadata.get("step_status") == TaskStatus.SKIPPED.value:
            return TaskStatus.SKIPPED
        return TaskStatus.SUCCESS
