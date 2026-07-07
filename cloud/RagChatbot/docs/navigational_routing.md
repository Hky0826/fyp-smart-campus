# Navigational Intent Routing

The Smart Campus RAG chatbot is designed to provide information from university documents. However, campus users frequently ask for physical directions or locations (e.g., "Where is the library?", "How do I get to the cafeteria?").

To handle these requests, the `query_router.py` module classifies such queries as having a `NAVIGATIONAL` intent.

## Current Behavior
Currently, when a `NAVIGATIONAL` query is detected, the `chat_service.py` pipeline bypasses the RAG database search and immediately returns a fast response placeholder:
```
"Navigational request detected. Routing to map module..."
```

## How to Connect It Later

To fully integrate this intent with a mapping or wayfinding module in the future, follow these steps:

### 1. Edge Device / Client Side Integration
The edge device can examine the returned text string or we can augment the `ChatResponse` model to return an explicit intent enum. If you want the edge device to switch from the chatbot UI to a map UI:

1. Update `ChatResponse` in `schemas.py`:
   ```python
   class ChatResponse(BaseModel):
       answer: str
       citations: List[CitationSchema]
       access_granted: bool
       status_message: str | None = None
       response_time_ms: int
       query_id: int | None = None
       intent: str = "DEFAULT"  # Add this field
   ```
2. In `chat_service.py`, set `intent="NAVIGATIONAL"` when returning the fast answer.
3. The edge device client should check `if response.intent == "NAVIGATIONAL":` and trigger the local Map UI instead of speaking the text.

### 2. Cloud-Side API Integration (Optional)
If the cloud needs to generate the route coordinates:
1. Create a `map_service.py` module that integrates with your campus GIS or indoor mapping API.
2. Inside `chat_service.py`, instead of returning a static string for `NAVIGATIONAL`, call `map_service.get_directions(sanitized_query)` and return the dynamic directions.

```python
elif route.category == "NAVIGATIONAL":
    from RagChatbot.services.map_service import get_directions
    fast_answer = get_directions(sanitized_query)
```
