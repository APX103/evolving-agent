"""
Mermaid diagram generator for Graph visualization.
"""
from agent.workflow.graph import Graph, Edge, Node


def generate_mermaid(graph: Graph, direction: str = "TD") -> str:
    """
    Generate a Mermaid flowchart string from a Graph.

    Args:
        graph: The Graph to visualize.
        direction: Mermaid direction (TD, LR, BT, RL).

    Returns:
        Mermaid syntax string.
    """
    lines = [f"flowchart {direction}"]

    # Subgraph wrapper if this graph has a name
    if graph.name and graph.name != "graph":
        lines.append(f"    subgraph {graph.name}")
        indent = "        "
    else:
        indent = "    "

    # Nodes
    for name, node in graph.nodes.items():
        label = name
        if node.subgraph is not None:
            label = f"{name} [subgraph]"
        if node.retry_count > 0:
            label = f"{label} (retry:{node.retry_count})"
        if node.timeout is not None:
            label = f"{label} (timeout:{node.timeout}s)"
        lines.append(f'{indent}{name}["{label}"]')

    # Edges
    for edge in graph.edges:
        cond = ""
        if edge.condition is not None:
            cond = f'|"condition"|'
        lines.append(f"{indent}{edge.source} -->{cond} {edge.target}")

    if graph.name and graph.name != "graph":
        lines.append("    end")

    return "\n".join(lines)
