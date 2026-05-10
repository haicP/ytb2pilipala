from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

import backend.app.runner.download as download_module
from backend.app.domain import SourceType, TaskStatus
from backend.app.repositories import TaskRepository
from backend.app.runner.download import (
    DownloadResult,
    DownloadRunner,
    YtDlpDownloader,
    run_download_task,
)


class AiWorkflowAdapterStub:
    pass


class FakeDownloader:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def download(self, task):
        if self.should_fail:
            raise RuntimeError("download failed")
        return DownloadResult(
            video_path=f"data/artifacts/{task.id}/source.mp4",
            thumbnail_path=f"data/artifacts/{task.id}/thumbnail.jpg",
            metadata={"mode": "test"},
        )


MINIMAL_JPEG_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000201010201010202020202020202030503"
    "0303030306040507060607070706080a100a09080809120d0e0b101512131514111417181a211c17192019"
    "14141d271d20222623282a2a2a191f2d302d283025282a28ffc0000b080001000101011100ffc400140001"
    "00000000000000000000000000000009ffc40014100100000000000000000000000000000000ffda000801"
    "0100003f00d2cf20ffd9"
)


def _write_test_video(path: Path) -> None:
    process = download_module.subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            "1",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise AssertionError(f"failed to prepare test video: {detail}")


