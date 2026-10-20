import secrets

from app.repositories import RegistrationError, RegistrationRepository
from registrar.errors import GraphError, SendStatusUnknown
from registrar.models import validate_student_id


class RegistrationService:
    def __init__(self, repository: RegistrationRepository, registrar):
        self.repository = repository
        self.registrar = registrar

    async def request_code(self, user_id: int, student_id: str) -> str:
        student_id = validate_student_id(student_id)
        student = await self.registrar.find_student(student_id, refresh=True)
        if student is None:
            await self.repository.event(user_id, "registration_student_not_found", requested_student_id=student_id)
            raise RegistrationError("No student found with this ID. Check the ID and try again.")
        code = f"{secrets.randbelow(1000000):06d}"
        nonce = await self.repository.reserve_code(user_id, student, code)
        try:
            await self.registrar.send_verification_code(student, code, self.repository.CODE_TTL_SECONDS)
        except SendStatusUnknown:
            await self.repository.mark_email(user_id, nonce, "unknown")
            return "unknown"
        except GraphError:
            await self.repository.mark_email(user_id, nonce, "failed")
            raise
        await self.repository.mark_email(user_id, nonce, "accepted")
        return "accepted"

    async def resend(self, user_id):
        student = await self.repository.pending(user_id)
        if student is None:
            raise RegistrationError("Send your student ID first.")
        return await self.request_code(user_id, student.student_id)
