# 架構決策 (Architecture Decision Records)

記錄「為什麼這樣設計」：每個重要的架構取捨一個檔案，之後的人（或 Agent）不用再猜。

- 新增：`python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-adr <slug> --title "標題" --agent <名字>`
- 格式：[`_TEMPLATE.md`](_TEMPLATE.md)；在相關程式碼註解加 `Refs: ADR-NNN`。
- 決策被推翻時不要刪檔，把狀態改成 `Superseded by ADR-NNN`。

> 命名規則：`_TEMPLATE.md` 是新增紀錄時要照著寫的範本；紀錄檔命名為 `NNN-<slug>.md`。整個專案只有根目錄一份 `README.md`。

## 總表

| ADR | 標題 | 狀態 | 日期 | 相關程式 |
|---|---|---|---|---|
| [ADR-001](001-literature-download-strategy.md) | 文獻下載策略：開放取用優先、Chrome 走機構授權、不繞過驗證 | Accepted | 2026-10-20 | TODO |
| [ADR-002](002-apa-list-conversion.md) | APA 清單轉換：本地解析 + Crossref 核對 | Accepted | 2026-10-20 | TODO |
| [ADR-003](003-version-of-record-first.md) | 下載順序：正式版優先（開放取用正式版 → EBSCO → 出版社 → 作者稿/預印本） | Accepted | 2026-10-20 | TODO |
| [ADR-004](004-unattended-mode-and-books.md) | 無人值守模式（需人工的步驟改標需人工處理）與書籍處理 | Accepted | 2026-10-20 | TODO |
| [ADR-005](005-markdown-reference-list.md) | 以 Markdown 清單作為輸入與輸出（待處理區 + APA 7 表格） | Accepted | 2026-10-20 | TODO |
| [ADR-006](006-sqlite-store-and-runner.md) | SQLite 資料庫 + 共用 Runner；references.md 只當輸入、report.md 放結果 | Accepted | 2026-10-20 | TODO |
| [ADR-007](007-chinese-references-airiti.md) | 中文文獻：華藝（Airiti）辨識與下載、中文 APA 格式 | Accepted | 2026-10-20 | TODO |
