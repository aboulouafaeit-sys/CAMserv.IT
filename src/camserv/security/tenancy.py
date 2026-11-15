"""
camserv.security.tenancy
========================

Multi-tenancy isolation engine and server-side boundary enforcement for CAMserv Enterprise.
Prevents cross-tenant data leakage across organizations, sites, devices, and forensic evidence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TenantAccessDeniedError(PermissionError):
    """Raised when an identity attempts to access data outside their authorized tenant organization."""


@dataclass(slots=True)
class TenantRecord:
    """Organizational tenant partition definition."""

    tenant_id: str
    name: str
    subscription_tier: str = "ENTERPRISE"
    allowed_sites: list[str] = field(default_factory=list)
    max_cameras: int = 64
    is_active: bool = True
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class TenantContext:
    """Active identity context establishing the caller's tenant and authorization boundaries."""

    tenant_id: str
    user_id: str
    role: str
    assigned_sites: list[str] = field(default_factory=list)
    is_system_admin: bool = False


class MultiTenantEnforcer:
    """
    Server-side multi-tenancy enforcement.
    Guarantees that UI filters are never relied upon as security boundaries.
    """

    def __init__(self) -> None:
        self.tenants: dict[str, TenantRecord] = {}

    def register_tenant(self, tenant_id: str, name: str, allowed_sites: list[str] | None = None, max_cameras: int = 64) -> TenantRecord:
        """Register a new organizational tenant."""
        tenant = TenantRecord(
            tenant_id=tenant_id,
            name=name,
            allowed_sites=allowed_sites or [],
            max_cameras=max_cameras,
        )
        self.tenants[tenant_id] = tenant
        logger.info("tenancy.tenant_registered", tenant_id=tenant_id, name=name)
        return tenant

    def enforce_tenant_boundary(self, context: TenantContext, resource_tenant_id: str, resource_description: str = "resource") -> None:
        """
        Validate that the caller's tenant matches the resource's owner tenant.
        System super admins are exempted.
        """
        if context.is_system_admin or context.role.upper() == "SUPER_ADMIN":
            return

        # Check active status of caller's tenant
        tenant = self.tenants.get(context.tenant_id)
        if tenant and not tenant.is_active:
            logger.critical("tenancy.inactive_tenant_blocked", tenant_id=context.tenant_id, user_id=context.user_id)
            raise TenantAccessDeniedError(
                f"SECURITY VIOLATION: Tenant '{context.tenant_id}' is inactive or suspended. Access denied."
            )

        if context.tenant_id != resource_tenant_id:
            logger.critical(
                "tenancy.cross_tenant_access_blocked",
                caller_user=context.user_id,
                caller_tenant=context.tenant_id,
                target_tenant=resource_tenant_id,
                resource=resource_description,
            )
            raise TenantAccessDeniedError(
                f"SECURITY VIOLATION: Caller from tenant '{context.tenant_id}' cannot access "
                f"{resource_description} belonging to tenant '{resource_tenant_id}'."
            )

    def enforce_site_boundary(self, context: TenantContext, resource_site_id: str) -> None:
        """Validate that the caller is authorized for the specific physical site within the tenant."""
        if context.is_system_admin or context.role.upper() in ("SUPER_ADMIN", "TENANT_ADMIN"):
            return

        if resource_site_id not in context.assigned_sites:
            logger.warning(
                "tenancy.cross_site_access_blocked",
                caller_user=context.user_id,
                assigned_sites=context.assigned_sites,
                target_site=resource_site_id,
            )
            raise TenantAccessDeniedError(
                f"SECURITY VIOLATION: User '{context.user_id}' is not authorized to access site '{resource_site_id}'."
            )

    def filter_items_by_tenant(
        self,
        context: TenantContext,
        items: list[dict[str, Any]],
        tenant_key: str = "tenant_id",
        site_key: str = "site_id",
    ) -> list[dict[str, Any]]:
        """
        Filter a list of resource dictionaries strictly to those authorized for the caller.
        Enforces both tenant matching and site matching.
        """
        if context.is_system_admin or context.role.upper() == "SUPER_ADMIN":
            return items

        filtered = []
        for it in items:
            t_id = it.get(tenant_key)
            s_id = it.get(site_key)

            # Must match caller's tenant
            if t_id != context.tenant_id:
                continue

            # If site is specified and role is site-scoped, must match assigned sites
            if s_id and context.role.upper() not in ("SUPER_ADMIN", "TENANT_ADMIN"):
                if s_id not in context.assigned_sites:
                    continue

            filtered.append(it)
        return filtered
