# SPDX-License-Identifier: Apache-2.0
"""python -m embedding_server 로 실행."""

import uvicorn

from embedding_server.config import config

if __name__ == "__main__":
    uvicorn.run("embedding_server.main:app", host=config.host, port=config.port)
