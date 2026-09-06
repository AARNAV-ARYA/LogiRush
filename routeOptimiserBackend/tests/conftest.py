"""Test-wide invariants that have to hold before any module is imported.

Rainfall is live in normal operation: the platform fetches real precipitation from
Open-Meteo and substitutes it for the shipped snapshot. That is right for a running system
and wrong for a test suite, for two reasons that both bite:

  * The numbers would be this afternoon's weather in Meghalaya. A test asserting a corridor's
    accessibility score would pass or fail depending on the monsoon, which is not a test.
  * Every run would make a network request, so the suite would be slow offline and flaky on
    CI for reasons that have nothing to do with the code being tested.

So the suite is pinned to the snapshot. The live path has its own tests, which stub the HTTP
layer rather than reaching the internet — see test_live_weather.py.

This must run before `src.data_processing.weather_provider` is first imported, because
LIVE_ENABLED is read at import time. conftest.py is imported before test modules, which is
exactly the hook that guarantees it.
"""

import os

os.environ.setdefault("NER_LIVE_WEATHER", "0")
os.environ.setdefault("NER_DISABLE_WARMUP", "1")
