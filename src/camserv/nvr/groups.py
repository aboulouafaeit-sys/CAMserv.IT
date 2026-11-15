"""
camserv.nvr.groups
==================

Logical camera grouping, physical location tagging, and facility hierarchy
management for the CAMserv NVR subsystem.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class CameraGroup:
    """Logical grouping of camera streams (e.g., 'Perimeter', 'Floor 1', 'Loading Bay')."""

    group_id: str
    name: str
    description: str = ""
    camera_ids: list[str] = field(default_factory=list)
    site_id: str = "default"
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize group record."""
        return asdict(self)


class CameraGroupManager:
    """In-memory coordinator and manager for camera groups and locations."""

    def __init__(self) -> None:
        self.groups: dict[str, CameraGroup] = {}

    def create_group(
        self,
        group_id: str,
        name: str,
        description: str = "",
        camera_ids: list[str] | None = None,
        site_id: str = "default",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CameraGroup:
        """Create and register a new camera group."""
        if group_id in self.groups:
            raise ValueError(f"Camera group '{group_id}' already exists.")

        group = CameraGroup(
            group_id=group_id,
            name=name,
            description=description,
            camera_ids=camera_ids or [],
            site_id=site_id,
            tags=tags or [],
            metadata=metadata or {},
        )
        self.groups[group_id] = group
        logger.info("nvr.group_created", group_id=group_id, name=name)
        return group

    def get_group(self, group_id: str) -> CameraGroup | None:
        """Retrieve group by ID."""
        return self.groups.get(group_id)

    def update_group(
        self,
        group_id: str,
        name: str | None = None,
        description: str | None = None,
        camera_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> CameraGroup:
        """Update group metadata or camera assignments."""
        group = self.groups.get(group_id)
        if not group:
            raise KeyError(f"Camera group '{group_id}' not found.")

        if name is not None:
            group.name = name
        if description is not None:
            group.description = description
        if camera_ids is not None:
            group.camera_ids = camera_ids
        if tags is not None:
            group.tags = tags

        logger.info("nvr.group_updated", group_id=group_id)
        return group

    def delete_group(self, group_id: str) -> bool:
        """Remove a camera group."""
        if group_id in self.groups:
            del self.groups[group_id]
            logger.info("nvr.group_deleted", group_id=group_id)
            return True
        return False

    def list_groups(self, site_id: str | None = None) -> list[CameraGroup]:
        """List groups, optionally filtered by site ID."""
        if site_id:
            return [g for g in self.groups.values() if g.site_id == site_id]
        return list(self.groups.values())

    def add_camera_to_group(self, group_id: str, camera_id: str) -> None:
        """Assign a camera to a group if not already present."""
        group = self.groups.get(group_id)
        if not group:
            raise KeyError(f"Camera group '{group_id}' not found.")
        if camera_id not in group.camera_ids:
            group.camera_ids.append(camera_id)

    def remove_camera_from_group(self, group_id: str, camera_id: str) -> None:
        """Remove a camera from a group."""
        group = self.groups.get(group_id)
        if group and camera_id in group.camera_ids:
            group.camera_ids.remove(camera_id)
