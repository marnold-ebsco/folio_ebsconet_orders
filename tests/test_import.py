import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folio_import as imp  # noqa: E402

SINCE = "2026-09-30T14:00:00.000+00:00"


def job(hr, kind, status, started="2026-09-30T14:10:00.000+00:00"):
    return {"hrId": hr, "subordinationType": kind, "status": status,
            "startedDate": started}


def test_select_jobs_ignores_older_uploads_and_sorts():
    jobs = [job(3, "COMPOSITE_CHILD", "COMMITTED"),
            job(1, "COMPOSITE_PARENT", "ERROR", "2026-09-29T09:00:00.000+00:00"),
            job(2, "COMPOSITE_PARENT", "COMMITTED")]
    assert [j["hrId"] for j in imp.select_jobs(jobs, SINCE)] == [2, 3]


def test_finished_split_import():
    jobs = [job(1, "PARENT_SINGLE", "FILE_UPLOADED"),
            job(2, "COMPOSITE_PARENT", "COMMITTED"),
            job(3, "COMPOSITE_CHILD", "COMMITTED")]
    assert imp.jobs_finished(jobs)


def test_not_finished_while_child_running_or_missing():
    running = [job(2, "COMPOSITE_PARENT", "COMMITTED"),
               job(3, "COMPOSITE_CHILD", "PROCESSING_IN_PROGRESS")]
    assert not imp.jobs_finished(running)
    assert not imp.jobs_finished([job(2, "COMPOSITE_PARENT", "COMMITTED")])
    assert not imp.jobs_finished([])


def test_finished_unsplit_import():
    assert imp.jobs_finished([job(1, "PARENT_SINGLE", "COMMITTED")])
    assert not imp.jobs_finished([job(1, "PARENT_SINGLE", "FILE_UPLOADED")])


def test_error_child_counts_as_finished():
    jobs = [job(2, "COMPOSITE_PARENT", "COMMITTED"), job(3, "COMPOSITE_CHILD", "ERROR")]
    assert imp.jobs_finished(jobs)
