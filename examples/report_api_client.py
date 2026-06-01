#!/usr/bin/env python3
"""
TradingAgents-CN report API client.

This example mirrors the parameter surface used by:
    frontend/src/views/Analysis/SingleAnalysis.vue

Supported workflows:
1. Login only
2. Submit single-stock analysis
3. Poll task status
4. Stream task progress through SSE
5. Fetch structured task result
6. Download markdown/json/docx/pdf report
7. Run the full submit -> wait -> result -> download workflow

Examples:
    python examples/report_api_client.py run-single \
      --base-url http://127.0.0.1:8000 \
      --username admin \
      --password 'your-password' \
      --symbol 600036 \
      --market-type A股 \
      --research-depth-level 3 \
      --download-format markdown

    python examples/report_api_client.py task-sse \
      --base-url http://127.0.0.1:8000 \
      --access-token '<token>' \
      --task-id '<task_id>'
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import requests


FRONTEND_DEFAULT_ANALYSTS = ["market", "fundamentals"]
FINAL_STATUSES = {"completed", "failed", "cancelled"}
FALLBACK_QUICK_MODEL = "qwen-turbo"
FALLBACK_DEEP_MODEL = "qwen-max"
RESEARCH_DEPTH_LABELS = {
    1: "快速",
    2: "基础",
    3: "标准",
    4: "深度",
    5: "全面",
}
ANALYST_NAME_TO_ID_MAP = {
    "市场分析师": "market",
    "基本面分析师": "fundamentals",
    "新闻分析师": "news",
    "社媒分析师": "social",
}
VALID_ANALYST_IDS = {"market", "fundamentals", "news", "social"}
TODAY = date.today().isoformat()


def remove_none_values(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None and value != ""}


def parse_content_disposition(header_value: str | None) -> str | None:
    if not header_value:
        return None
    match = re.search(r'filename="?([^";]+)"?', header_value)
    if match:
        return match.group(1)
    return None


def emit_json(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


def emit_warning(message: str) -> None:
    print(json.dumps({"warning": message}, ensure_ascii=False), file=sys.stderr)


def normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        raise ValueError("symbol 不能为空")
    return normalized


def normalize_analysis_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise ValueError(f"analysis_date 格式无效: {value}，请使用 YYYY-MM-DD") from exc


def normalize_research_depth(raw_value: str, raw_level: int | None) -> str:
    if raw_level is not None:
        return RESEARCH_DEPTH_LABELS[raw_level]

    value = str(raw_value or "").strip()
    if not value:
        return RESEARCH_DEPTH_LABELS[3]

    if value.isdigit():
        level = int(value)
        if level not in RESEARCH_DEPTH_LABELS:
            raise ValueError(f"research_depth 数字必须在 1-5 之间，当前是 {value}")
        return RESEARCH_DEPTH_LABELS[level]

    for label in RESEARCH_DEPTH_LABELS.values():
        if value == label:
            return label

    raise ValueError(f"research_depth 无效: {value}，可选值为 1-5 或 快速/基础/标准/深度/全面")


def normalize_analysts(raw_values: list[str] | None) -> list[str]:
    if not raw_values:
        return list(FRONTEND_DEFAULT_ANALYSTS)

    normalized: list[str] = []
    for raw_value in raw_values:
        for item in str(raw_value).split(","):
            candidate = item.strip()
            if not candidate:
                continue

            analyst_id = ANALYST_NAME_TO_ID_MAP.get(candidate, candidate.lower())
            if analyst_id not in VALID_ANALYST_IDS:
                valid_values = sorted(list(VALID_ANALYST_IDS) + list(ANALYST_NAME_TO_ID_MAP.keys()))
                raise ValueError(f"不支持的分析师: {candidate}，可选值: {', '.join(valid_values)}")

            if analyst_id not in normalized:
                normalized.append(analyst_id)

    if not normalized:
        raise ValueError("selected_analysts 不能为空")
    return normalized


def build_single_analysis_payload(args: argparse.Namespace) -> dict[str, Any]:
    symbol = normalize_symbol(args.symbol)
    payload = {
        "symbol": symbol,
        "stock_code": symbol,
        "parameters": remove_none_values(
            {
                "market_type": args.market_type,
                "analysis_date": normalize_analysis_date(args.analysis_date),
                "research_depth": normalize_research_depth(args.research_depth, getattr(args, "research_depth_level", None)),
                "selected_analysts": normalize_analysts(args.analysts),
                "custom_prompt": getattr(args, "custom_prompt", ""),
                "include_sentiment": bool(args.include_sentiment),
                "include_risk": bool(args.include_risk),
                "language": args.language,
                "quick_analysis_model": getattr(args, "quick_analysis_model", None),
                "deep_analysis_model": getattr(args, "deep_analysis_model", None),
            }
        ),
    }
    return payload


def write_json_file(output_dir: Path, file_name: str, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / file_name
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def parse_sse_events(response: requests.Response) -> Iterable[dict[str, Any]]:
    event_name = "message"
    data_lines: list[str] = []

    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue

        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                raw_data = "\n".join(data_lines)
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    data = raw_data
                yield {"event": event_name, "data": data}
            event_name = "message"
            data_lines = []
            continue

        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())

    if data_lines:
        raw_data = "\n".join(data_lines)
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            data = raw_data
        yield {"event": event_name, "data": data}


class TradingAgentsApiClient:
    def __init__(self, base_url: str, request_timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            headers["Content-Type"] = "application/json"

        response = self.session.request(
            method,
            self._url(path),
            headers=headers,
            json=payload,
            params=params,
            timeout=self.request_timeout,
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{method} {path} 返回了非 JSON 响应: {response.text[:500]}") from exc

        if response.status_code >= 400:
            detail = data.get("detail") or data.get("message") or response.text
            raise RuntimeError(f"{method} {path} 失败: {detail}")

        if data.get("success") is False:
            raise RuntimeError(f"{method} {path} 失败: {data.get('message', data)}")

        return data

    def login(self, username: str, password: str) -> dict[str, Any]:
        response = self._json_request(
            "POST",
            "/api/auth/login",
            payload={"username": username, "password": password},
        )
        return response["data"]

    def submit_single_analysis(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._json_request(
            "POST",
            "/api/analysis/single",
            token=token,
            payload=payload,
        )
        return response["data"]

    def get_task_status(self, token: str, task_id: str) -> dict[str, Any]:
        response = self._json_request("GET", f"/api/analysis/tasks/{task_id}/status", token=token)
        return response["data"]

    def get_task_result(self, token: str, task_id: str) -> dict[str, Any]:
        response = self._json_request("GET", f"/api/analysis/tasks/{task_id}/result", token=token)
        return response["data"]

    def get_system_settings(self, token: str) -> dict[str, Any]:
        response = self._json_request("GET", "/api/config/settings", token=token)
        return response["data"]

    def get_default_models(self, token: str) -> dict[str, str]:
        settings = self.get_system_settings(token)
        return {
            "quick_analysis_model": settings.get("quick_analysis_model") or FALLBACK_QUICK_MODEL,
            "deep_analysis_model": settings.get("deep_analysis_model") or FALLBACK_DEEP_MODEL,
        }

    def stream_task_sse(self, token: str, task_id: str) -> Iterable[dict[str, Any]]:
        response = self.session.get(
            self._url(f"/api/stream/tasks/{task_id}"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=(self.request_timeout, max(self.request_timeout, 30)),
            stream=True,
        )

        if response.status_code >= 400:
            try:
                data = response.json()
                detail = data.get("detail") or data.get("message") or data
            except ValueError:
                detail = response.text
            raise RuntimeError(f"GET /api/stream/tasks/{task_id} 失败: {detail}")

        yield from parse_sse_events(response)

    def wait_for_completion_by_poll(
        self,
        token: str,
        task_id: str,
        *,
        poll_interval: float,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = self.get_task_status(token, task_id)
            current_status = str(status.get("status", "")).lower()
            if current_status in FINAL_STATUSES:
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(f"任务 {task_id} 在 {timeout_seconds} 秒内未完成")
            time.sleep(poll_interval)

    def wait_for_completion_by_sse(
        self,
        token: str,
        task_id: str,
        *,
        timeout_seconds: int,
        print_events: bool = False,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds

        for event in self.stream_task_sse(token, task_id):
            if print_events:
                print(json.dumps(event, ensure_ascii=False))

            if time.monotonic() >= deadline:
                raise TimeoutError(f"任务 {task_id} 在 {timeout_seconds} 秒内未完成")

            if event["event"] == "error":
                data = event.get("data")
                if isinstance(data, dict):
                    raise RuntimeError(data.get("error", data))
                raise RuntimeError(str(data))

            if event["event"] == "progress" and isinstance(event.get("data"), dict):
                progress_payload = event["data"]
                current_status = str(progress_payload.get("status", "")).lower()
                if current_status in FINAL_STATUSES:
                    return self.get_task_status(token, task_id)

        final_status = self.get_task_status(token, task_id)
        if str(final_status.get("status", "")).lower() in FINAL_STATUSES:
            return final_status
        raise TimeoutError(f"SSE 流已结束，但任务 {task_id} 仍未进入最终状态")

    def wait_for_completion(
        self,
        token: str,
        task_id: str,
        *,
        wait_method: str,
        poll_interval: float,
        timeout_seconds: int,
        print_sse_events: bool = False,
    ) -> dict[str, Any]:
        if wait_method == "poll":
            return self.wait_for_completion_by_poll(
                token,
                task_id,
                poll_interval=poll_interval,
                timeout_seconds=timeout_seconds,
            )
        if wait_method == "sse":
            return self.wait_for_completion_by_sse(
                token,
                task_id,
                timeout_seconds=timeout_seconds,
                print_events=print_sse_events,
            )
        raise ValueError(f"不支持的 wait_method: {wait_method}")

    def download_report(
        self,
        token: str,
        report_id: str,
        report_format: str,
        output_dir: Path,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        response = self.session.get(
            self._url(f"/api/reports/{report_id}/download"),
            headers={"Authorization": f"Bearer {token}"},
            params={"format": report_format},
            timeout=self.request_timeout,
            stream=True,
        )

        if response.status_code >= 400:
            try:
                data = response.json()
                detail = data.get("detail") or data.get("message") or data
            except ValueError:
                detail = response.text
            raise RuntimeError(f"GET /api/reports/{report_id}/download 失败: {detail}")

        filename = parse_content_disposition(response.headers.get("Content-Disposition"))
        if not filename:
            filename = f"{report_id}.{report_format}"

        output_path = output_dir / filename
        with output_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        return output_path


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--request-timeout", type=int, default=30, help="Per-request timeout in seconds")


def add_auth_args(parser: argparse.ArgumentParser, *, require_login: bool = False) -> None:
    if not require_login:
        parser.add_argument("--access-token", default="", help="Existing bearer token; skips login")
    parser.add_argument("--username", required=require_login, help="Login username")
    parser.add_argument("--password", required=require_login, help="Login password")


def add_single_analysis_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbol", required=True, help="Stock symbol, e.g. 600036 / 0700.HK / AAPL")
    parser.add_argument("--market-type", default="A股", choices=["A股", "港股", "美股"], help="Market type")
    parser.add_argument("--analysis-date", default=TODAY, help="Analysis date, e.g. 2026-05-28")
    parser.add_argument("--research-depth", default="标准", help="Research depth label or numeric string")
    parser.add_argument("--research-depth-level", type=int, choices=sorted(RESEARCH_DEPTH_LABELS), help="Research depth level 1-5")
    parser.add_argument(
        "--analyst",
        action="append",
        dest="analysts",
        help="Repeatable analyst id or Chinese name; also accepts comma-separated values",
    )
    parser.add_argument("--custom-prompt", default="", help="Optional custom_prompt supported by the API")

    sentiment_group = parser.add_mutually_exclusive_group()
    sentiment_group.add_argument("--include-sentiment", dest="include_sentiment", action="store_true")
    sentiment_group.add_argument("--no-include-sentiment", dest="include_sentiment", action="store_false")
    parser.set_defaults(include_sentiment=True)

    risk_group = parser.add_mutually_exclusive_group()
    risk_group.add_argument("--include-risk", dest="include_risk", action="store_true")
    risk_group.add_argument("--no-include-risk", dest="include_risk", action="store_false")
    parser.set_defaults(include_risk=True)

    parser.add_argument("--language", default="zh-CN", choices=["zh-CN", "en-US"], help="Analysis language")
    parser.add_argument(
        "--use-server-default-models",
        action="store_true",
        help="Load quick/deep models from /api/config/settings first, matching frontend startup behavior",
    )
    parser.add_argument(
        "--quick-analysis-model",
        default=None,
        help=f"Quick analysis model; defaults to {FALLBACK_QUICK_MODEL} unless --use-server-default-models is set",
    )
    parser.add_argument(
        "--deep-analysis-model",
        default=None,
        help=f"Deep analysis model; defaults to {FALLBACK_DEEP_MODEL} unless --use-server-default-models is set",
    )


def add_task_id_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-id", required=True, help="Analysis task_id")


def add_report_id_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--report-id", required=True, help="analysis_id / task_id / report _id")


def add_wait_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wait-method", default="poll", choices=["poll", "sse", "none"], help="How to track progress")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Polling interval in seconds")
    parser.add_argument("--timeout-seconds", type=int, default=1800, help="Max wait time for analysis")
    parser.add_argument("--print-sse-events", action="store_true", help="Print SSE events while waiting via SSE")


def add_output_args(parser: argparse.ArgumentParser, *, default_download_format: str = "none") -> None:
    parser.add_argument(
        "--download-format",
        choices=["none", "markdown", "json", "docx", "pdf"],
        default=default_download_format,
        help="Optional report download format",
    )
    parser.add_argument("--output-dir", default="./api_output", help="Directory for downloaded artifacts")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TradingAgents-CN report API client")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Login and print access token")
    add_connection_args(login_parser)
    add_auth_args(login_parser, require_login=True)

    submit_parser = subparsers.add_parser("submit-single", help="Submit a single analysis task")
    add_connection_args(submit_parser)
    add_auth_args(submit_parser)
    add_single_analysis_args(submit_parser)

    status_parser = subparsers.add_parser("task-status", help="Fetch task status")
    add_connection_args(status_parser)
    add_auth_args(status_parser)
    add_task_id_arg(status_parser)

    wait_parser = subparsers.add_parser("wait-task", help="Wait for task completion")
    add_connection_args(wait_parser)
    add_auth_args(wait_parser)
    add_task_id_arg(wait_parser)
    add_wait_args(wait_parser)

    sse_parser = subparsers.add_parser("task-sse", help="Stream task progress via SSE")
    add_connection_args(sse_parser)
    add_auth_args(sse_parser)
    add_task_id_arg(sse_parser)
    sse_parser.add_argument("--timeout-seconds", type=int, default=1800, help="Max streaming duration")

    result_parser = subparsers.add_parser("task-result", help="Fetch structured task result")
    add_connection_args(result_parser)
    add_auth_args(result_parser)
    add_task_id_arg(result_parser)

    download_parser = subparsers.add_parser("download-report", help="Download report file")
    add_connection_args(download_parser)
    add_auth_args(download_parser)
    add_report_id_arg(download_parser)
    add_output_args(download_parser, default_download_format="markdown")

    run_parser = subparsers.add_parser("run-single", help="Submit, wait, fetch result, and optionally download report")
    add_connection_args(run_parser)
    add_auth_args(run_parser)
    add_single_analysis_args(run_parser)
    add_wait_args(run_parser)
    add_output_args(run_parser, default_download_format="markdown")

    return parser


def require_token(args: argparse.Namespace, client: TradingAgentsApiClient) -> str:
    token = str(getattr(args, "access_token", "") or "").strip()
    if token:
        return token

    username = str(getattr(args, "username", "") or "").strip()
    password = str(getattr(args, "password", "") or "").strip()
    if username and password:
        return client.login(username, password)["access_token"]

    raise RuntimeError("请提供 --access-token，或同时提供 --username 和 --password")


def resolve_model_settings(client: TradingAgentsApiClient, token: str, args: argparse.Namespace) -> None:
    quick_model = getattr(args, "quick_analysis_model", None)
    deep_model = getattr(args, "deep_analysis_model", None)

    if args.use_server_default_models and (not quick_model or not deep_model):
        try:
            default_models = client.get_default_models(token)
            quick_model = quick_model or default_models["quick_analysis_model"]
            deep_model = deep_model or default_models["deep_analysis_model"]
        except RuntimeError as exc:
            emit_warning(f"加载服务端默认模型失败，已回退到本地默认值: {exc}")

    args.quick_analysis_model = quick_model or FALLBACK_QUICK_MODEL
    args.deep_analysis_model = deep_model or FALLBACK_DEEP_MODEL


def command_login(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    login_data = client.login(args.username, args.password)
    emit_json({"mode": "login", "data": login_data})
    return 0


def command_submit_single(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    token = require_token(args, client)
    resolve_model_settings(client, token, args)
    payload = build_single_analysis_payload(args)
    task_meta = client.submit_single_analysis(token, payload)
    emit_json({"mode": "submit-single", "request": payload, "task": task_meta})
    return 0


def command_task_status(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    token = require_token(args, client)
    status = client.get_task_status(token, args.task_id)
    emit_json({"mode": "task-status", "task_id": args.task_id, "status": status})
    return 0


def command_wait_task(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    token = require_token(args, client)
    if args.wait_method == "none":
        status = client.get_task_status(token, args.task_id)
    else:
        status = client.wait_for_completion(
            token,
            args.task_id,
            wait_method=args.wait_method,
            poll_interval=args.poll_interval,
            timeout_seconds=args.timeout_seconds,
            print_sse_events=args.print_sse_events,
        )
    emit_json({"mode": "wait-task", "task_id": args.task_id, "status": status})
    return 0 if str(status.get("status", "")).lower() == "completed" else 2


def command_task_sse(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    token = require_token(args, client)
    deadline = time.monotonic() + args.timeout_seconds

    for event in client.stream_task_sse(token, args.task_id):
        print(json.dumps(event, ensure_ascii=False))

        if event["event"] == "error":
            return 1

        if event["event"] == "progress" and isinstance(event.get("data"), dict):
            current_status = str(event["data"].get("status", "")).lower()
            if current_status in FINAL_STATUSES:
                return 0 if current_status == "completed" else 2

        if time.monotonic() >= deadline:
            emit_json({"error": f"任务 {args.task_id} 在 {args.timeout_seconds} 秒内未完成"}, stream=sys.stderr)
            return 1

    final_status = client.get_task_status(token, args.task_id)
    current_status = str(final_status.get("status", "")).lower()
    if current_status in FINAL_STATUSES:
        return 0 if current_status == "completed" else 2

    emit_json(
        {"error": f"SSE 流已结束，但任务 {args.task_id} 仍未进入最终状态", "status": final_status},
        stream=sys.stderr,
    )
    return 1


def command_task_result(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    token = require_token(args, client)
    result = client.get_task_result(token, args.task_id)
    emit_json({"mode": "task-result", "task_id": args.task_id, "result": result})
    return 0


def command_download_report(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    token = require_token(args, client)
    output_path = client.download_report(token, args.report_id, args.download_format, Path(args.output_dir))
    emit_json(
        {
            "mode": "download-report",
            "report_id": args.report_id,
            "format": args.download_format,
            "output_path": str(output_path),
        }
    )
    return 0


def command_run_single(client: TradingAgentsApiClient, args: argparse.Namespace) -> int:
    token = require_token(args, client)
    resolve_model_settings(client, token, args)
    payload = build_single_analysis_payload(args)
    task_meta = client.submit_single_analysis(token, payload)
    task_id = task_meta["task_id"]

    status = None
    result = None
    result_json_path = None
    report_path = None

    if args.wait_method == "none":
        emit_json(
            {
                "mode": "run-single",
                "request": payload,
                "task": task_meta,
                "status": "submitted",
            }
        )
        return 0

    status = client.wait_for_completion(
        token,
        task_id,
        wait_method=args.wait_method,
        poll_interval=args.poll_interval,
        timeout_seconds=args.timeout_seconds,
        print_sse_events=args.print_sse_events,
    )

    if str(status.get("status", "")).lower() == "completed":
        result = client.get_task_result(token, task_id)
        output_dir = Path(args.output_dir)
        result_json_path = write_json_file(output_dir, f"{task_id}.result.json", result)

        if args.download_format != "none":
            report_id = result.get("analysis_id") or task_id
            report_path = client.download_report(token, report_id, args.download_format, output_dir)

    emit_json(
        {
            "mode": "run-single",
            "request": payload,
            "task": task_meta,
            "final_status": status,
            "analysis_id": result.get("analysis_id") if result else None,
            "result_json_path": str(result_json_path) if result_json_path else None,
            "report_path": str(report_path) if report_path else None,
            "result": result,
        }
    )
    return 0 if str(status.get("status", "")).lower() == "completed" else 2


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    client = TradingAgentsApiClient(args.base_url, request_timeout=args.request_timeout)

    try:
        if args.command == "login":
            return command_login(client, args)
        if args.command == "submit-single":
            return command_submit_single(client, args)
        if args.command == "task-status":
            return command_task_status(client, args)
        if args.command == "wait-task":
            return command_wait_task(client, args)
        if args.command == "task-sse":
            return command_task_sse(client, args)
        if args.command == "task-result":
            return command_task_result(client, args)
        if args.command == "download-report":
            return command_download_report(client, args)
        if args.command == "run-single":
            return command_run_single(client, args)
        raise RuntimeError(f"未知命令: {args.command}")
    except Exception as exc:
        emit_json({"error": str(exc)}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
