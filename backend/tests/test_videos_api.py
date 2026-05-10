from backend.app.domain import SourceType
from backend.app.repositories import TaskRepository


def test_get_video_artifact_streams_matching_task_file(client, db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.LOCAL, "/videos/demo.mp4")
    preview_path = tmp_path / "preview.mp4"
    preview_path.write_bytes(b"preview-bytes")
    artifact = repo.add_artifact(task.id, task.steps[0].id, "preview", str(preview_path))

    response = client.get(f"/api/videos/{task.id}/artifacts/{artifact.id}")

    assert response.status_code == 200
    assert response.content == b"preview-bytes"
    assert response.headers["content-type"].startswith("video/mp4")


def test_get_video_artifact_rejects_artifact_from_other_task(client, db_session, tmp_path):
    repo = TaskRepository(db_session)
    owner_task = repo.create_task(SourceType.LOCAL, "/videos/owner.mp4")
    other_task = repo.create_task(SourceType.LOCAL, "/videos/other.mp4")
    subtitle_path = tmp_path / "preview.srt"
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nsubtitle\n", encoding="utf-8")
    artifact = repo.add_artifact(
        owner_task.id,
        owner_task.steps[0].id,
        "subtitle_translated",
        str(subtitle_path),
    )

    response = client.get(f"/api/videos/{other_task.id}/artifacts/{artifact.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"
