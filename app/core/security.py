from passlib.context import CryptContext
import secrets
import time

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password or not plain_password:
        return False
    # Podpora jednoduchého fallbacku pokud by někdo vložil nehashované heslo
    if not hashed_password.startswith("$2b$") and not hashed_password.startswith("$2a$"):
        return plain_password == hashed_password
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

hash_password = get_password_hash

def generate_session_token() -> str:
    return secrets.token_hex(24)
