"""
The Enterprise Data Copilot build: the Orchestrator.

WHAT THIS FILE ADDS THAT'S GENUINELY NEW:
Days 2-3 each built one agent that always does the same kind of work --
the SQL Agent always queries the database, the RAG Agent always searches
PDFs. Neither of them has to DECIDE anything about what KIND of question
it's looking at; they just do their one job.

The Orchestrator is different: it looks at an incoming question and has
to decide, before doing any real work, which agent(s) are actually needed.
That decision-making step is what "orchestration" means here. Everything
after the decision is just calling functions you already built.

THE THREE-STEP FLOW FOR ONE QUESTION:
  1. ROUTE   -- ask the LLM which data source(s) this question needs
  2. DISPATCH -- call whichever of ask_sql() / ask_rag() / the MCP tool
               the routing decision says to call
  3. SYNTHESIZE -- if more than one source was used, ask the LLM to
               combine their raw answers into ONE coherent response,
               tagging which fact came from where. If only one source
               was used, skip this step entirely -- no need to pay for
               an extra LLM call to "combine" a single answer with itself.
"""

import os
import time
import datetime
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv(".env.local")


from sql_agent import ask_sql
from rag_agent import ask_rag
from mcp_agent import ask_mcp





# =============================================================================
# STEP 1: The routing decision.
# =============================================================================

class RoutingDecision(BaseModel):
    needs_sql: bool = Field(
        description="True if answering requires querying the database "
        "(counts, sums, records, anything about specific customers/orders/products)."
    )
    needs_rag: bool = Field(
        description="True if answering requires looking up policy or reference "
        "documents (return policy, warranty, shipping SLA, loyalty program, etc.)."
    )
    needs_mcp: bool = Field(
        description="True if answering requires an external tool: the current "
        "date/time, calculating days between dates, currency conversion, unit "
        "conversion (weight/volume/distance/temperature), or a live weather forecast."
    )
    reasoning: str = Field(
        description="One short sentence explaining why these sources were chosen."
    )


router_model = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0)
router = router_model.with_structured_output(RoutingDecision)

ROUTING_PROMPT = """You are deciding which data sources are needed to answer a \
question about TrailPeak Outdoor Co., an outdoor gear retailer.

- SQL is needed for anything requiring the database: counts, totals, specific \
customers/orders/products/tickets.
- RAG is needed for anything requiring policy or reference documents: return \
policy, warranties, shipping SLAs, loyalty program rules, support hours.
- MCP is needed for anything requiring an external tool: current date/time, \
days-between-dates calculations, currency conversion, unit conversion \
(weight/volume/distance/temperature), or a live weather forecast.

A question can need more than one source. Choose only what's genuinely needed.

Question: {question}"""


def route(question: str) -> RoutingDecision:
    return router.invoke(ROUTING_PROMPT.format(question=question))


# =============================================================================
# STEP 2 + 3: Dispatch to the right agent(s), then synthesize if needed.
# =============================================================================
synthesis_model = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", temperature=0)

SYNTHESIS_PROMPT = """You are combining answers from different systems into ONE \
coherent response to the user's original question. Each source below is labeled.
Write a single natural answer that uses all the relevant information, and \
briefly note which source each fact came from (e.g. "per the database" / \
"per the Shipping SLA document").

If one or more sources indicate they don't have relevant information, say so \
plainly in your combined answer rather than glossing over the gap -- do not \
invent information to fill in what a source didn't provide.

Original question: {question}

--- SOURCE ANSWERS ---
{sources}
--- END SOURCE ANSWERS ---

Combined answer:"""


def _extract_text(content) -> str:
    """See sql_agent.py for the full explanation -- normalizes Gemini's
    response content into plain text instead of a raw block structure."""
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


def ask_orchestrator(question: str, verbose: bool = True, return_details: bool = False):
    """The single entry point for the whole system. Routes the question,
    calls the agents that are actually needed, and synthesizes a final
    answer if more than one agent contributed.

    return_details=False (the default) returns just the final answer text --
    what you want for quick scripts and testing. return_details=True instead
    returns a dict with the routing decision, each agent's raw answer, and
    the final answer -- what the Streamlit UI wants, so it can show a
    "how did it get this answer" trace panel without re-parsing printed text."""

    decision = route(question)
    if verbose:
        print(f"\n{'='*70}\nQ: {question}\n{'='*70}")
        print(f"[routing] sql={decision.needs_sql}  rag={decision.needs_rag}  "
              f"mcp={decision.needs_mcp}  -- {decision.reasoning}")

    
    collected = {}

    if decision.needs_sql:
        collected["database (SQL)"] = ask_sql(question, verbose=False)

    if decision.needs_rag:
        collected["internal documents (RAG)"] = ask_rag(question, verbose=False)

    if decision.needs_mcp:
        collected["external tools (MCP)"] = ask_mcp(question, verbose=False)

    if not collected:
        
        collected["internal documents (RAG)"] = ask_rag(question, verbose=False)

    # --- Single source: no synthesis needed, just return it directly. ---
    if len(collected) == 1:
        final_answer = next(iter(collected.values()))

    # --- Multiple sources: combine them into one coherent answer. ---
    else:
        sources_block = "\n\n".join(f"[{label}]\n{text}" for label, text in collected.items())
        prompt = SYNTHESIS_PROMPT.format(question=question, sources=sources_block)
        final_answer = _extract_text(synthesis_model.invoke(prompt).content)

    if verbose:
        print(f"\nANSWER: {final_answer}\n")

    if return_details:
        return {
            "question": question,
            "routing": decision,
            "sources": collected,
            "final_answer": final_answer,
        }
    return final_answer


# =============================================================================
# STEP 4: Test routing across all 4 question types from eval_questions.json.
# =============================================================================
if __name__ == "__main__":
    test_questions = [
        # Pure SQL -- expect needs_sql=True, everything else False
        "How many customers are on the Gold loyalty tier?",
        # Pure RAG -- expect needs_rag=True, everything else False
        "What are the benefits of being a Gold tier loyalty member?",
        # Hybrid SQL+RAG -- expect both True (this is the hardest case)
        "Our Pacific Northwest customers had several delayed orders -- how many, "
        "and what does our SLA document say counts as delayed for that region?",
        # MCP -- expect needs_mcp=True, likely combined with needs_sql
        "What is today's date, and how many days ago was the most recent order placed?",
    ]

    for q in test_questions:
        ask_orchestrator(q)
        time.sleep(30)  