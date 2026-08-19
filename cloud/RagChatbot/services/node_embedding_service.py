"""Node embedding synchronization and auto-population service for campus navigation."""

from __future__ import annotations

import logging
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text

logger = logging.getLogger("RagChatbot.services.node_embedding_service")


def sync_missing_node_embeddings(db: Session, force_reembed: bool = False) -> int:
    """Check for campus nodes missing vector embeddings and generate them in batch.

    Args:
        db: Active SQLAlchemy database session.
        force_reembed: If True, re-generates embeddings for all nodes.

    Returns:
        Number of newly created node embeddings.
    """
    if db is None:
        return 0

    try:
        from app.models.models import Node, NodeEmbedding, Floorplan, Building
        from RagChatbot.embeddings.google_embedding_service import embed_text
    except Exception as exc:
        logger.warning("Could not import models or embedding service: %s", exc)
        return 0

    # Ensure table exists in database if not created yet
    try:
        from app.core.database import Base, engine
        Base.metadata.create_all(bind=engine, tables=[NodeEmbedding.__table__])
    except Exception as exc:
        logger.debug("Table check: %s", exc)

    try:
        nodes = (
            db.query(Node)
            .options(joinedload(Node.floorplan).joinedload(Floorplan.building))
            .filter(Node.room_label.isnot(None), Node.room_label != "")
            .all()
        )
        if not nodes:
            return 0

        existing_ids = set()
        if not force_reembed:
            existing_embeddings = db.query(NodeEmbedding.node_id).all()
            existing_ids = {row[0] for row in existing_embeddings}

        missing_nodes = [n for n in nodes if n.node_id not in existing_ids]
        if not missing_nodes:
            logger.debug("All %d navigable nodes have vector embeddings.", len(nodes))
            return 0

        logger.info("Found %d nodes requiring vector embeddings.", len(missing_nodes))
        created_count = 0

        for node in missing_nodes:
            label = str(node.room_label or "").strip()
            if not label:
                continue

            node_type = str(node.node_type or "OTHER")
            building_name = ""
            floor_str = ""
            if node.floorplan:
                if node.floorplan.building:
                    building_name = getattr(node.floorplan.building, "building_name", "") or ""
                if node.floorplan.floor_level is not None:
                    floor_str = f"Level {node.floorplan.floor_level}"

            # Rich semantic prompt for cross-lingual vector alignment
            semantic_text = f"{label} ({node_type})"
            if floor_str or building_name:
                semantic_text += f" - {floor_str} {building_name}".strip()

            try:
                vector = embed_text(semantic_text)
                if not vector:
                    continue

                if force_reembed and node.node_id in existing_ids:
                    db.query(NodeEmbedding).filter(NodeEmbedding.node_id == node.node_id).update({
                        "embedding": vector,
                        "model_version": "gemini-embedding-2"
                    })
                else:
                    new_emb = NodeEmbedding(
                        node_id=node.node_id,
                        embedding=vector,
                        model_version="gemini-embedding-2"
                    )
                    db.add(new_emb)
                created_count += 1
            except Exception as emb_err:
                logger.error("Failed to generate embedding for node %d (%s): %s", node.node_id, label, emb_err)

        db.commit()
        logger.info("Successfully populated %d node embeddings into database.", created_count)
        return created_count

    except Exception as exc:
        db.rollback()
        logger.error("Error during node embedding synchronization: %s", exc)
        return 0
