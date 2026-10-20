# 本專案專屬規則 (PROJECT_RULES)

> 規則分兩層：`docs/standards/` 的其他文件是**所有專案通用**的規範（由專案模板提供，`agentctl update` 會更新）；
> 本檔是**只適用這個專案**的規則，由這個專案自己維護，模板更新時不會被覆蓋。每次開工都要讀。

## 1. 領域知識與術語

- 使用者的清單是 `DATA_DIR/input/references.md`（待處理區 + APA 7 表格，ADR-005），程式狀態在同名 `references.json`。PDF 存在 `DATA_DIR/output/literature/<key>.pdf`。
- 東華大學（NDHU）用 OpenAthens，redirector 網域 `ndhu.edu.tw`；校內 IP（134.208.x.x）直接授權。

## 2. 本專案特有的規則

- 帳密只能填在 `*.openathens.net` 頁面（ADR-001）。
- 每篇下載都要過標題比對才存檔（ISSUE-002）。
- Crossref 搜尋結果必須標題、年份、第一作者都吻合才採用 DOI；不可直接用第一筆（ADR-002）。

## 3. 和通用規範不同的例外（要寫理由）

- （例）`legacy_parser.py` 暫時允許 900 行：正在依 TASK-012 拆分。

## 4. 禁止事項

- 不得自動通過 Cloudflare / CAPTCHA，不得使用影子圖書館（Sci-Hub、LibGen 等）；預設遇到驗證就標「需人工處理」跳過，`--interactive` 才等使用者（ADR-001、ADR-004）。
- 書籍只下載公版／開放授權的掃描檔，不下載 Internet Archive 的借閱本（ADR-004）。
