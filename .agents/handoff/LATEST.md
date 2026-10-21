# 🤝 Agent 狀態看板與交接紀錄 (`LATEST.md`)

> **AI Agent 開工必讀**：進入對話時請先閱讀下方「即時狀態看板」，確認上一位 Agent 的完成進度、待接手任務 (`handed_off`) 與注意事項；詳細過程請看本機的 `.agents/conversations/`。

<!-- LIVE_STATE_START -->
## 📊 即時狀態看板 (Live Snapshot)

- **最後更新時間**: `2026-10-21 13:32 UTC`
- **最近操作 Agent**: `claude-code`
- **目前 Git 分支**: `main`
- **最新 Git Commit**: `4c896aa chore(tooling): update tooling tooling and config (ISSUE-004, ISSUE-005, ISSUE-006, TASK-001) [agent:claude-code]`

### 🎯 進行中 / 待接手任務 (Active & Handed-Off Tasks)

> 目前無進行中或待接手任務。可執行 `python3 scripts/agentctl.py task create "任務名稱" --agent <name>` 建立任務。

<!-- LIVE_STATE_END -->

## 📜 交接與活動時間軸 (Handoff & Activity Timeline)

### [2026-10-21 13:32 UTC] Session Closeout (結束對話收尾) (by `claude-code`)
- **檢查結果**: 測試與 Code Review Guard 通過
- **目標**: Full review of the literature downloader: requirements, bugs, docs consistency, test leftovers, push to GitHub; then point the project at the moved data folder
- **錯誤與根因**: Inherited DATA_DIR from the desktop app env overrode .env -> load_dotenv uses setdefault -> launch.json runs env -u DATA_DIR (ISSUE-006, mitigated, template fee
- **下一步**: Ask the user whether to push the local commits; optional: rename the GitHub repo to match literature-fetch; decide ISSUE-006 template feedback
- **交接備註**: All checks and 130 tests pass; data in ~/Desktop/projects-data/literature-fetch
- **本機對話紀錄**: `.agents/conversations/2026-10-21-2132-claude-code-2-summary.md`（只在這台電腦）

### [2026-10-21 13:32 UTC] Session Closeout (結束對話收尾) (by `claude-code`)
- **檢查結果**: 測試與 Code Review Guard 通過
- **目標**: Check whether the pasted 19 APA references were downloaded; import the manually downloaded Heinz 2025 (NEJM AI) PDF
- **錯誤與根因**: No CLI/web command exists to import a manually downloaded PDF; had to use a one-off Python snippet. Report source field must be a URL (plain text renders empty)
- **下一步**: Consider adding an 'import local PDF' operation (CLI + web + MCP with confirm). Handle the 5 list items not in the user's pasted list (2 Chinese, Kosmyna 2025, 
- **交接備註**: 16 VoR / 5 author copies / 3 books to borrow; nothing unavailable
- **本機對話紀錄**: `.agents/conversations/2026-10-21-2132-claude-code-summary.md`（只在這台電腦）

### [2026-10-21 13:31 UTC] Session Closeout (結束對話收尾) (by `claude-code`)
- **檢查結果**: 測試與 Code Review Guard 通過
- **目標**: Verify the project runs on its own after moving to ~/Desktop/projects/literature-fetch, then push the pending commit.
- **錯誤與根因**: agentctl commit --push does nothing when there are no new changes; the pre-push hook needs ALLOW_PUSH=1 and the agent's override was blocked by the auto-mode sa
- **下一步**: Optional: auto-start the web app at login (launchd); test off-campus OpenAthens login; handle Airiti theses/book chapters; consider a project-specific DATA_DIR 
- **交接備註**: Project moved to ~/Desktop/projects/literature-fetch; everything verified working and main is in sync with origin.
- **本機對話紀錄**: `.agents/conversations/2026-10-21-2131-claude-code-summary.md`（只在這台電腦）

### [2026-10-20 13:06 UTC] 完成任務 `TASK-001` — Literature downloader with OpenAthens and download project references (by `claude-code`)
- **狀態**: ✅ 已完成 (`done`)
- **完成摘要**: Literature downloader complete: APA/title/DOI input (EN+ZH), Crossref/OpenAlex/Airiti identification, VoR-first download (OA, Airiti, EBSCO, OpenAthens), SQLite store, CLI + local web app + Open WebUI tool. Full review fixed refresh data loss (ISSUE-004), stuck jobs (ISSUE-005), DATA_DIR override (ISSUE-006, mitigated).

### [2026-10-20 06:09 UTC] 建立任務 `TASK-001`: Literature downloader with OpenAthens and download project references (by `claude-code`)
- **狀態**: `in_progress`
- **相關範圍**: `-`

### [2026-10-20 05:47 UTC] Initial Bootstrap (by `init_project`)
- **狀態**: 專案已初始化（框架 v3.1.0）。
- **下一步**: 檢視 `.agents/project.toml`，再用 `agentctl task create` 建立第一個任務。
