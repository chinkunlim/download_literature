# ISSUE-004：--refresh 會遺失書籍 PDF，或把正式版換成作者稿

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 現象

對已下載的書籍執行 --refresh 且找不到公版掃描檔時，原 PDF 留在 superseded/ 沒有放回；對正式版執行 --refresh 時，若只找到作者稿會直接覆蓋正式版。

- **錯誤訊息**：沒有錯誤訊息；結果是清單上的書變成「📕 需借閱」且檔案欄空白，或 ✅ 正式版變成 🟡 作者稿。
- **重現步驟**：`uv run fetch-literature --refresh <已下載的書 key>`（Open Library 沒有公版掃描檔）；或對正式版 key 執行 `--refresh`，而 OpenAlex 只有作者稿。
- **影響範圍**：`services/literature.py` 的 `download_reference()` 與 `_download_book()`；網頁 API 的 `refresh` 參數。

## 2. 根本原因

`download_reference()` 在 refresh 時先把舊檔 `set_aside()` 到 `superseded/`，但書籍分支 `_download_book()` 沒收到這個舊檔，失敗時不會 `restore()`；一般文獻分支只要 `_obtain()` 有回傳就存檔，沒有檢查是不是正式版（`is_version_of_record`）。

## 3. 修正或規避方式

`_download_book(attempt, aside)` 找不到檔案時改走 `_no_pdf()` 放回舊檔；`download_reference()` 在 refresh 且只找到作者稿／預印本時也放回舊檔（ADR-003：`--refresh` 只換成正式版）。

## 4. 防回歸

`tests/test_books.py::BookFlowTest::test_refreshing_a_book_without_a_better_copy_keeps_its_pdf`、`tests/test_literature.py::ServiceTest::test_refresh_never_replaces_a_file_with_an_author_copy`。
