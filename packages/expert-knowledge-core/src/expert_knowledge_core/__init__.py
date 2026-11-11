"""What the web application's ingestion and the retrieval package must agree on.

One copy of: the BM25 sparse vectors (a query has to be tokenised exactly as the stored vectors
were), the notes the generator reads (packing a unit's sentences), the findings record that is
stored in the database, the prompts and the retrieval constants the evaluations settled on.
No LangChain, no web framework, no database driver.
"""
