# ADR-004：無人值守模式（需人工的步驟改標需人工處理）與書籍處理

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 背景與問題

使用者不在電腦前時，驗證頁會讓程式卡住；書籍也需要下載（公版）與最新版本資訊。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A：遇到驗證就等使用者（原做法） | 一次跑完 | 使用者不在時整批卡住 |
| B：用程式自動點驗證／CAPTCHA | 全自動 | 繞過機器人偵測，違反出版社條款，不採用 |
| C：預設無人值守：自動驗證給 8 秒，仍需人工就標「需人工處理」跳過；`--interactive` 時才等待 | 不卡住、合規 | 部分條目要使用者回來再跑一次 |

## 3. 決策與理由

選 C。
- `BrowserPublisherFetcher(wait_seconds=0)` 時 `settle()` 拋出 `NeedsUserError(site)`；服務層記下被擋的網站，最後沒有 PDF 就標 `needs_review`，有作者稿則先存作者稿並註明正式版需人工。
- OpenAthens 登入頁仍會自動填 `.env` 帳密（不是人機驗證）。
- 書籍：Open Library 找最新印刷版本（排除有聲書），只有 `ebook_access == public` 且 Internet Archive 未限制借閱的掃描檔才下載；有 DOI 的電子書另走 EBSCO／出版社路線。其餘標「需借閱」並附最新版本資訊。

## 4. 影響與代價

- 無人值守執行不再卡住；需人工的條目集中在 `--interactive` 處理。
- Open Library 版本資料不一定完整（例：Burns 只查到 2012 版），最新版本僅供參考。
