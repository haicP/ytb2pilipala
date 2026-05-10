import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app.bilibili_upload import BilibiliUploadClient, BilibiliUploadError
from backend.app.domain import SourceType
from backend.app.models import AccountBinding
from backend.app.repositories import TaskRepository
from backend.app.runner.manual_upload import ManualUploadRunner


class FakeBilibiliHttpClient:
    def __init__(
        self,
        *,
        subtitle_code: int = 0,
        cover_code: int = 0,
        endpoint: str = "https://upos.example.com",
        upos_uri: str = "upos://bucket/fake-file.mp4",
    ):
        self.subtitle_code = subtitle_code
        self.cover_code = cover_code
        self.endpoint = endpoint
        self.upos_uri = upos_uri
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    @staticmethod
    def _response(method: str, url: str, status_code: int, *, json_payload=None, headers=None):
        return httpx.Response(
            status_code,
            json=json_payload,
            headers=headers,
            request=httpx.Request(method, url),
        )

    def get(self, url, params=None, cookies=None, **kwargs):
        self.requests.append(("GET", url, {"params": params or {}, "cookies": cookies or {}}))
        if "nav" in url:
            return self._response("GET", url, 200, json_payload={"code": 0, "data": {"isLogin": True}})
        if "preupload" in url:
            return self._response(
                "GET",
                url,
                200,
                json_payload={
                    "endpoint": self.endpoint,
                    "upos_uri": self.upos_uri,
                    "auth": "upos-auth",
                    "biz_id": 20002,
                    "chunk_size": 4,
                },
            )
        if "typeid" in url:
            return self._response("GET", url, 200, json_payload={"code": 0, "data": [{"tid": 201}]})
        if "web-interface/view" in url:
            return self._response(
                "GET",
                url,
                200,
                json_payload={
                    "code": 0,
                    "data": {"bvid": "BV1real", "aid": 10001, "pages": [{"cid": 20002}]},
                },
            )
        return self._response("GET", url, 404, json_payload={"code": -404, "message": "not found"})

    def post(self, url, params=None, data=None, json=None, files=None, cookies=None, headers=None, **kwargs):
        self.requests.append(
            (
                "POST",
                url,
                {
                    "params": params or {},
                    "data": data or {},
                    "json": json or {},
                    "files": bool(files),
                    "cookies": cookies or {},
                    "headers": headers or {},
                },
            )
        )
        if "cover/up" in url:
            if self.cover_code != 0:
                return self._response(
                    "POST",
                    url,
                    200,
                    json_payload={"code": self.cover_code, "message": "请求错误"},
                )
            return self._response(
                "POST",
                url,
                200,
                json_payload={"code": 0, "data": {"url": "https://i0.hdslb.com/cover.jpg"}},
            )
        if "upos.example.com" in url and params and "uploads" in params:
            return self._response("POST", url, 200, json_payload={"upload_id": "upload-1"})
        if "upos.example.com" in url and params and params.get("uploadId") == "upload-1":
            return self._response("POST", url, 200, json_payload={"OK": 1})
        if "upos-cs-upcdnqn.bilivideo.com" in url and params and "uploads" in params:
            return self._response("POST", url, 200, json_payload={"upload_id": "upload-1"})
        if "upos-cs-upcdnqn.bilivideo.com" in url and params and params.get("uploadId") == "upload-1":
            return self._response("POST", url, 200, json_payload={"OK": 1})
        if "add/v3" in url:
            return self._response(
                "POST",
                url,
                200,
                json_payload={"code": 0, "data": {"bvid": "BV1real", "aid": 10001}},
            )
        if "subtitle/draft/save" in url:
            if self.subtitle_code == 0:
                return self._response("POST", url, 200, json_payload={"code": 0, "data": {}})
            return self._response(
                "POST",
                url,
                200,
                json_payload={"code": self.subtitle_code, "message": "subtitle rejected"},
            )
        return self._response("POST", url, 404, json_payload={"code": -404, "message": "not found"})

    def put(self, url, params=None, content=None, cookies=None, headers=None, **kwargs):
        self.requests.append(
            (
                "PUT",
                url,
                {
                    "params": params or {},
                    "content_length": len(content or b""),
                    "cookies": cookies or {},
                    "headers": headers or {},
                },
            )
        )
        return self._response("PUT", url, 200, json_payload={}, headers={"etag": "etag-1"})


