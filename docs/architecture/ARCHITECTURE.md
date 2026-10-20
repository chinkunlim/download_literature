# 系統架構 (Architecture)

> 手動維護本檔的「系統概覽」；以下報告由工具自動產生，請勿手動修改。

| 文件 | 內容 | 產生方式 |
|---|---|---|
| [`PROJECT_TREE.md`](PROJECT_TREE.md) | 完整目錄樹 | `agentctl sync` / 每次 commit |
| `GRAPH_REPORT.md` | 模組依賴圖、分層檢查、函式大小 | 需要時 `agentctl graph`（不進 git） |
| `AGENT_AUDIT_REPORT.md` | 各 Agent 的 commit 與任務 | 需要時 `agentctl audit`（不進 git） |

## 系統概覽

三個入口（指令列 `fetch-literature`、本機網頁 `literature-web`、Open WebUI 工具）都經過同一個 `Runner`，資料存在 SQLite；一次只跑一個處理工作。

```text
fetch_cli ─┐
web_cli ───┼─► entrypoints/runner.py (Runner) ──► adapters/db (SQLite: items, jobs)
Open WebUI ┘     │  (HTTP API: entrypoints/http)   adapters/locks.py (run.lock)
                 │
                 ├─ 1. 讀 input/references.md「待處理」→ queue_entries（⏳ 待處理）
                 ├─ 2. identify_pending：Crossref + OpenAlex（中文另加華藝）→ APA 7、去重複
                 ├─ 3. download_items：每篇依序嘗試
                 │      開放取用正式版 → 華藝 → EBSCO → 出版社（Chrome + OpenAthens）
                 │      → 作者稿／預印本；每篇核對 PDF 標題
                 └─ 4. 重寫 input/references.md（精簡清單）與 output/report.md
```

| 元件 | 位置 | 說明 |
|---|---|---|
| 解析與格式 | `domain/apa.py`、`apa_format.py`、`literature.py` | APA 解析、APA 7（中英文）、標題比對；純函式，無 I/O |
| 流程 | `services/reference_builder.py`、`tracker.py`、`literature.py` | 辨識、清單狀態、下載順序（ADR-002、003、005） |
| 外部服務 | `adapters/literature/` | Crossref、OpenAlex、Open Library、EBSCO、華藝、Chrome（Playwright）、PDF 文字 |
| 資料 | `adapters/db/`（Alembic 遷移）、`adapters/locks.py` | 逐筆更新；工作紀錄與每篇目前步驟（ADR-006） |
| 入口 | `entrypoints/` | 指令列、FastAPI 網頁與 JSON API（只綁 127.0.0.1，ADR-008） |

資料都在 `DATA_DIR`（專案資料夾外）：`input/references.md`、`output/report.md`、`output/literature/*.pdf`、`db/literature.db`、`state/`（run.lock、Chrome profile）、`logs/`。

外部服務：Crossref、OpenAlex、Open Library / Internet Archive、EBSCO Discovery、華藝、出版社網站（經 OpenAthens redirector 或校內 IP）。不自動通過 Cloudflare / CAPTCHA（ADR-001、ADR-004）。

## 分層

見 `.agents/project.toml` 的 `[architecture] layers` 與 [`ARCHITECTURE_RULES.md`](../standards/ARCHITECTURE_RULES.md)。
