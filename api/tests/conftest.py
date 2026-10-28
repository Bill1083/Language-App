import os
from pathlib import Path

# Point the app at the curriculum both inside the test image and in a local checkout.
_in_image = Path("/app/curriculum")
os.environ.setdefault("CURRICULUM_DIR", str(_in_image if _in_image.exists()
                                            else Path(__file__).resolve().parents[2] / "curriculum"))
os.environ.setdefault("DATA_DIR", "/tmp/parlo-test")
os.environ.setdefault("APP_SECRET", "test")
