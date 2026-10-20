# ISSUE-006：系統環境已有 DATA_DIR 時會蓋過本專案 .env

- **狀態**：🟡 已規避 (Mitigated)
- **發現日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 現象

從 Claude 桌面版預覽（launch.json）啟動網頁時，資料夾變成 ~/open-webui-data，清單是空的；在那裡建立了 db/、logs/、state/。

- **錯誤訊息**：`run started ... log_dir=/Users/limchinkun/open-webui-data/logs`（應為 `~/project-data/download-literature/logs`）
- **重現步驟**：在已設定 `DATA_DIR`（給別的專案用）的環境中執行 `uv run literature-web`。
- **影響範圍**：`config/settings.py::load_dotenv_file`（`os.environ.setdefault`），所有入口。

## 2. 根本原因

`load_dotenv_file()` 依框架慣例不覆蓋已存在的環境變數；`DATA_DIR` 是通用名稱，別的專案（Open WebUI）在桌面 App 的環境設了同名變數，於是被繼承並優先使用。

## 3. 修正或規避方式

規避：`.claude/launch.json` 改用 `env -u DATA_DIR uv run literature-web` 啟動，讓 `.env` 生效。一般終端機沒有這個變數時不受影響。根治（例如改用專案專屬變數名稱）屬於專案模板的決定，已寫進 `docs/TEMPLATE_FEEDBACK.md`。啟動 log 第一行的 `log_dir=` 可確認實際資料夾。

## 4. 防回歸

環境相關，無離線測試；啟動網頁後檢查 log 的 `log_dir=` 是否為 `.env` 的 `DATA_DIR`。
