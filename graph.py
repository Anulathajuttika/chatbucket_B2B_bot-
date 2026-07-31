"""
LangGraph pipeline:

    START -> retrieve_context -> generate_answer -> END
"""
import logging
from typing import TypedDict, List

from langgraph.graph import StateGraph, START, END
from openai import OpenAI

import config
from retriever import retrieve_context
from prompt import build_messages

logger = logging.getLogger("graph")
client = OpenAI(api_key=config.OPEN_AI_API_KEY)


class ChatState(TypedDict):
    session_id: str
    question: str
    history: List[dict]
    context: str
    answer: str


def retrieve_context_node(state: ChatState) -> ChatState:
    """Node 1: retrieve relevant chunks from ChromaDB for the user's question."""
    chunks = retrieve_context(state["question"])
    state["context"] = "\n\n---\n\n".join(chunks) if chunks else ""
    logger.info(f"Retrieved {len(chunks)} chunk(s) for session {state['session_id']}")
    return state


def generate_answer_node(state: ChatState) -> ChatState:
    """Node 2: call OpenAI to generate an answer grounded in the retrieved context."""
    try:
        messages = build_messages(state["context"], state["question"], state.get("history", []))
        response = client.chat.completions.create(
            model=config.CHAT_MODEL,
            messages=messages,
            temperature=config.TEMPERATURE,
        )
        state["answer"] = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"OpenAI generation failed: {e}")
        state["answer"] = "Sorry, something went wrong while generating a response. Please try again."
    return state


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("retrieve_context", retrieve_context_node)
    graph.add_node("generate_answer", generate_answer_node)

    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "generate_answer")
    graph.add_edge("generate_answer", END)

    return graph.compile()


# compiled once at import time and reused across requests
chat_graph = build_graph()


def run_chat(session_id: str, question: str, history: list) -> str:
    """Invoke the compiled graph and return the final answer string."""
    result = chat_graph.invoke({
        "session_id": session_id,
        "question": question,
        "history": history,
        "context": "",
        "answer": "",
    })
    return result["answer"]