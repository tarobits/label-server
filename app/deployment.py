"""Native installs have one immutable server role; shared checkouts can develop either."""

from pathlib import Path


def require_role(role: str, root: Path | None = None) -> None:
    marker = (root or Path(__file__).resolve().parent.parent) / ".label-server-role"
    if marker.is_symlink() or (marker.exists() and marker.read_text().strip() != role):
        raise RuntimeError(f"This installation is not a {role} server")
