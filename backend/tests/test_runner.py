from pathlib import Path

from backend.app.domain import SourceType, TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.adapters import DryRunAdapter
from backend.app.runner.dry_run import DryRunRunner


class RaisingAdapter:
    def execute(self, task, step_name: str):
        raise RuntimeError("boom")


def test_dry_run_runner_completes_task_and_materializes_artifacts(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    runner = DryRunRunner(
        repo,
        adapter=DryRunAdapter(
            storage_root=tmp_path / "artifacts",
            prefer_video_subtitles=False,
        ),
    )

    runner.run_task(task.id)
    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.status == TaskStatus.SUCCESS
    assert loaded.progress == 100
    assert [step.status for step in loaded.steps[-2:]] == [TaskStatus.SKIPPED, TaskStatus.SKIPPED]
    assert all(
        step.status in {TaskStatus.SUCCESS, TaskStatus.SKIPPED}
        for step in loaded.steps
    )
    assert len(loaded.logs) >= 11
    assert len(loaded.artifacts) >= 5
    assert all(Path(artifact.path).is_file() for artifact in loaded.artifacts)
    assert (tmp_path / "artifacts" / str(task.id) / "source.srt").is_file()
    assert (tmp_path / "artifacts" / str(task.id) / "zh.srt").is_file()
    assert (tmp_path / "artifacts" / str(task.id) / "zh_voice.wav").is_file()
    assert (tmp_path / "artifacts" / str(task.id) / "preview.mp4").is_file()
    assert loaded.metadata_record.title == "【中文配音】demo"
    assert loaded.metadata_record.upload_status == "skipped"


def test_dry_run_runner_marks_failed_when_adapter_raises(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    runner = DryRunRunner(repo, adapter=RaisingAdapter())

    runner.run_task(task.id)
    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.status == TaskStatus.FAILED
    assert "boom" in loaded.error_summary
    assert loaded.current_step == "import"
    assert loaded.steps[0].status == TaskStatus.FAILED
    assert loaded.steps[0].error_message
    assert "boom" in loaded.steps[0].error_message
    assert any(log.level == "error" and "boom" in log.message for log in loaded.logs)
