# H7-02 evidence (literal output)

Commands run on the branch after the code commit, from a clean tree:

    python -m pytest -q -m "not e2e" -p no:cacheprovider   -> pytest_output.txt
    node tests/<each>.test.js (8 files)                     -> node_output.txt
    ruff check <touched .py>                                -> ruff_output.txt
    node --check <touched .js>                              -> node_check_output.txt
    git status --short (excluding this evidence dir)        -> git_status_after_suite.txt

Environment: Linux, Python 3.11, no proxy env vars for the pytest run
(`env -u HTTPS_PROXY ...`), `pytest-mock`/`pytest-asyncio`/`playwright` installed.

Remaining failures are listed in the PR description.
