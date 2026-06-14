from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Tuple

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.backtest.engine import DEFAULT_ETF_UNIVERSE  # noqa: E402
import app.services.backtest.etf_data_service as etf_data_module  # noqa: E402
from app.services.backtest.etf_data_service import ETFDataService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Slowly cache adjusted ETF daily history into MongoDB for backtests.",
    )
    parser.add_argument("--start-date", default="2020-01-01", help="Inclusive start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"), help="Inclusive end date, YYYY-MM-DD.")
    parser.add_argument("--adjust", default="qfq", choices=["qfq", "hfq"], help="Adjusted price mode to cache.")
    parser.add_argument(
        "--codes",
        nargs="*",
        default=None,
        help="ETF codes to cache. Omit to use the default backtest universe.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=2.0, help="Delay between ETF fetches.")
    parser.add_argument("--rounds", type=int, default=1, help="Retry failed ETF codes for this many rounds.")
    parser.add_argument("--round-sleep-seconds", type=float, default=60.0, help="Delay between retry rounds.")
    parser.add_argument("--chunk-years", type=int, default=0, help="Fetch each ETF in year-sized chunks; use 0 to disable.")
    parser.add_argument("--chunk-sleep-seconds", type=float, default=1.0, help="Delay between chunks for the same ETF.")
    parser.add_argument("--fetch-attempts", type=int, default=5, help="Low-level retry attempts for each chunk.")
    parser.add_argument("--fetch-delay-seconds", type=float, default=2.0, help="Base delay for low-level retries.")
    parser.add_argument("--cache-none", action="store_true", help="Also cache unadjusted history for factor verification.")
    parser.add_argument("--cache-factors", action="store_true", help="Fetch and cache adjustment factors from an external source.")
    parser.add_argument("--factor-source", default="tushare", choices=["tushare"], help="External adjustment factor source.")
    parser.add_argument("--verify-factors", action="store_true", help="Verify adjusted ~= unadjusted * cached factor.")
    parser.add_argument("--verify-tolerance", type=float, default=0.01, help="Absolute price tolerance for factor verification.")
    parser.add_argument("--max-codes", type=int, default=None, help="Limit number of ETF codes for this run.")
    parser.add_argument("--force", action="store_true", help="Fetch even when cached data already covers the range.")
    parser.add_argument("--skip-adjusted-fetch", action="store_true", help="Use cached adjusted data without fetching it.")
    parser.add_argument("--refresh-basic", action="store_true", help="Refresh ETF basic info before history caching.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without fetching.")
    return parser.parse_args()


def normalize_codes(codes: Iterable[str] | None, max_codes: int | None) -> List[str]:
    raw_codes = list(codes) if codes else [item["code"] for item in DEFAULT_ETF_UNIVERSE]
    normalized: List[str] = []
    seen = set()
    for code in raw_codes:
        item = str(code).strip().zfill(6)
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    if max_codes is not None:
        normalized = normalized[: max(0, max_codes)]
    return normalized


def date_range(records: List[dict]) -> str:
    dates = [row.get("trade_date") for row in records if row.get("trade_date")]
    if not dates:
        return "-"
    return f"{min(dates)}..{max(dates)}"


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, month=2, day=28)


def chunk_ranges(start_date: str, end_date: str, chunk_years: int) -> List[Tuple[str, str]]:
    if chunk_years <= 0:
        return [(start_date, end_date)]
    start = parse_date(start_date)
    end = parse_date(end_date)
    ranges: List[Tuple[str, str]] = []
    current = start
    while current <= end:
        next_start = add_years(current, chunk_years)
        current_end = min(end, next_start - timedelta(days=1))
        ranges.append((format_date(current), format_date(current_end)))
        current = current_end + timedelta(days=1)
    return ranges


async def fetch_code_history(
    service: ETFDataService,
    code: str,
    adjust: str,
    args: argparse.Namespace,
    prefix: str,
) -> int:
    saved_total = 0
    ranges = chunk_ranges(args.start_date, args.end_date, args.chunk_years)
    for chunk_index, (chunk_start, chunk_end) in enumerate(ranges, start=1):
        saved = await service.fetch_and_cache_history(code, chunk_start, chunk_end, adjust)
        saved_total += saved
        print(f"{prefix} {adjust} chunk {chunk_index}/{len(ranges)} {chunk_start}..{chunk_end} saved={saved}")
        if chunk_index < len(ranges) and args.chunk_sleep_seconds > 0:
            await asyncio.sleep(args.chunk_sleep_seconds)
    return saved_total


async def cache_none_if_needed(service: ETFDataService, code: str, args: argparse.Namespace, prefix: str) -> None:
    records = await service._query_history(code, args.start_date, args.end_date, "none")
    if service._covers_range(records, args.start_date, args.end_date) and not args.force:
        print(f"{prefix} none skip covered rows={len(records)} dates={date_range(records)}")
        return
    if args.dry_run:
        print(f"{prefix} none would fetch rows={len(records)} dates={date_range(records)}")
        return
    saved = await fetch_code_history(service, code, "none", args, prefix)
    records_after = await service._query_history(code, args.start_date, args.end_date, "none")
    print(f"{prefix} none fetched saved={saved} rows={len(records_after)} dates={date_range(records_after)}")


