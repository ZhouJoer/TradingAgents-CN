#!/usr/bin/env python3
"""
TradingAgents-CN 行业/概念分析 API 客户端示例。

面向飞书Bot、AI Agent、自动化服务的集成脚本。

支持两种模式：
1. 同步模式（推荐飞书）：run 命令，一次调用返回结果
2. 异步模式：submit → wait → result

Examples:
    # 同步一键分析（推荐飞书Bot使用）
    python examples/industry_analysis_api_client.py run \\
      --base-url http://127.0.0.1:8000 \\
      --username admin \\
      --password 'your-password' \\
      --concept "AI相关"

    # 异步提交
    python examples/industry_analysis_api_client.py submit \\
      --base-url http://127.0.0.1:8000 \\
      --access-token '<token>' \\
      --concept "高股息" \\
      --top-n 5

    # 查看历史
    python examples/industry_analysis_api_client.py history \\
      --base-url http://127.0.0.1:8000 \\
      --access-token '<token>'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

BASE_PREFIX = "/api/industry-analysis"
TODAY = date.today().isoformat()


def _output_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _get_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ─── Login ───────────────────────────────────────────────────────────────────

def cmd_login(args: argparse.Namespace) -> None:
    """登录并输出 access_token"""
    resp = requests.post(
        f"{args.base_url}/api/auth/login",
        data={"username": args.username, "password": args.password},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token") or payload.get("data", {}).get("access_token")
    _output_json({"mode": "login", "access_token": token})


# ─── Run (Sync) ──────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    """同步模式：提交并等待结果（推荐飞书Bot使用）"""
    token = _resolve_token(args)
    headers = _get_headers(token)

    body = {
        "concept": args.concept,
        "detail_level": args.detail_level,
        "top_n": args.top_n,
        "market": args.market,
    }

    print(f"⏳ 正在分析「{args.concept}」(同步模式，可能需要2-4分钟)...", file=sys.stderr)

    resp = requests.post(
        f"{args.base_url}{BASE_PREFIX}/run",
        headers=headers,
        json=body,
        timeout=args.timeout,
    )
    resp.raise_for_status()
    result = resp.json()

    if args.output_file:
        Path(args.output_file).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"✅ 结果已保存到 {args.output_file}", file=sys.stderr)

    # 输出精简摘要到 stdout
    data = result.get("data", {})
    inner_result = data.get("result", {})
    recommendations = inner_result.get("recommendations", [])

    summary = {
        "mode": "run",
        "success": result.get("success"),
        "concept": args.concept,
        "status": data.get("status"),
        "task_id": data.get("task_id"),
        "analysis_time": inner_result.get("analysis_time"),
        "candidate_count": inner_result.get("candidate_count"),
        "mapped_boards": inner_result.get("mapped_boards"),
        "top_stocks": [
            {
                "rank": r.get("rank"),
                "code": r.get("code"),
                "name": r.get("name"),
                "score": r.get("score"),
                "summary": r.get("summary"),
            }
            for r in recommendations[:args.top_n]
        ],
        "conclusion": inner_result.get("conclusion", "")[:500],
        "risk_warning": inner_result.get("risk_warning", "")[:300],
    }

    if result.get("success") is False:
        summary["error"] = data.get("error") or result.get("message")

    _output_json(summary)


# ─── Submit (Async) ──────────────────────────────────────────────────────────

def cmd_submit(args: argparse.Namespace) -> None:
    """异步提交行业分析任务"""
    token = _resolve_token(args)
    headers = _get_headers(token)

    body = {
        "concept": args.concept,
        "detail_level": args.detail_level,
        "top_n": args.top_n,
        "market": args.market,
    }

    resp = requests.post(
        f"{args.base_url}{BASE_PREFIX}/submit",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    _output_json({"mode": "submit", "task_id": result["data"]["task_id"], "concept": args.concept})


# ─── Status ──────────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    """查询任务状态"""
    token = _resolve_token(args)
    headers = _get_headers(token)

    resp = requests.get(
        f"{args.base_url}{BASE_PREFIX}/result/{args.task_id}",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    _output_json({
        "mode": "status",
        "task_id": args.task_id,
        "status": data.get("status"),
        "progress": data.get("progress"),
        "progress_message": data.get("progress_message"),
        "error": data.get("error"),
    })


# ─── Wait ────────────────────────────────────────────────────────────────────

def cmd_wait(args: argparse.Namespace) -> None:
    """轮询等待任务完成"""
    token = _resolve_token(args)
    headers = _get_headers(token)

    print(f"⏳ 等待任务 {args.task_id} 完成...", file=sys.stderr)
    poll_interval = args.poll_interval
    max_wait = args.timeout
    elapsed = 0

    while elapsed < max_wait:
        resp = requests.get(
            f"{args.base_url}{BASE_PREFIX}/result/{args.task_id}",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        status = data.get("status")

        if status in ("completed", "failed"):
            _output_json({
                "mode": "wait",
                "task_id": args.task_id,
                "status": status,
                "elapsed_seconds": elapsed,
            })
            return

        progress = data.get("progress", 0)
        msg = data.get("progress_message", "")
        print(f"  [{progress}%] {msg}", file=sys.stderr)
        time.sleep(poll_interval)
        elapsed += poll_interval

    _output_json({"mode": "wait", "task_id": args.task_id, "status": "timeout", "elapsed_seconds": elapsed})
    sys.exit(1)


# ─── Result ──────────────────────────────────────────────────────────────────

def cmd_result(args: argparse.Namespace) -> None:
    """获取完整任务结果"""
    token = _resolve_token(args)
    headers = _get_headers(token)

    resp = requests.get(
        f"{args.base_url}{BASE_PREFIX}/result/{args.task_id}",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if args.output_file:
        Path(args.output_file).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"✅ 完整结果已保存到 {args.output_file}", file=sys.stderr)

    _output_json(result)


# ─── Download ────────────────────────────────────────────────────────────────

def cmd_download(args: argparse.Namespace) -> None:
    """下载报告文件"""
    token = _resolve_token(args)
    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(
        f"{args.base_url}{BASE_PREFIX}/{args.task_id}/download",
        headers=headers,
        params={"format": args.format},
        timeout=60,
    )
    resp.raise_for_status()

    ext = {"markdown": ".md", "json": ".json", "pdf": ".pdf"}.get(args.format, ".txt")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"industry-analysis-{args.task_id[:8]}{ext}"

    filepath.write_bytes(resp.content)
    print(f"✅ 报告已下载: {filepath}", file=sys.stderr)
    _output_json({"mode": "download", "path": str(filepath), "size_bytes": len(resp.content)})


# ─── History ─────────────────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> None:
    """查看分析历史"""
    token = _resolve_token(args)
    headers = _get_headers(token)

    resp = requests.get(
        f"{args.base_url}{BASE_PREFIX}/history",
        headers=headers,
        params={"limit": args.limit},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    tasks = result.get("data", [])

    summary = []
    for task in tasks:
        summary.append({
            "task_id": task.get("task_id"),
            "concept": task.get("concept"),
            "status": task.get("status"),
            "created_at": task.get("created_at"),
        })
    _output_json({"mode": "history", "count": len(summary), "tasks": summary})


# ─── Delete ──────────────────────────────────────────────────────────────────

def cmd_delete(args: argparse.Namespace) -> None:
    """删除分析记录"""
    token = _resolve_token(args)
    headers = _get_headers(token)

    resp = requests.delete(
        f"{args.base_url}{BASE_PREFIX}/{args.task_id}",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    _output_json({"mode": "delete", "task_id": args.task_id, "success": True})


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_token(args: argparse.Namespace) -> str:
    """Resolve access token: explicit --access-token or login with credentials."""
    if hasattr(args, "access_token") and args.access_token:
        return args.access_token

    if hasattr(args, "username") and args.username and hasattr(args, "password") and args.password:
        resp = requests.post(
            f"{args.base_url}/api/auth/login",
            data={"username": args.username, "password": args.password},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("access_token") or payload.get("data", {}).get("access_token", "")

    print("❌ 需要提供 --access-token 或 --username + --password", file=sys.stderr)
    sys.exit(1)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TradingAgents-CN 行业/概念分析 API 客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common args
    def add_common_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--base-url", default="http://127.0.0.1:8000", help="后端API地址")
        sub.add_argument("--access-token", help="Bearer token (如不提供则自动登录)")
        sub.add_argument("--username", help="登录用户名")
        sub.add_argument("--password", help="登录密码")

    def add_concept_args(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--concept", required=True, help="行业/概念关键词 (如: AI相关, 高股息, 新能源)")
        sub.add_argument("--detail-level", default="detailed", choices=["brief", "detailed"], help="分析粒度")
        sub.add_argument("--top-n", type=int, default=5, help="推荐股票数量")
        sub.add_argument("--market", default="A", help="市场")

    # login
    p_login = subparsers.add_parser("login", help="登录获取token")
    p_login.add_argument("--base-url", default="http://127.0.0.1:8000")
    p_login.add_argument("--username", required=True)
    p_login.add_argument("--password", required=True)
    p_login.set_defaults(func=cmd_login)

    # run (sync)
    p_run = subparsers.add_parser("run", help="同步分析（提交并等待结果，推荐飞书Bot使用）")
    add_common_args(p_run)
    add_concept_args(p_run)
    p_run.add_argument("--timeout", type=int, default=360, help="超时秒数 (默认360)")
    p_run.add_argument("--output-file", help="保存完整结果到文件")
    p_run.set_defaults(func=cmd_run)

    # submit
    p_submit = subparsers.add_parser("submit", help="异步提交分析任务")
    add_common_args(p_submit)
    add_concept_args(p_submit)
    p_submit.set_defaults(func=cmd_submit)

    # status
    p_status = subparsers.add_parser("status", help="查询任务状态")
    add_common_args(p_status)
    p_status.add_argument("--task-id", required=True, help="任务ID")
    p_status.set_defaults(func=cmd_status)

    # wait
    p_wait = subparsers.add_parser("wait", help="轮询等待任务完成")
    add_common_args(p_wait)
    p_wait.add_argument("--task-id", required=True, help="任务ID")
    p_wait.add_argument("--poll-interval", type=int, default=5, help="轮询间隔秒数")
    p_wait.add_argument("--timeout", type=int, default=360, help="最大等待秒数")
    p_wait.set_defaults(func=cmd_wait)

    # result
    p_result = subparsers.add_parser("result", help="获取完整任务结果")
    add_common_args(p_result)
    p_result.add_argument("--task-id", required=True, help="任务ID")
    p_result.add_argument("--output-file", help="保存结果到文件")
    p_result.set_defaults(func=cmd_result)

    # download
    p_download = subparsers.add_parser("download", help="下载报告文件")
    add_common_args(p_download)
    p_download.add_argument("--task-id", required=True, help="任务ID")
    p_download.add_argument("--format", default="markdown", choices=["markdown", "json", "pdf"])
    p_download.add_argument("--output-dir", default="./api_output", help="输出目录")
    p_download.set_defaults(func=cmd_download)

    # history
    p_history = subparsers.add_parser("history", help="查看分析历史")
    add_common_args(p_history)
    p_history.add_argument("--limit", type=int, default=20, help="返回数量")
    p_history.set_defaults(func=cmd_history)

    # delete
    p_delete = subparsers.add_parser("delete", help="删除分析记录")
    add_common_args(p_delete)
    p_delete.add_argument("--task-id", required=True, help="任务ID")
    p_delete.set_defaults(func=cmd_delete)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except requests.HTTPError as exc:
        error_detail = ""
        if exc.response is not None:
            try:
                error_detail = exc.response.json().get("detail", exc.response.text[:200])
            except Exception:
                error_detail = exc.response.text[:200]
        _output_json({"error": str(exc), "detail": error_detail})
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
