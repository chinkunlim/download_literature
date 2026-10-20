"""Command-line entrypoint (also usable as a tool by Ollama / Open WebUI) — ADR-006.

Usage:
    uv run fetch-literature                        # process: entries in references.md + pending items
    uv run fetch-literature --add "Your Brain on ChatGPT" --add "10.1037/a0027600"
    uv run fetch-literature --interactive          # at the computer: also handle ⚠️ items
    uv run fetch-literature --retry Gross_1998_RGP # process an item again
    uv run fetch-literature --delete Old_2001_X    # remove an item from the list
    uv run fetch-literature --status               # print the list without processing
    uv run fetch-literature --identify-only | --no-browser | --only K1,K2 | --refresh K1

Everything is stored in the database (`DATA_DIR/db/literature.db`); `input/references.md` and
`output/report.md` are rewritten after every command. The web app (`uv run literature-web`) uses
the same data.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter

from download_literature.adapters.literature.tracker_md import STATUS_LABELS, short_apa
from download_literature.config.logging_setup import setup_logging
from download_literature.config.settings import load_config
from download_literature.domain.tracker import AlreadyRunningError, ItemStatus
from download_literature.entrypoints.runner import ProcessOptions, Runner, RunSummary

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line options.

    Args:
        argv: Arguments; defaults to `sys.argv[1:]`.

    Returns:
        Parsed options.
    """
    p = argparse.ArgumentParser(description="Reference list: add, process, retry, delete, show status")
    p.add_argument(
        "--add", action="append", default=[], help="add an entry (APA, title, author + title or DOI)"
    )
    p.add_argument("--retry", default="", help="comma-separated keys to process again")
    p.add_argument("--delete", default="", help="comma-separated keys to remove from the list")
    p.add_argument("--status", action="store_true", help="print the list and exit (no processing)")
    p.add_argument("--identify-only", action="store_true", help="identify new entries, no download")
    p.add_argument("--no-browser", action="store_true", help="open access only; no Chrome")
    p.add_argument("--only", default="", help="comma-separated keys to process in this run")
    p.add_argument(
        "--refresh", default="", help="comma-separated keys whose PDF should be replaced if better"
    )
    p.add_argument("--interactive", action="store_true", help="wait for bot checks / sign-ins; retry ⚠️ items")
    p.add_argument("--wait", type=int, default=300, help="seconds to wait per check in --interactive mode")
    return p.parse_args(argv)


def _keys(value: str) -> frozenset[str]:
    """Split a comma-separated key option.

    Args:
        value: Option text.

    Returns:
        Keys.
    """
    return frozenset(k.strip() for k in value.split(",") if k.strip())


def _print_status(runner: Runner) -> None:
    """Print counts and the items that need the user.

    Args:
        runner: Shared runner.
    """
    items = runner.store.list_items()
    counts = Counter(i.status for i in items)
    print(f"清單共 {len(items)} 筆｜報告：{runner.report_md}")
    for status in ItemStatus:
        if counts[status]:
            print(f"  {STATUS_LABELS[status]}：{counts[status]}")
    for item in items:
        if item.status in (ItemStatus.NEEDS_REVIEW, ItemStatus.NOT_FOUND, ItemStatus.PENDING):
            print(f"  - {STATUS_LABELS[item.status]} {item.key}：{short_apa(item, 70)}")
    if counts[ItemStatus.NEEDS_REVIEW]:
        print("  在電腦前時執行：uv run fetch-literature --interactive")


def _print_run(summary: RunSummary) -> None:
    """Print what a run did.

    Args:
        summary: Run summary.
    """
    queued, identified, processed = len(summary.queued), summary.identify.changed, len(summary.processed)
    print(f"從 references.md 加入 {queued} 筆，辨識 {identified} 筆，處理 {processed} 筆")
    for line in summary.identify.duplicates:
        print(f"  已在清單中，略過：{line}")


def main(argv: list[str] | None = None) -> int:
    """Run one command.

    Args:
        argv: Command-line arguments; defaults to `sys.argv[1:]`.

    Returns:
        0 on success, 3 when another job is already running.
    """
    config = load_config()
    args = _parse_args(argv)
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    runner = Runner(config)
    if args.add:
        print(f"已加入 {len(runner.add_entries(args.add))} 筆")
    if args.retry:
        print(f"重新處理：{', '.join(runner.retry(set(_keys(args.retry)))) or '（沒有符合的 key）'}")
    if args.delete:
        print(f"已移除：{', '.join(runner.delete(set(_keys(args.delete)))) or '（沒有符合的 key）'}")
    if not args.status:
        options = ProcessOptions(
            args.interactive,
            args.wait,
            not args.no_browser,
            _keys(args.only),
            _keys(args.refresh),
            args.identify_only,
        )
        try:
            _print_run(runner.process(options))
        except AlreadyRunningError:
            print("另一個處理工作正在執行（網頁或另一個指令），請稍後再試。")
            return 3
    if args.status:
        runner.write_files()
    _print_status(runner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
