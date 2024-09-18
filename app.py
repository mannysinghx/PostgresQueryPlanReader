import re
from flask import Flask, request, render_template_string

app = Flask(__name__)

def parse_query_plan(plan):
    lines = plan.strip().split('\n')
    stack = []
    root = None
    
    for line in lines:
        level = len(line) - len(line.lstrip())
        node = {'name': line.strip(), 'children': []}
        
        while stack and stack[-1]['level'] >= level:
            stack.pop()
        
        if stack:
            stack[-1]['node']['children'].append(node)
        else:
            root = node
        
        stack.append({'level': level, 'node': node})
    
    return root

def analyze_query_plan(plan):
    recommendations = []
    operators = {
        "Seq Scan": [],
        "Index Scan": [],
        "Index Only Scan": [],
        "Bitmap Heap Scan": [],
        "Hash Join": [],
        "Nested Loop": [],
        "Merge Join": [],
        "Sort": [],
        "Aggregate": [],
        "Materialize": [],
        "Parallel": [],
        "Rows Removed by Filter": []
    }
    
    # Collecting occurrences of each operator and their costs
    operator_costs = {}
    for operator in operators.keys():
        if operator in plan:
            operators[operator].append(operator)
            cost_pattern = r"{}.*?cost=(\d+\.\d+)\.\.(\d+\.\d+)".format(operator.replace(" ", "_"))
            matches = re.findall(cost_pattern, plan)
            if matches:
                total_cost = sum(float(match[1]) for match in matches)  # Sum of the upper cost values
                operator_costs[operator] = total_cost

    # Check for sequential scans
    if operators["Seq Scan"]:
        tables = re.findall(r"Seq Scan on (\w+)", plan)
        for table in tables:
            recommendations.append(f"Consider adding an index to table '{table}' to avoid sequential scans.")
            recommendations.append(f"- Sequential scans read every row in the table, which can be inefficient for large datasets.")
            recommendations.append(f"- They are useful when the entire table needs to be processed or when the table is small.")
            recommendations.append(f"- However, for larger tables, consider using indexes to speed up data retrieval.")
            recommendations.append(f"- Suggested Index: `CREATE INDEX idx_{table}_on_column ON {table} (column_name);`")  # Placeholder for actual column name

    # Check for index scans
    if operators["Index Scan"]:
        recommendations.append("Index Scan detected. This is generally efficient, but consider:")
        recommendations.append("- Ensuring the index is selective enough to avoid scanning too many rows.")
        recommendations.append("- Analyzing the index usage to confirm it is being utilized effectively.")

    # Check for index-only scans
    if operators["Index Only Scan"]:
        recommendations.append("Index Only Scan detected. This is optimal as it avoids accessing the heap.")
        recommendations.append("- Ensure that the index covers all columns needed for the query to maximize efficiency.")
        recommendations.append("- Regularly update statistics to maintain index effectiveness.")

    # Check for bitmap heap scans
    if operators["Bitmap Heap Scan"]:
        recommendations.append("Bitmap Heap Scan detected. While better than sequential scan, consider:")
        recommendations.append("- Creating a covering index to enable Index Only Scan")
        recommendations.append("- Reviewing the query to see if it can be optimized to use an Index Scan")
        recommendations.append("- Investigate the use of bitmap indexes if applicable.")
        recommendations.append(f"- Suggested Index: `CREATE INDEX idx_bitmap ON table_name (column_name);`")  # Placeholder for actual column name

    # Check for hash joins
    if operators["Hash Join"]:
        bucket_pattern = r"buckets=(\d+)"
        matches = re.findall(bucket_pattern, plan)
        if matches:
            max_buckets = max(int(match) for match in matches)
            if max_buckets > 100000:
                recommendations.append(f"Large hash join detected ({max_buckets} buckets). Consider:")
                recommendations.append(f"- Increasing work_mem (current buckets: {max_buckets})")
                recommendations.append("- Reviewing join conditions to reduce the size of the hash table")
                recommendations.append("- Using an index-based join if possible")
                recommendations.append("- Analyze the distribution of data in the involved tables.")
                recommendations.append(f"- If the hash table exceeds the `work_mem` limit, it may spill to disk, processing data in batches, which can slow down execution. Consider increasing `work_mem` to allow hashing in a single batch for better performance. [Learn more](https://pganalyze.com/docs/explain/insights/hash-batches)")

    # Check for nested loops
    if operators["Nested Loop"]:
        nested_loops = plan.count("Nested Loop")
        if nested_loops > 2:
            recommendations.append(f"{nested_loops} nested loops detected. Consider the following:")
            recommendations.append("- Use JOIN clauses instead of subqueries where possible")
            recommendations.append("- Ensure proper indexing on join columns")
            recommendations.append("- Review query structure to minimize nested operations")
            recommendations.append("- Investigate the possibility of rewriting the query to reduce complexity.")

    # Check for merge joins
    if operators["Merge Join"]:
        recommendations.append("Merge Join detected. This is efficient for sorted data, but consider:")
        recommendations.append("- Ensuring that the input data is sorted to avoid additional sorting overhead.")
        recommendations.append("- Reviewing the join conditions to confirm they are optimal for merge joins.")

    # Check for sort operations
    if operators["Sort"]:
        recommendations.append("Sort operation detected. Consider:")
        recommendations.append("- Adding an index that matches the sort order to avoid in-memory sorting.")
        recommendations.append("- Analyzing the data distribution to determine if sorting can be optimized.")

    # Check for aggregate operations
    if operators["Aggregate"]:
        recommendations.append("Aggregate operation detected. Consider:")
        recommendations.append("- Ensuring that the aggregation is performed on indexed columns to improve performance.")
        recommendations.append("- Reviewing the query to see if it can be simplified to reduce the number of rows processed.")

    # Check for materialization
    if operators["Materialize"]:
        recommendations.append("Materialization detected. Consider:")
        recommendations.append("- Reviewing subqueries to see if they can be simplified or eliminated")
        recommendations.append("- Increasing work_mem to allow larger operations in memory")
        recommendations.append("- Evaluate if the materialized results can be cached for repeated queries.")

    # Check for parallel operations
    if "Parallel" not in plan:
        recommendations.append("No parallel operations detected. Consider:")
        recommendations.append("- Increasing max_parallel_workers_per_gather")
        recommendations.append("- Ensuring tables are large enough to benefit from parallelism")
        recommendations.append("- Reviewing queries to allow for parallelization")
        recommendations.append("- Consider using parallel query execution for large datasets.")
        recommendations.append(f"- Parallel operations can significantly improve performance for large queries by utilizing multiple CPU cores.")

    # Check for high rows removed by filter
    filter_pattern = r"Rows Removed by Filter: (\d+)"
    matches = re.findall(filter_pattern, plan)
    if matches:
        max_removed = max(int(match) for match in matches)
        if max_removed > 10000:
            recommendations.append(f"High number of rows removed by filter ({max_removed}). Consider:")
            recommendations.append("- Adding indexes to support the filter conditions")
            recommendations.append("- Reviewing data distribution and updating statistics")
            recommendations.append("- Rewriting the query to filter data earlier in the plan")
            recommendations.append("- Analyze the filter conditions to ensure they are selective enough.")

    return recommendations

