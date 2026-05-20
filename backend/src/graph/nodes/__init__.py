"""LangGraph nodes — import each node module explicitly.

We avoid an eager bundle import so tests can import individual node modules
without pulling in heavy deps (langchain-mcp-adapters, langchain-openai, etc.).

The builder imports everything it needs explicitly. Production-side this file stays empty.
"""
