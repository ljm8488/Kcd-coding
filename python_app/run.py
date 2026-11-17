from pathlib import Path

# .env 파일(있으면)을 환경변수로 읽는다 — 로컬 개발용
env = Path(__file__).with_name(".env")
if env.exists():
    import os
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from app.main import run  # noqa: E402

if __name__ in {"__main__", "__mp_main__"}:
    run()
