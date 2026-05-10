from datetime import datetime, timezone

import pytest

from backend.app.subscriptions import ChannelInfo, SubscriptionService, VideoInfo


class FakeFetcher:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []

    def fetch(self, input_value: str):
        self.calls.append(input_value)
        if self.fail:
            raise RuntimeError("youtube unavailable")
        return (
            ChannelInfo(
                source_url="https://www.youtube.com/@demo/videos",
                channel_id="UCdemo",
                title="Demo Channel",
                thumbnail_url="https://i.ytimg.com/channel.jpg",
            ),
            [
                VideoInfo(
                    video_id="video-1",
                    youtube_url="https://www.youtube.com/watch?v=video-1",
                    title="First video",
                    published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    thumbnail_url="https://i.ytimg.com/video-1.jpg",
                )
            ],
        )


@pytest.fixture(autouse=True)
def disable_background_download(monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.subscriptions.run_download_task",
        lambda task_id: None,
        raising=False,
    )


@pytest.fixture(autouse=True)
def fake_subscription_fetcher(monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.subscriptions.SubscriptionService",
        lambda repo: SubscriptionService(repo, fetcher=FakeFetcher()),
    )


def test_create_channel_saves_channel_and_videos(client):
    response = client.post("/api/subscriptions/channels", json={"input": "@demo"})

    assert response.status_code == 201
    created = response.json()
    assert created["channel_id"] == "UCdemo"
    assert created["title"] == "Demo Channel"
    assert created["video_count"] == 1

    videos_response = client.get("/api/subscriptions/videos")
    assert videos_response.status_code == 200
    videos = videos_response.json()["items"]
    assert len(videos) == 1
    assert videos[0]["video_id"] == "video-1"
    assert videos[0]["channel_title"] == "Demo Channel"


def test_create_channel_deduplicates_channel_and_video(client):
    first = client.post("/api/subscriptions/channels", json={"input": "@demo"})
    second = client.post("/api/subscriptions/channels", json={"input": "@demo"})

    assert first.status_code == 201
    assert second.status_code == 201

    channels = client.get("/api/subscriptions/channels").json()["items"]
    videos = client.get("/api/subscriptions/videos").json()["items"]
    assert len(channels) == 1
    assert len(videos) == 1


def test_sync_failure_records_channel_error(client, monkeypatch):
    client.post("/api/subscriptions/channels", json={"input": "@demo"})
    monkeypatch.setattr(
        "backend.app.api.subscriptions.SubscriptionService",
        lambda repo: SubscriptionService(repo, fetcher=FakeFetcher(fail=True)),
    )

    response = client.post("/api/subscriptions/channels/sync")

    assert response.status_code == 200
    assert response.json()["items"][0]["error_summary"] == "youtube unavailable"


def test_create_task_for_subscription_video(client):
    client.post("/api/subscriptions/channels", json={"input": "@demo"})
    video = client.get("/api/subscriptions/videos").json()["items"][0]

    response = client.post(f"/api/subscriptions/videos/{video['id']}/create-task")

    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "queued"
    assert updated["task_id"] is not None

    duplicate = client.post(f"/api/subscriptions/videos/{video['id']}/create-task")
    assert duplicate.status_code == 200
    assert duplicate.json()["task_id"] == updated["task_id"]
