/**
 * AI 學術文獻分析與雙語心智圖生成系統 - 主前端邏輯 (main.js)
 * 負責服務健康檢查、PDF 上傳與實體頁碼文字擷取、模式切換與預覽互動。
 */

// 全域狀態管理 (前端狀態快取)
const AppState = {
  currentDocumentId: null,
  currentFilename: null,
  totalPages: 0,
  totalCharacters: 0,
  metadataReview: null,
  analysisMode: null,
  topic: "",
  analysisSubmitting: false,
};

document.addEventListener("DOMContentLoaded", () => {
  initHealthCheck();
  initUploadInteractions();
  initMetadataReviewActions();
  initModeSelection();
  initAnalysisRequest();
  initTabs();
  initDemoAction();
  initPDFExport();
  initPNGExport();
});

/**
 * 1. 服務健康檢查 (動態確認後端連線)
 */
async function initHealthCheck() {
  const statusPill = document.getElementById("health-status");
  const statusText = document.getElementById("health-status-text");

  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      const data = await res.json();
      if (statusText) {
        statusText.textContent = `後端服務正常 (v${data.version})`;
      }
    } else {
      throw new Error(`HTTP ${res.status}`);
    }
  } catch (err) {
    if (statusPill && statusText) {
      statusPill.style.backgroundColor = "#fef2f2";
      statusPill.style.color = "#dc2626";
      statusPill.style.borderColor = "#fecaca";
      statusText.textContent = "無法連線至後端服務";
    }
  }
}

/**
 * 2. 檔案上傳與實體頁碼文字擷取互動
 */
function initUploadInteractions() {
  const dropzone = document.getElementById("upload-dropzone");
  const fileInput = document.getElementById("pdf-file-input");
  const uploadTitle = document.getElementById("upload-file-title");
  const actionRow = document.getElementById("upload-action-row");
  const selectedBadge = document.getElementById("selected-file-badge");
  const btnUpload = document.getElementById("btn-upload-file");
  const loadingIndicator = document.getElementById("upload-loading-indicator");
  const errorAlert = document.getElementById("upload-error-alert");
  const errorMessage = document.getElementById("error-message");
  const successCard = document.getElementById("upload-success-card");

  let selectedFile = null;

  if (!dropzone || !fileInput) return;

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      fileInput.files = e.dataTransfer.files;
      handleFileSelected(fileInput.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length > 0) {
      handleFileSelected(fileInput.files[0]);
    }
  });

  function handleFileSelected(file) {
    AppState.currentDocumentId = null;
    AppState.metadataReview = null;
    updateAnalysisButton();
    // 隱藏先前的結果或錯誤提示
    hideError();
    if (successCard) successCard.style.display = "none";

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      showError("非 PDF 檔案格式", "本系統僅支援學術論文之 .pdf 文件格式，請重新選擇。");
      fileInput.value = "";
      selectedFile = null;
      if (actionRow) actionRow.style.display = "none";
      return;
    }

    selectedFile = file;
    const sizeMb = (file.size / 1024 / 1024).toFixed(2);

    if (uploadTitle) {
      uploadTitle.textContent = `已選取：${file.name} (${sizeMb} MB)`;
    }

    if (actionRow && selectedBadge) {
      selectedBadge.textContent = `📄 待上傳：${file.name} (${sizeMb} MB)`;
      actionRow.style.display = "flex";
    }
  }

  // 點擊送出上傳並進行物理頁碼擷取
  if (btnUpload) {
    btnUpload.addEventListener("click", async () => {
      if (!selectedFile) {
        showError("未選擇檔案", "請先點選上傳區選取 PDF 文件。");
        return;
      }
      await uploadPDF(selectedFile);
    });
  }

  async function uploadPDF(file) {
    hideError();
    if (successCard) successCard.style.display = "none";
    if (loadingIndicator) loadingIndicator.style.display = "flex";
    if (btnUpload) btnUpload.disabled = true;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/documents/upload", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || data.detail || `上傳處理失敗 (HTTP ${response.status})`);
      }

      // 上傳與擷取成功
      AppState.currentDocumentId = data.document_id;
      AppState.currentFilename = data.original_filename;
      AppState.totalPages = data.total_pages;
      AppState.totalCharacters = data.total_characters;

      renderSuccessResult(data);

      // 基本資料只顯示有 PDF 證據的候選，不再以檔名推定論文標題。
      const metaPages = document.getElementById("meta-pages");
      renderMetadataReview(data.metadata_review || null);
      updateAnalysisButton();
      if (metaPages) {
        metaPages.value = `${data.total_pages} 頁 (實體頁碼 1 ~ ${data.total_pages})`;
      }

      // 更新進度步驟指標
      const step1Ind = document.getElementById("step-ind-1");
      if (step1Ind) {
        step1Ind.classList.add("active");
        step1Ind.textContent = `✅ 1. 物理頁碼解析 (共 ${data.total_pages} 頁)`;
      }

    } catch (err) {
      showError("PDF 文字擷取失敗", err.message);
    } finally {
      if (loadingIndicator) loadingIndicator.style.display = "none";
      if (btnUpload) btnUpload.disabled = false;
    }
  }

  function showError(title, msg) {
    const errorTitle = document.getElementById("error-title");
    if (errorTitle) errorTitle.textContent = title;
    if (errorMessage) errorMessage.textContent = msg;
    if (errorAlert) errorAlert.style.display = "flex";
  }

  function hideError() {
    if (errorAlert) errorAlert.style.display = "none";
  }

  function renderSuccessResult(data) {
    const resDocId = document.getElementById("res-doc-id");
    const resFilename = document.getElementById("res-filename");
    const resTotalPages = document.getElementById("res-total-pages");
    const resTotalChars = document.getElementById("res-total-chars");
    const resExcerpt = document.getElementById("res-excerpt");

    if (resDocId) resDocId.textContent = `ID: ${data.document_id.slice(0, 8)}...`;
    if (resFilename) resFilename.textContent = data.original_filename;
    if (resTotalPages) resTotalPages.textContent = `${data.total_pages} 頁 (物理頁碼 1 ~ ${data.total_pages})`;
    if (resTotalChars) resTotalChars.textContent = `${data.total_characters.toLocaleString()} 字元`;
    if (resExcerpt) resExcerpt.textContent = data.preview_excerpt || "(第 1 頁無前導文字)";

    if (successCard) successCard.style.display = "block";
  }
}

