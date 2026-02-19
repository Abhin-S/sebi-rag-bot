"""
CRAG (Corrective RAG) + Self-RAG Chain for SEBI Chatbot
─────────────────────────────────────────────────────────────────────────────
Implements the patterns from rag_from_scratch_15_to_18.ipynb:

1. Retrieve documents
2. Grade each document for relevance  (CRAG)
3. If too few relevant → reformulate query and re-retrieve
4. Generate answer from relevant context
5. Grade answer for hallucination     (Self-RAG)
6. Return answer + confidence + sources
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from retriever import SEBIRetriever


class SEBIRAGChain:
    """End-to-end CRAG pipeline for SEBI regulatory queries."""

    def __init__(self, llm, retriever: SEBIRetriever):
        self.llm = llm
        self.retriever = retriever

        # ── Relevance grading prompt ──────────────────────────────────────
        self.relevance_prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You are a grader assessing whether a retrieved document is "
                "relevant to a user question about SEBI regulations.\n"
                "If the document contains ANY information useful for answering "
                "the question, respond with exactly: relevant\n"
                "Otherwise respond with exactly: not_relevant\n"
                "Output ONLY one word. No explanation.",
            ),
            (
                "human",
                "Document excerpt:\n{document}\n\nQuestion: {question}",
            ),
        ])

        # ── Hallucination check prompt ────────────────────────────────────
        self.hallucination_prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You are a grader assessing whether an answer is grounded "
                "in the provided source documents.\n"
                "If all or nearly all claims in the answer can be traced to "
                "the documents, respond with exactly: grounded\n"
                "If the answer is mostly supported but has minor "
                "unsupported elaborations, respond with exactly: partial\n"
                "If major claims in the answer are fabricated or clearly "
                "not in the documents, respond with exactly: not_grounded\n"
                "Output ONLY one word. No explanation.",
            ),
            (
                "human",
                "Source documents:\n{documents}\n\nAnswer:\n{answer}",
            ),
        ])

        # ── Main RAG generation prompt ────────────────────────────────────
        self.rag_prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You are a specialized SEBI (Securities and Exchange Board of "
                "India) regulatory assistant.\n\n"
                "Rules:\n"
                "1. Answer ONLY based on the provided context.\n"
                "2. Cite the source document name and section when possible.\n"
                "3. If the context contains tables, preserve their structure "
                "   in your response using Markdown tables.\n"
                "4. Use exact regulatory language where appropriate.\n"
                "5. Distinguish between ACTIVE and SUPERSEDED regulations.\n"
                "6. If the answer is not present in the context, say so "
                "   clearly — do NOT make up information.\n"
                "{definitions}",
            ),
            (
                "human",
                "── Matched chunks (most relevant) ──────────────────────\n"
                "{child_context}\n\n"
                "── Broader context (parent chunks) ─────────────────────\n"
                "{parent_context}\n\n"
                "Question: {question}\n\n"
                "Provide a comprehensive, well-structured answer.",
            ),
        ])

    # ══════════════════════════════════════════════════════════════════════
    #  GRADING
    # ══════════════════════════════════════════════════════════════════════

    def grade_relevance(self, docs, question: str) -> list:
        """Return only the documents deemed relevant to the question."""
        chain = self.relevance_prompt | self.llm | StrOutputParser()
        relevant = []

        for doc in docs:
            try:
                result = chain.invoke({
                    "document": doc.page_content[:800],
                    "question": question,
                })
                text = result.strip().lower()
                if "not_relevant" not in text and "relevant" in text:
                    relevant.append(doc)
            except Exception:
                relevant.append(doc)  # include on error to be safe

        return relevant if relevant else docs  # never return empty

    def check_hallucination(self, answer: str, context: str) -> str:
        """Check whether the generated answer is grounded in source context."""
        chain = self.hallucination_prompt | self.llm | StrOutputParser()
        # Use up to 6000 chars of the actual generation context
        doc_text = context[:6000]
        try:
            result = chain.invoke({
                "documents": doc_text,
                "answer": answer,
            })
            text = result.strip().lower()
            if "not_grounded" in text:
                return "not_grounded"
            if "partial" in text:
                return "partial"
            if "grounded" in text:
                return "grounded"
            return "unknown"
        except Exception:
            return "unknown"

    # ══════════════════════════════════════════════════════════════════════
    #  GENERATION
    # ══════════════════════════════════════════════════════════════════════

    def generate_answer(self, question: str, retrieval_result: dict) -> str:
        chain = self.rag_prompt | self.llm | StrOutputParser()
        return chain.invoke({
            "question": question,
            "child_context": retrieval_result["child_context"] or "(no child context)",
            "parent_context": retrieval_result["parent_context"] or "(no parent context)",
            "definitions": retrieval_result.get("definitions", ""),
        })

    # ══════════════════════════════════════════════════════════════════════
    #  FULL CRAG PIPELINE
    # ══════════════════════════════════════════════════════════════════════

    def query(self, question: str) -> dict:
        """
        Complete query flow:
        retrieve → grade → (re-retrieve?) → generate → hallucination check
        """
        # ── Step 1: Retrieve ──────────────────────────────────────────────
        retrieval = self.retriever.retrieve(question)
        child_docs = retrieval["child_docs"]

        if not child_docs:
            return {
                "answer": (
                    "I could not find relevant information in the SEBI "
                    "regulatory documents for your question. Please try "
                    "rephrasing or ask about a specific regulation."
                ),
                "sources": [],
                "confidence": "no_results",
                "hallucination_check": "n/a",
                "queries_used": retrieval["queries_used"],
                "num_relevant": 0,
                "num_retrieved": 0,
            }

        # ── Step 2: Grade relevance (CRAG) ────────────────────────────────
        relevant_docs = self.grade_relevance(child_docs, question)

        # ── Step 3: Re-retrieve if too few relevant docs ──────────────────
        if (
            len(relevant_docs) < 2
            and retrieval.get("metadata_filter")
        ):
            retry = self.retriever.retrieve(question)
            extra = self.grade_relevance(retry["child_docs"], question)
            seen_ids = {
                d.metadata.get("child_id") for d in relevant_docs
            }
            for doc in extra:
                if doc.metadata.get("child_id") not in seen_ids:
                    relevant_docs.append(doc)
            # Merge contexts
            retrieval["child_context"] += "\n\n---\n\n" + retry["child_context"]
            retrieval["parent_context"] += "\n\n---\n\n" + retry["parent_context"]

        # ── Step 4: Generate answer ───────────────────────────────────────
        answer = self.generate_answer(question, retrieval)

        # ── Step 5: Hallucination check (Self-RAG) ────────────────────────
        full_context = (
            retrieval["child_context"] + "\n\n" + retrieval["parent_context"]
        )
        hall = self.check_hallucination(answer, full_context)

        confidence = {
            "grounded": "high",
            "partial": "medium",
            "unknown": "medium",
            "not_grounded": "low",
        }.get(hall, "medium")

        if hall == "not_grounded":
            answer += (
                "\n\n⚠️ *Note: Parts of this answer may not be directly "
                "supported by the source documents. Please verify against "
                "the original SEBI circulars.*"
            )

        # ── Sources ───────────────────────────────────────────────────────
        sources = []
        seen_src = set()
        for doc in relevant_docs:
            src = doc.metadata.get("source", "Unknown")
            if src not in seen_src:
                seen_src.add(src)
                sources.append({
                    "file": src,
                    "section": doc.metadata.get("section", ""),
                    "date": doc.metadata.get("date", ""),
                    "audience": doc.metadata.get("audience", ""),
                    "status": doc.metadata.get("status", ""),
                    "pages": doc.metadata.get("pages", ""),
                })

        return {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
            "hallucination_check": hall,
            "queries_used": retrieval["queries_used"],
            "num_relevant": len(relevant_docs),
            "num_retrieved": len(child_docs),
        }
