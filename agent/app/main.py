"""Argus RAG Studio Agent - FastAPI application entry point."""

import argparse
import logging
import sys
import time
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI

from app import __version__
from app.certmgr.router import router as certmgr_router
from app.command.router import router as command_router
from app.containermgr.router import router as containermgr_router
from app.modelmgr.router import router as modelmgr_router
from app.core.config import settings
from app.core.config_loader import load_properties, update_properties
from app.core.logging import setup_logging
from app.core.security import SecurityHeadersMiddleware
from app.filemgr.router import router as filemgr_router
from app.heartbeat.scheduler import heartbeat_scheduler
from app.hostmgr.router import router as hostmgr_router
from app.metrics.router import router as metrics_router
from app.metrics.scheduler import metrics_scheduler
from app.monitor.router import router as monitor_router
from app.package.router import router as package_router
from app.processmgr.router import router as processmgr_router
from app.servicemgr.router import router as servicemgr_router
from app.sysmon.router import router as sysmon_router
from app.terminal.router import router as terminal_router
from app.terminal.service import terminal_manager
from app.usermgr.router import router as usermgr_router
from app.yum.router import router as yum_router

logger = logging.getLogger(__name__)
_start_time: float = 0.0

BANNER = r"""
    _                            ____      _    ____   ____  _             _ _
   / \   _ __ __ _ _   _ ___    |  _ \    / \  / ___| / ___|| |_ _   _  __| (_) ___
  / _ \ | '__/ _` | | | / __|   | |_) |  / _ \| |  _  \___ \| __| | | |/ _` | |/ _ \
 / ___ \| | | (_| | |_| \__ \   |  _ <  / ___ \ |_| |  ___) | |_| |_| | (_| | | (_) |
/_/   \_\_|  \__, |\__,_|___/   |_| \_\/_/   \_\____| |____/ \__|\__,_|\__,_|_|\___/
            |___/                        A G E N T
"""


def _print_banner() -> None:
    """Print startup banner with version and config paths."""
    logger.info(BANNER)
    logger.info("Version           : %s", settings.app_version)
    logger.info("Config YAML       : %s", settings.config_yaml_path)
    logger.info("Config Properties : %s", settings.config_properties_path)
    logger.info("Config Server Properties : %s", settings.config_server_properties_path)


async def _sync_prometheus_config_from_server() -> None:
    """Fetch Prometheus settings from Argus RAG Studio Server and apply if changed."""
    server_url = (
        f"http://{settings.studio_server_ip}:{settings.studio_server_port}"
        f"/api/v1/settings/configuration"
    )
    logger.info("Fetching Prometheus config from server: %s", server_url)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(server_url)
            if resp.status_code != 200:
                logger.warning(
                    "Failed to fetch config from server: status=%d", resp.status_code,
                )
                return

        data = resp.json()
        categories = data.get("categories", [])
        argus_items: dict[str, str] = {}
        for cat in categories:
            if cat.get("category") == "argus":
                argus_items = cat.get("items", {})
                break

        # Extract prometheus keys from server config
        key_map = {
            "prometheus_enable_push": "prometheus.enable-push",
            "prometheus_push_cron": "prometheus.push-cron",
            "prometheus_pushgateway_host": "prometheus.pushgateway.host",
            "prometheus_pushgateway_port": "prometheus.pushgateway.port",
        }
        server_values: dict[str, str] = {}
        for db_key, prop_key in key_map.items():
            if db_key in argus_items:
                server_values[prop_key] = argus_items[db_key]

        if not server_values:
            logger.info("No Prometheus config found on server, using local config")
            return

        # Compare with local config.properties
        local_props = load_properties(settings.config_properties_path)
        changed: dict[str, str] = {}
        for key, server_val in server_values.items():
            if local_props.get(key, "") != server_val:
                changed[key] = server_val

        if not changed:
            logger.info("Prometheus config is up-to-date, no changes needed")
            return

        logger.info("Prometheus config changed, updating: %s", changed)

        # Update config.properties with changed values
        update_properties(settings.config_properties_path, changed)

        # Update in-memory settings
        settings.update_prometheus(
            enable_push=server_values.get(
                "prometheus.enable-push", str(settings.prometheus_enable_push),
            ),
            push_cron=server_values.get(
                "prometheus.push-cron", settings.prometheus_push_cron,
            ),
            pushgateway_host=server_values.get(
                "prometheus.pushgateway.host", settings.prometheus_pushgateway_host,
            ),
            pushgateway_port=server_values.get(
                "prometheus.pushgateway.port", str(settings.prometheus_pushgateway_port),
            ),
        )

        logger.info(
            "Prometheus config synced from server: "
            "enable_push=%s, cron=%s, gateway=%s:%s",
            settings.prometheus_enable_push,
            settings.prometheus_push_cron,
            settings.prometheus_pushgateway_host,
            settings.prometheus_pushgateway_port,
        )

    except httpx.ConnectError:
        logger.warning(
            "Cannot connect to server at %s:%s, using local Prometheus config",
            settings.studio_server_ip, settings.studio_server_port,
        )
    except Exception:
        logger.exception("Failed to sync Prometheus config from server, using local config")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _start_time
    _start_time = time.monotonic()
    setup_logging()
    _print_banner()
    logger.info("Argus RAG Studio Agent %s starting", __version__)
    await _sync_prometheus_config_from_server()
    await metrics_scheduler.start()
    await heartbeat_scheduler.start()
    terminal_manager.start_reaper()
    yield
    await heartbeat_scheduler.stop()
    await metrics_scheduler.stop()
    logger.info("Argus RAG Studio Agent shutting down")
    terminal_manager.close_all()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
)

