"""Create local configuration without replacing existing credentials or data."""

import os
from pathlib import Path
import secrets


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    template = (root / ".env.example").read_text()
    content = template.replace("replace-with-generated-local-password", secrets.token_hex(24))
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env preserved.")
        return
    with os.fdopen(fd, "w") as file:
        file.write(content)
    print("Created .env with local database credentials. AI keys are optional for setup.")


if __name__ == "__main__":
    main()
