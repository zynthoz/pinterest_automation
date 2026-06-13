"""Tests for jobs API endpoints."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.database import get_db
from app.models.job import JobStatus, Job


def test_retry_failed_job_success():
    client = TestClient(app)

    mock_job = MagicMock(spec=Job)
    mock_job.id = 123
    mock_job.status = JobStatus.FAILED
    mock_job.product_id = 456
    mock_job.affiliate_url = "https://amazon.com/dp/B0CXYZ1234"
    mock_job.celery_task_id = "old-task-id"
    mock_job.current_step = "Some step"
    mock_job.started_at = datetime.now(timezone.utc)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_job

    # Override get_db dependency in FastAPI
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.jobs.run_pipeline") as mock_run_pipeline:
        mock_task = MagicMock()
        mock_task.id = "new-task-id"
        mock_run_pipeline.delay.return_value = mock_task

        response = client.post("/api/jobs/123/retry")

        assert response.status_code == 200
        assert mock_job.status == JobStatus.QUEUED
        assert mock_job.error is None
        assert mock_job.current_step == "Retrying..."
        assert mock_job.celery_task_id == "new-task-id"
        mock_run_pipeline.delay.assert_called_once_with(123)

    app.dependency_overrides.clear()


def test_retry_completed_job_success():
    client = TestClient(app)

    mock_job = MagicMock(spec=Job)
    mock_job.id = 124
    mock_job.status = JobStatus.COMPLETED
    mock_job.product_id = 456
    mock_job.affiliate_url = "https://amazon.com/dp/B0CXYZ1234"
    mock_job.celery_task_id = "old-task-id"
    mock_job.current_step = "Pin published successfully"
    mock_job.started_at = datetime.now(timezone.utc)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_job

    # Override get_db dependency in FastAPI
    app.dependency_overrides[get_db] = lambda: mock_db

    with patch("app.api.jobs.run_pipeline") as mock_run_pipeline:
        mock_task = MagicMock()
        mock_task.id = "new-task-id-2"
        mock_run_pipeline.delay.return_value = mock_task

        response = client.post("/api/jobs/124/retry")

        assert response.status_code == 200
        assert mock_job.status == JobStatus.QUEUED
        assert mock_job.error is None
        assert mock_job.current_step == "Retrying..."
        assert mock_job.celery_task_id == "new-task-id-2"
        mock_run_pipeline.delay.assert_called_once_with(124)

    app.dependency_overrides.clear()


def test_retry_active_job_fails():
    client = TestClient(app)

    mock_job = MagicMock(spec=Job)
    mock_job.id = 125
    mock_job.status = JobStatus.DOWNLOADING
    mock_job.product_id = 456
    mock_job.affiliate_url = "https://amazon.com/dp/B0CXYZ1234"
    mock_job.celery_task_id = "old-task-id"
    mock_job.current_step = "Downloading TikTok video"
    mock_job.started_at = datetime.now(timezone.utc)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_job

    # Override get_db dependency in FastAPI
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post("/api/jobs/125/retry")
    assert response.status_code == 400
    assert "Only failed or completed jobs can be retried" in response.json()["detail"]

    app.dependency_overrides.clear()


def test_delete_job_success():
    client = TestClient(app)

    mock_job = MagicMock(spec=Job)
    mock_job.id = 126
    mock_job.status = JobStatus.COMPLETED
    mock_job.celery_task_id = "some-task-id"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_job

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.delete("/api/jobs/126")
    assert response.status_code == 200
    assert response.json()["detail"] == "Job deleted successfully"
    mock_db.delete.assert_called_once_with(mock_job)
    mock_db.commit.assert_called_once()

    app.dependency_overrides.clear()
