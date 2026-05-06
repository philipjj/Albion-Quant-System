"""
FastAPI routes for per-user personalization.

This is intentionally minimal: a single profile record keyed by Discord user id.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import UserProfile

router = APIRouter(prefix="/user", tags=["User"])


class UserProfileIn(BaseModel):
    discord_user_id: str = Field(min_length=1, max_length=32)
    is_premium: Optional[bool] = None
    home_city: Optional[str] = None
    api_server: Optional[str] = None

    max_capital_per_trade: Optional[int] = None
    target_exit_hours: Optional[float] = None
    min_arbitrage_margin: Optional[float] = None
    min_arbitrage_profit: Optional[int] = None
    min_crafting_profit: Optional[int] = None


class UserProfileOut(BaseModel):
    discord_user_id: str
    is_premium: bool
    home_city: Optional[str] = None
    api_server: Optional[str] = None

    max_capital_per_trade: Optional[int] = None
    target_exit_hours: Optional[float] = None
    min_arbitrage_margin: Optional[float] = None
    min_arbitrage_profit: Optional[int] = None
    min_crafting_profit: Optional[int] = None


@router.get("/profile/{discord_user_id}", response_model=UserProfileOut)
def get_profile(discord_user_id: str, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).filter_by(discord_user_id=discord_user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return UserProfileOut(
        discord_user_id=profile.discord_user_id,
        is_premium=bool(profile.is_premium),
        home_city=profile.home_city,
        api_server=profile.api_server,
        max_capital_per_trade=profile.max_capital_per_trade,
        target_exit_hours=profile.target_exit_hours,
        min_arbitrage_margin=profile.min_arbitrage_margin,
        min_arbitrage_profit=profile.min_arbitrage_profit,
        min_crafting_profit=profile.min_crafting_profit,
    )


@router.put("/profile", response_model=UserProfileOut)
def upsert_profile(payload: UserProfileIn, db: Session = Depends(get_db)):
    profile = db.query(UserProfile).filter_by(discord_user_id=payload.discord_user_id).first()
    if not profile:
        profile = UserProfile(discord_user_id=payload.discord_user_id)
        db.add(profile)

    data = payload.model_dump(exclude_unset=True)
    data.pop("discord_user_id", None)
    for key, value in data.items():
        setattr(profile, key, value)

    db.commit()
    db.refresh(profile)
    return get_profile(profile.discord_user_id, db)
