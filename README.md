# ArtificersManual

Lightweight D&D-centric site you can run locally and share with external users on your network.

## Run locally

```bash
python3 /home/runner/work/ArtificersManual/ArtificersManual/serve.py --port 8080
```

The server binds to `0.0.0.0` by default so other devices can connect using:

`http://<your-local-ip>:8080`

## Notes

- Content is in `/home/runner/work/ArtificersManual/ArtificersManual/site/index.html`
- Use `--host` and `--port` flags to customize bind address and port.
