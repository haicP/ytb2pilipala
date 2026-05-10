import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.accounts import BILIBILI_HEADERS
from backend.app.models import AccountBinding, Artifact, SubmissionMetadata, Task


BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_COVER_UPLOAD_URL = "https://member.bilibili.com/x/vu/web/cover/up"
BILIBILI_PREUPLOAD_URL = "https://member.bilibili.com/preupload"
BILIBILI_ADD_URL = "https://member.bilibili.com/x/vu/web/add/v3"
BILIBILI_VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
BILIBILI_TYPE_PREDICT_URL = "https://member.bilibili.com/x/vupre/web/archive/typeid"
BILIBILI_SUBTITLE_SAVE_URL = "https://api.bilibili.com/x/v2/dm/subtitle/draft/save"
BILIBILI_SUBTITLE_LANG_ZH = "zh"
BILIBILI_SUBTITLE_LANG_ZH_DOC = "中文（简体）"

TECH_HUMAN_TYPE2 = 1012
FALLBACK_TECH_TYPE_ID = 201
MAX_TITLE_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 2000
MAX_TAG_COUNT = 10
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_UPOS_ENDPOINT = "https://upos-cs-upcdnqn.bilivideo.com"


class BilibiliUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class BilibiliVideoUploadResult:
    bvid: str
    aid: str
    cid: str
    filename: str
    cover_url: str


@dataclass(frozen=True)
class BilibiliSubtitleResult:
    skipped: bool
    message: str


@dataclass(frozen=True)
class BilibiliUploadedFile:
    filename: str
    cid: str


def _json_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise BilibiliUploadError("B 站接口返回了无法解析的响应") from exc
    if not isinstance(payload, dict):
        raise BilibiliUploadError("B 站接口返回格式异常")
    return payload


def _raise_for_bilibili_code(payload: dict[str, Any], fallback_message: str) -> None:
    code = payload.get("code", 0)
    if code != 0:
        message = str(payload.get("message") or payload.get("msg") or fallback_message)
        raise BilibiliUploadError(message)


def _raise_stage_error(stage: str, exc: Exception) -> None:
    if isinstance(exc, BilibiliUploadError):
        raise BilibiliUploadError(f"{stage}：{exc}") from exc
    if isinstance(exc, httpx.HTTPStatusError):
        raise BilibiliUploadError(f"{stage}：HTTP {exc.response.status_code}") from exc
    if isinstance(exc, httpx.HTTPError):
        raise BilibiliUploadError(f"{stage}：网络请求失败") from exc
    raise BilibiliUploadError(f"{stage}：{exc}") from exc


def _loads_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _srt_timestamp_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _srt_to_bilibili_body(text: str) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    blocks = [block.strip() for block in text.replace("\r\n", "\n").split("\n\n") if block.strip()]
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_line = next((line for line in lines if "-->" in line), "")
        if not timing_line:
            continue
        start_raw, end_raw = [part.strip().split(" ")[0] for part in timing_line.split("-->", 1)]
        content_index = lines.index(timing_line) + 1
        content = "\n".join(lines[content_index:]).strip()
        if not content:
            continue
        body.append(
            {
                "from": _srt_timestamp_to_seconds(start_raw),
                "to": _srt_timestamp_to_seconds(end_raw),
                "location": 2,
                "content": content,
            }
        )
        if not body:
            raise BilibiliUploadError("中文字幕文件为空或格式无法识别")
    body.sort(key=lambda item: item["from"])
    return {
        "font_size": 0.4,
        "font_color": "#FFFFFF",
        "background_alpha": 0.5,
        "background_color": "#9C27B0",
        "Stroke": "none",
        "body": body,
    }


