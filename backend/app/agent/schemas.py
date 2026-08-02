# SPDX-License-Identifier: Apache-2.0
"""에이전트 하트비트 스키마."""

from pydantic import BaseModel, Field


class HeartbeatRequest(BaseModel):
    """에이전트가 주기적으로 보내는 하트비트 페이로드."""

    hostname: str = Field(..., description="Agent hostname")
    ip_address: str = Field(..., description="Agent IP address")
    version: str | None = Field(None, description="Agent software version")
    kernel_version: str | None = Field(None, description="OS kernel version")
    os_version: str | None = Field(None, description="OS distribution and version")
    arch: str | None = Field(None, description="CPU architecture (amd64|arm64)")
    cpu_count: int | None = Field(None, description="Logical CPU count")
    core_count: int | None = Field(None, description="Physical core count")
    total_memory: int | None = Field(None, description="Total memory in bytes")
    cpu_usage: float | None = Field(None, description="Total CPU usage percentage")
    memory_usage: float | None = Field(None, description="Total memory usage percentage")
    disk_swap_percent: float | None = Field(None, description="Disk swap usage percentage")
    gpu_count: int | None = Field(None, description="NVIDIA GPU count (0/None if no GPU)")
    gpu_usage: float | None = Field(None, description="Average GPU utilization percentage")
    gpu_memory_usage: float | None = Field(None, description="Average GPU memory occupancy %")
    gpu_memory_total: int | None = Field(None, description="Total VRAM across GPUs in MiB (discrete)")
    gpu_name: str | None = Field(None, description="First GPU model name")
