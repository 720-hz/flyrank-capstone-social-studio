from fastapi import FastAPI

from app.db import init_db
from app.routes import posts, schedule, variants

app = FastAPI(title="Social Media Studio")

app.include_router(posts.router)
app.include_router(variants.router)
app.include_router(schedule.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
