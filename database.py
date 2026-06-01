import asyncpg
from pgvector.asyncpg import register_vector
import os

async def get_pool():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])

    async with pool.acquire() as conn:
        await conn.execute('CREATE EXTENSION IF NOT EXISTS vector')

        await register_vector(conn)

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS session_windows (
                id SERIAL PRIMARY KEY,
                session_id TEXT,
                embedding VECTOR(384),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

    return pool


async def upsert_and_check_similarity(
    pool,
    session_id: str,
    current_embedding: list
) -> float:

    async with pool.acquire() as conn:
        await register_vector(conn)

        # Find highest cosine similarity
        row = await conn.fetchrow('''
            SELECT 1 - (embedding <=> $1::vector) AS similarity
            FROM session_windows
            WHERE session_id = $2
            ORDER BY similarity DESC
            LIMIT 1
        ''', current_embedding, session_id)

        max_sim = row['similarity'] if row else 0.0

        # Insert current embedding
        await conn.execute('''
            INSERT INTO session_windows (session_id, embedding)
            VALUES ($1, $2::vector)
        ''', session_id, current_embedding)

        # Keep only latest 5 embeddings
        await conn.execute('''
            DELETE FROM session_windows
            WHERE id NOT IN (
                SELECT id
                FROM session_windows
                WHERE session_id = $1
                ORDER BY created_at DESC
                LIMIT 5
            )
            AND session_id = $1
        ''', session_id)

        return max_sim