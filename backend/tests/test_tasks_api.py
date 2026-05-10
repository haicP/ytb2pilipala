import pytest

from backend.app.domain import SourceType, TaskStatus
from backend.app.models import AccountBinding, SubscriptionChannel, SubscriptionVideo
from backend.app.repositories import TaskRepository
from backend.app.runner.dry_run import DryRunRunner


@pytest.fixture(autouse=True)
def disable_background_download(monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.tasks.run_download_task",
        lambda task_id: None,
        raising=False,
    )


def _create_completed_task(db_session, source_type: SourceType, input_value: str):
    repo = TaskRepository(db_session)
    task = repo.create_task(source_type, input_value)
    DryRunRunner(repo).run_task(task.id)
    completed = repo.get_task(task.id)
    assert completed is not None
    return completed


def test_create_youtube_task_starts_download_step_and_names_from_video_id(client):
    response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://www.youtube.com/watch?v=abc123XYZ"},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["source_type"] == "youtube"
    assert created["title"] == "abc123XYZ"
    assert created["status"] == "running"
    assert created["current_step"] == "download_video"
    assert created["progress"] > 0
    assert len(created["steps"]) == 11
    assert created["steps"][0]["status"] == "success"
    assert created["steps"][0]["progress"] == 100
    assert created["steps"][1]["name"] == "download_video"
    assert created["steps"][1]["status"] == "running"
    assert created["steps"][1]["progress"] > 0
    assert {step["status"] for step in created["steps"][2:]} == {"pending"}
    assert created["metadata"]["title"] == ""

    logs_response = client.get(f"/api/tasks/{created['id']}/logs")
    assert logs_response.status_code == 200
    assert logs_response.json()["total"] >= 2


def test_create_task_options_can_skip_optional_workflow_steps(client):
    response = client.post(
        "/api/tasks",
        json={
            "source_type": "youtube",
            "input": "https://youtu.be/options-demo",
            "options": {
                "download_resolution": "1080p",
                "playlist": {"enabled": False, "start_index": 1, "max_items": 10},
                "enabled_steps": {
                    "download_thumbnail": False,
                    "transcribe": True,
                    "translate": False,
                    "synthesize_voice": True,
                },
            },
        },
    )

    assert response.status_code == 201
    step_statuses = {step["name"]: step for step in response.json()["steps"]}
    assert step_statuses["download_thumbnail"]["status"] == "skipped"
    assert step_statuses["download_thumbnail"]["error_message"] == "由本次提交设置跳过"
    assert step_statuses["translate"]["status"] == "skipped"
    assert step_statuses["synthesize_voice"]["status"] == "skipped"
    assert step_statuses["sync_preview"]["status"] == "skipped"
    assert step_statuses["transcribe"]["status"] == "pending"


def test_create_youtube_task_uses_incrementing_suffix_for_duplicate_video_id(client):
    first_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://www.youtube.com/watch?v=dup123XYZ"},
    )
    second_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/dup123XYZ?t=1"},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_response.json()["title"] == "dup123XYZ"
    assert second_response.json()["title"] == "dup123XYZ #2"


def test_task_list_and_logs(client):
    create_response = client.post(
        "/api/tasks",
        json={"source_type": "local", "input": "/videos/demo.mp4"},
    )
    task_id = create_response.json()["id"]

    list_response = client.get("/api/tasks")
    logs_response = client.get(f"/api/tasks/{task_id}/logs")

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == task_id
    assert logs_response.status_code == 200
    assert logs_response.json()["items"] == []
    assert logs_response.json()["total"] == 0


def test_task_list_supports_source_status_and_keyword_filters(client):
    youtube_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/demo-youtube"},
    )
    local_response = client.post(
        "/api/tasks",
        json={"source_type": "local", "input": "/videos/demo-local.mp4"},
    )

    youtube_id = youtube_response.json()["id"]
    local_id = local_response.json()["id"]

    source_response = client.get("/api/tasks", params={"source_type": "youtube"})
    running_response = client.get("/api/tasks", params={"status_filter": "running"})
    pending_response = client.get("/api/tasks", params={"status_filter": "pending"})
    keyword_response = client.get("/api/tasks", params={"keyword": "demo-local"})

    assert source_response.status_code == 200
    assert [item["id"] for item in source_response.json()["items"]] == [youtube_id]

    assert running_response.status_code == 200
    assert [item["id"] for item in running_response.json()["items"]] == [youtube_id]

    assert pending_response.status_code == 200
    assert [item["id"] for item in pending_response.json()["items"]] == [local_id]

    assert keyword_response.status_code == 200
    assert [item["id"] for item in keyword_response.json()["items"]] == [local_id]


