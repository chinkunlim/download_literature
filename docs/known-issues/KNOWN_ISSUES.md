# 已知問題 (Known Issues)

記錄「踩過的坑」：值得記住的 bug、外部服務的怪行為、環境問題，以及它們的根本原因與修正方式。
除錯時先查這裡：`grep -rn "關鍵字" docs/known-issues .agents/conversations`（後者只在本機）。

- 新增：`python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-issue <slug> --title "標題" --summary "錯誤訊息" --agent <名字>`
- 格式：[`_TEMPLATE.md`](_TEMPLATE.md)；在修正的程式碼註解加 `Refs: ISSUE-NNN`，並寫防回歸測試。
- 狀態：🔴 未解決 (open) → 🟡 已規避 (mitigated) → 🟢 已根治 (resolved)

> 命名規則：`_TEMPLATE.md` 是新增紀錄時要照著寫的範本；紀錄檔命名為 `NNN-<slug>.md`。整個專案只有根目錄一份 `README.md`。

## 總表

| ISSUE | 狀態 | 標題 | 現象 | 程式與測試 |
|---|---|---|---|---|
| [ISSUE-001](001-playwright-request-blocked.md) | 🟢 已根治 (Resolved) | Playwright context.request 下載 PDF 被出版社防護擋下 (403) | 用 page.context.request.get() 下載 Sage / NEJM / T&F 的 PDF 一律回 403 或 HTML 驗證頁，即使頁面本身已正常載入。 | `adapters/literature/browser.py`；`test_literature.py::BrowserHelpersTest` |
| [ISSUE-002](002-openalex-wrong-paper.md) | 🟡 已規避 (Mitigated) | OpenAlex 開放取用連結可能指向別篇論文 | Braun & Clarke (2006) 的 OpenAlex locations 包含 HAL 與 Dialnet 上完全不同的論文 PDF。 | `services/literature.py::_acceptable`；`test_literature.py::TitleTest` |
| [ISSUE-003](003-cloudflare-loop-automated-chrome.md) | 🟡 已規避 (Mitigated) | Cloudflare 對程式控制的 Chrome 反覆要求驗證 | UWE 典藏庫（worktribe）在 Playwright 開的 Chrome 中，使用者點了驗證後又一直跳回驗證頁；同時程式在頁面跳轉中讀取，出現 Execution context was destroyed。 | `adapters/literature/browser.py::settle` |
| [ISSUE-004](004-refresh-loses-or-downgrades-pdf.md) | 🟢 已根治 (Resolved) | --refresh 會遺失書籍 PDF，或把正式版換成作者稿 | 對已下載的書籍執行 --refresh 且找不到公版掃描檔時，原 PDF 留在 superseded/ 沒有放回；對正式版執行 --refresh 時，若只找到作者稿會直接覆蓋正式版。 | `services/literature.py`；`test_books.py`、`test_literature.py`（refresh 測試） |
| [ISSUE-005](005-job-stuck-running-after-interrupt.md) | 🟢 已根治 (Resolved) | Ctrl-C 或程式中斷後，網頁一直顯示「處理中」 | 指令列下載中按 Ctrl-C（KeyboardInterrupt）或程式被終止時，jobs 表的工作停在 running、條目的步驟沒清掉，網頁之後一直顯示處理中。 | `services/tracker.py`、`entrypoints/runner.py`；`test_workflow.py`、`test_web.py::StaleJobTest` |
| [ISSUE-006](006-inherited-data-dir-overrides-env.md) | 🟡 已規避 (Mitigated) | 系統環境已有 DATA_DIR 時會蓋過本專案 .env | 從 Claude 桌面版預覽（launch.json）啟動網頁時，資料夾變成 ~/open-webui-data，清單是空的；在那裡建立了 db/、logs/、state/。 | `.claude/launch.json`、`config/settings.py` |
