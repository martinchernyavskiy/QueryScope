/**
 * Main React application component for the QueryScope frontend.
 * Handles user input, API communication, and the visualization of 
 * query optimization metrics, AST differences, and per-pass profiling.
 */

import React, { useState } from "react";

const API = "http://localhost:8000";

/**
 * Recursively renders an Abstract Syntax Tree (AST) node.
 * Allows users to collapse and expand nested tree structures for easier 
 * navigation of complex logical query plans.
 */
function ASTNode({ node, depth = 0 }) {
  const [open, setOpen] = useState(depth < 3);
  
  if (!node || !node.name) return null;
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div style={{ marginLeft: depth * 16, fontFamily: "monospace", fontSize: 13 }}>
      <span
        style={{ cursor: hasChildren ? "pointer" : "default", userSelect: "none" }}
        onClick={() => hasChildren && setOpen((o) => !o)}
      >
        {hasChildren ? (open ? "▾ " : "▸ ") : "  "}
        <span
          style={{
            background: depth === 0 ? "#1d4ed8" : depth === 1 ? "#2563eb" : "#3b82f6",
            color: "#fff",
            borderRadius: 4,
            padding: "1px 6px",
            marginRight: 4,
          }}
        >
          {node.name}
        </span>
      </span>
      {open && hasChildren && (
        <div>
          {node.children.map((child, i) => (
            <ASTNode key={i} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Reusable UI component for displaying high-level optimization metrics 
 */
function StatBadge({ label, value, highlight }) {
  return (
    <div
      style={{
        background: highlight ? "#dcfce7" : "#f1f5f9",
        border: `1px solid ${highlight ? "#86efac" : "#cbd5e1"}`,
        borderRadius: 8,
        padding: "8px 16px",
        textAlign: "center",
        minWidth: 120,
      }}
    >
      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: highlight ? "#16a34a" : "#1e293b" }}>
        {value}
      </div>
    </div>
  );
}

// Pre-defined deterministic queries to demonstrate specific rewrite rules
const EXAMPLES = [
  {
    label: "Constant Folding",
    sql: "SELECT * FROM orders WHERE price > 10 + 5 * 2",
  },
  {
    label: "TPC-H Q3",
    sql: `SELECT l.l_orderkey, SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM customer c, orders o, lineitem l
WHERE c.c_mktsegment = 'BUILDING'
  AND c.c_custkey = o.o_custkey
  AND l.l_orderkey = o.o_orderkey
  AND o.o_orderdate < DATE '1995-03-15'
  AND l.l_shipdate > DATE '1995-03-15'
GROUP BY l.l_orderkey, o.o_orderdate, o.o_shippriority
ORDER BY revenue DESC
LIMIT 10`,
  },
  {
    label: "Projection Pruning",
    sql: `SELECT agg.department_id, agg.avg_salary 
FROM (
    SELECT 
        department_id, 
        AVG(salary) AS avg_salary, 
        MAX(salary) AS max_salary, 
        MIN(salary) AS min_salary,
        COUNT(employee_id) AS total_employees
    FROM employees
    GROUP BY department_id
) agg 
WHERE agg.avg_salary > 50000`,
  },
];


export default function App() {
  const [sql, setSql] = useState(EXAMPLES[0].sql);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  /**
   * Submits the raw SQL query to the FastAPI backend for optimization.
   * Expects a JSON payload containing the original and optimized ASTs,
   * along with telemetry data (pass throughput, node reductions).
   */
  async function handleOptimize() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/optimize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql }),
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Server error");
      }
      
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc", padding: "32px 24px" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        
        {/* Application Header */}
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: "#1e293b", margin: 0 }}>
            QueryScope
          </h1>
          <p style={{ color: "#64748b", margin: "4px 0 0" }}>
            Rule-based SQL query optimizer with AST plan visualization
          </p>
        </div>

        {/* Example Selection Buttons */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              onClick={() => setSql(ex.sql)}
              style={{
                background: "#e2e8f0",
                border: "none",
                borderRadius: 6,
                padding: "6px 14px",
                cursor: "pointer",
                fontSize: 13,
                color: "#334155",
              }}
            >
              {ex.label}
            </button>
          ))}
        </div>

        {/* SQL Input Area */}
        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          rows={8}
          style={{
            width: "100%",
            fontFamily: "monospace",
            fontSize: 14,
            padding: 12,
            borderRadius: 8,
            border: "1px solid #cbd5e1",
            background: "#1e293b",
            color: "#e2e8f0",
            resize: "vertical",
            boxSizing: "border-box",
          }}
          placeholder="Enter SQL query..."
        />

        {/* Execution Control */}
        <button
          onClick={handleOptimize}
          disabled={loading}
          style={{
            marginTop: 12,
            background: loading ? "#94a3b8" : "#1d4ed8",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            padding: "10px 28px",
            fontSize: 15,
            fontWeight: 600,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Optimizing…" : "Optimize"}
        </button>

        {/* Error Handling */}
        {error && (
          <div
            style={{
              marginTop: 16,
              background: "#fef2f2",
              border: "1px solid #fca5a5",
              borderRadius: 8,
              padding: "12px 16px",
              color: "#dc2626",
            }}
          >
            {error}
          </div>
        )}

        {/* Results Dashboard */}
        {result && (
          <div style={{ marginTop: 32 }}>
            
            {/* Global Metrics Row */}
            <div style={{ display: "flex", gap: 12, marginBottom: 28, flexWrap: "wrap" }}>
              <StatBadge label="Rules Applied" value={result.rules_applied.length} />
              <StatBadge label="Original Nodes" value={result.original_node_count} />
              <StatBadge label="Optimized Nodes" value={result.optimized_node_count} />
              <StatBadge
                label="Node Reduction"
                value={`${result.reduction_pct}%`}
                highlight={result.reduction_pct > 0}
              />
              <StatBadge label="Elapsed" value={`${result.elapsed_ms}ms`} />
            </div>

            {/* Per-Pass Profiling and Node Reduction Panel */}
            {result.pass_times && result.pass_reductions && (
              <div style={{ marginBottom: 24 }}>
                <div style={{ fontWeight: 600, color: "#475569", fontSize: 13, marginBottom: 8 }}>
                  Pass Profiling & Reduction
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {Object.entries(result.pass_times).map(([name, time]) => (
                    <div
                      key={name}
                      style={{
                        background: "#f1f5f9",
                        borderRadius: 6,
                        padding: "8px 12px",
                        fontSize: 13,
                        border: "1px solid #e2e8f0"
                      }}
                    >
                      <div style={{ fontWeight: 600, color: "#1e293b", marginBottom: 4 }}>{name}</div>
                      <div style={{ color: "#64748b", fontSize: 12 }}>⏱️ {time} ms</div>
                      <div style={{ color: result.pass_reductions[name] > 0 ? "#16a34a" : "#64748b", fontSize: 12, marginTop: 2 }}>
                        📉 -{result.pass_reductions[name]} nodes
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Rules Triggered List */}
            {result.rules_applied.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <strong style={{ color: "#1e293b" }}>Rules fired:</strong>{" "}
                {result.rules_applied.map((r) => (
                  <span
                    key={r}
                    style={{
                      background: "#dbeafe",
                      color: "#1d4ed8",
                      borderRadius: 4,
                      padding: "2px 10px",
                      marginLeft: 6,
                      fontSize: 13,
                    }}
                  >
                    {r}
                  </span>
                ))}
              </div>
            )}

            {/* SQL Query Transformation Diff */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 28 }}>
              {[
                { label: "Original SQL", content: result.original_sql },
                { label: "Optimized SQL", content: result.optimized_sql },
              ].map(({ label, content }) => (
                <div key={label}>
                  <div
                    style={{
                      fontWeight: 600,
                      color: "#475569",
                      fontSize: 13,
                      marginBottom: 6,
                      textTransform: "uppercase",
                      letterSpacing: 1,
                    }}
                  >
                    {label}
                  </div>
                  <pre
                    style={{
                      background: "#1e293b",
                      color: "#e2e8f0",
                      padding: 16,
                      borderRadius: 8,
                      fontSize: 13,
                      overflowX: "auto",
                      margin: 0,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {content}
                  </pre>
                </div>
              ))}
            </div>

            {/* AST Interactive Tree Rendering */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {[
                { label: "Original Query Plan", ast: result.original_ast },
                { label: "Optimized Query Plan", ast: result.optimized_ast },
              ].map(({ label, ast }) => (
                <div key={label}>
                  <div
                    style={{
                      fontWeight: 600,
                      color: "#475569",
                      fontSize: 13,
                      marginBottom: 8,
                      textTransform: "uppercase",
                      letterSpacing: 1,
                    }}
                  >
                    {label}
                  </div>
                  <div
                    style={{
                      background: "#fff",
                      border: "1px solid #e2e8f0",
                      borderRadius: 8,
                      padding: 16,
                      maxHeight: 500,
                      overflowY: "auto",
                    }}
                  >
                    <ASTNode node={ast} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}