"""Prometheus Push Gateway client.

Uses prometheus_client's push_to_gateway with method='POST' to avoid
deleting metrics pushed by other agents (grouping key includes instance).
"""

import logging

from prometheus_client import pushadd_to_gateway

from app.core.config import settings
from app.metrics.collector import _get_hostname, collect_metrics

logger = logging.getLogger(__name__)

JOB_NAME = "argus_rag_studio_metrics"


def push_metrics() -> bool:
    """Collect and push host metrics to Prometheus Push Gateway.

    Uses POST method (not PUT) so that metrics from other agents/instances
    are not deleted. Grouping key includes instance=FQDN to isolate
    per-host metrics.

    Returns True on success, False on failure.
    """
    if not settings.prometheus_enable_push:
        logger.debug("Prometheus push is disabled, skipping")
        return False

    gateway = f"{settings.prometheus_pushgateway_host}:{settings.prometheus_pushgateway_port}"
    instance = _get_hostname()

    try:
        registry = collect_metrics()
        pushadd_to_gateway(
            gateway,
            job=JOB_NAME,
            registry=registry,
            grouping_key={"instance": instance},
        )
        logger.info(
            "Pushed metrics to %s (job=%s, instance=%s)",
            gateway,
            JOB_NAME,
            instance,
        )
        return True
    except Exception:
        logger.exception("Failed to push metrics to %s", gateway)
        return False
