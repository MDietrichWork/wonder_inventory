"""One-off Jira admin helpers (sandbox/prod setup). Run: python -m wonder.jira_admin

Creates the owner-team groups from reference.JIRA_TEAM_MAP and adds each group's default
assignee (or the JIRA_EMAIL account) as a member. Safe to re-run (existing groups/members
are left as-is).
"""
import warnings; warnings.filterwarnings("ignore")  # noqa: E702
import httpx

from .config import settings
from . import reference


def _client():
    return httpx.Client(auth=httpx.BasicAuth(settings.jira_email, settings.jira_api_token),
                        headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=30)


def setup_groups():
    c = _client()
    base = settings.jira_base_url.rstrip("/")
    my_acct = c.get(base + "/rest/api/3/myself").json()["accountId"]
    for team, info in reference.JIRA_TEAM_MAP.items():
        g = info["group"]
        r = c.post(base + "/rest/api/3/group", json={"name": g})
        status = "created" if r.status_code in (200, 201) else ("exists" if r.status_code == 400 else "ERR %s" % r.status_code)
        acct = my_acct
        if info.get("assignee_email"):
            us = c.get(base + "/rest/api/3/user/search", params={"query": info["assignee_email"]}).json()
            if us:
                acct = us[0]["accountId"]
        am = c.post(base + "/rest/api/3/group/user", params={"groupname": g}, json={"accountId": acct})
        member = "added" if am.status_code in (200, 201) else ("already member" if am.status_code == 400 else "ERR %s" % am.status_code)
        print("  %-20s [group %s] [member %s]" % (g, status, member))


if __name__ == "__main__":
    print("Setting up Jira owner-team groups on", settings.jira_base_url)
    setup_groups()
    print("Done.")
