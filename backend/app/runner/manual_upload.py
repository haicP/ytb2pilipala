from backend.app.domain import TaskStatus
from backend.app.database import SessionLocal
from backend.app.repositories import TaskRepository
from backend.app.bilibili_upload import BilibiliUploadClient, BilibiliUploadError


MANUAL_UPLOAD_STEPS = ("upload_video", "upload_subtitle")


class ManualUploadRunner:
    def __init__(
        self,
        repo: TaskRepository,
        uploader: BilibiliUploadClient | None = None,
        account_id: int | None = None,
    ):
        self.repo = repo
        self.uploader = uploader or BilibiliUploadClient(repo.session, account_id=account_id)

    def run_task(self, task_id: int) -> None:
        task = self.repo.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        upload_steps = [
            step
            for step in sorted(task.steps, key=lambda item: item.order)
            if step.name in MANUAL_UPLOAD_STEPS
        ]
        if task.metadata_record is not None and task.metadata_record.bilibili_video_id:
            upload_steps = [step for step in upload_steps if step.name != "upload_video"]

        self.repo.update_task_status(
            task,
            TaskStatus.RUNNING,
            current_step=upload_steps[0].name if upload_steps else task.current_step,
            progress=task.progress,
        )

        for step in upload_steps:
            self.repo.update_step_status(step, TaskStatus.RUNNING, 10)
            self.repo.append_log(task.id, step.id, "info", f"开始手动执行：{step.label}")

            try:
                result = (
                    self.uploader.upload_video(task)
                    if step.name == "upload_video"
                    else self.uploader.upload_subtitle(task)
                )
            except BilibiliUploadError as exc:
                message = f"manual upload step {step.name} failed: {exc}"
                self.repo.update_step_status(step, TaskStatus.FAILED, 100, message)
                task_status = TaskStatus.SUCCESS if step.name == "upload_subtitle" else TaskStatus.FAILED
                self.repo.update_task_status(
                    task,
                    task_status,
                    current_step=step.name,
                    progress=100 if task_status == TaskStatus.SUCCESS else task.progress,
                    error_summary=message,
                )
                self.repo.append_log(task.id, step.id, "error", message)
                return
            except Exception as exc:
                message = f"manual upload step {step.name} failed: {exc}"
                self.repo.update_step_status(step, TaskStatus.FAILED, 100, message)
                self.repo.update_task_status(
                    task,
                    TaskStatus.FAILED,
                    current_step=step.name,
                    progress=task.progress,
                    error_summary=message,
                )
                self.repo.append_log(task.id, step.id, "error", message)
                return

            step_status = TaskStatus.SUCCESS

            if step.name == "upload_video" and task.metadata_record is not None:
                metadata = task.metadata_record
                metadata.upload_status = "uploaded"
                metadata.bilibili_video_id = result.bvid
                metadata.bilibili_aid = result.aid
                metadata.bilibili_cid = result.cid
                metadata.bilibili_filename = result.filename
                metadata.bilibili_cover_url = result.cover_url
                self.repo.session.commit()
                self.repo.append_log(task.id, step.id, "info", f"B 站稿件已投递：{result.bvid}")
            elif step.name == "upload_subtitle" and task.metadata_record is not None:
                if result.skipped:
                    step_status = TaskStatus.SKIPPED
                    self.repo.append_log(task.id, step.id, "info", result.message)
                else:
                    self.repo.append_log(task.id, step.id, "info", result.message)

            self.repo.update_step_status(step, step_status, 100)
            self.repo.append_log(task.id, step.id, "info", f"完成手动执行：{step.label}")
            self.repo.update_task_status(task, TaskStatus.RUNNING, current_step=step.name, progress=task.progress)

        self.repo.update_task_status(task, TaskStatus.SUCCESS, progress=100)
        self.repo.append_log(task.id, None, "info", "B 站手动上传流程已完成")


def run_manual_upload_task(task_id: int, account_id: int | None = None) -> None:
    session = SessionLocal()
    try:
        ManualUploadRunner(TaskRepository(session), account_id=account_id).run_task(task_id)
    finally:
        session.close()
