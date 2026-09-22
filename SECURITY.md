# Security

Audio Rescue runs locally on `127.0.0.1` and handles temporary provider access tokens only for downloading files your account is permitted to access.

- Never report a bug by pasting an actual access token, refresh token, cookie, signed private URL or unredacted request headers.
- Do not commit downloaded songs, integrity manifests, credentials, `.env` files or personal logs.
- If credentials are exposed, revoke the session if possible and sign in again.
- Only paste tokens into a local instance of Audio Rescue that **you** started, and review browser-console scripts before running them.

For potentially sensitive vulnerabilities, contact the repository maintainer privately through their GitHub profile; do not paste exploitable credentials in public issues.

Audio Rescue is independent of the audio services mentioned in its documentation.
