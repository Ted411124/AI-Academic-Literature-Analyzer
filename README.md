# AI 學術文獻分析與雙語心智圖生成系統

## AI Academic Literature Analyzer & Bilingual Mind Map Generator

[![Python Version](https://img.shields.io/badge/Python-3.13%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Target Cost](https://img.shields.io/badge/Target%20Cost-NT%240-orange.svg)]()

> 一套專為學術文獻閱讀與研究整理設計的輔助分析系統。以 **原文封閉式分析（Closed-Domain Grounded Analysis）** 為核心原則，要求 AI 僅根據使用者上傳的 PDF 擷取、整理、摘要及比較研究內容，不自行補充外部知識。分析結果將逐步整合 PDF 實體頁碼、原文引句與來源依據驗證機制，並以原文語言及繁體中文呈現雙語報告與階層式心智圖。

**目前開發階段：核心 PDF 處理、資料驗證及部分雙語資料結構已完成；AI 分析與完整報告功能仍在開發中。**

---

## 專案簡介 (Introduction)

閱讀外文學術文獻往往需要大量時間。尤其當研究者手上有多篇外文論文，卻必須在有限時間內判斷哪些文獻真正符合報告主題時，逐頁閱讀可能造成相當大的負擔。

一般通用型 AI 工具雖然能快速摘要，但也可能出現過度推論、補充原文未提及的資訊，以及遺失原文出處等問題。

本系統希望透過 PDF 文字擷取、結構化分析、來源驗證與雙語呈現，協助使用者更有效率地理解學術文獻。

### 核心設計理念

1. **原文封閉式分析**：AI 僅根據上傳的 PDF 執行內容擷取、摘要、整理、翻譯及主題相關性比較，不應自行補充外部背景知識。原文未提及的資訊應標示為 `【原文未提及】`，無法辨識的內容則標示為 `【無法辨識】`。

2. **實體頁碼追溯**：以 PDF 實際檔案頁碼（1、2、3……）作為來源定位依據，不將期刊印刷頁碼與 PDF 實體頁碼混淆。

3. **來源依據與引註驗證機制**：重要論點應盡可能對應原文引句及 PDF 實體頁碼，並透過程式驗證引句與頁碼。此機制旨在降低錯誤引用及無根據內容，但不能保證 AI 完全不會產生錯誤。

4. **動態雙語適配**：
   - 英文論文：英文原文語言＋繁體中文。
   - 日文論文：日文＋繁體中文。
   - 簡體中文論文：簡體中文＋繁體中文。
   - 繁體中文論文：僅呈現繁體中文，避免重複欄位。

5. **研究主題相關性分析**：比較論文實際研究內容與使用者輸入的報告主題，評估高度、部分或低度相關性，不應只依賴關鍵字出現次數。

6. **結構化報告與心智圖**：規劃將全文概述、研究背景、研究目的、研究方法、核心論點、研究發現及重要引句整理成可閱讀的雙語報告與階層式心智圖。

7. **低成本開發目標**：以免費服務及免費額度作為部署規劃方向，目標總支出為 NT$0、不綁定信用卡。但實際可用額度、服務政策及免費方案可能隨時間改變，不能保證永久免費。

---

## 系統開發進度 (Development Status)

目前已完成核心後端、PDF 處理、資料驗證及部分雙語資料結構。以下區分已完成、部分完成與尚未完成的功能。

### 一、已完成 (Completed)

- [x] **正式需求規格書**：建立 `PROJECT_SPEC.md`，作為系統功能及開發流程的正式規格依據。
- [x] **Git 版本控制與安全排除**：建立 `.gitignore`，排除虛擬環境、環境變數、暫存 PDF、快取及其他不應納入版本控制的資料。
- [x] **FastAPI 核心架構**：建立後端主程式 `app/main.py` 與系統組態 `app/config.py`。
- [x] **健康檢查與系統資訊 API**：
  - `GET /api/health`：提供服務健康狀態。
  - `GET /api/info`：提供系統限制及支援資訊。
- [x] **PDF 文字擷取引擎**：
  - 使用 PyMuPDF（fitz）擷取數位原生 PDF 文字。
  - 以 1-based 頁碼記錄 PDF 實體頁數。
  - 使用 `get_text("text", sort=True)` 整理文字順序。
  - 檢查 PDF 檔案格式及有效性。
  - 拒絕缺乏可擷取文字的掃描型 PDF，不包含 OCR。
  - 使用隨機 `document_id` 隔離文件資料。
  - 實作暫存資料儲存及 TTL 清理機制。
- [x] **PDF 上傳與查詢 API**：
  - `POST /api/documents/upload`：上傳 PDF 並逐頁擷取文字。
  - `GET /api/documents/{document_id}`：取得文件基本處理資訊。
  - `GET /api/documents/{document_id}/pages`：取得逐頁原文及實體頁碼。
- [x] **PDF 基本資料辨識與處理**：
  - 從 PDF 前兩頁、最多 8,000 字元的內容辨識標題、作者、年份及語言。
  - 提供使用者確認或修改基本資料的流程。
  - 使用者選擇「略過」時，保留系統辨識結果及其來源證據，不清空或刪除資料。
  - 基本資料不足時，不應直接阻止後續分析流程。
- [x] **分析請求資料驗證**：
  - 建立 Pydantic 資料模型。
  - 驗證文件識別碼、分析主題及分析模式。
  - 建立分析結果驗收及來源資料驗證機制。
- [x] **候選分析結果驗收機制**：
  - 驗證文件識別碼及頁數。
  - 驗證引用頁碼是否在有效範圍內。
  - 驗證原文引句是否能在對應 PDF 頁面找到。
  - 使用原子方式儲存通過驗證的資料。
- [x] **學術簡約前端介面**：
  - 建立響應式網頁操作介面。
  - 串接 PDF 上傳及進度顯示。
  - 顯示上傳成功資訊與錯誤提示。
- [x] **自動化測試**：
  - 建立 pytest 測試套件。
  - 涵蓋 PDF 處理、API、資料驗證及邊界條件等測試。

### 二、部分完成 (Partially Completed)

- [x] **雙語資料結構初步實作**：
  - 已加入部分原文語言及繁體中文欄位。
  - 已建立部分雙語欄位的條件驗證。
  - 已處理繁體中文來源不重複產生相同語言欄位的驗證。
- [ ] **完整雙語報告**：
  - 尚未完成所有報告欄位的雙語生成、呈現及整合。
- [ ] **分析結果整合**：
  - 已有候選結果驗收機制，但尚未完成從 AI 生成到完整報告的整體流程。

### 三、尚未完成 (Planned)

- [ ] **Gemini AI 分析服務**：整合 Google AI Studio Gemini API，實作封閉領域 Prompt、長文分塊分析及內容整合。
- [ ] **分析服務啟用**：將分析 executor 注入系統，正式啟用 `POST /api/analysis`。
- [ ] **完整來源驗證**：擴充重要引句、頁碼、數字及作者主張的驗證流程，並區分作者明確陳述與 AI 推論。
- [ ] **完整雙語報告**：產生全文概述、研究背景、研究目的、研究方法、核心論點、研究發現、重要引句及主題相關性分析。
- [ ] **報告預覽介面**：完成網頁端完整報告呈現。
- [ ] **Markmap.js 心智圖**：將分析結果轉換成可互動的階層式雙語心智圖。
- [ ] **PDF 報告匯出**：完成雙語報告排版及 PDF 下載。
- [ ] **PNG 心智圖匯出**：完成心智圖圖片輸出及下載。
- [ ] **Demo Mode**：預載《The Transatlantic Slave Trade》主題的靜態示範資料，供無法即時呼叫 AI 時展示。示範結果會明確標示為預先產生的資料。
- [ ] **錯誤處理與使用限制**：完善 API 錯誤提示、分析紀錄、使用限制及失敗復原機制。
- [ ] **端到端測試**：以實際學術 PDF 測試完整上傳、分析、報告與匯出流程。
- [ ] **雲端部署**：評估 Hugging Face Spaces 等符合預算需求的部署方案，完成公開 HTTPS 網址驗證。

---

## PDF 上傳與文字擷取規格 (PDF Processing Specs)

### 1. 支援與不支援的 PDF 類型

- **支援文件**：數位原生、具有可選取文字的學術論文 PDF（Digital-native text PDF）。
- **不支援文件**：純圖片掃描檔、影印照片 PDF、沒有可擷取文字的檔案。
- **OCR 限制**：第一版不包含 OCR 影像辨識功能。若 PDF 缺乏可擷取文字，系統將拒絕處理並提供提示。

### 2. 容量與頁數限制

| 項目 | 規格 |
|---|---|
| 單一 PDF 大小 | 預設最多 10 MB |
| 單一 PDF 頁數 | 最多 50 頁 |
| 單次上傳數量 | 一次一份 PDF |
| 支援語言 | 英文、日文、繁體中文、簡體中文 |
| OCR | 第一版不支援 |

檔案大小與頁數限制可透過環境變數 `MAX_FILE_SIZE_MB` 及 `MAX_PAGES` 調整。

### 3. PDF 實體頁碼規則

系統使用 PDF 實際頁面順序作為頁碼基準：

- 第一頁為第 1 頁。
- 第二頁為第 2 頁。
- 依此類推。

不以論文內部印刷頁碼取代 PDF 實體頁碼。

### 4. PDF 基本資料辨識

系統初步使用 PDF 前兩頁、最多 8,000 字元辨識：

- 論文標題
- 作者
- 出版年份
- 文件語言

辨識結果可由使用者確認或修改。

若使用者選擇「略過」，系統仍保留自動辨識資料及其來源證據，不會清空資料，也不會阻止後續分析。

---

## 動態雙語呈現規則 (Bilingual Output)

系統依照 PDF 原始語言決定輸出語言，不固定使用英文與中文兩種語言。

| PDF 原始語言 | 預定輸出方式 |
|---|---|
| 英文 | 英文＋繁體中文 |
| 日文 | 日文＋繁體中文 |
| 簡體中文 | 簡體中文＋繁體中文 |
| 繁體中文 | 繁體中文單一呈現 |

預定套用於：

- 全文概述
- 研究背景與研究目的
- 研究方法
- 核心論點
- 研究發現
- 重要原文引句
- 主題相關性分析
- 心智圖節點

英文與日文等雙語內容，桌面版預定採雙欄對照，手機版則採上下排列。

目前僅完成部分雙語資料結構，完整生成及前端呈現仍在開發中。

---

## 分析內容與來源驗證原則

本系統的分析範圍限於使用者上傳的 PDF。

### 預定報告內容

1. 論文基本資料。
2. 全文概述。
3. 研究背景。
4. 研究目的。
5. 研究方法。
6. 核心論點。
7. 研究發現。
8. 重要原文引句與 PDF 實體頁碼。
9. 作者明確指出的研究限制。
10. AI 推論與作者原文陳述的區分。
11. 使用者報告主題與論文內容的相關性分析。

### 來源標示

- `【原文未提及】`：原文沒有明確提供相關資訊。
- `【無法辨識】`：系統無法可靠辨識該項資訊。

重要分析內容應盡可能附上原文引句及 PDF 實體頁碼。

程式可以驗證頁碼範圍及引句是否出現在對應頁面，但這不代表已經完成所有語意驗證，也不能保證 AI 的摘要或翻譯完全正確。使用者仍應以原始 PDF 核對重要研究資訊。

---

## API 路由清單 (API Endpoints)

| 方法 | 路由端點 | 功能說明 | 目前狀態 |
|---|---|---|---|
| `GET` | `/` | 系統首頁 | `200 OK` |
| `GET` | `/api/health` | 服務健康檢查 | `200 OK` |
| `GET` | `/api/info` | 系統規格及限制資訊 | `200 OK` |
| `POST` | `/api/documents/upload` | 上傳 PDF 並逐頁擷取文字 | 已實作 |
| `GET` | `/api/documents/{document_id}` | 查詢文件基本處理資訊 | 已實作 |
| `GET` | `/api/documents/{document_id}/pages` | 取得逐頁原文及實體頁碼 | 已實作 |
| `POST` | `/api/analysis` | 驗證分析請求 | 目前回傳 `501 Not Implemented` |

### 分析 API 特別說明

`POST /api/analysis` 已具備請求資料驗證，但目前分析服務尚未啟用。

收到有效請求後，系統回傳：

- `status = "not_implemented"`
- `analysis_started = false`

這表示請求資料已通過驗證，但尚未開始 AI 分析，也尚未產生報告。

---

## 本機快速啟動指南 (Quickstart)

### 1. 建立 Python 虛擬環境

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 安裝相依套件

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. 啟動 FastAPI 本機伺服器

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

### 4. 開啟系統

- 系統首頁：http://127.0.0.1:8001/
- Swagger API 文件：http://127.0.0.1:8001/docs
- 健康檢查：http://127.0.0.1:8001/api/health

> 注意：本專案目前使用 port 8001。若其他程式已占用該連接埠，請先確認服務狀態，不要任意終止其他應用程式。

### 5. 執行自動化測試

請在專案根目錄使用虛擬環境中的 pytest：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 自動化測試結果 (Test Results)

最近一次完整測試結果：

| 測試項目 | 結果 |
|---|---:|
| Passed | 165 |
| XFailed | 1 |
| Failed | 0 |
| Warnings | 3 |

**測試結果：165 passed、1 xfailed、3 warnings，0 failed。**

`xfailed` 代表預期會失敗的測試項目，不應計入一般通過項目。三項 warnings 為相容性棄用警告，不代表本次測試失敗。

此數字代表最近一次測試執行結果，不代表未來所有修改都已經通過測試。

---

## 專案目錄結構 (Directory Structure)

以下列出主要程式模組與用途，實際檔案以專案目前版本為準。

```text
AI-Academic-Literature-Analyzer/
│
├── .gitignore
├── .env.example
├── requirements.txt
├── PROJECT_SPEC.md
├── README.md
│
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── pdf_service.py
│   │   └── gemini_service.py
│   │
│   ├── templates/
│   │   └── index.html
│   │
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── main.js
│
├── storage/
│   ├── temp_uploads/
│   └── temp_results/
│
└── tests/
```

---

## AI 模型與服務規劃 (AI Integration)

預定使用 Google AI Studio 提供的 Gemini API 作為文獻分析模型。

目前狀態：

- Gemini API 尚未正式啟用。
- `gemini_service.py` 尚未完成實際模型呼叫。
- API 金鑰尚未設定為正式服務組態。
- 尚未進行實際 Gemini 文獻分析。
- `/api/analysis` 尚未注入可執行的分析服務。

未來整合時，將優先確認 Google AI Studio 當時的免費額度、模型可用性及使用限制，避免未經使用者同意產生付費支出。

API 金鑰應透過環境變數管理，不應寫入程式碼或提交至 GitHub。

---

## Demo Mode 示範模式規劃

為了讓系統在 AI API 無法使用、額度不足或展示環境沒有金鑰時，仍能展示主要介面，預定建立靜態示範資料。

預定示範主題：

**The Transatlantic Slave Trade（跨大西洋奴隸貿易）**

示範模式將使用預先產生的結構化 JSON，不需要每次展示都呼叫 Gemini API。

畫面必須明確標示：

「此為預先產生的示範分析結果，並非本次即時 AI 分析。」

Demo Mode 尚未完成。

---

## 免費部署規劃 (Deployment)

本專案以總支出 NT$0、不綁定信用卡、不使用付費服務為預算目標。

目前尚未完成公開雲端部署。

未來優先評估：

- **Google AI Studio**：評估 Gemini API 免費額度及相關限制。
- **Hugging Face Spaces**：評估 Docker／FastAPI 部署的可行性與免費方案。
- **Render**：僅作為備選方案，需評估免費服務的休眠及資源限制。

實際方案必須以部署當時官方公告的免費額度、硬體資源、服務政策及使用限制為準。

不保證任何平台永久提供免費服務，也不應在未確認的情況下啟用需要付費或綁定信用卡的服務。

---

## 開發者與專案資訊 (Project Information)

- **專案名稱**：AI 學術文獻分析與雙語心智圖生成系統
- **英文名稱**：AI Academic Literature Analyzer & Bilingual Mind Map Generator
- **開發者**：許家瑋
- **GitHub 儲存庫**：[AI-Academic-Literature-Analyzer](https://github.com/Ted411124/AI-Academic-Literature-Analyzer)
- **正式規格文件**：`PROJECT_SPEC.md`

---

## 重要聲明 (Disclaimer)

本系統定位為學術閱讀與研究整理的輔助工具，不取代研究者對原始文獻的閱讀、判斷與引用查核。

AI 產生的摘要、翻譯、研究發現及主題相關性判斷仍可能存在錯誤。重要數字、引句、頁碼及研究結論應回到原始 PDF 核對。

本專案目前仍在開發中，README 所列尚未完成的功能不代表已可供正式使用。