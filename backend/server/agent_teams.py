"""Validation, persistence facade, and context resolution for Agent teams."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from jsonschema import SchemaError
from jsonschema.validators import validator_for

from . import db, tool_registry

BUILTIN_TEAMS_DIR = Path(__file__).resolve().parents[1] / "agent_teams"
BUILTIN_ROLES_PATH = Path(__file__).resolve().parents[1] / "agent_role_templates.json"
CONTEXT_KINDS = {"generic", "software_idea", "papers", "notes"}
APPROVAL_MODES = {"auto", "manual", "strict"}


class TeamValidationError(ValueError):
    """Raised when a team definition cannot be saved or executed."""


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def list_builtin_teams() -> List[Dict[str, Any]]:
    teams: List[Dict[str, Any]] = []
    if not BUILTIN_TEAMS_DIR.exists():
        return teams
    for path in sorted(BUILTIN_TEAMS_DIR.glob("*.json")):
        team, warnings = validate_team(_load_json(path))
        team.update({"builtin": True, "warnings": warnings})
        teams.append(team)
    return teams


def list_builtin_role_templates() -> List[Dict[str, Any]]:
    if not BUILTIN_ROLES_PATH.exists():
        return []
    values = _load_json(BUILTIN_ROLES_PATH)
    if not isinstance(values, list):
        raise TeamValidationError("built-in role templates must be an array")
    templates: List[Dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"].strip():
            raise TeamValidationError("built-in role template requires a stable id")
        template_id = value["id"].strip()
        templates.append({**validate_role_template(value), "id": template_id, "builtin": True})
    return templates


def _available_tool_names() -> set[str]:
    return {
        item.get("function", {}).get("name", "")
        for item in tool_registry.get_tools()
        if item.get("function", {}).get("name")
    }


def validate_role_template(source: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a reusable role template definition."""
    if not isinstance(source, dict):
        raise TeamValidationError("role template must be an object")
    role = copy.deepcopy(source)
    if (not isinstance(role.get("name"), str) or not role["name"].strip()
            or not isinstance(role.get("systemPrompt"), str) or not role["systemPrompt"].strip()):
        raise TeamValidationError("name and systemPrompt are required")
    tools = role.get("allowedTools", [])
    if (not isinstance(tools, list) or any(not isinstance(name, str) or not name for name in tools)
            or len(tools) != len(set(tools))):
        raise TeamValidationError("allowedTools must contain unique non-empty tool names")
    model = role.get("model")
    if model is not None and not isinstance(model, str):
        raise TeamValidationError("model must be a string or null")
    temperature = role.get("temperature")
    if temperature is not None and (isinstance(temperature, bool)
                                    or not isinstance(temperature, (int, float))
                                    or not 0 <= temperature <= 2):
        raise TeamValidationError("temperature must be between 0 and 2")
    max_tokens = role.get("maxTokens")
    if max_tokens is not None and (isinstance(max_tokens, bool)
                                   or not isinstance(max_tokens, int)
                                   or not 1 <= max_tokens <= 32768):
        raise TeamValidationError("maxTokens must be between 1 and 32768")
    output = role.get("output")
    if output is None:
        output = {"type": "text"}
    if not isinstance(output, dict) or output.get("type") not in {"text", "json_schema"}:
        raise TeamValidationError("output type must be text or json_schema")
    if output.get("type") == "json_schema":
        schema = output.get("schema")
        if not isinstance(schema, dict):
            raise TeamValidationError("JSON output requires a schema")
        try:
            validator_for(schema).check_schema(schema)
        except SchemaError as exc:
            raise TeamValidationError(f"invalid JSON Schema: {exc.message}") from exc
    for field in ("id", "builtin", "createdAt", "updatedAt"):
        role.pop(field, None)
    role.setdefault("description", "")
    role.setdefault("allowedTools", [])
    role.setdefault("model", None)
    role.setdefault("temperature", None)
    role.setdefault("maxTokens", None)
    role["output"] = output
    return role


