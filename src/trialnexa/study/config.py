"""Study YAML construction and safe serialization/parsing."""

from pathlib import Path
from typing import Any

import yaml

from trialnexa.study import StudyError
from trialnexa.study.layout import STUDY_PATHS, check_path


class _StudyLoader(yaml.SafeLoader):
    """Reject duplicate keys and aliases instead of silently accepting ambiguity."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.YAMLError(f"YAML aliases are unsupported at {event.start_mark}")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[str, Any]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.YAMLError("Expected a YAML mapping")
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise yaml.YAMLError("YAML mapping keys must be unique strings")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def make_config(study_id: str, versions: dict[str, str]) -> dict[str, Any]:
    """Build the issue's schema using YAML strings and meaningful booleans."""
    return {
        "study_id": study_id,
        "standards": versions,
        "paths": {
            group: {name: f"./{group}/{name}" for name in names}
            for group, names in STUDY_PATHS.items()
        },
        "validation": {
            "offline": True,
            "rule_engine": "cdisc_core",
            "custom_rules": True,
        },
        "reference": {"root": "../../cdisc_reference", "verify_checksums": True},
    }


def serialize_config(config: dict[str, Any]) -> str:
    """Return deterministic UTF-8-compatible YAML with preserved string types."""
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


def read_config(path: Path) -> dict[str, Any]:
    """Parse one small configuration without executing tags or exposing content."""
    check_path(path, directory=False)
    try:
        with path.open("rb") as stream:
            contents = stream.read(1_048_577)
        if len(contents) > 1_048_576:
            raise StudyError(f"Configuration exceeds the 1 MiB limit: {path}")
        config = yaml.load(contents.decode("utf-8-sig"), Loader=_StudyLoader)
    except (yaml.YAMLError, ValueError, OverflowError, RecursionError) as exc:
        # YAML parser exceptions may contain entire input lines; do not print
        # them, since user-edited configuration may include sensitive text.
        raise StudyError(
            f"Invalid YAML in {path}; use UTF-8, unique string keys, no aliases, "
            "and standard YAML types."
        ) from exc
    if not isinstance(config, dict):
        raise StudyError(f"study.yaml must contain a YAML mapping: {path}")
    return config
