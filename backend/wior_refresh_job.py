from __future__ import annotations

from backend.wior_fetch import init_wior_db, sync_wior_data


def run_wior_refresh_job() -> dict:
    init_wior_db()
    return sync_wior_data()


def main() -> int:
    result = run_wior_refresh_job()
    print("WIOR refresh result:", result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
