# ISSUE-003：Cloudflare 對程式控制的 Chrome 反覆要求驗證

- **狀態**：🟡 已規避 (Mitigated)
- **發現日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 現象

UWE 典藏庫（worktribe）在 Playwright 開的 Chrome 中，使用者點了驗證後又一直跳回驗證頁；同時程式在頁面跳轉中讀取，出現 Execution context was destroyed。

- **錯誤訊息**：`browser route failed key=Braun_2006_QRP: Page.evaluate: Execution context was destroyed, most likely because of a navigation`；之後 in-page fetch 回 403（Cloudflare 頁）。
- **重現步驟**：`uv run fetch-literature --wait 300 --only Braun_2006_QRP`，在 Chrome 點 Cloudflare 驗證。
- **影響範圍**：用 Cloudflare 互動驗證的網站（worktribe 典藏庫、部分 ScienceDirect 頁面）。

## 2. 根本原因

1. Cloudflare 能偵測到瀏覽器由自動化工具控制，人工點擊後仍持續要求驗證。依 ADR-001 不使用隱藏自動化的手段。
2. 驗證頁會先短暫消失再重新載入，`_settle` 一看到非驗證頁就結束，接著在跳轉中執行 `page.evaluate` 而失敗。

## 3. 修正或規避方式

- `_settle` 需連續兩次檢查都不是驗證頁才結束；`_needs_user` 讀標題失敗時視為仍在跳轉。
- 這類網站改由使用者用自己的瀏覽器手動下載，存成 `<key>.pdf` 放進 `DATA_DIR/output/literature/`。

## 4. 防回歸

瀏覽器行為無法離線測試；以實機重跑 `--only Braun_2006_QRP` 驗證不再出現 Execution context 錯誤。
