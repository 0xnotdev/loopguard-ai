from sentence_transformers import SentenceTransformer
import functools

@functools.lru_cache(maxsize=1)
def get_model():
    # Loads once into RAM — 43MB, ~15ms encode time afterward
    return SentenceTransformer('all-MiniLM-L6-v2')

def embed_request(messages: list) -> list:
    model = get_model()

    # Walk messages in reverse to find most recent agent action
    latest_content = ""

    for msg in reversed(messages):
        latest_content += str(msg.get("content", ""))

        if "tool_calls" in msg:
            # Include tool execution arguments
            latest_content += str(msg["tool_calls"])
            break

    # Convert numpy array -> normal Python list
    embedding = model.encode(latest_content).tolist()

    return embedding