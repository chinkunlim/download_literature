# ADR-006：SQLite 資料庫 + 共用 Runner；references.md 只當輸入、report.md 放結果

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 背景與問題

網頁、指令列、Open WebUI 會同時使用清單；JSON 整檔覆寫會互相蓋掉。md 同時當輸入與結果表格造成混淆，表格需要左右捲動。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A：維持 JSON，整檔讀寫 | 簡單 | 多個入口同時執行會互相覆蓋 |
| B：SQLite（SQLAlchemy 2.0 + Alembic），逐筆更新，一次只跑一個處理工作 | 安全共用、可顯示進度 | 多一層資料庫與遷移檔 |

## 3. 決策與理由

選 B（使用者確認）。
- 資料：`DATA_DIR/db/literature.db`，`items`（清單）與 `jobs`（處理紀錄）。所有更新逐筆進行；工作執行中被刪除的條目不會被寫回。
- 一次只跑一個處理工作：`DATA_DIR/state/run.lock`（作業系統檔案鎖）。
- 新增文獻立即存成「⏳ 待處理」原文，辨識（Crossref/OpenAlex）、去重複在處理時做；查詢失敗保持待處理、下次重試（不再誤標「找不到」）。
- `entrypoints/runner.py` 是指令列、網頁、API 共用的組裝層（新增、重試、刪除、處理、寫檔）。
- 檔案分工：`input/references.md` 只放「待處理」（每筆一段，可多行）與「已處理」精簡清單；`output/report.md` 放完整結果（條列，不用表格）與可複製的 APA 7 清單。重試、刪除改用網頁或 `--retry` / `--delete`。
- 舊 `references.json` 第一次啟動時自動匯入，原檔移到 `DATA_DIR/archive/`。

## 4. 影響與代價

- 結構變更都要新增 Alembic 遷移檔；`agentctl check` 會跑 `alembic upgrade head && alembic check`。
- md 檔是由資料庫產生的；直接改「已處理」清單不會生效（請用網頁或指令）。