def _bind_account(
    db_session,
    *,
    platform_user_id: str = "10086",
    nickname: str = "UP 主",
    is_primary: int = 1,
    status: str = "active",
    session_value: str = "secret-session",
    csrf_value: str = "secret-csrf",
):
    account = AccountBinding(
        platform="bilibili",
        platform_user_id=platform_user_id,
        nickname=nickname,
        status=status,
        is_primary=is_primary,
        cookie_summary="已保存关键 Cookie",
        cookies_json=json.dumps(
            {"SESSDATA": session_value, "bili_jct": csrf_value, "DedeUserID": platform_user_id}
        ),
    )
    db_session.add(account)
    db_session.commit()
    return account


def _completed_upload_task(db_session, tmp_path: Path, *, with_subtitle: bool = True):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/source-url")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    preview = task_dir / "preview.mp4"
    preview.write_bytes(b"0123456789")
    thumbnail = task_dir / "cover.jpg"
    thumbnail.write_bytes(b"jpg")
    repo.add_artifact(task.id, None, "preview", str(preview))
    repo.add_artifact(task.id, None, "thumbnail", str(thumbnail))
    if with_subtitle:
        subtitle = task_dir / "zh.srt"
        subtitle.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n你好，世界\n",
            encoding="utf-8",
        )
        repo.add_artifact(task.id, None, "subtitle_translated", str(subtitle))
    loaded = repo.get_task(task.id)
    assert loaded is not None
    loaded.metadata_record.title = "真实投稿标题"
    loaded.metadata_record.description = "投稿简介"
    loaded.metadata_record.tags = '["技术","翻译"]'
    loaded.metadata_record.category = "科技"
    db_session.commit()
    return loaded


def test_bilibili_upload_client_posts_video_and_metadata(db_session, tmp_path):
    _bind_account(db_session)
    task = _completed_upload_task(db_session, tmp_path)
    fake_client = FakeBilibiliHttpClient()

    result = BilibiliUploadClient(db_session, client=fake_client).upload_video(task)

    assert result.bvid == "BV1real"
    assert result.aid == "10001"
    assert result.cid == "20002"
    assert result.filename == "fake-file"
    cover_request = next(request for request in fake_client.requests if "cover/up" in request[1])
    assert cover_request[2]["files"] is False
    assert cover_request[2]["data"]["cover"].startswith("data:image/jpeg;base64,")
    add_request = next(request for request in fake_client.requests if "add/v3" in request[1])
    submit_json = add_request[2]["json"]
    assert submit_json["copyright"] == 2
    assert submit_json["source"] == "https://youtu.be/source-url"
    assert "来源：https://youtu.be/source-url" in submit_json["desc"]
    assert submit_json["tid"] == 201
    assert submit_json["human_type2"] == 1012
    assert submit_json["videos"][0]["filename"] == "fake-file"
    assert submit_json["videos"][0]["cid"] == 20002
    assert "secret-session" not in str(submit_json)


def test_bilibili_upload_requires_bound_cookies(db_session, tmp_path):
    task = _completed_upload_task(db_session, tmp_path)

    with pytest.raises(BilibiliUploadError, match="未绑定可用的 B 站账号"):
        BilibiliUploadClient(db_session, client=FakeBilibiliHttpClient()).upload_video(task)


def test_bilibili_upload_wraps_cover_error_with_stage(db_session, tmp_path):
    _bind_account(db_session)
    task = _completed_upload_task(db_session, tmp_path)

    with pytest.raises(BilibiliUploadError, match="B 站封面上传失败：请求错误"):
        BilibiliUploadClient(db_session, client=FakeBilibiliHttpClient(cover_code=-1)).upload_video(task)


