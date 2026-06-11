from fastapi.testclient import TestClient
from unittest.mock import patch
from engine.dashboard import app

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Secondo Cervello - Dashboard Unificata" in response.text

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

def test_webhook_no_secret():
    response = client.post("/api/webhook/notion")
    assert response.status_code == 401

def test_webhook_wrong_secret():
    response = client.post("/api/webhook/notion", headers={"x-webhook-secret": "wrong"})
    assert response.status_code == 401

@patch.dict("os.environ", {"WEBHOOK_SECRET": "testsecret"})
def test_webhook_invalid_source():
    response = client.post("/api/webhook/invalid_src", headers={"x-webhook-secret": "testsecret"})
    assert response.status_code == 400

@patch.dict("os.environ", {"WEBHOOK_SECRET": "testsecret"})
@patch("engine.dashboard.manager.start")
def test_webhook_success(mock_start):
    mock_start.return_value = True
    response = client.post("/api/webhook/notion", headers={"x-webhook-secret": "testsecret"})
    assert response.status_code == 200
    assert response.json() == {"status": "triggered", "source": "notion"}
    mock_start.assert_called_once_with(source="notion")

def test_get_wiki_success():
    # 'wiki/entities/FF3300.md' esiste nel vault e dovrebbe essere risolto
    response = client.get("/api/wiki?path=FF3300")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "FF3300"
    assert "path" in data
    assert "content" in data
    assert "frontmatter" in data

def test_get_wiki_not_found():
    response = client.get("/api/wiki?path=NonExistentNoteXYZ123")
    assert response.status_code == 404

