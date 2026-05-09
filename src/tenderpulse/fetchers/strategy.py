# Placeholder strategy bridging static and browser fetchers
def route(url: str):
    return {"strategy": "static" if "http" in url else "browser"}
