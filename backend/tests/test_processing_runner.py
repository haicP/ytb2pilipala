import json

from backend.app.domain import SourceType, TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.adapters import AdapterResult
from backend.app.runner.processing import WorkflowRunner


class MetadataAdapter:
    def execute(self, task, step_name: str):
        if step_name == "extract_audio":
            return AdapterResult(
                success=True,
                message="audio extracted",
                artifacts=[("audio", f"artifacts/{task.id}/audio.wav")],
            )
        if step_name == "generate_metadata":
            return AdapterResult(
                success=True,
                message="metadata generated",
                metadata={
                    "submission_metadata": {
                        "title": "生成标题",
                        "description": "生成简介",
                        "tags": ["AI", "翻译"],
                        "category": "科技",
                    },
                },
            )
        if step_name in {"synthesize_voice", "sync_preview"}:
            return AdapterResult(
                success=True,
                message=f"{step_name} skipped",
                metadata={"step_status": "skipped"},
            )
        return AdapterResult(success=True, message=f"{step_name} completed")


class CurrentStepAssertingAdapter:
    def __init__(self, repo: TaskRepository):
        self.repo = repo
        self.seen_steps = []

    def execute(self, task, step_name: str):
        loaded = self.repo.get_task(task.id)
        assert loaded is not None
        assert loaded.status == TaskStatus.RUNNING.value
        assert loaded.current_step == step_name
        self.seen_steps.append(step_name)
        return AdapterResult(
            success=True,
            message=f"{step_name} skipped",
            metadata={"step_status": "skipped"},
        )


def test_workflow_runner_persists_artifacts_submission_metadata_and_skipped_steps(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    for step in task.steps[:3]:
        repo.update_step_status(step, TaskStatus.SUCCESS, 100)
    repo.update_task_status(task, TaskStatus.PENDING, current_step="extract_audio")

    WorkflowRunner(repo, adapter=MetadataAdapter()).run_task(task.id)

    loaded = repo.get_task(task.id)
    assert loaded is not None
    assert loaded.status == TaskStatus.SUCCESS
    assert loaded.progress == 100
    assert any(artifact.artifact_type == "audio" for artifact in loaded.artifacts)
    assert loaded.metadata_record.title == "生成标题"
    assert loaded.metadata_record.description == "生成简介"
    assert json.loads(loaded.metadata_record.tags) == ["AI", "翻译"]
    assert loaded.metadata_record.category == "科技"
    assert {step.name: step.status for step in loaded.steps}["synthesize_voice"] == TaskStatus.SKIPPED
    assert {step.name: step.status for step in loaded.steps}["upload_video"] == TaskStatus.PENDING
    assert {step.name: step.status for step in loaded.steps}["upload_subtitle"] == TaskStatus.PENDING


def test_workflow_runner_sets_current_step_before_executing_each_step(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-current-step")
    for step in task.steps[:4]:
        repo.update_step_status(step, TaskStatus.SUCCESS, 100)
    repo.update_task_status(task, TaskStatus.PENDING, current_step="transcribe")
    adapter = CurrentStepAssertingAdapter(repo)

    WorkflowRunner(repo, adapter=adapter).run_task(task.id)

    assert adapter.seen_steps[:2] == ["transcribe", "translate"]


def test_workflow_runner_progress_includes_running_step_progress(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-progress")
    for step in task.steps[:6]:
        repo.update_step_status(step, TaskStatus.SUCCESS, 100)
    synthesize_step = next(step for step in task.steps if step.name == "synthesize_voice")
    repo.update_step_status(synthesize_step, TaskStatus.RUNNING, 50)
    task = repo.get_task(task.id)

    from backend.app.runner.workflow import calculate_task_progress

    assert calculate_task_progress(task) == 72


def test_workflow_runner_progress_callback_updates_step_without_resetting_started_at(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-progress-callback")
    step = next(step for step in task.steps if step.name == "synthesize_voice")
    repo.update_step_status(step, TaskStatus.RUNNING, 10)
    started_at = step.started_at
    runner = WorkflowRunner(repo, adapter=MetadataAdapter())
    callback = runner._step_progress_callback(task, step)

    callback(55)
    loaded = repo.get_task(task.id)
    synthesize_step = next(item for item in loaded.steps if item.name == "synthesize_voice")

    assert synthesize_step.progress == 55
    assert synthesize_step.started_at == started_at
    assert loaded.progress > 0
