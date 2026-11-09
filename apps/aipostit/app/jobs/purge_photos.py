"""The purge-photos CronJob's command (python -m app.jobs.purge_photos): runs
purge_orphan_photos once in the Job's own pod, so a failed purge fails the Job and its alert
fires. Exits 0 when it worked, 1 otherwise; the logs say why."""

import logging
import sys

from app.config import get_settings
from app.observability import configure_logging

log = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    from app.database import get_supabase
    from app.profile_photo import purge_orphan_photos

    try:
        purge_orphan_photos(get_supabase())
    except Exception:
        log.exception("The purge of orphan profile photos failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