# Middleware
app.add_middleware(SecurityHeadersMiddleware)

# Routers
app.include_router(command_router, prefix="/api/v1")
app.include_router(monitor_router, prefix="/api/v1")
app.include_router(package_router, prefix="/api/v1")
app.include_router(terminal_router, prefix="/api/v1")
app.include_router(sysmon_router, prefix="/api/v1")
app.include_router(yum_router, prefix="/api/v1")
app.include_router(hostmgr_router, prefix="/api/v1")
app.include_router(usermgr_router, prefix="/api/v1")
app.include_router(certmgr_router, prefix="/api/v1")
app.include_router(filemgr_router, prefix="/api/v1")
app.include_router(processmgr_router, prefix="/api/v1")
app.include_router(servicemgr_router, prefix="/api/v1")
app.include_router(containermgr_router, prefix="/api/v1")
app.include_router(modelmgr_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")


@app.get("/health")
async def health():
    """Health check endpoint."""
    uptime_seconds = int(time.monotonic() - _start_time)
    return {
        "status": "ok",
        "service": "argus-rag-studio-agent",
        "uptime": uptime_seconds,
        "version": __version__,
    }


def run() -> None:
    """CLI entry point with config file argument support."""
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-agent",
        description="Argus RAG Studio Agent - Server management agent for Argus RAG Studio platform.",
        epilog=(
            "examples:\n"
            "  argus-rag-studio-agent\n"
            "  argus-rag-studio-agent --config-yaml /opt/config/config.yml\n"
            "  argus-rag-studio-agent --config-properties /opt/config/config.properties\n"
            "  argus-rag-studio-agent --config-server-properties /opt/config/server.properties\n"
            "  argus-rag-studio-agent --config-yaml ./config.yml --config-properties ./config.properties"
            " --config-server-properties ./server.properties\n"
            "\n"
            "If no options are specified, configuration files are loaded from\n"
            "/etc/argus-rag-studio-agent/ (or the ARGUS_CONFIG_DIR environment variable)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config-yaml",
        metavar="PATH",
        help=(
            "path to the YAML configuration file (config.yml). "
            "This file defines the main application settings using "
            "Spring Boot style ${variable:default} placeholders. "
            "(default: /etc/argus-rag-studio-agent/config.yml)"
        ),
    )
    parser.add_argument(
        "--config-properties",
        metavar="PATH",
        help=(
            "path to the properties variable file (config.properties). "
            "This file defines key=value variables referenced by config.yml "
            "for environment-specific values such as host, port, and credentials. "
            "(default: /etc/argus-rag-studio-agent/config.properties)"
        ),
    )
    parser.add_argument(
        "--config-server-properties",
        metavar="PATH",
        help=(
            "path to the server properties file (server.properties). "
            "This file defines the central server address that this agent reports to "
            "for heartbeat and management. "
            "(default: /etc/argus-rag-studio-agent/server.properties)"
        ),
    )
    args = parser.parse_args()

    if args.config_yaml or args.config_properties or args.config_server_properties:
        from app.core.config import init_settings

        init_settings(
            yaml_path=args.config_yaml,
            properties_path=args.config_properties,
            server_properties_path=args.config_server_properties,
        )
    else:
        yaml_exists = settings.config_yaml_path.is_file()
        props_exists = settings.config_properties_path.is_file()
        server_props_exists = settings.config_server_properties_path.is_file()
        if not yaml_exists and not props_exists and not server_props_exists:
            parser.print_help()
            print()
            print(
                f"Error: No configuration files found at default location:\n"
                f"  - {settings.config_yaml_path}\n"
                f"  - {settings.config_properties_path}\n"
                f"  - {settings.config_server_properties_path}\n"
                f"\n"
                f"Specify config file paths with --config-yaml, "
                f"--config-properties, and/or "
                f"--config-server-properties options."
            )
            sys.exit(1)

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
