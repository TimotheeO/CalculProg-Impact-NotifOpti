import sys
from src.data_loader import load_event_graph
from src.impact import compute_impacted_set

def main():
    if len(sys.argv) != 2:
        print("Usage : python3 demo.py <id_atelier>")
        print("Exemples disponibles : w1 (Cuisine), w3 (Poterie)")
        sys.exit(1)

    workshop_id = sys.argv[1]
    graph = load_event_graph("data/sample_event.json")

    if workshop_id not in graph.workshops:
        print(f"Atelier inconnu : {workshop_id}")
        print(f"Ateliers disponibles : {', '.join(graph.workshops.keys())}")
        sys.exit(1)

    workshop_name = graph.workshops[workshop_id].name
    result = compute_impacted_set(graph, workshop_id)

    print("=" * 50)
    print(f"CHANGEMENT SUR : {workshop_name} ({workshop_id})")
    print("=" * 50)

    print(f"\nAteliers impactés en cascade ({len(result.impacted_workshop_ids)}) :")
    for w_id in sorted(result.impacted_workshop_ids):
        marker = "  <- point de départ" if w_id == workshop_id else "  <- impacté en cascade"
        print(f"  - {graph.workshops[w_id].name} ({w_id}){marker}")

    print(f"\nParticipants à notifier ({len(result.impacted_participant_ids)}) :")
    for p_id in sorted(result.impacted_participant_ids):
        print(f"  - {graph.participants[p_id].name}")

    not_notified = set(graph.participants.keys()) - result.impacted_participant_ids
    print(f"\nParticipants NON notifiés, à raison ({len(not_notified)}) :")
    for p_id in sorted(not_notified):
        print(f"  - {graph.participants[p_id].name}")

    print()

if __name__ == "__main__":
    main()