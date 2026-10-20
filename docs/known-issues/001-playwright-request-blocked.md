# ISSUE-001：Playwright context.request 下載 PDF 被出版社防護擋下 (403)

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 現象

用 page.context.request.get() 下載 Sage / NEJM / T&F 的 PDF 一律回 403 或 HTML 驗證頁，即使頁面本身已正常載入。

- **錯誤訊息**：`pdf request attempt=1 status=403 bytes=5815 url=https://journals.sagepub.com/doi/pdf/10.1177/1754073917742706`（內容是 "Just a moment..." 驗證頁）
- **重現步驟**：在已載入出版社文章頁的 Playwright context 中呼叫 `page.context.request.get(pdf_url)`。
- **影響範圍**：Sage、NEJM AI、Wiley、T&F 等有 Cloudflare 防護的出版社，PDF 全部抓不到。

## 2. 根本原因

`APIRequestContext` 是在瀏覽器之外由 Playwright 自己送出的請求，連線特徵和真正的瀏覽器不同，出版社的防護把它當成機器人；頁面導覽本身是真的 Chrome，所以不受影響。

## 3. 修正或規避方式

改成在頁面內執行 `fetch(url, {credentials: 'include'})`，把內容以 base64 傳回（`BrowserPublisherFetcher._fetch_in_page`）。Wiley 的 `/doi/pdf/` 是閱讀器頁，改用 `/doi/pdfdirect/...?download=true`（`pdf_url_variants`）。

## 4. 防回歸

`tests/test_literature.py::BrowserHelpersTest`（網址規則）；瀏覽器下載本身需實機驗證：`uv run fetch-literature --only Torre_2018_EmotRev`。
