"""
Demonstration: Gemma 3 27B WITHOUT RAG context
────────────────────────────────────────────────
Sends the same questions directly to Gemma 3 via Google AI Studio
with NO retrieval, NO context — just the raw LLM.

Compare these responses to the RAG chatbot to show why
retrieval-augmented generation is necessary for domain-specific
regulatory questions.

Usage:
    python demo_no_rag.py
"""

import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ── Questions that expose the gap between plain LLM and RAG ──────────────────
QUESTIONS = [
    # Q1: Highly specific — requires exact SEBI circular content
    "What is the compensation mechanism for investor grievances against "
    "stock brokers as per SEBI Master Circulars?",

    # Q2: Table-heavy — RAG preserves table structure, plain LLM will hallucinate numbers
    "What are the net worth requirements and fees for different categories "
    "of Research Analysts as specified in the SEBI Master Circular?",

    # Q3: Cross-document — needs awareness of ACTIVE vs SUPERSEDED circulars
    "Which SEBI Master Circulars for Stock Brokers are currently active and "
    "which ones have been superseded? List the circular dates.",
]


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GOOGLE_API_KEY in your .env file first.")
        return

    client = genai.Client(api_key=api_key)
    model = "gemma-3-27b-it"

    print("=" * 70)
    print("  DEMO: Gemma 3 27B — NO RAG CONTEXT (plain LLM)")
    print("=" * 70)

    for i, question in enumerate(QUESTIONS, 1):
        print(f"\n{'─' * 70}")
        print(f"  Question {i}: {question}")
        print(f"{'─' * 70}\n")

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=question)],
            ),
        ]

        config = types.GenerateContentConfig(
            temperature=0.1,
        )

        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            print(response.text)
        except Exception as e:
            print(f"  [Error: {e}]")

        print()

    print("=" * 70)
    print("  END OF DEMO")
    print("=" * 70)
    print(
        "\nCompare these responses with the RAG chatbot (streamlit run app.py)."
        "\nThe RAG system will cite specific circular names, sections, dates,"
        "\nand preserve table structures — none of which the plain LLM can do."
    )


if __name__ == "__main__":
    main()
