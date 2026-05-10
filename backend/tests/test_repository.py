import json

from sqlalchemy.orm.exc import DetachedInstanceError

from backend.app.domain import SourceType, TaskStatus
from backend.app.repositories import TaskRepository


def test_create_task_builds_steps_and_metadata(db_session):
    repo = TaskRepository(db_session)

    task = repo.create_task(source_type=SourceType.YOUTUBE, input_value="https://youtu.be/demo")

    assert task.id is not None
    assert task.status == TaskStatus.PENDING
    assert task.progress == 0
    assert len(task.steps) == 11
    assert task.metadata_record is not None
    assert task.steps[0].name == "import"


def test_create_task_names_youtube_task_from_video_id(db_session):
    repo = TaskRepository(db_session)

    watch_task = repo.create_task(
        source_type=SourceType.YOUTUBE,
        input_value="https://www.youtube.com/watch?v=abc123XYZ&list=demo",
    )
    short_task = repo.create_task(source_type=SourceType.YOUTUBE, input_value="https://youtu.be/short456?t=1")
    shorts_task = repo.create_task(
        source_type=SourceType.YOUTUBE,
        input_value="https://www.youtube.com/shorts/shorts789",
    )
    embed_task = repo.create_task(
        source_type=SourceType.YOUTUBE,
        input_value="https://www.youtube.com/embed/embed012",
    )

    assert watch_task.title == "abc123XYZ"
    assert short_task.title == "short456"
    assert shorts_task.title == "shorts789"
    assert embed_task.title == "embed012"


def test_create_task_names_duplicate_youtube_video_ids_with_incrementing_suffix(db_session):
    repo = TaskRepository(db_session)

    first_task = repo.create_task(
        source_type=SourceType.YOUTUBE,
        input_value="https://www.youtube.com/watch?v=dup123XYZ",
    )
    second_task = repo.create_task(
        source_type=SourceType.YOUTUBE,
        input_value="https://youtu.be/dup123XYZ?t=2",
    )
    third_task = repo.create_task(
        source_type=SourceType.YOUTUBE,
        input_value="https://www.youtube.com/embed/dup123XYZ",
    )

    assert first_task.title == "dup123XYZ"
    assert second_task.title == "dup123XYZ #2"
    assert third_task.title == "dup123XYZ #3"


def test_create_task_names_local_task_from_file_name(db_session):
    repo = TaskRepository(db_session)

    task = repo.create_task(source_type=SourceType.LOCAL, input_value="/videos/My Demo.mp4")

    assert task.title == "My Demo"


def test_get_task_returns_steps_ordered_by_workflow_order(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type=SourceType.YOUTUBE, input_value="https://youtu.be/demo")
    task_id = task.id

    for index, step in enumerate(task.steps):
        step.order = len(task.steps) - index
    db_session.commit()
    db_session.expunge_all()

    loaded = repo.get_task(task_id)

    assert loaded is not None
    orders = [step.order for step in loaded.steps]
    assert orders == sorted(orders)


def test_append_log_and_artifact(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type=SourceType.LOCAL, input_value="/videos/demo.mp4")
    first_step = task.steps[0]

    log = repo.append_log(task_id=task.id, step_id=first_step.id, level="info", message="导入完成")
    db_session.expunge(log)

    try:
        assert log.task is not None
        assert log.task.id == task.id
        assert log.step is not None
        assert log.step.id == first_step.id
    except DetachedInstanceError as exc:
        raise AssertionError("append_log 返回对象不应依赖懒加载") from exc

    artifact = repo.add_artifact(
        task_id=task.id,
        step_id=first_step.id,
        artifact_type="video",
        path="/mock/video.mp4",
    )
    db_session.expunge(artifact)

    try:
        assert artifact.task is not None
        assert artifact.task.id == task.id
        assert artifact.step is not None
        assert artifact.step.id == first_step.id
    except DetachedInstanceError as exc:
        raise AssertionError("add_artifact 返回对象不应依赖懒加载") from exc

    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.logs[0].message == "导入完成"
    assert loaded.artifacts[0].artifact_type == "video"


def test_update_task_status_returns_task_with_loaded_relationships(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type=SourceType.YOUTUBE, input_value="https://youtu.be/demo")

    updated = repo.update_task_status(
        task=task,
        status=TaskStatus.RUNNING,
        current_step="download_video",
        progress=20,
    )
    db_session.expunge(updated)

    assert updated.status == TaskStatus.RUNNING
    assert updated.current_step == "download_video"
    assert updated.progress == 20
    try:
        assert updated.steps[0].name == "import"
        assert updated.metadata_record is not None
    except DetachedInstanceError as exc:
        raise AssertionError("update_task_status 返回对象不应依赖懒加载") from exc


def test_update_step_status_sets_started_and_finished_at(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type=SourceType.YOUTUBE, input_value="https://youtu.be/demo")
    step = task.steps[0]

    running = repo.update_step_status(step=step, status=TaskStatus.RUNNING, progress=30)
    assert running.status == TaskStatus.RUNNING
    assert running.progress == 30
    assert running.started_at is not None
    assert running.finished_at is None

    finished = repo.update_step_status(step=running, status=TaskStatus.SUCCESS, progress=100)
    db_session.expunge(finished)
    assert finished.status == TaskStatus.SUCCESS
    assert finished.progress == 100
    assert finished.finished_at is not None
    try:
        assert finished.task is not None
    except DetachedInstanceError as exc:
        raise AssertionError("update_step_status 返回对象不应依赖懒加载") from exc


def test_update_step_status_retry_clears_finished_at_then_sets_again(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type=SourceType.YOUTUBE, input_value="https://youtu.be/demo")
    step = task.steps[1]

    first_finished = repo.update_step_status(step=step, status=TaskStatus.SUCCESS, progress=100)
    assert first_finished.finished_at is not None
    first_finished_at = first_finished.finished_at

    retried = repo.update_step_status(step=first_finished, status=TaskStatus.RUNNING, progress=60)
    assert retried.status == TaskStatus.RUNNING
    assert retried.started_at is not None
    assert retried.finished_at is None

    second_finished = repo.update_step_status(step=retried, status=TaskStatus.SUCCESS, progress=100)
    assert second_finished.status == TaskStatus.SUCCESS
    assert second_finished.finished_at is not None
    assert second_finished.finished_at > first_finished_at


def test_update_metadata_persists_and_returns_updated_record(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type=SourceType.LOCAL, input_value="/videos/demo.mp4")

    metadata = repo.update_metadata(
        task_id=task.id,
        title="新标题",
        description="新简介",
        tags=["技术", "翻译"],
        category="科技",
    )
    db_session.expunge(metadata)

    assert metadata.title == "新标题"
    assert metadata.description == "新简介"
    assert json.loads(metadata.tags) == ["技术", "翻译"]
    try:
        assert metadata.task is not None
        assert metadata.task.id == task.id
    except DetachedInstanceError as exc:
        raise AssertionError("update_metadata 返回对象不应依赖懒加载") from exc
