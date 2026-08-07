"""Run the local Research Outreach workspace."""

import os

import uvicorn


if __name__ == "__main__":
    # Port 8000 is often taken by another local project; override with PORT.
    uvicorn.run(
        "gtm_agent.research_api:app",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
