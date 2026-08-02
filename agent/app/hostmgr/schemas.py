"""Host management schemas."""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class OperationResult(BaseModel):
    """Generic success/failure result."""

    success: bool
    message: str


class BackupResult(BaseModel):
    """Result of a file backup operation."""

    success: bool
    backup_path: str
    message: str


class FileContent(BaseModel):
    """Content of a system file."""

    path: str
    content: str


class FileUpdateRequest(BaseModel):
    """Request to update a system file."""

    content: str = Field(..., description="New file content")


# ---------------------------------------------------------------------------
# Hostname
# ---------------------------------------------------------------------------


class HostnameInfo(BaseModel):
    """Current hostname information."""

    hostname: str = Field(description="Short hostname (hostname)")
    fqdn: str = Field(description="Fully qualified domain name (hostname -f)")


class HostnameValidation(BaseModel):
    """Result of hostname validation."""

    hostname: str
    fqdn: str
    is_consistent: bool = Field(description="True if hostname and FQDN are properly configured")
    message: str


class HostnameChangeRequest(BaseModel):
    """Request to change the hostname."""

    hostname: str = Field(..., description="New hostname to set")


# ---------------------------------------------------------------------------
# /etc/resolv.conf
# ---------------------------------------------------------------------------


class NameserverInfo(BaseModel):
    """Parsed nameserver entry from /etc/resolv.conf."""

    address: str


class ResolvConfInfo(BaseModel):
    """Parsed /etc/resolv.conf information."""

    nameservers: list[NameserverInfo]
    search_domains: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    raw: str = Field("", description="Raw file content")


class NameserverUpdateRequest(BaseModel):
    """Request to update nameservers in /etc/resolv.conf."""

    nameservers: list[str] = Field(..., description="List of nameserver IP addresses")


# ---------------------------------------------------------------------------
# Ulimit
# ---------------------------------------------------------------------------

# Mapping of ulimit option flags to resource names
ULIMIT_OPTIONS: dict[str, str] = {
    "-n": "open files",
    "-u": "max user processes",
    "-v": "virtual memory",
    "-s": "stack size",
    "-c": "core file size",
}


class UlimitEntry(BaseModel):
    """A single ulimit resource entry."""

    option: str = Field(description="Ulimit flag (e.g. -n, -u)")
    resource: str = Field(description="Resource name (e.g. 'open files')")
    soft: str = Field(description="Soft limit value")
    hard: str = Field(description="Hard limit value")


class UlimitAllResponse(BaseModel):
    """All ulimit values."""

    entries: list[UlimitEntry] = Field(default_factory=list)


class UlimitSetRequest(BaseModel):
    """Request to set a ulimit value."""

    option: str = Field(..., description="Ulimit flag (-n, -u, -v, -s, -c)")
    value: str = Field(..., description="New limit value (number or 'unlimited')")


class LimitsConfEntry(BaseModel):
    """A single entry in /etc/security/limits.conf."""

    domain: str = Field(description="User, group (@group), or * for all")
    type: str = Field(description="soft or hard")
    item: str = Field(description="Resource item (e.g. nofile, nproc)")
    value: str = Field(description="Limit value")


class LimitsConfSetRequest(BaseModel):
    """Request to set max open files in /etc/security/limits.conf."""

    user: str = Field(..., description="Username or '*' for all users")
    soft: str = Field(..., description="Soft limit value (number or 'unlimited')")
    hard: str = Field(..., description="Hard limit value (number or 'unlimited')")


class LimitsConfResponse(BaseModel):
    """Response after updating /etc/security/limits.conf."""

    success: bool
    message: str
    entries: list[LimitsConfEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Host Inspection
# ---------------------------------------------------------------------------


class InspectHostname(BaseModel):
    """Hostname inspection result."""

    hostname: str = Field(description="Short hostname (hostname)")
    fqdn: str = Field(description="Fully qualified domain name (hostname -f)")
    is_consistent: bool = Field(
        description="True if hostname and FQDN match or FQDN starts with hostname"
    )


class InspectIpAddress(BaseModel):
    """IP address information."""

    interface: str = Field(description="Network interface name")
    address: str = Field(description="IPv4 or IPv6 address")


class InspectNameserver(BaseModel):
    """Nameserver entry."""

    address: str


class InspectDiskPartition(BaseModel):
    """Disk partition info."""

    device: str
    mount_point: str
    fs_type: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


class InspectResourceUsage(BaseModel):
    """CPU, memory, and disk swap resource usage."""

    cpu_cores: int
    total_memory_bytes: int
    cpu_usage_percent: float
    memory_usage_percent: float
    swap_usage_percent: float


class InspectProcess(BaseModel):
    """Process entry (ps -ef style)."""

    uid: str
    pid: int
    ppid: int
    c: str = Field(description="CPU utilization")
    stime: str = Field(description="Start time")
    tty: str
    time: str = Field(description="Cumulative CPU time")
    cmd: str


class InspectUlimitEntry(BaseModel):
    """Ulimit resource entry."""

    option: str
    resource: str
    soft: str
    hard: str


class InspectNetworkInterface(BaseModel):
    """ifconfig-style network interface info."""

    name: str
    flags: str = ""
    mtu: str = ""
    inet: str = ""
    netmask: str = ""
    broadcast: str = ""
    inet6: str = ""
    ether: str = ""
    rx_packets: str = ""
    tx_packets: str = ""
    rx_bytes: str = ""
    tx_bytes: str = ""
    raw: str = Field(description="Raw ifconfig output for this interface")


class InspectResult(BaseModel):
    """Complete host inspection result."""

    # 1. Hostname & IP addresses
    hostname: InspectHostname
    ip_addresses: list[InspectIpAddress]

    # 2. Nameservers
    nameservers: list[InspectNameserver]

    # 3. Shell environment variables (set command output)
    env_variables: str = Field(description="Output of 'set' command")

    # 4. Disk partitions
    disk_partitions: list[InspectDiskPartition]

    # 5. Resource usage (CPU, Memory, Swap)
    resource_usage: InspectResourceUsage

    # 6. Process list (ps -ef)
    processes: list[InspectProcess]

    # 7. Ulimit values
    ulimits: list[InspectUlimitEntry]

    # 8. sysctl.conf
    sysctl_conf: str = Field(description="Content of /etc/sysctl.conf")

    # 9. Network interfaces (ifconfig)
    network_interfaces: list[InspectNetworkInterface]

    # 10. Firewall status
    firewall_enabled: bool = Field(description="Whether firewall (firewalld/ufw/iptables) is active")

    # 11. uname -a
    uname: str

    # 11. /etc/passwd
    etc_passwd: str

    # 12. /etc/hosts
    etc_hosts: str
