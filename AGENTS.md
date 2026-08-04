# Agent Instructions

## Starting and Stopping the App

- To start the backend or frontend, always run `./up.sh`.
- To stop the backend or frontend, always run `./down.sh`.
- Do not start uvicorn, the frontend dev server, or any related process with ad-hoc commands instead of `up.sh`, and do not stop them with ad-hoc `pkill`/kill commands instead of `down.sh`.
