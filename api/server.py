from __future__ import annotations

import uvicorn

from config.config import config
from .app import app


def main() -> None:
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, reload=False)


if __name__ == "__main__":
    main()