def test_update_metadata(client):
    create_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/demo"},
    )
    task_id = create_response.json()["id"]

    response = client.patch(
        f"/api/tasks/{task_id}/metadata",
        json={
            "title": "新的标题",
            "description": "新的简介",
            "tags": ["AI", "翻译"],
            "category": "科技",
        },
    )

    assert response.status_code == 200
    assert response.json()["title"] == "新的标题"
    assert response.json()["tags"] == ["AI", "翻译"]


def test_delete_completed_task_removes_records_artifacts_and_subscription_link(
    client,
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    completed_task = _create_completed_task(db_session, SourceType.LOCAL, "/videos/delete-demo.mp4")
    task_dir = tmp_path / "data" / "artifacts" / str(completed_task.id)
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "extra.txt").write_text("delete me", encoding="utf-8")

    channel = SubscriptionChannel(
        source_url="https://www.youtube.com/@demo/videos",
        channel_id="UCdeleteDemo",
        title="Delete Demo",
    )
    db_session.add(channel)
    db_session.flush()
    subscription_video = SubscriptionVideo(
        channel_id=channel.id,
        video_id="delete-video",
        youtube_url="https://youtu.be/delete-video",
        title="Delete video",
        status="queued",
        task_id=completed_task.id,
    )
    db_session.add(subscription_video)
    db_session.commit()

    response = client.delete(f"/api/tasks/{completed_task.id}")

    assert response.status_code == 204
    assert not task_dir.exists()
    assert client.get(f"/api/tasks/{completed_task.id}").status_code == 404
    db_session.refresh(subscription_video)
    assert subscription_video.task_id is None
    assert subscription_video.status == "discovered"


def test_delete_task_rejects_pending_and_running_tasks(client):
    pending_response = client.post(
        "/api/tasks",
        json={"source_type": "local", "input": "/videos/pending-delete.mp4"},
    )
    running_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/running-delete"},
    )

    assert pending_response.status_code == 201
    assert running_response.status_code == 201

    pending_delete = client.delete(f"/api/tasks/{pending_response.json()['id']}")
    running_delete = client.delete(f"/api/tasks/{running_response.json()['id']}")

    assert pending_delete.status_code == 409
    assert running_delete.status_code == 409


def test_cover_generation_requires_api_key(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("API2KEY_BASE_URL", "")
    create_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/cover-api"},
    )
    task_id = create_response.json()["id"]

    response = client.post(
        f"/api/tasks/{task_id}/cover-generation",
        data={"mode": "text", "prompt": "科技视频封面"},
    )

    assert response.status_code == 400
    assert "OpenAI API Key" in response.json()["detail"]


def test_cover_generation_rejects_image_mode_without_reference(client):
    create_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/no-cover-reference"},
    )
    task_id = create_response.json()["id"]

    response = client.post(
        f"/api/tasks/{task_id}/cover-generation",
        data={"mode": "image", "prompt": "基于参考图生成封面"},
    )

    assert response.status_code == 400
    assert "缺少参考图" in response.json()["detail"]


