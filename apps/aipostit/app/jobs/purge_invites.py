"""The purge-invites CronJob's command (python -m app.jobs.purge_invites): runs
purge_ended_invites once in the Job's own pod, so a failed purge fails the Job and its alert
fires. Exits 0 when every hotel was purged, 1 otherwise; the logs say which hotel failed."""

import logging
import sys

from app.config import get_settings
from app.observability import configure_logging

log = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    from app.database import get_supabase
    from app.hotels.invites import purge_ended_invites

    try:
        purge_ended_invites(get_supabase())
    except Exception:
        log.exception("The purge of ended staff invites failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
