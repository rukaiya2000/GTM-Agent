from datetime import date

import requests

from gtm_agent.config import get_notion_token

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# The canonical Tweet Drafts schema. This is the single source of truth — the
# skills describe how to use these fields, but the names and options are defined
# here so the two can't drift apart.
TWEET_DRAFTS_SCHEMA = {
    "Post Info": {"title": {}},
    "Title": {"rich_text": {}},
    "Final Text": {"rich_text": {}},
    "Stage": {
        "select": {
            "options": [
                {"name": "Ready for AI Review", "color": "blue"},
                {"name": "Ready for Human Review", "color": "brown"},
                {"name": "Ready to post", "color": "purple"},
                {"name": "Scheduled", "color": "blue"},
                {"name": "Posted", "color": "green"},
                {"name": "Rejected Agent Post", "color": "red"},
            ]
        }
    },
    "post-type": {
        "multi_select": {
            "options": [
                {"name": "single-thread", "color": "brown"},
                {"name": "multi-thread", "color": "green"},
                {"name": "article", "color": "default"},
            ]
        }
    },
    "Scheduled Time": {"date": {}},
    "Post Error": {"rich_text": {}},
    "Typefully Draft ID": {"rich_text": {}},
    "Date": {"created_time": {}},
}

# The canonical Company Research schema (deep-search skill). Same
# single-source-of-truth rule as TWEET_DRAFTS_SCHEMA above.
COMPANY_RESEARCH_SCHEMA = {
    "Name": {"title": {}},
    "Description": {"rich_text": {}},
    "URL": {"url": {}},
    "Query": {"rich_text": {}},
    "Source": {
        "multi_select": {
            "options": [
                {"name": "news", "color": "blue"},
                {"name": "funding", "color": "green"},
                {"name": "directory", "color": "yellow"},
            ]
        }
    },
    "Signal Date": {"date": {}},
    "Date": {"created_time": {}},
}


class NotionApiError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Notion API error {status_code}: {message}")
        self.status_code = status_code


def _plain_text(prop: dict | None) -> str:
    if not prop:
        return ""
    return "".join(part.get("plain_text", "") for part in prop.get("rich_text", []))


def _select_name(prop: dict | None) -> str | None:
    if not prop or not prop.get("select"):
        return None
    return prop["select"].get("name")


def _date_start(prop: dict | None) -> str | None:
    if not prop or not prop.get("date"):
        return None
    return prop["date"].get("start")


def _multi_select_first(prop: dict | None, default: str) -> str:
    if not prop:
        return default
    values = prop.get("multi_select", [])
    return values[0]["name"] if values else default


def _url_value(prop: dict | None) -> str | None:
    if not prop:
        return None
    return prop.get("url")


def _checkbox(prop: dict | None) -> bool:
    if not prop:
        return False
    return bool(prop.get("checkbox"))


def _plain_text_title(prop: dict | None) -> str:
    if not prop:
        return ""
    return "".join(part.get("plain_text", "") for part in prop.get("title", []))


def _row_from_page(page: dict) -> dict:
    props = page["properties"]
    return {
        "id": page["id"],
        "final_text": _plain_text(props.get("Final Text")),
        "title": _plain_text(props.get("Title")),
        "stage": _select_name(props.get("Stage")),
        "scheduled_time": _date_start(props.get("Scheduled Time")),
        "post_type": _multi_select_first(props.get("post-type"), "single-thread"),
        "typefully_draft_id": _plain_text(props.get("Typefully Draft ID")),
    }