async def cache_and_verify_factors(service: ETFDataService, code: str, args: argparse.Namespace, prefix: str) -> None:
    if args.cache_factors:
        if args.dry_run:
            print(f"{prefix} would fetch {args.adjust} factors from {args.factor_source}")
        else:
            summary = await service.fetch_and_cache_adjustment_factors(
                code,
                args.start_date,
                args.end_date,
                args.adjust,
                args.factor_source,
            )
            print(
                f"{prefix} factors fetched source={summary['source']} "
                f"count={summary['factor_count']} saved={summary['saved']} "
                f"dates={summary.get('date_range', '-')}"
            )
    if args.verify_factors:
        report = await service.verify_cached_adjustment_factors(
            code,
            args.start_date,
            args.end_date,
            args.adjust,
            tolerance=args.verify_tolerance,
        )
        print(
            f"{prefix} verify common={report['common_count']} "
            f"raw={report['raw_count']} adjusted={report['adjusted_count']} factors={report['factor_count']} "
            f"max_abs_error={report['max_abs_error']:.8f} mismatches={report['mismatch_count']} "
            f"field_errors={report['field_errors']}"
        )
        if report.get("worst"):
            print(f"{prefix} verify worst={report['worst']}")


async def main() -> int:
    args = parse_args()
    codes = normalize_codes(args.codes, args.max_codes)
    if not codes:
        print("No ETF codes to cache.")
        return 1
    etf_data_module.FETCH_RETRY_ATTEMPTS = max(1, args.fetch_attempts)
    etf_data_module.FETCH_RETRY_DELAY_SECONDS = max(0.0, args.fetch_delay_seconds)

    client = AsyncIOMotorClient(
        settings.MONGO_URI,
        serverSelectionTimeoutMS=settings.MONGO_SERVER_SELECTION_TIMEOUT_MS,
        connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
        socketTimeoutMS=settings.MONGO_SOCKET_TIMEOUT_MS,
    )
    service = ETFDataService(client[settings.MONGO_DB])

    try:
        await client.admin.command("ping")
        await service.ensure_indexes()
        if args.refresh_basic and not args.dry_run:
            saved_basic = await service.refresh_basic_info()
            print(f"Refreshed ETF basic info: {saved_basic} rows changed.")

        print(
            f"MongoDB={settings.MONGO_DB} adjust={args.adjust} "
            f"range={args.start_date}..{args.end_date} codes={len(codes)} "
            f"chunk_years={args.chunk_years} rounds={args.rounds}"
        )

        fetched = 0
        skipped = 0
        remaining = codes
        failed_codes: List[str] = []
        rounds = max(1, args.rounds)
        for round_index in range(1, rounds + 1):
            failed_codes = []
            if rounds > 1:
                print(f"Round {round_index}/{rounds}: codes={len(remaining)}")
            for index, code in enumerate(remaining, start=1):
                records = await service._query_history(code, args.start_date, args.end_date, args.adjust)
                covered = service._covers_range(records, args.start_date, args.end_date)
                prefix = f"[round {round_index}/{rounds} {index}/{len(remaining)}] {code}"

                if covered and not args.force:
                    skipped += 1
                    print(f"{prefix} skip covered rows={len(records)} dates={date_range(records)}")
                elif args.skip_adjusted_fetch:
                    print(f"{prefix} adjusted fetch skipped rows={len(records)} dates={date_range(records)}")
                elif args.dry_run:
                    print(f"{prefix} would fetch rows={len(records)} dates={date_range(records)}")
                else:
                    try:
                        saved = await fetch_code_history(service, code, args.adjust, args, prefix)
                        records_after = await service._query_history(code, args.start_date, args.end_date, args.adjust)
                        fetched += 1
                        print(f"{prefix} fetched saved={saved} rows={len(records_after)} dates={date_range(records_after)}")
                    except Exception as exc:
                        failed_codes.append(code)
                        print(f"{prefix} failed: {exc}")

                if code not in failed_codes and (args.cache_none or args.cache_factors or args.verify_factors):
                    try:
                        if args.cache_none or args.verify_factors:
                            await cache_none_if_needed(service, code, args, prefix)
                        await cache_and_verify_factors(service, code, args, prefix)
                    except Exception as exc:
                        failed_codes.append(code)
                        print(f"{prefix} factor failed: {exc}")

                if index < len(remaining) and args.sleep_seconds > 0:
                    await asyncio.sleep(args.sleep_seconds)

            if not failed_codes or args.dry_run:
                break
            if round_index < rounds:
                print(
                    f"Waiting {args.round_sleep_seconds}s before retrying failed codes: "
                    f"{', '.join(failed_codes)}"
                )
                if args.round_sleep_seconds > 0:
                    await asyncio.sleep(args.round_sleep_seconds)
                remaining = failed_codes

        if failed_codes:
            print(f"Failed codes: {', '.join(failed_codes)}")
        print(f"Done. fetched={fetched} skipped={skipped} failed={len(failed_codes)}")
        return 0 if not failed_codes else 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
