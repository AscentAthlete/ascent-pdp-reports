# Ascent PDP Connected Report Generator

This version is designed for one-click athlete reporting:

1. Search athlete
2. Choose PDP package length and end date
3. Pull data from connected systems
4. Generate/download the final PDF

## Current integration status

### Hawkin Dynamics
Live connector included. Requires an organization API refresh token.

### TrackMan
Connector framework included. TrackMan Data API is a paid/optional add-on and requires credentials plus the exact production endpoints/schema supplied to your organization. Put those values in Streamlit Secrets.

### HitTrax
Connector framework included. Requires vendor-provided programmatic/API access and documentation.

### Blast Motion
Connector framework included. Requires vendor-provided programmatic/API access and documentation.

## GitHub upload

Upload all files/folders in this ZIP to the root of your GitHub repository:

- app.py
- requirements.txt
- connectors/
- README.md
- .streamlit/secrets.example.toml

Do NOT upload real secrets.

## Streamlit Secrets

In Streamlit Cloud:
Manage app -> Settings -> Secrets

Copy the fields from `.streamlit/secrets.example.toml` and fill in only the credentials you have.

## Security

Never commit usernames, passwords, refresh tokens, or API keys to GitHub.
