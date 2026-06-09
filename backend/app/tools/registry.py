"""Tool registry.

A flat catalog of ToolSpecs. Lookups happen two ways: by exact name (when a
plan step or action names the tool) and by capability (when the selector has to
choose among a capability's tools).
"""

from app.tools.schemas import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._by_name:
            raise ValueError(f"tool already registered: {tool.name}")
        self._by_name[tool.name] = tool

    def get(self, name: str) -> ToolSpec | None:
        return self._by_name.get(name)

    def by_capability(self, capability: str) -> list[ToolSpec]:
        return [t for t in self._by_name.values() if t.capability == capability]

    def names(self) -> list[str]:
        return list(self._by_name)

    def all(self) -> list[ToolSpec]:
        return list(self._by_name.values())


def render_tool_catalog(tools: list[ToolSpec]) -> str:
    """Render tools for an agent's system prompt INCLUDING their argument schema.

    Listing only name + description forces the model to guess argument names
    (it would send "text" or "message" when a tool needs "body"). Showing the
    exact fields, types, and which are required makes tool calls far more
    reliable, especially for smaller local models.
    """
    lines: list[str] = []
    for t in tools:
        args: list[str] = []
        for fname, field in t.args_schema.model_fields.items():
            if fname == "action":  # internal discriminator, not model-facing
                continue
            req = "required" if field.is_required() else "optional"
            args.append(f"{fname} ({_type_name(field.annotation)}, {req})")
        hint = ", ".join(args) if args else "no arguments"
        lines.append(f"- {t.name}: {t.description}\n    args: {hint}")
    return "\n".join(lines)


def _type_name(annotation) -> str:
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return str(annotation).replace("typing.", "").replace("NoneType", "None")
