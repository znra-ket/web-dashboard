from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.onboarding import SshOnboardingCreate, SshOnboardingResponse
from app.services.onboarding_service import Stage1OnboardingService

router = APIRouter()


@router.post("/ssh", response_model=SshOnboardingResponse, status_code=status.HTTP_201_CREATED)
async def install_agent_over_ssh_endpoint(
    payload: SshOnboardingCreate,
    session: AsyncSession = Depends(get_session),
) -> SshOnboardingResponse:
    result = await Stage1OnboardingService(session).install_agent_over_ssh(payload)
    return SshOnboardingResponse(
        node_id=result.node.id,
        lifecycle_status=result.node.lifecycle_status,
        ssh_host_key_fingerprint=result.node.ssh_host_key_fingerprint,
        bootstrap_expires_at=result.bootstrap_record.expires_at,
        bootstrap_window_expires_at=result.bootstrap_record.bootstrap_window_expires_at,
        warning=result.warning,
    )
