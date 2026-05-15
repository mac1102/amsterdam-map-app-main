from __future__ import annotations

from backend.wior_fetch import init_wior_db, sync_wior_data


def main() -> None:
    init_wior_db()
    result = sync_wior_data()
    print("WIOR refresh result:", result)


if __name__ == "__main__":
    main()