from typing import TypedDict, List, Any


class Route(TypedDict):
    rule_set: List[dict[str, Any]]
    rules: List[dict[str, Any]]
    final: str
    auto_detect_interface: bool
