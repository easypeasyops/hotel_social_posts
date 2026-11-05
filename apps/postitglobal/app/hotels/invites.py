"""Staff invites sent by email: a 7-day invite for one role that only the address it's sent
to can sign up with (/signup), in an email in Turkish, like the staff pages."""

from urllib.parse import quote

from app.auth.upload_tokens import STAFF_INVITE_TTL_SECONDS, create_token, staff_invite_purpose
from app.mail import send_mail

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
        f"{hotel['name']} için postitglobal'e {ROLE_NAMES_TR[role]} olarak davet edildiniz. "
        f"Bu bağlantıdan bir şifre belirleyip hesabınızı açın ({days} gün geçerli):\n\n"
        f"{link}\n\n"
        f"Bağlantı yalnızca bu e-posta adresiyle ({email}) kullanılabilir. "
        f"Bu daveti beklemiyorsanız e-postayı yok sayabilirsiniz.\n",
    )
