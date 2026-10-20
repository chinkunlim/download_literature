# ISSUE-005：Ctrl-C 或程式中斷後，網頁一直顯示「處理中」

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-10-20
- **Agent**：`claude-code`
- **任務**：`TASK-001`

## 1. 現象

指令列下載中按 Ctrl-C（KeyboardInterrupt）或程式被終止時，jobs 表的工作停在 running、條目的步驟沒清掉，網頁之後一直顯示處理中。

- **錯誤訊息**：沒有錯誤訊息；`jobs` 表最後一筆 `state=running`、`finished_at` 為空，網頁顯示「處理中」不會結束。
- **重現步驟**：`uv run fetch-literature` 下載途中按 Ctrl-C，之後開 `uv run literature-web`。
- **影響範圍**：網頁進度列、`/api/status`、Open WebUI 的 get_status。

## 2. 根本原因

`download_items()` 只用 `except Exception` 收尾；`KeyboardInterrupt` 繼承自 `BaseException`，不會進到收尾，工作與步驟停在進行中。程式被強制終止（kill、當機）時則完全沒有機會收尾。

## 3. 修正或規避方式

`download_items()` 改用 `except BaseException` 標記失敗並清除步驟後再拋出；`Runner` 啟動時若能取得 `run.lock`（表示沒有工作在跑），用 `SqlItemStore.close_stale()` 把殘留的 running 工作標成 failed 並清除所有步驟。

## 4. 防回歸

`tests/test_workflow.py::DownloadTest::test_interrupted_run_is_recorded_as_failed`、`tests/test_web.py::StaleJobTest::test_new_runner_closes_jobs_and_steps_left_by_a_stopped_process`。
