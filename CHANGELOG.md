# Changelog

All notable changes to **download_literature** are documented here
(format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions: [SemVer](https://semver.org/)).

## [Unreleased]

### Added
- feat(literature): add literature downloader with open-access lookup and OpenAthens browser route (TASK-001) (`TASK-001`, by `@claude-code`)
- feat(literature): try author and repository PDF URLs through the browser (TASK-001) (`TASK-001`, by `@claude-code`)
- feat(literature): convert APA reference lists via Crossref and run the full pipeline in one command (by `@claude-code`)
- feat(literature): add EBSCO route and prefer versions of record over preprints (by `@claude-code`)
- feat(literature): format APA 7 references and resolve title-only inputs via Crossref and OpenAlex (by `@claude-code`)
- feat(literature): look up latest book editions and download public-domain scans via Open Library (by `@claude-code`)
- feat(literature): skip steps that need a person and mark them needs_review unless --interactive (by `@claude-code`)
- feat(literature): use a Markdown reference list as input and APA 7 output, processing only new entries (by `@claude-code`)
- feat(literature): store the list in SQLite, share a runner across front ends, split references.md and report.md (by `@claude-code`)
- feat(literature): identify and download Chinese references through Airiti with Chinese APA 7 formatting (by `@claude-code`)
- feat(literature): add local web app, JSON API and Open WebUI tool (by `@claude-code`)

### Fixed
- fix(literature): wait for a stable page after bot checks before fetching (TASK-001) (`TASK-001`, by `@claude-code`)
- fix(literature): keep PDFs on refresh, close interrupted jobs, remove template leftovers and update docs (by `@claude-code`)

### Documentation
- docs: update repository clone URL to literature-fetch (by `@antigravity`)

## [0.1.0] - 2026-10-20
### Added
- Initial project scaffold (framework v3.1.0).
