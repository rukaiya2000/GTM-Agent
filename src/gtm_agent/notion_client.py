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

    def query_database(self, database_id: str, filter_: dict | None = None) -> list[dict]:
        results: list[dict] = []
        body: dict = {"filter": filter_} if filter_ else {}
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
    # Careful: this database has TWO status properties whose names differ only by
    # case. `Status` (capital) is the review workflow (New/Reviewed/Stale/...).
    # `status` (lowercase) is the engagement signal (Commented/Rejected/
    # not-commented) that the curation skill learns from. Notion matches property
    # names exactly, so mixing them up fails silently.

    def get_response_calendar_rows(self, database_id: str) -> list[dict]:
        rows = []
        for page in self.query_database(database_id):
            props = page["properties"]
            rows.append(
                {
                    "id": page["id"],
                    "text": _plain_text_title(props.get("Original Tweet Text")),
                    "url": _url_value(props.get("Original Tweet URL")),
                    "review_status": _select_name(props.get("Status")),
                    "engagement_status": _select_name(props.get("status")),
                    "selected": _select_name(props.get("Selected")),
                    "posted": _checkbox(props.get("Posted")),
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
        """The reply the author actually chose, or "" if none/Like-RT (which has
        no text of its own)."""
        return row["replies"].get(row.get("selected") or "", "")

    def create_discovery_row(
        self,
        database_id: str,
        text: str,
        tweet_url: str,
        tweet_date: str | None = None,
        source: str = "discovery",
    ) -> None:
        properties = {
            "Original Tweet Text": {"title": [{"text": {"content": text[:2000]}}]},
            "Original Tweet URL": {"url": tweet_url},
            "Status": {"select": {"name": "New"}},
            "Source": {"select": {"name": source}},
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

    def create_database(
        self, parent_page_id: str, title: str = "Tweet Drafts"
    ) -> str:
        """Create the Tweet Drafts database under an existing page. Returns the
        new database id. The integration must be shared with the parent page."""
        response = requests.post(
            f"{BASE_URL}/databases",
            headers=self._headers(),
            json={
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "is_inline": True,
                "properties": TWEET_DRAFTS_SCHEMA,
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
