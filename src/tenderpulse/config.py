from typing import Optional

class Config:
    # Minimal placeholder config holder
    APP_NAME: str = "tenderpulse"
    DEBUG: bool = False
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
