"""
Advanced Retrieval for SEBI RAG
─────────────────────────────────────────────────────────────────────────────
• Multi-Query generation    (rag_from_scratch Part 5)
• RAG-Fusion / RRF scoring  (rag_from_scratch Part 6)
• Metadata filtering         (rag_from_scratch Part 10-11)
• Parent-child context lookup
• Definitions injection
"""

import json
from typing import Optional
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.load import dumps, loads
from config import (
    EMBEDDING_MODEL, CHROMA_DIR, CHILD_COLLECTION, DEFINITIONS_COLLECTION,
    PARENT_STORE_PATH, CIRCULAR_INDEX_PATH,
    TOP_K, MULTI_QUERY_COUNT, RRF_K,
)


class SEBIRetriever:
    """Retriever combining multi-query, fusion, metadata filtering,
    parent-child lookup, and definitions context."""

    def __init__(self, llm):
        self.llm = llm
        self.embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

        # ── Vector stores ─────────────────────────────────────────────────
        self.vectorstore = Chroma(
            collection_name=CHILD_COLLECTION,
            embedding_function=self.embeddings,
            persist_directory=str(CHROMA_DIR),
        )

        self.definitions_store = None
        try:
            self.definitions_store = Chroma(
                collection_name=DEFINITIONS_COLLECTION,
                embedding_function=self.embeddings,
                persist_directory=str(CHROMA_DIR),
            )
        except Exception:
            pass

        # ── Parent store (parent_id → full text) ─────────────────────────
        self.parent_store: dict[str, str] = {}
        if PARENT_STORE_PATH.exists():
            with open(PARENT_STORE_PATH, "r", encoding="utf-8") as f:
                self.parent_store = json.load(f)

        # ── Circular index ────────────────────────────────────────────────
        self.circular_index: list[dict] = []
        if CIRCULAR_INDEX_PATH.exists():
            with open(CIRCULAR_INDEX_PATH, "r", encoding="utf-8") as f:
                self.circular_index = json.load(f)

    # ══════════════════════════════════════════════════════════════════════
    #  MULTI-QUERY  (rag_from_scratch Part 5)
    # ══════════════════════════════════════════════════════════════════════

    def generate_multi_queries(self, question: str) -> list[str]:
        """Generate alternate phrasings of the user's question."""
        template = (
            "You are an AI assistant specializing in SEBI (Securities and Exchange "
            "Board of India) regulations.\n"
            "Generate {n} different versions of the given user question to help "
            "retrieve relevant regulatory documents from a vector database.\n"
            "Cover different angles: legal terminology, practical implications, "
            "and specific regulation names.\n\n"
            "Original question: {question}\n\n"
            "Provide the alternative questions, one per line. "
            "Do NOT number them."
        )
        prompt = ChatPromptTemplate.from_template(template)
        chain = (
            prompt
            | self.llm
            | StrOutputParser()
            | (lambda x: [q.strip() for q in x.strip().split("\n") if q.strip()])
        )

        try:
            alt_queries = chain.invoke({
                "question": question,
                "n": MULTI_QUERY_COUNT,
            })
            return [question] + alt_queries[: MULTI_QUERY_COUNT]
        except Exception as e:
            print(f"  [multi-query] fallback (error: {e})")
            return [question]

    # ══════════════════════════════════════════════════════════════════════
    #  RECIPROCAL RANK FUSION  (rag_from_scratch Part 6)
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def reciprocal_rank_fusion(
        result_lists: list[list], k: int = RRF_K
    ) -> list:
        """Merge multiple ranked lists into one via RRF scoring."""
        fused: dict[str, float] = {}
        for docs in result_lists:
            for rank, doc in enumerate(docs):
                key = dumps(doc)
                fused.setdefault(key, 0.0)
                fused[key] += 1.0 / (rank + k)

        reranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return [loads(doc_str) for doc_str, _ in reranked]

    # ══════════════════════════════════════════════════════════════════════
    #  METADATA FILTER  (rag_from_scratch Part 10-11)
    # ══════════════════════════════════════════════════════════════════════

    def build_metadata_filter(self, question: str) -> Optional[dict]:
        """Map keywords in the question to ChromaDB where-filters."""
        q = question.lower()

        audience_map = {
            "stock broker": "Stock Brokers",
            "mutual fund": "Mutual Funds",
            "depositor": "Depositories",
            "credit rating": "Credit Rating Agencies (CRAs)",
            "portfolio manager": "Portfolio Managers",
            "research analyst": "Research Analysts",
            "investment adviser": "Investment Advisers",
            "registrar": "Registrars to an Issue and Share Transfer Agents",
            "debenture trustee": "Debenture Trustees (DTs)",
            "stock exchange": "Stock Exchanges and Clearing Corporations",
            "clearing corporation": "Stock Exchanges and Clearing Corporations",
            "invit": "Infrastructure Investment Trusts (InvITs)",
            "reit": "Real Estate Investment Trusts (REITs)",
            "esg": "ESG Rating Providers (ERPs)",
            "social stock": "Social Stock Exchange",
            "listing obligation": "Listed Entities",
            "issue of capital": "Market Participants",
        }

        clauses: list[dict] = []

        for kw, aud in audience_map.items():
            if kw in q:
                clauses.append({"audience": aud})
                break

        if any(w in q for w in ("latest", "current", "most recent", "newest")):
            clauses.append({"is_latest": True})

        if any(w in q for w in ("active", "in force", "in effect")):
            clauses.append({"status": "ACTIVE"})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    # ══════════════════════════════════════════════════════════════════════
    #  PARENT CONTEXT LOOKUP
    # ══════════════════════════════════════════════════════════════════════

    def get_parent_context(self, child_docs) -> list[str]:
        """Fetch the broader parent chunk for each retrieved child."""
        seen, parents = set(), []
        for doc in child_docs:
            pid = doc.metadata.get("parent_id", "")
            if pid and pid not in seen:
                seen.add(pid)
                text = self.parent_store.get(pid, "")
                if text:
                    parents.append(text)
        return parents

    # ══════════════════════════════════════════════════════════════════════
    #  DEFINITIONS CONTEXT
    # ══════════════════════════════════════════════════════════════════════

    def get_definitions_context(self, question: str) -> str:
        """Pull relevant glossary / definition entries."""
        if not self.definitions_store:
            return ""
        try:
            results = self.definitions_store.similarity_search(question, k=3)
            if results:
                lines = "\n".join(f"• {d.page_content}" for d in results)
                return f"\n**Relevant Regulatory Definitions:**\n{lines}\n"
        except Exception:
            pass
        return ""

    # ══════════════════════════════════════════════════════════════════════
    #  MAIN RETRIEVE
    # ══════════════════════════════════════════════════════════════════════

    def retrieve(self, question: str) -> dict:
        """
        Full retrieval pipeline:
        multi-query → per-query search → RRF fusion → parent lookup → defs
        """
        # 1. Generate queries
        queries = self.generate_multi_queries(question)

        # 2. Metadata filter
        meta_filter = self.build_metadata_filter(question)

        # 3. Search for each query
        all_results: list[list] = []
        for q in queries:
            try:
                if meta_filter:
                    docs = self.vectorstore.similarity_search(
                        q, k=TOP_K, filter=meta_filter
                    )
                    # Fall back to unfiltered if too few
                    if len(docs) < 2:
                        docs = self.vectorstore.similarity_search(q, k=TOP_K)
                else:
                    docs = self.vectorstore.similarity_search(q, k=TOP_K)
                all_results.append(docs)
            except Exception as e:
                print(f"  [retrieval] error for '{q[:50]}': {e}")
                try:
                    all_results.append(
                        self.vectorstore.similarity_search(q, k=TOP_K)
                    )
                except Exception:
                    pass

        # 4. Fuse via RRF
        fused_docs = (
            self.reciprocal_rank_fusion(all_results)[: TOP_K]
            if all_results
            else []
        )

        # 5. Parent context
        parent_contexts = self.get_parent_context(fused_docs)

        # 6. Definitions
        definitions = self.get_definitions_context(question)

        # 7. Format context strings
        child_context = "\n\n---\n\n".join(
            f"[Source: {doc.metadata.get('source', '?')} | "
            f"Section: {doc.metadata.get('section', 'N/A')} | "
            f"Date: {doc.metadata.get('date', 'N/A')} | "
            f"Status: {doc.metadata.get('status', 'N/A')}]\n"
            f"{doc.page_content}"
            for doc in fused_docs
        )

        parent_context = "\n\n---\n\n".join(parent_contexts[:3])

        return {
            "child_docs": fused_docs,
            "child_context": child_context,
            "parent_context": parent_context,
            "definitions": definitions,
            "queries_used": queries,
            "metadata_filter": meta_filter,
        }
