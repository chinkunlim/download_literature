# ADR-001：文獻下載策略：開放取用優先、Chrome 走機構授權、不繞過驗證

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 背景與問題

需要下載專題引用的文獻；部分在付費出版社，東華用 OpenAthens（校外）與 IP（校內）授權，出版社多有 Cloudflare 防護。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A：純 HTTP（httpx）抓所有來源 | 簡單、快、可離線測試 | 付費出版社有 Cloudflare / 機構驗證，程式請求一律被擋 |
| B：開放取用優先（arXiv、明列網址、OpenAlex）＋ 有頭 Chrome（Playwright，用已安裝的 Google Chrome）走 OpenAthens redirector | 合法、能用學校授權；人工驗證時使用者可在視窗內完成 | 需要開視窗；部分網站仍須使用者點驗證 |
| C：用 stealth 套件或第三方服務自動通過 Cloudflare / CAPTCHA，或用影子圖書館 | 全自動 | 違反出版社條款與學校授權規範，不採用 |

## 3. 決策與理由

選 B。順序：書籍標記 manual → 已存在跳過 → arXiv / 明列網址 / OpenAlex 開放取用（httpx）→ Chrome 開 `go.openathens.net/redirector/<domain>?url=https://doi.org/<doi>`。
- 校內 IP 時 redirector 直接轉到出版社；校外時出現 OpenAthens 登入頁，程式**只在 `*.openathens.net`** 填入 `.env` 的 `USER_EMAIL` / `USER_PASSWORD`。
- Cloudflare 驗證、CAPTCHA、Google / Microsoft 登入一律不自動處理，程式暫停等使用者在視窗完成（`--wait` 秒）。
- PDF 用頁面內 `fetch()` 下載（見 ISSUE-001），並以前兩頁文字比對標題（見 ISSUE-002）。

## 4. 影響與代價

- 正面：合法、可重跑（已下載會跳過）、每篇都有報告 `DATA_DIR/output/literature/report.md`。
- 代價：學校沒訂閱的期刊（例如 NEJM AI、部分 APA / T&F）抓不到，需館際合作或向作者索取；ScienceDirect 常要求人工驗證。
- Chrome profile 存在 `DATA_DIR/state/browser_profile`，保留登入狀態；換電腦需重新登入。
- 程式：`src/download_literature/adapters/literature/`、`services/literature.py`、`entrypoints/fetch_cli.py`。
