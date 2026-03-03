from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from Orchestration import ResearchState
import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  SYNTHESIZER SYSTEM PROMPT
# ─────────────────────────────────────────────
SYNTHESIZER_SYSTEM_PROMPT = """You are the Synthesizer Agent for a multi-agent research system called Nexus.

You receive raw retrieval results from multiple sources (Arxiv, Wikipedia, Tavily) gathered by specialist agents.
Your job is to merge them into a single, clean, coherent synthesis — the foundation for the final report.

YOUR RESPONSIBILITIES:
1. Merge information from all sources into a unified understanding
2. Remove redundancy — if multiple sources say the same thing, say it once (best version)
3. Resolve minor conflicts — if sources slightly disagree, note both perspectives
4. Preserve source attribution — always mention where key facts came from
5. Prioritize higher-scored sources — arxiv (peer reviewed) > wiki (background) > tavily (web)
6. Identify key themes, trends, and insights that emerge across sources
7. Flag any significant gaps — if something important seems missing, note it

OUTPUT FORMAT:
Write in clean markdown. Structure your synthesis as follows:

## Overview
[2-3 sentence summary of the topic based on all sources combined]

## Key Findings
[The most important facts, discoveries, or insights — merged from all sources]

## Themes & Trends
[Patterns that emerge across multiple sources]

## Source Insights
[Brief note on what each source contributed and its reliability]

## Gaps & Limitations
[What's missing, outdated, or uncertain in the retrieved data]

IMPORTANT:
- Do NOT invent facts. Only use what the sources provide.
- Do NOT copy-paste raw source text. Rewrite everything in your own words.
- If a source failed to retrieve (score 0.0), ignore it and mention it in gaps.
- Keep the synthesis focused and dense — no filler, no repetition."""



llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ.get("GROQ_API_KEY"),
    temperature=0.4,   # slightly creative but still factual
)



def format_results_for_llm(retrieval_results: list[dict]) -> str:
    """
    Formats the retrieval results into a clean prompt block for the LLM.
    Sorts by score descending so highest quality sources appear first.
    Skips failed retrievals (score 0.0).
    """
    valid = [r for r in retrieval_results if r.get("score", 0) > 0.0]
    failed = [r for r in retrieval_results if r.get("score", 0) == 0.0]

    # Sort by score — highest first
    valid.sort(key=lambda x: x.get("score", 0), reverse=True)

    blocks = []
    for i, r in enumerate(valid, 1):
        source  = r.get("source", "unknown").upper()
        goal    = r.get("goal", "")
        score   = r.get("score", 0)
        content = r.get("content", "").strip()

        blocks.append(
            f"--- SOURCE {i}: {source} (confidence: {score:.2f}) ---\n"
            f"Goal: {goal}\n"
            f"Content:\n{content}\n"
        )

    if failed:
        failed_names = ", ".join(r.get("source", "?").upper() for r in failed)
        blocks.append(f"--- FAILED RETRIEVALS: {failed_names} ---\n(No content available)")

    return "\n".join(blocks)


def extract_all_urls(retrieval_results: list[dict]) -> list[str]:
    """Pulls all URLs from tavily results for the frontend source panel."""
    urls = []
    for r in retrieval_results:
        urls.extend(r.get("urls", []))
    return list(set(urls))  # deduplicate


def synthesizer_node(state: ResearchState) -> dict:
    """
    Merges all retrieval results into a clean, unified synthesis.
    Output feeds into both the Critic and Report Generator.
    """
    print(f"\n[SYNTHESIZER] Merging {len(state['retrieval_results'])} retrieval results...")

    retrieval_results = state.get("retrieval_results", [])

    # Guard: if nothing was retrieved, return early
    if not retrieval_results:
        print("[SYNTHESIZER] No retrieval results found — cannot synthesize.")
        return {
            "synthesis": "No retrieval results were available to synthesize.",
            "agent_status": {**state.get("agent_status", {}), "synthesizer": "failed"}
        }


    formatted = format_results_for_llm(retrieval_results)

    # Show score summary
    print("[SYNTHESIZER] Source scores:")
    for r in sorted(retrieval_results, key=lambda x: x.get("score", 0), reverse=True):
        print(f"  [{r['source'].upper()}] score={r.get('score', 0):.2f} — {r.get('goal', '')[:60]}")

    # Build prompt
    user_prompt = f"""Original research query: {state['query']}

Retrieved source data (sorted by confidence score):
{formatted}

Please synthesize all of the above into a unified research synthesis following your instructions."""

    response = llm.invoke([
        SystemMessage(content=SYNTHESIZER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt)
    ])

    synthesis = response.content.strip()
    print(f"[SYNTHESIZER] ✓ Synthesis complete ({len(synthesis)} chars)")

    # Extract all URLs for frontend source panel
    all_urls = extract_all_urls(retrieval_results)
    print(f"[SYNTHESIZER] Extracted {len(all_urls)} unique source URLs")

    return {
        "synthesis":    synthesis,
        "agent_status": {**state.get("agent_status", {}), "synthesizer": "done"},
        # Pass URLs through state so report generator and frontend can access them
        "retrieval_results": [
            {**r, "_all_urls": all_urls} if i == 0 else r
            for i, r in enumerate(retrieval_results)
        ]
    }