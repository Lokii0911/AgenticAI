from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from Orchestration import ResearchState
import os
import json
from dotenv import load_dotenv

load_dotenv()


CRITIC_SYSTEM_PROMPT = """You are the Critic Agent for a multi-agent research system called Nexus.

You receive a research synthesis and your job is to validate its quality, accuracy, and completeness.
You are skeptical, rigorous, and honest. You do not let weak research pass.

CHECK FOR THESE ISSUES:
1. CONTRADICTIONS    — Does the synthesis contradict itself or have conflicting facts?
2. WEAK SOURCES      — Are claims made with no source backing or only low-confidence sources?
3. HALLUCINATIONS    — Are there specific claims that seem invented or unsupported by the retrieved data?
4. GAPS              — Are there obvious missing angles that would make this research incomplete?
5. STALENESS         — Is the information potentially outdated for a time-sensitive topic?
6. VAGUENESS         — Are key claims too vague to be useful (no numbers, dates, specifics)?

SCORING:
Rate the synthesis on a scale of 1-10 across:
- accuracy    (are facts well-supported?)
- completeness (are all angles covered?)
- source_quality (how reliable are the sources?)
- overall

VERDICT:
- "PASS"  → overall score >= 7 AND no critical contradictions or hallucinations
- "RETRY" → overall score < 7 OR critical issues found that need more research

OUTPUT FORMAT (strict JSON only — no prose outside JSON):
{
  "verdict": "PASS" or "RETRY",
  "scores": {
    "accuracy": <1-10>,
    "completeness": <1-10>,
    "source_quality": <1-10>,
    "overall": <1-10>
  },
  "issues": [
    {
      "type": "CONTRADICTION" | "WEAK_SOURCE" | "HALLUCINATION" | "GAP" | "STALENESS" | "VAGUENESS",
      "description": "Specific description of the issue",
      "severity": "low" | "medium" | "high"
    }
  ],
  "retry_queries": [
    {
      "tool": "tavily" | "arxiv" | "wiki",
      "query": "<specific query to fill the gap>",
      "goal": "<what this retry is trying to fix>",
      "reason": "<which issue this addresses>"
    }
  ],
  "feedback_summary": "One paragraph summarizing the overall quality and main concerns."
}

RULES:
- If verdict is "PASS", retry_queries can be empty [].
- If verdict is "RETRY", retry_queries must have at least 1 entry targeting the worst issue.
- Be specific in issues — "source is weak" is not useful. Say WHY it is weak.
- retry_queries should be targeted and different from original queries — don't repeat what already failed."""


llm = ChatGroq(
    model="moonshotai/kimi-k2-instruct-0905",
    api_key=os.environ.get("GROQ_API_KEY"),
    temperature=0.2,  # low temp — critic must be consistent and strict
)

MAX_CRITIC_LOOPS = 2

