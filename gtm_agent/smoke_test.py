import sys

from gtm_agent.config import ConfigError
from gtm_agent.trajectory import run_main
from gtm_agent.x_client import XApiError, XClient


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else "X"

    try:
        client = XClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        user = client.get_user_by_username(username)
    except XApiError as e:
        print(f"Request failed: {e}")
        return 1

    print(user)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_main(main, __file__))
