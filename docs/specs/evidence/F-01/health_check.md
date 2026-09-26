| Step | Endpoint | Status Code |
|---|---|---|
| extract | GET /api/brain | 200 |
| 404 | GET /api/soul | 404 |
| (LLM mocked) | POST /api/soul/generate | 200 |
| 200 | GET /api/soul | 200 |
| (regenerate) | POST /api/soul/generate | 200 |
