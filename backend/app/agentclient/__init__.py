# SPDX-License-Identifier: Apache-2.0
"""Argus Insight Agent REST 클라이언트(컨트롤러→Agent push)."""

from app.agentclient.client import AgentClient, AgentError

__all__ = ["AgentClient", "AgentError"]
