"""
系統組態設定模組 (System Configuration)
支援環境變數讀取與安全預設值設定，落實零付費原則與容量保護。
"""

import os
from pathlib import Path

# 專案基底路徑
BASE_DIR = Path(__file__).resolve().parent.parent

# 暫存目錄定義 (隨啟動自動確認存在)
STORAGE_DIR = BASE_DIR / "storage"
TEMP_UPLOADS_DIR = STORAGE_DIR / "temp_uploads"
TEMP_RESULTS_DIR = STORAGE_DIR / "temp_results"

# 確保暫存目錄存在
os.makedirs(TEMP_UPLOADS_DIR, exist_ok=True)
os.makedirs(TEMP_RESULTS_DIR, exist_ok=True)

# 系統基本資訊
APP_NAME = "AI Academic Literature Analyzer & Bilingual Mind Map Generator"
APP_NAME_ZH = "AI學術文獻分析與雙語心智圖生成系統"
APP_VERSION = "0.1.0"
APP_ENV = os.getenv("APP_ENV", "development")

# 上傳檔案與規格限制 (依據 PROJECT_SPEC.md 規範)
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PAGES = int(os.getenv("MAX_PAGES", "50"))

# 文本擷取有效性門檻 (低於此字數判定為純圖檔/掃描檔而拒絕)
MIN_TOTAL_CHARACTERS = int(os.getenv("MIN_TOTAL_CHARACTERS", "30"))

# 暫存檔案過期生命週期 (預設 3600 秒 / 1 小時)
TEMP_FILE_TTL_SECONDS = int(os.getenv("TEMP_FILE_TTL_SECONDS", "3600"))

# 支援之語系標籤
SUPPORTED_LANGUAGES = ["en", "ja", "zh-TW", "zh-CN"]

# Gemini API Key (僅從伺服器環境變數讀取，不寫死)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