def validate_team(source: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    if not isinstance(source, dict):
        raise TeamValidationError("team definition must be an object")
    team = copy.deepcopy(source)
    if team.get("schemaVersion") != 1:
        raise TeamValidationError("schemaVersion must be 1")
    if not isinstance(team.get("name"), str) or not team["name"].strip():
        raise TeamValidationError("team name is required")
    contexts = team.get("acceptedContexts") or []
    if (not isinstance(contexts, list) or not contexts
            or any(not isinstance(kind, str) or kind not in CONTEXT_KINDS for kind in contexts)
            or len(contexts) != len(set(contexts))):
        raise TeamValidationError("acceptedContexts contains an unsupported context kind")
    max_concurrency = team.get("maxConcurrency", 2)
    if (isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int)
            or not 1 <= max_concurrency <= 4):
        raise TeamValidationError("maxConcurrency must be an integer from 1 to 4")
    if team.get("approvalMode", "manual") not in APPROVAL_MODES:
        raise TeamValidationError("approvalMode must be auto, manual, or strict")
    nodes = team.get("nodes")
    edges = team.get("edges")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 20:
        raise TeamValidationError("a team must contain 1 to 20 nodes")
    if not isinstance(edges, list):
        raise TeamValidationError("edges must be an array")

    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise TeamValidationError("each node must be an object")
        raw_node_id = node.get("id")
        node_id = raw_node_id.strip() if isinstance(raw_node_id, str) else ""
        if not node_id or node_id in node_ids:
            raise TeamValidationError("node ids must be non-empty and unique")
        node["id"] = node_id
        node_ids.add(node_id)
        if (not isinstance(node.get("name"), str) or not node["name"].strip()
                or not isinstance(node.get("systemPrompt"), str)
                or not node["systemPrompt"].strip()):
            raise TeamValidationError(f"node {node_id} requires name and systemPrompt")
        tools = node.get("allowedTools", [])
        if (not isinstance(tools, list)
                or any(not isinstance(name, str) or not name for name in tools)
                or len(tools) != len(set(tools))):
            raise TeamValidationError(f"node {node_id} allowedTools must contain unique tool names")
        model = node.get("model")
        if model is not None and not isinstance(model, str):
            raise TeamValidationError(f"node {node_id} model must be a string or null")
        position = node.get("position")
        if (not isinstance(position, dict)
                or isinstance(position.get("x"), bool)
                or isinstance(position.get("y"), bool)
                or not isinstance(position.get("x"), (int, float))
                or not isinstance(position.get("y"), (int, float))):
            raise TeamValidationError(f"node {node_id} requires a numeric canvas position")
        temperature = node.get("temperature")
        if temperature is not None and (isinstance(temperature, bool)
                                        or not isinstance(temperature, (int, float))
                                        or not 0 <= temperature <= 2):
            raise TeamValidationError(f"node {node_id} temperature must be between 0 and 2")
        max_tokens = node.get("maxTokens")
        if max_tokens is not None and (isinstance(max_tokens, bool)
                                       or not isinstance(max_tokens, int)
                                       or not 1 <= max_tokens <= 32768):
            raise TeamValidationError(f"node {node_id} maxTokens must be between 1 and 32768")
        output = node.get("output")
        if output is None:
            output = {"type": "text"}
        if not isinstance(output, dict) or output.get("type") not in {"text", "json_schema"}:
            raise TeamValidationError(f"node {node_id} has an unsupported output type")
        if output.get("type") == "json_schema":
            schema = output.get("schema")
            if not isinstance(schema, dict):
                raise TeamValidationError(f"node {node_id} requires a JSON Schema")
            try:
                validator_for(schema).check_schema(schema)
            except SchemaError as exc:
                raise TeamValidationError(f"node {node_id} has an invalid JSON Schema: {exc.message}") from exc

    raw_output_id = team.get("outputNodeId")
    output_id = raw_output_id.strip() if isinstance(raw_output_id, str) else ""
    if not output_id:
        raise TeamValidationError("outputNodeId must identify an existing node")
    team["outputNodeId"] = output_id
    if output_id not in node_ids:
        raise TeamValidationError("outputNodeId must identify an existing node")
    edge_ids: set[str] = set()
    edge_pairs: set[str] = set()
    successors = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise TeamValidationError("each edge must be an object")
        raw_source, raw_target = edge.get("source"), edge.get("target")
        if not isinstance(raw_source, str) or not isinstance(raw_target, str):
            raise TeamValidationError(f"edge {index} references a missing node")
        source, target = raw_source.strip(), raw_target.strip()
        raw_edge_id = edge.get("id")
        if raw_edge_id is not None and not isinstance(raw_edge_id, str):
            raise TeamValidationError("edge ids must be non-empty and unique")
        edge_id = (raw_edge_id or f"{source}->{target}").strip()
        if source not in node_ids or target not in node_ids:
            raise TeamValidationError(f"edge {index} references a missing node")
        if source == target:
            raise TeamValidationError("self edges are not allowed")
        if not edge_id or edge_id in edge_ids:
            raise TeamValidationError("edge ids must be non-empty and unique")
        pair = f"{source}\0{target}"
        if pair in edge_pairs:
            raise TeamValidationError("duplicate edges are not allowed")
        edge_ids.add(edge_id)
        edge_pairs.add(pair)
        edge.update({"id": edge_id, "source": source, "target": target})
        successors[source].append(target)
        indegree[target] += 1

    queue = [node_id for node_id in node_ids if indegree[node_id] == 0]
    visited: List[str] = []
    while queue:
        current = queue.pop(0)
        visited.append(current)
        for target in successors[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(visited) != len(nodes):
        raise TeamValidationError("team graph must be acyclic")

    memo: Dict[str, bool] = {}
    def reaches_output(node_id: str) -> bool:
        if node_id == output_id:
            return True
        if node_id not in memo:
            memo[node_id] = any(reaches_output(target) for target in successors[node_id])
        return memo[node_id]
    unreachable = [node_id for node_id in node_ids if not reaches_output(node_id)]
    if unreachable:
        raise TeamValidationError(
            "every node must reach outputNodeId; disconnected: " + ", ".join(sorted(unreachable)))

    team.setdefault("description", "")
    team.setdefault("category", "custom")
    team.setdefault("maxConcurrency", 2)
    team.setdefault("approvalMode", "manual")
    available = _available_tool_names()
    missing = sorted({name for node in nodes for name in node.get("allowedTools", []) if name not in available})
    warnings = [f"tool is not installed and will be ignored: {name}" for name in missing]
    return team, warnings


async def list_teams(space_id: str) -> List[Dict[str, Any]]:
    return list_builtin_teams() + await db.database.list_agent_teams(space_id)


async def resolve_team(team_id: str, space_id: str) -> Optional[Dict[str, Any]]:
    if team_id.startswith("builtin-"):
        return next((team for team in list_builtin_teams() if team["id"] == team_id), None)
    return await db.database.get_agent_team(team_id, space_id)


async def unique_team_name(name: str, space_id: str) -> str:
    names = {team["name"] for team in await list_teams(space_id)}
    if name not in names:
        return name
    base = f"{name} 副本"
    candidate, index = base, 2
    while candidate in names:
        candidate = f"{base} {index}"
        index += 1
    return candidate


async def clone_team(team: Dict[str, Any], space_id: str) -> Dict[str, Any]:
    clone = copy.deepcopy(team)
    clone.pop("id", None)
    clone.pop("builtin", None)
    clone.pop("warnings", None)
    clone["name"] = await unique_team_name(team["name"], space_id)
    validated, _ = validate_team(clone)
    return await db.database.create_agent_team(validated, space_id)


async def resolve_input_context(context: Optional[Dict[str, Any]], space_id: str) -> Dict[str, Any]:
    if context is None:
        context = {"kind": "generic", "entityIds": [], "variables": {}}
    elif not isinstance(context, dict):
        raise TeamValidationError("context must be an object")
    else:
        context = copy.deepcopy(context)
    kind = context.get("kind", "generic")
    if not isinstance(kind, str) or kind not in CONTEXT_KINDS:
        raise TeamValidationError("unsupported context kind")
    entity_ids = context.get("entityIds") or []
    if not isinstance(entity_ids, list) or len(entity_ids) > 20:
        raise TeamValidationError("context accepts at most 20 entity ids")
    variables = context.get("variables") or {}
    if not isinstance(variables, dict):
        raise TeamValidationError("context variables must be an object")
    if len(json.dumps(variables, ensure_ascii=False).encode("utf-8")) > 256 * 1024:
        raise TeamValidationError("context variables exceed 256 KB")

    entities: List[Dict[str, Any]] = []
    if kind == "papers":
        for entity_id in entity_ids:
            paper = await db.database.get_paper_by_id(str(entity_id), space_id)
            if paper:
                entities.append({key: paper.get(key) for key in
                    ("id", "title", "authors", "abstract", "arxivId", "categories", "summary")})
    elif kind == "notes":
        for entity_id in entity_ids:
            note = await db.database.get_note_by_id(str(entity_id), space_id)
            if note:
                entities.append({key: note.get(key) for key in
                    ("id", "title", "content", "tags", "noteType", "aiGenerated")})
    if kind in {"papers", "notes"} and len(entities) != len(entity_ids):
        raise TeamValidationError("one or more context entities do not exist in this space")
    return {"kind": kind, "entityIds": entity_ids, "variables": variables, "entities": entities}


def build_node_input(requirement: str, context: Dict[str, Any], node: Dict[str, Any],
                     predecessors: Iterable[Tuple[Dict[str, Any], Dict[str, Any]]]) -> str:
    sections = [f"## Original goal\n{requirement}",
                "## Trusted workspace context\n" + json.dumps(context, ensure_ascii=False, indent=2)]
    predecessor_list = list(predecessors)
    if predecessor_list:
        sections.append("## Direct predecessor outputs")
        for spec, result in predecessor_list:
            value = result.get("structured") if result.get("structured") is not None else result.get("text", "")
            sections.append(f"### {spec.get('name', spec['id'])} [{spec['id']}]\n" +
                            (json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value))
    sections.append(f"## Your assignment\n{node.get('description', '')}")
    return "\n\n".join(sections)


def list_tool_capabilities() -> List[Dict[str, Any]]:
    specs = {spec.name: spec for spec in tool_registry.list_specs()}
    result = []
    for item in tool_registry.get_tools():
        function = item["function"]
        spec = specs.get(function["name"])
        result.append({"name": function["name"], "description": function.get("description", ""),
                       "source": spec.source if spec else "skill",
                       "policy": spec.policy if spec else "safe"})
    return sorted(result, key=lambda value: value["name"])


__all__ = ["TeamValidationError", "build_node_input", "clone_team", "list_builtin_role_templates",
           "list_teams", "list_tool_capabilities", "resolve_input_context", "resolve_team",
           "unique_team_name", "validate_role_template", "validate_team"]
