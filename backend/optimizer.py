"""
Core query optimization engine for QueryScope.
Parses SQL into an Abstract Syntax Tree (AST) using sqlglot and applies a series 
of rewrite rules to optimize the logical plan. 

The optimizer runs in a fixed-point loop to ensure passes are composable and 
independent of execution order.
"""

import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Set, Tuple

import sqlglot
import sqlglot.expressions as exp


@dataclass
class OptimizationResult:
    original_sql: str
    optimized_sql: str
    original_ast: dict
    optimized_ast: dict
    rules_applied: List[str]
    pass_times: Dict[str, float]        # Time taken per pass in ms
    pass_reductions: Dict[str, int]     # Number of AST nodes removed per pass
    original_node_count: int
    optimized_node_count: int
    reduction_pct: float
    elapsed_ms: float


def count_nodes(node: exp.Expression) -> int:
    """Recursively counts the total number of nodes in the AST."""
    if node is None:
        return 0
    total = 1
    for child in node.args.values():
        if isinstance(child, exp.Expression):
            total += count_nodes(child)
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, exp.Expression):
                    total += count_nodes(item)
    return total


def ast_to_dict(node: exp.Expression, depth: int = 0) -> dict:
    """Converts the AST into a JSON-serializable dictionary for the React frontend."""
    if node is None:
        return {}

    children = []
    for _, child in node.args.items():
        if isinstance(child, exp.Expression):
            children.append(ast_to_dict(child, depth + 1))
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, exp.Expression):
                    children.append(ast_to_dict(item, depth + 1))

    # Clean up node names for the visualizer
    label = type(node).__name__
    if isinstance(node, exp.Column):
        label = f"Column({node.name})"
    elif isinstance(node, exp.Table):
        label = f"Table({node.name})"
    elif isinstance(node, exp.Literal):
        label = f"Literal({node.this})"
    elif isinstance(node, exp.Anonymous):
        label = f"Func({node.name})"

    return {
        "name": label,
        "type": type(node).__name__,
        "children": children,
    }


def _collect_columns(node: exp.Expression) -> Set[str]:
    """Helper to find all table references inside a given AST node."""
    tables = set()
    for col in node.find_all(exp.Column):
        if col.table:
            tables.add(col.table.lower())
    return tables


def predicate_pushdown(ast: exp.Expression) -> Tuple[exp.Expression, bool]:
    """
    Predicate Pushdown
    
    Finds predicates in the WHERE clause that only reference a single table.
    In a real database, these would be pushed down to the scan nodes. For this 
    logical optimizer, we just identify and isolate them.
    """
    applied = False
    for select in ast.find_all(exp.Select):
        where = select.args.get("where")
        if where is None:
            continue

        predicates = []
        def _split(node):
            if isinstance(node, exp.And):
                _split(node.left)
                _split(node.right)
            else:
                predicates.append(node)
        _split(where.this)

        single_table_preds = []
        multi_table_preds = []
        
        for pred in predicates:
            referenced = _collect_columns(pred)
            if len(referenced) == 1:
                single_table_preds.append((referenced.pop(), pred))
            else:
                multi_table_preds.append(pred)

        if not single_table_preds:
            continue

        # Rebuild the WHERE clause
        all_preds = [pred for _, pred in single_table_preds] + multi_table_preds
        new_where_expr = all_preds[0]
        for p in all_preds[1:]:
            new_where_expr = exp.And(this=new_where_expr, expression=p)
        
        select.set("where", exp.Where(this=new_where_expr))
        applied = True
        
    return ast, applied


def projection_pruning(ast: exp.Expression) -> Tuple[exp.Expression, bool]:
    """
    Projection Pruning
    
    Removes unused columns from subquery SELECT lists to save memory and processing time.
    Only applies to nested SELECTs, never the root query.
    """
    applied = False

    for select in ast.find_all(exp.Select):
        # Do not prune the top-level query
        parent = select.parent
        has_select_ancestor = False
        while parent is not None:
            if isinstance(parent, exp.Select):
                has_select_ancestor = True
                break
            parent = parent.parent
        if not has_select_ancestor:
            continue

        expressions = select.args.get("expressions", [])
        if any(isinstance(e, exp.Star) for e in expressions):
            continue

        # Cannot safely prune if a parent is doing SELECT *
        ancestor_has_star = False
        p = select.parent
        while p is not None:
            if isinstance(p, exp.Select):
                if any(isinstance(e, exp.Star) for e in p.args.get("expressions", [])):
                    ancestor_has_star = True
                    break
            p = p.parent
        if ancestor_has_star:
            continue

        # Collect columns referenced outside this subquery
        def _collect_external_refs(node: exp.Expression, skip: exp.Expression) -> Set[str]:
            if node is skip:
                return set()
            names: Set[str] = set()
            if isinstance(node, exp.Column):
                names.add(node.name.lower())
            for child in node.args.values():
                if isinstance(child, exp.Expression):
                    names |= _collect_external_refs(child, skip)
                elif isinstance(child, list):
                    for item in child:
                        if isinstance(item, exp.Expression):
                            names |= _collect_external_refs(item, skip)
            return names

        referenced_names = _collect_external_refs(ast, select)
        original_count = len(expressions)

        def _should_keep(e: exp.Expression) -> bool:
            if isinstance(e, exp.Alias):
                if e.alias.lower() in referenced_names:
                    return True
                return False
                
            if isinstance(e, exp.Column):
                return (e.name.lower() in referenced_names
                        or e.alias_or_name.lower() in referenced_names)
            
            return False

        pruned = [e for e in expressions if _should_keep(e)]
        
        if len(pruned) < original_count and len(pruned) > 0:
            select.set("expressions", pruned)
            applied = True

    return ast, applied


