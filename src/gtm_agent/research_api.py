"""Local API and static UI for research outreach."""

from pathlib import Path
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

from gtm_agent import scholar
from gtm_agent.outreach_llm import OutreachLLMError, author_brief, outreach_draft
from gtm_agent.research_store import ResearchStore

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI(title="Wingman Research Outreach")
store = ResearchStore()


class LinkInput(BaseModel):
    label: Literal["Personal website", "University / lab", "LinkedIn", "X", "Email / contact", "Other"]
    url: HttpUrl


class PaperInput(BaseModel):
    paper_id: str | None = None
    title: str
    year: int | None = None
    doi: str | None = None
    url: str | None = None


class ContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    affiliation: str | None = Field(default=None, max_length=500)
    semantic_scholar_author_id: str | None = None
    paper: PaperInput | None = None
    links: list[LinkInput] = []
    note: str | None = Field(default=None, max_length=5000)


class ContactUpdate(BaseModel):
    relationship_stage: Literal["Prospect", "Connected", "Active", "Nurture", "Archived"] | None = None
    relationship_summary: str | None = Field(default=None, max_length=3000)


class InteractionInput(BaseModel):
    kind: Literal["note", "meeting", "message_sent", "message_received", "introduction"]
    body: str = Field(min_length=1, max_length=5000)
    occurred_at: date = Field(default_factory=date.today)


class FollowUpInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    due_at: date


class DraftInput(BaseModel):
    channel: Literal["Email", "LinkedIn", "X"]
    purpose: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=5000)


class BriefInput(BaseModel):
    author_id: str = Field(min_length=1, max_length=100)
    paper: PaperInput | None = None


class GenerateDraftInput(BaseModel):
    channel: Literal["Email", "LinkedIn", "X"]
    purpose: str = Field(min_length=1, max_length=500)
    sender: str | None = Field(default=None, max_length=1000)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(WEB_DIR / "styles.css", media_type="text/css")


@app.get("/app.js")
def javascript() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js", media_type="text/javascript")


@app.get("/api/papers")
def search_papers(query: str = Query(min_length=2, max_length=300)) -> list[dict]:
    try:
        return scholar.search_papers(query)
    except scholar.ScholarError as exc:
        raise HTTPException(status_code=502, detail="Paper search is unavailable. Please try again shortly.") from exc


@app.get("/api/authors/{author_id}")
def get_author(author_id: str) -> dict:
    """Look up a namespaced author ID such as ``openalex:A5103024730``."""
    try:
        return scholar.get_author(author_id)
    except scholar.ScholarError as exc:
        raise HTTPException(status_code=502, detail="That author profile could not be loaded right now.") from exc


@app.get("/api/author-search")
def search_author(
    name: str = Query(min_length=2, max_length=200),
    affiliation: str | None = Query(default=None, max_length=300),
) -> dict:
    """Name-only lookup for papers that carried no author ID. Public scholarly
    sources only; this never queries LinkedIn, X, or any logged-in platform."""
    try:
        return scholar.find_author_by_name(name, affiliation)
    except scholar.ScholarError as exc:
        raise HTTPException(status_code=502, detail="Author lookup is unavailable. Please try again.") from exc


@app.post("/api/author-brief")
def summarize_author(request: BriefInput) -> dict:
    try:
        profile = scholar.get_author(request.author_id)
    except scholar.ScholarError as exc:
        raise HTTPException(status_code=502, detail="That author profile could not be loaded right now.") from exc
    try:
        return {"brief": author_brief(profile, request.paper.model_dump() if request.paper else None)}
    except OutreachLLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/contacts", status_code=201)
def create_contact(contact: ContactInput) -> dict:
    return store.save_contact(
        name=contact.name,
        affiliation=contact.affiliation,
        author_id=contact.semantic_scholar_author_id,
        paper=contact.paper.model_dump() if contact.paper else None,
        links=[{"label": link.label, "url": str(link.url)} for link in contact.links],
        note=contact.note,
    )


@app.get("/api/contacts")
def list_contacts() -> list[dict]:
    return store.list_contacts()


@app.get("/api/contacts/{contact_id}")
def get_contact(contact_id: int) -> dict:
    try:
        return store.get_contact(contact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc


@app.patch("/api/contacts/{contact_id}")
def update_contact(contact_id: int, update: ContactUpdate) -> dict:
    try:
        return store.update_contact(contact_id, update.relationship_stage, update.relationship_summary)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc


@app.post("/api/contacts/{contact_id}/interactions")
def add_interaction(contact_id: int, interaction: InteractionInput) -> dict:
    try:
        return store.add_interaction(contact_id, interaction.kind, interaction.body, interaction.occurred_at.isoformat())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc


@app.post("/api/contacts/{contact_id}/follow-ups")
def add_follow_up(contact_id: int, task: FollowUpInput) -> dict:
    try:
        return store.add_follow_up(contact_id, task.reason, task.due_at.isoformat())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc


@app.post("/api/contacts/{contact_id}/drafts")
def save_draft(contact_id: int, draft: DraftInput) -> dict:
    try:
        return store.save_draft(contact_id, draft.channel, draft.purpose, draft.body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc


@app.post("/api/contacts/{contact_id}/generate-draft")
def generate_draft(contact_id: int, request: GenerateDraftInput) -> dict:
    """Draft a message from stored facts. Nothing is sent; the user still approves."""
    try:
        contact = store.get_contact(contact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc
    try:
        body = outreach_draft(
            contact=contact,
            paper=(contact.get("papers") or [None])[0],
            channel=request.channel,
            purpose=request.purpose,
            sender=request.sender,
        )
    except OutreachLLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"body": body}


@app.get("/api/follow-ups")
def list_follow_ups() -> list[dict]:
    return store.list_follow_ups()


@app.patch("/api/follow-ups/{task_id}")
def complete_follow_up(task_id: int, status: Literal["done", "snoozed"]) -> dict:
    try:
        store.complete_follow_up(task_id, status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Follow-up not found") from exc
    return {"ok": True}
