import os
import psycopg2
import psycopg2.extras
import json
from datetime import date

class PostgresAppointmentMCP:
    """
    MCP Server for managing medical appointments with a PostgreSQL database.
    This class connects to an existing Postgres DB and provides methods (tools)
    for an AI agent to schedule, query, reschedule, and cancel appointments.
    It is designed to be used as a tool in a Flowise agent.
    """

    def __init__(self):
        """
        Initializes the database connection using environment variables.
        For Flowise, set these in your environment or secrets:
        - DB_NAME
        - DB_USER
        - DB_PASSWORD
        - DB_HOST
        - DB_PORT
        """
        try:
            self.conn = psycopg2.connect(
                dbname=os.environ.get("DB_NAME"),
                user=os.environ.get("DB_USER"),
                password=os.environ.get("DB_PASSWORD"),
                host=os.environ.get("DB_HOST"),
                port=os.environ.get("DB_PORT")
            )
        except psycopg2.OperationalError as e:
            print(f"FATAL: Could not connect to the database. Please check credentials and environment variables. Details: {e}")
            self.conn = None

    def _execute_query(self, query, params=(), commit=False, fetch=None):
        """Helper function to execute simple, non-transactional SQL queries."""
        if not self.conn:
            return {"error": "Database connection is not available."}
        
        def date_serializer(obj):
            if isinstance(obj, date):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                cursor.execute(query, params)
                if commit:
                    self.conn.commit()
                    return {"success": True, "rows_affected": cursor.rowcount}
                
                if fetch == 'one':
                    result = cursor.fetchone()
                    return json.loads(json.dumps(dict(result), default=date_serializer)) if result else None
                if fetch == 'all':
                    result = cursor.fetchall()
                    return json.loads(json.dumps([dict(row) for row in result], default=date_serializer)) if result else []
            return {"success": True}
        except Exception as e:
            print(f"ERROR: Database query failed. Query: {query}, Params: {params}, Error: {e}")
            self.conn.rollback()
            return {"error": f"A database error occurred: {e}"}

    def log_conversation(self, member_number: str, interaction_start_date: str, interaction_start_time: str, interaction_summary: str) -> str:
        """
        Logs the summary of an interaction with a member into the conversation_history table.
        """
        if not self.conn:
            return json.dumps({"error": "Database connection is not available."})

        insert_query = """
            INSERT INTO public.conversation_history 
            (member_number, interaction_start_date, interaction_start_time, interaction_summary) 
            VALUES (%s, %s, %s, %s);
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(insert_query, (member_number, interaction_start_date, interaction_start_time, interaction_summary))
                self.conn.commit()
                if cursor.rowcount > 0:
                    return json.dumps({"success": True, "message": "Interaction logged successfully."})
                else:
                    self.conn.rollback()
                    return json.dumps({"error": "Failed to log interaction, no rows were affected."})
        except psycopg2.Error as e:
            self.conn.rollback()
            if e.pgcode == '23503':
                 return json.dumps({"error": f"Failed to log interaction: member number '{member_number}' does not exist."})
            return json.dumps({"error": f"A database error occurred while logging interaction: {e}"})

    def get_member_details(self, member_number: str) -> str:
        """
        Retrieves all details for a member based on their member number.
        """
        query = "SELECT * FROM public.members WHERE member_number = %s;"
        member = self._execute_query(query, (member_number,), fetch='one')
        if member:
            return json.dumps(member)
        return json.dumps({"error": f"No member found with number {member_number}."})

    def review_upcoming_appointments(self, member_number: str) -> str:
        """
        Reviews all upcoming appointments for a given member.
        """
        query = """
            SELECT a.appointment_date, a.appointment_time, d.doctor_name, o.office_name
            FROM public.appointments a
            JOIN public.doctors d ON a.doctor_id = d.doctor_id
            JOIN public.offices o ON a.office_id = o.office_id
            WHERE a.member_id = %s AND a.appointment_date >= CURRENT_DATE
            ORDER BY a.appointment_date, a.appointment_time;
        """
        appointments = self._execute_query(query, (member_number,), fetch='all')
        if appointments:
            return json.dumps(appointments)
        return json.dumps({"message": "No upcoming appointments found."})

    def schedule_appointment(self, member_number: str, appointment_date: str, appointment_time: str) -> str:
        """
        Schedules a new appointment by creating an appointment record and removing the corresponding available slot.
        """
        if not self.conn:
            return json.dumps({"error": "Database connection is not available."})

        member_details = json.loads(self.get_member_details(member_number))
        if "error" in member_details:
            return json.dumps(member_details)
        
        doctor_id = member_details.get('pcp')
        if not doctor_id:
            return json.dumps({"error": "Member does not have a Primary Care Provider (PCP) assigned."})

        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                slot_query = "SELECT office_id FROM public.appointment_slots WHERE doctor_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(slot_query, (doctor_id, appointment_date, appointment_time))
                slot = cursor.fetchone()
                if not slot:
                    return json.dumps({"error": "This time slot does not exist or is already taken for the member's PCP."})
                
                office_id = slot['office_id']

                delete_slot_query = "DELETE FROM public.appointment_slots WHERE doctor_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(delete_slot_query, (doctor_id, appointment_date, appointment_time))

                insert_appt_query = "INSERT INTO public.appointments (member_id, doctor_id, office_id, appointment_date, appointment_time) VALUES (%s, %s, %s, %s, %s);"
                cursor.execute(insert_appt_query, (member_number, doctor_id, office_id, appointment_date, appointment_time))
                
                self.conn.commit()
                return json.dumps({"success": "Appointment scheduled successfully."})
        except Exception as e:
            self.conn.rollback()
            print(f"ERROR during schedule_appointment: {e}")
            return json.dumps({"error": f"Appointment could not be scheduled due to a database error: {e}"})

    def reschedule_appointment(self, member_number: str, old_date: str, old_time: str, new_date: str, new_time: str) -> str:
        """
        Reschedules an appointment transactionally.
        """
        if not self.conn:
            return json.dumps({"error": "Database connection is not available."})
            
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                find_old_query = "SELECT doctor_id, office_id FROM public.appointments WHERE member_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(find_old_query, (member_number, old_date, old_time))
                old_appointment = cursor.fetchone()
                if not old_appointment:
                    return json.dumps({"error": "Could not find the original appointment to reschedule."})
                
                doctor_id = old_appointment['doctor_id']
                old_office_id = old_appointment['office_id']

                find_new_query = "SELECT office_id FROM public.appointment_slots WHERE doctor_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(find_new_query, (doctor_id, new_date, new_time))
                new_slot = cursor.fetchone()
                if not new_slot:
                    return json.dumps({"error": "The new appointment slot is not available."})
                new_office_id = new_slot['office_id']

                update_query = "UPDATE public.appointments SET appointment_date = %s, appointment_time = %s, office_id = %s WHERE member_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(update_query, (new_date, new_time, new_office_id, member_number, old_date, old_time))

                delete_new_slot_query = "DELETE FROM public.appointment_slots WHERE doctor_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(delete_new_slot_query, (doctor_id, new_date, new_time))
                
                insert_old_slot_query = "INSERT INTO public.appointment_slots (doctor_id, office_id, appointment_date, appointment_time) VALUES (%s, %s, %s, %s);"
                cursor.execute(insert_old_slot_query, (doctor_id, old_office_id, old_date, old_time))

                self.conn.commit()
                return json.dumps({"success": "Appointment rescheduled successfully."})
        except Exception as e:
            self.conn.rollback()
            print(f"ERROR during reschedule_appointment: {e}")
            return json.dumps({"error": f"Reschedule failed due to a database error: {e}"})

    def cancel_appointment(self, member_number: str, appointment_date: str, appointment_time: str) -> str:
        """
        Cancels an appointment transactionally.
        """
        if not self.conn:
            return json.dumps({"error": "Database connection is not available."})

        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                find_query = "SELECT doctor_id, office_id FROM public.appointments WHERE member_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(find_query, (member_number, appointment_date, appointment_time))
                appointment_to_cancel = cursor.fetchone()
                if not appointment_to_cancel:
                    return json.dumps({"error": "No matching appointment found to cancel."})
                
                doctor_id = appointment_to_cancel['doctor_id']
                office_id = appointment_to_cancel['office_id']

                delete_query = "DELETE FROM public.appointments WHERE member_id = %s AND appointment_date = %s AND appointment_time = %s;"
                cursor.execute(delete_query, (member_number, appointment_date, appointment_time))
                
                if cursor.rowcount == 0:
                    self.conn.rollback()
                    return json.dumps({"error": "Failed to cancel appointment, appointment not found."})

                insert_slot_query = "INSERT INTO public.appointment_slots (doctor_id, office_id, appointment_date, appointment_time) VALUES (%s, %s, %s, %s);"
                cursor.execute(insert_slot_query, (doctor_id, office_id, appointment_date, appointment_time))

                self.conn.commit()
                return json.dumps({"success": "Appointment cancelled successfully."})
        except Exception as e:
            self.conn.rollback()
            print(f"ERROR during cancel_appointment: {e}")
            return json.dumps({"error": f"Cancellation failed due to a database error: {e}"})

    def get_available_slots_for_pcp(self, member_number: str, start_date: str) -> str:
        """
        Finds available appointment slots for a member's assigned PCP on or after a given date.
        """
        member_details = json.loads(self.get_member_details(member_number))
        if "error" in member_details:
            return json.dumps(member_details)
        
        doctor_id = member_details.get('pcp')
        if not doctor_id:
            return json.dumps({"error": "Member does not have a PCP assigned."})
        
        query = """
            SELECT s.appointment_date, s.appointment_time, o.office_name
            FROM public.appointment_slots s
            JOIN public.offices o ON s.office_id = o.office_id
            WHERE s.doctor_id = %s AND s.appointment_date >= %s
            ORDER BY s.appointment_date, s.appointment_time
            LIMIT 20;
        """
        slots = self._execute_query(query, (doctor_id, start_date), fetch='all')

        if slots:
            return json.dumps(slots)
        return json.dumps({"message": "No available appointment slots found for the member's PCP on or after the specified date."})

    def __del__(self):
        """Destructor to close the database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()