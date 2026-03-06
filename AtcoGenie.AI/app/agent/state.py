"""
AtcoGenie AI Engine — Agent State Definition

Defines the LangGraph state schema and the base agent structure.
State includes message history, security context, and tool outputs.
"""

from typing import Annotated, Sequence, TypedDict, List, Dict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from app.security.context import SecurityContext


class AgentState(TypedDict):
    """
    Current state of the LangGraph agent.
    Reducers (Annotated) define how new values are merged.
    """
    # Messages in the conversation (new messages are appended)
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Security context injected at startup (AD identity, roles, etc.)
    security_context: SecurityContext
    
    # Track which system is currently being used (pharma, sap, etc.)
    current_system: str
    
    # Store intermediate SQL queries or data for auditing
    sql_audit_log: List[Dict]
    
    # Critical flags
    is_authorized: bool
    error_message: str


class AgentOutput(TypedDict):
    """Schema for the final output returned to the API."""
    answer: str
    sources: List[str]
    system_queried: str
    intermediate_steps: List[Dict]
