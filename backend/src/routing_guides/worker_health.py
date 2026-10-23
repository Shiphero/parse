"""Container-local worker heartbeat; another task cannot mask a stalled worker."""
import time
from pathlib import Path

HEARTBEAT = Path('/tmp/parse-worker-heartbeat')


def mark_alive():
    temporary = HEARTBEAT.with_suffix('.tmp')
    temporary.write_text(str(time.time()))
    temporary.replace(HEARTBEAT)


def healthy() -> bool:
    try:
        return 0 <= time.time() - float(HEARTBEAT.read_text()) < 60
    except (OSError, ValueError):
        return False


if __name__ == '__main__':
    raise SystemExit(0 if healthy() else 1)
