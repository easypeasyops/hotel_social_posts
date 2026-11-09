"""Staff invites sent by email: a 7-day invite for one role that only the address it's sent
to can sign up with (/signup), in an email in Turkish, like the staff pages. And recorded
invites: a staff_invites row (migration 006), pending until it's accepted, revoked or expired."""

import logging
from datetime import UTC, datetime
from urllib.parse import quote

from app.auth.upload_tokens import STAFF_INVITE_TTL_SECONDS, create_token, staff_invite_purpose
from app.mail import send_mail

logger = logging.getLogger(__name__)

ROLE_NAMES_TR = {
    "hotel_admin": "otel yöneticisi",
    "content_moderator": "içerik moderatörü",
    "content_creator": "içerik üreticisi",
}


def send_invite_email(base_url: str, hotel: dict, role: str, email: str) -> None:
    """Raises MailError when the email can't be sent."""
    email = email.strip().lower()
    invite = create_token(hotel["id"], staff_invite_purpose(role), STAFF_INVITE_TTL_SECONDS, email)
    link = f"{base_url.rstrip('/')}/signup#invite={quote(invite, safe='')}"
    days = STAFF_INVITE_TTL_SECONDS // 86400
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
