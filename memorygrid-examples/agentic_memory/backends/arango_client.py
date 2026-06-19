from typing import Any, Dict, List, Optional

from arango import ArangoClient as _ArangoClient

from ..config import ArangoConfig

# Vertex collections — one per memory type plus a shared entity collection
NODE_COLLECTIONS = {
    "episodic": "episodic_nodes",
    "semantic": "semantic_nodes",
    "procedural": "procedural_nodes",
    "reflective": "reflective_nodes",
    "reward": "reward_nodes",
    "entity": "entity_nodes",  # knowledge-graph entities for semantic memory
}

# Edge collections
EDGE_COLLECTIONS = {
    "memory_relations": "memory_relations",        # generic cross-memory links
    "entity_relations": "entity_relations",        # subject → object edges in knowledge graph
    "episode_reflection": "episode_reflection",    # episodic → reflective provenance
}


class ArangoBackend:
    def __init__(self, config: ArangoConfig):
        self.config = config
        self._client = _ArangoClient(hosts=config.url)
        self._db = self._connect()
        self._ensure_collections()

    # ------------------------------------------------------------------
    # Connection & schema
    # ------------------------------------------------------------------

    def _connect(self):
        sys_db = self._client.db("_system", username=self.config.username, password=self.config.password)
        if not sys_db.has_database(self.config.database):
            sys_db.create_database(self.config.database)
        return self._client.db(
            self.config.database, username=self.config.username, password=self.config.password
        )

    def _ensure_collections(self):
        for name in NODE_COLLECTIONS.values():
            if not self._db.has_collection(name):
                self._db.create_collection(name)
        for name in EDGE_COLLECTIONS.values():
            if not self._db.has_collection(name):
                self._db.create_collection(name, edge=True)

    # ------------------------------------------------------------------
    # Node CRUD
    # ------------------------------------------------------------------

    def _col(self, memory_type: str):
        return self._db.collection(NODE_COLLECTIONS[memory_type])

    def insert_node(self, memory_type: str, doc: Dict[str, Any]) -> str:
        result = self._col(memory_type).insert(doc)
        return result["_key"]

    def get_node(self, memory_type: str, key: str) -> Optional[Dict[str, Any]]:
        try:
            return self._col(memory_type).get(key)
        except Exception:
            return None

    def update_node(self, memory_type: str, key: str, doc: Dict[str, Any]):
        self._col(memory_type).update({"_key": key, **doc})

    def delete_node(self, memory_type: str, key: str):
        self._col(memory_type).delete(key, ignore_missing=True)

    # ------------------------------------------------------------------
    # Edge CRUD
    # ------------------------------------------------------------------

    def insert_edge(
        self,
        edge_collection: str,
        from_type: str,
        from_key: str,
        to_type: str,
        to_key: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        from_col = NODE_COLLECTIONS[from_type]
        to_col = NODE_COLLECTIONS[to_type]
        edge = {
            "_from": f"{from_col}/{from_key}",
            "_to": f"{to_col}/{to_key}",
            **(attributes or {}),
        }
        self._db.collection(EDGE_COLLECTIONS[edge_collection]).insert(edge)

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_related(
        self,
        memory_type: str,
        key: str,
        edge_collection: str,
        direction: str = "OUTBOUND",
        depth: int = 1,
    ) -> List[Dict[str, Any]]:
        vertex_col = NODE_COLLECTIONS[memory_type]
        edge_col = EDGE_COLLECTIONS.get(edge_collection, edge_collection)
        aql = f"""
        FOR v IN 1..{depth} {direction.upper()} '{vertex_col}/{key}'
            {edge_col}
        RETURN v
        """
        cursor = self._db.aql.execute(aql)
        return list(cursor)

    def find_entity_path(self, from_key: str, to_key: str) -> List[Dict[str, Any]]:
        aql = """
        FOR path IN OUTBOUND SHORTEST_PATH
            CONCAT('entity_nodes/', @from) TO CONCAT('entity_nodes/', @to)
            entity_relations
        RETURN path
        """
        cursor = self._db.aql.execute(aql, bind_vars={"from": from_key, "to": to_key})
        return list(cursor)

    def search_nodes(self, memory_type: str, field: str, value: Any) -> List[Dict[str, Any]]:
        col_name = NODE_COLLECTIONS[memory_type]
        aql = f"FOR doc IN {col_name} FILTER doc.{field} == @value RETURN doc"
        cursor = self._db.aql.execute(aql, bind_vars={"value": value})
        return list(cursor)
