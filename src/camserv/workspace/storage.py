"""
camserv.workspace.storage
=========================

Secure Workspace Storage & Persistence Manager.
Implements schema-validated JSON persistence, path traversal protection,
untrusted input sanitization, safe schema migrations, and audit logging.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from camserv.workspace.models import (
    DisplayLayout,
    LayoutPreset,
    OperationalContext,
    PanelVisibility,
    ResourceProfile,
    WorkspaceConfig,
)

logger = structlog.get_logger(__name__)

# Security Bounds
MAX_WORKSPACE_FILE_BYTES = 512 * 1024  # 512 KB
WORKSPACE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
PROHIBITED_SECURITY_KEYS = {
    "password",
    "secret",
    "private_key",
    "api_token",
    "auth_token",
    "credential",
    "token",
    "master_key",
}


class WorkspaceSecurityError(ValueError):
    """Raised when workspace data violates security or validation policies."""


class WorkspaceStorageManager:
    """
    Manages persistent storage, import, export, and validation of operator workspaces.
    Enforces strict path containment, size limits, and secret sanitization.
    """

    def __init__(self, storage_dir: Path | str = "data/workspaces") -> None:
        self.storage_dir = Path(storage_dir).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _validate_workspace_id(self, workspace_id: str) -> str:
        """Validate workspace identifier to prevent path traversal and shell injection."""
        clean_id = workspace_id.strip()
        if not WORKSPACE_ID_REGEX.match(clean_id) or ".." in clean_id or "/" in clean_id or "\\" in clean_id:
            raise WorkspaceSecurityError(
                f"Invalid workspace_id: '{workspace_id}'. Must match pattern ^[a-zA-Z0-9_-]{{1,64}}$ without path traversal."
            )
        return clean_id

    def _get_workspace_path(self, workspace_id: str) -> Path:
        """Resolve safe filesystem path within the dedicated workspaces directory."""
        clean_id = self._validate_workspace_id(workspace_id)
        target_path = (self.storage_dir / f"{clean_id}.json").resolve()
        # Verify path containment
        if not target_path.is_relative_to(self.storage_dir):
            raise WorkspaceSecurityError("Path traversal violation detected.")
        return target_path

    def sanitize_untrusted_data(self, data: Any) -> Any:
        """Recursively strip any accidentally included secret or token keys."""
        if isinstance(data, dict):
            sanitized: dict[str, Any] = {}
            for k, v in data.items():
                if k.lower() in PROHIBITED_SECURITY_KEYS:
                    logger.warning("workspace.storage.prohibited_key_stripped", key=k)
                    continue
                sanitized[k] = self.sanitize_untrusted_data(v)
            return sanitized
        elif isinstance(data, list):
            return [self.sanitize_untrusted_data(item) for item in data]
        return data

    def save_workspace(self, workspace: WorkspaceConfig) -> bool:
        """Save a WorkspaceConfig model to disk as schema-compliant JSON."""
        target_path = self._get_workspace_path(workspace.workspace_id)
        raw_dict = workspace.to_dict()
        sanitized_dict = self.sanitize_untrusted_data(raw_dict)

        payload_bytes = json.dumps(sanitized_dict, indent=2, sort_keys=True).encode("utf-8")
        if len(payload_bytes) > MAX_WORKSPACE_FILE_BYTES:
            raise WorkspaceSecurityError(
                f"Workspace serialized size ({len(payload_bytes)} bytes) exceeds maximum allowed size ({MAX_WORKSPACE_FILE_BYTES} bytes)."
            )

        target_path.write_bytes(payload_bytes)
        logger.info("workspace.storage.saved", workspace_id=workspace.workspace_id, path=str(target_path))
        return True

    def get_workspace(self, workspace_id: str) -> WorkspaceConfig | None:
        """Load and deserialize a workspace configuration by identifier."""
        target_path = self._get_workspace_path(workspace_id)
        if not target_path.is_file():
            return None

        content_bytes = target_path.read_bytes()
        if len(content_bytes) > MAX_WORKSPACE_FILE_BYTES:
            raise WorkspaceSecurityError("Stored workspace file exceeds allowed size limit.")

        try:
            data = json.loads(content_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkspaceSecurityError(f"Corrupted workspace JSON in {target_path.name}: {exc}") from exc

        return WorkspaceConfig.from_dict(data)

    def load_workspace(self, workspace_id: str) -> WorkspaceConfig | None:
        """Convenience alias for get_workspace."""
        return self.get_workspace(workspace_id)

    def workspace_exists(self, workspace_id: str) -> bool:
        """Check whether a workspace exists on disk."""
        try:
            return self._get_workspace_path(workspace_id).is_file()
        except Exception:
            return False

    def list_workspaces(self) -> list[dict[str, Any]]:
        """Return an inventory of all available saved workspaces."""
        workspaces: list[dict[str, Any]] = []
        for p in sorted(self.storage_dir.glob("*.json")):
            try:
                ws = self.get_workspace(p.stem)
                if ws:
                    workspaces.append(
                        {
                            "workspace_id": ws.workspace_id,
                            "name": ws.name,
                            "operational_context": ws.operational_context.value,
                            "resource_profile": ws.resource_profile.value,
                            "display_count": len(ws.display_layouts),
                            "updated_at": ws.updated_at,
                        }
                    )
            except Exception as exc:
                logger.warning("workspace.storage.list_entry_corrupt", path=str(p), error=str(exc))
        return workspaces

    def create_workspace(
        self,
        workspace_id: str,
        name: str,
        operational_context: OperationalContext = OperationalContext.GENERAL_MONITORING,
        resource_profile: ResourceProfile = ResourceProfile.BALANCED,
        display_layouts: dict[str, DisplayLayout] | None = None,
        panels: PanelVisibility | None = None,
    ) -> WorkspaceConfig:
        """Create and persist a new workspace configuration."""
        clean_id = self._validate_workspace_id(workspace_id)
        now_str = datetime.now(timezone.utc).isoformat()

        ws = WorkspaceConfig(
            workspace_id=clean_id,
            name=name.strip() or f"Workspace {clean_id}",
            operational_context=operational_context,
            resource_profile=resource_profile,
            display_layouts=display_layouts or {},
            panels=panels or PanelVisibility(),
            version=2,
            schema_version="2.0",
            created_at=now_str,
            updated_at=now_str,
        )
        self.save_workspace(ws)
        return ws

    def rename_workspace(self, workspace_id: str, new_name: str) -> WorkspaceConfig:
        """Update workspace human-readable display name."""
        ws = self.get_workspace(workspace_id)
        if ws is None:
            raise FileNotFoundError(f"Workspace '{workspace_id}' not found.")

        ws.name = new_name.strip()
        ws.updated_at = datetime.now(timezone.utc).isoformat()
        self.save_workspace(ws)
        return ws

    def duplicate_workspace(self, source_id: str, new_id: str, new_name: str) -> WorkspaceConfig:
        """Create a clone of an existing workspace under a new identifier."""
        source = self.get_workspace(source_id)
        if source is None:
            raise FileNotFoundError(f"Source workspace '{source_id}' not found.")

        clean_new_id = self._validate_workspace_id(new_id)
        if self._get_workspace_path(clean_new_id).exists():
            raise FileExistsError(f"Target workspace '{clean_new_id}' already exists.")

        now_str = datetime.now(timezone.utc).isoformat()
        clone = WorkspaceConfig(
            workspace_id=clean_new_id,
            name=new_name.strip() or f"Copy of {source.name}",
            operational_context=source.operational_context,
            resource_profile=source.resource_profile,
            display_layouts=dict(source.display_layouts),
            panels=source.panels,
            version=source.version,
            schema_version="2.0",
            created_at=now_str,
            updated_at=now_str,
            metadata=dict(source.metadata),
        )
        self.save_workspace(clone)
        return clone

    def delete_workspace(self, workspace_id: str, confirm: bool = True) -> bool:
        """Permanently delete a workspace configuration file with explicit confirmation."""
        if not confirm:
            raise ValueError("Workspace deletion requires explicit confirmation (confirm=True).")

        target_path = self._get_workspace_path(workspace_id)
        if not target_path.is_file():
            return False

        target_path.unlink()
        logger.info("workspace.storage.deleted", workspace_id=workspace_id)
        return True

    def export_workspace_json(self, workspace_id: str) -> str:
        """Export workspace as clean, validated JSON string."""
        ws = self.get_workspace(workspace_id)
        if ws is None:
            raise FileNotFoundError(f"Workspace '{workspace_id}' not found.")
        return json.dumps(self.sanitize_untrusted_data(ws.to_dict()), indent=2, sort_keys=True)

    def export_workspace_to_json(self, workspace: WorkspaceConfig) -> str:
        """Export workspace object directly to JSON string."""
        return json.dumps(self.sanitize_untrusted_data(workspace.to_dict()), indent=2, sort_keys=True)

    def import_workspace_json(self, json_string: str, overwrite: bool = True) -> WorkspaceConfig:
        """
        Import untrusted JSON string with full defense-in-depth sanitization.
        Guards against oversized payloads, path traversal, and malicious keys.
        """
        raw_bytes = json_string.encode("utf-8")
        if len(raw_bytes) > MAX_WORKSPACE_FILE_BYTES:
            raise WorkspaceSecurityError(
                f"Import payload size ({len(raw_bytes)} bytes) exceeds maximum allowed size ({MAX_WORKSPACE_FILE_BYTES} bytes)."
            )

        try:
            raw_data = json.loads(json_string)
        except json.JSONDecodeError as exc:
            raise WorkspaceSecurityError(f"Malformed JSON payload: {exc}") from exc

        if not isinstance(raw_data, dict):
            raise WorkspaceSecurityError("Root of workspace payload must be a JSON object.")

        sanitized_data = self.sanitize_untrusted_data(raw_data)

        if "workspace_id" not in sanitized_data and "id" in sanitized_data:
            sanitized_data["workspace_id"] = sanitized_data["id"]
        if "name" not in sanitized_data and "title" in sanitized_data:
            sanitized_data["name"] = sanitized_data["title"]

        if "workspace_id" not in sanitized_data:
            raise WorkspaceSecurityError("Missing mandatory 'workspace_id' in import payload.")
        if "name" not in sanitized_data:
            raise WorkspaceSecurityError("Missing mandatory 'name' in import payload.")

        ws = WorkspaceConfig.from_dict(sanitized_data)
        target_path = self._get_workspace_path(ws.workspace_id)

        if target_path.exists() and not overwrite:
            raise FileExistsError(
                f"Workspace '{ws.workspace_id}' already exists. Pass overwrite=True to replace."
            )

        self.save_workspace(ws)
        return ws

    def import_workspace_from_json(self, json_string: str, overwrite: bool = True) -> WorkspaceConfig:
        """Convenience alias for import_workspace_json."""
        return self.import_workspace_json(json_string, overwrite=overwrite)
