from collections import deque
_q = deque()
def enqueue(item):
    _q.append(item)
def dequeue():
    return _q.popleft() if _q else None
