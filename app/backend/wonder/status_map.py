"""App status vocabulary <-> Jira status names (used pushing to and syncing from Jira)."""

APP_TO_JIRA = {"Open": "To Do", "In Progress": "In Progress", "In Review": "In Review", "Resolved": "Done"}
JIRA_TO_APP = {"To Do": "Open", "In Progress": "In Progress", "In Review": "In Review", "Done": "Resolved"}

# A ticket is closed once it reaches one of these (app + Jira terms).
CLOSED_STATES = ("Resolved", "Closed", "Auto-Closed", "Done")
