"""Token do trabalho, assinado pelo Worker (mesmo formato de backend/src/video/jobToken.ts).

Formato: `<dados>.<assinatura>`, ambos base64url sem `=`. `dados` é o JSON {"u": usuário, "r": trabalho,
"e": vence em (ms)}; a assinatura é HMAC-SHA256 com a chave `studioprompter:studio:<segredo>`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

_B64URL = re.compile(r'^[A-Za-z0-9_-]+$')


@dataclass(frozen=True)
class Job:
    user_id: str
    job_id: str


def _decode(text: str) -> bytes | None:
    if not _B64URL.match(text):
        return None
    try:
        return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    except (ValueError, TypeError):
        return None


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _key(secret: str) -> bytes:
    return f'studioprompter:studio:{secret}'.encode('utf-8')


def sign(secret: str, user_id: str, job_id: str, expires_ms: int) -> str:
    """Só para testes e ferramentas: o app recebe o token do Worker."""
    payload = json.dumps({'u': user_id, 'r': job_id, 'e': expires_ms}, separators=(',', ':'))
    data = _encode(payload.encode('utf-8'))  # igual ao JSON.stringify do Worker
    signature = hmac.new(_key(secret), data.encode('ascii'), hashlib.sha256).digest()
    return f'{data}.{_encode(signature)}'


def verify(secret: str, token: str, now_ms: int | None = None) -> Job | None:
    """Devolve o trabalho, ou None se o token for inválido, adulterado ou vencido."""
    parts = token.split('.')
    if len(parts) != 2 or not secret:
        return None
    data, signature = parts
    given = _decode(signature)
    if given is None:
        return None
    expected = hmac.new(_key(secret), data.encode('ascii'), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, given):
        return None
    raw = _decode(data)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    user, job, expires = payload.get('u'), payload.get('r'), payload.get('e')
    if not isinstance(user, str) or not isinstance(job, str) or not isinstance(expires, (int, float)):
        return None
    # O id do trabalho vira nome de pasta: só caracteres seguros.
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', job):
        return None
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if expires < now:
        return None
    return Job(user_id=user, job_id=job)
