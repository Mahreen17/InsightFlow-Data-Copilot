"""

The MCP Agent -- an expanded, multi-tool version of what was previously a
single hardcoded function in orchestrator.py.

WHY THIS IS NOW ITS OWN AGENT, NOT ONE FUNCTION:
With one tool (get the date), the Orchestrator could just call it directly --
there was no decision to make. With several tools, something has to decide
WHICH one(s) a question needs. That's the same shape of problem the SQL
Agent solves (which columns/tables does this question need?), so this file
follows the same pattern: bind several tools to an LLM via create_agent()
and let it pick.

WHAT "MCP-PATTERN" MEANS HERE:
A real MCP integration talks to tools over the Model Context Protocol via a
separate server process. These functions skip that protocol layer and are
just plain Python -- but they play the same ROLE (external capabilities the
LLM doesn't have natively), which is what actually matters for the
Orchestrator's routing logic. Swapping these for real MCP-protocol calls
later would not require changing anything outside this file.
"""

import os
import datetime
import requests
from dotenv import load_dotenv
from langchain.tools import tool
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv(".env.local")

MODEL_NAME = "gemini-flash-lite-latest"


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


# =============================================================================
# The tools.
# =============================================================================


@tool
def get_current_date() -> str:
    """Returns today's date and day of the week. Use for any question
    involving 'today', 'now', 'currently', or relative dates like
    'how many days until/since'."""
    today = datetime.date.today()
    return f"{today.isoformat()} ({today.strftime('%A')})"


@tool
def get_current_time() -> str:
    """Returns the current time on the server. Note: this is server local
    time, not the user's timezone -- say so if precision matters."""
    now = datetime.datetime.now()
    return now.strftime("%I:%M %p (server local time)")


@tool
def days_between_dates(date1: str, date2: str) -> str:
    """Calculates the number of days between two dates. Both dates must be
    in YYYY-MM-DD format (e.g. '2026-08-11'). Use this instead of doing
    date math yourself -- it's easy to get off-by-one errors wrong."""
    try:
        d1 = datetime.date.fromisoformat(date1.strip())
        d2 = datetime.date.fromisoformat(date2.strip())
        diff = abs((d2 - d1).days)
        return f"{diff} days between {date1} and {date2}"
    except ValueError as e:
        return f"Error: could not parse one of the dates ({e}). Use YYYY-MM-DD format."



_CURRENCY_RATES_PER_USD = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "INR": 83.1,
    "CAD": 1.36, "AUD": 1.52, "JPY": 149.5,
}

@tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Converts an amount between currencies using FIXED reference rates
    (not live market rates -- clearly say so in your answer). Supported
    currency codes: USD, EUR, GBP, INR, CAD, AUD, JPY."""
    from_code, to_code = from_currency.strip().upper(), to_currency.strip().upper()
    if from_code not in _CURRENCY_RATES_PER_USD or to_code not in _CURRENCY_RATES_PER_USD:
        supported = ", ".join(_CURRENCY_RATES_PER_USD.keys())
        return f"Error: unsupported currency code. Supported: {supported}"
    usd_amount = amount / _CURRENCY_RATES_PER_USD[from_code]
    converted = usd_amount * _CURRENCY_RATES_PER_USD[to_code]
    return f"{amount} {from_code} ≈ {converted:.2f} {to_code} (fixed reference rate, not live)"


@tool
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """Converts a value between units commonly relevant to outdoor gear:
    weight (kg, lb), volume (l, gal), distance (km, mi), temperature (c, f).
    Use lowercase unit codes exactly: kg, lb, l, gal, km, mi, c, f."""
    from_u, to_u = from_unit.strip().lower(), to_unit.strip().lower()

    conversions = {
        ("kg", "lb"): lambda v: v * 2.20462,
        ("lb", "kg"): lambda v: v / 2.20462,
        ("l", "gal"): lambda v: v * 0.264172,
        ("gal", "l"): lambda v: v / 0.264172,
        ("km", "mi"): lambda v: v * 0.621371,
        ("mi", "km"): lambda v: v / 0.621371,
        ("c", "f"): lambda v: (v * 9/5) + 32,
        ("f", "c"): lambda v: (v - 32) * 5/9,
    }
    key = (from_u, to_u)
    if key not in conversions:
        supported = ", ".join(f"{a}->{b}" for a, b in conversions.keys())
        return f"Error: unsupported conversion '{from_u}' to '{to_u}'. Supported: {supported}"
    result = conversions[key](value)
    return f"{value} {from_u} = {result:.2f} {to_u}"


@tool
def get_weather_forecast(location: str) -> str:
    """Gets today's weather forecast for a location (city name, e.g.
    'Seattle' or 'Denver, CO'). Makes a real live API call -- if it fails
    (no internet, location not found), say so rather than guessing weather."""
    try:
        
        geo_resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
            timeout=8,
        )
        geo_resp.raise_for_status()
        geo_results = geo_resp.json().get("results")
        if not geo_results:
            return f"Error: could not find location '{location}'."
        lat, lon = geo_results[0]["latitude"], geo_results[0]["longitude"]
        resolved_name = geo_results[0].get("name", location)

        # Step 2: get today's forecast for those coordinates.
        forecast_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=8,
        )
        forecast_resp.raise_for_status()
        daily = forecast_resp.json()["daily"]
        high, low = daily["temperature_2m_max"][0], daily["temperature_2m_min"][0]
        rain_chance = daily["precipitation_probability_max"][0]
        return (f"{resolved_name}: high {high}°F, low {low}°F, "
                f"{rain_chance}% chance of precipitation today.")
    except requests.RequestException as e:
        return f"Error: weather lookup failed ({e}). This tool needs internet access."


# =============================================================================
# Assemble the agent.
# =============================================================================
model = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)
tools = [get_current_date, get_current_time, days_between_dates,
         convert_currency, convert_units, get_weather_forecast]

SYSTEM_PROMPT = """
You are an agent with access to external tools for TrailPeak Outdoor Co.'s
data copilot. You do NOT have access to the customer database or internal
documents -- only the tools listed below.

Use the tool(s) that match the question. If a question needs a tool you
don't have, say so plainly rather than guessing an answer.

Keep your final answer concise and direct.
"""

agent = create_agent(model, tools, system_prompt=SYSTEM_PROMPT)


def ask_mcp(question: str, verbose: bool = True) -> str:
    """Sends one question to the MCP Agent and returns its final text answer."""
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})

    if verbose:
        print(f"\n{'='*70}\nQ: {question}\n{'='*70}")
        for msg in result["messages"]:
            msg_type = type(msg).__name__
            if msg_type == "AIMessage" and getattr(msg, "tool_calls", None):
                for call in msg.tool_calls:
                    print(f"  [tool call] {call['name']}({call['args']})")
            elif msg_type == "ToolMessage":
                print(f"  [tool result] {str(msg.content)[:200]}")

    final_answer = _extract_text(result["messages"][-1].content)
    if verbose:
        print(f"\nANSWER: {final_answer}\n")
    return final_answer


# =============================================================================
# Standalone test -- one question per tool.
# =============================================================================
if __name__ == "__main__":
    import time

    test_questions = [
        "What is today's date?",
        "What time is it right now?",
        "How many days are there between 2026-01-01 and 2026-08-11?",
        "Convert 150 USD to EUR.",
        "How many pounds is a 65 liter backpack's typical 3kg empty weight?",
        "What's the weather like in Denver, CO today?",
    ]

    for q in test_questions:
        ask_mcp(q)
        time.sleep(15)  