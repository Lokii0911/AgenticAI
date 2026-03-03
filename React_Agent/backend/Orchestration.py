from typing import TypedDict,Annotated
from langgraph.graph.message import  AnyMessage,add_messages
import operator

def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}

class ResearchState(TypedDict):
    # Input
    query: str

    # Planner output
    tasks: list[dict]           # [{"tool": "tavily", "goal": "...", "query": "..."}, ...]
    report_format: str          # "summary" | "bullets" | "full_paper"
    planner_reasoning: str      # why planner made these decisions

    # Retrieval results (accumulated from all specialist agents)
    retrieval_results: Annotated[list, operator.add]
    # e.g. [{"source": "arxiv", "content": "...", "goal": "...", "score": 0.9}]

    # Synthesizer output
    synthesis: str

    # Critic output
    critic_feedback: str
    critic_loops: int

    # Report Generator output
    final_report: str

    # Streaming / frontend
    messages: Annotated[list[AnyMessage], add_messages]
    agent_status:Annotated[dict, merge_dicts]         # {"planner": "done", "retrieval": "running", ...}
