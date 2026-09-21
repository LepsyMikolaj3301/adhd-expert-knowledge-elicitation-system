from fastapi import FastAPI

app = FastAPI(title="ADHD Expert Knowledge RAG Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
