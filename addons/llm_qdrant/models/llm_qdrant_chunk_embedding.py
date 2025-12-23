import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LLMQdrantChunkEmbedding(models.TransientModel):
    """Transient model to display Qdrant chunk embeddings.

    This model fetches embedding data from Qdrant server and displays it
    in Odoo views. Since Qdrant stores vectors externally, this is a
    read-only transient model that queries Qdrant on demand.
    """

    _name = "llm.qdrant.chunk.embedding"
    _description = "Qdrant Chunk Embedding"

    name = fields.Char(string="Name", readonly=True)
    chunk_id = fields.Many2one(
        "llm.knowledge.chunk",
        string="Chunk",
        readonly=True,
    )
    resource_id = fields.Many2one(
        "llm.resource",
        string="Resource",
        readonly=True,
    )
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Collection",
        readonly=True,
    )
    qdrant_point_id = fields.Integer(
        string="Qdrant Point ID",
        readonly=True,
    )
    qdrant_collection_name = fields.Char(
        string="Qdrant Collection",
        readonly=True,
    )
    store_id = fields.Many2one(
        "llm.store",
        string="Vector Store",
        readonly=True,
    )
    payload = fields.Text(
        string="Payload (Metadata)",
        readonly=True,
    )

    @api.model
    def action_refresh_embeddings(self):
        """Fetch embeddings from all Qdrant stores and populate the transient model."""
        # Clear existing transient records
        self.search([]).unlink()

        # Find all Qdrant stores
        stores = self.env["llm.store"].search([("service", "=", "qdrant")])

        records_to_create = []

        for store in stores:
            try:
                client = store._get_qdrant_client()
                if not client:
                    continue

                # Get all collections from Qdrant
                collections_response = client.get_collections()
                qdrant_collections = [c.name for c in collections_response.collections]

                _logger.info(f"Found Qdrant collections: {qdrant_collections}")

                # Iterate through all Qdrant collections and try to match with Odoo
                for qdrant_name in qdrant_collections:
                    # Try to extract collection ID from the qdrant name
                    # Format is typically: prefix_collection_id (e.g., odoo_hungpq_9)
                    collection_id = None
                    collection = None

                    # Try to find collection by matching sanitized name
                    all_collections = self.env["llm.knowledge.collection"].search([])
                    for coll in all_collections:
                        sanitized = store.get_santized_collection_name(coll.id)
                        if sanitized == qdrant_name:
                            collection = coll
                            collection_id = coll.id
                            break

                    # Get points from this Qdrant collection
                    try:
                        # Scroll through all points in the collection
                        points, next_offset = client.scroll(
                            collection_name=qdrant_name,
                            limit=1000,  # Limit for performance
                            with_payload=True,
                            with_vectors=False,  # Don't fetch vectors to save bandwidth
                        )

                        _logger.info(f"Found {len(points)} points in Qdrant collection {qdrant_name}")

                        for point in points:
                            # Try to find the matching chunk in Odoo
                            chunk = None
                            chunk_exists = False
                            if isinstance(point.id, int) and point.id > 0:
                                chunk = self.env["llm.knowledge.chunk"].browse(point.id)
                                chunk_exists = chunk.exists()

                            payload_str = str(point.payload) if point.payload else "{}"

                            records_to_create.append({
                                "name": chunk.name if chunk_exists else f"Point {point.id}",
                                "chunk_id": chunk.id if chunk_exists else False,
                                "resource_id": chunk.resource_id.id if chunk_exists and chunk.resource_id else False,
                                "collection_id": collection_id,
                                "qdrant_point_id": point.id if isinstance(point.id, int) else 0,
                                "qdrant_collection_name": qdrant_name,
                                "store_id": store.id,
                                "payload": payload_str,
                            })

                    except Exception as e:
                        _logger.warning(
                            f"Error fetching points from Qdrant collection {qdrant_name}: {e}"
                        )
                        continue

            except Exception as e:
                _logger.error(f"Error connecting to Qdrant store {store.name}: {e}")
                continue

        # Batch create records
        if records_to_create:
            self.create(records_to_create)
            _logger.info(f"Created {len(records_to_create)} Qdrant embedding records")

        # Return action to refresh the view
        return {
            "type": "ir.actions.act_window",
            "name": "Qdrant Chunk Embeddings",
            "res_model": "llm.qdrant.chunk.embedding",
            "view_mode": "list,form",
            "target": "current",
        }

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        """Override to auto-refresh embeddings when viewing."""
        # Check if we have any records, if not, try to fetch
        if not self.search_count([]):
            self.action_refresh_embeddings()
        return super().web_search_read(domain, specification, offset, limit, order, count_limit)
