"""
健康檢查與系統資訊 API 測試 (Health & System Info Tests)
"""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_endpoint():
    """測試 /api/health 是否正確回傳 200 與標準 JSON"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "AI Academic Literature Analyzer" in data["app_name"]
    assert "AI學術文獻分析與雙語心智圖生成系統" in data["app_name_zh"]
    assert data["version"] == "0.1.0"
    assert "zh-TW" in data["supported_languages"]
    assert "en" in data["supported_languages"]


def test_system_info_endpoint():
    """測試 /api/info 是否回傳正確的零費用與規格限制"""
    response = client.get("/api/info")
    assert response.status_code == 200
    data = response.json()
    assert data["digital_text_only"] is True
    assert data["single_upload_only"] is True
    assert data["zero_cost_compliant"] is True
    assert data["max_file_size_mb"] > 0
    assert data["max_pages"] > 0
