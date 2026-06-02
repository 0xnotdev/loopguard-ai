
from sentence_transformers import SentenceTransformer

model = None


def get_model():

    global model

    if model is None:

        print("Loading embedding model...")

        model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2"
        )

        print("✓ Embedding model loaded")

    return model


def embed_request(messages):

    model = get_model()

    combined = " ".join(
        msg["content"]
        for msg in messages
        if "content" in msg
    )

    embedding = model.encode(combined)

    return embedding.tolist()

