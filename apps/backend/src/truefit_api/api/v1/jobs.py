
# from datetime import datetime, timedelta
# from typing import List
# from uuid import UUID, uuid4
# from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request, status
# import httpx

# from config import AppConfig
# from src.users.services import AnalyticsService, get_analytics_service
# from src.utils.logger import logger




# jobs_router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])



# # ----- Jobs Routes -----
# @jobs_router.get("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
# async def create_event_route(
#     event_data: EventCreate,
#     current_user: TokenData = Depends(get_current_user),
#     service: EventService = Depends(get_event_service)
# ):
#     """List job listings."""
#     event_data = event_data.model_copy(update={"organiser_id": current_user.id})
#     event = await service.create_event(event_data)
#     return event