def test_download_runner_downloads_video_and_thumbnail_then_waits_for_next_step(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    runner = DownloadRunner(repo, downloader=FakeDownloader())

    runner.start(task.id)
    runner.run_task(task.id)
    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.status == TaskStatus.PENDING
    assert loaded.current_step == "extract_audio"
    assert loaded.steps[0].status == TaskStatus.SUCCESS
    assert loaded.steps[1].status == TaskStatus.SUCCESS
    assert loaded.steps[2].status == TaskStatus.SUCCESS
    assert loaded.steps[3].name == "extract_audio"
    assert loaded.steps[3].status == TaskStatus.PENDING
    assert {artifact.artifact_type for artifact in loaded.artifacts} == {"video", "thumbnail"}
    assert any("开始下载视频" in log.message for log in loaded.logs)
    assert any("下载视频与缩略图完成" in log.message for log in loaded.logs)


def test_download_runner_keeps_thumbnail_step_skipped_when_disabled(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/no-thumbnail")
    thumbnail_step = next(step for step in task.steps if step.name == "download_thumbnail")
    repo.update_step_status(thumbnail_step, TaskStatus.SKIPPED, 100, "由本次提交设置跳过")
    runner = DownloadRunner(repo, downloader=FakeDownloader())

    runner.start(task.id)
    runner.run_task(task.id)
    loaded = repo.get_task(task.id)

    assert loaded is not None
    loaded_thumbnail_step = next(step for step in loaded.steps if step.name == "download_thumbnail")
    assert loaded_thumbnail_step.status == TaskStatus.SKIPPED
    assert {artifact.artifact_type for artifact in loaded.artifacts} == {"video"}
    assert any("按本次提交设置跳过下载缩略图" in log.message for log in loaded.logs)


def test_download_runner_marks_download_step_failed_when_downloader_fails(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    runner = DownloadRunner(repo, downloader=FakeDownloader(should_fail=True))

    runner.start(task.id)
    runner.run_task(task.id)
    loaded = repo.get_task(task.id)

    assert loaded is not None
    assert loaded.status == TaskStatus.FAILED
    assert loaded.current_step == "download_video"
    assert loaded.steps[0].status == TaskStatus.SUCCESS
    assert loaded.steps[1].status == TaskStatus.FAILED
    assert "download failed" in loaded.error_summary
    assert any(log.level == "error" and "download failed" in log.message for log in loaded.logs)


def test_run_download_task_continues_workflow_after_thumbnail_download(
    db_session, monkeypatch, tmp_path
):
    testing_session_local = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    storage_root = tmp_path / "artifacts"

    def fake_download(_self, task):
        task_dir = storage_root / str(task.id)
        task_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = task_dir / "source.jpg"
        thumbnail_path.write_bytes(MINIMAL_JPEG_BYTES)
        video_path = task_dir / "source.mp4"
        _write_test_video(video_path)
        return DownloadResult(
            video_path=str(video_path),
            thumbnail_path=str(thumbnail_path),
            metadata={"mode": "test"},
        )

    monkeypatch.setattr(download_module, "SessionLocal", testing_session_local)
    monkeypatch.setattr(YtDlpDownloader, "download", fake_download)

    class WorkflowRunnerStub:
        def __init__(self, repo, adapter=None):
            self.repo = repo
            self.adapter = adapter

        def run_task(self, task_id):
            task_dir = storage_root / str(task_id)
            (task_dir / "source.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nsource subtitle\n\n",
                encoding="utf-8",
            )
            (task_dir / "zh.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\ntranslated subtitle\n\n",
                encoding="utf-8",
            )
            (task_dir / "zh_voice.wav").write_bytes(b"voice")
            (task_dir / "preview.mp4").write_bytes(b"preview")
            loaded = self.repo.get_task(task_id)
            assert loaded is not None
            self.repo.update_task_status(loaded, TaskStatus.SUCCESS, current_step="upload_subtitle", progress=100)
            self.repo.append_log(task_id, None, "info", "processing 工作流已完成")

    monkeypatch.setattr(
        download_module,
        "WorkflowRunner",
        WorkflowRunnerStub,
    )
    monkeypatch.setattr(download_module, "AiWorkflowAdapter", AiWorkflowAdapterStub)

    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    DownloadRunner(repo).start(task.id)

    run_download_task(task.id)
    verification_session = testing_session_local()
    try:
        loaded = TaskRepository(verification_session).get_task(task.id)
    finally:
        verification_session.close()

    assert loaded is not None
    assert loaded.status == TaskStatus.SUCCESS
    assert loaded.current_step == "upload_subtitle"
    assert all(Path(artifact.path).is_file() for artifact in loaded.artifacts)
    assert (storage_root / str(task.id) / "source.srt").is_file()
    assert (storage_root / str(task.id) / "zh.srt").is_file()
    assert (storage_root / str(task.id) / "zh_voice.wav").is_file()
    assert (storage_root / str(task.id) / "preview.mp4").is_file()
    assert any("下载视频与缩略图完成" in log.message for log in loaded.logs)
    assert any("processing 工作流已完成" in log.message for log in loaded.logs)


def test_yt_dlp_downloader_uses_cookies_file_when_present(tmp_path, monkeypatch):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tplaceholder\n",
        encoding="utf-8",
    )
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        task_dir = tmp_path / "artifacts" / "1"
        (task_dir / "source.mp4").write_text("video", encoding="utf-8")
        (task_dir / "source.jpg").write_text("thumbnail", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("backend.app.runner.download.subprocess.run", fake_run)
    downloader = YtDlpDownloader(storage_root=tmp_path / "artifacts", cookies_path=cookies_file)

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    downloader.download(TaskStub())

    assert "--cookies" in calls[0]
    assert str(cookies_file) in calls[0]


def test_yt_dlp_downloader_enables_node_js_runtime_when_available(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        task_dir = tmp_path / "artifacts" / "1"
        (task_dir / "source.mp4").write_text("video", encoding="utf-8")
        (task_dir / "source.jpg").write_text("thumbnail", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    def fake_which(binary):
        if binary == "node":
            return "/usr/bin/node"
        if binary == "yt-dlp":
            return "/usr/local/bin/yt-dlp"
        return None

    monkeypatch.setattr(download_module.shutil, "which", fake_which)
    monkeypatch.setattr(download_module.subprocess, "run", fake_run)
    downloader = YtDlpDownloader(
        storage_root=tmp_path / "artifacts",
        cookies_path=tmp_path / "missing-cookies.txt",
    )

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    downloader.download(TaskStub())

    js_runtime_index = calls[0].index("--js-runtimes")
    assert calls[0][js_runtime_index + 1] == "node"


def test_yt_dlp_downloader_rejects_invalid_cookies_file_before_running_yt_dlp(
    tmp_path, monkeypatch
):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("ffmpeg-output\n", encoding="utf-8")
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(download_module.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr("backend.app.runner.download.subprocess.run", fake_run)
    downloader = YtDlpDownloader(storage_root=tmp_path / "artifacts", cookies_path=cookies_file)

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    with pytest.raises(RuntimeError) as exc:
        downloader.download(TaskStub())

    detail = str(exc.value)
    assert "YouTube cookies 文件不可用" in detail
    assert "Netscape HTTP Cookie File" in detail
    assert "ffmpeg-output" not in detail
    assert calls == []


def test_yt_dlp_downloader_requests_mp4_output(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        task_dir = tmp_path / "artifacts" / "1"
        (task_dir / "source.mp4").write_text("video", encoding="utf-8")
        (task_dir / "source.jpg").write_text("thumbnail", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("backend.app.runner.download.subprocess.run", fake_run)
    downloader = YtDlpDownloader(
        storage_root=tmp_path / "artifacts",
        cookies_path=tmp_path / "missing-cookies.txt",
    )

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    downloader.download(TaskStub())

    assert "--recode-video" in calls[0]
    assert "mp4" in calls[0]


def test_yt_dlp_downloader_skips_missing_cookies_file(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        task_dir = tmp_path / "artifacts" / "1"
        (task_dir / "source.mp4").write_text("video", encoding="utf-8")
        (task_dir / "source.jpg").write_text("thumbnail", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("backend.app.runner.download.subprocess.run", fake_run)
    downloader = YtDlpDownloader(
        storage_root=tmp_path / "artifacts",
        cookies_path=tmp_path / "missing-cookies.txt",
    )

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    downloader.download(TaskStub())

    assert "--cookies" not in calls[0]


def test_run_download_task_hands_off_pending_youtube_task_to_workflow_runner(db_session, monkeypatch):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/demo")
    runner = DownloadRunner(repo, downloader=FakeDownloader())
    runner.start(task.id)

    calls = []

    class SessionStub:
        def close(self):
            pass

    class RepoStub:
        def __init__(self, session):
            self.session = session

        def get_task(self, task_id):
            return repo.get_task(task_id)

        def add_artifact(self, *args, **kwargs):
            return repo.add_artifact(*args, **kwargs)

        def update_step_status(self, *args, **kwargs):
            return repo.update_step_status(*args, **kwargs)

        def append_log(self, *args, **kwargs):
            return repo.append_log(*args, **kwargs)

        def update_task_status(self, *args, **kwargs):
            return repo.update_task_status(*args, **kwargs)

    class WorkflowRunnerStub:
        def __init__(self, repo_arg, adapter=None):
            self.repo = repo_arg
            self.adapter = adapter

        def run_task(self, task_id):
            calls.append((task_id, isinstance(self.adapter, AiWorkflowAdapterStub)))

    monkeypatch.setattr("backend.app.runner.download.SessionLocal", lambda: SessionStub())
    monkeypatch.setattr("backend.app.runner.download.TaskRepository", RepoStub)
    monkeypatch.setattr("backend.app.runner.download.YtDlpDownloader", lambda: FakeDownloader())
    monkeypatch.setattr("backend.app.runner.download.WorkflowRunner", WorkflowRunnerStub)
    monkeypatch.setattr("backend.app.runner.download.AiWorkflowAdapter", AiWorkflowAdapterStub)

    run_download_task(task.id)

    assert calls == [(task.id, True)]
def test_yt_dlp_downloader_fails_fast_when_yt_dlp_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(download_module.shutil, "which", lambda binary: None)
    downloader = YtDlpDownloader(
        storage_root=tmp_path / "artifacts",
        cookies_path=tmp_path / "missing-cookies.txt",
    )

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    try:
        downloader.download(TaskStub())
    except RuntimeError as exc:
        assert "yt-dlp 不可用" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_yt_dlp_downloader_fails_fast_when_js_runtime_is_missing(tmp_path, monkeypatch):
    def fake_which(binary):
        if binary in {"node", "deno", "bun", "qjs", "quickjs"}:
            return None
        return f"/usr/bin/{binary}"

    monkeypatch.setattr(download_module.shutil, "which", fake_which)
    downloader = YtDlpDownloader(
        storage_root=tmp_path / "artifacts",
        cookies_path=tmp_path / "missing-cookies.txt",
    )

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    try:
        downloader.download(TaskStub())
    except RuntimeError as exc:
        detail = str(exc)
        assert "JavaScript 运行时" in detail
        assert "Node.js" in detail
    else:
        raise AssertionError("expected RuntimeError")


def test_yt_dlp_downloader_wraps_youtube_challenge_failure_with_actionable_message(
    tmp_path, monkeypatch
):
    def fake_run(command, capture_output, text, check):
        class Result:
            returncode = 1
            stdout = ""
            stderr = (
                "WARNING: [youtube] demo: n challenge solving failed: Some formats may be missing. "
                "Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. "
                "WARNING: Only images are available for download. "
                "ERROR: [youtube] demo: Requested format is not available."
            )

        return Result()

    monkeypatch.setattr(download_module.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(download_module.subprocess, "run", fake_run)
    downloader = YtDlpDownloader(
        storage_root=tmp_path / "artifacts",
        cookies_path=tmp_path / "missing-cookies.txt",
    )

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    try:
        downloader.download(TaskStub())
    except RuntimeError as exc:
        detail = str(exc)
        assert "YouTube 挑战校验失败" in detail
        assert "Node.js" in detail
        assert "yt-dlp-ejs" in detail
    else:
        raise AssertionError("expected RuntimeError")


def test_yt_dlp_downloader_prioritizes_auth_error_when_youtube_requires_sign_in(
    tmp_path, monkeypatch
):
    def fake_run(command, capture_output, text, check):
        class Result:
            returncode = 1
            stdout = ""
            stderr = (
                "WARNING: [youtube] demo: n challenge solving failed: Some formats may be missing. "
                "WARNING: [youtube] No title found in player responses; falling back to title from initial data. "
                "ERROR: [youtube] demo: Sign in to confirm you're not a bot. "
                "Use --cookies-from-browser or --cookies for the authentication."
            )

        return Result()

    monkeypatch.setattr(download_module.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(download_module.subprocess, "run", fake_run)
    downloader = YtDlpDownloader(
        storage_root=tmp_path / "artifacts",
        cookies_path=tmp_path / "missing-cookies.txt",
    )

    class TaskStub:
        id = 1
        input = "https://youtu.be/demo"

    try:
        downloader.download(TaskStub())
    except RuntimeError as exc:
        detail = str(exc)
        assert "YouTube 认证失效或缺少有效登录态" in detail
        assert "cookies.txt" in detail
        assert "挑战校验失败" not in detail
    else:
        raise AssertionError("expected RuntimeError")
