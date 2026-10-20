# ADR-008：本機網頁 + JSON API（FastAPI，127.0.0.1），Open WebUI 工具呼叫同一組 API

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 背景與問題

使用者希望不用指令或開 md，就能在網頁新增、處理、追進度、下載；也要能當 Ollama / Open WebUI 的工具。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A：只有指令列 | 簡單 | 使用者要開終端機、開 md |
| B：FastAPI 本機網頁（單頁 HTML+JS）+ JSON API；背景單一工作執行緒；Open WebUI 工具呼叫 API | 網頁可完成全部操作；同一組 API 給工具用 | 多一個常駐服務 |

## 3. 決策與理由

選 B。
- `uv run literature-web` → http://127.0.0.1:8765（`HTTP_PORT`）。路由在 `entrypoints/http/`，共用 `Runner`；處理在背景執行緒（`JobManager`），一次一個，與指令列共用 `run.lock`。
- API：`GET/POST /api/items`、`POST /api/items/{key}/retry|reidentify`、`DELETE /api/items/{key}`、`POST /api/process`、`GET /api/status`、`GET /api/apa`、`GET /api/report.md`、`GET /files/{key}`（PDF）；文件在 `/docs`。
- 安全：只綁 127.0.0.1；Host 必須是 127.0.0.1/localhost（防 DNS rebinding），變更請求若帶外部 Origin 一律 403（防惡意網頁 CSRF）。Open WebUI 在 Docker 時，在 `.env` 設 `HTTP_ALLOWED_HOSTS=host.docker.internal`。
- 「人工處理模式」需要使用者在這台 Mac 的 Chrome 操作；網頁只負責觸發與顯示進度。
- Open WebUI：`integrations/openwebui/literature_tool.py`（只用標準函式庫），提供新增、開始處理、查進度、列清單、取 APA 清單。

## 4. 影響與代價

- 網頁與指令列、Open WebUI 共用同一個資料庫，任何一邊的變更另一邊立即可見。
- 複製 APA 清單時同時放 HTML（斜體）與純文字，貼到 Word 會保留斜體。
