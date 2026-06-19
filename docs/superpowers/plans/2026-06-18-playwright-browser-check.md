# Playwright Browser Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Playwright Chromium browser-real detection layer, document it, expose it in API/UI/config/deployment, and verify it against `https://dashboard.prem.io/auth/login` with manual check concurrency 10.

**Architecture:** Keep `proxy_check.py` as the HTTP fast-check engine. Add `browser_check.py` as a focused Playwright engine. Let `server.py` orchestrate two-stage detection, runtime settings, capabilities, and `/api/deep-check`; let the frontend configure and display browser results.

**Tech Stack:** Python 3.11, `curl_cffi`, Playwright Python Chromium, stdlib HTTP server, vanilla JS frontend, Docker.

---

## Files

- Create `browser_check.py`: Playwright config/result dataclasses, proxy normalization, page verdict logic, async browser engine, JSON merge helper.
- Create `tests/test_browser_check.py`: unit tests for proxy normalization, verdict logic, and result merge semantics.
- Create `tests/test_server_browser_config.py`: unit tests for server-facing config normalization and settings payload.
- Modify `proxy_check.py`: add `http_valid` and default browser result fields in public results.
- Modify `server.py`: replace nodriver capability with Playwright, add settings, runtime config, browser-check orchestration, `/api/deep-check` rewrite.
- Modify `app.js`: settings UI and proxy card display for Playwright browser results.
- Modify `config.json`, `.env.example`, `requirements.txt`, `Dockerfile`, `start.sh`, `start.ps1`, `README.md`.

## Task 1: Tests for browser_check pure behavior

- [ ] Create `tests/test_browser_check.py` with tests for proxy normalization and verdict/merge behavior.
- [ ] Run `python -m unittest tests.test_browser_check -v` and confirm it fails because `browser_check` does not exist.
- [ ] Implement pure pieces in `browser_check.py` without starting Playwright.
- [ ] Re-run `python -m unittest tests.test_browser_check -v` and confirm pass.

## Task 2: Tests for server/browser settings

- [ ] Create `tests/test_server_browser_config.py` with tests that `public_settings_payload()` exposes browser fields and `apply_runtime_settings()` normalizes them.
- [ ] Run `python -m unittest tests.test_server_browser_config -v` and confirm it fails on missing fields.
- [ ] Implement config globals, payload fields, and runtime save/load fields in `server.py`.
- [ ] Re-run tests and confirm pass.

## Task 3: Playwright engine implementation

- [ ] Add Playwright import detection to `browser_check.py`.
- [ ] Implement `BrowserCheckEngine.check_proxy()` using `async_playwright`, Chromium, context-level proxy, network listeners, `page.goto()`, content extraction, and cleanup.
- [ ] Implement `run_browser_check_sync()` helper for `/api/deep-check`.
- [ ] Run `python -m py_compile browser_check.py`.

## Task 4: Server orchestration

- [ ] Modify `run_check()` so result publishing optionally runs browser check for HTTP candidates before appending results.
- [ ] Modify auto-run path to use the same two-stage helper.
- [ ] Rewrite `/api/deep-check` to call Playwright helper.
- [ ] Update `/api/capabilities` to return `playwright`, `browser_check`, and `deep_check`.
- [ ] Run `python -m py_compile server.py proxy_check.py browser_check.py`.

## Task 5: Frontend/settings/docs/deployment

- [ ] Add browser settings defaults, settings form controls, save payload fields, result tags, and details in `app.js`.
- [ ] Add config defaults to `config.json` and `.env.example`.
- [ ] Add `playwright>=1.0.0` to `requirements.txt`.
- [ ] Update `Dockerfile` to install Playwright Chromium and remove nodriver patch usage.
- [ ] Update `start.sh` and `start.ps1` to run `python -m playwright install chromium` after dependency install.
- [ ] Update `README.md` with Playwright browser detection explanation.

## Task 6: Verification

- [ ] Run unit tests.
- [ ] Install dependencies in `.venv` and install Chromium if needed.
- [ ] Start service locally.
- [ ] Use authenticated API calls to set `browser_check_enabled=true`, `browser_check_target_url=https://dashboard.prem.io/auth/login`, `browser_check_concurrent=10`, and manual `max_concurrent=10`.
- [ ] Start a local CONNECT-capable proxy for deterministic end-to-end testing.
- [ ] Submit the local proxy through `/api/start` and poll `/api/status`.
- [ ] Verify a result contains `browser_checked=true` and browser fields.
- [ ] Stop service and local proxy.
