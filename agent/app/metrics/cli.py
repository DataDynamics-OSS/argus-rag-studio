"""Argus RAG Studio Agent - Metrics CLI.

Collect host metrics and optionally push to Prometheus Push Gateway.
"""

import argparse
import sys

from prometheus_client import generate_latest

from app.metrics.collector import _get_hostname, collect_metrics
from app.metrics.pusher import JOB_NAME


def _print_metrics(registry) -> None:
    """Print metrics in Prometheus exposition format."""
    output = generate_latest(registry).decode("utf-8")
    print(output, end="")


def _push_metrics(registry, host: str, port: int) -> bool:
    """Push metrics to Prometheus Push Gateway."""
    from prometheus_client import pushadd_to_gateway

    gateway = f"{host}:{port}"
    instance = _get_hostname()

    try:
        pushadd_to_gateway(
            gateway,
            job=JOB_NAME,
            registry=registry,
            grouping_key={"instance": instance},
        )
        print(f"Pushed metrics to {gateway} (job={JOB_NAME}, instance={instance})")
        return True
    except Exception as e:
        print(f"Failed to push metrics to {gateway}: {e}", file=sys.stderr)
        return False


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-metric",
        description="Collect and display host metrics for Prometheus Push Gateway",
    )
    parser.add_argument(
        "--pushgateway.host",
        dest="pushgateway_host",
        help="Push Gateway host (if specified, metrics will be pushed after display)",
    )
    parser.add_argument(
        "--pushgateway.port",
        dest="pushgateway_port",
        type=int,
        default=9091,
        help="Push Gateway port (default: 9091)",
    )

    args = parser.parse_args()

    registry = collect_metrics()
    _print_metrics(registry)

    if args.pushgateway_host:
        success = _push_metrics(registry, args.pushgateway_host, args.pushgateway_port)
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
