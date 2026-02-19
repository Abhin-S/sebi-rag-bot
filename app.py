"""
SEBI Regulatory Assistant — Streamlit Chat Interface
─────────────────────────────────────────────────────────────────────────────
Run:  streamlit run app.py
"""

import os
import json
import streamlit as st
from config import CHROMA_DIR, CIRCULAR_INDEX_PATH, LLM_MODEL, LLM_FALLBACK, LLM_TEMPERATURE


# ═══════════════════════════════════════════════════════════════════════════════
#  INITIALISATION
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def init_rag():
    """Initialise LLM, retriever, and RAG chain (cached across reruns)."""

    from langchain_google_genai import ChatGoogleGenerativeAI
    from retriever import SEBIRetriever
    from rag_chain import SEBIRAGChain

    # Try primary model, fall back if unavailable
    try:
        llm = ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            convert_system_message_to_human=True,
        )
        llm.invoke("ping")
        model_used = LLM_MODEL
    except Exception:
        llm = ChatGoogleGenerativeAI(
            model=LLM_FALLBACK,
            temperature=LLM_TEMPERATURE,
            convert_system_message_to_human=True,
        )
        model_used = LLM_FALLBACK

    retriever = SEBIRetriever(llm)
    chain = SEBIRAGChain(llm, retriever)
    return chain, model_used


# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.header("📊 Knowledge Base")

        if CIRCULAR_INDEX_PATH.exists():
            with open(CIRCULAR_INDEX_PATH, "r", encoding="utf-8") as f:
                idx = json.load(f)
            active = sum(1 for d in idx if d.get("status") == "ACTIVE")
            superseded = sum(1 for d in idx if d.get("status") == "SUPERSEDED")
            st.metric("Total Documents", len(idx))
            col1, col2 = st.columns(2)
            col1.metric("Active", active)
            col2.metric("Superseded", superseded)

            with st.expander("Active document topics"):
                for d in idx:
                    if d.get("status") == "ACTIVE":
                        st.markdown(f"• {d.get('subject', d.get('title', ''))}")
        else:
            st.warning("Index not built yet.\nRun `python build_index.py`")

        st.markdown("---")
        st.markdown(
            "**Powered by**\n"
            "- Gemma 3 / Gemma 2 via Google AI\n"
            "- LangChain + ChromaDB\n"
            "- Sentence Transformers"
        )




# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="SEBI Regulatory Assistant",
        page_icon="📋",
        layout="wide",
    )
    # Hide Streamlit deploy button and hamburger menu
    st.markdown(
        """
        <style>
        .stDeployButton {display: none;}
        #MainMenu {display: none;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("📋 SEBI Regulatory Assistant")
    st.caption(
        "RAG chatbot over 25 SEBI Master Circulars · "
        "CRAG pipeline · Table-aware retrieval"
    )

    render_sidebar()

    # ── Pre-flight checks ─────────────────────────────────────────────────
    if not CHROMA_DIR.exists():
        st.error(
            "**Vector store not found.**\n\n"
            "Run the following command first:\n```\npython build_index.py\n```"
        )
        return

    if not os.getenv("GOOGLE_API_KEY"):
        st.error(
            "**GOOGLE_API_KEY not found.**\n\n"
            "Add your key to the `.env` file:\n"
            "```\nGOOGLE_API_KEY=your_key_here\n```"
        )
        return

    # ── Initialise RAG ────────────────────────────────────────────────────
    if "rag_chain" not in st.session_state:
        with st.spinner("Loading SEBI knowledge base & LLM..."):
            try:
                chain, model_used = init_rag()
                st.session_state.rag_chain = chain
                st.session_state.model_used = model_used
            except Exception as e:
                st.error(f"Initialisation failed: {e}")
                return

    # ── Chat history ──────────────────────────────────────────────────────
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander("📄 Sources"):
                    for src in msg["sources"]:
                        status_icon = "🟢" if src.get("status") == "ACTIVE" else "🟡"
                        st.markdown(
                            f"{status_icon} **{src['file']}**  \n"
                            f"   Date: {src.get('date', 'N/A')} · "
                            f"Section: {src.get('section', 'N/A')} · "
                            f"Pages: {src.get('pages', 'N/A')}"
                        )
            if msg.get("confidence"):
                conf = msg["confidence"]
                icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")
                st.caption(
                    f"{icon} Confidence: {conf} · "
                    f"Model: {st.session_state.get('model_used', '?')}"
                )

    # ── Chat input ────────────────────────────────────────────────────────
    if question := st.chat_input("Ask about SEBI regulations..."):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Searching regulatory documents..."):
                try:
                    result = st.session_state.rag_chain.query(question)
                    answer = result["answer"]
                    sources = result.get("sources", [])
                    confidence = result.get("confidence", "unknown")

                    st.markdown(answer)

                    if sources:
                        with st.expander("📄 Sources"):
                            for src in sources:
                                status_icon = (
                                    "🟢" if src.get("status") == "ACTIVE" else "🟡"
                                )
                                st.markdown(
                                    f"{status_icon} **{src['file']}**  \n"
                                    f"   Date: {src.get('date', 'N/A')} · "
                                    f"Section: {src.get('section', 'N/A')} · "
                                    f"Pages: {src.get('pages', 'N/A')}"
                                )

                    conf_icon = {
                        "high": "🟢", "medium": "🟡",
                        "low": "🔴", "no_results": "⚪",
                    }.get(confidence, "⚪")
                    st.caption(
                        f"{conf_icon} Confidence: {confidence} · "
                        f"Relevant: {result.get('num_relevant', 0)}"
                        f"/{result.get('num_retrieved', 0)} docs · "
                        f"Model: {st.session_state.get('model_used', '?')}"
                    )

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                        "confidence": confidence,
                    })

                except Exception as e:
                    error_msg = f"An error occurred: {e}"
                    st.error(error_msg)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"❌ {error_msg}",
                    })


if __name__ == "__main__":
    main()
