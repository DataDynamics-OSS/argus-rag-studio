"""Prometheus metrics configuration API endpoint."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.config_loader import update_properties
from app.metrics.scheduler import metrics_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


class PrometheusConfigRequest(BaseModel):
    """Request to update Prometheus Push Gateway configuration."""

    prometheus_enable_push: str = Field(description="Enable push to gateway (true/false)")
    prometheus_push_cron: str = Field(description="Cron expression for push schedule")
    prometheus_pushgateway_host: str = Field(description="Push Gateway host")
    prometheus_pushgateway_port: str = Field(description="Push Gateway port")


class PrometheusConfigResponse(BaseModel):
    """Response after updating Prometheus configuration."""

    success: bool
    message: str


@router.put("/config", response_model=PrometheusConfigResponse)
async def update_prometheus_config(body: PrometheusConfigRequest) -> PrometheusConfigResponse:
    """Update Prometheus Push Gateway configuration.

    1. Update config.properties file on disk.
    2. Update in-memory settings.
    3. Reschedule the metrics scheduler with the new cron expression.
    """
    try:
        # 1. Update config.properties file
        updates = {
            "prometheus.enable-push": body.prometheus_enable_push,
            "prometheus.push-cron": body.prometheus_push_cron,
            "prometheus.pushgateway.host": body.prometheus_pushgateway_host,
            "prometheus.pushgateway.port": body.prometheus_pushgateway_port,
        }
        update_properties(settings.config_properties_path, updates)

        # 2. Update in-memory settings
        settings.update_prometheus(
            enable_push=body.prometheus_enable_push,
            push_cron=body.prometheus_push_cron,
            pushgateway_host=body.prometheus_pushgateway_host,
            pushgateway_port=body.prometheus_pushgateway_port,
        )

        # 3. Reschedule the metrics scheduler
        await metrics_scheduler.reschedule()

        logger.info(
            "Prometheus config updated: enable_push=%s, cron=%s, gateway=%s:%s",
            body.prometheus_enable_push,
            body.prometheus_push_cron,
            body.prometheus_pushgateway_host,
            body.prometheus_pushgateway_port,
        )
        return PrometheusConfigResponse(
            success=True,
            message="Prometheus configuration updated and scheduler rescheduled",
        )
    except Exception as exc:
        logger.exception("Failed to update Prometheus config")
        return PrometheusConfigResponse(success=False, message=str(exc))
