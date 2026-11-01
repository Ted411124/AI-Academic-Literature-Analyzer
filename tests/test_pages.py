"""
前端頁面與靜態資源路由測試 (Frontend & Static Resource Tests)
"""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_index_page_returns_200():
    """測試首頁 GET / 是否正常載入 HTML"""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html_content = response.text
    assert "AI學術文獻分析與雙語心智圖生成系統" in html_content
    assert "AI Academic Literature Analyzer" in html_content
    assert "Bilingual Mind Map Generator" in html_content
    assert "跨大西洋奴隸貿易" in html_content
    assert "一般文獻分析" in html_content
    assert "主題導向分析" in html_content


def test_static_css_accessible():
    """測試靜態樣式表 /static/css/style.css 是否可正常讀取"""
    response = client.get("/static/css/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--primary-navy" in response.text


def test_static_js_accessible():
    """測試靜態指令碼 /static/js/main.js 是否可正常讀取"""
    response = client.get("/static/js/main.js")
    assert response.status_code == 200
    assert "initHealthCheck" in response.text
