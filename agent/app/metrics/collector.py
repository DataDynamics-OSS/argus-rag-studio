"""Host metrics collector for Prometheus Push Gateway."""

import logging
import socket
from pathlib import Path

import psutil
from prometheus_client import CollectorRegistry, Gauge

logger = logging.getLogger(__name__)


def _get_fqdn() -> str:
    """Get the FQDN hostname for use as Prometheus instance label."""
    return socket.getfqdn()


def _get_hostname() -> str:
    """Get the short hostname for use as Prometheus hostname label."""
    return socket.gethostname()


def _get_socket_count() -> int:
    """Get the total number of socket connections."""
    try:
        return len(psutil.net_connections(kind="all"))
    except (psutil.AccessDenied, OSError):
        return 0


def _get_too_many_open_files_count(threshold: float = 90.0) -> int:
    """Count processes where open files usage >= threshold% of max."""
    count = 0
    for proc in psutil.process_iter():
        try:
            pid = proc.pid
            fd_path = Path(f"/proc/{pid}/fd")
            try:
                current = len(list(fd_path.iterdir()))
            except OSError:
                continue

            # Read soft limit from /proc/<pid>/limits
            try:
                limits_content = Path(f"/proc/{pid}/limits").read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue

            max_open = 0
            for line in limits_content.splitlines():
                if "max open files" in line.lower():
                    parts = line.rsplit(None, 3)
                    if len(parts) >= 3:
                        try:
                            max_open = int(parts[-3])
                        except ValueError:
                            pass
                    break

            if max_open > 0 and (current / max_open * 100) >= threshold:
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return count


