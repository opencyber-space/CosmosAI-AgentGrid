#!/usr/bin/env python3
"""
Database cleanup script for CosmosAI Agentic Memory.
Cleans all data from Postgres tables, ArangoDB collections, and Weaviate collections cleanly.
"""

import os
import sys

# Add current folder to path to import db_config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from db_config import make_config
except ImportError:
    print("Error: Could not import make_config from db_config.py")
    sys.exit(1)

import psycopg2
from arango import ArangoClient
import weaviate

def cleanup_postgres(config):
    print("--- Cleaning up Postgres Database ---")
    pg_conf = config.postgres
    print(f"Connecting to Postgres at {pg_conf.host}:{pg_conf.port}/{pg_conf.database}...")
    try:
        conn = psycopg2.connect(
            host=pg_conf.host,
            port=pg_conf.port,
            dbname=pg_conf.database,
            user=pg_conf.username,
            password=pg_conf.password
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            tables = [
                "procedure_steps",
                "procedures",
                "episodic_memories",
                "semantic_memories",
                "reflective_memories",
                "reward_memories"
            ]
            print(f"Truncating tables: {', '.join(tables)} with CASCADE...")
            cur.execute(f"TRUNCATE TABLE {', '.join(tables)} CASCADE;")
            print("Postgres database cleaned cleanly.")
        conn.close()
    except Exception as e:
        print(f"Warning: Failed to clean Postgres database: {e}")

def cleanup_arango(config):
    print("\n--- Cleaning up ArangoDB Database ---")
    ar_conf = config.arango
    print(f"Connecting to ArangoDB at {ar_conf.url}...")
    try:
        client = ArangoClient(hosts=ar_conf.url)
        sys_db = client.db("_system", username=ar_conf.username, password=ar_conf.password)
        if not sys_db.has_database(ar_conf.database):
            print(f"Database {ar_conf.database} does not exist, nothing to clean.")
            return
        
        db = client.db(ar_conf.database, username=ar_conf.username, password=ar_conf.password)
        
        # Vertex collections
        node_cols = ["episodic_nodes", "semantic_nodes", "procedural_nodes", "reflective_nodes", "reward_nodes", "entity_nodes"]
        # Edge collections
        edge_cols = ["memory_relations", "entity_relations", "episode_reflection"]
        
        all_cols = node_cols + edge_cols
        for col_name in all_cols:
            if db.has_collection(col_name):
                print(f"Truncating ArangoDB collection: {col_name}...")
                db.collection(col_name).truncate()
            else:
                print(f"Collection {col_name} does not exist, skipping.")
        print("ArangoDB database cleaned cleanly.")
    except Exception as e:
        print(f"Warning: Failed to clean ArangoDB database: {e}")

def cleanup_weaviate(config):
    print("\n--- Cleaning up Weaviate Database ---")
    we_conf = config.weaviate
    print(f"Connecting to Weaviate at {we_conf.host}:{we_conf.port}...")
    client = None
    try:
        client = weaviate.connect_to_local(
            host=we_conf.host,
            port=we_conf.port,
            grpc_port=we_conf.grpc_port,
        )
        memory_types = ["episodic", "semantic", "procedural", "reflective", "reward"]
        for mt in memory_types:
            col_name = f"{we_conf.collection_prefix}{mt.capitalize()}"
            if client.collections.exists(col_name):
                print(f"Deleting Weaviate collection: {col_name}...")
                client.collections.delete(col_name)
            else:
                print(f"Collection {col_name} does not exist, skipping.")
        print("Weaviate database cleaned cleanly.")
    except Exception as e:
        print(f"Warning: Failed to clean Weaviate database: {e}")
    finally:
        if client is not None:
            client.close()

def main():
    print("==========================================")
    print("Starting CosmosAI Database Cleanup Process")
    print("==========================================")
    config = make_config()
    cleanup_postgres(config)
    cleanup_arango(config)
    cleanup_weaviate(config)
    print("\n==========================================")
    print("Database Cleanup Process Completed Successfully")
    print("==========================================")

if __name__ == "__main__":
    main()
