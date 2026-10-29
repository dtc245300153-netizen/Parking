from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .database import Base, engine
from . import models

from .routers import (
    areas,
    auth,
    users,
    vehicles,
    tickets,
    prices,
    dashboard
)


# =========================
# DATABASE
# =========================

Base.metadata.create_all(bind=engine)


# =========================
# APP
# =========================

app = FastAPI(
    title="Parking Management System",
    description="Hệ thống quản lý bãi đỗ xe tích hợp AI",
    version="1.0.0"
)


# =========================
# TEMPLATE
# =========================

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


# =========================
# ROUTERS
# =========================

app.include_router(auth.router)
app.include_router(areas.router)
app.include_router(users.router)
app.include_router(vehicles.router)
app.include_router(tickets.router)
app.include_router(prices.router)
app.include_router(dashboard.router)


# =========================
# LOGIN
# =========================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )


# =========================
# PARKING
# =========================

@app.get("/parking", response_class=HTMLResponse)
def parking_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="parking.html"
    )


# =========================
# ROOT
# =========================

@app.get("/")
def root():
    return {
        "message": "Parking API is running",
        "login": "/login",
        "parking": "/parking",
        "docs": "/docs"
    }


# =========================
# HEALTH
# =========================

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "database": "connected"
    }