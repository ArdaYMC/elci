"""Need-to-know disclosure: reveal only what an agent's mandate allows."""

from __future__ import annotations

from dataclasses import dataclass, field

# Ordered from least to most revealing. Each level lists the keys it adds.
LEVELS: dict[str, dict[str, tuple[str, ...]]] = {
    "availability": {
        "none": (),
        "busy_free": ("slot", "busy"),
        "title": ("title",),
        "full": ("*",),
    },
}


@dataclass(frozen=True)
class DisclosurePolicy:
    """Maps a field family (e.g. ``availability``) to the highest level an agent may reveal."""

    allowed: dict[str, str] = field(default_factory=dict)

    def visible_keys(self, family: str) -> set[str] | None:
        """Keys visible for ``family``; None means every key (``full``)."""
        levels = LEVELS[family]
        level = self.allowed.get(family, "none")
        if level not in levels:
            raise ValueError(f"unknown level {level!r} for {family!r}")
        keys: set[str] = set()
        for name, added in levels.items():
            if "*" in added:
                return None
            keys.update(added)
            if name == level:
                break
        return keys

    def redact(self, record: dict, family: str = "availability") -> dict:
        keys = self.visible_keys(family)
        if keys is None:
            return dict(record)
        return {k: v for k, v in record.items() if k in keys}
