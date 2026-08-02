# SPDX-License-Identifier: Apache-2.0
"""python -m reranker_server 로 실행."""

import uvicorn

from reranker_server.config import config

if __name__ == "__main__":
    uvicorn.run("reranker_server.main:app", host=config.host, port=config.port)