def test_bilibili_upload_uses_default_upos_endpoint_for_relative_uri(db_session, tmp_path):
    _bind_account(db_session)
    task = _completed_upload_task(db_session, tmp_path)
    fake_client = FakeBilibiliHttpClient(endpoint="", upos_uri="/ugcever/demo.mp4")

    result = BilibiliUploadClient(db_session, client=fake_client).upload_video(task)

    assert result.filename == "demo"
    assert any(
        request[0] == "POST" and request[1] == "https://upos-cs-upcdnqn.bilivideo.com/ugcever/demo.mp4"
        for request in fake_client.requests
    )


def test_bilibili_upload_uses_selected_account_cookies(db_session, tmp_path):
    _bind_account(
        db_session,
        platform_user_id="primary",
        session_value="primary-session",
        csrf_value="primary-csrf",
    )
    selected = _bind_account(
        db_session,
        platform_user_id="selected",
        nickname="Selected UP",
        is_primary=0,
        session_value="selected-session",
        csrf_value="selected-csrf",
    )
    task = _completed_upload_task(db_session, tmp_path)
    fake_client = FakeBilibiliHttpClient()

    BilibiliUploadClient(db_session, client=fake_client, account_id=selected.id).upload_video(task)

    nav_request = next(request for request in fake_client.requests if "nav" in request[1])
    add_request = next(request for request in fake_client.requests if "add/v3" in request[1])
    assert nav_request[2]["cookies"]["SESSDATA"] == "selected-session"
    assert add_request[2]["params"]["csrf"] == "selected-csrf"


def test_manual_runner_keeps_video_success_when_subtitle_fails(db_session, tmp_path):
    _bind_account(db_session)
    repo = TaskRepository(db_session)
    task = _completed_upload_task(db_session, tmp_path)
    fake_client = FakeBilibiliHttpClient(subtitle_code=-1)

    ManualUploadRunner(repo, uploader=BilibiliUploadClient(db_session, client=fake_client)).run_task(task.id)

    loaded = repo.get_task(task.id)
    assert loaded is not None
    steps = {step.name: step for step in loaded.steps}
    assert loaded.status == "success"
    assert loaded.metadata_record.bilibili_video_id == "BV1real"
    assert loaded.metadata_record.upload_status == "uploaded"
    assert steps["upload_video"].status == "success"
    assert steps["upload_subtitle"].status == "failed"
    assert "secret-session" not in loaded.error_summary


def test_manual_runner_retries_only_subtitle_after_video_uploaded(db_session, tmp_path):
    _bind_account(db_session)
    repo = TaskRepository(db_session)
    task = _completed_upload_task(db_session, tmp_path)
    task.metadata_record.bilibili_video_id = "BV1existing"
    task.metadata_record.bilibili_aid = "10001"
    task.metadata_record.bilibili_cid = "20002"
    db_session.commit()
    fake_client = FakeBilibiliHttpClient()

    ManualUploadRunner(repo, uploader=BilibiliUploadClient(db_session, client=fake_client)).run_task(task.id)

    subtitle_request = next(request for request in fake_client.requests if "subtitle/draft/save" in request[1])
    subtitle_payload = json.loads(subtitle_request[2]["data"]["data"])
    assert not any("preupload" in request[1] for request in fake_client.requests)
    assert subtitle_request[2]["data"]["lan"] == "zh"
    assert subtitle_payload["lan"] == "zh"
    assert subtitle_payload["lan_doc"] == "中文（简体）"


def test_manual_runner_skips_missing_subtitle(db_session, tmp_path):
    _bind_account(db_session)
    repo = TaskRepository(db_session)
    task = _completed_upload_task(db_session, tmp_path, with_subtitle=False)

    ManualUploadRunner(repo, uploader=BilibiliUploadClient(db_session, client=FakeBilibiliHttpClient())).run_task(
        task.id
    )

    loaded = repo.get_task(task.id)
    assert loaded is not None
    steps = {step.name: step for step in loaded.steps}
    assert loaded.status == "success"
    assert loaded.metadata_record.bilibili_video_id == "BV1real"
    assert steps["upload_subtitle"].status == "skipped"
