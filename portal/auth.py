import hashlib
import re
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException
from sqlalchemy import delete
from portal.models import User, SessionToken, AuditEvent

COOKIE = "pacs_session"
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))


def hash_password(password):
    if not 12 <= len(password) <= 1024:
        raise HTTPException(400, "گذرواژه باید بین ۱۲ و ۱۰۲۴ نویسه باشد.")
    return hasher.hash(password)


def valid_username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", value):
        raise HTTPException(400, "نام کاربری: ۳ تا ۶۴ حرف انگلیسی، عدد، نقطه، خط تیره یا زیرخط.")
    return value


def verify_password(encoded, password):
    try:
        return len(password) <= 1024 and hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def identity(request, db):
    token = db.get(SessionToken, token_hash(request.cookies.get(COOKIE, "")))
    if not token or token.expires_at <= time.time():
        raise HTTPException(401, "لطفاً وارد حساب خود شوید.")
    user = db.get(User, token.user_id)
    if not user or not user.active:
        raise HTTPException(401, "حساب غیرفعال است.")
    return user, token


def staff(user, admin=False):
    if user.role not in (["admin"] if admin else ["operator", "admin"]):
        raise HTTPException(403, "دسترسی به این بخش مجاز نیست.")


def check_csrf(token, form):
    value = form.get("csrf", "")
    if not isinstance(value, str) or not secrets.compare_digest(token.csrf, value):
        raise HTTPException(403, "توکن امنیتی معتبر نیست؛ صفحه را دوباره باز کنید.")


def revoke_sessions(db, user_id):
    db.execute(delete(SessionToken).where(SessionToken.user_id == user_id))


def audit(db, actor, action, target="", detail=""):
    db.add(AuditEvent(actor_id=actor, action=action, target=str(target)[:80], detail=str(detail)[:1000]))
