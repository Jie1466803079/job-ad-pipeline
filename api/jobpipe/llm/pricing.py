"""Cost of one LLM call."""

from jobpipe.configfiles import Price


def cost_usd(model: str, input_tokens: int, output_tokens: int, prices: dict[str, Price],
             fallback_model: str | None = None) -> float | None:
    """US dollars for one call, or None when neither model has a price in config/prices.yaml."""
    price = prices.get(model) or (prices.get(fallback_model) if fallback_model else None)
    if price is None:
        return None
    return round((input_tokens * price.input + output_tokens * price.output) / 1_000_000, 6)
