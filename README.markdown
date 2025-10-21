# Factory Steady & Bounded Belts

This project implements two command-line tools, `factory` and `belts`, that process JSON input from stdin and produce JSON output to stdout, solving production and flow optimization problems. 

Both are designed to be deterministic and able to complete in less than 2 seconds.

## Factory Modeling Choices

### Item Balances and Conservation Equations
- **Conservation Equations**: For each item, the net flow is computed as the sum of outputs (adjusted by productivity) minus inputs, multiplied by the crafts per minute (`x_r`) for each recipe `r`. The balance is enforced as:
  - **Target Item**: Net production equals the requested rate (`b[t] = target_rate`).
  - **Intermediate Items**: Net production is zero (`b[i] = 0`), ensuring steady-state balance.
  - **Raw Items**: Net production is non-positive (`b[i] ≤ 0`), with consumption not exceeding supply caps (`|b[i]| ≤ raw_cap[i]`).
- **Implementation**: Linear programming (LP) variables `x_r` represent crafts per minute for each recipe. Constraints are added to the LP problem to enforce conservation using PuLP, ensuring exact balance within a tolerance of `1e-9`.

### Raw Consumption and Machine Capacity Constraints
- **Raw Consumption**: For raw items, the net flow constraint ensures consumption (`-net`) does not exceed the supply cap (`raw_supply_per_min[i]`). This is enforced via LP constraints: `net ≥ -raw_cap[i]`.
- **Machine Capacity**: For each machine type `m`, the number of machines used is computed as `x_r / eff_crafts_per_min(r)` for each recipe `r` on machine `m`. The sum of machines used per type is constrained to not exceed `max_machines[m]`.

### Module Application (Per-Machine-Type)
- **Speed and Productivity**: Modules apply uniformly to all recipes on a machine type. For a recipe `r` on machine `m`:
  - Effective crafts per minute: `eff_crafts_per_min(r) = machines[m].crafts_per_min * (1 + modules[m].speed) * 60 / time_s(r)`.
  - Productivity (`modules[m].prod`) multiplies only the output quantities of a recipe (`out_r[i] * (1 + prod_m)`), leaving inputs unchanged.
- **Implementation**: Speed and productivity are factored into the LP constraints for conservation and machine counts, ensuring accurate scaling of production rates.

### Handling Cycles, Byproducts, and Self-Contained Recipes
- **Cycles and Byproducts**: Cycles (e.g., A → B → A) and byproducts are handled naturally by the conservation equations. Intermediate items, including those in cycles, have `b[i] = 0`, allowing surplus or deficit to balance dynamically.
- **Self-Contained Recipes**: Recipes that produce and consume the same items are supported as long as the net balance is zero for intermediates or matches the target for the target item.
- **Implementation**: The LP formulation inherently supports cyclic dependencies by solving the system of linear equations, ensuring steady-state feasibility.

### Tie-Breaking for Machine Count
- **Objective**: The primary objective is feasibility (satisfying conservation and caps). The secondary objective minimizes total machine usage: `∑_m ∑_{r uses m} x_r / eff_crafts_per_min(r)`.
- **Tie-Breaking**: If multiple solutions exist with the same machine count, the LP solver (CBC) with a fixed random seed (`randomSeed 42`) ensures deterministic output. Recipe names are processed lexicographically in the output for consistency.

### Infeasibility Detection and Reporting
- **Approach**: A two-phase LP is used:
  1. **Phase 1**: Solve for feasibility with the target rate.
  2. **Phase 2**: If infeasible, a second LP maximizes the target rate (`target_rate`) subject to the same constraints, reporting the maximum feasible rate and bottleneck hints (tight raw supply or machine caps).
- **Why LP Relaxation**: LP relaxation is preferred over binary search for efficiency and precision, as it directly computes the maximum feasible rate in one solve, avoiding iterative searches.
- **Output**: The infeasible output includes `max_feasible_target_per_min` and `bottleneck_hint` listing tight constraints (e.g., `iron_ore supply`, `assembler_1 cap`).

## Belts Modeling Choices

### Max-Flow with Lower Bounds
- **Transformation Steps**:
  1. **Node Splitting**: For nodes with throughput caps (except sources and sink), split node `v` into `v_in` and `v_out` with an edge `v_in → v_out` capped at `node_caps[v]`.
  2. **Edge Bounds**: Each edge `(u → v)` has a flow variable with bounds `lo ≤ f ≤ hi`. No transformation for lower bounds is needed since PuLP supports lower bounds directly.
  3. **Flow Conservation**: Enforce inflow + supply = outflow + demand at each node. Sources have supply (`-actual_supplies[s]`), the sink has demand (`v`), and other nodes have zero net flow.
