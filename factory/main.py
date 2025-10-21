#!/usr/bin/env python3

import sys
import json
import pulp
from collections import defaultdict

# solver_list = pulp.listSolvers(onlyAvailable=True)
# print("ye hai tumpe ",solver_list)

data = json.load(sys.stdin)
machines = data['machines']
recipes = data['recipes']
modules = data.get('modules', {})
limits = data['limits']
target = data['target']

all_items = set()
for r in recipes:
    for i in recipes[r].get('in', {}):
        all_items.add(i)
    for i in recipes[r].get('out', {}):
        all_items.add(i)

raw_items = set(limits['raw_supply_per_min'].keys())
target_item = target['item']
intermediate_items = all_items - raw_items - {target_item}

prob = pulp.LpProblem("factorioboy", pulp.LpMinimize)
x = pulp.LpVariable.dicts("x", recipes.keys(), lowBound=0, cat='Continuous')

total_machines = pulp.lpSum(0)
machine_eff = {}
for r in recipes:
    m = recipes[r]['machine']
    speed = modules.get(m, {}).get('speed', 0)
    base = machines[m]['crafts_per_min']
    time = recipes[r]['time_s']
    eff = base * (1 + speed) * 60 / time
    machine_eff[r] = eff
    total_machines += x[r] / eff
prob += total_machines

for i in intermediate_items:
    net = pulp.lpSum(0)
    for r in recipes:
        prod = modules.get(recipes[r]['machine'], {}).get('prod', 0)
        out = recipes[r].get('out', {}).get(i, 0) * (1 + prod)
        inp = recipes[r].get('in', {}).get(i, 0)
        net += (out * x[r]) - (inp * x[r])
    prob += net == 0

for i in [target_item]:
    net = pulp.lpSum(0)
    for r in recipes:
        prod = modules.get(recipes[r]['machine'], {}).get('prod', 0)
        out = recipes[r].get('out', {}).get(i, 0) * (1 + prod)
        inp = recipes[r].get('in', {}).get(i, 0)
        net += (out * x[r]) - (inp * x[r])
    prob += net == target['rate_per_min']

for i in raw_items:
    net = pulp.lpSum(0)
    for r in recipes:
        prod = modules.get(recipes[r]['machine'], {}).get('prod', 0)
        out = recipes[r].get('out', {}).get(i, 0) * (1 + prod)
        inp = recipes[r].get('in', {}).get(i, 0)
        net += (out * x[r]) - (inp * x[r])
    prob += net <= 0
    prob += net >= -limits['raw_supply_per_min'][i]

machine_used = defaultdict(lambda: pulp.LpAffineExpression())

for r in recipes:
    m = recipes[r]['machine']
    eff = machine_eff[r]
    machine_used[m] += x[r] / eff

for m in limits.get('max_machines', {}):
    prob += machine_used[m] <= limits['max_machines'][m]

solver = pulp.HiGHS(msg=0, options=['randomSeed 42'])
status = prob.solve(solver)

if pulp.LpStatus[status] == 'Optimal':
    output = {
        "status": "ok",
        "per_recipe_crafts_per_min": {r: float(pulp.value(x[r])) for r in recipes},
        "per_machine_counts": {m: float(pulp.value(machine_used[m])) for m in machines if pulp.value(machine_used[m]) > 1e-9},
        "raw_consumption_per_min": {}
    }
    for i in raw_items:
        net = 0.0
        for r in recipes:
            prod = modules.get(recipes[r]['machine'], {}).get('prod', 0)
            out = recipes[r].get('out', {}).get(i, 0) * (1 + prod)
            inp = recipes[r].get('in', {}).get(i, 0)
            net += (out * pulp.value(x[r])) - (inp * pulp.value(x[r]))

        consumption = -net if abs(net) > 1e-9 else 0.0
        if consumption > 0:
            output["raw_consumption_per_min"][i] = consumption


else:
    prob2 = pulp.LpProblem("Max_Target", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("x", recipes.keys(), lowBound=0, cat='Continuous')
    target_rate = pulp.LpVariable("target_rate", lowBound=0)
    prob2 += target_rate

    for i in intermediate_items:
        net = pulp.lpSum(0)
        for r in recipes:
            prod = modules.get(recipes[r]['machine'], {}).get('prod', 0)
            out = recipes[r].get('out', {}).get(i, 0) * (1 + prod)
            inp = recipes[r].get('in', {}).get(i, 0)
            net += out * x[r] - (inp * x[r])
        prob2 += net == 0

    for i in [target_item]:
        net = pulp.lpSum(0)
        for r in recipes:
            prod = modules.get(recipes[r]['machine'], {}).get('prod', 0)
            out = recipes[r].get('out', {}).get(i, 0) * (1 + prod)
            inp = recipes[r].get('in', {}).get(i, 0)
            net += (out * x[r]) - inp * x[r]
        prob2 += net == target_rate

    for i in raw_items:
        net = pulp.lpSum(0)
        for r in recipes:
            prod = modules.get(recipes[r]['machine'], {}).get('prod', 0)
            out = recipes[r].get('out', {}).get(i, 0) * (1 + prod)
            inp = recipes[r].get('in', {}).get(i, 0)
            net += (out * x[r]) - (inp * x[r])
        prob2 += net <= 0, f"raw_net_{i}"
        prob2 += net >= -limits['raw_supply_per_min'][i], f"raw_cap_{i}"

    machine_used = defaultdict(lambda: pulp.LpAffineExpression())


    for r in recipes:
        m = recipes[r]['machine']
        speed = modules.get(m, {}).get('speed', 0)
        base = machines[m]['crafts_per_min']
        time = recipes[r]['time_s']
        eff = base * (1 + speed) * 60 / time
        machine_used[m] += x[r] / eff
    for m in limits.get('max_machines', {}):
        prob2 += machine_used[m] <= limits['max_machines'][m], f"max_machine_{m}"

    status = prob2.solve(solver)
    max_rate = float(pulp.value(target_rate))
    bottleneck = []
    for name, c in prob2.constraints.items():
        if abs(c.slack) < 1e-9:
            if name.startswith("raw_cap_"):
                i = name[len("raw_cap_"):]
                bottleneck.append(f"{i} supply")
            elif name.startswith("max_machine_"):
                m = name[len("max_machine_"):]
                bottleneck.append(f"{m} cap")

    output = {
        "status": "infeasible",
        "max_feasible_target_per_min": max_rate,
        "bottleneck_hint": bottleneck
    }

json.dump(output, sys.stdout, indent=4)
sys.stdout.flush()