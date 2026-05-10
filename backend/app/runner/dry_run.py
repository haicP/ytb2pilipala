import json

from backend.app.domain import TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.adapters import DryRunAdapter, WorkflowAdapter
from backend.app.runner.workflow import calculate_task_progress


class DryRunRunner:
    def __init__(self, repo: TaskRepository, adapter: WorkflowAdapter | None = None):
        self.repo = repo
        self.adapter = adapter or DryRunAdapter()

    def run_task(self, task_id: int) -> None:
        task = self.repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        self.repo.update_task_status(
            task,
            TaskStatus.RUNNING,
            current_step=task.current_step,
            progress=calculate_task_progress(task),
        )

        for step in sorted(task.steps, key=lambda item: item.order):
            if step.status in {TaskStatus.SUCCESS.value, TaskStatus.SKIPPED.value}:
                continue
            self.repo.update_step_status(step, TaskStatus.RUNNING, 10)
            self.repo.append_log(task.id, step.id, "info", f"开始执行：{step.label}")

            try:
                result = self.adapter.execute(task, step.name)
            except Exception as exc:
                message = f"dry-run step {step.name} failed: {exc}"
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

            step_status_value = str(result.metadata.get("step_status", TaskStatus.SUCCESS.value))
            step_status = TaskStatus(step_status_value)

            if step.name == "generate_metadata" and task.metadata_record is not None:
                metadata = task.metadata_record
                metadata.title = f"【中文配音】{task.title}"
                metadata.description = "由 ytb2pilipala dry-run 工作流生成的投稿简介。"
                metadata.tags = json.dumps(["YouTube", "中文配音", "AI翻译"], ensure_ascii=False)
                metadata.category = "科技"
                self.repo.session.commit()

            if step.name == "upload_video" and task.metadata_record is not None:
                metadata = task.metadata_record
                metadata.upload_status = "skipped" if step_status == TaskStatus.SKIPPED else "success"
                if step_status == TaskStatus.SUCCESS:
                    metadata.bilibili_video_id = f"dry-run-{task.id}"
                self.repo.session.commit()

            self.repo.update_step_status(step, step_status, 100)
            if step_status == TaskStatus.SKIPPED:
                reason = str(result.metadata.get("skip_reason", "当前步骤未接入真实外部服务。"))
                self.repo.append_log(task.id, step.id, "info", f"跳过执行：{step.label}。{reason}")
            else:
                self.repo.append_log(task.id, step.id, "info", f"完成执行：{step.label}")
            self.repo.update_task_status(
                task,
                TaskStatus.RUNNING,
                current_step=step.name,
                progress=calculate_task_progress(task),
            )

        self.repo.update_task_status(task, TaskStatus.SUCCESS, progress=100)
        self.repo.append_log(task.id, None, "info", "dry-run 工作流已完成")
