"""
The Enterprise Data Copilot build: the SQL Agent.

WHAT THIS FILE DOES, IN PLAIN ENGLISH:
An "agent" in LangChain isn't magic — it's an LLM given a set of tools
(regular Python functions) plus a loop that lets it call those tools,
read the results, and decide what to do next. For a SQL Agent, the tools
are things like "list the tables" and "run this query." The LLM decides
WHICH tool to call and WHEN, based on your question — that decision-making
is the "agent" part. Everything else here is just wiring.

The flow for a typical question looks like:
  1. Agent calls sql_db_list_tables() to see what tables exist
  2. Agent calls sql_db_schema() on the tables that sound relevant
  3. Agent writes a SQL query based on what it learned
  4. Agent calls sql_db_query_checker() to sanity-check that query
  5. Agent calls sql_db_query() to actually run it
  6. Agent reads the result and writes you a natural-language answer

You don't write any of that control flow yourself — create_agent() builds
it for you. You just define the tools and a system prompt describing the
agent's job.
"""

import os
import sqlite3
from dotenv import load_dotenv

load_dotenv(".env.local")  

# --- LangChain imports -----------------------------------------------------

from langchain.tools import tool
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

# --- Configuration -----------------------------------------------------
DB_PATH = "trailpeak.db"          
MODEL_NAME = "gemini-flash-lite-latest"  




# =============================================================================
# STEP 1: Define the tools the agent is allowed to use.
# =============================================================================


@tool
def sql_db_list_tables() -> str:
    """Input is an empty string. Output is a comma-separated list of all
    table names in the database. Always call this first, before writing
    any query, so you know what tables actually exist."""
    con = sqlite3.connect(DB_PATH)
    try:
        cursor = con.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
        return ", ".join(tables)
    finally:
        con.close()


@tool
def sql_db_schema(table_names: str) -> str:
    """Input is a comma-separated list of table names (e.g. 'customers, orders').
    Output is the CREATE TABLE statement for each table plus 3 sample rows,
    so you can see real column names and real data before writing a query.
    Call sql_db_list_tables first to confirm a table actually exists."""
    con = sqlite3.connect(DB_PATH)
    try:
        cursor = con.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        valid_tables = {row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")}

        results = []
        for table in table_names.split(","):
            table = table.strip()
            if table not in valid_tables:
                results.append(f"Error: table '{table}' not found in database")
                continue

            # Get the CREATE TABLE statement (shows columns + types)
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?;", (table,))
            schema_row = cursor.fetchone()
            if schema_row:
                results.append(schema_row[0])

           
            cursor.execute(f'SELECT * FROM "{table}" LIMIT 3;')
            rows = cursor.fetchall()
            if rows:
                col_names = [d[0] for d in cursor.description]
                sample = f"/* 3 rows from {table}:\n" + "\t".join(col_names) + "\n"
                sample += "\n".join("\t".join(str(v) for v in row) for row in rows) + "\n*/"
                results.append(sample)

        return "\n\n".join(results)
    finally:
        con.close()


@tool
def sql_db_query(query: str) -> str:
    """Input is a syntactically correct SQLite query. Output is the query
    result. If the query has an error, the error message is returned instead
    — read it, fix the query, and try again rather than giving up."""
    con = sqlite3.connect(DB_PATH)
    try:
        cursor = con.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        return str(result)
    except Exception as e:
        return f"Error: {e}"
    finally:
        con.close()


# =============================================================================
# STEP 2: Set up the model.
# =============================================================================

model = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)

# All three tools get bundled into one list, which is what create_agent expects.
tools = [sql_db_list_tables, sql_db_schema, sql_db_query]


# =============================================================================
# STEP 3: Write the system prompt.
# =============================================================================

SYSTEM_PROMPT = """
You are an agent designed to answer questions about TrailPeak Outdoor Co.'s
business by querying a SQLite database.

Given an input question, create a syntactically correct SQLite query, run it,
and then answer the question in plain English based on the result. Always
show your reasoning briefly, but keep the final answer concise and direct.

Rules:
- ALWAYS call sql_db_list_tables first if you haven't already seen the schema
  in this conversation. Do not guess table or column names.
- Call sql_db_schema on any table you plan to query, so you use real column
  names and understand the data types.
- Limit results to at most 10 rows unless the question asks for more.
- Answer ONLY what the question asks. Do not volunteer additional related
  facts you happen to notice while exploring the schema (e.g. if asked for
  a count of delayed orders, do not also mention support ticket counts
  unless specifically asked) -- extra facts make downstream synthesis and
  UI display unpredictable.
- If the question asks about something these tables don't contain (a
  product, region, or attribute that doesn't exist in the schema), say so
  plainly -- e.g. "The database doesn't have information on X." Never
  guess or invent a plausible-sounding number.
- DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP, etc.) —
  you are read-only.
- If a query returns an error, read the error message, fix the query, and
  try again rather than giving up.
"""

# create_agent wires the model + tools + prompt into a runnable agent.

agent = create_agent(
    model,
    tools,
    system_prompt=SYSTEM_PROMPT,
)


# =============================================================================
# STEP 4: A helper to ask the agent a question and print a clean answer.
# =============================================================================
def _extract_text(content) -> str:
    """Normalizes a model response's .content into a plain string.

    Gemini sometimes returns content as a LIST of blocks instead of a
    plain string -- e.g. [{'type': 'text', 'text': '...', 'extras': {...}}]
    -- where 'extras' carries internal signature data that's meaningless
    to a reader. Without this, that raw structure leaks straight into the
    UI instead of looking like a normal chat reply. This pulls out just
    the human-readable text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def ask_sql(question: str, verbose: bool = True) -> str:
    """Sends one question to the SQL Agent and returns its final text answer.

    verbose=True (the default) also prints which tools it called along the
    way -- useful when running this file standalone to learn from. The
    Orchestrator will call this with verbose=False to keep its own output
    clean, since it does its own reporting."""
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})

    if verbose:
        print(f"\n{'='*70}\nQ: {question}\n{'='*70}")
        for msg in result["messages"]:
            msg_type = type(msg).__name__
            if msg_type == "AIMessage" and getattr(msg, "tool_calls", None):
                for call in msg.tool_calls:
                    print(f"  [tool call] {call['name']}({call['args']})")
            elif msg_type == "ToolMessage":
                preview = str(msg.content)[:200]
                print(f"  [tool result] {preview}")

    final_answer = _extract_text(result["messages"][-1].content)
    if verbose:
        print(f"\nANSWER: {final_answer}\n")
    return final_answer


# =============================================================================
# STEP 5: Run today's 5 pure-SQL eval questions.
# =============================================================================

if __name__ == "__main__":
    sql_questions = [
        "How many customers are in the West region?",
        "How many customers are on the Gold loyalty tier?",
        "What is the total revenue from Delivered orders in the Pacific Northwest region?",
        "Which product has the highest total quantity sold across all orders?",
        "How many support tickets have the issue type 'Warranty Claim'?",
    ]

    for q in sql_questions:
        ask_sql(q)