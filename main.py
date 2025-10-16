# main.py
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from mcp_tool import PostgresAppointmentMCP 

load_dotenv()

# --- Pydantic Models for Request Bodies ---

class ScheduleRequest(BaseModel):
    member_number: str
    appointment_date: str
    appointment_time: str

class RescheduleRequest(BaseModel):
    member_number: str
    old_date: str
    old_time: str
    new_date: str
    new_time: str

class CancelRequest(BaseModel):
    member_number: str
    appointment_date: str
    appointment_time: str

class LogRequest(BaseModel):
    member_number: str
    interaction_start_date: str
    interaction_start_time: str
    interaction_summary: str

# --- FastAPI Application ---

app = FastAPI(
    title="Appointment Management API",
    description="An API service for scheduling, viewing, and managing medical appointments and conversation history."
)

mcp_tool = PostgresAppointmentMCP()

@app.on_event("startup")
async def startup_event():
    if not mcp_tool.conn:
        raise Exception("FATAL: Database connection could not be established. API cannot start.")

# --- API Endpoints ---

@app.get("/member/{member_number}", summary="Get Member Details")
def get_member(member_number: str):
    response = mcp_tool.get_member_details(member_number)
    return response

@app.get("/appointments/upcoming/{member_number}", summary="Review Upcoming Appointments")
def review_appointments(member_number: str):
    response = mcp_tool.review_upcoming_appointments(member_number)
    return response

@app.get("/slots/available", summary="Get Available Slots for PCP")
def get_available_slots(member_number: str, start_date: str):
    response = mcp_tool.get_available_slots_for_pcp(member_number, start_date)
    return response

@app.post("/appointments/schedule", summary="Schedule a New Appointment")
def schedule_appointment(request: ScheduleRequest):
    response = mcp_tool.schedule_appointment(
        request.member_number, 
        request.appointment_date, 
        request.appointment_time
    )
    return response

@app.put("/appointments/reschedule", summary="Reschedule an Existing Appointment")
def reschedule_appointment(request: RescheduleRequest):
    response = mcp_tool.reschedule_appointment(
        request.member_number,
        request.old_date,
        request.old_time,
        request.new_date,
        request.new_time
    )
    return response

@app.delete("/appointments/cancel", summary="Cancel an Appointment")
def cancel_appointment(request: CancelRequest):
    response = mcp_tool.cancel_appointment(
        request.member_number,
        request.appointment_date,
        request.appointment_time
    )
    return response

@app.post("/conversations/log", summary="Log a Conversation")
def log_conversation_history(request: LogRequest):
    response = mcp_tool.log_conversation(
        request.member_number,
        request.interaction_start_date,
        request.interaction_start_time,
        request.interaction_summary
    )
    return response