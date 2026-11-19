import logging
import secrets
from time import perf_counter

from app.analytics.instrumentation import error_category, track
from app.repositories import RegistrationError, RegistrationRepository
from registrar.errors import GraphError, SendStatusUnknown
from registrar.models import validate_student_id

logger = logging.getLogger(__name__)


class RegistrationService:
    def __init__(self, repository: RegistrationRepository, registrar, *, health=None):
        self.repository = repository
        self.registrar = registrar
        self.health = health

    async def request_code(self, user_id: int, student_id: str) -> str:
        student_id = validate_student_id(student_id)
        started = perf_counter()
        try:
            student = await self.registrar.find_student(student_id, refresh=True)
        except GraphError as error:
            track(
                "email_lookup",
                outcome="error",
                error=error_category(error),
                duration_ms=(perf_counter() - started) * 1000,
            )
            logger.warning("Registration lookup unavailable (%s)", error.diagnostic)
            if self.health:
                self.health.incident("email", error)
            raise
        track(
            "email_lookup",
            outcome="ok" if student else "rejected",
            error=None if student else "not_found",
            duration_ms=(perf_counter() - started) * 1000,
        )
        if student is None:
            await self.repository.event(
                user_id, "registration_student_not_found", requested_student_id=student_id
            )
            raise RegistrationError("No student found with this ID. Check the ID and try again.")
        code = f"{secrets.randbelow(1000000):06d}"
        nonce = await self.repository.reserve_code(user_id, student, code)
        try:
            await self.registrar.send_verification_code(
                student, code, self.repository.CODE_TTL_SECONDS
            )
        except SendStatusUnknown as error:
            logger.warning("Verification email submission unconfirmed (%s)", error.diagnostic)
            if self.health:
                self.health.incident("email", error)
            await self.repository.mark_email(user_id, nonce, "unknown")
            return "unknown"
        except GraphError as error:
            logger.warning("Verification email submission failed (%s)", error.diagnostic)
            if self.health:
                self.health.incident("email", error)
            await self.repository.mark_email(user_id, nonce, "failed")
            raise
        await self.repository.mark_email(user_id, nonce, "accepted")
        logger.info("Verification email submission accepted by Microsoft")
        return "accepted"

    async def resend(self, user_id):
        student = await self.repository.pending(user_id)
        if student is None:
            raise RegistrationError("Send your student ID first.")
        return await self.request_code(user_id, student.student_id)
