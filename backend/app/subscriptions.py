import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from backend.app.domain import SourceType
from backend.app.models import SubscriptionChannel, SubscriptionVideo, utc_now
from backend.app.repositories import TaskRepository


@dataclass(frozen=True)
class ChannelInfo:
    source_url: str
    channel_id: str
    title: str
    thumbnail_url: str = ""


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    youtube_url: str
    title: str
    published_at: datetime | None = None
    thumbnail_url: str = ""


def _normalize_channel_input(input_value: str) -> str:
    stripped = input_value.strip()
    if not stripped:
        raise ValueError("请输入 YouTube 频道 URL、@handle 或 channel id")
    if stripped.startswith("@"):
        return f"https://www.youtube.com/{stripped}/videos"
    if stripped.startswith("UC") and "/" not in stripped:
        return f"https://www.youtube.com/channel/{stripped}/videos"
    parsed = urlparse(stripped)
    if parsed.scheme and parsed.netloc:
        return stripped
    raise ValueError("请输入有效的 YouTube 频道 URL、@handle 或 channel id")


def _video_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.endswith("youtu.be") and path_parts:
        return path_parts[0]
    if "youtube.com" in parsed.netloc:
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            return query_id
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
            return path_parts[1]
    return ""


def _parse_date(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _thumbnail_from_entry(entry: dict[str, object]) -> str:
    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list) and thumbnails:
        last = thumbnails[-1]
        if isinstance(last, dict):
            url = last.get("url")
            return str(url) if url else ""
    thumbnail = entry.get("thumbnail")
    return str(thumbnail) if thumbnail else ""


class YtDlpSubscriptionFetcher:
    def __init__(self, max_videos: int = 20):
        self.max_videos = max_videos

    def fetch(self, input_value: str) -> tuple[ChannelInfo, list[VideoInfo]]:
        if shutil.which("yt-dlp") is None:
            raise RuntimeError("yt-dlp 不可用，请先安装或修复 yt-dlp 可执行文件。")

        source_url = _normalize_channel_input(input_value)
        command = [
            "yt-dlp",
            "--flat-playlist",
            "--dump-single-json",
            "--playlist-end",
            str(self.max_videos),
            source_url,
        ]
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or "订阅同步失败"
            raise RuntimeError(detail[-1000:])

        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("yt-dlp 返回了无法解析的频道数据") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("yt-dlp 返回了无效的频道数据")

        channel_id = str(payload.get("channel_id") or payload.get("id") or source_url)
        channel = ChannelInfo(
            source_url=source_url,
            channel_id=channel_id,
            title=str(payload.get("channel") or payload.get("uploader") or payload.get("title") or channel_id),
            thumbnail_url=_thumbnail_from_entry(payload),
        )

        videos: list[VideoInfo] = []
        entries = payload.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                video_url = str(entry.get("url") or entry.get("webpage_url") or "")
                video_id = str(entry.get("id") or _video_id_from_url(video_url))
                if not video_id:
                    continue
                youtube_url = (
                    video_url
                    if video_url.startswith("http")
                    else f"https://www.youtube.com/watch?v={video_id}"
                )
                videos.append(
                    VideoInfo(
                        video_id=video_id,
                        youtube_url=youtube_url,
                        title=str(entry.get("title") or video_id),
                        published_at=_parse_date(entry.get("upload_date") or entry.get("timestamp")),
                        thumbnail_url=_thumbnail_from_entry(entry),
                    )
                )
        return channel, videos


class SubscriptionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_channels(self, keyword: str | None = None) -> list[SubscriptionChannel]:
        statement = (
            select(SubscriptionChannel)
            .options(joinedload(SubscriptionChannel.videos))
            .order_by(SubscriptionChannel.updated_at.desc(), SubscriptionChannel.id.desc())
        )
        if keyword:
            statement = statement.where(
                SubscriptionChannel.title.contains(keyword)
                | SubscriptionChannel.channel_id.contains(keyword)
                | SubscriptionChannel.source_url.contains(keyword)
            )
        return list(self.session.execute(statement).unique().scalars())

    def get_channel(self, channel_id: int) -> SubscriptionChannel | None:
        statement = (
            select(SubscriptionChannel)
            .where(SubscriptionChannel.id == channel_id)
            .options(joinedload(SubscriptionChannel.videos))
        )
        return self.session.execute(statement).unique().scalar_one_or_none()

    def upsert_channel(self, info: ChannelInfo) -> SubscriptionChannel:
        statement = select(SubscriptionChannel).where(SubscriptionChannel.channel_id == info.channel_id)
        channel = self.session.execute(statement).scalar_one_or_none()
        now = utc_now()
        if channel is None:
            channel = SubscriptionChannel(
                source_url=info.source_url,
                channel_id=info.channel_id,
                title=info.title,
                thumbnail_url=info.thumbnail_url,
                status="active",
                updated_at=now,
            )
            self.session.add(channel)
        else:
            channel.source_url = info.source_url
            channel.title = info.title
            channel.thumbnail_url = info.thumbnail_url
            channel.status = "active"
            channel.updated_at = now
        self.session.commit()
        loaded = self.get_channel(channel.id)
        if loaded is None:
            raise ValueError("Subscription channel not found after upsert")
        return loaded

    def set_channel_sync_result(self, channel: SubscriptionChannel, error_summary: str = "") -> SubscriptionChannel:
        channel.last_synced_at = utc_now()
        channel.error_summary = error_summary
        channel.updated_at = utc_now()
        self.session.commit()
        loaded = self.get_channel(channel.id)
        if loaded is None:
            raise ValueError(f"Subscription channel {channel.id} not found")
        return loaded

    def upsert_videos(self, channel: SubscriptionChannel, videos: list[VideoInfo]) -> None:
        now = utc_now()
        for info in videos:
            statement = select(SubscriptionVideo).where(SubscriptionVideo.video_id == info.video_id)
            video = self.session.execute(statement).scalar_one_or_none()
            if video is None:
                video = SubscriptionVideo(
                    channel_id=channel.id,
                    video_id=info.video_id,
                    youtube_url=info.youtube_url,
                    title=info.title,
                    published_at=info.published_at,
                    thumbnail_url=info.thumbnail_url,
                    updated_at=now,
                )
                self.session.add(video)
            else:
                video.channel_id = channel.id
                video.youtube_url = info.youtube_url
                video.title = info.title
                video.published_at = info.published_at
                video.thumbnail_url = info.thumbnail_url
                video.updated_at = now
        self.session.commit()

    def list_videos(self, status_filter: str | None = None, keyword: str | None = None) -> list[SubscriptionVideo]:
        statement = (
            select(SubscriptionVideo)
            .options(joinedload(SubscriptionVideo.channel), joinedload(SubscriptionVideo.task))
            .order_by(
                SubscriptionVideo.published_at.desc(),
                SubscriptionVideo.discovered_at.desc(),
                SubscriptionVideo.id.desc(),
            )
        )
        if status_filter:
            statement = statement.where(SubscriptionVideo.status == status_filter)
        if keyword:
            statement = statement.join(SubscriptionVideo.channel).where(
                or_(
                    SubscriptionVideo.title.contains(keyword),
                    SubscriptionVideo.video_id.contains(keyword),
                    SubscriptionChannel.title.contains(keyword),
                )
            )
        return list(self.session.execute(statement).unique().scalars())

    def get_video(self, video_id: int) -> SubscriptionVideo | None:
        statement = (
            select(SubscriptionVideo)
            .where(SubscriptionVideo.id == video_id)
            .options(joinedload(SubscriptionVideo.channel), joinedload(SubscriptionVideo.task))
        )
        return self.session.execute(statement).unique().scalar_one_or_none()

    def create_task_for_video(self, video_id: int) -> tuple[SubscriptionVideo, bool]:
        video = self.get_video(video_id)
        if video is None:
            raise ValueError(f"Subscription video {video_id} not found")
        if video.task_id is not None:
            return video, False

        task = TaskRepository(self.session).create_task(SourceType.YOUTUBE, video.youtube_url)
        video.task_id = task.id
        video.status = "queued"
        video.updated_at = utc_now()
        self.session.commit()
        loaded = self.get_video(video_id)
        if loaded is None:
            raise ValueError(f"Subscription video {video_id} not found")
        return loaded, True


class SubscriptionService:
    def __init__(self, repo: SubscriptionRepository, fetcher: YtDlpSubscriptionFetcher | None = None):
        self.repo = repo
        self.fetcher = fetcher or YtDlpSubscriptionFetcher()

    def subscribe_channel(self, input_value: str) -> SubscriptionChannel:
        channel_info, videos = self.fetcher.fetch(input_value)
        channel = self.repo.upsert_channel(channel_info)
        self.repo.upsert_videos(channel, videos)
        return self.repo.set_channel_sync_result(channel)

    def sync_channel(self, channel: SubscriptionChannel) -> SubscriptionChannel:
        try:
            channel_info, videos = self.fetcher.fetch(channel.source_url)
            refreshed = self.repo.upsert_channel(channel_info)
            self.repo.upsert_videos(refreshed, videos)
            return self.repo.set_channel_sync_result(refreshed)
        except Exception as exc:
            return self.repo.set_channel_sync_result(channel, str(exc))

    def sync_all(self) -> list[SubscriptionChannel]:
        channels = [channel for channel in self.repo.list_channels() if channel.status == "active"]
        return [self.sync_channel(channel) for channel in channels]
