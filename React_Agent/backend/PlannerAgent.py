from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import AnyMessage, add_messages
import json
import os
from dotenv import load_dotenv
from Orchestration import ResearchState
load_dotenv()

# ─────────────────────────────────────────────
#  PLANNER SYSTEM PROMPT
# ─────────────────────────────────────────────
PLANNER_SYSTEM_PROMPT = """You are the Planner Agent for a multi-agent research system called Nexus.

Your job is to analyze the user's research query and break it into a structured list of retrieval tasks.

You have access to 3 retrieval tools:
- "tavily"  → Use for: recent news, current events, live web data, company info, trends
- "arxiv"   → Use for: academic papers, scientific research, technical concepts, studies
- "wiki"    → Use for: background knowledge, definitions, history, overviews of topics

RULES:
1. Always output valid JSON only — no prose, no markdown, no explanation outside the JSON.
2. Decide which tools are actually needed — not every query needs all 3.
3. Order tasks by dependency (background first, then specifics).
4. Each task must have a focused, specific goal — not just the raw user query.
5. Choose a report_format based on query type:
   - "summary"    → casual questions, quick lookups
   - "bullets"    → comparisons, lists, how-tos
   - "full_paper" → deep research, academic topics, "explain in detail"
   
OUTPUT FORMAT (strict JSON):
{
  "tasks": [
    {
      "tool": "wiki",
      "goal": "Get background and foundational context on <topic>",
      "query": "<broad topic> overview"
    },
    {
      "tool": "arxiv",
      "goal": "Find recent academic research on <specific aspect>",
      "query": "<specific aspect> recent papers"
    },
    {
      "tool": "tavily",
      "goal": "Find latest news and developments on <topic>",
      "query": "<topic> latest news"
    }
  ],
  "report_format": "full_paper",
  "reasoning": "Brief explanation of why these tools and this format were chosen."
}"""

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ.get("GROQ_API_KEY"),
    temperature=0.3,
)

def planner_node(state: ResearchState) -> dict:
    """
    Takes the user query and outputs a structured task list.
    Decides which tools to use, in what order, and what report format to generate.
    """
    print(f"\n[PLANNER] Analyzing query: {state['query']}")

    if state.get("critic_feedback", "").startswith("RETRY"):
        print("[PLANNER] Using critic-refined tasks (skipping re-plan)")
        return {
            "tasks": state["tasks"],
            "report_format": state.get("report_format", "summary"),
            "planner_reasoning": "Using critic-refined tasks",
            "agent_status": {"planner": "skipped"},
        }

    response = llm.invoke([
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=f"Research query: {state['query']}")
    ])

    raw = response.content.strip()

    # Strip markdown code fences if model wraps output
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        # Fallback: default to all 3 tools if parsing fails
        print(f"[PLANNER] JSON parse failed: {e}. Using fallback plan.")
        parsed = {
            "tasks": [
                {"tool": "wiki",   "goal": "Get background context", "query": state["query"]},
                {"tool": "arxiv",  "goal": "Find academic research",  "query": state["query"]},
                {"tool": "tavily", "goal": "Find recent information",  "query": state["query"]},
            ],
            "report_format": "summary",
            "reasoning": "Fallback plan — planner output could not be parsed."
        }

    tasks          = parsed.get("tasks", [])
    report_format  = parsed.get("report_format", "summary")
    reasoning      = parsed.get("reasoning", "")

    print(f"[PLANNER] Tasks planned: {len(tasks)}")
    for i, t in enumerate(tasks, 1):
        print(f"  Task {i}: [{t['tool'].upper()}] {t['goal']}")
    print(f"[PLANNER] Report format: {report_format}")
    print(f"[PLANNER] Reasoning: {reasoning}")

    return {
        "tasks":             tasks,
        "report_format":     report_format,
        "planner_reasoning": reasoning,
        "agent_status":      {"planner": "done", "retrieval": "pending"},
        "retrieval_results": [],
        "critic_loops":      0,
    }