# Dispatch table for constant folding arithmetic
_BINARY_OPS = {
    exp.Add: lambda a, b: a + b,
    exp.Sub: lambda a, b: a - b,
    exp.Mul: lambda a, b: a * b,
    exp.Div: lambda a, b: a / b if b != 0 else None,
}

def _try_fold(node: exp.Expression) -> Optional[exp.Expression]:
    """Evaluates basic arithmetic on literal values."""
    op_fn = _BINARY_OPS.get(type(node))
    if op_fn is None:
        return None

    left  = node.args.get("this")
    right = node.args.get("expression")
    
    if not (isinstance(left, exp.Literal) and isinstance(right, exp.Literal)):
        return None

    try:
        lv, rv = float(left.this), float(right.this)
        result = op_fn(lv, rv)
        
        if result is None:
            return None
            
        if result == int(result):
            return exp.Literal.number(int(result))
        return exp.Literal.number(result)
    except (ValueError, TypeError):
        return None


def constant_folding(ast: exp.Expression) -> Tuple[exp.Expression, bool]:
    """
    Constant Folding
    
    Evaluates static arithmetic expressions (e.g., 5 + 10) at compile time 
    so the database engine doesn't have to compute them per row.
    Evaluates bottom-up to handle nested operations.
    """
    applied = False
    nodes = list(ast.walk())
    nodes.reverse() 
    
    for node in nodes:
        if isinstance(node, tuple):
            node = node[0]
        folded = _try_fold(node)
        if folded is not None:
            node.replace(folded)
            applied = True
            
    return ast, applied


# Order of passes does not matter since we iterate until convergence
PASSES = [
    ("Predicate Pushdown", predicate_pushdown),
    ("Projection Pruning", projection_pruning),
    ("Constant Folding",   constant_folding),
]


def optimize(sql: str) -> OptimizationResult:
    """
    Main entry point for query optimization.
    Applies passes repeatedly until the AST stops changing (fixed-point iteration).
    This guarantees the passes are order-independent.
    """
    start_total = time.perf_counter()

    try:
        original_ast = sqlglot.parse_one(sql, dialect="duckdb")
    except Exception as e:
        raise ValueError(f"SQL parse error: {e}")

    # Gather baseline metrics
    original_count   = count_nodes(original_ast)
    original_dict    = ast_to_dict(original_ast)
    original_sql_out = original_ast.sql(dialect="duckdb", pretty=True)

    working = original_ast.copy()

    # Track metrics per pass
    rules_applied = set()
    pass_times = {name: 0.0 for name, _ in PASSES}
    pass_reductions = {name: 0 for name, _ in PASSES}

    # Run passes in a loop until convergence
    max_iters = 10
    for _ in range(max_iters):
        changed_in_loop = False
        
        for rule_name, rule_fn in PASSES:
            count_before = count_nodes(working)
            start_pass = time.perf_counter()
            
            working, did_apply = rule_fn(working)
            
            elapsed_pass = (time.perf_counter() - start_pass) * 1000
            pass_times[rule_name] += elapsed_pass
            
            if did_apply:
                rules_applied.add(rule_name)
                count_after = count_nodes(working)
                pass_reductions[rule_name] += (count_before - count_after)
                changed_in_loop = True
                
        # Stop if the AST is fully optimized and stable
        if not changed_in_loop:
            break

    # Gather final metrics
    optimized_count   = count_nodes(working)
    optimized_dict    = ast_to_dict(working)
    optimized_sql_out = working.sql(dialect="duckdb", pretty=True)

    elapsed_total = (time.perf_counter() - start_total) * 1000
    reduction_pct = (
        (original_count - optimized_count) / original_count * 100
        if original_count > 0 else 0.0
    )

    pass_times = {k: round(v, 3) for k, v in pass_times.items()}

    return OptimizationResult(
        original_sql=original_sql_out,
        optimized_sql=optimized_sql_out,
        original_ast=original_dict,
        optimized_ast=optimized_dict,
        rules_applied=list(rules_applied),
        pass_times=pass_times,
        pass_reductions=pass_reductions,
        original_node_count=original_count,
        optimized_node_count=optimized_count,
        reduction_pct=round(reduction_pct, 1),
        elapsed_ms=round(elapsed_total, 3),
    )