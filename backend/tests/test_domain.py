from backend.app.domain import STEP_DEFINITIONS, StepName, TaskStatus, create_initial_steps


def test_step_definitions_match_required_workflow_order():
    assert [step.name for step in STEP_DEFINITIONS] == [
        StepName.IMPORT,
        StepName.DOWNLOAD_VIDEO,
        StepName.DOWNLOAD_THUMBNAIL,
        StepName.EXTRACT_AUDIO,
        StepName.TRANSCRIBE,
        StepName.TRANSLATE,
        StepName.SYNTHESIZE_VOICE,
        StepName.SYNC_PREVIEW,
        StepName.GENERATE_METADATA,
        StepName.UPLOAD_VIDEO,
        StepName.UPLOAD_SUBTITLE,
    ]


def test_create_initial_steps_marks_only_import_ready():
    steps = create_initial_steps()

    assert steps[0].status == TaskStatus.PENDING
    assert all(step.status == TaskStatus.PENDING for step in steps)
    assert [step.order for step in steps] == list(range(1, 12))
