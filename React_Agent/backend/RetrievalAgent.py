from langchain_community.tools import ArxivQueryRun, WikipediaQueryRun
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_community.utilities import WikipediaAPIWrapper, ArxivAPIWrapper
from Orchestration import ResearchState
import os
from dotenv import load_dotenv

load_dotenv()


api_wrapper_arxiv = ArxivAPIWrapper(top_k_results=2, doc_content_chars_max=1500)
arxiv_tool = ArxivQueryRun(api_wrapper=api_wrapper_arxiv)

api_wrapper_wiki = WikipediaAPIWrapper(top_k_results=2, doc_content_chars_max=1500)
wiki_tool = WikipediaQueryRun(api_wrapper=api_wrapper_wiki)

tavily_tool = TavilySearchResults(
    api_key=os.environ.get("TAVILY_API_KEY"),
    max_results=3
)


def score_result(source: str, content: str) -> float:
    """
    Assigns a confidence score (0.0 - 1.0) based on source type and content quality.
    - arxiv:  high trust (peer reviewed)
    - wiki:   medium trust (good background, not always current)
    - tavily: variable (web — scored by result count and length)
    """
    if source == "arxiv":
        # Arxiv results are peer-reviewed — high base score
        base = 0.85
        if len(content) > 800:
            base += 0.05
        return min(base, 1.0)

    elif source == "wiki":
        base = 0.70
        if len(content) > 600:
            base += 0.05
        return min(base, 1.0)

    elif source == "tavily":
        # Tavily returns multiple results — more results = higher confidence
        base = 0.65
        if len(content) > 500:
            base += 0.05
        return min(base, 1.0)

    return 0.5



def arxiv_node(state: ResearchState) -> dict:
    """Handles all arxiv tasks from the planner."""
    tasks = [t for t in state["tasks"] if t["tool"] == "arxiv"]
    results = []

    if not tasks:
        print("[ARXIV] No tasks assigned, skipping.")
        return {"retrieval_results": results}

    for task in tasks:
        print(f"[ARXIV] Running: {task['goal']}")
        print(f"[ARXIV] Query: {task['query']}")
        try:
            content = arxiv_tool.run(task["query"])
            score = score_result("arxiv", content)
            results.append({
                "source": "arxiv",
                "goal":   task["goal"],
                "query":  task["query"],
                "content": content,
                "score":  score
            })
            print(f"[ARXIV] ✓ Retrieved {len(content)} chars (score: {score})")
        except Exception as e:
            print(f"[ARXIV] ✗ Failed: {e}")
            results.append({
                "source":  "arxiv",
                "goal":    task["goal"],
                "query":   task["query"],
                "content": f"Retrieval failed: {e}",
                "score":   0.0
            })

    return {
        "retrieval_results": results,
        "agent_status": {"arxiv": "done"}
    }


def wiki_node(state: ResearchState) -> dict:
    """Handles all wiki tasks from the planner."""
    tasks = [t for t in state["tasks"] if t["tool"] == "wiki"]
    results = []

    if not tasks:
        print("[WIKI] No tasks assigned, skipping.")
        return {"retrieval_results": results}

    for task in tasks:
        print(f"[WIKI] Running: {task['goal']}")
        print(f"[WIKI] Query: {task['query']}")
        try:
            content = wiki_tool.run(task["query"])
            score = score_result("wiki", content)
            results.append({
                "source":  "wiki",
                "goal":    task["goal"],
                "query":   task["query"],
                "content": content,
                "score":   score
            })
            print(f"[WIKI] ✓ Retrieved {len(content)} chars (score: {score})")
        except Exception as e:
            print(f"[WIKI] ✗ Failed: {e}")
            results.append({
                "source":  "wiki",
                "goal":    task["goal"],
                "query":   task["query"],
                "content": f"Retrieval failed: {e}",
                "score":   0.0
            })

    return {
        "retrieval_results": results,
        "agent_status": {"wiki": "done"}
    }


def tavily_node(state: ResearchState) -> dict:
    """Handles all tavily tasks from the planner."""
    tasks = [t for t in state["tasks"] if t["tool"] == "tavily"]
    results = []

    if not tasks:
        print("[TAVILY] No tasks assigned, skipping.")
        return {"retrieval_results": results}

    for task in tasks:
        print(f"[TAVILY] Running: {task['goal']}")
        print(f"[TAVILY] Query: {task['query']}")
        try:
            raw = tavily_tool.invoke(task["query"])

            # Tavily returns a list of dicts — combine into readable content
            if isinstance(raw, list):
                content = "\n\n".join(
                    f"[{r.get('url', 'unknown')}]\n{r.get('content', '')}"
                    for r in raw
                )
                # Extract URLs for source tracking
                urls = [r.get("url", "") for r in raw if r.get("url")]
            else:
                content = str(raw)
                urls = []

            score = score_result("tavily", content)
            results.append({
                "source":  "tavily",
                "goal":    task["goal"],
                "query":   task["query"],
                "content": content,
                "score":   score,
                "urls":    urls       # ← frontend uses these for source panel
            })
            print(f"[TAVILY] ✓ Retrieved {len(content)} chars, {len(urls)} URLs (score: {score})")
        except Exception as e:
            print(f"[TAVILY] ✗ Failed: {e}")
            results.append({
                "source":  "tavily",
                "goal":    task["goal"],
                "query":   task["query"],
                "content": f"Retrieval failed: {e}",
                "score":   0.0,
                "urls":    []
            })

    return {
        "retrieval_results": results,
        "agent_status": {"tavily": "done"}
    }


def retrieval_router(state: ResearchState):
    """
    Reads the task list from planner and decides which retrieval nodes to run.
    Returns Send() commands for parallel execution in LangGraph.
    """
    from langgraph.types import Send

    tools_needed = set(t["tool"] for t in state["tasks"])
    print(f"\n[ROUTER] Tools needed: {tools_needed}")

    sends = []
    if "arxiv"  in tools_needed: sends.append(Send("arxiv_node",  state))
    if "wiki"   in tools_needed: sends.append(Send("wiki_node",   state))
    if "tavily" in tools_needed: sends.append(Send("tavily_node", state))

    print(f"[ROUTER] Dispatching {len(sends)} parallel retrieval agents")
    return sends