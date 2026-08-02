# SPDX-License-Identifier: Apache-2.0
"""python -m detection_server 로 실행."""

import uvicorn

from detection_server.config import config

if __name__ == "__main__":
    uvicorn.run("detection_server.main:app", host=config.host, port=config.port)
