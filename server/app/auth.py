"""
Cuentas de usuario: hash de contraseñas, sesiones y dependencias de FastAPI.

* Contraseñas con scrypt (hashlib, biblioteca estándar): es lento a propósito y
  usa memoria, así que probar millones de contraseñas contra un hash robado cuesta
  caro. No necesita dependencias nativas extra en Vercel.
  Formato guardado: "scrypt$n$r$p$sal_hex$hash_hex".
* Sesión: token aleatorio de 256 bits en la cookie httponly `vault_session`.
  En la tabla `sessions` solo se guarda su SHA-256.
* Es independiente de la cookie `sid` (identificador anónimo del rate limiter).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.responses import Response

from app import config
from app.pg import get_pg

COOKIE_NAME = "vault_session"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)   # comparación en tiempo constante


# Hash de relleno: si el usuario no existe se verifica contra este para que la
# respuesta tarde lo mismo y no se pueda averiguar qué nombres están registrados.
DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, user_id: int, response: Response) -> None:
    """Crea la sesión en la base y pone la cookie en la respuesta."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=config.SESSION_DAYS)
    conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                 (_token_hash(token), user_id, expires))
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        max_age=config.SESSION_DAYS * 86400,
        httponly=True,                 # JavaScript no la puede leer (XSS)
        samesite="lax",                # no viaja en POST desde otros sitios (CSRF)
        secure=config.COOKIE_SECURE,   # solo por HTTPS en Vercel
        path="/",
    )


def destroy_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with get_pg() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))
    response.delete_cookie(COOKIE_NAME, path="/")


def user_from_request(conn, request: Request) -> dict | None:
    """Usuario de la cookie de sesión, o None si no hay sesión válida."""
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 100:
        return None
    return conn.execute(
        "SELECT u.id, u.username, u.points, u.last_bonus FROM sessions s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = %s AND s.expires_at > now()",
        (_token_hash(token),),
    ).fetchone()


def require_user(conn, request: Request) -> dict:
    """Como user_from_request, pero responde 401 si no hay sesión."""
    user = user_from_request(conn, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
    return user
