from backend.app.domain import MANUAL_UPLOAD_STEP_NAMES, TaskStatus
from backend.app.models import Task
from backend.app.repositories import TaskRepository


def calculate_task_progress(task: Task) -> int:
    automatic_steps = [step for step in task.steps if step.name not in MANUAL_UPLOAD_STEP_NAMES]
    if not automatic_steps:
        return 0
    progress_units = 0
    for step in automatic_steps:
        if step.status in {TaskStatus.SUCCESS.value, TaskStatus.SKIPPED.value}:
            progress_units += 100
        elif step.status == TaskStatus.RUNNING.value:
            progress_units += max(0, min(100, int(step.progress)))
    return round(progress_units / (len(automatic_steps) * 100) * 100)


def next_failed_step_name(task: Task) -> str | None:
    failed_steps = sorted(
        [step for step in task.steps if step.status == TaskStatus.FAILED.value],
        key=lambda step: step.order,
    )
    return failed_steps[0].name if failed_steps else None


def mark_task_cancelled(repo: TaskRepository, task: Task) -> None:
    for step in task.steps:
        if step.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
            repo.update_step_status(step, TaskStatus.CANCELLED, step.progress)
    repo.update_task_status(task, TaskStatus.CANCELLED, progress=calculate_task_progress(task))
