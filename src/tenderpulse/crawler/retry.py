def should_retry(attempt: int) -> bool:
    return attempt < 3