def analyze_query(query):
    recommendations = []
    recommendations.append("### Query Analysis Recommendations")
    
    # Check for common issues in the query
    if "SELECT *" in query:
        recommendations.append("- Avoid using `SELECT *`. Specify only the columns you need to reduce data transfer and improve performance.")
    
    if "JOIN" in query:
        recommendations.append("- Ensure that JOIN conditions are properly indexed to improve join performance.")
        if "ON" not in query:
            recommendations.append("- Make sure to include `ON` conditions for JOINs to avoid Cartesian products.")
    
    if "WHERE" in query:
        recommendations.append("- Review the WHERE clause to ensure it filters data efficiently.")
        recommendations.append("- Consider adding indexes on columns used in the WHERE clause to speed up filtering.")
    
    if "GROUP BY" in query:
        recommendations.append("- Ensure that the columns in the GROUP BY clause are indexed if possible to improve aggregation performance.")
    
    if "ORDER BY" in query:
        recommendations.append("- If using ORDER BY, consider adding an index that matches the sort order to avoid in-memory sorting.")
    
    if "LIMIT" in query:
        recommendations.append("- Using `LIMIT` can improve performance by reducing the number of rows processed. Ensure it is used appropriately.")
    
    if "DISTINCT" in query:
        recommendations.append("- Using `DISTINCT` can be costly. Ensure it is necessary and consider if it can be avoided.")
    
    recommendations.append("- Regularly update statistics on your tables to help the query planner make informed decisions.")
    recommendations.append("- Use `EXPLAIN` to analyze the execution plan of your query and identify potential bottlenecks.")
    recommendations.append("- Consider breaking complex queries into smaller, simpler queries if performance issues arise.")
    
    return recommendations

@app.route('/', methods=['GET', 'POST'])
def index():
    recommendations = []
    query_plan = ""  # Initialize query_plan to capture user input
    query = ""  # Initialize query to capture user input

    if request.method == 'POST':
        query_plan = request.form['query_plan']  # Capture the new query plan
        query = request.form['query']  # Capture the new SQL query
        recommendations.extend(analyze_query_plan(query_plan))  # Analyze the new query plan
        if query:  # If a query is provided, analyze it as well
            recommendations.extend(analyze_query(query))  # Analyze the SQL query

    return render_template_string(''' 
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PostgreSQL Query Plan Analyzer</title>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; max-width: 1200px; margin: 0 auto; }
            textarea { width: 100%; height: 200px; margin-bottom: 10px; }
            button { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; cursor: pointer; }
            button:hover { background-color: #45a049; }
            #recommendations { margin-top: 20px; }
            .recommendation { background-color: #f2f2f2; padding: 10px; margin-bottom: 10px; border-radius: 5px; }
            .sub-recommendation { margin-left: 20px; color: #555; }
        </style>
    </head>
    <body>
        <h1>PostgreSQL Query Plan Analyzer</h1>
        <form method="post">
            <textarea name="query_plan" placeholder="Paste your query plan here...">{{ query_plan }}</textarea>
            <br>
            <textarea name="query" placeholder="Paste your SQL query here...">{{ query }}</textarea>
            <br>
            <button type="submit">Analyze</button>
        </form>
        <div id="recommendations">
            <h2>Recommendations:</h2>
            {% for recommendation in recommendations %}
                {% if recommendation.startswith('- ') %}
                    <div class="sub-recommendation">{{ recommendation }}</div>
                {% else %}
                    <div class="recommendation">{{ recommendation }}</div>
                {% endif %}
            {% endfor %}
        </div>
    </body>
    </html>
    ''', recommendations=recommendations, query_plan=query_plan, query=query)  # Ensure recommendations and user inputs are passed to the template

if __name__ == '__main__':
    app.run(debug=True)