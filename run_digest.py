"""Run the daily digest from the command line.

uv run python run_digest.py                    # build and send (once per day)
uv run python run_digest.py --dry-run          # build and save HTML to out/, don't send
uv run python run_digest.py --fixture slow-day # offline run on a saved snapshot
uv run python run_digest.py --force            # send even if already sent today
"""

import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv(".env.secrets")
load_dotenv()

from app import config  # noqa: E402
from app.collect import local_today  # noqa: E402
from app.daily import run_daily  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="save HTML to out/ instead of emailing"
    )
    parser.add_argument(
        "--fixture", help="use tests/eval/fixtures/<name>.json (implies --dry-run)"
    )
    parser.add_argument(
        "--force", action="store_true", help="send even if already sent today"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    result = asyncio.run(
        run_daily(send=not args.dry_run, fixture=args.fixture, force=args.force)
    )
    if result.get("html"):
        config.OUT_DIR.mkdir(exist_ok=True)
        out_file = config.OUT_DIR / f"digest-{local_today().isoformat()}.html"
        out_file.write_text(result["html"])
        logging.info("saved %s (%d items)", out_file, result["items"])
    logging.info(
        "result: %s",
        result["status"] + (f" ({result['reason']})" if result.get("reason") else ""),
    )
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
