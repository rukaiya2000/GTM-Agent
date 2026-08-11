"""Paper and author lookup for the research-outreach workspace.

OpenAlex is the primary source: it needs no key, exposes per-paper author
affiliations, and answers reliably. Semantic Scholar is only consulted for IDs
that came from Semantic Scholar, because unauthenticated traffic there is
rate-limited (HTTP 429) most of the time.

Author IDs are returned to callers namespaced — ``openalex:A5103024730`` or
``s2:1738948`` — so a profile lookup always knows which API to ask, and so the
ID is safe to put in a URL path (raw OpenAlex IDs are full URLs).
"""

import re

import requests

from gtm_agent.config import get_openalex_mailto, get_semantic_scholar_api_key

OPENALEX = "https://api.openalex.org"
SEMANTIC_SCHOLAR = "https://api.semanticscholar.org/graph/v1"
ARXIV_API = "https://export.arxiv.org/api/query"
TIMEOUT_SECONDS = 15
# Candidates fetched per search. Only the best one is returned; the rest exist
# so an exact title can be spotted below a higher-scoring near-miss.
CANDIDATE_LIMIT = 5

DOI_PATTERN = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)")
ARXIV_PATTERN = re.compile(r"(?:arxiv[.:/ ]+(?:abs/)?)?(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
ARXIV_TITLE_PATTERN = re.compile(r"<entry>.*?<title>(.*?)</title>", re.DOTALL)

WORK_FIELDS = "id,doi,ids,display_name,publication_year,cited_by_count,abstract_inverted_index,primary_location,best_oa_location,authorships,topics"
AUTHOR_FIELDS = "id,orcid,display_name,works_count,cited_by_count,summary_stats,last_known_institutions,affiliations,topics"


class ScholarError(RuntimeError):
    """A scholarly source could not answer. Callers surface this to the user."""


def _openalex(path: str, params: dict | None = None) -> dict:
    """Call OpenAlex on the polite pool, which gets faster and steadier limits."""
    query = dict(params or {})
    mailto = get_openalex_mailto()
    if mailto:
        query["mailto"] = mailto
    try:
        response = requests.get(
            f"{OPENALEX}{path}",
            params=query,
            headers={"User-Agent": f"wingman-research-outreach ({mailto or 'no-contact-set'})"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise ScholarError("OpenAlex did not respond") from exc


def _semantic_scholar(path: str, params: dict) -> dict:
    api_key = get_semantic_scholar_api_key()
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        response = requests.get(f"{SEMANTIC_SCHOLAR}{path}", params=params, headers=headers, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise ScholarError("Semantic Scholar did not respond") from exc


def _abstract(inverted_index: dict | None) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the prose."""
    if not inverted_index:
        return None
    words = [(position, word) for word, positions in inverted_index.items() for position in positions]
    return " ".join(word for _, word in sorted(words)) or None


def _short_id(openalex_id: str | None) -> str | None:
    """Turn 'https://openalex.org/A5103024730' into 'A5103024730'."""
    return openalex_id.rsplit("/", 1)[-1] if openalex_id else None


def _author_from_authorship(authorship: dict) -> dict:
    author = authorship.get("author") or {}
    institutions = [institution.get("display_name") for institution in authorship.get("institutions") or []]
    raw = authorship.get("raw_affiliation_strings") or []
    short = _short_id(author.get("id"))
    return {
        "authorId": f"openalex:{short}" if short else None,
        "name": author.get("display_name") or "Unknown author",
        "orcid": author.get("orcid"),
        # The affiliation as printed on *this* paper, which is what outreach needs.
        "affiliation": next((name for name in institutions if name), None) or (raw[0] if raw else None),
        "isCorresponding": bool(authorship.get("is_corresponding")),
    }


def _paper_from_work(work: dict) -> dict:
    location = work.get("primary_location") or {}
    open_access = work.get("best_oa_location") or {}
    doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
    arxiv_id = (work.get("ids") or {}).get("arxiv")
    return {
        "paperId": _short_id(work.get("id")),
        "source": "OpenAlex",
        "title": work.get("display_name") or "Untitled paper",
        "abstract": _abstract(work.get("abstract_inverted_index")),
        "year": work.get("publication_year"),
        "venue": (location.get("source") or {}).get("display_name"),
        "citationCount": work.get("cited_by_count"),
        "authors": [_author_from_authorship(authorship) for authorship in work.get("authorships") or []],
        "topics": [topic.get("display_name") for topic in (work.get("topics") or [])[:4] if topic.get("display_name")],
        "externalIds": {"DOI": doi, "ArXiv": arxiv_id},
        "openAccessPdf": {"url": open_access.get("pdf_url")} if open_access.get("pdf_url") else None,
        "url": location.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else work.get("id")),
    }


def _arxiv_title(arxiv_id: str) -> str | None:
    """arXiv IDs are absent from many OpenAlex records, so resolve via title."""
    try:
        response = requests.get(ARXIV_API, params={"id_list": arxiv_id}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        return None
    match = ARXIV_TITLE_PATTERN.search(response.text)
    return " ".join(match.group(1).split()) if match else None


def _normalize_title(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _best_match(query: str, works: list[dict], require_exact: bool = False) -> dict | None:
    """Pick the one work a query names.

    OpenAlex ``search`` is full-text relevance over title, abstract and
    fulltext, so a title query also matches anything sharing its words. Rank
    alone is not enough either, because an exact title can score below a
    near-miss, so an exact title wins and rank only breaks ties.

    ``require_exact`` is for queries that came from an identifier. An arXiv ID
    names one specific paper, and OpenAlex sometimes cannot find it by title at
    all, so falling back to the top hit would answer a precise question with a
    confident guess.
    """
    wanted = _normalize_title(query)
    for work in works:
        if _normalize_title(work.get("display_name", "")) == wanted:
            return work
    return None if require_exact else (works[0] if works else None)


def search_papers(query: str) -> list[dict]:
    """Resolve a DOI, arXiv ID/link, or free-text title to the paper meant.

    Returns at most one paper. This workflow ends in a real message to a real
    person, so offering near-misses beside the right paper is a way to send
    outreach about work someone did not write.
    """
    doi = DOI_PATTERN.search(query)
    if doi:
        work = _openalex(f"/works/doi:{doi.group(1).rstrip('.')}", {"select": WORK_FIELDS})
        return [_paper_from_work(work)]

    arxiv = ARXIV_PATTERN.search(query) if "arxiv" in query.lower() or ARXIV_PATTERN.fullmatch(query.strip()) else None
    if arxiv:
        # An arXiv ID names one specific paper. If we can't resolve its real
        # title, searching OpenAlex full-text on the raw ID/URL instead would
        # rank on whatever it loosely matches and return a false-confidence
        # result for a completely different paper — worse than no match.
        title = _arxiv_title(arxiv.group(1))
        if not title:
            return []
        query, from_identifier = title, True
    else:
        from_identifier = False

    payload = _openalex("/works", {"search": query, "per-page": str(CANDIDATE_LIMIT), "select": WORK_FIELDS})
    work = _best_match(query, payload.get("results", []), require_exact=from_identifier)
    return [_paper_from_work(work)] if work else []


def _openalex_author(author_id: str) -> dict:
    profile = _openalex(f"/authors/{author_id}", {"select": AUTHOR_FIELDS})
    stats = profile.get("summary_stats") or {}
    institutions = [entry.get("display_name") for entry in profile.get("last_known_institutions") or []]
    if not any(institutions):
        institutions = [
            (entry.get("institution") or {}).get("display_name")
            for entry in (profile.get("affiliations") or [])[:2]
        ]
    short = _short_id(profile.get("id"))
    works = _openalex(
        "/works",
        {
            "filter": f"author.id:{short}",
            "sort": "cited_by_count:desc",
            "per-page": "5",
            "select": "id,doi,display_name,publication_year,cited_by_count,primary_location",
        },
    )
    return {
        "authorId": f"openalex:{short}",
        "source": "OpenAlex",
        "name": profile.get("display_name"),
        "affiliations": [name for name in institutions if name],
        "orcid": profile.get("orcid"),
        "profileUrl": profile.get("id"),
        "homepage": None,
        "paperCount": profile.get("works_count"),
        "citationCount": profile.get("cited_by_count"),
        "hIndex": stats.get("h_index"),
        "topics": [topic.get("display_name") for topic in (profile.get("topics") or [])[:5] if topic.get("display_name")],
        "recentPapers": [
            {
                "title": work.get("display_name"),
                "year": work.get("publication_year"),
                "venue": ((work.get("primary_location") or {}).get("source") or {}).get("display_name"),
                "citationCount": work.get("cited_by_count"),
                "url": (work.get("primary_location") or {}).get("landing_page_url") or work.get("doi") or work.get("id"),
            }
            for work in works.get("results", [])
        ],
    }


def _s2_author(author_id: str) -> dict:
    profile = _semantic_scholar(
        f"/author/{author_id}",
        {"fields": "name,affiliations,paperCount,citationCount,hIndex,homepage,url,papers.title,papers.year,papers.venue,papers.citationCount,papers.url"},
    )
    papers = sorted(profile.get("papers") or [], key=lambda paper: paper.get("citationCount") or 0, reverse=True)
    return {
        "authorId": f"s2:{author_id}",
        "source": "Semantic Scholar",
        "name": profile.get("name"),
        "affiliations": profile.get("affiliations") or [],
        "orcid": None,
        "profileUrl": profile.get("url"),
        "homepage": profile.get("homepage"),
        "paperCount": profile.get("paperCount"),
        "citationCount": profile.get("citationCount"),
        "hIndex": profile.get("hIndex"),
        "topics": [],
        "recentPapers": [
            {
                "title": paper.get("title"),
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "citationCount": paper.get("citationCount"),
                "url": paper.get("url"),
            }
            for paper in papers[:5]
        ],
    }


def get_author(namespaced_id: str) -> dict:
    """Look up a profile for an ID produced by :func:`search_papers`."""
    source, _, raw_id = namespaced_id.partition(":")
    if not raw_id:
        # Pre-namespacing IDs and bare OpenAlex IDs both land here.
        raw_id, source = namespaced_id, "openalex" if namespaced_id.upper().startswith("A") else "s2"
    if source == "openalex":
        return _openalex_author(_short_id(raw_id))
    if source == "s2":
        return _s2_author(raw_id)
    raise ScholarError(f"Unknown author source '{source}'")


def find_author_by_name(name: str, affiliation_hint: str | None = None) -> dict:
    """Last-resort lookup when a paper record carried no author ID.

    Name search is ambiguous, so the result is flagged ``matchedBy: "name"``
    and the UI must present it as unconfirmed.
    """
    payload = _openalex("/authors", {"search": name, "per-page": "3"})
    candidates = payload.get("results", [])
    if not candidates:
        return {}
    chosen = candidates[0]
    if affiliation_hint:
        for candidate in candidates:
            institutions = " ".join(
                entry.get("display_name") or "" for entry in candidate.get("last_known_institutions") or []
            )
            if affiliation_hint.lower() in institutions.lower():
                chosen = candidate
                break
    profile = _openalex_author(_short_id(chosen.get("id")))
    profile["matchedBy"] = "name"
    profile["ambiguous"] = len(candidates) > 1
    return profile
