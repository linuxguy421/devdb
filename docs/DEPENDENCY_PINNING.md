# Dependency Pinning

DevDB currently declares minimum dependency versions in `requirements.txt`. The exact versions used by the known-good Docker build should be captured before converting the production dependency set to exact pins.

Because dependency resolution is part of the build, do not invent or manually guess exact versions for a release lock file.

From the known-good application image, capture the resolved set with:

```bash
docker compose run --rm app python -m pip freeze > requirements.lock
```

Review the generated file, commit it with the release, and have production builds install the lock file rather than the open-ended requirements file.

The lock should be regenerated deliberately when dependencies are upgraded, followed by the full Docker test suite.
