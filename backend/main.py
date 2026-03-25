"""
FastAPI application server for QueryScope.
Exposes endpoints for SQL query optimization, health checks, and demo examples.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from optimizer import optimize

app = FastAPI(title="QueryScope", version="1.0.0")

# Allow cross-origin requests from the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class OptimizeRequest(BaseModel):
    sql: str


class OptimizeResponse(BaseModel):
    """Data model for the optimization pipeline payload."""
    original_sql: str
    optimized_sql: str
    original_ast: dict
    optimized_ast: dict
    rules_applied: list[str]
    pass_times: dict[str, float]       # Execution time per pass (ms)
    pass_reductions: dict[str, int]    # AST nodes eliminated per pass
    original_node_count: int
    optimized_node_count: int
    reduction_pct: float
    elapsed_ms: float


@app.post("/optimize", response_model=OptimizeResponse)
def optimize_query(req: OptimizeRequest):
    """
    Parses and optimizes the provided SQL query.
    Returns the original and optimized ASTs, along with telemetry metrics.
    """
    if not req.sql.strip():
        raise HTTPException(status_code=400, detail="SQL string cannot be empty.")
    
    try:
        result = optimize(req.sql)
    except ValueError as e:
        # Catch sqlglot parsing errors and return a 422 Unprocessable Entity
        raise HTTPException(status_code=422, detail=str(e))
        
    return OptimizeResponse(**result.__dict__)


@app.get("/health")
def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


@app.get("/examples")
def get_examples():
    """Provides pre-defined SQL queries for the frontend demo."""
    return [
        {
            "label": "TPC-H Q3 (Join + Filter)",
            "sql": (
                "SELECT l.l_orderkey, SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue "
                "FROM customer c, orders o, lineitem l "
                "WHERE c.c_mktsegment = 'BUILDING' "
                "AND c.c_custkey = o.o_custkey "
                "AND l.l_orderkey = o.o_orderkey "
                "AND o.o_orderdate < DATE '1995-03-15' "
                "AND l.l_shipdate > DATE '1995-03-15' "
                "GROUP BY l.l_orderkey, o.o_orderdate, o.o_shippriority "
                "ORDER BY revenue DESC LIMIT 10"
            ),
        },
        {
            "label": "Constant Folding",
            "sql": "SELECT * FROM orders WHERE price > 10 + 5 * 2",
        },
        {
            "label": "Projection Pruning",
            "sql": "SELECT a, b, c FROM t WHERE a > 1",
        },
    ]