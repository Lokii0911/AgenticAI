from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from Orchestration import ResearchState
import os
from dotenv import load_dotenv

load_dotenv()


SUMMARY_PROMPT = """You are the Report Generator for a research system called Nexus.
Your job is to convert a research synthesis into a clean, concise IEEE-style PDF with sections, fonts, and formatting report.

FORMAT: summary
- 3-5 paragraphs of flowing prose
- No bullet points, no headers
- Write for a general audience — clear, accessible language
- End with a one-sentence takeaway

Keep it tight. No filler. No repetition."""

BULLETS_PROMPT = """You are the Report Generator for a research system called Nexus.
Your job is to convert a research synthesis into a structured bullet-point report.

FORMAT: bullets
Use this structure:

## Key Points
- [most important finding]
- [second finding]
...

## Trends & Patterns
- [trend 1]
- [trend 2]
...

## What To Watch
- [future development or open question]
...

## Bottom Line
[One crisp sentence summarizing everything]

Be specific — include numbers, dates, names where available. No vague statements."""

FULL_PAPER_PROMPT = """You are the Report Generator for a research system called Nexus.
Your job is to convert a research synthesis into a full, concise IEEE-style PDF with sections, fonts, and formatting report.

FORMAT: full research paper
Use this structure:

# [Generate an appropriate title based on the query]

## Abstract
[150-200 word summary of the entire report]

## 1. Introduction
[Context, why this topic matters, scope of this report]

## 2. Background
[Foundational knowledge needed to understand the findings]

## 3. Current State & Key Findings
[The main discoveries, developments, and facts from the research]

## 4. Analysis & Implications
[What the findings mean — trends, patterns, significance]

## 5. Gaps & Open Questions
[What is still unknown, debated, or needs more research]

## 6. Conclusion
[Summary of findings and final assessment]

## Sources
[List the sources used: arxiv, wikipedia, web — with their confidence scores]

Write with academic clarity but remain readable. Use specific facts, numbers, and dates where available.
Minimum 600 words."""


FORMAT_PROMPTS = {
    "summary":    SUMMARY_PROMPT,
    "bullets":    BULLETS_PROMPT,
    "full_paper": FULL_PAPER_PROMPT,
}


# ─────────────────────────────────────────────
#  LLM
# ─────────────────────────────────────────────
llm = ChatGroq(
    model="moonshotai/kimi-k2-instruct-0905",
    api_key=os.environ.get("GROQ_API_KEY"),
    temperature=0.5,  # balanced — clear writing with natural flow
)


def build_source_list(retrieval_results: list[dict]) -> str:
    """Builds a formatted source list for the report footer."""
    lines = []
    seen = set()
    for r in retrieval_results:
        source = r.get("source", "unknown")
        score  = r.get("score", 0)
        goal   = r.get("goal", "")
        urls   = r.get("urls", [])

        if source not in seen:
            seen.add(source)
            lines.append(f"- {source.upper()} (confidence: {score:.2f}) — {goal}")
            for url in urls[:2]:  # max 2 urls per source
                lines.append(f"  • {url}")

    return "\n".join(lines) if lines else "No sources available."


def report_generator_node(state: ResearchState) -> dict:
    """
    Converts the validated synthesis into the final formatted report.
    Format is determined by the planner (summary / bullets / full_paper).
    """
    report_format   = state.get("report_format", "summary")
    synthesis       = state.get("synthesis", "")
    query           = state.get("query", "")
    critic_feedback = state.get("critic_feedback", "")

    print(f"\n[REPORT GENERATOR] Generating '{report_format}' report...")

    # Pick the right system prompt based on format
    system_prompt = FORMAT_PROMPTS.get(report_format, SUMMARY_PROMPT)

    # Build source list
    source_list = build_source_list(state.get("retrieval_results", []))

    # Include critic notes if research was retried
    critic_note = ""
    if critic_feedback and "RETRY" in critic_feedback:
        critic_note = f"\nNote: This report was refined after critic validation. {critic_feedback[6:200]}"

    user_prompt = f"""Original research query: {query}

Research synthesis (validated):
{synthesis}

Source list:
{source_list}
{critic_note}

Please generate the final report now in the '{report_format}' format."""

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ])

    final_report = response.content.strip()
    print(f"[REPORT GENERATOR] ✓ Report complete ({len(final_report)} chars, format: {report_format})")

    # Extract all URLs for frontend source panel
    all_urls = []
    for r in state.get("retrieval_results", []):
        all_urls.extend(r.get("urls", []))
    all_urls = list(set(all_urls))

    return {
        "final_report":  final_report,
        "agent_status":  {**state.get("agent_status", {}), "report_generator": "done"},
        "messages":      state.get("messages", []),
    }