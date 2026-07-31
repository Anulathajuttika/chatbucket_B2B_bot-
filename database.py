"""
MongoDB: permanent chat history storage.
"""
import logging
from datetime import datetime, timezone

from pymongo import MongoClient

import config

logger = logging.getLogger("database")

# --- MongoDB client ---
# Short timeouts so a down/unreachable MongoDB fails fast (~3s) instead of
# the pymongo default of up to 30s per call -- with both a history read and
# a history write on the /chat critical path, the 30s default meant a dead
# MongoDB added up to 60s to every single response.
mongo_client = MongoClient(
    config.MONGO_URI,
    serverSelectionTimeoutMS=3000,
    connectTimeoutMS=3000,
    socketTimeoutMS=3000,
)
mongo_db = mongo_client[config.MONGO_DB_NAME]
chat_collection = mongo_db[config.MONGO_COLLECTION_NAME]


def get_session_history(session_id: str, limit: int = 10) -> list[dict]:
    """Return the last `limit` turns for a session, oldest first, from MongoDB."""
    try:
        cursor = chat_collection.find({"session_id": session_id}).sort("timestamp", -1).limit(limit)
        turns = list(cursor)[::-1]  # reverse to chronological order
        return [{"user_message": t["user_message"], "bot_response": t["bot_response"]} for t in turns]
    except Exception as e:
        logger.error(f"MongoDB read error: {e}")
        return []


def save_to_mongo(session_id: str, user_message: str, bot_response: str) -> None:
    """Persist the full chat turn permanently in MongoDB."""
    try:
        chat_collection.insert_one({
            "session_id": session_id,
            "user_message": user_message,
            "bot_response": bot_response,
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.error(f"MongoDB write error: {e}")