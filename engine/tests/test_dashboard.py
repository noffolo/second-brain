from fastapi.testclient import TestClient
from unittest.mock import patch
from engine.dashboard import app

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Secondo Cervello - Pannello di controllo" in response.text

def test_get_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "running" in data
    assert "active_source" in data
    assert "queue_count" in data
    assert "queue_preview" in data
    assert "log_history" in data
    assert "log_tail" in data
    assert "schedule_time" in data

def test_post_schedule():
    with patch("engine.dashboard.set_schedule_time") as mock_set:
        mock_set.return_value = True
        response = client.post("/api/schedule", json={"time": "12:30"})
        assert response.status_code == 200
        assert response.json() == {"status": "updated", "time": "12:30"}
        mock_set.assert_called_once_with("12:30")

def test_post_schedule_error():
    with patch("engine.dashboard.set_schedule_time") as mock_set:
        mock_set.return_value = False
        response = client.post("/api/schedule", json={"time": "12:30"})
        assert response.status_code == 500
        assert response.json() == {"status": "error_updating"}
        mock_set.assert_called_once_with("12:30")