class BilibiliUploadClient:
    def __init__(
        self,
        session: Session,
        client: httpx.Client | None = None,
        account_id: int | None = None,
    ):
        self.session = session
        self.client = client or httpx.Client(timeout=60.0, headers=BILIBILI_HEADERS)
        self.account_id = account_id

    def upload_video(self, task: Task) -> BilibiliVideoUploadResult:
        metadata = self._require_metadata(task)
        cookies = self._active_cookies()
        csrf = self._csrf(cookies)
        try:
            self._ensure_login(cookies)
        except Exception as exc:
            _raise_stage_error("B 站登录校验失败", exc)

        preview = self._latest_artifact(task, "preview")
        if preview is None:
            raise BilibiliUploadError("预览视频未就绪，无法上传 B 站")
        video_path = Path(preview.path)
        if not video_path.is_file():
            raise BilibiliUploadError("预览视频文件不存在，无法上传 B 站")

        try:
            cover_url = self._upload_cover(task, metadata, cookies, csrf)
        except Exception as exc:
            _raise_stage_error("B 站封面上传失败", exc)
        try:
            uploaded_file = self._upload_video_file(video_path, cookies, csrf)
        except Exception as exc:
            _raise_stage_error("B 站视频文件上传失败", exc)
        type_id = self._predict_type_id(metadata, cookies)
        submit_payload = self._build_submit_payload(task, metadata, uploaded_file, cover_url, type_id, csrf)
        try:
            submit_response = self.client.post(
                BILIBILI_ADD_URL,
                params={"csrf": csrf},
                json=submit_payload,
                cookies=cookies,
            )
            submit_response.raise_for_status()
            submit_payload_json = _json_payload(submit_response)
            _raise_for_bilibili_code(submit_payload_json, "B 站稿件投递失败")
        except Exception as exc:
            _raise_stage_error("B 站稿件投递失败", exc)
        data = submit_payload_json.get("data")
        if not isinstance(data, dict):
            raise BilibiliUploadError("B 站稿件投递响应缺少 data")

        bvid = str(data.get("bvid") or "")
        aid = str(data.get("aid") or "")
        if not bvid and aid:
            bvid = self._fetch_view_identifier(cookies, aid=aid).get("bvid", "")
        if not aid and bvid:
            aid = self._fetch_view_identifier(cookies, bvid=bvid).get("aid", "")
        cid = str(data.get("cid") or uploaded_file.cid)
        if not cid and (bvid or aid):
            cid = self._fetch_view_identifier(cookies, bvid=bvid, aid=aid).get("cid", "")
        if not bvid:
            raise BilibiliUploadError("B 站稿件投递成功但未返回 BV 号")

        return BilibiliVideoUploadResult(
            bvid=bvid,
            aid=aid,
            cid=cid,
            filename=uploaded_file.filename,
            cover_url=cover_url,
        )

    def upload_subtitle(self, task: Task) -> BilibiliSubtitleResult:
        metadata = self._require_metadata(task)
        if not metadata.bilibili_video_id:
            raise BilibiliUploadError("B 站稿件 BV 号缺失，无法上传字幕")
        subtitle = self._latest_artifact(task, "subtitle_translated")
        if subtitle is None:
            return BilibiliSubtitleResult(skipped=True, message="暂无中文字幕产物，已跳过字幕上传")
        subtitle_path = Path(subtitle.path)
        if not subtitle_path.is_file():
            return BilibiliSubtitleResult(skipped=True, message="中文字幕文件不存在，已跳过字幕上传")
        if not metadata.bilibili_cid:
            cookies_for_view = self._active_cookies()
            view_data = self._fetch_view_identifier(cookies_for_view, bvid=metadata.bilibili_video_id)
            metadata.bilibili_aid = view_data.get("aid", metadata.bilibili_aid)
            metadata.bilibili_cid = view_data.get("cid", metadata.bilibili_cid)
            self.session.commit()
        if not metadata.bilibili_cid:
            raise BilibiliUploadError("B 站稿件 cid 缺失，无法上传字幕")

        cookies = self._active_cookies()
        csrf = self._csrf(cookies)
        try:
            self._ensure_login(cookies)
        except Exception as exc:
            _raise_stage_error("B 站登录校验失败", exc)
        subtitle_body = _srt_to_bilibili_body(subtitle_path.read_text(encoding="utf-8"))
        response = self.client.post(
            BILIBILI_SUBTITLE_SAVE_URL,
            data={
                "type": 1,
                "oid": metadata.bilibili_cid,
                "lan": BILIBILI_SUBTITLE_LANG_ZH,
                "submit": "true",
                "sign": "true",
                "bvid": metadata.bilibili_video_id,
                "csrf": csrf,
                "data": json.dumps(
                    {
                        "lan": BILIBILI_SUBTITLE_LANG_ZH,
                        "lan_doc": BILIBILI_SUBTITLE_LANG_ZH_DOC,
                        "subtitle_url": "",
                        "body": subtitle_body["body"],
                        "font_size": subtitle_body["font_size"],
                        "font_color": subtitle_body["font_color"],
                        "background_alpha": subtitle_body["background_alpha"],
                        "background_color": subtitle_body["background_color"],
                        "Stroke": subtitle_body["Stroke"],
                    },
                    ensure_ascii=False,
                ),
            },
            cookies=cookies,
        )
        response.raise_for_status()
        payload = _json_payload(response)
        _raise_for_bilibili_code(payload, "B 站字幕上传失败")
        return BilibiliSubtitleResult(skipped=False, message="中文字幕已提交 B 站")

    def _active_cookies(self) -> dict[str, str]:
        if self.account_id is not None:
            account = self.session.get(AccountBinding, self.account_id)
            if account is None:
                raise BilibiliUploadError("指定的 B 站账号不存在，请重新选择投稿账号")
            if account.platform != "bilibili" or account.status != "active":
                raise BilibiliUploadError("指定的 B 站账号不可用，请重新选择投稿账号")
        else:
            statement = (
                select(AccountBinding)
                .where(AccountBinding.platform == "bilibili")
                .where(AccountBinding.status == "active")
                .where(AccountBinding.is_primary == 1)
                .order_by(AccountBinding.updated_at.desc())
            )
            account = self.session.execute(statement).scalars().first()
        if account is None:
            raise BilibiliUploadError("未绑定可用的 B 站账号，请先扫码登录")
        cookies = _loads_json_object(account.cookies_json)
        required = {"SESSDATA", "bili_jct", "DedeUserID"}
        missing = sorted(name for name in required if not cookies.get(name))
        if missing:
            raise BilibiliUploadError(f"B 站登录凭据缺少关键 Cookie：{', '.join(missing)}，请重新扫码登录")
        return {key: str(value) for key, value in cookies.items()}

    @staticmethod
    def _csrf(cookies: dict[str, str]) -> str:
        csrf = cookies.get("bili_jct", "")
        if not csrf:
            raise BilibiliUploadError("B 站 CSRF 凭据缺失，请重新扫码登录")
        return csrf

    def _ensure_login(self, cookies: dict[str, str]) -> None:
        response = self.client.get(BILIBILI_NAV_URL, cookies=cookies)
        response.raise_for_status()
        payload = _json_payload(response)
        data = payload.get("data") if payload.get("code") == 0 else None
        if not isinstance(data, dict) or not data.get("isLogin"):
            raise BilibiliUploadError("B 站登录已失效，请重新扫码绑定账号")

    @staticmethod
    def _require_metadata(task: Task) -> SubmissionMetadata:
        if task.metadata_record is None:
            raise BilibiliUploadError("投稿信息缺失，无法上传 B 站")
        return task.metadata_record

    @staticmethod
    def _latest_artifact(task: Task, artifact_type: str) -> Artifact | None:
        artifacts = [artifact for artifact in task.artifacts if artifact.artifact_type == artifact_type]
        return max(artifacts, key=lambda item: (item.created_at, item.id)) if artifacts else None

    def _cover_artifact(self, task: Task, metadata: SubmissionMetadata) -> Artifact | None:
        if metadata.cover_artifact_id is not None:
            for artifact in task.artifacts:
                if artifact.id == metadata.cover_artifact_id:
                    return artifact
        return self._latest_artifact(task, "thumbnail")

    def _upload_cover(
        self,
        task: Task,
        metadata: SubmissionMetadata,
        cookies: dict[str, str],
        csrf: str,
    ) -> str:
        cover = self._cover_artifact(task, metadata)
        if cover is None:
            return ""
        cover_path = Path(cover.path)
        if not cover_path.is_file():
            return ""
        suffix = cover_path.suffix.lower()
        mime_type = "image/png" if suffix == ".png" else "image/jpeg"
        encoded_cover = base64.b64encode(cover_path.read_bytes()).decode("ascii")
        response = self.client.post(
            BILIBILI_COVER_UPLOAD_URL,
            data={"csrf": csrf, "cover": f"data:{mime_type};base64,{encoded_cover}"},
            cookies=cookies,
        )
        response.raise_for_status()
        payload = _json_payload(response)
        _raise_for_bilibili_code(payload, "B 站封面上传失败")
        data = payload.get("data")
        return str(data.get("url") if isinstance(data, dict) else "")

    def _upload_video_file(self, video_path: Path, cookies: dict[str, str], csrf: str) -> BilibiliUploadedFile:
        file_size = video_path.stat().st_size
        preupload_response = self.client.get(
            BILIBILI_PREUPLOAD_URL,
            params={
                "name": video_path.name,
                "size": file_size,
                "r": "upos",
                "profile": "ugcupos/bup",
                "ssl": 0,
                "version": "2.14.0",
                "build": 2082400,
                "webVersion": "2.0.0",
                "csrf": csrf,
            },
            cookies=cookies,
        )
        preupload_response.raise_for_status()
        upload_info = _json_payload(preupload_response)
        endpoint = str(upload_info.get("endpoint") or "").rstrip("/")
        upos_uri = str(upload_info.get("upos_uri") or "")
        auth = str(upload_info.get("auth") or "")
        biz_id = str(upload_info.get("biz_id") or "")
        if not upos_uri or not auth:
            raise BilibiliUploadError("B 站预上传响应缺少分片上传参数")
        endpoint = endpoint or DEFAULT_UPOS_ENDPOINT
        upload_path = upos_uri.removeprefix("upos://")
        if upload_path.startswith("http://") or upload_path.startswith("https://"):
            upload_url = upload_path
        else:
            upload_path = upload_path if upload_path.startswith("/") else f"/{upload_path}"
            endpoint = endpoint if urlparse(endpoint).scheme else f"https://{endpoint.lstrip('/')}"
            upload_url = f"{endpoint.rstrip('/')}{upload_path}"
        object_name = upload_path.split("?")[0].split("/")[-1]
        filename = Path(object_name).stem
        chunk_size = int(upload_info.get("chunk_size") or UPLOAD_CHUNK_SIZE)
        headers = {"X-Upos-Auth": auth}

        create_response = self.client.post(
            upload_url,
            params={"uploads": "", "output": "json"},
            headers=headers,
            cookies=cookies,
        )
        create_response.raise_for_status()
        create_payload = _json_payload(create_response)
        upload_id = str(create_payload.get("upload_id") or create_payload.get("uploadId") or "")
        if not upload_id:
            raise BilibiliUploadError("B 站分片上传未返回 upload_id")

        parts: list[dict[str, int | str]] = []
        chunks = max((file_size + chunk_size - 1) // chunk_size, 1)
        with video_path.open("rb") as video_file:
            for index in range(chunks):
                start = index * chunk_size
                data = video_file.read(chunk_size)
                end = start + len(data)
                part_number = index + 1
                part_response = self.client.put(
                    upload_url,
                    params={
                        "partNumber": part_number,
                        "uploadId": upload_id,
                        "chunk": index,
                        "chunks": chunks,
                        "size": len(data),
                        "start": start,
                        "end": end,
                        "total": file_size,
                    },
                    content=data,
                    headers=headers,
                    cookies=cookies,
                )
                part_response.raise_for_status()
                etag = part_response.headers.get("etag", "")
                parts.append({"partNumber": part_number, "eTag": etag})

        complete_response = self.client.post(
            upload_url,
            params={
                "output": "json",
                "name": object_name,
                "profile": "ugcupos/bup",
                "uploadId": upload_id,
                "biz_id": biz_id,
            },
            json={"parts": parts},
            headers=headers,
            cookies=cookies,
        )
        complete_response.raise_for_status()
        try:
            complete_payload = _json_payload(complete_response)
            _raise_for_bilibili_code(complete_payload, "B 站分片上传结束失败")
        except BilibiliUploadError:
            raise
        complete_data = complete_payload.get("data") if isinstance(complete_payload, dict) else None
        if not biz_id and isinstance(complete_data, dict):
            biz_id = str(complete_data.get("biz_id") or complete_data.get("cid") or "")
        if not biz_id:
            raise BilibiliUploadError("B 站预上传响应缺少稿件 cid/biz_id")
        return BilibiliUploadedFile(filename=filename, cid=biz_id)

    def _predict_type_id(
        self,
        metadata: SubmissionMetadata,
        cookies: dict[str, str],
    ) -> int:
        try:
            response = self.client.get(
                BILIBILI_TYPE_PREDICT_URL,
                params={"title": metadata.title[:MAX_TITLE_LENGTH], "desc": metadata.description[:200]},
                cookies=cookies,
            )
            response.raise_for_status()
            payload = _json_payload(response)
            data = payload.get("data") if payload.get("code") == 0 else None
            candidates = data if isinstance(data, list) else data.get("typelist", []) if isinstance(data, dict) else []
            for candidate in candidates:
                if isinstance(candidate, dict):
                    type_id = candidate.get("tid") or candidate.get("id") or candidate.get("typeid")
                    if type_id:
                        return int(type_id)
        except Exception:
            return FALLBACK_TECH_TYPE_ID
        return FALLBACK_TECH_TYPE_ID

    def _build_submit_payload(
        self,
        task: Task,
        metadata: SubmissionMetadata,
        uploaded_file: BilibiliUploadedFile,
        cover_url: str,
        type_id: int,
        csrf: str,
    ) -> dict[str, Any]:
        copyright_type = 1 if metadata.copyright_type == 1 else 2
        description = metadata.description.strip()
        if copyright_type == 2 and task.input and task.input not in description:
            source_line = f"来源：{task.input}"
            description = f"{description}\n\n{source_line}".strip()
        tags = _loads_json_list(metadata.tags)[:MAX_TAG_COUNT]
        return {
            "copyright": copyright_type,
            "source": task.input if copyright_type == 2 else "",
            "tid": type_id,
            "human_type2": TECH_HUMAN_TYPE2,
            "title": metadata.title.strip()[:MAX_TITLE_LENGTH],
            "desc_format_id": 9999,
            "desc": description[:MAX_DESCRIPTION_LENGTH],
            "desc_v2": [],
            "tag": ",".join(tags),
            "cover": cover_url,
            "cover43": "",
            "dynamic": "",
            "recreate": -1,
            "interactive": 0,
            "act_reserve_create": 0,
            "no_disturbance": 0,
            "no_reprint": 1,
            "subtitle": {"open": 0, "lan": ""},
            "dolby": 0,
            "lossless_music": 0,
            "up_selection_reply": False,
            "up_close_reply": False,
            "up_close_danmu": False,
            "web_os": 3,
            "csrf": csrf,
            "videos": [
                {
                    "filename": uploaded_file.filename,
                    "title": metadata.title.strip()[:MAX_TITLE_LENGTH],
                    "desc": "",
                    "cid": int(uploaded_file.cid),
                }
            ],
        }

    def _fetch_view_identifier(
        self,
        cookies: dict[str, str],
        *,
        bvid: str = "",
        aid: str = "",
    ) -> dict[str, str]:
        params = {"bvid": bvid} if bvid else {"aid": aid}
        response = self.client.get(BILIBILI_VIEW_URL, params=params, cookies=cookies)
        response.raise_for_status()
        payload = _json_payload(response)
        _raise_for_bilibili_code(payload, "B 站稿件信息查询失败")
        data = payload.get("data")
        if not isinstance(data, dict):
            return {}
        pages = data.get("pages")
        cid = ""
        if isinstance(pages, list) and pages and isinstance(pages[0], dict):
            cid = str(pages[0].get("cid") or "")
        return {
            "bvid": str(data.get("bvid") or ""),
            "aid": str(data.get("aid") or ""),
            "cid": cid or str(data.get("cid") or ""),
        }