def test_patch_settings_saves_non_sensitive_values(client):
    response = client.patch(
        "/api/settings",
        json={
            "default_category": "科技",
            "dry_run_step_delay_ms": 0,
            "assistant_base_url": "https://api.example.com/v1",
            "assistant_api_key": "sk-llm-saved",
            "assistant_model_id": "gpt-4.1-mini",
            "image_model_id": "gpt-image-2",
            "tts_provider": "openai",
            "mimo_base_url": "https://tts.example.com/v1",
            "mimo_api_key": "sk-tts-saved",
            "mimo_tts_model": "mimo-v2.5-tts",
            "mimo_tts_voice": "冰糖",
            "mimo_tts_style_prompt": "请自然朗读。",
            "mimo_tts_concurrency": 12,
            "tts_concurrency": 9,
            "openai_tts_base_url": "https://api.openai.com/v1",
            "openai_tts_api_key": "sk-openai-tts",
            "openai_tts_model": "gpt-4o-mini-tts",
            "openai_tts_voice": "alloy",
            "openai_tts_instructions": "请自然朗读。",
            "openai_tts_speed": 1.15,
        },
    )

    assert response.status_code == 200
    assert response.json()["settings"]["default_category"] == "科技"
    assert response.json()["settings"]["dry_run_step_delay_ms"] == "0"
    assert response.json()["settings"]["assistant_base_url"] == "https://api.example.com/v1"
    assert response.json()["settings"]["assistant_api_key"] == "sk-llm-saved"
    assert response.json()["settings"]["assistant_model_id"] == "gpt-4.1-mini"
    assert response.json()["settings"]["image_model_id"] == "gpt-image-2"
    assert response.json()["settings"]["tts_provider"] == "openai"
    assert response.json()["settings"]["mimo_base_url"] == "https://tts.example.com/v1"
    assert response.json()["settings"]["mimo_api_key"] == "sk-tts-saved"
    assert response.json()["settings"]["mimo_tts_model"] == "mimo-v2.5-tts"
    assert response.json()["settings"]["mimo_tts_voice"] == "冰糖"
    assert response.json()["settings"]["mimo_tts_style_prompt"] == "请自然朗读。"
    assert response.json()["settings"]["mimo_tts_concurrency"] == "12"
    assert response.json()["settings"]["tts_concurrency"] == "9"
    assert response.json()["settings"]["openai_tts_base_url"] == "https://api.openai.com/v1"
    assert response.json()["settings"]["openai_tts_api_key"] == "sk-openai-tts"
    assert response.json()["settings"]["openai_tts_model"] == "gpt-4o-mini-tts"
    assert response.json()["settings"]["openai_tts_voice"] == "alloy"
    assert response.json()["settings"]["openai_tts_instructions"] == "请自然朗读。"
    assert response.json()["settings"]["openai_tts_speed"] == "1.15"


def test_patch_settings_rejects_excessive_delay(client):
    response = client.patch(
        "/api/settings",
        json={"dry_run_step_delay_ms": 10_001},
    )

    assert response.status_code == 422


def test_patch_settings_rejects_invalid_tts_concurrency(client):
    too_low = client.patch("/api/settings", json={"mimo_tts_concurrency": 0})
    too_high = client.patch("/api/settings", json={"mimo_tts_concurrency": 51})
    generic_too_low = client.patch("/api/settings", json={"tts_concurrency": 0})

    assert too_low.status_code == 422
    assert too_high.status_code == 422
    assert generic_too_low.status_code == 422


def test_patch_settings_rejects_invalid_tts_provider_and_openai_speed(client):
    invalid_provider = client.patch("/api/settings", json={"tts_provider": "unknown"})
    invalid_speed = client.patch("/api/settings", json={"openai_tts_speed": 4.1})

    assert invalid_provider.status_code == 422
    assert invalid_speed.status_code == 422


