# 本專案專屬規則 (PROJECT_RULES)

> 規則分兩層：`docs/standards/` 的其他文件是**所有專案通用**的規範（由專案模板提供，`agentctl update` 會更新）；
> 本檔是**只適用這個專案**的規則，由這個專案自己維護，模板更新時不會被覆蓋。每次開工都要讀。

## 1. 領域知識與術語

- 使用者在 `DATA_DIR/input/references.md` 的「待處理」區加文獻（ADR-005），或用網頁 / `--add`；程式狀態在 SQLite `DATA_DIR/db/literature.db`（ADR-006），`references.md` 與 `output/report.md` 都由資料庫重寫。PDF 存在 `DATA_DIR/output/literature/<key>.pdf`。
- 指令列、網頁、Open WebUI 共用 `entrypoints/runner.py`；一次只跑一個處理工作（`DATA_DIR/state/run.lock`）。
- 東華大學（NDHU）用 OpenAthens，redirector 網域 `ndhu.edu.tw`；校內 IP（134.208.x.x）直接授權。

## 2. 本專案特有的規則

- 帳密只能填在 `*.openathens.net` 頁面（ADR-001）。
- 每篇下載都要過標題比對才存檔（ISSUE-002）。
- Crossref 搜尋結果必須標題、年份、第一作者都吻合才採用 DOI；不可直接用第一筆（ADR-002）。

## 3. 和通用規範不同的例外（要寫理由）

- Alembic 自動產生的遷移檔（`adapters/db/migrations/versions/`）的 `upgrade()` 可以超過函式長度上限：內容由工具產生，且已 commit 的遷移檔不可修改（ARCHITECTURE_RULES §4）。

## 4. 禁止事項

- 不得自動通過 Cloudflare / CAPTCHA，不得使用影子圖書館（Sci-Hub、LibGen 等）；預設遇到驗證就標「需人工處理」跳過，`--interactive` 才等使用者（ADR-001、ADR-004）。
- 書籍只下載公版／開放授權的掃描檔，不下載 Internet Archive 的借閱本（ADR-004）。
