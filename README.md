# download_literature

從 APA 文獻清單自動下載論文 PDF：解析 APA → 到 Crossref 核對並補上 DOI → 先找開放取用版本、再用 Chrome 經學校 OpenAthens／IP 授權到出版社下載 → 核對 PDF 標題 → 產生報告。

## 使用方式

1. 把 APA 格式的參考文獻清單存成 `DATA_DIR/input/references.txt`（或 `.md`），一筆一段；可以直接從 Word 或 Markdown 貼上。
2. 執行：

```bash
uv run fetch-literature
```

3. 結果在 `DATA_DIR/output/literature/`：每篇 `<key>.pdf`，以及 `report.md`（每篇狀態、來源，以及「Check these citations」需要人工確認的引文）。

| 指令 | 用途 |
|---|---|
| `uv run fetch-literature --convert-only` | 只把 APA 轉成 `references.json`，先檢查再下載 |
| `uv run fetch-literature --no-browser` | 只抓開放取用版本，不開 Chrome |
| `uv run fetch-literature --only <key>,<key>` | 只處理指定的文獻（key 見 `references.json`） |
| `uv run fetch-literature --input <檔案>` | 用其他清單（`.txt` / `.md` / `.json`） |

說明：
- 轉換後的 `references.json` 可以手動修改（例如加 `pdf_urls` 放作者網站的 PDF、改 `kind`）；重跑時會保留這些修改與已下載的檔案。
- 校外使用時，`.env` 的 `USER_EMAIL` / `USER_PASSWORD` 只會填在 OpenAthens 登入頁。遇到 Cloudflare / CAPTCHA 驗證，程式會停下來等你在 Chrome 視窗完成；一直重複驗證的網站請改用自己的瀏覽器手動下載，存成 `<key>.pdf` 放進輸出資料夾。
- 專書不會自動下載；學校沒訂閱的期刊會列為 failed，可以找作者／大學網站的版本加進 `pdf_urls`。

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
