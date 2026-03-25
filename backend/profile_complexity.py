"""
Performance profiling harness for the QueryScope optimization engine.
Evaluates pass throughput across scaling query complexities (measured by JOIN depth)
to identify algorithmic bottlenecks in the logical plan transformation pipeline.
"""

from optimizer import optimize


def generate_complex_query(num_joins: int) -> str:
    """
    Generates a synthetic SQL query with a specified number of nested JOINs
    and a mix of predicates/arithmetic to trigger all optimization passes.
    """
    selects = "t0.id"
    joins = "FROM t0 "
    
    for i in range(1, num_joins + 1):
        joins += f"JOIN t{i} ON t{i-1}.id = t{i}.id "
        selects += f", t{i}.val "
        
    # Includes static arithmetic for Constant Folding 
    # and a single-table predicate for Pushdown
    where_clause = "WHERE t0.id > 100 + 50 * 2 AND t0.status = 'ACTIVE'"
    
    return f"SELECT {selects} {joins} {where_clause}"


def run_complexity_sweep():
    """
    Executes a scaling complexity sweep, recording AST node volumes, 
    total execution latency, and isolating the bottleneck pass per tier.
    """
    print("Starting QueryScope Complexity Sweep...")
    print("=" * 80)
    print(f"{'JOIN Depth':<12} | {'Initial Nodes':<15} | {'Total Time (ms)':<18} | {'Bottleneck Pass'}")
    print("-" * 80)
    
    # Sweep through progressively larger query structures
    complexity_levels = [1, 5, 10, 20, 50]
    
    for joins in complexity_levels:
        sql = generate_complex_query(joins)
        
        try:
            result = optimize(sql)
        except Exception as e:
            print(f"Error optimizing query at depth {joins}: {e}")
            continue
            
        # Isolate the pass that consumed the most time
        bottleneck_rule = max(result.pass_times, key=result.pass_times.get)
        bottleneck_time = result.pass_times[bottleneck_rule]
        
        print(
            f"{joins:<12} | "
            f"{result.original_node_count:<15} | "
            f"{result.elapsed_ms:<18.3f} | "
            f"{bottleneck_rule} ({bottleneck_time:.3f} ms)"
        )
        
    print("=" * 80)
    print("Profiling complete.")


if __name__ == "__main__":
    run_complexity_sweep()