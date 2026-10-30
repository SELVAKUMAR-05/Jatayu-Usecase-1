data = open('backend/app/main.py').read()
if 'enterprise_router' not in data:
    old_import = '''from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker'''
    new_import = old_import + '''

from app.api.v2_enterprise import router as enterprise_router
from app.core.config import get_settings
from app.core.logging import logger
from app.telemetry.collector import telemetry
from app.core.utils import new_correlation_id, new_trace_id

settings = get_settings()'''
    data = data.replace(old_import, new_import)
    old_app = '''app = FastAPI(title="OrderFlow Sentinel", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)'''
    new_app = '''app = FastAPI(title="OrderFlow Sentinel", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(enterprise_router)'''
    data = data.replace(old_app, new_app)
    open('backend/app/main.py','w').write(data)
    print('done')
else:
    print('exists')
