"""Staff invites: a staff_invites row (migration 006) for one email and role, pending until
it's accepted, revoked or expired, and its link (/signup), emailed in Turkish, like the staff
pages, where SMTP is set up."""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import uuid4

from app.auth.upload_tokens import create_recorded_invite_token
from app.mail import MailError, mail_configured, send_mail

logger = logging.getLogger(__name__)

ROLE_NAMES_TR = {
    "hotel_admin": "otel yöneticisi",
    "content_moderator": "içerik moderatörü",
    "content_creator": "içerik üreticisi",
}


def _send_invite_mail(hotel: dict, role: str, email: str, link: str, days: int) -> None:
    """Raises MailError when the email can't be sent."""
    send_mail(
        email,
        f"{hotel['name']} ekibine davetlisiniz",
        f"Merhaba,\n\n"
        f"{hotel['name']} için aipostit'e {ROLE_NAMES_TR[role]} olarak davet edildiniz. "
        f"Bu bağlantıdan bir şifre belirleyip hesabınızı açın ({days} gün geçerli):\n\n"
        f"{link}\n\n"
        f"Bağlantı yalnızca bu e-posta adresiyle ({email}) kullanılabilir. "
        f"Bu daveti beklemiyorsanız e-postayı yok sayabilirsiniz.\n",
    )


def _link(base_url: str, hotel_id: str, invite_id: str, email: str, expires_at: datetime) -> str:
    """An invite's /signup link, made again from its row whenever it's shown: none is stored."""
    invite = create_recorded_invite_token(hotel_id, invite_id, email, expires_at)
    return f"{base_url.rstrip('/')}/signup#invite={quote(invite, safe='')}"


def invite_status(row: dict, now: datetime) -> str:
    """accepted, revoked, expired or pending: derived from the row, not stored."""
    if row["accepted_at"] is not None:
        return "accepted"
    if row["revoked_at"] is not None:
        return "revoked"
    if datetime.fromisoformat(row["expires_at"]) <= now:
        return "expired"
    return "pending"


def list_invites(db, base_url: str, hotel_id: str) -> list[dict]:
    """The hotel's invites, newest first, each with its status and, while pending, its link."""
    rows = (
        db.table("staff_invites")
        .select(
            "id, role, email, invited_by_email, created_at, expires_at, last_sent_at,"
            " accepted_at, revoked_at"
        )
        .eq("hotel_id", hotel_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    now = datetime.now(UTC)
    invites = []
    for row in rows:
        status = invite_status(row, now)
        link = None
        if status == "pending":
            expires_at = datetime.fromisoformat(row["expires_at"])
            link = _link(base_url, hotel_id, row["id"], row["email"], expires_at)
        invites.append({**row, "status": status, "link": link})
    return invites


def create_invite(
    db, base_url: str, hotel: dict, role: str, email: str, valid_days: int, invited_by: str
) -> tuple[str, bool]:
    """Records an invite for this email and role, valid for valid_days, and emails its link
    where SMTP is set up. The link, and whether the email went out: if it didn't (no SMTP, or
    the send failed), the invite stays pending with no last_sent_at."""
    email = email.strip().lower()
    invite_id, expires_at = str(uuid4()), datetime.now(UTC) + timedelta(days=valid_days)
    db.table("staff_invites").insert(
        {
            "id": invite_id,
            "hotel_id": hotel["id"],
            "role": role,
            "email": email,
            "valid_days": valid_days,
            "invited_by_email": invited_by,
            "expires_at": expires_at.isoformat(),
        }
    ).execute()
    link = _link(base_url, hotel["id"], invite_id, email, expires_at)
    if not mail_configured():
        return link, False
    try:
        _send_invite_mail(hotel, role, email, link, valid_days)
    except MailError:
        logger.exception("The staff invite email could not be sent")
        return link, False
    # The email went out: a failure to note that is logged, not an error page, which would
    # have the inviter send it again. The invite then reads "email not sent".
    try:
        sent_at = datetime.now(UTC).isoformat()
        db.table("staff_invites").update({"last_sent_at": sent_at, "send_count": 1}).eq(
            "id", invite_id
        ).execute()
    except Exception:
        logger.exception("Staff invite %s was emailed but its send wasn't recorded", invite_id)
    return link, True


def pending_invite(db, invite_id: str, hotel_id: str) -> dict | None:
    """The row of a recorded invite for this hotel that can still be used (its email and
    role), or None: missing, another hotel's, accepted, revoked or expired."""
    rows = (
        db.table("staff_invites")
        .select("hotel_id, role, email, expires_at, accepted_at, revoked_at")
        .eq("id", invite_id)
        .execute()
        .data
    )
    row = rows[0] if rows else None
    if (
        row is None
        or row["hotel_id"] != hotel_id
        or row["accepted_at"] is not None
        or row["revoked_at"] is not None
        or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC)
    ):
        return None
    return row


def claim_invite(db, invite_id: str) -> bool:
    """Marks a pending invite accepted, in one conditional update, so of two sign-ups racing
    on it only one gets True."""
    now = datetime.now(UTC).isoformat()
    claimed = (
        db.table("staff_invites")
        .update({"accepted_at": now})
        .eq("id", invite_id)
        .is_("accepted_at", "null")
        .is_("revoked_at", "null")
        .gt("expires_at", now)
        .execute()
        .data
    )
    return bool(claimed)


def release_invite(db, invite_id: str | None) -> None:
    """Makes a claimed invite pending again, when the sign-up that claimed it made no member
    (None: the sign-up had no recorded invite). If that fails too, the invite stays accepted
    and unused: a new one is needed."""
    if invite_id is None:
        return
    try:
        db.table("staff_invites").update({"accepted_at": None}).eq("id", invite_id).execute()
    except Exception:
        logger.exception("Could not release staff invite %s after a failed sign-up", invite_id)
