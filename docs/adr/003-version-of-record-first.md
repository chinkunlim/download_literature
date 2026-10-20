# ADR-003：下載順序：正式版優先（開放取用正式版 → EBSCO → 出版社 → 作者稿/預印本）

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 背景與問題

研究需要同儕審查的正式版；預印本與作者稿頁碼不同。東華透過 EBSCO 訂閱 PsycARTICLES、Academic Search Premier 等，且 EBSCO 較少機器人驗證。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A：開放取用（含預印本）最先，出版社最後 | 最快 | 常拿到預印本／作者稿（例：Schleider 2022 拿到 OSF 版） |
| B：出版社優先，再 EBSCO | 直接用 DOI，不需搜尋 | 出版社網站常有 Cloudflare 驗證，需要人工 |
| C：正式版開放取用 → EBSCO → 出版社 → 預印本／作者稿 | 優先拿正式版，且 EBSCO 少驗證；作者稿只在最後用並標註 | EBSCO 用搜尋，需要標題比對防配錯 |

## 3. 決策與理由

選 C（使用者確認）。
- 是否為正式版：依 OpenAlex location 的 `version`（publishedVersion，或無版本但由期刊提供）判斷，不靠網址猜。
- EBSCO：`research.ebsco.com/c/<profile>`（東華 `3pnjf3`，`.env` 的 `EBSCO_PROFILE`）。用 DOI 搜尋，只採用標題吻合的結果，開 PDF 閱讀器並接住它載入的 `application/pdf` 回應。
- 機構路線依序嘗試；某路線拿到別篇（標題不符）就換下一條。
- 作者稿／預印本下載後在報告標註「author/preprint copy」。`--refresh` 可把既有檔案換成正式版，找不到則保留舊檔（舊檔移到 `superseded/`）。

## 4. 影響與代價

- 實測：Webb 2012（原本拿不到）由 EBSCO 取得正式版；Neff 2003、Ayduk 2010、Schleider 2022、Sharma 2024、Moore 2025 由作者稿／預印本換成正式版。
- 代價：每篇多一次 EBSCO 搜尋（約 10–20 秒）。EBSCO 有禁載期的新文章仍需出版社路線。
