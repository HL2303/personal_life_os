from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_authenticated_user
from app.db.session import get_db
from app.models.activity import User
from app.schemas.analytics import AnalyticsResponse
from app.services.analytics_service import get_analytics

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("", response_model=AnalyticsResponse)
def read_analytics(
    start_date: date,
    end_date: date,
    timezone: str = Query(default="UTC", min_length=1, max_length=100),
    user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
) -> AnalyticsResponse:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="End date must be on or after start date.")
    if (end_date - start_date).days >= 366:
        raise HTTPException(status_code=422, detail="Analytics ranges cannot exceed 366 days.")
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise HTTPException(
            status_code=422,
            detail="Timezone must be a valid IANA timezone.",
        ) from None
    return get_analytics(db, user.id, start_date, end_date, timezone)
