"""Append-only Meta API spend ledger with a hard cap."""

import json
import time
from pathlib import Path


class BudgetExhausted(Exception):
    pass


class Budget:
    def __init__(self, ledger: Path, cap_usd: float, price_in: float, price_out: float):
        """Prices are USD per million tokens and must come from the user."""
        if cap_usd <= 0 or price_in <= 0 or price_out <= 0:
            raise ValueError("cap and prices must be positive")
        self.ledger, self.cap = ledger, cap_usd
        self.price_in, self.price_out = price_in, price_out

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.price_in + completion_tokens * self.price_out
        ) / 1e6

    def spent(self) -> float:
        if not self.ledger.exists():
            return 0.0
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        return sum(json.loads(line)["usd"] for line in lines if line.strip())

    def reserve(self, prompt_tokens: int, max_completion_tokens: int) -> None:
        """Refuse a call whose worst case would cross the cap."""
        worst = self.spent() + self.cost(prompt_tokens, max_completion_tokens)
        if worst > self.cap:
            raise BudgetExhausted(f"spent ${self.spent():.2f} of ${self.cap:.2f}")

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        usd = self.cost(prompt_tokens, completion_tokens)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": time.time(),
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "usd": usd,
        }
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return usd
