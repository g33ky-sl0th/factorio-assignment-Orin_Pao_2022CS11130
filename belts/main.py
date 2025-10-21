#!/usr/bin/env python3

import sys
import json
import pulp
import networkx as nx
from collections import defaultdict, deque

data = json.load(sys.stdin)
edges = data['edges']
node_caps = data.get('node_caps', {})
sources = data['sources']
sink = data['sink']
total_target = sum(sources.values())

all_original_nodes = set(sources.keys()) | {sink} | {e['from'] for e in edges} | {e['to'] for e in edges}

split_nodes = set(node_caps.keys()) & (all_original_nodes - set(sources.keys()) - {sink})

node_rep = {}
for n in all_original_nodes:
    if n in split_nodes:
        node_rep[n] = {'in': n + '_in', 'out': n + '_out'}
    else:
        node_rep[n] = {'in': n, 'out': n}

all_nodes = {node_rep[n]['in'] for n in all_original_nodes} | {node_rep[n]['out'] for n in all_original_nodes}

prob = pulp.LpProblem("Belts", pulp.LpMaximize)

v = pulp.LpVariable("v", lowBound=0)
prob += v

actual_supplies = {}
for s in sources:
    actual_supplies[s] = pulp.LpVariable(f"actual_{s}", lowBound=0, upBound=sources[s])

edge_vars = {}
edge_info = {}

for e in edges:
    u = e['from']
    v = e['to']
    lo = e['lo']
    hi = e['hi']
    af = node_rep[u]['out']
    at = node_rep[v]['in']
    var = pulp.LpVariable(f"f_{u}_{v}", lowBound=lo, upBound=hi)
    edge_vars[(af, at)] = var
    edge_info[(af, at)] = {'lo': lo, 'hi': hi, 'orig_from': u, 'orig_to': v}

split_flow_vars = {}
for s in split_nodes:
    u = node_rep[s]['in']
    v = node_rep[s]['out']
    lo = 0
    hi = node_caps[s]
    var = pulp.LpVariable(f"f_split_{s}", lowBound=lo, upBound=hi)
    edge_vars[(u, v)] = var
    edge_info[(u, v)] = {'lo': lo, 'hi': hi, 'orig_from': None, 'orig_to': None}
    split_flow_vars[s] = var

in_edges = defaultdict(list)
out_edges = defaultdict(list)
for (u, v) in edge_vars:
    out_edges[u].append((u, v))
    in_edges[v].append((u, v))

for n in all_nodes:
    net = pulp.lpSum(edge_vars[e] for e in in_edges[n]) - pulp.lpSum(edge_vars[e] for e in out_edges[n])
    if n in sources:
        prob += net == -actual_supplies[n]
    elif n == sink:
        prob += net == v
    else:
        prob += net == 0

solver = pulp.PULP_CBC_CMD(msg=0, options=['randomSeed 42'])
status = prob.solve(solver)

achieved = pulp.value(v) if pulp.LpStatus[status] == 'Optimal' else 0

if achieved >= total_target - 1e-9:
    output = {
        "status": "ok",
        "max_flow_per_min": round(total_target, 4),
        "flows": []
    }
    for e in edges:
        u = e['from']
        v = e['to']
        flow = pulp.value(edge_vars[(node_rep[u]['out'], node_rep[v]['in'])])
        if abs(flow) > 1e-9:  # Only include non-zero flows
            output["flows"].append({"from": u, "to": v, "flow": round(float(flow), 4)})
else:
    G_res = nx.DiGraph()
    for n in all_nodes:
        G_res.add_node(n)
    for (u, v), info in edge_info.items():
        f = pulp.value(edge_vars[(u, v)])
        if f < info['hi'] - 1e-9:
            G_res.add_edge(u, v, cap=info['hi'] - f)
        if f > info['lo'] + 1e-9:
            G_res.add_edge(v, u, cap=f - info['lo'])
    G_res.add_node('S')
    for s in sources:
        remaining = sources[s] - pulp.value(actual_supplies[s])
        if remaining > 1e-9:
            G_res.add_edge('S', s, cap=remaining)

    reachable = set()
    queue = deque(['S'])
    while queue:
        u = queue.popleft()
        if u in reachable:
            continue
        reachable.add(u)
        for v in G_res.neighbors(u):
            if G_res[u][v]['cap'] > 1e-9 and v not in reachable:
                queue.append(v)

    cut_original = set()
    for r in reachable - {'S'}:
        if r.endswith('_in'):
            orig = r[:-3]
        elif r.endswith('_out'):
            orig = r[:-4]
        else:
            orig = r
        cut_original.add(orig)
    cut_reachable = sorted(list(cut_original))

    tight_nodes = []
    for s in split_nodes:
        v_in = node_rep[s]['in']
        v_out = node_rep[s]['out']
        if v_in in reachable and v_out not in reachable:
            f = pulp.value(split_flow_vars[s])
            if abs(f - node_caps[s]) < 1e-9:
                tight_nodes.append(s)
    tight_nodes = sorted(tight_nodes)

    tight_edges = []
    for (u, v), info in edge_info.items():
        if info['orig_from'] is None:
            continue
        if u in reachable and v not in reachable:
            f = pulp.value(edge_vars[(u, v)])
            if abs(f - info['hi']) < 1e-9:
                tight_edges.append({
                    "from": info['orig_from'],
                    "to": info['orig_to'],
                    "flow_needed": round(float(total_target - achieved), 4)
                })

    deficit_dict = {
        "demand_balance": round(float(total_target - achieved), 4),
        "tight_nodes": tight_nodes,
        "tight_edges": tight_edges
    }
    output = {
        "status": "infeasible",
        "cut_reachable": cut_reachable,
        "deficit": deficit_dict
    }

json.dump(output, sys.stdout, indent=4)
sys.stdout.flush()