def test_get_system_metrics(client):
    response = client.get("/api/system/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["disk_free_gb"], float)
    assert isinstance(payload["disk_total_gb"], float)
    assert isinstance(payload["cpu_percent"], float)
    assert isinstance(payload["memory_available_gb"], float)
    assert isinstance(payload["memory_total_gb"], float)


def test_settings_reports_youtube_cookies_file_state(client, tmp_path, monkeypatch):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tplaceholder\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("YOUTUBE_COOKIES_PATH", str(cookies_file))

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["config"]["youtube_cookies_file"] is True


def test_settings_reports_invalid_youtube_cookies_file_as_unavailable(
    client, tmp_path, monkeypatch
):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("ffmpeg-output\n", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_COOKIES_PATH", str(cookies_file))

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["config"]["youtube_cookies_file"] is False


def test_settings_reports_assistant_saved_llm_configuration(client, db_session):
    repo = TaskRepository(db_session)
    repo.update_app_settings(
        {
            "assistant_base_url": "https://api.example.com/v1",
            "assistant_api_key": "sk-saved",
            "mimo_base_url": "https://tts.example.com/v1",
            "mimo_api_key": "sk-tts-saved",
        }
    )

    response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["api2key_base_url"] is True
    assert payload["config"]["llm_key"] is True
    assert payload["config"]["tts_base_url"] is True
    assert payload["config"]["tts_api_key"] is True


def test_settings_reports_openai_tts_configuration_for_selected_provider(client, db_session):
    repo = TaskRepository(db_session)
    repo.update_app_settings(
        {
            "tts_provider": "openai",
            "openai_tts_base_url": "https://api.openai.com/v1",
            "openai_tts_api_key": "sk-openai-tts",
        }
    )

    response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()["config"]
    assert payload["tts_base_url"] is True
    assert payload["tts_api_key"] is True


def test_cancel_task_returns_conflict_for_completed_task(client, db_session):
    completed_task = _create_completed_task(db_session, SourceType.LOCAL, "/videos/demo.mp4")
    task_id = completed_task.id

    response = client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 409
    assert "cannot be cancelled" in response.json()["detail"]

    detail_response = client.get(f"/api/tasks/{task_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "success"


def test_cancel_task_returns_updated_task_detail_for_unfinished_task(client, db_session):
    repo = TaskRepository(db_session)
    pending_task = repo.create_task(SourceType.LOCAL, "/videos/pending.mp4")

    response = client.post(f"/api/tasks/{pending_task.id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == pending_task.id
    assert payload["status"] == "cancelled"


def test_retry_task_returns_conflict_for_success_task(client, db_session):
    completed_task = _create_completed_task(db_session, SourceType.YOUTUBE, "https://youtu.be/demo-retry")
    task_id = completed_task.id

    detail_response = client.get(f"/api/tasks/{task_id}")
    before_logs = client.get(f"/api/tasks/{task_id}/logs").json()["total"]

    response = client.post(f"/api/tasks/{task_id}/retry")

    assert response.status_code == 409
    assert "cannot be retried" in response.json()["detail"]

    after_detail = client.get(f"/api/tasks/{task_id}")
    after_logs = client.get(f"/api/tasks/{task_id}/logs").json()["total"]
    assert detail_response.json()["status"] == "success"
    assert after_detail.json()["status"] == "success"
    assert after_logs == before_logs


def test_retry_youtube_task_failed_at_translate_routes_to_processing_runner(
    client,
    db_session,
    monkeypatch,
):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-retry-translate")
    for step in task.steps[:5]:
        repo.update_step_status(step, TaskStatus.SUCCESS, 100)
    translate_step = task.steps[5]
    repo.update_step_status(translate_step, TaskStatus.FAILED, 100, "translate failed")
    repo.update_task_status(
        task,
        TaskStatus.FAILED,
        current_step="translate",
        error_summary="translate failed",
    )
    calls = {"download": [], "processing": [], "dry_run": []}

    class WorkflowRunnerStub:
        def __init__(self, repo_arg, adapter=None):
            self.repo = repo_arg

        def run_task(self, task_id):
            calls["processing"].append(task_id)

    class DryRunRunnerStub:
        def __init__(self, repo_arg):
            self.repo = repo_arg

        def run_task(self, task_id):
            calls["dry_run"].append(task_id)

    monkeypatch.setattr("backend.app.api.tasks.run_download_task", lambda task_id: calls["download"].append(task_id))
    monkeypatch.setattr("backend.app.api.tasks.WorkflowRunner", WorkflowRunnerStub, raising=False)
    monkeypatch.setattr("backend.app.api.tasks.DryRunRunner", DryRunRunnerStub)

    response = client.post(f"/api/tasks/{task.id}/retry")

    assert response.status_code == 200
    assert calls == {"download": [], "processing": [task.id], "dry_run": []}


def test_retry_youtube_task_failed_at_download_routes_to_download_runner(
    client,
    db_session,
    monkeypatch,
):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-retry-download")
    repo.update_step_status(task.steps[0], TaskStatus.SUCCESS, 100)
    repo.update_step_status(task.steps[1], TaskStatus.FAILED, 100, "download failed")
    repo.update_task_status(
        task,
        TaskStatus.FAILED,
        current_step="download_video",
        error_summary="download failed",
    )
    calls = {"download": [], "processing": [], "dry_run": []}

    class WorkflowRunnerStub:
        def __init__(self, repo_arg, adapter=None):
            self.repo = repo_arg

        def run_task(self, task_id):
            calls["processing"].append(task_id)

    class DryRunRunnerStub:
        def __init__(self, repo_arg):
            self.repo = repo_arg

        def run_task(self, task_id):
            calls["dry_run"].append(task_id)

    monkeypatch.setattr("backend.app.api.tasks.run_download_task", lambda task_id: calls["download"].append(task_id))
    monkeypatch.setattr("backend.app.api.tasks.WorkflowRunner", WorkflowRunnerStub, raising=False)
    monkeypatch.setattr("backend.app.api.tasks.DryRunRunner", DryRunRunnerStub)

    response = client.post(f"/api/tasks/{task.id}/retry")

    assert response.status_code == 200
    assert calls == {"download": [task.id], "processing": [], "dry_run": []}


def test_retry_failed_youtube_task_restarts_real_download_runner(client, db_session, monkeypatch):
    runner_calls: list[int] = []

    def fake_run_download_task(task_id: int) -> None:
        runner_calls.append(task_id)

    monkeypatch.setattr("backend.app.api.tasks.run_download_task", fake_run_download_task)

    create_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/retry-demo"},
    )
    task_id = create_response.json()["id"]
    assert runner_calls == [task_id]

    repo = TaskRepository(db_session)
    task = repo.get_task(task_id)
    assert task is not None
    download_step = next(step for step in task.steps if step.name == "download_video")
    repo.update_step_status(download_step, TaskStatus.FAILED, 100, "download failed")
    repo.update_task_status(
        task,
        TaskStatus.FAILED,
        current_step="download_video",
        progress=10,
        error_summary="download failed",
    )

    response = client.post(f"/api/tasks/{task_id}/retry")

    assert response.status_code == 200
    assert runner_calls == [task_id, task_id]
    assert response.json()["status"] == "running"
    assert response.json()["current_step"] == "download_video"


def test_retry_youtube_task_failed_at_import_restarts_download_stage_from_start(
    client,
    db_session,
    monkeypatch,
):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-retry-import")
    import_step = task.steps[0]
    repo.update_step_status(import_step, TaskStatus.FAILED, 100, "import failed")
    repo.update_task_status(
        task,
        TaskStatus.FAILED,
        current_step="import",
        error_summary="import failed",
    )
    calls = []

    class DownloadRunnerStub:
        def __init__(self, repo_arg):
            self.repo = repo_arg

        def start(self, task_id):
            calls.append(("start", task_id))

    monkeypatch.setattr("backend.app.api.tasks.DownloadRunner", DownloadRunnerStub)
    monkeypatch.setattr("backend.app.api.tasks.run_download_task", lambda task_id: calls.append(("run", task_id)))

    response = client.post(f"/api/tasks/{task.id}/retry")

    assert response.status_code == 200
    assert calls == [("start", task.id), ("run", task.id)]


def test_retry_cancelled_youtube_task_in_download_stage_routes_to_download_runner(
    client,
    db_session,
    monkeypatch,
):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo-cancelled-download")
    repo.update_step_status(task.steps[0], TaskStatus.SUCCESS, 100)
    repo.update_step_status(task.steps[1], TaskStatus.CANCELLED, 25)
    repo.update_task_status(
        task,
        TaskStatus.CANCELLED,
        current_step="download_video",
        progress=9,
    )
    calls = []

    class DownloadRunnerStub:
        def __init__(self, repo_arg):
            self.repo = repo_arg

        def start(self, task_id):
            calls.append(("start", task_id))

    class WorkflowRunnerStub:
        def __init__(self, repo_arg, adapter=None):
            self.repo = repo_arg

        def run_task(self, task_id):
            calls.append(("processing", task_id))

    monkeypatch.setattr("backend.app.api.tasks.DownloadRunner", DownloadRunnerStub)
    monkeypatch.setattr("backend.app.api.tasks.WorkflowRunner", WorkflowRunnerStub)
    monkeypatch.setattr("backend.app.api.tasks.run_download_task", lambda task_id: calls.append(("run", task_id)))

    response = client.post(f"/api/tasks/{task.id}/retry")

    assert response.status_code == 200
    assert calls == [("start", task.id), ("run", task.id)]


def test_retry_step_resets_target_and_following_steps_and_clears_artifacts(
    client,
    db_session,
    monkeypatch,
):
    completed_task = _create_completed_task(db_session, SourceType.LOCAL, "/videos/demo-step-retry.mp4")
    task_id = completed_task.id
    repo = TaskRepository(db_session)
    task = repo.get_task(task_id)
    assert task is not None
    translate_step = next(step for step in task.steps if step.name == "translate")
    generate_metadata_step = next(step for step in task.steps if step.name == "generate_metadata")
    translated_artifacts_before = [artifact.id for artifact in task.artifacts if artifact.step_id == translate_step.id]
    assert translated_artifacts_before

    calls = {"dry_run": [], "processing": [], "download": []}

    class DryRunRunnerStub:
        def __init__(self, repo_arg):
            self.repo = repo_arg

        def run_task(self, task_id):
            calls["dry_run"].append(task_id)

    class WorkflowRunnerStub:
        def __init__(self, repo_arg, adapter=None):
            self.repo = repo_arg

        def run_task(self, task_id):
            calls["processing"].append(task_id)

    monkeypatch.setattr("backend.app.api.tasks.DryRunRunner", DryRunRunnerStub)
    monkeypatch.setattr("backend.app.api.tasks.WorkflowRunner", WorkflowRunnerStub)
    monkeypatch.setattr("backend.app.api.tasks.run_download_task", lambda task_id: calls["download"].append(task_id))

    response = client.post(f"/api/tasks/{task_id}/steps/{translate_step.id}/retry")

    assert response.status_code == 200
    payload = response.json()
    step_statuses = {step["name"]: step for step in payload["steps"]}
    assert payload["status"] == "pending"
    assert payload["current_step"] == "translate"
    assert step_statuses["translate"]["status"] == "pending"
    assert step_statuses["translate"]["retry_count"] == 1
    assert step_statuses["generate_metadata"]["status"] == "pending"
    assert calls == {"dry_run": [task_id], "processing": [], "download": []}

    reloaded_task = repo.get_task(task_id)
    assert reloaded_task is not None
    remaining_artifact_step_ids = {artifact.step_id for artifact in reloaded_task.artifacts}
    assert translate_step.id not in remaining_artifact_step_ids
    assert generate_metadata_step.id not in remaining_artifact_step_ids


def test_retry_step_routes_download_stage_for_youtube_task(
    client,
    db_session,
    monkeypatch,
):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/retry-step-download")
    repo.update_step_status(task.steps[0], TaskStatus.SUCCESS, 100)
    download_step = task.steps[1]
    repo.update_step_status(download_step, TaskStatus.SUCCESS, 100)
    repo.update_task_status(task, TaskStatus.SUCCESS, current_step="upload_subtitle", progress=100)
    calls = []

    class DownloadRunnerStub:
        def __init__(self, repo_arg):
            self.repo = repo_arg

        def start(self, task_id):
            calls.append(("start", task_id))

    monkeypatch.setattr("backend.app.api.tasks.DownloadRunner", DownloadRunnerStub)
    monkeypatch.setattr("backend.app.api.tasks.run_download_task", lambda task_id: calls.append(("run", task_id)))

    response = client.post(f"/api/tasks/{task.id}/steps/{download_step.id}/retry")

    assert response.status_code == 200
    assert calls == [("start", task.id), ("run", task.id)]


def test_retry_step_returns_conflict_for_running_task(client, db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.LOCAL, "/videos/running-step.mp4")
    repo.update_task_status(task, TaskStatus.RUNNING, current_step="translate", progress=42)
    target_step = next(step for step in task.steps if step.name == "translate")

    response = client.post(f"/api/tasks/{task.id}/steps/{target_step.id}/retry")

    assert response.status_code == 409
    assert "cannot retry steps while task is running" in response.json()["detail"]


def test_retry_step_rejects_manual_upload_steps(client, db_session):
    completed_task = _create_completed_task(db_session, SourceType.LOCAL, "/videos/manual-step.mp4")
    upload_step = next(step for step in completed_task.steps if step.name == "upload_video")

    response = client.post(f"/api/tasks/{completed_task.id}/steps/{upload_step.id}/retry")

    assert response.status_code == 409
    assert "Manual upload steps" in response.json()["detail"]


def test_bilibili_upload_starts_background_manual_steps(client, db_session, monkeypatch):
    completed_task = _create_completed_task(db_session, SourceType.LOCAL, "/videos/manual-upload.mp4")
    calls = []

    def run_manual_upload_task_stub(task_id, account_id=None):
        calls.append((task_id, account_id))

    monkeypatch.setattr("backend.app.api.tasks.run_manual_upload_task", run_manual_upload_task_stub)

    response = client.post(f"/api/tasks/{completed_task.id}/bilibili-upload")

    assert response.status_code == 200
    payload = response.json()
    step_statuses = {step["name"]: step for step in payload["steps"]}
    assert payload["status"] == "running"
    assert payload["progress"] == 100
    assert payload["current_step"] == "upload_video"
    assert step_statuses["upload_video"]["status"] == "pending"
    assert step_statuses["upload_subtitle"]["status"] == "pending"
    assert payload["metadata"]["upload_status"] == "pending"
    assert calls == [(completed_task.id, None)]
    assert "cookies" not in payload["metadata"]


def test_bilibili_upload_accepts_selected_active_bilibili_account(client, db_session, monkeypatch):
    completed_task = _create_completed_task(db_session, SourceType.LOCAL, "/videos/account-upload.mp4")
    account = AccountBinding(
        platform="bilibili",
        platform_user_id="10086",
        nickname="UP 主",
        status="active",
        is_primary=0,
        cookie_summary="已保存关键 Cookie",
        cookies_json='{"SESSDATA":"secret","bili_jct":"csrf","DedeUserID":"10086"}',
    )
    db_session.add(account)
    db_session.commit()
    calls = []

    def run_manual_upload_task_stub(task_id, account_id=None):
        calls.append((task_id, account_id))

    monkeypatch.setattr("backend.app.api.tasks.run_manual_upload_task", run_manual_upload_task_stub)

    response = client.post(
        f"/api/tasks/{completed_task.id}/bilibili-upload",
        json={"account_id": account.id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert calls == [(completed_task.id, account.id)]


def test_bilibili_upload_rejects_invalid_selected_account(client, db_session):
    completed_task = _create_completed_task(db_session, SourceType.LOCAL, "/videos/bad-account-upload.mp4")
    inactive = AccountBinding(
        platform="bilibili",
        platform_user_id="inactive",
        nickname="Inactive UP",
        status="unbound",
        is_primary=0,
        cookies_json="{}",
    )
    other_platform = AccountBinding(
        platform="youtube",
        platform_user_id="yt-user",
        nickname="YouTube",
        status="active",
        is_primary=0,
        cookies_json="{}",
    )
    db_session.add_all([inactive, other_platform])
    db_session.commit()

    missing_response = client.post(
        f"/api/tasks/{completed_task.id}/bilibili-upload",
        json={"account_id": 9999},
    )
    inactive_response = client.post(
        f"/api/tasks/{completed_task.id}/bilibili-upload",
        json={"account_id": inactive.id},
    )
    other_platform_response = client.post(
        f"/api/tasks/{completed_task.id}/bilibili-upload",
        json={"account_id": other_platform.id},
    )

    assert missing_response.status_code == 404
    assert inactive_response.status_code == 409
    assert "not active" in inactive_response.json()["detail"]
    assert other_platform_response.status_code == 409
    assert "not a Bilibili" in other_platform_response.json()["detail"]


def test_bilibili_upload_requires_finished_processing(client, db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.LOCAL, "/videos/not-ready.mp4")
    repo.update_task_status(task, TaskStatus.RUNNING, current_step="sync_preview", progress=80)

    response = client.post(f"/api/tasks/{task.id}/bilibili-upload")

    assert response.status_code == 409
    assert "not ready" in response.json()["detail"]


def test_bilibili_upload_requires_preview_and_metadata(client, db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.LOCAL, "/videos/missing-preview.mp4")
    for step in task.steps:
        if step.name not in {"upload_video", "upload_subtitle"}:
            repo.update_step_status(step, TaskStatus.SUCCESS, 100)
    repo.update_task_status(task, TaskStatus.SUCCESS, current_step="generate_metadata", progress=100)

    response = client.post(f"/api/tasks/{task.id}/bilibili-upload")

    assert response.status_code == 409
    assert "preview video and submission metadata" in response.json()["detail"]


def test_task_logs_support_pagination_metadata(client, db_session):
    completed_task = _create_completed_task(db_session, SourceType.YOUTUBE, "https://youtu.be/demo")
    task_id = completed_task.id

    response = client.get(f"/api/tasks/{task_id}/logs", params={"limit": 1, "offset": 0})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["total"] >= 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0


def test_update_metadata_validates_provided_fields(client):
    create_response = client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/demo"},
    )
    task_id = create_response.json()["id"]

    response = client.patch(
        f"/api/tasks/{task_id}/metadata",
        json={"title": "", "category": "", "tags": list(range(21))},
    )

    assert response.status_code == 422


def test_list_videos_returns_completed_tasks(client, db_session):
    client.post(
        "/api/tasks",
        json={"source_type": "youtube", "input": "https://youtu.be/pending-demo"},
    )
    completed_task = _create_completed_task(db_session, SourceType.YOUTUBE, "https://youtu.be/completed-demo")

    response = client.get("/api/videos")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == completed_task.id
    assert items[0]["status"] == "success"
