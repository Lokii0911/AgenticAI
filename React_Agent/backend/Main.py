from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse, FileResponse
from starlette.middleware.cors import CORSMiddleware
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage
import json
import os
import uuid
from typing import Optional
from dotenv import load_dotenv
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
# ── Import all agents ──
from Orchestration import ResearchState
from PlannerAgent import planner_node
from RetrievalAgent import arxiv_node, wiki_node, tavily_node, retrieval_router
from Synthesizer import synthesizer_node
from CriticAgent import critic_node, critic_router
from ReportAgent import report_generator_node

load_dotenv()

# ─────────────────────────────────────────────
#  API KEY AUTH
# ─────────────────────────────────────────────
REPORT_STORE = {}
NEXUS_API_KEY = os.environ.get("NEXUS_API_KEY")
if not NEXUS_API_KEY:
    raise RuntimeError("NEXUS_API_KEY is not set in .env")

print(f"\n✓ NEXUS API KEY loaded\n")

def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key.")
    if x_api_key != NEXUS_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key.")


# ─────────────────────────────────────────────
#  BUILD LANGGRAPH
# ─────────────────────────────────────────────
builder = StateGraph(ResearchState)

# ── Register all nodes ──
builder.add_node("planner",          planner_node)
builder.add_node("arxiv_node",       arxiv_node)
builder.add_node("wiki_node",        wiki_node)
builder.add_node("tavily_node",      tavily_node)
builder.add_node("synthesizer",      synthesizer_node)
builder.add_node("critic",           critic_node)
builder.add_node("report_generator", report_generator_node)

# ── Wire the edges ──
builder.add_edge(START, "planner")

# Router fans out directly from planner via Send()
builder.add_conditional_edges(
    "planner",
    retrieval_router,
    ["arxiv_node", "wiki_node", "tavily_node"]
)

# All retrieval nodes join at synthesizer
builder.add_edge("arxiv_node",  "synthesizer")
builder.add_edge("wiki_node",   "synthesizer")
builder.add_edge("tavily_node", "synthesizer")

# Synthesizer → Critic
builder.add_edge("synthesizer", "critic")

# Critic → conditional route
builder.add_conditional_edges(
    "critic",
    critic_router,
    {
        "report_generator": "report_generator",
        "retrieval_router": "planner",
    }
)

# Report Generator → END
builder.add_edge("report_generator", END)

# ── Compile ──
graph = builder.compile()
print("✓ LangGraph compiled successfully\n")

# Save graph visualization
try:
    png_data = graph.get_graph().draw_mermaid_png()
    with open("graph.png", "wb") as f:
        f.write(png_data)
    print("✓ Graph saved to graph.png\n")
except Exception as e:
    print(f"⚠ Could not save graph PNG: {e}")


