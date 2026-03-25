"""
validate_tpch.py

Validation harness for the QueryScope optimizer.
Verifies semantic equivalence of optimized queries by executing both the
original and optimized ASTs against a live PostgreSQL database provisioned
with a subset of the TPC-H schema and deterministic test data.
"""

import psycopg2
from optimizer import optimize

# Target database configuration
DB_CONFIG = {
    "dbname": "tpch",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432,
}

# TPC-H Query 3 variant used for semantic validation
TPCH_Q3 = """
SELECT l.l_orderkey, SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue 
FROM customer c, orders o, lineitem l 
WHERE c.c_mktsegment = 'BUILDING' 
  AND c.c_custkey = o.o_custkey 
  AND l.l_orderkey = o.o_orderkey 
  AND o.o_orderdate < DATE '1995-03-15' 
  AND l.l_shipdate > DATE '1995-03-15' 
GROUP BY l.l_orderkey, o.o_orderdate, o.o_shippriority 
ORDER BY revenue DESC 
LIMIT 10
"""


def setup_test_database(conn):
    """
    Provisions the target database with the necessary TPC-H tables and
    inserts a deterministic dataset designed to trigger specific filter conditions.
    """
    with conn.cursor() as cur:
        # Drop existing tables to ensure a clean testing state
        cur.execute("""
            DROP TABLE IF EXISTS lineitem, orders, customer CASCADE;
            
            CREATE TABLE customer (
                c_custkey integer PRIMARY KEY,
                c_mktsegment char(10)
            );
            CREATE TABLE orders (
                o_orderkey integer PRIMARY KEY,
                o_custkey integer,
                o_orderdate date,
                o_shippriority integer
            );
            CREATE TABLE lineitem (
                l_orderkey integer,
                l_extendedprice decimal(15,2),
                l_discount decimal(15,2),
                l_shipdate date
            );
        """)

        # Insert boundary test cases targeting the Q3 WHERE clause
        cur.execute("""
            INSERT INTO customer (c_custkey, c_mktsegment) VALUES 
            (1, 'BUILDING'), (2, 'AUTOMOBILE');
            
            INSERT INTO orders (o_orderkey, o_custkey, o_orderdate, o_shippriority) VALUES 
            (100, 1, '1995-03-01', 1),
            (101, 2, '1995-03-01', 1),
            (102, 1, '1995-04-01', 1);
            
            INSERT INTO lineitem (l_orderkey, l_extendedprice, l_discount, l_shipdate) VALUES 
            (100, 1000.00, 0.10, '1995-03-20'),
            (100, 500.00, 0.05, '1995-03-10'),
            (101, 2000.00, 0.00, '1995-03-20');
        """)
        conn.commit()


def run_validation():
    """
    Executes the validation pipeline:
    1. Establishes database connection.
    2. Provisions schema and test data.
    3. Executes the baseline query.
    4. Applies logical optimizations via QueryScope.
    5. Executes the optimized query.
    6. Asserts result set equivalence.
    """
    print(f"Connecting to PostgreSQL database at {DB_CONFIG['host']}:{DB_CONFIG['port']}...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except psycopg2.OperationalError as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return

    print("Initializing TPC-H schema and deterministic test data...")
    setup_test_database(conn)

    print("Executing baseline query...")
    with conn.cursor() as cur:
        cur.execute(TPCH_Q3)
        original_results = cur.fetchall()
        print(f"  -> Baseline results: {original_results}")

    print("Applying logical optimization passes...")
    result = optimize(TPCH_Q3)
    optimized_sql = result.optimized_sql
    
    print("Executing optimized query...")
    with conn.cursor() as cur:
        cur.execute(optimized_sql)
        optimized_results = cur.fetchall()
        print(f"  -> Optimized results: {optimized_results}")

    # Strict result set assertion to guarantee semantic equivalence
    assert original_results == optimized_results, "Validation failed: Result sets do not match."
    
    print("\n-----------------------------------------------------------------")
    print("Validation passed: Result sets match. Optimized AST is semantically equivalent.")
    print(f"Applied rewrite rules: {', '.join(result.rules_applied)}")
    print("-----------------------------------------------------------------")
    
    conn.close()


if __name__ == "__main__":
    run_validation()