- **Order of Operations**:
  1. Construct the transformed graph with split nodes.
  2. Set up LP with flow variables and constraints.
  3. Solve to maximize flow `v` to the sink.
  4. Check if `v ≥ total_target` (sum of source supplies).

### Node-Splitting for Capacity Constraints
- **Method**: For each capped node `v`, redirect incoming edges to `v_in` and outgoing edges from `v_out`. Add an edge `v_in → v_out` with capacity `node_caps[v]` to enforce the throughput cap.
- **Implementation**: The `node_rep` dictionary maps original nodes to their `in` and `out` versions, and `edge_vars` includes split edges with appropriate bounds.

### Feasibility Check Strategy
- **Max-Flow**: The LP maximizes the flow `v` to the sink, with source supplies limited by `actual_supplies[s] ≤ sources[s]`. Feasibility is achieved if `v ≥ total_target - 1e-9`.
- **Direct LP**: Lower bounds are enforced directly in the LP variables (`lowBound=lo`), eliminating the need for a separate feasibility check with a super-source/sink transformation.

### Infeasibility Certificates (Min-Cut)
- **Computation**:
  - Build a residual graph using `networkx.DiGraph`.
  - Add edges `(u, v)` with capacity `hi - f` if flow `f < hi`, and reverse edges `(v, u)` with capacity `f - lo` if `f > lo`.
  - Add a super-source `S` connected to sources with remaining supply (`sources[s] - actual_supplies[s]`).
  - Perform BFS from `S` to find reachable nodes in the residual graph, forming the source side of the min-cut.
- **Reporting**:
  - **cut_reachable**: Original nodes reachable from `S` (mapped back from split nodes).
  - **deficit.demand_balance**: `total_target - achieved` flow.
  - **deficit.tight_nodes**: Capped nodes where the split edge flow equals the cap (`f ≈ node_caps[s]`).
  - **deficit.tight_edges**: Edges crossing the cut where flow equals the upper bound (`f ≈ hi`).

## Numeric Approach

### Tolerances
- **Conservation and Bounds**: All constraints (item balances, flow conservation, edge bounds, machine/node caps) are enforced within an absolute tolerance of `1e-9`.
- **Output**: Values are rounded to 4 decimal places for readability while ensuring precision within `1e-9`.

### Linear Programming Solver
- **Choice**: Both tools use PuLP with the CBC solver due to its efficiency, open-source availability, and ability to handle linear constraints (equalities and inequalities) for both problems.

### Tie-Breaking Strategy
- **Factory**: The LP minimizes total machine usage, and ties are resolved by CBC’s deterministic behavior with `randomSeed 42`. Output is sorted lexicographically by recipe/machine names.
- **Belts**: Flow assignments are deterministic due to the fixed seed. Augmenting paths are effectively tie-broken by the solver’s internal ordering, and output edges are processed in input order.

## Failure Modes & Edge Cases

### Factory
- **Cycles in Recipes**: Handled by the conservation equations, which allow cyclic dependencies to balance naturally (e.g., A → B → A with `b[i] = 0`).
- **Infeasible Raw Supplies or Machine Counts**: Detected in Phase 1 of the LP. Phase 2 computes the maximum feasible target rate and identifies tight constraints (raw supply or machine caps).
- **Degenerate/Redundant Recipes**: Supported as long as they satisfy conservation. Redundant recipes (e.g., zero crafts) are filtered out in the output if `x_r < 1e-9`.
- **Implementation**: The LP formulation is robust to degeneracy, and the solver handles numerical stability.

### Belts
- **Disconnected Graph Components**: The LP ensures only the component connected to the sink receives flow. Disconnected sources contribute zero flow, and their remaining supply appears in the residual graph for infeasibility analysis.
- **Infeasible Cases**: Detected when `v < total_target`. The min-cut analysis identifies bottlenecks (tight edges/nodes) accurately.
- **Implementation**: Node splitting and direct lower-bound constraints ensure all edge cases (e.g., zero-flow edges, fully saturated nodes) are handled correctly.

## Conclusion
The implementation uses a robust LP-based approach for both `factory` and `belts`, leveraging PuLP and CBC for efficiency and reliability. It handles all specified edge cases, enforces strict tolerances, and ensures deterministic output, meeting the performance and correctness requirements of the assignment.
