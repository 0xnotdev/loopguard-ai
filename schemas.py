from enum import Enum
from pydantic import BaseModel
from typing import List, Dict, Any

class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class SessionWindow(BaseModel):
    session_id: str
    embeddings: List[List[float]]
    error_outputs: List[str]
    state: CircuitBreakerState
    iteration_count: int

class LoopDetectedError(Exception):
    def __init__(self, session_id: str, similarity: float):
        self.session_id = session_id
        self.similarity = similarity
        self.message = f"Loop Detected! Session {session_id} blocked. Similarity: {similarity:.4f}"
        super().__init__(self.message)

class ProxyRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    session_id: str