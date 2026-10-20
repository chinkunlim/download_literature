# download_literature

從 APA 文獻清單自動下載論文 PDF：解析 APA → 到 Crossref 核對並補上 DOI → 先找開放取用版本、再用 Chrome 經學校 OpenAthens／IP 授權到出版社下載 → 核對 PDF 標題 → 產生報告。

## 使用方式

### 網頁（建議）

```bash
uv run literature-web
```

打開 http://127.0.0.1:8765 ：貼上文獻 → 「開始處理」→ 在清單追進度、開啟 PDF、重試／重新辨識／刪除、複製 APA 7 清單（貼到 Word 保留斜體）、下載 report.md。
在電腦前時按「人工處理模式」：遇到機器人驗證或登入，會等你在 Chrome 完成。

### 檔案與指令

- **輸入**：`DATA_DIR/input/references.md` 的「待處理」（每筆一段，可以是 APA、作者＋標題、標題或 DOI，中英文皆可）。
- **結果**：`DATA_DIR/output/report.md`（每篇的 APA、狀態、檔案、來源、備註，以及可複製的 APA 7 清單）；PDF 在 `DATA_DIR/output/literature/`。

| 指令 | 用途 |
|---|---|
| `uv run fetch-literature` | 處理：md 的新文獻＋所有待處理 |
| `uv run fetch-literature --add "標題或 APA"` | 新增文獻（可重複 `--add`） |
| `uv run fetch-literature --status` | 只看目前狀態 |
| `uv run fetch-literature --interactive` | 在電腦前時：處理「⚠️ 需人工處理」 |
| `--retry <key>` / `--reidentify <key>` / `--delete <key>` | 重新下載／重新辨識（新 APA）／移除 |
| `--identify-only` / `--no-browser` / `--refresh <key>` | 只辨識／只抓開放取用／嘗試換成正式版 |

### Open WebUI（Ollama）工具

1. 執行 `uv run literature-web`。
2. Open WebUI → Workspace → Tools → 新增，貼上 `integrations/openwebui/literature_tool.py` 的內容。
3. Open WebUI 在 Docker 裡：工具設定（Valves）的 `base_url` 用 `http://host.docker.internal:8765`，並在本專案 `.env` 加 `HTTP_ALLOWED_HOSTS=host.docker.internal`；非 Docker 安裝則用 `http://127.0.0.1:8765`。

### 說明

- 資料在 `DATA_DIR/db/literature.db`；網頁、指令、Open WebUI 共用，一次只會有一個處理工作。
- 下載順序：正式版優先（出版社免費正式版 → 華藝（中文）→ EBSCO → 出版社網站 → 作者稿／預印本），每篇核對 PDF 標題。
- 預設不等人工：遇到驗證標「⚠️ 需人工處理」並繼續；程式不會自動點驗證。
- 書籍：公版書從 Internet Archive 下載；有版權的書標「📕 需借閱」並列出最新版本。
- 校外時，`.env` 的 `USER_EMAIL` / `USER_PASSWORD` 只會填在 OpenAthens 登入頁。

## 第一次在這台電腦使用

1. 取得程式（已經在本機就略過）

```bash
git clone <repo-url> && cd download_literature
```

2. 檢查並修復環境：啟用 git hook、建立 `.env`、建立 DATA_DIR、檢查 uv（只修這個專案，不安裝全域工具）

```bash
python3 scripts/agentctl.py doctor --fix
```

3. 打開 `.env` 填入金鑰與設定（`.env` 不會被 commit）。

4. 安裝依賴：uv sync（專案內 `.venv/`）

```bash
python3 scripts/agentctl.py setup --install
```

> 換電腦時：資料不在 git 裡，另外複製整個 `DATA_DIR`（路徑寫在 `.env`）。
> 搬移或改名專案資料夾後：執行一次 `python3 scripts/agentctl.py doctor --fix`（重建記住舊位置的 `.venv`）。

新增 Python 套件：`uv add <套件>`（開發工具 `uv add --dev <套件>`）；執行程式：`uv run ...`。Python 版本由 uv 依 `.python-version` 自動下載，不會動到主機的 Python / pip。

## 確認一切正常

註解、分層、秘密、lint、型別、目錄樹

```bash
python3 scripts/agentctl.py check
```

專案測試

```bash
uv run python -m unittest discover -s tests -v
```

## 和 AI Agent 一起開發

用 Claude Code、Antigravity、Cursor 等工具打開這個資料夾，Agent 會自動讀 `AGENTS.md`。直接用口語下指令：

| 你說 | Agent 會做 |
|---|---|
| 「開工」「繼續上次的」 | 看交接看板、上次的下一步、未完成的任務 |
| 「新功能：…」 | 建任務卡，寫測試與程式 |
| 「commit」 | 檢查後本機 commit（英文訊息，不會推送） |
| 「去上課」「先暫停」 | 記下進度，下次接著做 |
| 「收工」 | 測試、寫對話紀錄與摘要、更新交接看板、commit |
| 「推上去」 | 列出要推送的 commit，等你同意 |
| 「出版本」「專案完成了」 | 完成驗收；`--tag` 時升版並打 tag |

完整對照表見 [`AGENTS.md`](AGENTS.md) §1。

## 常用指令

```bash
python3 scripts/agentctl.py status
```

```bash
python3 scripts/agentctl.py task create "標題" --agent <名字>
```

```bash
python3 scripts/agentctl.py commit --agent <名字>
```

```bash
python3 scripts/agentctl.py closeout --agent <名字>
```

全部子指令

```bash
python3 scripts/agentctl.py --help
```

## 文件索引

- [`AGENTS.md`](AGENTS.md) — Agent 規則與「文件放哪裡」對照表
- [`.agents/handoff/LATEST.md`](.agents/handoff/LATEST.md) — 交接看板
- `.agents/conversations/` — 每次對話的逐字稿與摘要（本機，不進 git）
- [`docs/adr/DECISIONS.md`](docs/adr/DECISIONS.md) — 架構決策
- [`docs/known-issues/KNOWN_ISSUES.md`](docs/known-issues/KNOWN_ISSUES.md) — 已知問題
- [`docs/specs/SPECS.md`](docs/specs/SPECS.md) — 需求規格
- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) — 系統架構與目錄樹（依賴圖、審計報告需要時用 `agentctl graph` / `agentctl audit` 產生）
- [`docs/standards/PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md) — 本專案特有的規則
- [`CHANGELOG.md`](CHANGELOG.md) — 版本變更
