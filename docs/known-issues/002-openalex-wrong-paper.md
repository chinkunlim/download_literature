# ISSUE-002：OpenAlex 開放取用連結可能指向別篇論文

- **狀態**：🟡 已規避 (Mitigated)
- **發現日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 現象

Braun & Clarke (2006) 的 OpenAlex locations 包含 HAL 與 Dialnet 上完全不同的論文 PDF。

- **錯誤訊息**：`title mismatch, rejected key=Braun_2006_QRP first_text='Estrategias didácticas para un aprendizaje constructivista...'`
- **重現步驟**：`GET https://api.openalex.org/works/doi:10.1191/1478088706qp063oa`，看 `locations` 中 hal.science 與 dialnet 的 `pdf_url`。
- **影響範圍**：任何靠 OpenAlex 開放取用連結下載的文獻，可能把別篇論文存成這篇。

## 2. 根本原因

OpenAlex 會把「引用了這篇的文章」或錯誤配對的倉儲紀錄列為該作品的 location；索引資料本身有錯。

## 3. 修正或規避方式

文獻清單加 `title` 欄位；下載後以 pypdf 讀前兩頁文字，標題中 4 個字母以上的字要有 70% 出現才存檔（`domain.literature.title_matches`、`services.literature._acceptable`）。沒有文字層的掃描檔不擋，但記 WARNING。

## 4. 防回歸

`tests/test_literature.py::TitleTest`、`ServiceTest::test_wrong_paper_is_rejected_and_next_source_used`、`ServiceTest::test_unreadable_pdf_text_is_accepted`。
