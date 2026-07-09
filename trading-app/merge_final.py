import sys, json
from pathlib import Path

ast = json.loads(Path('graphify-out/.graphify_ast.json').read_text(encoding="utf-8"))
sem = json.loads(Path('graphify-out/.graphify_semantic.json').read_text(encoding="utf-8"))

# Merge: AST nodes first, semantic nodes deduplicated by id
seen = {n['id'] for n in ast['nodes']}
merged_nodes = list(ast['nodes'])
for n in sem.get('nodes', []):
    if n['id'] not in seen:
        seen.add(n['id'])
        merged_nodes.append(n)

# Edges: all AST edges + all semantic edges
merged_edges = ast['edges'] + sem.get('edges', [])
merged_hyperedges = ast.get('hyperedges', []) + sem.get('hyperedges', [])

merged = {
    'nodes': merged_nodes,
    'edges': merged_edges,
    'hyperedges': merged_hyperedges
}

Path('graph.json').write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
print(f'Final graph: {len(merged_nodes)} nodes, {len(merged_edges)} edges')
