import json
from pathlib import Path

from src.graph import EventGraph


def load_event_graph(json_path: str | Path) -> EventGraph:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    graph = EventGraph()

    for p in data.get("participants", []):
        graph.add_participant(p["id"], p["name"])

    for w in data.get("workshops", []):
        graph.add_workshop(w["id"], w["name"])

    for e in data.get("enrollments", []):
        graph.enroll(e["participant_id"], e["workshop_id"])

    for d in data.get("dependencies", []):
        graph.add_dependency(d["base_workshop_id"], d["dependent_workshop_id"])

    return graph