function initMetadataReviewActions() {
  const confirmButton = document.getElementById("btn-confirm-metadata");
  const skipButton = document.getElementById("btn-skip-metadata");
  if (confirmButton) {
    confirmButton.addEventListener("click", () => submitMetadataReview("confirmed"));
  }
  if (skipButton) {
    skipButton.addEventListener("click", () => submitMetadataReview("skipped"));
  }
}

function metadataFieldValue(field) {
  return field && field.value !== null && field.value !== undefined ? field.value : null;
}

function renderMetadataReview(review) {
  AppState.metadataReview = review;
  const status = document.getElementById("metadata-review-status");
  const fields = [
    ["title", "meta-title", "meta-title-evidence"],
    ["authors", "meta-authors", "meta-authors-evidence"],
    ["publication_year", "meta-year", "meta-year-evidence"],
    ["detected_language", "meta-language", "meta-language-evidence"],
  ];
  for (const [key, inputId, evidenceId] of fields) {
    const field = review && review[key];
    const input = document.getElementById(inputId);
    const evidence = document.getElementById(evidenceId);
    const value = metadataFieldValue(field);
    if (input) {
      input.value = Array.isArray(value) ? value.join("; ") : (value || "");
    }
    if (evidence) {
      const ref = field && field.evidence;
      const sourceLabels = { pdf_detected: "資料來源：PDF 偵測", user_provided: "資料來源：使用者提供" };
      const sourceText = field && field.source ? sourceLabels[field.source] || "" : "資料來源：無法辨識";
      evidence.hidden = !field || (!ref && !field.source);
      evidence.textContent = ref
        ? `${sourceText}；PDF 原文 [p. ${ref.page_number}]：${ref.original_quote}`
        : sourceText;
    }
  }
  const statusLabels = {
    pending_confirmation: "待確認：以下為本機規則產生的候選，請核對原文證據。",
    confirmed: "基本資料已確認。",
    skipped: "已略過基本資料確認，仍可繼續後續流程。",
  };
  if (status) {
    status.textContent = review ? (statusLabels[review.status] || "基本資料無法辨識；可自行輸入或略過。")
      : "基本資料無法辨識；可自行輸入或略過。";
  }
  const pending = review && review.status === "pending_confirmation";
  for (const id of ["btn-confirm-metadata", "btn-skip-metadata"]) {
    const button = document.getElementById(id);
    if (button) button.disabled = !pending;
  }
  updateAnalysisButton();
}

