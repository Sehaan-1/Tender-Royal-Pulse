def normalize_money(amount) -> float:
    try:
        return float(amount)
    except Exception:
        return 0.0
