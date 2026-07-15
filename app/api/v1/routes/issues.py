from fastapi import APIRouter, Depends, Response

from app.models.issue import IssueCreate, IssueUpdate
from app.services.issue_service import IssueService
from app.db.session import get_master_session, get_replica_session, get_redis_client

router = APIRouter()


def get_issue_service(
    master_session=Depends(get_master_session),
    replica_session=Depends(get_replica_session),
    redis_client=Depends(get_redis_client),
) -> IssueService:
    return IssueService(
        master_session_factory=lambda: master_session,
        replica_session_factory=lambda: replica_session,
        redis_client=redis_client,
    )


@router.get("/health")
def health(service: IssueService = Depends(get_issue_service)):
    return {"worker_id": service.worker_id, "status": "ok"}


@router.post("/issues", status_code=201)
def create_issue(payload: IssueCreate, response: Response, service: IssueService = Depends(get_issue_service)):
    return service.create_issue(payload, response)


@router.get("/issues")
def list_issues(service: IssueService = Depends(get_issue_service)):
    return service.list_issues()


@router.get("/issues/{issue_id}")
def get_issue(issue_id: str, service: IssueService = Depends(get_issue_service)):
    return service.get_issue(issue_id)


@router.put("/issues/{issue_id}")
def update_issue(issue_id: str, payload: IssueUpdate, service: IssueService = Depends(get_issue_service)):
    return service.update_issue(issue_id, payload)


@router.delete("/issues/{issue_id}", status_code=204)
def delete_issue(issue_id: str, service: IssueService = Depends(get_issue_service)):
    service.delete_issue(issue_id)
    return None
