from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import health, assess, challenge, save, save_corrections

app = FastAPI(
    title="Bike Assessment API",
    description="AI-powered bike identification and component assessment",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(assess.router)
app.include_router(challenge.router)
app.include_router(save.router)
app.include_router(save_corrections.router)