def critic_node(state: ResearchState) -> dict:
    """
    Validates the synthesis output.
    Returns PASS (proceed to report) or RETRY (loop back to retrieval with new queries).
    Hard capped at MAX_CRITIC_LOOPS retries to prevent infinite loops.
    """
    current_loop = state.get("critic_loops", 0)
    print(f"\n[CRITIC] Validating synthesis (loop {current_loop + 1}/{MAX_CRITIC_LOOPS})...")

    synthesis = state.get("synthesis", "")

    if not synthesis or synthesis.startswith("No retrieval results"):
        print("[CRITIC] No synthesis to validate — forcing PASS to avoid deadlock.")
        return {
            "critic_feedback": "PASS",
            "critic_loops": current_loop + 1,
            "agent_status": {**state.get("agent_status", {}), "critic": "skipped"}
        }

    # Hard cap check — if already hit max loops, force pass
    if current_loop >= MAX_CRITIC_LOOPS:
        print(f"[CRITIC] Max loops ({MAX_CRITIC_LOOPS}) reached — forcing PASS.")
        return {
            "critic_feedback": "PASS",
            "critic_loops": current_loop + 1,
            "agent_status": {**state.get("agent_status", {}), "critic": "max_loops_reached"}
        }

    # Build source quality context for critic
    source_summary = ""
    for r in state.get("retrieval_results", []):
        source_summary += (
            f"- [{r.get('source','?').upper()}] "
            f"score={r.get('score', 0):.2f} | "
            f"goal: {r.get('goal', '')[:80]}\n"
        )

    user_prompt = f"""Original research query: {state['query']}

Source confidence scores:
{source_summary if source_summary else "No source data available."}

Synthesis to validate:
{synthesis}

Please validate this synthesis and return your verdict as strict JSON."""

    response = llm.invoke([
        SystemMessage(content=CRITIC_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt)
    ])

    raw = response.content.strip()

    # Strip markdown code fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[CRITIC] JSON parse failed: {e} — defaulting to PASS")
        return {
            "critic_feedback":  "PASS",
            "critic_loops":     current_loop + 1,
            "agent_status":     {**state.get("agent_status", {}), "critic": "parse_error"}
        }

    verdict         = parsed.get("verdict", "PASS")
    scores          = parsed.get("scores", {})
    issues          = parsed.get("issues", [])
    retry_queries   = parsed.get("retry_queries", [])
    feedback        = parsed.get("feedback_summary", "")

    # ── Log results ──
    print(f"[CRITIC] Verdict: {verdict}")
    print(f"[CRITIC] Scores: accuracy={scores.get('accuracy')}, "
          f"completeness={scores.get('completeness')}, "
          f"source_quality={scores.get('source_quality')}, "
          f"overall={scores.get('overall')}")

    if issues:
        print(f"[CRITIC] Issues found ({len(issues)}):")
        for issue in issues:
            print(f"  [{issue.get('severity','?').upper()}] "
                  f"{issue.get('type','?')} — {issue.get('description','')[:80]}")

    if verdict == "RETRY" and retry_queries:
        print(f"[CRITIC] Retry queries ({len(retry_queries)}):")
        for rq in retry_queries:
            print(f"  [{rq.get('tool','?').upper()}] {rq.get('goal','')[:60]}")

    print(f"[CRITIC] Feedback: {feedback[:120]}...")

    # ── If RETRY — inject new tasks back into state for retrieval router ──
    if verdict == "RETRY" and retry_queries:
        # Format retry queries as tasks (same structure as planner tasks)
        new_tasks = [
            {
                "tool":  rq.get("tool", "tavily"),
                "goal":  rq.get("goal", ""),
                "query": rq.get("query", ""),
            }
            for rq in retry_queries
        ]
        print(f"[CRITIC] Injecting {len(new_tasks)} new tasks for retry retrieval...")
        return {
            "critic_feedback": f"RETRY: {feedback}",
            "critic_loops":    current_loop + 1,
            "tasks":           new_tasks,   # ← overwrite tasks with retry queries
            "agent_status":    {**state.get("agent_status", {}), "critic": "retry"}
        }


    return {
        "critic_feedback": f"PASS: {feedback}",
        "critic_loops":    current_loop + 1,
        "agent_status":    {**state.get("agent_status", {}), "critic": "done"}
    }

def critic_router(state: ResearchState) -> str:
    """
    Reads critic_feedback from state and routes accordingly.
    Called as a conditional edge function in main.py graph.
    """
    feedback     = state.get("critic_feedback", "PASS")
    critic_loops = state.get("critic_loops", 0)

    # Always go to report if max loops hit
    if critic_loops >= MAX_CRITIC_LOOPS:
        print(f"[CRITIC ROUTER] Max loops reached — routing to report_generator")
        return "report_generator"

    if feedback.startswith("RETRY"):
        print(f"[CRITIC ROUTER] RETRY detected — routing back to retrieval_router")
        return "retrieval_router"

    print(f"[CRITIC ROUTER] PASS — routing to report_generator")
    return "report_generator"