async function submitMetadataReview(decision) {
  if (!AppState.currentDocumentId) return;
  const status = document.getElementById("metadata-review-status");
  const confirmButton = document.getElementById("btn-confirm-metadata");
  const skipButton = document.getElementById("btn-skip-metadata");
  if (confirmButton) confirmButton.disabled = true;
  if (skipButton) skipButton.disabled = true;

  const payload = { decision };
  if (decision === "confirmed") {
    const authorsText = document.getElementById("meta-authors")?.value || "";
    payload.title = document.getElementById("meta-title")?.value.trim() || null;
    payload.authors = authorsText.split(/[;\n]+/).map((name) => name.trim()).filter(Boolean);
    payload.publication_year = document.getElementById("meta-year")?.value.trim() || null;
    payload.detected_language = document.getElementById("meta-language")?.value || null;
  }

  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(AppState.currentDocumentId)}/metadata`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.message || "基本資料審閱狀態保存失敗");
    renderMetadataReview(data);
  } catch (error) {
    if (status) status.textContent = `基本資料未能保存：${error.message}。您仍可繼續後續流程。`;
    if (confirmButton) confirmButton.disabled = false;
    if (skipButton) skipButton.disabled = false;
  }
}

/**
 * 3. 分析模式切換 (模式 A vs 模式 B)
 */
function initModeSelection() {
  const modeA = document.getElementById("mode-a-card");
  const modeB = document.getElementById("mode-b-card");
  const topicContainer = document.getElementById("topic-input-container");

  if (!modeA || !modeB) return;

  modeA.addEventListener("click", () => {
    modeA.classList.add("selected");
    modeB.classList.remove("selected");
    AppState.analysisMode = "general";
    AppState.topic = "";
    if (topicContainer) topicContainer.classList.remove("active");
    updateAnalysisButton();
  });

  modeB.addEventListener("click", () => {
    modeB.classList.add("selected");
    modeA.classList.remove("selected");
    AppState.analysisMode = "topic";
    if (topicContainer) {
      topicContainer.classList.add("active");
      const topicInput = document.getElementById("user-topic-input");
      if (topicInput) topicInput.focus();
    }
    updateAnalysisButton();
  });
}

function updateAnalysisButton() {
  const button = document.getElementById("btn-start-analyze");
  const topicInput = document.getElementById("user-topic-input");
  if (!button) return;
  AppState.topic = topicInput ? topicInput.value.trim() : AppState.topic.trim();
  const reviewStatus = AppState.metadataReview && AppState.metadataReview.status;
  const metadataHandled = reviewStatus === "confirmed" || reviewStatus === "skipped";
  const modeValid = AppState.analysisMode === "general"
    || (AppState.analysisMode === "topic" && AppState.topic.length > 0);
  button.disabled = !AppState.currentDocumentId || !metadataHandled || !modeValid || AppState.analysisSubmitting;
}

function initAnalysisRequest() {
  const button = document.getElementById("btn-start-analyze");
  const topicInput = document.getElementById("user-topic-input");
  if (topicInput) topicInput.addEventListener("input", updateAnalysisButton);
  if (button) button.addEventListener("click", submitAnalysisRequest);
  updateAnalysisButton();
}

async function submitAnalysisRequest() {
  const button = document.getElementById("btn-start-analyze");
  const status = document.getElementById("analysis-request-status");
  updateAnalysisButton();
  if (!button || button.disabled) return;

  const payload = {
    document_id: AppState.currentDocumentId,
    analysis_mode: AppState.analysisMode,
    topic: AppState.analysisMode === "topic" ? AppState.topic.trim() : null,
  };
  AppState.analysisSubmitting = true;
  updateAnalysisButton();
  if (status) status.textContent = "正在驗證分析請求…";

  try {
    const response = await fetch("/api/analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 501) {
      if (status) status.textContent = data.message || "分析服務尚未啟用；請求已驗證，但尚未開始分析或產生報告。";
      return;
    }
    if (!response.ok) {
      const messages = {
        404: "文件不存在或已過期，請重新上傳 PDF。",
        409: "請先完成基本資料確認或略過，再送出分析請求。",
        422: "分析模式或主題資料無效，請檢查選項後重試。",
      };
      if (status) status.textContent = messages[response.status] || "分析請求驗證失敗，請檢查資料後重試。";
      return;
    }
    if (!data.report_id) {
      if (status) status.textContent = "\u5206\u6790\u5df2\u5b8c\u6210\uff0c\u4f46\u5f8c\u7aef\u6c92\u6709\u56de\u50b3\u5831\u544a\u7de8\u865f\u3002";
      return;
    }

    if (status) status.textContent = "\u5206\u6790\u5b8c\u6210\uff0c\u6b63\u5728\u8f09\u5165\u5831\u544a\u2026";

    const reportResponse = await fetch(
      `/api/reports/${encodeURIComponent(data.report_id)}`
    );
    const reportData = await reportResponse.json().catch(() => ({}));

    if (!reportResponse.ok) {
      if (status) status.textContent = "\u5206\u6790\u5df2\u5b8c\u6210\uff0c\u4f46\u8b80\u53d6\u5831\u544a\u5931\u6557\uff0c\u8acb\u7a0d\u5f8c\u91cd\u8a66\u3002";
      return;
    }

    AppState.currentReport = reportData;
    renderAnalysisReport(reportData);
    renderInteractiveMindMap(reportData);

    if (status) status.textContent = "\u5206\u6790\u5b8c\u6210\uff0c\u5831\u544a\u5df2\u6210\u529f\u8f09\u5165\uff01";
  } catch (_error) {
    if (status) status.textContent = "無法連線至分析服務，請確認網路或稍後重試。";
  } finally {
    AppState.analysisSubmitting = false;
    updateAnalysisButton();
  }
}

/**
 * 4. 結果分頁切換 (雙語報告 vs 互動心智圖)
 */
function initTabs() {
  const tabReport = document.getElementById("tab-report-btn");
  const tabMindmap = document.getElementById("tab-mindmap-btn");
  const viewReport = document.getElementById("view-report");
  const viewMindmap = document.getElementById("view-mindmap");

  if (!tabReport || !tabMindmap) return;

  tabReport.addEventListener("click", () => {
    tabReport.classList.add("active");
    tabMindmap.classList.remove("active");
    if (viewReport) viewReport.style.display = "block";
    if (viewMindmap) viewMindmap.style.display = "none";
  });

  tabMindmap.addEventListener("click", () => {
    tabMindmap.classList.add("active");
    tabReport.classList.remove("active");
    if (viewReport) viewReport.style.display = "none";
    if (viewMindmap) viewMindmap.style.display = "block";
  });
}

/**
 * 5. 示範展示模式按鈕 (Demo Mode)
 */
function initDemoAction() {
  const btnDemo = document.getElementById("btn-load-demo");
  if (!btnDemo) return;

  btnDemo.addEventListener("click", (e) => {
    e.stopPropagation();
    alert("【示範展示模式】\n系統已預留《跨大西洋奴隸貿易》(The Transatlantic Slave Trade) 示範論文載入介面。\n完整預先分析靜態資料將於核心分析完成後於後續階段無縫串接！");
  });
}


// Render a complete, source-grounded bilingual academic report.
function renderAnalysisReport(report) {
  const container = document.getElementById("view-report");
  if (!container || !report) return;

  container.replaceChildren();

  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }
    if (className) element.className = className;
    return element;
  };

  const section = (title) => {
    const block = make("section", null, "report-section");
    block.style.cssText = "margin:24px 0;padding:20px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;";
    const heading = make("h3", title);
    heading.style.cssText = "margin:0 0 16px;color:#17324d;font-size:1.15rem;";
    block.appendChild(heading);
    container.appendChild(block);
    return block;
  };

  const paragraph = (parent, text, className) => {
    if (text === undefined || text === null || text === "") return;
    const p = make("p", text, className);
    p.style.cssText = "margin:7px 0;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere;";
    parent.appendChild(p);
  };

  const bilingual = (parent, original, traditional) => {
    if (original) {
      const originalBlock = make("div", null, "report-original");
      originalBlock.style.cssText = "padding:10px 12px;margin:8px 0;background:#f1f5f9;border-radius:8px;line-height:1.7;white-space:pre-wrap;";
      paragraph(originalBlock, original);
      parent.appendChild(originalBlock);
    }
    if (traditional) {
      const translatedBlock = make("div", null, "report-traditional");
      translatedBlock.style.cssText = "padding:10px 12px;margin:8px 0;background:#f8fafc;border-left:3px solid #547a9e;border-radius:4px;line-height:1.7;white-space:pre-wrap;";
      paragraph(translatedBlock, traditional);
      parent.appendChild(translatedBlock);
    }
  };

  const evidence = (parent, items) => {
    if (!Array.isArray(items) || items.length === 0) return;
    const wrapper = make("div");
    wrapper.style.cssText = "margin-top:12px;padding:12px;background:#fffbeb;border-radius:8px;";
    const label = make("strong", "PDF evidence / 原文依據");
    wrapper.appendChild(label);

    items.forEach((item) => {
      const quote = make("blockquote");
      quote.style.cssText = "margin:8px 0;padding-left:12px;border-left:3px solid #d6a84b;line-height:1.7;";
      paragraph(quote, item.original_quote);
      paragraph(quote, `[PDF p. ${item.page_number}]`);
      wrapper.appendChild(quote);
    });

    parent.appendChild(wrapper);
  };

  const statement = (parent, item) => {
    if (!item) return;

    const statusLabels = {
      supported: "Supported by PDF / 有原文依據",
      not_mentioned: "Not mentioned / 原文未提及",
      unrecognizable: "Unrecognizable / 無法辨識",
      pending_confirmation: "Pending confirmation / 待確認",
      user_provided: "User provided / 使用者提供"
    };

    const card = make("article", null, "report-statement");
    card.style.cssText = "margin:12px 0;padding:14px;border:1px solid #e5e7eb;border-radius:10px;";

    const status = make("span", statusLabels[item.status] || item.status);
    status.style.cssText = "display:inline-block;margin-bottom:8px;padding:4px 9px;background:#eef2f7;border-radius:20px;font-size:.82rem;color:#334155;";
    card.appendChild(status);

    bilingual(card, item.summary_original, item.summary_tw);
    evidence(card, item.evidence);
    parent.appendChild(card);
  };

  const metadata = report.metadata || {};
  const metaSection = section("Paper Information / 論文基本資料");

  const metadataRows = [
    ["Title / 標題", metadata.title],
    ["Authors / 作者", metadata.authors],
    ["Publication year / 出版年份", metadata.publication_year],
    ["Language / 原文語言", metadata.detected_language]
  ];

  metadataRows.forEach(([label, field]) => {
    const row = make("div");
    row.style.cssText = "padding:8px 0;border-bottom:1px solid #edf0f3;";
    paragraph(row, label);
    if (field) {
      const value = Array.isArray(field.value)
        ? field.value.join(", ")
        : field.value;
      paragraph(row, value || "Not available / 無法辨識");
      paragraph(row, `Source: ${field.source || "unknown"}`);
      evidence(row, field.evidence ? [field.evidence] : []);
    }
    metaSection.appendChild(row);
  });

  paragraph(metaSection, `Total PDF pages: ${report.total_pages}`);
  paragraph(metaSection, `Analysis mode: ${report.mode}`);
  if (report.topic) paragraph(metaSection, `Research topic: ${report.topic}`);

  const outlineSection = section("Article Outline / 文章大綱");
  if (Array.isArray(report.outline)) {
    report.outline.forEach((item) => {
      const card = make("article");
      card.style.cssText = "padding:10px 0;border-bottom:1px solid #edf0f3;";
      bilingual(card, item.title, item.title_tw);
      paragraph(card, `PDF pages: ${item.start_page}–${item.end_page}`);
      evidence(card, item.evidence);
      outlineSection.appendChild(card);
    });
  }

  const analysisSection = section("Academic Analysis / 學術分析");

  const analysisItems = [
    ["Research Background / 研究背景", report.research_background],
    ["Research Objectives / 研究目的", report.research_objectives],
    ["Methodology / 研究方法", report.methodology],
    ["Research Findings / 研究發現", report.research_findings],
    ["Core Arguments / 核心論點", report.core_arguments],
    ["Conclusion / 結論", report.conclusion]
  ];

  analysisItems.forEach(([label, item]) => {
    const heading = make("h4", label);
    heading.style.cssText = "margin:18px 0 8px;color:#294c68;";
    analysisSection.appendChild(heading);
    statement(analysisSection, item);
  });

  const findingsSection = section("Key Findings / 重要研究重點");
  if (Array.isArray(report.key_points)) {
    report.key_points.forEach((item, index) => {
      const card = make("article");
      card.style.cssText = "margin:12px 0;padding:14px;border:1px solid #e5e7eb;border-radius:10px;";
      const heading = make("h4", `${index + 1}. ${item.topic_tw || item.topic}`);
      heading.style.cssText = "margin:0 0 8px;color:#294c68;";
      card.appendChild(heading);
      if (item.topic_tw && item.topic_tw !== item.topic) {
        paragraph(card, `Original title: ${item.topic}`);
      }
      statement(card, item.statement);
      findingsSection.appendChild(card);
    });
  }

  const limitationsSection = section("Research Limitations / 研究限制");
  const limitations = report.research_limitations || {};
  if (limitations.status === "not_mentioned") {
    paragraph(limitationsSection, limitations.summary_tw || "【原文未提及】");
  } else if (Array.isArray(limitations.items)) {
    limitations.items.forEach((item) => statement(limitationsSection, item.statement));
  }

  if (report.topic_relevance) {
    const relevanceSection = section("Topic Relevance / 主題相關性");
    const levelLabels = {
      highly_relevant: "Highly relevant / 高度相關",
      partially_relevant: "Partially relevant / 部分相關",
      low_relevance: "Low relevance / 相關性較低"
    };
    paragraph(
      relevanceSection,
      levelLabels[report.topic_relevance.level] || report.topic_relevance.level
    );

    [
      ["Reasons / 判斷理由", report.topic_relevance.reasons],
      ["Related Sections / 相關章節", report.topic_relevance.related_sections],
      ["Recommended Reading / 建議優先研讀", report.topic_relevance.recommended_reading]
    ].forEach(([label, items]) => {
      const heading = make("h4", label);
      heading.style.cssText = "margin:16px 0 8px;color:#294c68;";
      relevanceSection.appendChild(heading);
      if (Array.isArray(items)) items.forEach((item) => statement(relevanceSection, item));
    });
  }

  const footer = make("p", `Document ID: ${report.document_id}`);
  footer.style.cssText = "margin:20px 0;color:#64748b;font-size:.8rem;";
  container.appendChild(footer);
}

// Build an interactive mind map using native SVG. No external libraries required.
function renderInteractiveMindMap(report) {
  const container = document.getElementById("view-mindmap");
  const root = report && report.mind_map && report.mind_map.root;
  if (!container || !root) return;

  container.replaceChildren();

  const collapsed = new Set();
  const svgNS = "http://www.w3.org/2000/svg";

  const makeSvg = (tag, attrs = {}) => {
    const element = document.createElementNS(svgNS, tag);
    Object.entries(attrs).forEach(([key, value]) => {
      element.setAttribute(key, String(value));
    });
    return element;
  };

  const toolbar = document.createElement("div");
  toolbar.style.cssText = "display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px;";

  const hint = document.createElement("span");
  hint.textContent = "操作方式：滾輪縮放、按住滑鼠拖曳移動、點擊節點展開或收合。";
  hint.style.cssText = "font-size:.88rem;color:#64748b;";

  const resetButton = document.createElement("button");
  resetButton.type = "button";
  resetButton.textContent = "重設視圖";
  resetButton.style.cssText = "padding:7px 14px;border:1px solid #cbd5e1;border-radius:7px;background:#fff;cursor:pointer;";

  toolbar.append(hint, resetButton);
  container.appendChild(toolbar);

  const svg = makeSvg("svg", {
    xmlns: svgNS,
    role: "img",
    "aria-label": "Interactive academic mind map"
  });
  svg.style.cssText = "display:block;width:100%;height:700px;min-height:500px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;cursor:grab;touch-action:none;";

  const viewport = makeSvg("g");
  svg.appendChild(viewport);

  container.appendChild(svg);

  let scale = 1;
  let translateX = 40;
  let translateY = 30;
  let pointerStart = null;
  let dragged = false;

  const applyTransform = () => {
    viewport.setAttribute(
      "transform",
      `translate(${translateX},${translateY}) scale(${scale})`
    );
  };

  const visibleChildren = (node) =>
    collapsed.has(node) ? [] : (Array.isArray(node.children) ? node.children : []);

  const layout = () => {
    const nodes = [];
    const edges = [];
    let nextY = 65;
    let maxDepth = 0;

    const visit = (node, depth) => {
      maxDepth = Math.max(maxDepth, depth);
      const children = visibleChildren(node);
      const childRecords = children.map((child) => visit(child, depth + 1));

      let y;
      if (childRecords.length) {
        y = childRecords.reduce((sum, item) => sum + item.y, 0) / childRecords.length;
      } else {
        y = nextY;
        nextY += 105;
      }

      const record = {
        node,
        depth,
        x: 90 + depth * 270,
        y
      };

      nodes.push(record);
      childRecords.forEach((child) => edges.push([record, child]));
      return record;
    };

    visit(root, 0);

    return {
      nodes,
      edges,
      width: Math.max(900, 90 + (maxDepth + 1) * 270 + 350),
      height: Math.max(650, nextY + 80)
    };
  };

  const draw = () => {
    viewport.replaceChildren();

    const data = layout();
    svg.setAttribute("viewBox", `0 0 ${data.width} ${data.height}`);
    svg.setAttribute("width", data.width);
    svg.setAttribute("height", data.height);

    data.edges.forEach(([parent, child]) => {
      const startX = parent.x + 10;
      const endX = child.x - 10;
      const middleX = (startX + endX) / 2;

      const path = makeSvg("path", {
        d: `M ${startX} ${parent.y} C ${middleX} ${parent.y}, ${middleX} ${child.y}, ${endX} ${child.y}`,
        fill: "none",
        stroke: "#94a3b8",
        "stroke-width": 2
      });

      viewport.appendChild(path);
    });

    data.nodes.forEach((record) => {
      const node = record.node;
      const children = Array.isArray(node.children) ? node.children : [];
      const hasChildren = children.length > 0;
      const isCollapsed = collapsed.has(node);

      const group = makeSvg("g", {
        transform: `translate(${record.x},${record.y})`,
        role: "button",
        tabindex: 0
      });
      group.style.cursor = hasChildren ? "pointer" : "default";

      const circle = makeSvg("circle", {
        r: record.depth === 0 ? 13 : 9,
        fill: record.depth === 0 ? "#234e70" : (hasChildren ? "#547a9e" : "#94a3b8"),
        stroke: "#ffffff",
        "stroke-width": 2
      });
      group.appendChild(circle);

      const label = node.label_tw || node.label_original || node.category || "未命名節點";
      const title = makeSvg("text", {
        x: 20,
        y: -5,
        fill: "#1e293b",
        "font-size": record.depth === 0 ? 17 : 15,
        "font-weight": record.depth === 0 ? 700 : 500
      });
      title.textContent = String(label).slice(0, 70);
      group.appendChild(title);

      if (node.label_original && node.label_original !== node.label_tw) {
        const original = makeSvg("text", {
          x: 20,
          y: 16,
          fill: "#64748b",
          "font-size": 12
        });
        original.textContent = String(node.label_original).slice(0, 70);
        group.appendChild(original);
      }

      if (Array.isArray(node.evidence) && node.evidence.length) {
        const pages = [...new Set(
          node.evidence
            .map((item) => item.page_number)
            .filter((page) => Number.isInteger(page))
        )];

        if (pages.length) {
          const pageLabel = makeSvg("text", {
            x: 20,
            y: node.label_original && node.label_original !== node.label_tw ? 34 : 16,
            fill: "#9a6b27",
            "font-size": 11
          });
          pageLabel.textContent = `PDF p. ${pages.join(", ")}`;
          group.appendChild(pageLabel);
        }
      }

      if (hasChildren) {
        const toggle = makeSvg("text", {
          x: -4,
          y: 4,
          "text-anchor": "middle",
          fill: "#ffffff",
          "font-size": 11,
          "font-weight": 700
        });
        toggle.textContent = isCollapsed ? "+" : "−";
        group.appendChild(toggle);

        const toggleNode = () => {
          if (dragged) return;
          if (collapsed.has(node)) collapsed.delete(node);
          else collapsed.add(node);
          draw();
        };

        group.addEventListener("click", toggleNode);
        group.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleNode();
          }
        });
      }

      viewport.appendChild(group);
    });

    applyTransform();
  };

  svg.addEventListener("pointerdown", (event) => {
    pointerStart = {
      x: event.clientX,
      y: event.clientY,
      tx: translateX,
      ty: translateY
    };
    dragged = false;
    svg.style.cursor = "grabbing";
    svg.setPointerCapture(event.pointerId);
  });

  svg.addEventListener("pointermove", (event) => {
    if (!pointerStart) return;

    const dx = event.clientX - pointerStart.x;
    const dy = event.clientY - pointerStart.y;

    if (Math.abs(dx) + Math.abs(dy) > 5) dragged = true;

    translateX = pointerStart.tx + dx;
    translateY = pointerStart.ty + dy;
    applyTransform();
  });

  const stopDragging = () => {
    pointerStart = null;
    svg.style.cursor = "grab";
  };

  svg.addEventListener("pointerup", stopDragging);
  svg.addEventListener("pointercancel", stopDragging);
  svg.addEventListener("lostpointercapture", stopDragging);

  svg.addEventListener("wheel", (event) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.12 : 0.89;
    scale = Math.min(3, Math.max(0.35, scale * factor));
    applyTransform();
  }, { passive: false });

  resetButton.addEventListener("click", () => {
    scale = 1;
    translateX = 40;
    translateY = 30;
    applyTransform();
  });

  draw();
}

// PDF export: print only the bilingual report and let the browser save it as PDF.
function initPDFExport() {
  const button = document.getElementById("btn-export-pdf");
  if (!button) return;

  button.addEventListener("click", () => {
    if (!AppState.currentReport) {
      alert("請先完成論文分析，再下載 PDF 報告。");
      return;
    }

    const report = document.getElementById("view-report");
    if (!report || !report.textContent.trim()) {
      alert("目前沒有可供下載的報告內容。");
      return;
    }

    const reportTab = document.getElementById("tab-report-btn");
    const mindmapTab = document.getElementById("tab-mindmap-btn");
    const mindmapView = document.getElementById("view-mindmap");

    if (reportTab) reportTab.classList.add("active");
    if (mindmapTab) mindmapTab.classList.remove("active");
    if (mindmapView) mindmapView.style.display = "none";
    report.style.display = "block";

    const styleId = "report-print-style";

    if (!document.getElementById(styleId)) {
      const style = document.createElement("style");
      style.id = styleId;
      style.textContent = `
        @media print {
          @page {
            size: A4;
            margin: 16mm;
          }

          body.printing-report * {
            visibility: hidden !important;
          }

          body.printing-report #step-5-card,
          body.printing-report #step-5-card #view-report,
          body.printing-report #step-5-card #view-report * {
            visibility: visible !important;
          }

          body.printing-report #step-5-card {
            position: absolute !important;
            left: 0 !important;
            top: 0 !important;
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
            border: 0 !important;
            box-shadow: none !important;
            background: white !important;
          }

          body.printing-report #step-5-card > * {
            display: none !important;
          }

          body.printing-report #step-5-card > #view-report {
            display: block !important;
            width: 100% !important;
            height: auto !important;
            overflow: visible !important;
          }

          body.printing-report #view-report article,
          body.printing-report #view-report section {
            break-inside: avoid;
          }

          body.printing-report #view-report p,
          body.printing-report #view-report blockquote {
            overflow-wrap: anywhere;
          }
        }
      `;
      document.head.appendChild(style);
    }

    const cleanup = () => {
      document.body.classList.remove("printing-report");
    };

    document.body.classList.add("printing-report");
    window.addEventListener("afterprint", cleanup, { once: true });

    window.print();
  });
}

// Export the currently visible interactive mind map as a high-resolution PNG.
function initPNGExport() {
  const button = document.getElementById("btn-export-png");
  if (!button) return;

  button.addEventListener("click", async () => {
    const container = document.getElementById("view-mindmap");
    const originalSvg = container?.querySelector("svg");

    if (!AppState.currentReport || !originalSvg) {
      alert("請先完成論文分析，產生心智圖後再下載 PNG。");
      return;
    }

    const width = Number(originalSvg.getAttribute("width"));
    const height = Number(originalSvg.getAttribute("height"));

    if (!Number.isFinite(width) || !Number.isFinite(height) ||
        width <= 0 || height <= 0) {
      alert("無法取得心智圖尺寸，請重新產生心智圖。");
      return;
    }

    let svgUrl = null;
    let pngUrl = null;

    try {
      const svgClone = originalSvg.cloneNode(true);

      svgClone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      svgClone.setAttribute("width", String(width));
      svgClone.setAttribute("height", String(height));
      svgClone.setAttribute("viewBox", `0 0 ${width} ${height}`);

      svgClone.removeAttribute("style");
      svgClone.style.background = "#ffffff";

      // Remove the interactive zoom and pan transform from the exported copy.
      const viewport = svgClone.querySelector("g");
      if (viewport) viewport.removeAttribute("transform");

      // Add a white background because CSS backgrounds are not included in SVG serialization.
      const background = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "rect"
      );
      background.setAttribute("x", "0");
      background.setAttribute("y", "0");
      background.setAttribute("width", String(width));
      background.setAttribute("height", String(height));
      background.setAttribute("fill", "#ffffff");

      svgClone.insertBefore(background, svgClone.firstChild);

      const serializer = new XMLSerializer();
      const svgText = serializer.serializeToString(svgClone);
      const svgBlob = new Blob(
        [svgText],
        { type: "image/svg+xml;charset=utf-8" }
      );

      svgUrl = URL.createObjectURL(svgBlob);

      const image = new Image();

      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(
          new Error("無法將心智圖 SVG 轉換成圖片。")
        );
        image.src = svgUrl;
      });

      const canvas = document.createElement("canvas");
      const resolution = 2;

      canvas.width = Math.round(width * resolution);
      canvas.height = Math.round(height * resolution);

      const context = canvas.getContext("2d");

      if (!context) {
        throw new Error("無法建立 PNG 繪圖畫布。");
      }

      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.scale(resolution, resolution);
      context.drawImage(image, 0, 0, width, height);

      const pngBlob = await new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("PNG 圖片產生失敗。"));
        }, "image/png");
      });

      pngUrl = URL.createObjectURL(pngBlob);

      const link = document.createElement("a");
      link.href = pngUrl;
      link.download = "academic-literature-mindmap.png";

      document.body.appendChild(link);
      link.click();
      link.remove();

      setTimeout(() => URL.revokeObjectURL(pngUrl), 1000);
      pngUrl = null;

    } catch (error) {
      console.error("PNG export failed:", error);
      alert("PNG 匯出失敗：" + (error.message || "未知錯誤"));
    } finally {
      if (svgUrl) URL.revokeObjectURL(svgUrl);
      if (pngUrl) URL.revokeObjectURL(pngUrl);
    }
  });
}