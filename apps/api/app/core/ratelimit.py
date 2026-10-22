"""Limite de taxa em memória, por chave (IP, transportadora).

A API roda com UM worker (o barramento da torre é in-process), então um contador em
processo é o contador do serviço inteiro. Janela deslizante simples: guarda os instantes
das últimas chamadas e recusa quando passam do teto dentro da janela.
"""

import time
from collections import deque
from threading import Lock

from fastapi import Request

from app.core.errors import AppError

ERR_RATE_LIMITED = "ERR_RATE_LIMITED"


class RateLimited(AppError):
    status_code = 429


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def hit(self, key: str) -> bool:
        """Registra uma chamada; devolve False se a chave passou do teto."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= self.max_keys and key not in self._hits:
                self._evict(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def check(self, key: str, **detail) -> None:
        if not self.hit(key):
            raise RateLimited(ERR_RATE_LIMITED, retry_after_seconds=int(self.window), **detail)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self.max_keys:  # ainda cheio: descarta os mais antigos
            for key in sorted(self._hits, key=lambda k: self._hits[k][-1])[: self.max_keys // 10]:
                del self._hits[key]


def client_ip(request: Request) -> str:
    """IP do cliente como o uvicorn o resolveu.

    O uvicorn roda com `--proxy-headers --forwarded-allow-ips 127.0.0.1`: só o Caddy local
    pode reescrever o endereço. Ler o `X-Forwarded-For` na mão deixaria o cliente escolher
    o próprio IP se algum dia o proxy repassar o cabeçalho recebido.
    """
    return (request.client.host if request.client else "unknown")[:64]