def collect_metrics() -> CollectorRegistry:
    """Collect all host metrics and return a Prometheus registry.

    Returns a fresh CollectorRegistry each time to avoid duplicate metric
    registration errors across collection cycles.
    """
    registry = CollectorRegistry()
    hostname = _get_hostname()

    # -----------------------------------------------------------------------
    # CPU
    # -----------------------------------------------------------------------
    cpu_pct = psutil.cpu_percent(interval=0.5)
    load1, load5, load15 = psutil.getloadavg()
    cpu_count = psutil.cpu_count() or 1

    Gauge(
        "node_argus_cpu_usage_percent", "CPU usage percent", ["hostname"], registry=registry
    ).labels(hostname).set(cpu_pct)
    Gauge(
        "node_argus_cpu_load1", "1-min load average", ["hostname"], registry=registry
    ).labels(hostname).set(load1)
    Gauge(
        "node_argus_cpu_load5", "5-min load average", ["hostname"], registry=registry
    ).labels(hostname).set(load5)
    Gauge(
        "node_argus_cpu_load15", "15-min load average", ["hostname"], registry=registry
    ).labels(hostname).set(load15)
    Gauge(
        "node_argus_cpu_count", "CPU core count", ["hostname"], registry=registry
    ).labels(hostname).set(cpu_count)

    # -----------------------------------------------------------------------
    # Memory
    # -----------------------------------------------------------------------
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    Gauge(
        "node_argus_memory_total_bytes", "Total memory", ["hostname"], registry=registry
    ).labels(hostname).set(mem.total)
    Gauge(
        "node_argus_memory_used_bytes", "Used memory", ["hostname"], registry=registry
    ).labels(hostname).set(mem.used)
    Gauge(
        "node_argus_memory_available_bytes", "Available memory", ["hostname"], registry=registry
    ).labels(hostname).set(mem.available)
    Gauge(
        "node_argus_memory_usage_percent", "Memory usage percent", ["hostname"], registry=registry
    ).labels(hostname).set(mem.percent)
    Gauge(
        "node_argus_swap_total_bytes", "Total swap memory", ["hostname"], registry=registry
    ).labels(hostname).set(swap.total)
    Gauge(
        "node_argus_swap_used_bytes", "Used swap memory", ["hostname"], registry=registry
    ).labels(hostname).set(swap.used)

    # -----------------------------------------------------------------------
    # Processes
    # -----------------------------------------------------------------------
    pids = psutil.pids()
    zombie_count = 0
    for proc in psutil.process_iter():
        try:
            if proc.status() == psutil.STATUS_ZOMBIE:
                zombie_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    Gauge(
        "node_argus_process_total", "Total process count", ["hostname"], registry=registry
    ).labels(hostname).set(len(pids))
    Gauge(
        "node_argus_process_zombie_count", "Zombie process count", ["hostname"], registry=registry
    ).labels(hostname).set(zombie_count)

    # -----------------------------------------------------------------------
    # Sockets
    # -----------------------------------------------------------------------
    Gauge(
        "node_argus_socket_count", "Total socket count", ["hostname"], registry=registry
    ).labels(hostname).set(_get_socket_count())

    # -----------------------------------------------------------------------
    # Disk (per partition)
    # -----------------------------------------------------------------------
    disk_total = Gauge(
        "node_argus_disk_total_bytes",
        "Disk total bytes",
        ["hostname", "device", "mountpoint", "fstype"],
        registry=registry,
    )
    disk_used = Gauge(
        "node_argus_disk_used_bytes",
        "Disk used bytes",
        ["hostname", "device", "mountpoint", "fstype"],
        registry=registry,
    )
    disk_free = Gauge(
        "node_argus_disk_free_bytes",
        "Disk free bytes",
        ["hostname", "device", "mountpoint", "fstype"],
        registry=registry,
    )
    disk_usage_pct = Gauge(
        "node_argus_disk_usage_percent",
        "Disk usage percent",
        ["hostname", "device", "mountpoint", "fstype"],
        registry=registry,
    )

    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            labels = [hostname, part.device, part.mountpoint, part.fstype]
            disk_total.labels(*labels).set(usage.total)
            disk_used.labels(*labels).set(usage.used)
            disk_free.labels(*labels).set(usage.free)
            disk_usage_pct.labels(*labels).set(usage.percent)
        except (PermissionError, OSError):
            continue

    # -----------------------------------------------------------------------
    # Disk I/O
    # -----------------------------------------------------------------------
    try:
        disk_io = psutil.disk_io_counters(perdisk=True)
        dio_read = Gauge(
            "node_argus_disk_io_read_bytes",
            "Disk I/O read bytes",
            ["hostname", "device"],
            registry=registry,
        )
        dio_write = Gauge(
            "node_argus_disk_io_write_bytes",
            "Disk I/O write bytes",
            ["hostname", "device"],
            registry=registry,
        )
        dio_read_count = Gauge(
            "node_argus_disk_io_read_count",
            "Disk I/O read count",
            ["hostname", "device"],
            registry=registry,
        )
        dio_write_count = Gauge(
            "node_argus_disk_io_write_count",
            "Disk I/O write count",
            ["hostname", "device"],
            registry=registry,
        )
        if disk_io:
            for dev, counters in disk_io.items():
                dio_read.labels(hostname, dev).set(counters.read_bytes)
                dio_write.labels(hostname, dev).set(counters.write_bytes)
                dio_read_count.labels(hostname, dev).set(counters.read_count)
                dio_write_count.labels(hostname, dev).set(counters.write_count)
    except (RuntimeError, OSError):
        pass

    # -----------------------------------------------------------------------
    # Network (per interface)
    # -----------------------------------------------------------------------
    try:
        net_io = psutil.net_io_counters(pernic=True)
        net_sent = Gauge(
            "node_argus_network_bytes_sent",
            "Network bytes sent",
            ["hostname", "interface"],
            registry=registry,
        )
        net_recv = Gauge(
            "node_argus_network_bytes_recv",
            "Network bytes received",
            ["hostname", "interface"],
            registry=registry,
        )
        net_errin = Gauge(
            "node_argus_network_errors_in",
            "Network input errors",
            ["hostname", "interface"],
            registry=registry,
        )
        net_errout = Gauge(
            "node_argus_network_errors_out",
            "Network output errors",
            ["hostname", "interface"],
            registry=registry,
        )
        net_dropin = Gauge(
            "node_argus_network_drop_in",
            "Network input drops",
            ["hostname", "interface"],
            registry=registry,
        )
        net_dropout = Gauge(
            "node_argus_network_drop_out",
            "Network output drops",
            ["hostname", "interface"],
            registry=registry,
        )

        for iface, counters in net_io.items():
            net_sent.labels(hostname, iface).set(counters.bytes_sent)
            net_recv.labels(hostname, iface).set(counters.bytes_recv)
            net_errin.labels(hostname, iface).set(counters.errin)
            net_errout.labels(hostname, iface).set(counters.errout)
            net_dropin.labels(hostname, iface).set(counters.dropin)
            net_dropout.labels(hostname, iface).set(counters.dropout)
    except (RuntimeError, OSError):
        pass

    # -----------------------------------------------------------------------
    # Too many open files
    # -----------------------------------------------------------------------
    Gauge(
        "node_argus_too_many_open_files_count",
        "Processes with open files >= 90% of limit",
        ["hostname"],
        registry=registry,
    ).labels(hostname).set(_get_too_many_open_files_count())

    logger.debug("Collected host metrics for Prometheus push")
    return registry