class NotionClient:
    def __init__(self, token: str | None = None):
        self._token = token or get_notion_token()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def query_database(
        self, database_id: str, filter_: dict | None = None, sorts: list[dict] | None = None
    ) -> list[dict]:
        results: list[dict] = []
        body: dict = {}
        if filter_:
            body["filter"] = filter_
        if sorts:
            body["sorts"] = sorts
        cursor: str | None = None

        while True:
            if cursor:
                body["start_cursor"] = cursor
            response = requests.post(
                f"{BASE_URL}/databases/{database_id}/query",
                headers=self._headers(),
                json=body,
            )
            if not response.ok:
                raise NotionApiError(response.status_code, response.text)
            data = response.json()
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data["next_cursor"]

        return results

    def get_rows_by_stage(self, database_id: str, stage: str) -> list[dict]:
        pages = self.query_database(
            database_id,
            filter_={"property": "Stage", "select": {"equals": stage}},
        )
        return [_row_from_page(page) for page in pages]

    def get_all_rows(self, database_id: str) -> list[dict]:
        pages = self.query_database(database_id)
        return [_row_from_page(page) for page in pages]

    # --- Response Calendar (discovered posts to engage with) ---
    #
    # `Status` is the single lifecycle column: New -> Reviewed -> Ready to post
    # -> Posted, with Stale and the two Rejected values as exits. `Posted` is
    # also the positive engagement signal the curation skill learns from.

    def get_response_calendar_rows(
        self, database_id: str, status: str | None = None
    ) -> list[dict]:
        filter_ = (
            {"property": "Status", "select": {"equals": status}} if status else None
        )
        rows = []
        for page in self.query_database(database_id, filter_=filter_):
            props = page["properties"]
            rows.append(
                {
                    "id": page["id"],
                    "text": _plain_text_title(props.get("Original Tweet Text")),
                    "url": _url_value(props.get("Original Tweet URL")),
                    "review_status": _select_name(props.get("Status")),
                    "selected": _select_name(props.get("Selected")),
                    "retweet_message": _plain_text(props.get("Retweet Message")),
                    "scheduled_time": _date_start(props.get("Scheduled Time")),
                    "typefully_draft_id": _plain_text(props.get("Typefully Draft ID")),
                    "replies": {
                        "Reply 1": _plain_text(props.get("Reply 1")),
                        "Reply 2": _plain_text(props.get("Reply 2")),
                        "Reply 3": _plain_text(props.get("Reply 3")),
                        "Self-Written Reply": _plain_text(
                            props.get("Self-Written Reply")
                        ),
                    },
                }
            )
        return rows

    @staticmethod
    def selected_reply_text(row: dict) -> str:
        """The reply the author actually chose, or "" for Retweet (whose text
        lives in `Retweet Message`, not a reply field)."""
        return row["replies"].get(row.get("selected") or "", "")

    def create_discovery_row(
        self,
        database_id: str,
        text: str,
        tweet_url: str,
        tweet_date: str | None = None,
    ) -> None:
        properties = {
            "Original Tweet Text": {"title": [{"text": {"content": text[:2000]}}]},
            "Original Tweet URL": {"url": tweet_url},
            "Status": {"select": {"name": "New"}},
            "Added Date": {"date": {"start": date.today().isoformat()}},
        }
        if tweet_date:
            properties["Original Tweet Date"] = {"date": {"start": tweet_date}}

        response = requests.post(
            f"{BASE_URL}/pages",
            headers=self._headers(),
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
        if not response.ok:
            raise NotionApiError(response.status_code, response.text)

    # --- Discovery Database (accounts worth tracking) ---

    def get_discovery_rows(self, database_id: str) -> list[dict]:
        rows = []
        for page in self.query_database(database_id):
            props = page["properties"]
            rows.append(
                {
                    "id": page["id"],
                    "name": _plain_text_title(props.get("Name")),
                    "username": _plain_text(props.get("Username")),
                    "review_status": _select_name(props.get("Review Status")),
                }
            )
        return rows

    def create_discovery_account_row(
        self,
        database_id: str,
        name: str,
        username: str,
        bio: str = "",
        follower_count: int | None = None,
        matched_query: str = "",
        sample_tweet: str = "",
        sample_tweet_url: str = "",
    ) -> None:
        from datetime import datetime, timezone

        properties: dict = {
            "Name": {"title": [{"text": {"content": (name or username)[:200]}}]},
            "Username": {"rich_text": [{"text": {"content": username}}]},
            "Profile URL": {"url": f"https://x.com/{username}"},
            "Review Status": {"select": {"name": "New"}},
            "Discovery Date": {
                "date": {"start": datetime.now(timezone.utc).date().isoformat()}
            },
        }
        if bio:
            properties["Bio"] = {"rich_text": [{"text": {"content": bio[:2000]}}]}
        if follower_count is not None:
            properties["Follower Count"] = {"number": follower_count}
        if matched_query:
            properties["Matched Query"] = {
                "rich_text": [{"text": {"content": matched_query[:2000]}}]
            }
        if sample_tweet:
            properties["Sample Tweet"] = {
                "rich_text": [{"text": {"content": sample_tweet[:2000]}}]
            }
        if sample_tweet_url:
            properties["Sample Tweet URL"] = {"url": sample_tweet_url}

        response = requests.post(
            f"{BASE_URL}/pages",
            headers=self._headers(),
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
        if not response.ok:
            raise NotionApiError(response.status_code, response.text)

    # --- Company Research (deep-search skill) ---

    def create_company_research_row(
        self,
        database_id: str,
        name: str,
        description: str,
        url: str,
        query: str,
        source: str,
        signal_date: str | None = None,
    ) -> None:
        properties: dict = {
            "Name": {"title": [{"text": {"content": name[:200]}}]},
            "Description": {"rich_text": [{"text": {"content": description[:2000]}}]},
            "URL": {"url": url},
            "Query": {"rich_text": [{"text": {"content": query[:2000]}}]},
            "Source": {"multi_select": [{"name": source}]},
        }
        if signal_date:
            properties["Signal Date"] = {"date": {"start": signal_date}}

        response = requests.post(
            f"{BASE_URL}/pages",
            headers=self._headers(),
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
        if not response.ok:
            raise NotionApiError(response.status_code, response.text)

    def create_database(
        self,
        parent_page_id: str,
        title: str = "Tweet Drafts",
        schema: dict | None = None,
    ) -> str:
        """Create a database under an existing page (defaults to the Tweet
        Drafts schema). Returns the new database id. The integration must be
        shared with the parent page."""
        response = requests.post(
            f"{BASE_URL}/databases",
            headers=self._headers(),
            json={
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "is_inline": True,
                "properties": schema or TWEET_DRAFTS_SCHEMA,
            },
        )
        if not response.ok:
            raise NotionApiError(response.status_code, response.text)
        return response.json()["id"]

    def create_posted_row(self, database_id: str, title: str, final_text: str) -> None:
        response = requests.post(
            f"{BASE_URL}/pages",
            headers=self._headers(),
            json={
                "parent": {"database_id": database_id},
                "properties": {
                    "Post Info": {
                        "title": [{"text": {"content": title[:200]}}]
                    },
                    "Final Text": {
                        "rich_text": [{"text": {"content": final_text[:2000]}}]
                    },
                    "Stage": {"select": {"name": "Posted"}},
                },
            },
        )
        if not response.ok:
            raise NotionApiError(response.status_code, response.text)

    # --- Paper outreach (papers awaiting author outreach) ---

    def get_paper_outreach_rows(self, database_id: str, status: str | None = None) -> list[dict]:
        filter_ = None
        if status == "__empty__":
            filter_ = {"property": "Status", "select": {"is_empty": True}}
        elif status:
            filter_ = {"property": "Status", "select": {"equals": status}}

        rows = []
        for page in self.query_database(database_id, filter_=filter_):
            props = page["properties"]
            rows.append(
                {
                    "id": page["id"],
                    "name": _plain_text_title(props.get("Paper Name")),
                    "link": _url_value(props.get("Paper link")),
                    "notes": _plain_text(props.get("Notes")),
                    "status": _select_name(props.get("Status")),
                    "blurb": _plain_text(props.get("Blurb")),
                }
            )
        return rows

    def set_paper_status(self, page_id: str, status: str) -> None:
        self.update_page(page_id, {"Status": {"select": {"name": status}}})

    def set_paper_name(self, page_id: str, name: str) -> None:
        """Backfills the title from the resolved paper — rows staged with
        only a link have no title, which also leaves the `Paper` relation
        column blank on every linked Paper Authors row (Notion displays a
        relation by the related page's title)."""
        self.update_page(page_id, {"Paper Name": {"title": [{"text": {"content": name[:2000]}}]}})

    def set_paper_blurb(self, page_id: str, blurb: str) -> None:
        self.update_page(page_id, {"Blurb": {"rich_text": [{"text": {"content": blurb[:2000]}}]}})

    # --- Paper authors (one row per author, linked to a paper) ---

    def create_paper_author_row(
        self,
        database_id: str,
        paper_page_id: str,
        name: str,
        affiliation: str = "",
        role: str = "Co-author",
        email: str = "",
        x_handle: str = "",
        linkedin: str = "",
        status: str = "Needs Handles",
    ) -> str:
        properties: dict = {
            "Author": {"title": [{"text": {"content": name[:200]}}]},
            "Paper": {"relation": [{"id": paper_page_id}]},
            "Role": {"select": {"name": role}},
            "Status": {"select": {"name": status}},
        }
        if affiliation:
            properties["Affiliation"] = {"rich_text": [{"text": {"content": affiliation[:2000]}}]}
        if email:
            properties["Email"] = {"email": email}
        if x_handle:
            properties["X Handle"] = {"rich_text": [{"text": {"content": x_handle}}]}
        if linkedin:
            properties["LinkedIn"] = {"url": linkedin}

        response = requests.post(
            f"{BASE_URL}/pages",
            headers=self._headers(),
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
        if not response.ok:
            raise NotionApiError(response.status_code, response.text)
        return response.json()["id"]

    def get_paper_author_rows(self, database_id: str, paper_page_id: str | None = None) -> list[dict]:
        filter_ = None
        if paper_page_id:
            filter_ = {"property": "Paper", "relation": {"contains": paper_page_id}}

        rows = []
        for page in self.query_database(database_id, filter_=filter_):
            props = page["properties"]
            rows.append(
                {
                    "id": page["id"],
                    "name": _plain_text_title(props.get("Author")),
                    "affiliation": _plain_text(props.get("Affiliation")),
                    "role": _select_name(props.get("Role")),
                    "email": (props.get("Email") or {}).get("email"),
                    "x_handle": _plain_text(props.get("X Handle")),
                    "linkedin": _url_value(props.get("LinkedIn")),
                    "selected": _checkbox(props.get("Selected")),
                    "send_via": _select_name(props.get("Send Via")),
                    "subject": _plain_text(props.get("Subject")),
                    "message": _plain_text(props.get("Message")),
                    "linkedin_note": _plain_text(props.get("LinkedIn Note")),
                    "post_error": _plain_text(props.get("Post Error")),
                    "status": _select_name(props.get("Status")),
                    "scheduled_time": _date_start(props.get("Scheduled Time")),
                    "first_sent": _date_start(props.get("First Sent")),
                    "last_sent": _date_start(props.get("Last Sent")),
                    "thread_ref": _plain_text(props.get("Thread Ref")),
                }
            )
        return rows

    def set_author_contact(
        self,
        page_id: str,
        email: str = "",
        x_handle: str = "",
        linkedin: str = "",
        affiliation: str = "",
        status: str | None = None,
    ) -> None:
        """Fill contact fields found by research (research_authors.py). Only
        non-empty values are written, so existing fields are never cleared."""
        properties: dict = {}
        if email:
            properties["Email"] = {"email": email}
        if x_handle:
            properties["X Handle"] = {"rich_text": [{"text": {"content": x_handle}}]}
        if linkedin:
            properties["LinkedIn"] = {"url": linkedin}
        if affiliation:
            properties["Affiliation"] = {"rich_text": [{"text": {"content": affiliation[:2000]}}]}
        if status:
            properties["Status"] = {"select": {"name": status}}
        if properties:
            self.update_page(page_id, properties)

    def get_sent_messages(self, database_id: str, limit: int = 5) -> list[str]:
        """Most recently sent outreach messages — used as tone examples so new
        drafts sound like what the user actually sends, not a generic default."""
        pages = self.query_database(
            database_id,
            filter_={"property": "Status", "select": {"equals": "Sent"}},
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
        )
        messages = []
        for page in pages[:limit]:
            text = _plain_text(page["properties"].get("Message"))
            if text:
                messages.append(text)
        return messages

    def set_author_message(
        self,
        page_id: str,
        message: str,
        status: str,
        send_via: str | None = None,
        subject: str | None = None,
        post_error: str | None = None,
    ) -> None:
        """`subject` is Email-only — a channel with no subject line (X,
        LinkedIn) simply never passes one, and the Subject column stays
        blank for that row. `send_via` is only ever passed by a human
        explicitly picking a channel elsewhere in Notion — drafting never
        sets it. `post_error` records what went wrong on a send attempt
        (LinkedIn's lack of a send API, a failed Gmail/X call, etc.) for a
        human to read directly in Notion; pass `""` to clear a stale error
        after a later successful send."""
        properties: dict = {
            "Message": {"rich_text": [{"text": {"content": message[:2000]}}]},
            "Status": {"select": {"name": status}},
        }
        if send_via:
            properties["Send Via"] = {"select": {"name": send_via}}
        if subject is not None:
            properties["Subject"] = {"rich_text": [{"text": {"content": subject[:2000]}}]}
        if post_error is not None:
            properties["Post Error"] = {"rich_text": [{"text": {"content": post_error[:2000]}}]}
        self.update_page(page_id, properties)

    # --- Follow-ups (send_followups.py) ---

    def record_initial_send(self, page_id: str, thread_ref: str | None, sent_date: str) -> None:
        """Called once, right after the initial message actually sends.
        `thread_ref` is the Gmail thread id for Email (used to reply within
        the same thread and to check it for a reply); left unset for X, since
        the participant id is cheap to re-resolve from the handle on demand."""
        properties: dict = {
            "First Sent": {"date": {"start": sent_date}},
            "Last Sent": {"date": {"start": sent_date}},
        }
        if thread_ref:
            properties["Thread Ref"] = {"rich_text": [{"text": {"content": thread_ref[:2000]}}]}
        self.update_page(page_id, properties)

    def record_followup(self, page_id: str, followup_number: int, message: str, status: str, sent_date: str) -> None:
        self.update_page(
            page_id,
            {
                f"Followup {followup_number} Message": {"rich_text": [{"text": {"content": message[:2000]}}]},
                "Status": {"select": {"name": status}},
                "Last Sent": {"date": {"start": sent_date}},
            },
        )

    def set_author_status(self, page_id: str, status: str) -> None:
        self.update_page(page_id, {"Status": {"select": {"name": status}}})

    def set_author_linkedin_note(
        self, page_id: str, note: str, status: str | None = None, post_error: str | None = None
    ) -> None:
        """Separate from set_author_message — LinkedIn's connection-request
        note is a distinct, 200-char-capped field, not a rename/reuse of
        Message (which stays Email/X's, and is what other channels' Status
        transitions key off)."""
        properties: dict = {"LinkedIn Note": {"rich_text": [{"text": {"content": note[:2000]}}]}}
        if status:
            properties["Status"] = {"select": {"name": status}}
        if post_error is not None:
            properties["Post Error"] = {"rich_text": [{"text": {"content": post_error[:2000]}}]}
        self.update_page(page_id, properties)

    def update_page(self, page_id: str, properties: dict) -> None:
        response = requests.patch(
            f"{BASE_URL}/pages/{page_id}",
            headers=self._headers(),
            json={"properties": properties},
        )
        if not response.ok:
            raise NotionApiError(response.status_code, response.text)

    def set_stage(self, page_id: str, stage: str) -> None:
        self.update_page(page_id, {"Stage": {"select": {"name": stage}}})

    def set_response_status(self, page_id: str, status: str) -> None:
        self.update_page(page_id, {"Status": {"select": {"name": status}}})

    def set_typefully_draft_id(self, page_id: str, draft_id: str) -> None:
        """Same property name/type on both Tweet Drafts and Response
        Calendar, so one method covers both."""
        self.update_page(
            page_id,
            {"Typefully Draft ID": {"rich_text": [{"text": {"content": draft_id}}]}},
        )

    def mark_posted(self, page_id: str) -> None:
        self.update_page(
            page_id,
            {
                "Stage": {"select": {"name": "Posted"}},
                "Post Error": {"rich_text": []},
            },
        )

    def set_post_error(self, page_id: str, message: str) -> None:
        self.update_page(
            page_id,
            {"Post Error": {"rich_text": [{"text": {"content": message[:2000]}}]}},
        )

    def mark_response_row_posted(self, page_id: str) -> None:
        self.update_page(
            page_id,
            {
                "Status": {"select": {"name": "Posted"}},
                "Post Error": {"rich_text": []},
            },
        )