# ─────────────────────────────────────────────
#  FASTAPI APP
# ─────────────────────────────────────────────
app = FastAPI(title="Nexus Research API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "https://your-app.streamlit.app"   # ← update after deploying frontend
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

def create_pdf(text, session_id):
    PDF_DIR = "generated_pdfs"
    os.makedirs(PDF_DIR, exist_ok=True)

    file_path = os.path.join(PDF_DIR, f"{session_id}.pdf")

    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    elements = []
    for line in text.split("\n"):
        elements.append(Paragraph(line, styles["Normal"]))
        elements.append(Spacer(1, 10))

    doc.build(elements)
    return file_path



# ─────────────────────────────────────────────
#  ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    """Public — frontend pings this to check if server is up."""
    return {"status": "online"}


@app.post("/verify-key")
def verify_key(x_api_key: Optional[str] = Header(None)):
    """Frontend calls this to validate API key before allowing access."""
    verify_api_key(x_api_key)
    return {"valid": True}


@app.post("/ask_stream")
def ask_stream(req: dict, x_api_key: Optional[str] = Header(None)):
    """
    Main streaming endpoint.
    Runs the full multi-agent pipeline and streams events to frontend.

    Event types emitted:
      {"type": "agent",  "data": {"agent": "planner", "status": "done", ...}}
      {"type": "tool",   "data": {"name": "arxiv", "goal": "...", "score": 0.9}}
      {"type": "source", "data": "https://..."}
      {"type": "answer", "data": "<final report markdown>"}
      {"type": "meta",   "data": {"format": "full_paper", "critic_loops": 1}}
    """
    verify_api_key(x_api_key)

    query = req.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    session_id = str(uuid.uuid4())
    def event_generator():
        initial_state: ResearchState = {
            "query":             query,
            "tasks":             [],
            "report_format":     "",
            "planner_reasoning": "",
            "retrieval_results": [],
            "synthesis":         "",
            "critic_feedback":   "",
            "critic_loops":      0,
            "final_report":      "",
            "messages":          [HumanMessage(content=query)],
            "agent_status":      {},
        }

        emitted_tools   = set()
        emitted_sources = set()
        final_emitted   = False

        for event in graph.stream(initial_state, stream_mode="updates"):
            for node_name, node_output in event.items():

                # ── PLANNER ──
                if node_name == "planner":
                    yield json.dumps({
                        "type": "agent",
                        "data": {
                            "agent":      "planner",
                            "status":     "done",
                            "reasoning":  node_output.get("planner_reasoning", ""),
                            "task_count": len(node_output.get("tasks", []))
                        }
                    }) + "\n"

                # ── RETRIEVAL NODES ──
                elif node_name in ("arxiv_node", "wiki_node", "tavily_node"):
                    tool_name = node_name.replace("_node", "")

                    if tool_name not in emitted_tools:
                        emitted_tools.add(tool_name)
                        results = node_output.get("retrieval_results", [])
                        latest  = next(
                            (r for r in reversed(results) if r.get("source") == tool_name), {}
                        )
                        yield json.dumps({
                            "type": "tool",
                            "data": {
                                "name":  tool_name,
                                "goal":  latest.get("goal", ""),
                                "score": latest.get("score", 0)
                            }
                        }) + "\n"

                    # Emit tavily URLs as sources
                    for r in node_output.get("retrieval_results", []):
                        for url in r.get("urls", []):
                            if url not in emitted_sources:
                                emitted_sources.add(url)
                                yield json.dumps({
                                    "type": "source",
                                    "data": url
                                }) + "\n"

                # ── SYNTHESIZER ──
                elif node_name == "synthesizer":
                    yield json.dumps({
                        "type": "agent",
                        "data": {"agent": "synthesizer", "status": "done"}
                    }) + "\n"

                # ── CRITIC ──
                elif node_name == "critic":
                    feedback = node_output.get("critic_feedback", "")
                    loops    = node_output.get("critic_loops", 0)
                    yield json.dumps({
                        "type": "agent",
                        "data": {
                            "agent":    "critic",
                            "status":   "retry" if "RETRY" in feedback else "pass",
                            "loops":    loops,
                            "feedback": feedback[:150]
                        }
                    }) + "\n"

                # ── REPORT GENERATOR ──
                elif node_name == "report_generator":
                    final_report = node_output.get("final_report", "")
                    if final_report and not final_emitted:
                        final_emitted = True
                        REPORT_STORE[session_id] = final_report

                        yield json.dumps({
                            "type": "meta",
                            "data": {
                                "session_id": session_id,
                                "format":       node_output.get("report_format", "summary"),
                                "critic_loops": node_output.get("critic_loops", 0),
                            }
                        }) + "\n"
                        yield json.dumps({
                            "type": "answer",
                            "data": final_report
                        }) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

@app.get("/download_pdf/{session_id}")
def download_pdf(session_id: str):
    if session_id not in REPORT_STORE:
        raise HTTPException(status_code=404, detail="Report not found")

    text = REPORT_STORE[session_id]
    file_path = create_pdf(text, session_id)


    del REPORT_STORE[session_id]

    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename="research_report.pdf"
    )