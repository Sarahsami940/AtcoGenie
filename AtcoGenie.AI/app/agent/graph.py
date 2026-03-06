"""
AtcoGenie AI Engine — Core LangGraph Agent

Defines the graph nodes, edges, and decision logic.
Implements the RAG + SQL + Security flow.
"""

from typing import Literal
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

from app.agent.state import AgentState
from app.models.factory import get_llm
from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class AtcoGenieAgent:
    def __init__(self, settings: Settings, checkpointer: PostgresSaver = None):
        self.settings = settings
        self.llm = get_llm(settings)
        self.checkpointer = checkpointer
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Construct the LangGraph workflow."""
        workflow = StateGraph(AgentState)

        # 1. Define Nodes
        workflow.add_node("orchestrator", self.orchestrator_node)
        # TODO: workflow.add_node("sql_generator", self.sql_generator_node)
        # TODO: workflow.add_node("data_summarizer", self.summarizer_node)

        # 2. Define Edges
        workflow.add_edge(START, "orchestrator")
        
        # We start with just the orchestrator for now
        workflow.add_edge("orchestrator", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def orchestrator_node(self, state: AgentState) -> dict:
        """
        Initial node: Analyzes intent and verifies security access.
        Decides if we need SQL, RAG, or a direct answer.
        """
        ctx = state["security_context"]
        last_message = state["messages"][-1].content
        
        logger.info("orchestrator_processing", user=ctx.user_id, accessible_systems=ctx.accessible_systems)

        # Simple system prompt for the orchestrator
        prompt = [
            SystemMessage(content=(
                f"You are AtcoGenie AI Orchestrator. You help employees query enterprise data. "
                f"User Profile: {ctx.display_name} ({ctx.department}). "
                f"Accessible Systems: {', '.join(ctx.accessible_systems)}. "
                "Decide if the user request requires a database query. "
                "If yes, specify which system (pharma/sap). If no, answer directly."
            )),
            *state["messages"]
        ]
        
        # For now, we just pass through to demonstrate flow
        response = await self.llm.ainvoke(prompt)
        
        return {
            "messages": [response],
            "is_authorized": True
        }

    async def run(self, input_text: str, config: dict, security_context: "SecurityContext"):
        """Entry point to run the agent."""
        initial_state = {
            "messages": [HumanMessage(content=input_text)],
            "security_context": security_context,
            "current_system": "",
            "sql_audit_log": [],
            "is_authorized": False,
            "error_message": ""
        }
        
        final_state = await self.graph.ainvoke(initial_state, config=config)
        return final_state
