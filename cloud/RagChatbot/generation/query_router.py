"""
LLM-based query router for the RAG chatbot.

Classifies incoming queries to determine if they need vector database retrieval,
or if they can be answered directly (e.g., greetings, out of scope, navigational).
"""

import json
import logging
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from RagChatbot.config import rag_settings

logger = logging.getLogger(__name__)

# The manifest of information we actually have in the database.
KNOWLEDGE_BASE_MANIFEST = [
    "Admissions",
    "Programmes and courses",
    "Fees and scholarships",
    "Student life",
    "Contact information",
    "FAQs",
    "International students",
    "Faculties and schools",
    "Academic policies",
    "News and events"
]

class RouteClassification(BaseModel):
    category: str = Field(description="The classification category of the query.")
    clarification_question: str | None = Field(
        default=None, 
        description="If category is UNCLEAR, provide a short clarifying question."
    )

def classify_query(query: str) -> RouteClassification:
    """
    Classifies the user query into one of the supported categories.
    
    Returns a RouteClassification object.
    """
    manifest_str = "\n".join([f"- {item}" for item in KNOWLEDGE_BASE_MANIFEST])
    
    system_instruction = f"""
You are a highly accurate query routing assistant for a university chatbot (Quest International University).
Your job is to analyze the user's query and classify it into exactly ONE of the following categories:

- GREETING: The user is saying hi, hello, or engaging in simple small talk (e.g., "how are you").
- CAPABILITY: The user is asking what you can do, what you know, or how you can help.
- NAVIGATIONAL: The user is asking for physical directions or locations on campus (e.g., "where is the library?", "how do I get to the cafeteria?").
- UNIVERSITY_INFO: The user is asking a substantive question that likely requires searching the university database.
  The database contains information on:
{manifest_str}
- OUT_OF_SCOPE: The user is asking a substantive question that is completely unrelated to the university (e.g., coding help, live sports, general world trivia).
- UNCLEAR: The query is a single ambiguous word (e.g., "fees", "help", "science") or incomplete thought where you need more context to search effectively.

If the category is UNCLEAR, you MUST provide a short, polite `clarification_question` asking the user what specific aspect they want to know about. Otherwise, set it to null.

Output your response strictly as a JSON object matching this schema:
{{
    "category": "GREETING | CAPABILITY | NAVIGATIONAL | UNIVERSITY_INFO | OUT_OF_SCOPE | UNCLEAR",
    "clarification_question": "string or null"
}}
Do NOT wrap the JSON in markdown code blocks.
"""

    # We use a low temperature for deterministic routing.
    try:
        client = genai.Client(api_key=rag_settings.GOOGLE_API_KEY)

        response = client.models.generate_content(
            model=rag_settings.LLM_MODEL,
            contents=query,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )

        raw_text = response.text.strip()
        
        data = json.loads(raw_text)
        category = data.get("category", "UNIVERSITY_INFO") # default fallback
        clarification = data.get("clarification_question")
        
        # Guardrail against hallucinatory categories
        valid_categories = {"GREETING", "CAPABILITY", "NAVIGATIONAL", "UNIVERSITY_INFO", "OUT_OF_SCOPE", "UNCLEAR"}
        if category not in valid_categories:
            logger.warning(f"Router returned invalid category: {category}. Falling back to UNIVERSITY_INFO.")
            category = "UNIVERSITY_INFO"
            
        logger.info(f"Query Router classified '{query}' as {category}")
        return RouteClassification(category=category, clarification_question=clarification)
        
    except Exception as exc:
        logger.error(f"Query router LLM call failed: {exc}. Falling back to UNIVERSITY_INFO.")
        # If the router fails, default to running the RAG pipeline so the user still gets a chance at an answer.
        return RouteClassification(category="UNIVERSITY_INFO")


def get_capabilities_summary() -> str:
    """Returns a natural language summary of the knowledge base manifest."""
    topics = ", ".join([t.lower() for t in KNOWLEDGE_BASE_MANIFEST[:-1]])
    last_topic = KNOWLEDGE_BASE_MANIFEST[-1].lower()
    return f"I can help answer questions about {topics}, and {last_topic} available in the university documents."
