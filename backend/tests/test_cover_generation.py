import base64
from types import SimpleNamespace

from backend.app.cover_generation import OpenAICoverClient
from backend.app.domain import SourceType
from backend.app.repositories import TaskRepository


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeImages:
    def __init__(self):
        self.generate_calls = []
        self.edit_calls = []

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(PNG_BYTES).decode("ascii"))])

    def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(PNG_BYTES).decode("ascii"))])


class FakeOpenAI:
    def __init__(self):
        self.images = FakeImages()


def _create_task(db_session):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/cover-demo")
    loaded = repo.get_task(task.id)
    assert loaded is not None
    return loaded


def test_text_cover_generation_saves_cover_and_updates_metadata(db_session):
    task = _create_task(db_session)
    fake = FakeOpenAI()

    result = OpenAICoverClient(db_session, client=fake).generate_from_text(task, "科技感封面")

    repo = TaskRepository(db_session)
    loaded = repo.get_task(task.id)
    assert loaded is not None
    assert loaded.metadata_record is not None
    assert loaded.metadata_record.cover_artifact_id == result.artifact_id
    cover = next(artifact for artifact in loaded.artifacts if artifact.id == result.artifact_id)
    assert cover.artifact_type == "cover"
    assert cover.path.endswith(".png")
    assert fake.images.generate_calls[0]["model"] == "gpt-image-2"
    assert fake.images.generate_calls[0]["prompt"] == "科技感封面"


def test_cover_generation_uses_saved_image_model_id(db_session):
    task = _create_task(db_session)
    repo = TaskRepository(db_session)
    repo.update_app_settings({"image_model_id": "custom-image-model"})
    fake = FakeOpenAI()

    OpenAICoverClient(db_session, client=fake).generate_from_text(task, "科技感封面")

    assert fake.images.generate_calls[0]["model"] == "custom-image-model"


def test_image_cover_generation_uses_uploaded_reference(db_session):
    task = _create_task(db_session)
    fake = FakeOpenAI()

    OpenAICoverClient(db_session, client=fake).generate_from_image(
        task,
        "保留人物主体，增强点击感",
        reference_bytes=b"uploaded-image",
        reference_filename="reference.jpg",
    )

    image_arg = fake.images.edit_calls[0]["image"]
    assert image_arg == ("reference.jpg", b"uploaded-image")


def test_image_cover_generation_falls_back_to_thumbnail(db_session, tmp_path):
    repo = TaskRepository(db_session)
    task = repo.create_task(SourceType.YOUTUBE, "https://youtu.be/thumbnail-demo")
    thumbnail_path = tmp_path / "thumbnail.jpg"
    thumbnail_path.write_bytes(b"thumbnail")
    repo.add_artifact(task.id, None, "thumbnail", str(thumbnail_path))
    loaded = repo.get_task(task.id)
    assert loaded is not None
    fake = FakeOpenAI()

    OpenAICoverClient(db_session, client=fake).generate_from_image(loaded, "基于缩略图生成封面")

    image_arg = fake.images.edit_calls[0]["image"]
    assert image_arg == ("thumbnail.jpg", b"thumbnail")
