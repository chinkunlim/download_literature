# ADR-002：APA 清單轉換：本地解析 + Crossref 核對

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 背景與問題

使用者拿到的文獻清單通常是 APA 格式，需要自動轉成下載用的 JSON（DOI、類型、標題），而且不能配錯論文。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A：只用規則解析 APA 文字 | 離線、快 | 很多引文沒附 DOI；無法分辨書／章節／論文 |
| B：整段引文丟給 Crossref 搜尋，直接用第一筆 | 簡單 | 第一筆常是評論、推薦文（Faculty Opinions）或書評，會配錯 |
| C：本地解析出作者、年份、標題、DOI，再到 Crossref 核對（有 DOI 查 DOI；沒 DOI 搜尋後要標題、年份、第一作者都吻合才接受） | 準確、可解釋；配不到就留下提醒 | 需要網路；Crossref 只記主標題時要特別處理 |

## 3. 決策與理由

選 C。
- 解析：`domain/apa.py`（支援 Markdown 清單、斜體、連結、斷行、`n.d.`、`2008b`、`doi:` 前綴、arXiv）。
- 核對：`services/reference_builder.py`。搜尋結果須同時滿足：標題雙向吻合（或 Crossref 只記主標題、至少 3 個關鍵字且第一作者相同）、年份差 ≤ 1、第一作者不衝突、書不配到期刊論文；Crossref 的 dataset / peer-review 等紀錄直接排除。
- 重跑同一份清單時，以 DOI 或標題對應舊 JSON，保留舊 key、類型、手動加的 `pdf_urls`，已下載的 PDF 不會重抓。
- 配不到的條目寫進報告的「Check these citations」，不中斷流程。

## 4. 影響與代價

- 一個指令完成：`uv run fetch-literature`（讀 `DATA_DIR/input/references.txt`）。
- 實測 21 筆（18 篇論文 + 3 本書）全新轉換，DOI 全部正確，其中 5 篇原文沒附 DOI。
- 代價：沒有 Crossref 紀錄的文獻（部分會議、灰色文獻）只能靠引文中的網址；專書一律列為手動取得。
