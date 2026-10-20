from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import service as s

router = APIRouter(prefix="/api/feedback", tags=["05 SignalLoop"])
CATS = "^(incorrect|unsupported|incomplete|outdated_source|formatting|harmful|other)$"


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    user: str = Field("me", pattern=r"^[\w\-]{1,30}$")


@router.post("/ask")
def ask(b: AskIn):
    return s.ask(b.question, b.user)


class RateIn(BaseModel):
    interaction_id: str
    user: str = Field("me", pattern=r"^[\w\-]{1,30}$")
    rating: int = Field(ge=-1, le=1)
    categories: list[str] = Field(default_factory=list, max_length=4)
    comment: str = Field("", max_length=2000)
    correction: str = Field("", max_length=4000)
    consent: bool = False


@router.post("/rate")
def rate(b: RateIn):
    import re
    if any(not re.match(CATS, c) for c in b.categories):
        raise HTTPException(422, "unknown category")
    return s.submit_feedback(b.interaction_id, b.user, b.rating, b.categories, b.comment, b.correction, b.consent)


class SignalIn(BaseModel):
    interaction_id: str
    user: str = Field("me", pattern=r"^[\w\-]{1,30}$")
    kind: str = Field(pattern="^(regenerate|copy|edit)$")
    edited_text: str | None = Field(None, max_length=4000)


@router.post("/signal")
def signal(b: SignalIn):
    return s.record_signal(b.interaction_id, b.user, b.kind, b.edited_text)


@router.get("/queue")
def queue():
    return s.queue()


class ReviewIn(BaseModel):
    action: str = Field(pattern="^(approve|reject|duplicate)$")
    reviewer: str = Field("reviewer", max_length=40)
    must_contain: list[list[str]] | None = None
    abstain: bool = False
    dataset: str = Field("eval", pattern="^(eval|train)$")
    note: str = Field("", max_length=500)


@router.post("/items/{feedback_id}/review")
def review(feedback_id: str, b: ReviewIn):
    return s.review(feedback_id, b.action, b.reviewer, b.must_contain, b.abstain, b.dataset, b.note)


@router.delete("/items/{feedback_id}")
def delete(feedback_id: str):
    return s.delete_feedback(feedback_id)


@router.post("/retention")
def retention(days: float = 30):
    return s.apply_retention(days)


@router.get("/analytics")
def analytics():
    return s.analytics()


@router.get("/examples")
def examples():
    return s.examples()


class FreezeIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)


@router.post("/evalsets")
def freeze(b: FreezeIn):
    return s.freeze(b.name)


@router.get("/evalsets")
def evalsets():
    return s.evalsets()


@router.get("/releases")
def releases():
    return s.releases()


class ReleaseIn(BaseModel):
    name: str = Field(min_length=2, max_length=40, pattern=r"^[\w.\-]+$")
    strategy: str = Field("hybrid", pattern="^(bm25|dense|hybrid)$")
    k: int = Field(5, ge=1, le=10)
    reranker: str = Field("overlap", pattern="^(none|overlap)$")
    prefer_current: bool = True
    min_coverage: float = Field(0.35, ge=0, le=1)
    use_llm: bool = False


@router.post("/releases")
def create(b: ReleaseIn):
    return s.create_release(b.name, b.model_dump(exclude={"name"}))


@router.post("/releases/{release_id}/gate")
def gate(release_id: str, evalset_id: str):
    return s.gate(release_id, evalset_id)


@router.post("/releases/{release_id}/promote")
def promote(release_id: str, rollback: bool = False):
    try:
        return s.promote(release_id, rollback)
    except PermissionError as e:
        raise HTTPException(403, str(e))


@router.post("/demo-seed")
def demo():
    return s.seed_demo()
