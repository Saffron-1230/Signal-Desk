from __future__ import annotations

import argparse
import json
from pathlib import Path

from app import dashboard_payload, refresh_all


SITE_DATA = Path(__file__).resolve().parent / "site" / "data" / "articles.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static Signal Desk data file.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Collect new articles before exporting the dashboard data.",
    )
    args = parser.parse_args()

    if args.refresh:
        result = refresh_all("github-actions")
        print(f"Collection finished with status: {result['status']}")

    payload = dashboard_payload(limit=100)
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    temporary = SITE_DATA.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(SITE_DATA)

    article_count = sum(len(source["articles"]) for source in payload["sources"].values())
    print(f"Exported {article_count} articles to {SITE_DATA}")


if __name__ == "__main__":
    main()
